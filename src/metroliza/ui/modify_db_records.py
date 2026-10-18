"""Model/view building blocks for the Modify Database record tables (#1118).

The report and measurement record tables can hold hundreds of thousands of rows. Rows are kept as
plain tuples inside a :class:`RecordTableModel` (no per-cell ``QTableWidgetItem``), edits are tracked
as a sparse ``{row: {column: text}}`` dict on top of the untouched original values, and filtering is a
substring test against one precomputed lowercase haystack per row. :func:`load_record_rows` builds
those structures from batched SQL fetches and is safe to run in a worker thread
(:class:`RecordLoadThread`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QCoreApplication, QModelIndex, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QTableView, QWidget

from metroliza.reports.db import iter_sql_query_batches


FIELD_SEPARATOR = "\x1f"
FETCH_BATCH_SIZE = 5000
FILTER_DEBOUNCE_MS = 250

_DISPLAY_ROLES = (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole)


def display_value(value: Any) -> str:
    """Return the text a record cell shows for a stored value (``NULL`` is empty text)."""

    return "" if value is None else str(value)


def row_haystack(values: Sequence[Any]) -> str:
    """Return the lowercase searchable text of one record row."""

    return FIELD_SEPARATOR.join(display_value(value) for value in values).lower()


@dataclass(frozen=True)
class RecordRows:
    """Rows aligned with the record specs plus their precomputed filter haystack."""

    rows: list[tuple[Any, ...]]
    haystack: list[str]


class _RecordRowBuilder:
    """Align fetched batches with the record specs and keep memory small."""

    def __init__(self, specs: Sequence[dict[str, Any]]) -> None:
        self._fields = [spec["field"].lower() for spec in specs]
        # Repeated text (section names, labels, status codes) is stored once per column. Key and float
        # columns are skipped: ids are unique and floats would only grow the lookup tables.
        self._interned: dict[int, dict[Any, Any]] = {
            index: {}
            for index, spec in enumerate(specs)
            if not spec.get("key") and spec.get("value_type") != "float"
        }
        self._positions: list[int | None] | None = None
        self.rows: list[tuple[Any, ...]] = []
        self.haystack: list[str] = []

    def add_batch(self, columns: Sequence[str], batch_rows: Sequence[tuple[Any, ...]]) -> None:
        if not batch_rows:
            return
        if self._positions is None:
            index_by_name = {str(name).lower(): index for index, name in enumerate(columns)}
            self._positions = [index_by_name.get(field) for field in self._fields]

        fetched = list(zip(*batch_rows))
        missing = (None,) * len(batch_rows)
        aligned = []
        for column_index, position in enumerate(self._positions):
            column = fetched[position] if position is not None else missing
            if column_index in self._interned:
                intern = self._interned[column_index].setdefault
                column = tuple([intern(value, value) if value.__class__ is str else value for value in column])
            aligned.append(column)

        self.rows.extend(zip(*aligned))
        displayed = [
            ["" if value is None else value if value.__class__ is str else str(value) for value in column]
            for column in aligned
        ]
        self.haystack.extend(map(str.lower, map(FIELD_SEPARATOR.join, zip(*displayed))))


def load_record_rows(
    db_file: str,
    query: str,
    specs: Sequence[dict[str, Any]],
    *,
    should_cancel: Callable[[], bool] | None = None,
    batch_size: int = FETCH_BATCH_SIZE,
) -> RecordRows | None:
    """Fetch ``query`` in batches and build model rows; return ``None`` when cancelled."""

    builder = _RecordRowBuilder(specs)
    batches = iter_sql_query_batches(db_file, query, batch_size=batch_size, should_cancel=should_cancel)
    try:
        for batch in batches:
            if should_cancel is not None and should_cancel():
                return None
            builder.add_batch(batch.columns, batch.rows)
    finally:
        batches.close()
    if should_cancel is not None and should_cancel():
        return None
    return RecordRows(builder.rows, builder.haystack)


class RecordTableModel(QAbstractTableModel):
    """Editable table model over immutable row tuples with a sparse edit overlay."""

    def __init__(
        self,
        specs: Sequence[dict[str, Any]] = (),
        rows: Sequence[tuple[Any, ...]] = (),
        haystack: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._specs = list(specs)
        self._rows = rows if isinstance(rows, list) else list(rows)
        self._haystack = haystack
        self._edits: dict[int, dict[int, str]] = {}
        self._needle = ""
        self._visible: list[int] | None = None

    # -- Qt model interface ---------------------------------------------------------
    @property
    def specs(self) -> list[dict[str, Any]]:
        return self._specs

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008 - Qt signature
        if parent.isValid():
            return 0
        return len(self._rows) if self._visible is None else len(self._visible)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008 - Qt signature
        return 0 if parent.isValid() else len(self._specs)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in _DISPLAY_ROLES:
            return self.text_at(self.source_row(index.row()), index.column())
        if role == Qt.ItemDataRole.UserRole:
            return self.original_value(self.source_row(index.row()), index.column())
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if index.isValid() and self._specs[index.column()].get("editable"):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._specs[section]["label"] if 0 <= section < len(self._specs) else None
        # Row numbers follow the unfiltered table, as hidden rows kept their numbers before.
        source = self.source_row(section) if 0 <= section < self.rowCount() else section
        return str(source + 1)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        column = index.column()
        if not self._specs[column].get("editable"):
            return False
        source = self.source_row(index.row())
        text = str(value)
        if text == display_value(self._rows[source][column]):
            row_edits = self._edits.get(source)
            if row_edits is not None:
                row_edits.pop(column, None)
                if not row_edits:
                    del self._edits[source]
        else:
            self._edits.setdefault(source, {})[column] = text
        if self._haystack is not None:
            self._haystack[source] = self._current_haystack(source)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
        return True

    # -- row identity ---------------------------------------------------------------
    @property
    def total_row_count(self) -> int:
        return len(self._rows)

    def source_row(self, row: int) -> int:
        """Map a (possibly filtered) view row to the index of the loaded row."""

        return row if self._visible is None else self._visible[row]

    # -- cell text and originals ----------------------------------------------------
    def text_at(self, source_row: int, column: int) -> str:
        row_edits = self._edits.get(source_row)
        if row_edits is not None and column in row_edits:
            return row_edits[column]
        return display_value(self._rows[source_row][column])

    def original_value(self, source_row: int, column: int) -> Any:
        return self._rows[source_row][column]

    def original_text(self, source_row: int, column: int) -> str:
        return display_value(self._rows[source_row][column])

    # -- edits ----------------------------------------------------------------------
    @property
    def has_edits(self) -> bool:
        return bool(self._edits)

    def edited_rows(self) -> Iterator[tuple[int, dict[int, str]]]:
        """Yield ``(source_row, {column: new_text})`` for edited rows in row order."""

        for source_row in sorted(self._edits):
            yield source_row, dict(sorted(self._edits[source_row].items()))

    def first_rows_by_key(
        self, key_column: int, wanted: set[int], coerce: Callable[[str], int | None]
    ) -> dict[int, int]:
        """Return the first loaded row holding each wanted record key."""

        found: dict[int, int] = {}
        for source_row, row in enumerate(self._rows):
            record_id = coerce(display_value(row[key_column]))
            if record_id in wanted and record_id not in found:
                found[record_id] = source_row
                if len(found) == len(wanted):
                    break
        return found

    # -- filtering ------------------------------------------------------------------
    @property
    def filter_text(self) -> str:
        return self._needle

    def set_filter_text(self, text: str) -> None:
        """Show only rows whose current text contains ``text`` (case-insensitive)."""

        needle = str(text).lower()
        if needle == self._needle:
            return
        matches = self._matching_rows(needle) if needle else None
        self.beginResetModel()
        self._needle = needle
        self._visible = matches
        self.endResetModel()

    def _matching_rows(self, needle: str) -> list[int]:
        if FIELD_SEPARATOR in needle:
            return [row for row in range(len(self._rows)) if self._row_cells_contain(row, needle)]
        if self._haystack is None:
            self._haystack = [self._current_haystack(row) for row in range(len(self._rows))]
        return [row for row, text in enumerate(self._haystack) if needle in text]

    def _row_cells_contain(self, source_row: int, needle: str) -> bool:
        return any(needle in self.text_at(source_row, column).lower() for column in range(len(self._specs)))

    def _current_haystack(self, source_row: int) -> str:
        return row_haystack([self.text_at(source_row, column) for column in range(len(self._specs))])


class RecordTableView(QTableView):
    """``QTableView`` that exposes the small ``QTableWidget`` surface the dialog relies on."""

    cellPressed = pyqtSignal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.pressed.connect(self._emit_cell_pressed)

    def _emit_cell_pressed(self, index) -> None:
        self.cellPressed.emit(index.row(), index.column())

    def set_record_model(self, model: RecordTableModel) -> None:
        """Install ``model`` (owned by the view) and release the previous one."""

        previous = self.model()
        model.setParent(self)
        self.setModel(model)
        if previous is not None and previous is not model:
            previous.deleteLater()

    def rowCount(self) -> int:
        model = self.model()
        return model.rowCount() if model is not None else 0

    def columnCount(self) -> int:
        model = self.model()
        return model.columnCount() if model is not None else 0

    def currentRow(self) -> int:
        index = self.currentIndex()
        return index.row() if index.isValid() else -1

    def setCurrentCell(self, row: int, column: int) -> None:
        model = self.model()
        if model is not None:
            self.setCurrentIndex(model.index(row, column))

    def try_apply_filter(self, text: str) -> bool:
        """Defer model resets until the user accepts or cancels the delegate's cell edit."""

        if self.state() == self.State.EditingState:
            return False
        model = self.model()
        if model is not None:
            model.set_filter_text(text)
        return True


class RecordBusyBanner(QWidget):
    """Compact "loading" row with an indeterminate progress bar."""

    def __init__(self, text: str = "Loading records...", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(text))
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setMaximumHeight(10)
        layout.addWidget(bar, 1)
        self.setVisible(False)


class RecordLoadThread(QThread):
    """Fetch and prepare one record table without blocking the GUI thread."""

    loaded = pyqtSignal(str, int, object)
    failed = pyqtSignal(str, int, object)

    def __init__(self, kind: str, generation: int, db_file: str, query: str, specs: Sequence[dict[str, Any]]):
        super().__init__()
        self._kind = kind
        self._generation = generation
        self._db_file = db_file
        self._query = query
        self._specs = list(specs)

    def run(self) -> None:
        try:
            rows = load_record_rows(
                self._db_file,
                self._query,
                self._specs,
                should_cancel=self.isInterruptionRequested,
            )
        except Exception as exc:  # worker boundary: report instead of killing the thread
            self.failed.emit(self._kind, self._generation, exc)
            return
        if rows is not None:
            self.loaded.emit(self._kind, self._generation, rows)


_ACTIVE_LOAD_THREADS: set[RecordLoadThread] = set()
_QUIT_HOOK_APPS: list[Any] = []


def cancel_load_thread(thread: RecordLoadThread | None, *, wait_ms: int = 3000) -> None:
    """Cancel SQL and join the worker before its owner or the application can shut down.

    Normal SQLite execution and lock waits cooperate promptly. A SQLite extension may be
    uninterruptible: if it exceeds the normal wait, defer shutdown until it returns rather
    than allowing interpreter teardown with a live QThread.
    """

    if thread is None:
        return
    thread.requestInterruption()
    if not thread.wait(wait_ms):
        thread.wait()


def shutdown_load_threads() -> None:
    """Stop every running record fetch (application exit must not destroy a running QThread)."""

    threads = list(_ACTIVE_LOAD_THREADS)
    for thread in threads:
        thread.requestInterruption()
    for thread in threads:
        cancel_load_thread(thread)


def start_load_thread(thread: RecordLoadThread) -> None:
    """Start ``thread`` and keep it alive until it has finished, whatever happens to its dialog."""

    app = QCoreApplication.instance()
    if app is not None and not any(app is hooked for hooked in _QUIT_HOOK_APPS):
        _QUIT_HOOK_APPS.append(app)
        app.aboutToQuit.connect(shutdown_load_threads)
    _ACTIVE_LOAD_THREADS.add(thread)
    thread.finished.connect(lambda: _ACTIVE_LOAD_THREADS.discard(thread))
    thread.start()


@dataclass
class RecordTableSlot:
    """Per-table lazy-load state owned by the dialog."""

    kind: str
    tab: QWidget
    view: RecordTableView
    filter_edit: Any
    banner: RecordBusyBanner
    filter_timer: QTimer
    state: str = "idle"
    generation: int = 0
    thread: RecordLoadThread | None = None
    pending_specs: list[dict[str, Any]] | None = None

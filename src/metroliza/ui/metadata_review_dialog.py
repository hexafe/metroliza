"""Metadata review step shown between report review and import (#1100).

``MetadataReviewPanel`` is host-agnostic (it can be embedded in a future unified
Reports workspace); ``MetadataReviewDialog`` is the modal wrapper used by the
import dialog.  Nothing here writes to a database: the panel only produces
``ReportMetadataOverride`` values that travel in the ``ImportPlan``.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from metroliza.parsing.metadata_review import (
    MODE_FAST,
    MODE_OCR,
    MetadataReviewReader,
)
from metroliza.reports.report_metadata_review import (
    FIELD_LABELS,
    REVIEW_FIELDS,
    ReportMetadataOverride,
    ReviewRow,
    apply_value_to_rows,
    build_overrides,
)
from metroliza.ui.metadata_review_model import MetadataReviewFilterModel, MetadataReviewModel
from metroliza.ui.metadata_review_worker import MetadataReviewThread
from metroliza.ui.report_planner import PLANNER_ACTION_STYLE
from metroliza.ui.ui_foundation import (
    _is_dark_widget_palette,
    apply_metroliza_theme,
    configure_accessibility,
    configure_dialog_button_roles,
    configure_window_size,
    secondary_label,
    set_status_variant,
    status_chip,
)

_PREF_WIDTHS = "presentation/metadata_review/column_widths"
_PREF_ATTENTION = "presentation/metadata_review/attention_only"
_DEFAULT_WIDTHS = [260, 130, 150, 90, 100, 70, 80, 110, 150, 120, 80, 280]


def summarize_rows(rows: Sequence[ReviewRow]) -> str:
    """One-line status shared by the dialog footer and the import dialog."""

    editable = [row for row in rows if row.editable]
    edited = sum(1 for row in editable if row.edited_fields)
    missing = sum(1 for row in editable if row.reference_missing)
    parts = [f"{len(rows)} report{'s' if len(rows) != 1 else ''}", f"{edited} edited"]
    parts.append(f"{missing} missing a reference" if missing else "all have a reference")
    return ", ".join(parts)


class MetadataReviewPanel(QWidget):
    """Editable table with fast prefill, bulk apply and cancellable OCR."""

    state_changed = pyqtSignal()
    idle = pyqtSignal()

    def __init__(
        self,
        reader: MetadataReviewReader,
        rows: Sequence[ReviewRow],
        parent=None,
        *,
        ui_preferences=None,
    ) -> None:
        super().__init__(parent)
        self._reader = reader
        self._preferences = ui_preferences
        self._thread: MetadataReviewThread | None = None
        self._ocr_notes: set[str] = set()
        self.model = MetadataReviewModel(rows, self)
        self.proxy = MetadataReviewFilterModel(self)
        self.proxy.setSourceModel(self.model)

        self.intro = secondary_label(
            "Metadata is read quickly from file names and embedded text. Fix or fill values "
            "here; nothing is written to the database until you import."
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search reports or values")
        self.search.setAccessibleName("Search metadata")
        self.search.textChanged.connect(self.proxy.set_text_filter)
        self.attention_only = QCheckBox("Only missing / low confidence")
        self.attention_only.toggled.connect(self.proxy.set_attention_only)
        self.counts = QLabel()
        self.counts.setAccessibleName("Metadata review counts")

        self.table = QTableView()
        self.table.setAccessibleName("Report metadata")
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(MetadataReviewModel.FILE_COLUMN, Qt.SortOrder.AscendingOrder)
        self.table.verticalHeader().hide()
        self.table.setStyleSheet("QTableView { min-height: 80px; }")
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setWordWrap(False)
        self._widths_applied = False

        self.bulk_field = QComboBox()
        self.bulk_field.setAccessibleName("Field to apply")
        for name in REVIEW_FIELDS:
            self.bulk_field.addItem(FIELD_LABELS[name], name)
        self.bulk_value = QLineEdit()
        self.bulk_value.setPlaceholderText("Value for the selected rows")
        self.bulk_value.setAccessibleName("Value to apply")
        self.bulk_apply = QPushButton("Apply to selected rows")
        self.bulk_apply.setToolTip("Set the chosen field on every selected row (counts as a manual edit).")
        self.bulk_apply.clicked.connect(self.apply_to_selected)
        self.bulk_value.returnPressed.connect(self.apply_to_selected)
        self.select_all = QPushButton("Select all visible")
        self.select_all.clicked.connect(self.table.selectAll)
        self.reset_edits = QPushButton("Reset edits in selected rows")
        self.reset_edits.setToolTip("Discard manual edits and return to the detected values.")
        self.reset_edits.clicked.connect(self.reset_selected_edits)

        self.ocr_selected = QPushButton("Run OCR on selected rows")
        self.ocr_selected.setToolTip(
            "Read the report header with OCR. Only cells you have not edited are filled."
        )
        self.ocr_selected.clicked.connect(lambda: self.start_ocr(selected_only=True))
        self.ocr_all = QPushButton("Run OCR on all rows")
        self.ocr_all.clicked.connect(lambda: self.start_ocr(selected_only=False))
        self.stop = QPushButton("Stop")
        self.stop.setToolTip("Stop after the current report. Values already read are kept.")
        self.stop.clicked.connect(self.stop_worker)
        self.stop.hide()
        self.accept_ocr = QPushButton("Use OCR values for edited cells...")
        self.accept_ocr.setToolTip("Replace manually edited cells by the different OCR values (asks first).")
        self.accept_ocr.clicked.connect(self.confirm_accept_ocr)
        self.accept_ocr.hide()

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setMaximumHeight(16)
        self.progress.hide()
        self.message = status_chip("", "neutral")
        self.message.setAccessibleName("Metadata review status")

        for button in (
            self.bulk_apply, self.select_all, self.reset_edits, self.ocr_selected,
            self.ocr_all, self.stop, self.accept_ocr,
        ):
            button.setStyleSheet(PLANNER_ACTION_STYLE)
        configure_accessibility(self.bulk_apply, name="Apply value to selected rows")
        configure_accessibility(self.ocr_selected, name="Run OCR on selected rows")
        configure_accessibility(self.ocr_all, name="Run OCR on all rows")
        configure_accessibility(self.stop, name="Stop metadata reading")

        filters = QHBoxLayout()
        filters.addWidget(self.search, 1)
        filters.addWidget(self.attention_only)
        bulk = QHBoxLayout()
        bulk.addWidget(QLabel("Set"))
        bulk.addWidget(self.bulk_field)
        bulk.addWidget(self.bulk_value, 1)
        bulk.addWidget(self.bulk_apply)
        bulk.addWidget(self.select_all)
        bulk.addWidget(self.reset_edits)
        ocr = QGridLayout()
        ocr.addWidget(self.ocr_selected, 0, 0)
        ocr.addWidget(self.ocr_all, 0, 1)
        ocr.addWidget(self.stop, 0, 2)
        ocr.addWidget(self.accept_ocr, 0, 3)
        ocr.addWidget(self.progress, 0, 4)
        ocr.setColumnStretch(4, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.intro)
        layout.addLayout(filters)
        layout.addWidget(self.counts)
        layout.addWidget(self.table, 1)
        layout.addLayout(bulk)
        layout.addLayout(ocr)
        layout.addWidget(self.message)

        self.model.changed.connect(self._refresh)
        self.model.edit_rejected.connect(lambda text: self._say(text, "warning"))
        self.attention_only.setChecked(self._load_attention())
        self.model.set_dark_mode(_is_dark_widget_palette(self))
        self._refresh()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._widths_applied:
            # Header sections only keep explicit widths once the view is shown.
            self._widths_applied = True
            for column, width in enumerate(self._load_widths()):
                self.table.setColumnWidth(column, width)

    # -- public API --------------------------------------------------------

    @property
    def rows(self) -> tuple[ReviewRow, ...]:
        return self.model.rows

    def overrides(self) -> tuple[ReportMetadataOverride, ...]:
        return build_overrides(self.model.rows)

    def summary_text(self) -> str:
        return summarize_rows(self.model.rows)

    def is_busy(self) -> bool:
        return self._thread is not None

    def start_fast_read(self) -> bool:
        pending = [row.occurrence_id for row in self.model.rows if row.state == "pending"]
        return self._start(pending, MODE_FAST) if pending else False

    def start_ocr(self, *, selected_only: bool) -> bool:
        rows = self._selected_rows() if selected_only else list(self.model.rows)
        ids = [row.occurrence_id for row in rows if row.editable]
        if not ids:
            self._say("Select at least one report to run OCR on.", "warning")
            return False
        return self._start(ids, MODE_OCR)

    def stop_worker(self) -> None:
        thread = self._thread
        if thread is not None:
            thread.stop_reading()
            self._say("Stopping after the current report. Values already read are kept.", "neutral")

    def save_preferences(self) -> None:
        prefs = self._preferences
        if prefs is None:
            return
        try:
            widths = [self.table.columnWidth(c) for c in range(self.model.columnCount())]
            prefs.set(_PREF_WIDTHS, widths)
            prefs.set(_PREF_ATTENTION, bool(self.attention_only.isChecked()))
        except Exception:  # noqa: BLE001 - presentation state must never block the workflow
            pass

    # -- actions -----------------------------------------------------------

    def apply_to_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            self._say("Select the reports to change first.", "warning")
            return
        field_name = self.bulk_field.currentData()
        changed, error = apply_value_to_rows(rows, field_name, self.bulk_value.text())
        if error:
            self._say(error, "warning")
            return
        self.model.notify_rows_changed(rows)
        self._say(f"{FIELD_LABELS[field_name]} set on {changed} report(s).", "success")

    def reset_selected_edits(self) -> None:
        rows = self._selected_rows()
        count = sum(row.reset_user_edits() for row in rows)
        self.model.notify_rows_changed(rows)
        self._say(f"Discarded {count} manual edit(s).", "neutral")

    def confirm_accept_ocr(self) -> None:
        rows = [row for row in self.model.rows if row.conflict_fields]
        cells = sum(len(row.conflict_fields) for row in rows)
        if not cells:
            return
        answer = QMessageBox.question(
            self,
            "Replace manual values?",
            f"OCR read different values for {cells} cell(s) you edited manually in "
            f"{len(rows)} report(s). Replace your values with the OCR values?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for row in rows:
            row.accept_ocr_suggestions()
        self.model.notify_rows_changed(rows)
        self._say(f"Replaced {cells} manual value(s) with OCR values.", "neutral")

    # -- worker ------------------------------------------------------------

    def _start(self, occurrence_ids: list[str], mode: str) -> bool:
        if self._thread is not None:
            return False
        thread = MetadataReviewThread(self._reader, occurrence_ids, mode=mode)
        self._thread = thread
        self._ocr_notes.clear()
        thread.reading_ready.connect(self._on_reading)
        thread.update_progress.connect(self.progress.setValue)
        thread.update_label.connect(self._on_label)
        thread.completed.connect(lambda summary, t=thread: self._on_completed(t, summary))
        thread.failed.connect(lambda text: self._say(text, "warning"))
        thread.finished.connect(lambda t=thread: self._on_stopped(t))
        self.progress.setValue(0)
        self.progress.show()
        self.stop.show()
        self._say(
            "Running OCR..." if mode == MODE_OCR else "Reading metadata...", "neutral"
        )
        self._refresh()
        thread.start()
        return True

    def _on_label(self, text: str) -> None:
        self.progress.setToolTip(text)

    def _on_reading(self, reading) -> None:
        self.model.apply_reading(reading)
        if reading.mode == MODE_OCR and reading.ocr_note and "not needed" not in reading.ocr_note:
            if reading.ocr_note != "Header read with OCR.":
                self._ocr_notes.add(reading.ocr_note)

    def _on_completed(self, thread, summary) -> None:
        verb = "OCR" if thread.mode == MODE_OCR else "Metadata read"
        if summary.cancelled:
            text = f"{verb} stopped: {summary.read} of {summary.total} done; the rest was not read."
        else:
            text = f"{verb} finished for {summary.read} of {summary.total} report(s)."
        if summary.failed:
            text += f" {summary.failed} could not be read."
        if self._ocr_notes:
            text += " " + " ".join(sorted(self._ocr_notes))
        self._say(text, "warning" if summary.failed or self._ocr_notes else "success")

    def _on_stopped(self, thread) -> None:
        if thread is self._thread:
            self._thread = None
        thread.deleteLater()
        self.progress.hide()
        self.stop.hide()
        self._refresh()
        self.idle.emit()

    # -- helpers -----------------------------------------------------------

    def _selected_rows(self) -> list[ReviewRow]:
        positions = {
            self.proxy.mapToSource(index).row()
            for index in self.table.selectionModel().selectedRows()
        }
        return [row for i in sorted(positions) if (row := self.model.row_at(i)) is not None]

    def _say(self, text: str, variant: str) -> None:
        self.message.setText(text)
        set_status_variant(self.message, variant)

    def _refresh(self) -> None:
        rows = self.model.rows
        attention = sum(1 for row in rows if row.needs_attention)
        conflicts = sum(len(row.conflict_fields) for row in rows)
        self.counts.setText(
            f"{self.proxy.rowCount()} shown / {len(rows)} reports - {attention} need attention - "
            f"{self.summary_text()}"
        )
        busy = self.is_busy()
        for button in (self.ocr_selected, self.ocr_all):
            button.setEnabled(not busy)
        self.accept_ocr.setVisible(bool(conflicts))
        self.accept_ocr.setEnabled(not busy)
        self.state_changed.emit()

    def _load_widths(self) -> list[int]:
        count = MetadataReviewModel.COLUMN_COUNT
        widths = list(_DEFAULT_WIDTHS[:count])
        prefs = self._preferences
        if prefs is not None:
            try:
                stored = prefs.get(_PREF_WIDTHS, [])
                if isinstance(stored, (str, int)):
                    stored = [stored]
                parsed = [int(value) for value in stored]
                if len(parsed) == count and all(20 <= value <= 2000 for value in parsed):
                    widths = parsed
            except Exception:  # noqa: BLE001
                pass
        return widths

    def _load_attention(self) -> bool:
        if self._preferences is None:
            return False
        try:
            return bool(self._preferences.get(_PREF_ATTENTION, False))
        except Exception:  # noqa: BLE001
            return False


class MetadataReviewDialog(QDialog):
    """Modal Metadata step. Accepting hands the confirmed rows to the caller."""

    def __init__(
        self,
        reader: MetadataReviewReader,
        rows: Sequence[ReviewRow],
        parent=None,
        *,
        ui_preferences=None,
        auto_read: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review metadata")
        configure_window_size(self, minimum=(640, 420), initial=(1180, 640), screen_margin=32)
        self._close_requested = False
        self.panel = MetadataReviewPanel(reader, rows, self, ui_preferences=ui_preferences)
        self.use_button = QPushButton("Use these values")
        self.use_button.setToolTip("Keep the table values for the import. Nothing is written yet.")
        self.use_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setToolTip("Discard changes made in this step. The database is not touched.")
        self.cancel_button.clicked.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.panel, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.use_button)
        layout.addLayout(buttons)
        configure_accessibility(self.use_button, name="Use these metadata values")
        configure_accessibility(self.cancel_button, name="Cancel metadata review")
        self.panel.idle.connect(self._on_idle)
        self.panel.state_changed.connect(self._sync_buttons)
        apply_metroliza_theme(self)
        for button in (self.use_button, self.cancel_button):
            button.setStyleSheet(PLANNER_ACTION_STYLE)
        configure_dialog_button_roles(primary=self.use_button, secondary=(self.cancel_button,))
        self._sync_buttons()
        if auto_read:
            self.panel.start_fast_read()

    def rows(self) -> tuple[ReviewRow, ...]:
        return self.panel.rows

    def overrides(self) -> tuple[ReportMetadataOverride, ...]:
        return self.panel.overrides()

    def summary_text(self) -> str:
        return self.panel.summary_text()

    def _sync_buttons(self) -> None:
        busy = self.panel.is_busy()
        self.use_button.setEnabled(not busy)
        self.use_button.setToolTip(
            "Wait for reading to finish or press Stop."
            if busy else "Keep the table values for the import. Nothing is written yet."
        )

    def _defer_close(self) -> bool:
        if not self.panel.is_busy():
            return False
        self._close_requested = True
        self.panel.stop_worker()
        return True

    def _on_idle(self) -> None:
        if self._close_requested:
            self._close_requested = False
            QDialog.reject(self)

    def accept(self) -> None:
        if self.panel.is_busy():
            return
        self.panel.save_preferences()
        super().accept()

    def reject(self) -> None:
        if self._defer_close():
            return
        self.panel.save_preferences()
        super().reject()

    def closeEvent(self, event):  # noqa: N802
        if self._defer_close():
            event.ignore()
            return
        super().closeEvent(event)

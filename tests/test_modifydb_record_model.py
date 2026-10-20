"""Model/view and lazy-loading behaviour of the Modify Database record tables (#1118)."""

from __future__ import annotations

from contextlib import closing
import sqlite3
import threading
import time
from unittest.mock import patch

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

from metroliza.ui import modify_db_records as records  # noqa: E402
from metroliza.ui.modify_db import ModifyDB  # noqa: E402
from metroliza.ui.modify_db_records import RecordTableModel, load_record_rows  # noqa: E402
from tests.test_modifydb_parity import _app, _build_current_database, _build_legacy_database  # noqa: E402


SPECS = [
    {"label": "ID", "field": "report_id", "editable": False, "key": True},
    {"label": "REFERENCE", "field": "reference", "editable": True},
    {"label": "NOM", "field": "nominal", "editable": True, "value_type": "float"},
]


def _model(rows=None):
    return RecordTableModel(SPECS, rows or [(1, "REF-A", 10.0), (2, "Ref-B", None), (3, "REF-C", 5.5)])


def _pump(predicate, timeout=10.0):
    app = _app()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    return predicate()


def _display(model, row, column):
    return model.index(row, column).data(Qt.ItemDataRole.DisplayRole)


# -- model ----------------------------------------------------------------------------


def test_model_shows_stored_values_and_keeps_originals_in_user_role():
    model = _model()

    assert [_display(model, 1, column) for column in range(3)] == ["2", "Ref-B", ""]
    assert model.index(0, 2).data(Qt.ItemDataRole.UserRole) == 10.0
    assert model.index(1, 2).data(Qt.ItemDataRole.UserRole) is None
    assert [model.headerData(c, Qt.Orientation.Horizontal) for c in range(3)] == ["ID", "REFERENCE", "NOM"]


def test_model_flags_follow_editable_specs_and_readonly_edits_are_rejected():
    model = _model()

    assert not model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable
    assert model.flags(model.index(0, 1)) & Qt.ItemFlag.ItemIsEditable
    assert model.setData(model.index(0, 0), "99", Qt.ItemDataRole.EditRole) is False
    assert _display(model, 0, 0) == "1"
    assert not model.has_edits


def test_model_edits_are_a_sparse_overlay_that_drops_back_to_the_original():
    model = _model()

    model.setData(model.index(1, 1), "Ref-X", Qt.ItemDataRole.EditRole)
    model.setData(model.index(1, 2), "7", Qt.ItemDataRole.EditRole)
    model.setData(model.index(0, 1), "REF-A", Qt.ItemDataRole.EditRole)  # unchanged text

    assert list(model.edited_rows()) == [(1, {1: "Ref-X", 2: "7"})]
    assert model.original_text(1, 1) == "Ref-B"
    assert _display(model, 1, 1) == "Ref-X"

    model.setData(model.index(1, 1), "Ref-B", Qt.ItemDataRole.EditRole)
    model.setData(model.index(1, 2), "", Qt.ItemDataRole.EditRole)  # NULL shows as empty text
    assert not model.has_edits


def test_filter_matches_current_text_of_any_column_case_insensitively():
    model = _model()
    model.setData(model.index(2, 1), "Zebra", Qt.ItemDataRole.EditRole)

    model.set_filter_text("ref-")
    assert model.rowCount() == 2 and [_display(model, r, 0) for r in range(2)] == ["1", "2"]
    model.set_filter_text("ZEBRA")
    assert [_display(model, r, 0) for r in range(model.rowCount())] == ["3"]
    model.set_filter_text("5.5")
    assert model.rowCount() == 1
    model.set_filter_text("no-such-text")
    assert model.rowCount() == 0
    model.set_filter_text("")
    assert model.rowCount() == 3 and model.total_row_count == 3


def test_filter_does_not_match_across_cell_boundaries_and_survives_separator_text():
    model = _model([(1, "ab", 1.0), (2, "cd", 2.0)])

    model.set_filter_text("b\x1fc")
    assert model.rowCount() == 0
    model.set_filter_text("b1")  # end of one cell + start of the next must not match
    assert model.rowCount() == 0
    model.set_filter_text("ab")
    assert model.rowCount() == 1


def test_edits_made_while_filtered_apply_to_the_right_source_row_and_keep_row_numbers():
    model = _model()
    model.set_filter_text("ref-c")

    model.setData(model.index(0, 1), "REF-C2", Qt.ItemDataRole.EditRole)

    assert list(model.edited_rows()) == [(2, {1: "REF-C2"})]
    assert model.headerData(0, Qt.Orientation.Vertical) == "3"  # keeps its unfiltered number


def test_first_rows_by_key_prefers_the_first_duplicate_and_ignores_bad_keys():
    model = _model([(7, "a", 1.0), (7, "b", 2.0), ("x", "c", 3.0), (9, "d", 4.0)])

    def coerce(text):
        try:
            return int(text)
        except ValueError:
            return None

    assert model.first_rows_by_key(0, {7, 9}, coerce) == {7: 0, 9: 3}


# -- fetching -------------------------------------------------------------------------


def _write_database(path, rows):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE t (id INTEGER, reference TEXT, nominal REAL)")
        connection.executemany("INSERT INTO t VALUES (?, ?, ?)", rows)


def test_load_record_rows_aligns_columns_to_specs_and_stores_repeated_text_once(tmp_path):
    database = tmp_path / "rows.db"
    _write_database(database, [(i, "".join(["REF", "-", "A"]), float(i)) for i in range(25)])
    specs = [*SPECS, {"label": "MISSING", "field": "missing", "editable": True}]

    result = load_record_rows(
        str(database), "SELECT nominal, reference, id AS report_id FROM t ORDER BY id", specs, batch_size=10
    )

    assert len(result.rows) == len(result.haystack) == 25
    assert result.rows[3] == (3, "REF-A", 3.0, None)
    assert len({id(row[1]) for row in result.rows}) == 1
    assert result.haystack[3] == "3\x1fref-a\x1f3.0\x1f"


def test_load_record_rows_returns_none_when_cancelled(tmp_path):
    database = tmp_path / "rows.db"
    _write_database(database, [(i, "R", 1.0) for i in range(30)])

    assert load_record_rows(str(database), "SELECT id AS report_id FROM t", SPECS, should_cancel=lambda: True) is None


# -- dialog: lazy, threaded loading ----------------------------------------------------


@pytest.fixture
def current_dialog(tmp_path):
    _app()
    database = tmp_path / "current.db"
    _build_current_database(database)
    dialog = ModifyDB(parent=None, db_file=str(database), modal=False)
    yield dialog
    dialog._changes_committed = True
    dialog.close()


def test_record_tables_stay_empty_until_their_tab_is_shown_then_load_in_a_worker(current_dialog):
    dialog = current_dialog
    report_slot, measurement_slot = dialog._record_slots

    assert report_slot.state == measurement_slot.state == "idle"
    assert dialog.report_records_table.rowCount() == dialog.measurement_records_table.rowCount() == 0

    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    assert measurement_slot.state == "loading" and measurement_slot.thread is not None
    assert report_slot.state == "idle"  # only the shown tab loads

    assert _pump(lambda: measurement_slot.state == "loaded")
    assert dialog.measurement_records_table.rowCount() == 10
    assert dialog.measurement_records_table.columnCount() == 17
    assert not measurement_slot.banner.isVisibleTo(dialog)
    assert report_slot.state == "idle" and dialog.report_records_table.rowCount() == 0


def test_filter_is_debounced_and_also_applies_to_text_typed_before_the_load_finished(current_dialog):
    dialog = current_dialog
    slot = dialog._record_slots[1]
    dialog.ensure_record_tables_loaded()
    model = dialog.measurement_records_table.model()

    slot.filter_edit.setText("nok")
    slot.filter_edit.setText("nok ")  # restarts the timer; nothing applied yet
    assert slot.filter_timer.isActive() and model.rowCount() == 10

    assert _pump(lambda: model.rowCount() != 10)
    assert model.rowCount() == 0  # "nok " (with trailing space) matches nothing

    slot.filter_edit.setText("nok")
    dialog.flush_record_filters()
    assert model.rowCount() == 2 and not slot.filter_timer.isActive()

    dialog.populate_tables()  # reload keeps the typed filter
    dialog.ensure_record_tables_loaded()
    assert dialog.measurement_records_table.model().rowCount() == 2


def test_ensure_record_tables_loaded_supersedes_a_running_background_load(current_dialog):
    dialog = current_dialog
    slot = dialog._record_slots[1]
    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    assert slot.state == "loading"

    dialog.ensure_record_tables_loaded()

    assert slot.state == "loaded" and dialog.measurement_records_table.rowCount() == 10
    assert dialog.report_records_table.rowCount() == 4


def test_results_of_a_superseded_load_are_ignored(current_dialog):
    dialog = current_dialog
    slot = dialog._record_slots[1]
    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    stale_generation = slot.generation

    dialog._reset_record_tables()  # e.g. another database was selected
    dialog._on_record_rows_loaded("measurement", stale_generation, records.RecordRows([(1,)], ["1"]))

    assert slot.state == "idle" and dialog.measurement_records_table.rowCount() == 0


def test_closing_while_a_load_runs_cancels_the_worker_and_keeps_no_thread_alive(current_dialog):
    dialog = current_dialog
    slot = dialog._record_slots[1]
    started = threading.Event()

    def slow_loader(*_args, should_cancel=None, **_kwargs):
        started.set()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if should_cancel():
                return None
            time.sleep(0.005)
        return records.RecordRows([], [])

    with patch.object(records, "load_record_rows", slow_loader):
        dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
        assert started.wait(5)
        thread = slot.thread
        assert thread is not None and thread.isRunning()

        dialog._changes_committed = True
        dialog.close()

        assert thread.wait(5000)  # `done()` already asked it to stop; it must not need the 20 s
        assert _pump(lambda: not records._ACTIVE_LOAD_THREADS)
    assert slot.thread is None and slot.state == "idle"


@pytest.mark.parametrize("blocked_by", ["execute", "lock"])
def test_sqlite_load_cancels_before_the_first_batch(tmp_path, blocked_by):
    _app()
    database = tmp_path / "blocked.db"
    _write_database(database, [(1, "R", 1.0)])
    started = threading.Event()
    cleanup_cancel = threading.Event()
    connections = []
    connect = sqlite3.connect

    def observed_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        connection.set_progress_handler(cleanup_cancel.is_set, 1000)
        connection.set_trace_callback(lambda sql: started.set() if "WITH RECURSIVE" in sql else None)
        if blocked_by == "lock":
            started.set()  # next step is the PRAGMA/SELECT blocked by the exclusive writer
        return connection

    query = """WITH RECURSIVE numbers(n) AS (
        VALUES(1) UNION ALL SELECT n + 1 FROM numbers WHERE n < 1000000000
    ) SELECT sum(n) AS report_id FROM numbers"""
    if blocked_by == "lock":
        query = "SELECT id AS report_id FROM t"
    worker = records.RecordLoadThread("report", 1, str(database), query, SPECS)
    loaded, failed = [], []
    worker.loaded.connect(lambda *args: loaded.append(args))
    worker.failed.connect(lambda *args: failed.append(args))
    with closing(connect(database)) as locker:
        if blocked_by == "lock":
            locker.execute("BEGIN EXCLUSIVE")
        with patch.object(sqlite3, "connect", observed_connect):
            records.start_load_thread(worker)
            try:
                assert started.wait(5)
                assert not worker.wait(100)  # the SQL/lock is still pending, before any batch
                records.cancel_load_thread(worker, wait_ms=1000)
                assert not worker.isRunning(), "cancellation returned with SQLite still executing"
            finally:
                # Always release real SQL and join, including when testing the broken code.
                worker.requestInterruption()
                cleanup_cancel.set()
                for connection in connections:
                    try:
                        connection.interrupt()
                    except sqlite3.ProgrammingError:  # already closed by the worker
                        pass
                locker.rollback()
                worker.wait()
                _pump(lambda: worker not in records._ACTIVE_LOAD_THREADS)
    assert not loaded and not failed


def test_about_to_quit_joins_a_worker_that_exceeds_the_bounded_wait(tmp_path):
    app = _app()
    database = tmp_path / "blocked.db"
    _write_database(database, [])
    entered, release = threading.Event(), threading.Event()
    connect = sqlite3.connect

    def blocked_sql():
        entered.set()
        release.wait(5)  # a finite stand-in for an uninterruptible SQLite extension
        return 1

    def blocking_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.create_function("blocked_sql", 0, blocked_sql)
        return connection

    worker = records.RecordLoadThread("report", 1, str(database), "SELECT blocked_sql() AS report_id", SPECS)
    cancel = records.cancel_load_thread
    unblock = threading.Timer(0.2, release.set)
    with patch.object(sqlite3, "connect", blocking_connect):
        records.start_load_thread(worker)
        try:
            assert entered.wait(5)
            unblock.start()
            with patch.object(worker, "wait", wraps=worker.wait) as waits, patch.object(
                records, "cancel_load_thread", lambda thread: cancel(thread, wait_ms=1)
            ):
                app.aboutToQuit.emit()
                assert not worker.isRunning(), "application shutdown returned before the worker finished"
                assert waits.call_count == 2  # bounded wait failed, so exit must wait for completion
        finally:
            release.set()
            unblock.cancel()
            worker.requestInterruption()
            worker.wait()
            _pump(lambda: worker not in records._ACTIVE_LOAD_THREADS)


def test_failed_load_is_logged_and_the_tab_can_retry(current_dialog):
    dialog = current_dialog
    slot = dialog._record_slots[1]
    logged = []

    def failing_loader(*_args, **_kwargs):
        raise sqlite3.OperationalError("boom")

    with patch.object(records, "load_record_rows", failing_loader), patch.object(
        dialog, "log_and_exit", logged.append
    ):
        dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
        assert _pump(lambda: bool(logged))

    assert isinstance(logged[0], sqlite3.OperationalError)
    assert slot.state == "idle" and not slot.banner.isVisibleTo(dialog)
    dialog.tab_widget.setCurrentWidget(dialog.report_records_tab)
    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    assert _pump(lambda: slot.state == "loaded")


def test_legacy_schema_record_tables_load_lazily(tmp_path):
    _app()
    database = tmp_path / "legacy.db"
    _build_legacy_database(database)
    dialog = ModifyDB(parent=None, db_file=str(database), modal=False)
    try:
        dialog.tab_widget.setCurrentWidget(dialog.report_records_tab)
        assert _pump(lambda: dialog._record_slots[0].state == "loaded")
        assert dialog.report_records_table.rowCount() == 4
        assert dialog.report_records_table.columnCount() == 6
    finally:
        dialog._changes_committed = True
        dialog.close()


# -- view -----------------------------------------------------------------------------


def test_in_cell_editor_commits_through_the_model_and_marks_the_dialog_dirty(current_dialog):
    from PyQt6.QtWidgets import QLineEdit

    dialog = current_dialog
    dialog.ensure_record_tables_loaded()
    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    view = dialog.measurement_records_table
    index = view.model().index(0, 2)  # HEADER of the first measurement, editable
    assert view.model().flags(index) & Qt.ItemFlag.ItemIsEditable

    view.setCurrentIndex(index)
    view.edit(index)
    editor = view.viewport().findChild(QLineEdit)
    assert editor is not None and editor.text() == "WIDTH"
    editor.setText("WIDTH-2")
    view.commitData(editor)
    view.closeEditor(editor, view.itemDelegate().EndEditHint.NoHint)

    assert _display(view.model(), 0, 2) == "WIDTH-2"
    assert dialog.has_pending_changes()


@pytest.mark.parametrize("filter_text", ["pending edit", "no matching row"])
def test_pending_filter_waits_for_uncommitted_cell_editor(current_dialog, filter_text):
    from PyQt6.QtWidgets import QLineEdit

    dialog = current_dialog
    dialog.ensure_record_tables_loaded()
    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    slot = dialog._record_slots[1]
    view = slot.view
    model = view.model()
    timeouts = []
    slot.filter_timer.timeout.connect(lambda: timeouts.append(True))
    slot.filter_edit.setText(filter_text)
    assert slot.filter_timer.isActive()

    index = model.index(0, 2)
    view.setCurrentIndex(index)
    view.edit(index)
    editor = view.viewport().findChild(QLineEdit)
    assert editor is not None
    editor.setText("pending edit")

    assert _pump(lambda: bool(timeouts))
    assert model.filter_text == ""  # no reset while the delegate owns uncommitted text
    assert view.state() == view.State.EditingState
    assert editor.text() == "pending edit"
    dialog.flush_record_filters()  # explicit flush must also preserve the editor
    assert view.state() == view.State.EditingState

    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert _pump(lambda: model.filter_text == filter_text)
    assert model.text_at(0, 2) == "pending edit"
    assert model.original_text(0, 2) == "WIDTH"
    assert dialog.collect_measurement_record_updates() == [(101, {"header": "pending edit"})]
    assert model.rowCount() == (1 if filter_text == "pending edit" else 0)
    assert dialog.has_pending_changes()


def test_mouse_clicks_emit_cell_pressed_and_shift_click_selects_a_row_range(current_dialog):
    dialog = current_dialog
    dialog.ensure_record_tables_loaded()
    dialog.resize(1400, 700)
    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    dialog.show()
    _app().processEvents()
    view = dialog.measurement_records_table
    pressed = []
    view.cellPressed.connect(lambda row, column: pressed.append((row, column)))

    def click(row, modifier=Qt.KeyboardModifier.NoModifier):
        QTest.mouseClick(
            view.viewport(), Qt.MouseButton.LeftButton, modifier, view.visualRect(view.model().index(row, 2)).center()
        )

    click(2)
    click(5, Qt.KeyboardModifier.ShiftModifier)

    assert pressed == [(2, 2), (5, 2)]
    # Same rows the QTableWidget produced for this click sequence before #1118 (the handler's
    # setCurrentCell toggles the clicked row back off in multi-selection mode).
    assert sorted({index.row() for index in view.selectionModel().selectedRows()}) == [2, 3, 4]
    assert view.currentRow() == 5 and view.rowCount() == 10 and view.columnCount() == 17


@pytest.mark.parametrize("batch_size", [1, 7, 5000])
def test_loader_matches_cellwise_reference_for_unicode_nulls_and_reordered_columns(tmp_path, batch_size):
    database = tmp_path / "equivalence.db"
    values = [(i, text, number) for i in range(8) for text, number in [
        ("İßΣ\x1fX", -0.0), ("", None), (None, 1.2345678901234567), ("Repeat", 1e100),
    ]]
    _write_database(database, values)
    specs = [*SPECS, {"label": "ABSENT", "field": "absent"}]
    result = load_record_rows(str(database), "SELECT nominal, reference, id AS report_id FROM t", specs,
                              batch_size=batch_size)
    with closing(sqlite3.connect(database)) as connection:
        stored = connection.execute("SELECT id, reference, nominal FROM t").fetchall()
    expected = [(*row, None) for row in stored]
    assert result.rows == expected
    assert result.haystack == [records.row_haystack(row) for row in expected]
    model = RecordTableModel(specs, result.rows, result.haystack)
    for needle in ["", "repeat", "i̇", "σ", "1e+100", "x\x1f", "absent"]:
        model.set_filter_text(needle)
        wanted = [i for i, row in enumerate(expected) if not needle or any(
            needle in records.display_value(value).lower() for value in row
        )] if records.FIELD_SEPARATOR in needle else [
            i for i, row in enumerate(expected) if needle in records.row_haystack(row)
        ]
        assert [model.source_row(i) for i in range(model.rowCount())] == wanted


def test_record_indicator_is_delayed_nonmodal_and_released_on_cancel(current_dialog, monkeypatch):
    dialog = current_dialog
    dialog.ensure_record_tables_loaded()
    dialog._reset_record_tables()
    entered = threading.Event()

    def held_loader(*_args, should_cancel, **_kwargs):
        entered.set()
        while not should_cancel():
            time.sleep(0.005)
        return None

    monkeypatch.setattr(records, "load_record_rows", held_loader)
    dialog.show()
    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    slot = dialog._record_slots[1]
    assert entered.wait(1)
    progress = slot.progress_dialog
    assert progress is not None and not progress.isVisible()
    assert progress.windowModality() == Qt.WindowModality.NonModal
    assert progress._delayed_show_timer.interval() == 1000
    assert _pump(progress.isVisible)
    assert progress._loading_gif_buffer is not None
    dialog._cancel_record_load(slot)
    assert slot.progress_dialog is None and not progress.isVisible()
    assert not progress._delayed_show_timer.isActive()

@pytest.mark.parametrize("terminal", ["loaded", "failed", "close", "user_cancel"])
def test_record_indicator_released_on_every_terminal_path(current_dialog, monkeypatch, terminal):
    dialog = current_dialog
    entered, release = threading.Event(), threading.Event()
    logged = []

    def held_loader(*_args, should_cancel, **_kwargs):
        entered.set()
        while not release.wait(0.005):
            if should_cancel():
                return None
        if terminal == "failed":
            raise ValueError("synthetic record load failure")
        return records.RecordRows([], [])

    monkeypatch.setattr(records, "load_record_rows", held_loader)
    monkeypatch.setattr(dialog, "log_and_exit", logged.append)
    dialog.show()
    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    slot = dialog._record_slots[1]
    progress, thread, generation = slot.progress_dialog, slot.thread, slot.generation
    assert entered.wait(1)
    try:
        if terminal == "close":
            dialog.close()
        elif terminal == "user_cancel":
            progress.reject()
        else:
            release.set()
            assert _pump(lambda: slot.state != "loading")
        assert slot.progress_dialog is None
        assert not progress.isVisible() and not progress._delayed_show_timer.isActive()
        assert thread.wait(1000)
        assert bool(logged) == (terminal == "failed")
        if terminal in {"close", "user_cancel"}:
            dialog._on_record_rows_loaded(slot.kind, generation, records.RecordRows([(99,)], ["99"]))
            assert slot.state == "idle" and slot.view.rowCount() == 0
    finally:
        release.set()
        records.cancel_load_thread(thread)

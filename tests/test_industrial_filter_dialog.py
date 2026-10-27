from __future__ import annotations

from contextlib import closing
import sqlite3

import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QDialog

    import metroliza.ui.industrial_filter_dialog as industrial_filter_dialog
    from metroliza.industrial.industrial_workflow_state import (
        IndustrialFilterState,
        IndustrialQueryFilter,
        parse_industrial_query_filter_lines,
        parse_reference_values,
    )
    from metroliza.reports.report_schema import ensure_report_schema
    from metroliza.ui.industrial_filter_dialog import IndustrialFilterDialog
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    QDialog = None
    QTest = None
    Qt = None
    IndustrialFilterDialog = None
    IndustrialFilterState = None
    IndustrialQueryFilter = None
    ensure_report_schema = None
    parse_industrial_query_filter_lines = None
    parse_reference_values = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial filter dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_reference_parser_accepts_common_paste_formats():
    assert parse_reference_values("REF1, REF2;REF3\nREF4 REF5\tREF6") == (
        "REF1",
        "REF2",
        "REF3",
        "REF4",
        "REF5",
        "REF6",
    )
    assert parse_reference_values("REF1 REF1,REF2") == ("REF1", "REF2")


def test_query_filter_parser_accepts_simple_filter_lines():
    assert parse_industrial_query_filter_lines(
        "station = S1\nstatus IN OK, NOK\nprocess_timestamp >= 2026-01-01"
    ) == (
        IndustrialQueryFilter("station", "=", ("S1",)),
        IndustrialQueryFilter("status", "IN", ("OK", "NOK")),
        IndustrialQueryFilter("process_timestamp", ">=", ("2026-01-01",)),
    )


def test_filter_dialog_apply_uses_parent_callback():
    _app()
    class _ParentDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.state = None

        def set_industrial_filter_state(self, state):
            self.state = state

    parent = _ParentDialog()
    dialog = IndustrialFilterDialog(parent=parent, state=IndustrialFilterState())
    dialog.reference_column_edit.setText("reference")
    dialog.references_edit.setPlainText("REF1, REF2")
    dialog.query_filters_edit.setPlainText("station = S1")

    dialog.apply_filter()

    assert parent.state == IndustrialFilterState(
        reference_column="reference",
        references=("REF1", "REF2"),
        query_filters=(IndustrialQueryFilter("station", "=", ("S1",)),),
    )


def test_filter_dialog_builder_appends_filter_without_overwriting_references():
    _app()
    dialog = IndustrialFilterDialog(
        state=IndustrialFilterState(reference_column="reference", references=("REF1",))
    )
    dialog.query_filters_edit.setPlainText("station = S1")
    dialog.filter_column_combo.setCurrentIndex(dialog.filter_column_combo.findData("process_status"))
    dialog.filter_operator_combo.setCurrentIndex(dialog.filter_operator_combo.findData("IN"))
    dialog.filter_value_edit.setText("OK, NOK")

    dialog.add_filter_from_builder()

    assert dialog.references_edit.toPlainText() == "REF1"
    assert dialog.query_filters_edit.toPlainText().splitlines() == [
        "station = S1",
        "process_status IN OK, NOK",
    ]
    assert dialog.current_state().query_filters == (
        IndustrialQueryFilter("station", "=", ("S1",)),
        IndustrialQueryFilter("process_status", "IN", ("OK", "NOK")),
    )
    dialog.close()


def test_filter_dialog_rejects_invalid_reference_column():
    _app()
    dialog = IndustrialFilterDialog(state=IndustrialFilterState())
    dialog.reference_column_edit.setText("reference;drop")
    dialog.references_edit.setPlainText("REF1")

    assert dialog.current_state().references == ("REF1",)
    with pytest.raises(ValueError):
        dialog.current_state().validate_for_sync()
    dialog.close()


def test_filter_dialog_loads_references_from_local_metroliza_metadata_only(tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    ensure_report_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        timestamp = "2026-06-23T00:00:00"
        conn.executemany(
            """
            INSERT INTO source_files(id, sha256, source_format, discovered_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (index, f"sha-{index}", "pdf", timestamp)
                for index in range(1, 6)
            ],
        )
        conn.executemany(
            """
            INSERT INTO parsed_reports(
                id,
                source_file_id,
                parser_id,
                template_family,
                parse_status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (index, index, "test", "test", "parsed", timestamp, timestamp)
                for index in range(1, 6)
            ],
        )
        conn.executemany(
            "INSERT INTO report_metadata(report_id, reference, metadata_version) VALUES (?, ?, ?)",
            [
                (1, "REF-2", "report_metadata_v1"),
                (2, "REF-1", "report_metadata_v1"),
                (3, "REF-1", "report_metadata_v1"),
                (4, "", "report_metadata_v1"),
                (5, None, "report_metadata_v1"),
            ],
        )

    dialog = IndustrialFilterDialog(db_file=db_path, state=IndustrialFilterState())
    dialog.load_database_references()
    _wait_references(dialog)

    assert dialog.references_edit.toPlainText().splitlines() == ["REF-1", "REF-2"]
    assert dialog.summary_label.text().startswith("1 active condition.")
    assert "2 value(s) loaded" in dialog.source_context_label.text()
    dialog.close()


def test_filter_dialog_uses_inline_validation_and_clear_paths(monkeypatch):
    _app()
    warnings = []
    monkeypatch.setattr(
        industrial_filter_dialog.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )
    dialog = IndustrialFilterDialog(state=IndustrialFilterState(references=("REF-1",)))

    dialog.load_database_references()
    dialog.clear_filter()
    dialog.reference_column_edit.setText("reference;drop")
    dialog.references_edit.setPlainText("REF-2")
    dialog.apply_filter()

    assert len(warnings) == 1
    assert "Select a Metroliza report database" in warnings[0][2]
    assert not dialog.apply_button.isEnabled()
    assert not dialog.validation_error_label.isHidden()
    assert "reference column" in dialog.validation_error_label.text()
    dialog.close()


def test_filter_dialog_exposes_count_accessibility_and_semantic_actions():
    _app()
    dialog = IndustrialFilterDialog(
        state=IndustrialFilterState(
            references=("REF-1", "REF-2"),
            query_filters=(IndustrialQueryFilter("station", "=", ("S1",)),),
        )
    )

    assert dialog.summary_label.text().startswith("2 active conditions.")
    assert dialog.summary_label.accessibleName() == "Industrial sync filter draft summary"
    assert dialog.validation_error_label.accessibleName() == "Industrial sync filter error"
    assert dialog.apply_button.property("buttonRole") == "primary"
    assert dialog.apply_button.isDefault()
    assert dialog.cancel_button.property("buttonRole") == "secondary"
    assert dialog.clear_button.property("buttonRole") == "quiet"
    assert dialog.clear_button.text() == "Reset filters"
    dialog.close()


def test_filter_dialog_reset_and_cancel_discard_only_confirmed_draft_changes(monkeypatch):
    _app()

    class _ParentDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.calls = []

        def set_industrial_filter_state(self, state):
            self.calls.append(state)

    parent = _ParentDialog()
    committed = IndustrialFilterState(references=("REF-1",))
    dialog = IndustrialFilterDialog(parent=parent, state=committed)
    answers = iter(
        (
            industrial_filter_dialog.QMessageBox.StandardButton.No,
            industrial_filter_dialog.QMessageBox.StandardButton.Yes,
            industrial_filter_dialog.QMessageBox.StandardButton.Yes,
        )
    )
    prompts = []
    monkeypatch.setattr(
        industrial_filter_dialog.QMessageBox,
        "question",
        lambda *args: prompts.append(args) or next(answers),
    )

    dialog.references_edit.setPlainText("REF-2")
    dialog._request_reset_filter()
    assert dialog.current_state().references == ("REF-2",)

    dialog._request_reset_filter()
    assert dialog.current_state() == IndustrialFilterState()
    assert parent.calls == []

    dialog.references_edit.setPlainText("REF-3")
    dialog.show()
    _app().processEvents()
    dialog._request_cancel()
    assert dialog.current_state() == committed
    assert parent.calls == []
    assert len(prompts) == 3


def test_filter_dialog_clean_cancel_and_window_close_do_not_prompt(monkeypatch):
    _app()
    dialog = IndustrialFilterDialog(state=IndustrialFilterState(references=("REF-1",)))
    monkeypatch.setattr(
        industrial_filter_dialog.QMessageBox,
        "question",
        lambda *_args: pytest.fail("clean cancel should not ask for confirmation"),
    )
    dialog._request_cancel()

    dialog = IndustrialFilterDialog(state=IndustrialFilterState())
    dialog.references_edit.setPlainText("REF-2")
    dialog.close()


def test_filter_dialog_dirty_x_and_escape_restore_without_parent_commit(monkeypatch):
    app = _app()

    class _ParentDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.calls = []

        def set_industrial_filter_state(self, state):
            self.calls.append(state)

    parent = _ParentDialog()
    committed = IndustrialFilterState(references=("REF-1",))
    dialog = IndustrialFilterDialog(parent=parent, state=committed)
    answers = iter(
        (
            industrial_filter_dialog.QMessageBox.StandardButton.No,
            industrial_filter_dialog.QMessageBox.StandardButton.Yes,
            industrial_filter_dialog.QMessageBox.StandardButton.No,
            industrial_filter_dialog.QMessageBox.StandardButton.Yes,
        )
    )
    monkeypatch.setattr(
        industrial_filter_dialog.QMessageBox,
        "question",
        lambda *_args, **_kwargs: next(answers),
    )
    try:
        dialog.show()
        app.processEvents()
        dialog.references_edit.setPlainText("REF-2")

        assert dialog.close() is False
        assert dialog.isVisible()
        assert dialog.current_state().references == ("REF-2",)
        assert dialog.close() is True
        assert not dialog.isVisible()
        assert dialog.current_state() == committed
        assert parent.calls == []

        dialog.show()
        app.processEvents()
        dialog.references_edit.setPlainText("REF-3")
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert dialog.isVisible()
        assert dialog.current_state().references == ("REF-3",)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert not dialog.isVisible()
        assert dialog.current_state() == committed
        assert parent.calls == []
    finally:
        dialog.close()
        parent.close()


def _wait_references(dialog):
    for _ in range(1000):
        if getattr(dialog, "_reference_thread", None) is None:
            return
        _app().processEvents()
        QTest.qWait(5)
    pytest.fail("reference load did not finish")


def test_reference_load_literal_edge_order(tmp_path):
    _app()
    db_path = str(tmp_path / "literal.db")
    ensure_report_schema(db_path)
    values = [" ref ", "REF", "réf", "RéF", "001", "1", "", " \t ", None]
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for index, value in enumerate(values, 1):
            conn.execute(
                "INSERT INTO source_files(id,sha256,source_format,discovered_at) VALUES (?,?,?,?)",
                (index, str(index), "pdf", "2026-01-01"),
            )
            conn.execute(
                "INSERT INTO parsed_reports(id,source_file_id,parser_id,template_family,parse_status,created_at,updated_at) "
                "VALUES (?,?, 'test','test','parsed','2026-01-01','2026-01-01')", (index, index),
            )
            conn.execute(
                "INSERT INTO report_metadata(report_id,reference,metadata_version) VALUES (?,?,'v1')", (index, value),
            )
    dialog = IndustrialFilterDialog(db_file=db_path)
    dialog.load_database_references()
    _wait_references(dialog)
    assert dialog.references_edit.toPlainText() == "001\n1\nref\nREF\nRéF\nréf"
    assert dialog.source_context_label.text() == (
        "Reference source: 6 value(s) loaded from the open Metroliza "
        "report database. Changes stay in this draft until you apply the filters."
    )
    dialog.close()


def test_reference_custom_scope_literal_error(monkeypatch):
    _app()
    calls, warnings = [], []

    def custom(path):
        calls.append(path)
        raise ValueError("literal password=abc Unicode: Ω")

    monkeypatch.setattr(industrial_filter_dialog, "sqlite_connection_scope", custom)
    monkeypatch.setattr(industrial_filter_dialog.QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    dialog = IndustrialFilterDialog(db_file="custom.db")
    dialog.load_database_references()
    assert calls == ["custom.db"]
    assert warnings == [
        "Could not read references from the selected Metroliza report database: literal password=abc Unicode: Ω"
    ]
    dialog.close()


@pytest.mark.parametrize("action", ["normal", "edit", "reset", "database", "close", "discard_gate", "apply"])
def test_native_reference_worker_stale_and_terminal_lifetime(monkeypatch, tmp_path, action):
    import threading

    from PyQt6 import sip
    from PyQt6.QtCore import QThread

    from metroliza.ui import detached_threads

    app = _app()
    entered, release = threading.Event(), threading.Event()
    original_run = industrial_filter_dialog._ReferenceThread.run
    owners = []

    def held_run(worker):
        owners.append(QThread.currentThread() is app.thread())
        entered.set()
        if not release.wait(5):
            worker.error = "test barrier timed out"
            return
        original_run(worker)

    monkeypatch.setattr(industrial_filter_dialog._ReferenceThread, "run", held_run)
    path = str(tmp_path / "new.db")
    dialog = IndustrialFilterDialog(db_file=path, state=IndustrialFilterState(references=("draft",)))
    dialog.load_database_references()
    worker = dialog._reference_thread
    try:
        assert entered.wait(2)
        assert detached_threads.is_registered(worker)
        assert detached_threads._QUIT_BLOCKERS[id(worker)] is worker
        assert not dialog.load_db_references_button.isEnabled()
        dialog.load_database_references()
        assert dialog._reference_thread is worker
        if action == "edit":
            dialog.references_edit.setPlainText("edited")
        elif action == "reset":
            dialog.clear_filter()
        elif action == "database":
            dialog.db_file = str(tmp_path / "other.db")
        elif action == "close":
            dialog.close()
        elif action == "discard_gate":
            dialog._discard_gate_active = True
        elif action == "apply":
            dialog.apply_filter()
        if action == "normal":
            QTest.qWait(1100)
            assert dialog._reference_progress.isVisible()
    finally:
        release.set()
        _wait_references(dialog)
    assert owners == [False]
    assert dialog.references_edit.toPlainText() == {
        "normal": "", "edit": "edited", "reset": "", "database": "draft",
        "close": "draft", "discard_gate": "draft", "apply": "draft",
    }[action]
    assert dialog._reference_progress is None
    assert not detached_threads.is_registered(worker)
    QTest.qWait(10)
    assert sip.isdeleted(worker)
    # The complete schema ensure really ran, including when its result was discarded.
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM report_metadata").fetchone() == (0,)
    dialog._discard_gate_active = False
    dialog.close()


@pytest.mark.parametrize("failure", ["construct", "start", "query"])
def test_reference_load_failures_release_once(monkeypatch, tmp_path, failure):
    _app()
    warnings = []
    monkeypatch.setattr(industrial_filter_dialog.QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    dialog = IndustrialFilterDialog(db_file=str(tmp_path / "new.db"))
    if failure == "construct":
        def fail(*_args):
            raise ValueError("constructor Ω")
        monkeypatch.setattr(industrial_filter_dialog, "_ReferenceThread", fail)
    elif failure == "start":
        def fail(_worker):
            raise ValueError("start Ω")
        monkeypatch.setattr(industrial_filter_dialog._ReferenceThread, "start", fail)
    else:
        dialog.db_file = str(tmp_path / "missing" / "new.db")
    dialog.load_database_references()
    _wait_references(dialog)
    expected = {"construct": "constructor Ω", "start": "start Ω", "query": "unable to open database file"}
    assert warnings == [
        "Could not read references from the selected Metroliza report database: " + expected[failure]
    ]
    assert dialog._reference_thread is None
    assert dialog._reference_progress is None
    assert dialog.load_db_references_button.isEnabled()
    dialog.close()


def test_custom_reference_rows_keep_conversion_exception_outside_warning(monkeypatch):
    from contextlib import contextmanager

    _app()
    calls = []

    class Value:
        def __str__(self):
            calls.append("str")
            raise ValueError("conversion Ω")

    class Connection:
        def execute(self, _sql):
            calls.append("execute")
            return self

        def fetchall(self):
            return [(Value(),)]

    @contextmanager
    def scope(path):
        calls.append(path)
        yield Connection()
        calls.append("closed")

    monkeypatch.setattr(industrial_filter_dialog, "sqlite_connection_scope", scope)
    monkeypatch.setattr(industrial_filter_dialog, "ensure_report_schema", lambda *_args, **_kw: calls.append("ensure"))
    monkeypatch.setattr(industrial_filter_dialog.QMessageBox, "warning", lambda *_args: pytest.fail("must propagate"))
    dialog = IndustrialFilterDialog(db_file="custom")
    with pytest.raises(ValueError, match="conversion Ω"):
        dialog.load_database_references()
    assert calls == ["custom", "ensure", "execute", "closed", "str"]
    assert getattr(dialog, "_reference_thread", None) is None
    dialog.close()


def test_reference_subclass_retains_synchronous_dispatch(tmp_path):
    _app()

    class CustomDialog(IndustrialFilterDialog):
        def _apply_database_references(self, _references):
            pytest.fail("new helper must not dispatch a preexisting subclass hook")

    path = str(tmp_path / "custom.db")
    dialog = CustomDialog(db_file=path)
    dialog.load_database_references()
    assert "0 value(s) loaded" in dialog.source_context_label.text()
    assert not hasattr(dialog, "_reference_thread")
    dialog.close()


def test_stale_completion_identity_preserves_current_request():
    from types import SimpleNamespace
    from metroliza.ui.industrial_filter_dialog import IndustrialFilterDialog

    current, stale = object(), object()
    owner = SimpleNamespace(_reference_thread=current)
    IndustrialFilterDialog._references_finished(owner, stale)
    assert owner._reference_thread is current


def test_successful_native_operation_normal_owner_close_and_quit(tmp_path):
    import subprocess
    import sys
    script = r"""
from contextlib import closing
from pathlib import Path
from threading import Event, Timer
from time import monotonic
import shutil, sqlite3, sys
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox
from metroliza.app.bootstrap import get_or_create_qapplication
from metroliza.ui import detached_threads
from tests.test_industrial_linking_dialog import _prepare_linking_db
app = get_or_create_qapplication(); app.setQuitOnLastWindowClosed(False)
path = _prepare_linking_db(Path(sys.argv[1]))
QMessageBox.question = lambda *args: QMessageBox.StandardButton.Discard
entered, release = Event(), Event()
beats, closed = [], []
def dump(database):
    with closing(sqlite3.connect(database)) as connection:
        return list(connection.iterdump())
from metroliza.ui import industrial_filter_dialog as module
Dialog, Worker = module.IndustrialFilterDialog, module._ReferenceThread
dialog = Dialog(db_file=path)
expected = dump(path)
original_finish = Dialog._references_finished
def finish(owner, worker):
    original_finish(owner, worker)
    assert owner._reference_thread is None
    assert owner.references_edit.toPlainText() == "MET-123"
    assert owner.source_context_label.text() == (
        "Reference source: 1 value(s) loaded from the open Metroliza "
        "report database. Changes stay in this draft until you apply the filters.")
    assert owner.close()
    closed.append(1)
    app.quit()
Dialog._references_finished = finish
start = dialog.load_database_references
field = '_reference_thread'
original_run = Worker.run
def held_run(worker):
    entered.set()
    assert release.wait(9), "native operation barrier expired"
    original_run(worker)
Worker.run = held_run
def quit_after_start():
    if not entered.is_set():
        QTimer.singleShot(5, quit_after_start); return
    worker = getattr(dialog, field)
    assert worker is not None and worker.isRunning()
    assert detached_threads._QUIT_BLOCKERS[id(worker)] is worker
    print('actual operation work started', flush=True)
    Timer(5.2, release.set).start()
    app.quit()
heartbeat = QTimer(); heartbeat.timeout.connect(lambda: beats.append(1)); heartbeat.start(10)
started = monotonic()
QTimer.singleShot(0, start)
QTimer.singleShot(5, quit_after_start)
QTimer.singleShot(12000, lambda: app.exit(99))
assert app.exec() == 0
assert entered.is_set() and release.is_set() and closed == [1]
assert monotonic() - started > 5 and len(beats) > 100
assert not detached_threads.running_threads() and not dialog.isVisible()
assert dump(path) == expected
print('native normal close and saved-reopen complete', len(beats), len(expected), flush=True)
"""
    child = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True, text=True, timeout=20)
    print('industrial actual child exit', child.returncode, child.stdout, child.stderr)
    assert child.returncode == 0, child.stdout + child.stderr
    assert 'native normal close and saved-reopen complete' in child.stdout
    assert 'QWaitCondition' not in child.stderr

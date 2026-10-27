from __future__ import annotations

import pytest

from modules.db import sqlite_connection_scope

try:
    from PyQt6.QtWidgets import QApplication

    from modules import industrial_linking_dialog
    from modules.industrial_linking_dialog import IndustrialLinkingDialog
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    industrial_linking_dialog = None
    IndustrialLinkingDialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

from modules.industrial_data_repository import IndustrialDataRepository
from modules.report_repository import ReportRepository


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial linking dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _persist_report(tmp_path, repository: ReportRepository, *, reference: str):
    source_path = tmp_path / f"{reference}.pdf"
    source_path.write_bytes(f"{reference}-content".encode("utf-8"))
    repository.persist_parsed_report(
        source_path=source_path,
        parser_id="cmm",
        parser_version="1.0",
        template_family="cmm_pdf_header_box",
        template_variant="variant",
        parse_status="parsed",
        metadata={
            "reference": reference,
            "reference_raw": reference,
            "report_date": "2026-05-10",
            "report_time": "10:00:00",
            "part_name": "Housing",
            "revision": "A",
            "sample_number": "1",
            "sample_number_kind": "explicit_sample_number",
            "operator_name": "Operator",
        },
        candidates=(),
        warnings=(),
        measurements=[
            {
                "page_number": 1,
                "row_order": 1,
                "header": "Feature 1",
                "section_name": "Feature 1",
                "feature_label": "Feature 1",
                "characteristic_name": "LOC",
                "characteristic_family": "LOC",
                "description": "Feature 1",
                "ax": "X",
                "nominal": 10.0,
                "tol_plus": 0.1,
                "tol_minus": -0.1,
                "bonus": 0.0,
                "meas": 10.0,
                "dev": 0.0,
                "outtol": 0.0,
            }
        ],
        metadata_version="report_metadata_v1",
        page_count=1,
        measurement_count=1,
        has_nok=False,
        nok_count=0,
        metadata_confidence=1.0,
        identity_hash=f"identity-{reference}",
    )


def _prepare_linking_db(tmp_path) -> str:
    db_path = str(tmp_path / "reports.db")
    report_repository = ReportRepository(db_path)
    report_repository.ensure_schema()
    _persist_report(tmp_path, report_repository, reference="MET-123")

    industrial_repository = IndustrialDataRepository(db_path)
    profile = industrial_repository.upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="plant_a",
        database_type="mssql",
        source_object_name="assembly.events",
        allowed_columns=["reference", "station"],
    )
    industrial_repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=[
            {
                "source_record_key": "PROD-9",
                "reference": "PRODUCTION-999",
                "station": "S1",
            }
        ],
    )
    return db_path


def test_manual_linking_dialog_links_and_clears_different_references(tmp_path):
    _app()
    db_path = _prepare_linking_db(tmp_path)
    dialog = IndustrialLinkingDialog(db_file=db_path)

    assert not dialog.link_button.isEnabled()
    assert not dialog.clear_button.isEnabled()

    dialog.report_table.selectRow(0)
    assert dialog.clear_button.isEnabled()
    assert not dialog.link_button.isEnabled()

    dialog.production_table.selectRow(0)
    assert dialog.link_button.isEnabled()
    dialog.link_selected_records()

    with sqlite_connection_scope(db_path) as conn:
        linked = conn.execute(
            """
            SELECT report_metadata.reference, industrial_records.reference
            FROM industrial_link_candidates
            JOIN parsed_reports ON parsed_reports.id = industrial_link_candidates.report_id
            JOIN report_metadata ON report_metadata.report_id = parsed_reports.id
            JOIN industrial_records
                ON industrial_records.id = industrial_link_candidates.industrial_record_id
            WHERE industrial_link_candidates.status = 'accepted'
            """
        ).fetchone()

    assert linked == ("MET-123", "PRODUCTION-999")

    dialog.report_table.selectRow(0)
    dialog.clear_selected_manual_link()
    with sqlite_connection_scope(db_path) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM industrial_link_candidates").fetchone()[0]

    assert remaining == 0
    dialog.close()


def test_manual_linking_dialog_handles_empty_database_state_and_missing_selection(monkeypatch):
    _app()
    warnings = []
    monkeypatch.setattr(industrial_linking_dialog.QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog = IndustrialLinkingDialog(db_file=None)

    assert dialog.report_table.rowCount() == 0
    assert dialog.production_table.rowCount() == 0
    assert not dialog.link_button.isEnabled()
    assert not dialog.clear_button.isEnabled()
    assert not dialog.auto_link_button.isEnabled()
    assert "Select a Metroliza report database" in dialog.status_label.text()

    dialog.link_selected_records()
    dialog.clear_selected_manual_link()
    dialog.refresh_auto_links()

    assert "Select one Metroliza report and one cached production row" in warnings[0][2]
    assert warnings[1][2] == "Select one Metroliza report."
    dialog.close()


def test_manual_linking_dialog_search_and_auto_refresh(monkeypatch, tmp_path):
    _app()
    db_path = _prepare_linking_db(tmp_path)
    summary = type("Summary", (), {"accepted_links": 1, "ambiguous_reports": 2, "unmatched_reports": 3})()
    monkeypatch.setattr(
        industrial_linking_dialog,
        "materialize_industrial_report_links",
        lambda db_file: summary,
    )
    dialog = IndustrialLinkingDialog(db_file=db_path)

    dialog.report_search_edit.setText("MET-123")
    dialog.production_search_edit.setText("PROD")
    assert dialog.report_table.rowCount() == 1
    assert dialog.production_table.rowCount() == 1

    dialog.refresh_auto_links()
    assert "1 accepted, 2 ambiguous, 3 unmatched" in dialog.status_label.text()
    dialog.close()


def _wait_auto_links(dialog):
    from PyQt6.QtTest import QTest

    for _ in range(1000):
        if getattr(dialog, "_auto_link_thread", None) is None:
            return
        _app().processEvents()
        QTest.qWait(5)
    pytest.fail("auto link refresh did not finish")


def test_auto_link_refresh_literal_unmatched_output(tmp_path):
    _app()
    db_path = _prepare_linking_db(tmp_path)
    dialog = IndustrialLinkingDialog(db_file=db_path)
    dialog.refresh_auto_links()
    _wait_auto_links(dialog)
    assert dialog.status_label.text() == (
        "Auto links refreshed: 0 accepted, 0 ambiguous, 1 unmatched."
    )
    with sqlite_connection_scope(db_path) as conn:
        assert conn.execute("SELECT * FROM industrial_link_candidates").fetchall() == []
    dialog.close()


def test_auto_link_custom_callback_literal_error(monkeypatch, tmp_path):
    _app()
    calls, warnings = [], []

    def custom(db_file):
        calls.append(db_file)
        raise ValueError("literal password=abc Unicode: Ω")

    monkeypatch.setattr(industrial_linking_dialog, "materialize_industrial_report_links", custom)
    monkeypatch.setattr(industrial_linking_dialog.QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    path = _prepare_linking_db(tmp_path)
    dialog = IndustrialLinkingDialog(db_file=path)
    dialog.refresh_auto_links()
    assert calls == [path]
    assert warnings == ["Could not refresh auto links: literal password=abc Unicode: Ω"]
    dialog.close()


def test_native_auto_link_worker_owns_write_and_terminal_lifetime(monkeypatch, tmp_path):
    import threading

    from PyQt6 import sip
    from PyQt6.QtCore import QThread
    from PyQt6.QtTest import QTest

    from metroliza.ui import detached_threads

    app = _app()
    entered, release = threading.Event(), threading.Event()
    original_run = industrial_linking_dialog._AutoLinkThread.run
    owners = []

    def held_run(worker):
        owners.append(QThread.currentThread() is app.thread())
        entered.set()
        if not release.wait(5):
            worker.error = "test barrier timed out"
            return
        original_run(worker)

    monkeypatch.setattr(industrial_linking_dialog._AutoLinkThread, "run", held_run)
    dialog = IndustrialLinkingDialog(db_file=_prepare_linking_db(tmp_path))
    dialog.show()
    dialog.refresh_auto_links()
    worker = dialog._auto_link_thread
    try:
        assert entered.wait(2)
        assert detached_threads.is_registered(worker)
        assert detached_threads._QUIT_BLOCKERS[id(worker)] is worker
        assert not dialog.auto_link_button.isEnabled()
        dialog.refresh_auto_links()
        assert dialog._auto_link_thread is worker
        assert dialog.close() is False
        dialog.accept()
        dialog.reject()
        assert dialog.isVisible()
        QTest.qWait(1100)
        assert dialog._auto_link_progress.isVisible()
        assert not detached_threads.wait_for_all(10)
    finally:
        release.set()
        _wait_auto_links(dialog)
    assert owners == [False]
    assert dialog.status_label.text() == "Auto links refreshed: 0 accepted, 0 ambiguous, 1 unmatched."
    assert not detached_threads.is_registered(worker)
    QTest.qWait(10)
    assert sip.isdeleted(worker)
    assert dialog.auto_link_button.isEnabled()
    dialog.close()


@pytest.mark.parametrize("failure", ["construct", "start", "service"])
def test_auto_link_failures_release_once_with_literal_error(monkeypatch, tmp_path, failure):
    _app()
    warnings = []
    monkeypatch.setattr(industrial_linking_dialog.QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    dialog = IndustrialLinkingDialog(db_file=_prepare_linking_db(tmp_path))
    if failure == "construct":
        def fail(_path):
            raise ValueError("constructor Ω")
        monkeypatch.setattr(industrial_linking_dialog, "_AutoLinkThread", fail)
    elif failure == "start":
        def fail(_worker):
            raise ValueError("start Ω")
        monkeypatch.setattr(industrial_linking_dialog._AutoLinkThread, "start", fail)
    else:
        # A real default-service SQLite failure, without replacing its dispatch.
        dialog.db_file = str(tmp_path / "missing" / "reports.db")
    dialog.refresh_auto_links()
    _wait_auto_links(dialog)
    assert len(warnings) == 1
    expected = {"construct": "constructor Ω", "start": "start Ω", "service": "unable to open database file"}
    assert warnings == ["Could not refresh auto links: " + expected[failure]]
    assert dialog._auto_link_thread is None
    assert dialog._auto_link_progress is None
    assert dialog.auto_link_button.isEnabled()
    dialog.close()


def test_native_auto_link_drops_result_after_database_replacement(monkeypatch, tmp_path):
    import threading

    entered, release = threading.Event(), threading.Event()
    _app()
    original_run = industrial_linking_dialog._AutoLinkThread.run

    def held_run(worker):
        entered.set()
        if release.wait(5):
            original_run(worker)

    monkeypatch.setattr(industrial_linking_dialog._AutoLinkThread, "run", held_run)
    path = _prepare_linking_db(tmp_path)
    dialog = IndustrialLinkingDialog(db_file=path)
    old_status = dialog.status_label.text()
    dialog.refresh_auto_links()
    try:
        assert entered.wait(2)
        dialog.db_file = str(tmp_path / "other.db")
    finally:
        release.set()
        _wait_auto_links(dialog)
    assert dialog.status_label.text() == old_status
    with sqlite_connection_scope(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM industrial_join_rules").fetchone() == (1,)
    dialog.close()


def test_auto_link_subclass_retains_synchronous_dispatch(tmp_path):
    _app()

    class CustomDialog(IndustrialLinkingDialog):
        def _apply_auto_link_summary(self, _summary):
            pytest.fail("new helper must not dispatch a preexisting subclass hook")

    dialog = CustomDialog(db_file=_prepare_linking_db(tmp_path))
    dialog.refresh_auto_links()
    assert dialog.status_label.text() == "Auto links refreshed: 0 accepted, 0 ambiguous, 1 unmatched."
    assert not hasattr(dialog, "_auto_link_thread")
    dialog.close()


def test_stale_completion_identity_preserves_current_request():
    from types import SimpleNamespace
    from metroliza.ui.industrial_linking_dialog import IndustrialLinkingDialog

    current, stale = object(), object()
    owner = SimpleNamespace(_auto_link_thread=current)
    IndustrialLinkingDialog._auto_links_finished(owner, stale)
    assert owner._auto_link_thread is current


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
from metroliza.ui import industrial_linking_dialog as module
from metroliza.industrial import industrial_join_service
industrial_join_service.utc_timestamp = lambda: "2026-01-05T12:00:00+00:00"
Dialog, Worker = module.IndustrialLinkingDialog, module._AutoLinkThread
dialog = Dialog(db_file=path)
oracle = str(Path(sys.argv[1]) / "oracle.db"); shutil.copyfile(path, oracle)
summary = module.materialize_industrial_report_links(oracle)
assert (summary.accepted_links, summary.ambiguous_reports, summary.unmatched_reports) == (0, 0, 1)
expected = dump(oracle)
original_finish = Dialog._auto_links_finished
def finish(owner, worker):
    original_finish(owner, worker)
    assert owner._auto_link_thread is None
    assert owner.status_label.text() == "Auto links refreshed: 0 accepted, 0 ambiguous, 1 unmatched."
    assert owner.close()
    closed.append(1)
    app.quit()
Dialog._auto_links_finished = finish
start = dialog.refresh_auto_links
field = '_auto_link_thread'
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

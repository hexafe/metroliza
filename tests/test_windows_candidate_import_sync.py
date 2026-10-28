"""Deterministic import identity, metadata handoff and cleanup regressions."""
from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QTimer

from metroliza.app import windows_candidate_inference as inference
from metroliza.app import windows_candidate_native_check as native
from metroliza.app import windows_candidate_qualification as core
from metroliza.ui import parsing_dialog as ui

FIXTURES = Path(__file__).parent / "fixtures/windows_candidate/reports"


@pytest.fixture
def metadata_barrier(monkeypatch):
    entered, release = Event(), Event()
    original = ui.MetadataReviewThread.run

    def held(worker):
        entered.set()
        if not release.wait(10):
            return
        original(worker)

    monkeypatch.setattr(ui.MetadataReviewThread, "run", held)
    yield entered, release
    release.set()


@pytest.fixture
def reviewed(tmp_path, qapplication_session, metadata_barrier):
    from metroliza.app.ui_entrypoint import load_main_window_factory
    from metroliza.ui.ui_preferences import UiPreferences
    from PyQt6.QtCore import QSettings

    app = qapplication_session
    reports, _hashes = core._stage_reports(FIXTURES, tmp_path)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = load_main_window_factory()("import-sync-test", None, ui_preferences=UiPreferences(settings))
    window.show()
    window._show_workspace_page("reports")
    assert window.set_directory(str(reports))
    assert window.set_db_file(str(tmp_path / "reports.sqlite"))
    workspace = window.reports_workspace
    try:
        workspace.scan_button.click()
        core._wait(app, lambda: workspace.preflight_thread is None and metadata_barrier[0].is_set(),
                   deadline_s=10, stage="review")
        core._select_exact_reports(workspace)
        assert workspace._metadata_workers_running()
        assert workspace.parse_button.isEnabled()
        yield app, window, workspace
    finally:
        metadata_barrier[1].set()
        native.close_report_owner(window, app)


def test_core_observes_queued_import_before_reading_worker(tmp_path, qapplication_session, metadata_barrier, monkeypatch):
    entered, release = metadata_barrier
    original_select = core._select_exact_reports
    original_close = native.close_report_owner
    clicks = []

    def select(workspace):
        original_select(workspace)
        core._wait(qapplication_session, entered.is_set, deadline_s=10, stage="metadata")
        assert workspace._metadata_workers_running()
        clicks.append(True)
        # This fires only after the real click has returned to GUI event processing.
        QTimer.singleShot(0, release.set)

    def close(window, app):
        release.set()
        original_close(window, app)

    monkeypatch.setattr(core, "_select_exact_reports", select)
    monkeypatch.setattr(native, "close_report_owner", close)
    receipt = {}
    error = None
    try:
        core._run_core(tmp_path, FIXTURES, receipt, qapplication_session)
    except Exception as caught:
        error = caught
    assert error is None, type(error).__name__
    assert clicks == [True]
    assert receipt["database_counts"]["parsed_reports"] == 2


@pytest.mark.parametrize("action", ["cancel", "close", "cleanup"])
def test_cancel_or_close_drops_queued_import(reviewed, metadata_barrier, monkeypatch, action):
    app, window, workspace = reviewed
    workspace.parse_button.click()
    assert workspace.parse_thread is None
    assert workspace._start_pending
    starts = []
    original = ui.ParseReportsThread.start

    def start(worker):
        starts.append(worker)
        original(worker)

    monkeypatch.setattr(ui.ParseReportsThread, "start", start)
    if action == "cancel":
        workspace.stop_parsing()
    elif action == "close":
        assert window.close() is False
    else:
        cancel = workspace._request_active_worker_cancellation

        def cancel_and_release():
            cancel()
            metadata_barrier[1].set()

        monkeypatch.setattr(workspace, "_request_active_worker_cancellation", cancel_and_release)
        native.close_report_owner(window, app)
    metadata_barrier[1].set()
    core._wait(app, lambda: not workspace._metadata_threads and workspace.parse_thread is None,
               deadline_s=10, stage="cleanup")
    assert starts == [], "cancel/close started the pending import"
    operation = getattr(workspace, "import_operation", None)
    assert operation is not None and operation.cancelled and operation.terminal
    assert operation.worker is None
    assert not workspace._after_metadata_idle
    assert not (Path(workspace.db_file)).exists()


@pytest.mark.parametrize("mode", ["fast", "error", "cancel", "close"])
def test_specific_import_survives_fast_completion_error_and_running_cancel(
    reviewed, metadata_barrier, monkeypatch, mode,
):
    from metroliza.parsing import parse_reports_thread as parser

    app, window, workspace = reviewed
    metadata_barrier[1].set()
    core._wait(app, lambda: not workspace._metadata_threads, deadline_s=10, stage="metadata")
    entered, release = Event(), Event()
    batch = parser.parse_new_reports

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return batch(*args, **kwargs)

    if mode in {"cancel", "close"}:
        monkeypatch.setattr(parser, "parse_new_reports", held)
    elif mode == "error":
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_PRIVATE_IMPORT_TEXT")
        monkeypatch.setattr(parser, "parse_new_reports", fail)
    try:
        workspace.parse_button.click()
        worker = workspace.parse_thread
        assert worker is not None
        if mode in {"cancel", "close"}:
            core._wait(app, entered.is_set, deadline_s=10, stage="batch")
            if mode == "cancel":
                workspace.stop_parsing()
            else:
                assert window.close() is False
            release.set()
        # Deliberately let the worker finish and parse_thread be cleared BEFORE observing.
        core._wait(app, lambda: workspace.parse_thread is None, deadline_s=10, stage="import")
        operation = getattr(workspace, "import_operation", None)
        assert operation is not None, "completed import has no durable operation identity"
        from metroliza.app.windows_candidate_import_sync import (
            ImportSyncFailure, wait_import_finished, wait_import_started,
        )
        assert wait_import_started(app, operation) is worker
        if mode == "fast":
            assert wait_import_finished(app, operation).imported_files == 2
        else:
            code = "import_worker_error" if mode == "error" else "import_cancelled"
            with pytest.raises(ImportSyncFailure, match=f"^{code}$"):
                wait_import_finished(app, operation)
        assert operation.terminal
        assert not worker.isRunning() and worker.wait(1000)
        assert "SYNTHETIC_PRIVATE_IMPORT_TEXT" not in repr(operation)
    finally:
        release.set()


def test_cleanup_preserves_primary_failure_in_producer_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "requested_scenario", lambda: "core")
    monkeypatch.setattr(core, "_root", lambda: tmp_path)
    monkeypatch.setattr(core, "_fixture_dir", lambda: FIXTURES)
    monkeypatch.setattr(core, "_ocr_fixture", lambda: FIXTURES / "report-0.pdf")
    monkeypatch.setattr(core, "_runtime_provenance", lambda: {"source_sha": "1" * 40})
    from metroliza.shared import diagnostic_runtime_audit
    monkeypatch.setattr(diagnostic_runtime_audit, "wait_for_host_ready", lambda: None)
    monkeypatch.setattr(native, "run_with_native_mode", lambda operation: operation())

    def execute(root, fixtures, ocr, receipt):
        receipt["stage"] = "selected_import"
        try:
            raise core.ScenarioFailure("import_worker_not_started")
        finally:
            native.close_report_owner(SimpleNamespace(close=lambda: False), SimpleNamespace(processEvents=lambda: None))

    monkeypatch.setattr(core, "_execute_core_checks", execute)
    assert core.run_qualification() == 21
    failed = json.loads((tmp_path / "windows-candidate-result.json").read_text())
    assert failed["failure"] == "import_worker_not_started"
    assert failed["cleanup_failure"] == "candidate_report_owner_close_refused"


def test_inference_retains_import_substage_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(inference, "_stage_reports", lambda *args: (tmp_path, {}))

    def fail(*args):
        try:
            raise inference.InferenceFailure("import_worker_not_started")
        finally:
            native.close_report_owner(SimpleNamespace(close=lambda: False), SimpleNamespace(processEvents=lambda: None))

    monkeypatch.setattr(inference, "_run_gui_import", fail)
    result = inference.run_inference_checks(tmp_path, FIXTURES)
    assert result["failure"] == "import_worker_not_started"
    assert result["failure_stage"] == "import"
    assert result["cleanup_failure"] == "candidate_report_owner_close_refused"


def test_rejected_click_cannot_reuse_an_earlier_terminal_result():
    from metroliza.app.windows_candidate_import_sync import ImportSyncFailure, click_import

    previous = SimpleNamespace(terminal=True, result=object())
    workspace = SimpleNamespace(import_operation=previous, parse_button=SimpleNamespace(click=lambda: None))
    with pytest.raises(ImportSyncFailure, match="^import_not_accepted$"):
        click_import(workspace)


@pytest.mark.parametrize("stage", ["database", "groups", "public_service"])
def test_inference_failure_binds_the_actual_computation_substage(tmp_path, monkeypatch, stage):
    monkeypatch.setattr(inference, "_stage_reports", lambda *args: (tmp_path, {}))
    monkeypatch.setattr(inference, "_run_gui_import", lambda *args: None)
    monkeypatch.setattr(inference, "_report_ids_by_filename", lambda *args: {})

    def counts(*args):
        if stage == "database":
            raise inference.InferenceFailure("database_snapshot_not_closed")
        return {}

    def analysis(database, report_ids, record_stage):
        if stage == "public_service":
            record_stage(stage)
        raise inference.InferenceFailure("group_analysis_not_ready")

    monkeypatch.setattr(inference, "_database_counts", counts)
    monkeypatch.setattr(inference, "_analysis_projection", analysis)
    result = inference.run_inference_checks(tmp_path, FIXTURES)
    assert result["status"] == "failed"
    assert result["failure_stage"] == stage


def test_queued_and_running_imports_have_bounded_deadlines(qapplication_session):
    from metroliza.app.windows_candidate_import_sync import wait_import_finished, wait_import_started

    queued = SimpleNamespace(worker=None, terminal=False)
    with pytest.raises(core.ScenarioFailure, match="^import_start_deadline$"):
        wait_import_started(qapplication_session, queued, seconds=0)
    with pytest.raises(core.ScenarioFailure, match="^import_deadline$"):
        wait_import_finished(qapplication_session, queued, seconds=0)


def test_terminal_gui_delivery_still_waits_for_native_completion(reviewed, metadata_barrier, monkeypatch):
    from PyQt6.QtCore import Qt
    from metroliza.app.windows_candidate_import_sync import wait_import_finished

    app, _window, workspace = reviewed
    metadata_barrier[1].set()
    core._wait(app, lambda: not workspace._metadata_threads, deadline_s=10, stage="metadata")
    entered, release = Event(), Event()
    original = ui.ParseReportsThread.start

    def hold_finished():
        entered.set()
        assert release.wait(10)

    def start(worker):
        worker.finished.connect(hold_finished, type=Qt.ConnectionType.DirectConnection)
        original(worker)

    monkeypatch.setattr(ui.ParseReportsThread, "start", start)
    try:
        workspace.parse_button.click()
        core._wait(app, lambda: entered.is_set() and workspace.parse_thread is None,
                   deadline_s=10, stage="finished_delivery")
        operation = workspace.import_operation
        assert operation.terminal
        with pytest.raises(core.ScenarioFailure, match="^import_worker_join_deadline$"):
            wait_import_finished(app, operation, seconds=0)
        release.set()
        assert wait_import_finished(app, operation).imported_files == 2
    finally:
        release.set()
        if workspace.import_operation.worker is not None:
            assert workspace.import_operation.worker.wait(10000)


def test_worker_start_error_is_terminal_without_a_deleted_thread_handle(reviewed, metadata_barrier, monkeypatch):
    from metroliza.app.windows_candidate_import_sync import ImportSyncFailure, click_import, wait_import_started

    app, _window, workspace = reviewed
    metadata_barrier[1].set()
    core._wait(app, lambda: not workspace._metadata_threads, deadline_s=10, stage="metadata")

    def fail(worker):
        raise RuntimeError("SYNTHETIC_PRIVATE_START_TEXT")

    monkeypatch.setattr(ui.ParseReportsThread, "start", fail)
    monkeypatch.setattr(workspace, "log_and_exit", lambda error: None)
    operation = click_import(workspace)
    app.processEvents()
    assert operation.failed and operation.terminal and operation.worker is None
    with pytest.raises(ImportSyncFailure, match="^import_worker_error$"):
        wait_import_started(app, operation)

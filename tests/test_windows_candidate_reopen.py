"""Real MainWindow reopen coverage for the bounded W04 acceptance subset."""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QSettings, Qt

from metroliza.app.bootstrap import get_or_create_qapplication
from metroliza.app.windows_candidate_reopen import run_reopen_checks
from metroliza.app import windows_candidate_native_check as native
from metroliza.ui.main_window import MainWindow
from metroliza.ui.ui_preferences import UiPreferences


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait(application, predicate, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert predicate()


@pytest.fixture(scope="module")
def application():
    return get_or_create_qapplication()


def _stage_reports(root: Path) -> tuple[Path, dict[str, str]]:
    original = Path(__file__).parent / "fixtures" / "windows_candidate" / "reports"
    reports = root / "reports"
    reports.mkdir()
    for index in range(5):
        shutil.copyfile(original / f"report-{index}.pdf", reports / f"REF001_2024-01-01_{index}.pdf")
    return reports, {path.name: _sha256(path) for path in reports.iterdir()}


def _close_window(application, window) -> None:
    try:
        workspace = getattr(window, "_reports_workspace", None)
        if workspace is not None:
            # Suppress metadata's queued import before any join/event pumping.
            workspace.request_shutdown()
            workspace._after_metadata_idle.clear()
            workspace._start_pending = False
        native.close_report_owner(window, application)
    except BaseException:
        if not any(owner is window for owner in native._UNJOINED_OWNERS):
            native._UNJOINED_OWNERS.append(window)
        raise
    window.deleteLater()
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def _seed_completed_import(application, root: Path) -> tuple[Path, Path, dict[str, str]]:
    reports, hashes = _stage_reports(root)
    database = root / "reports.sqlite"
    settings = QSettings(str(root / "seed.ini"), QSettings.Format.IniFormat)
    window = MainWindow("candidate-reopen-seed", None, ui_preferences=UiPreferences(settings))
    try:
        window.show()
        application.processEvents()
        reports_index = window.navigation_combo.findData("reports")
        assert reports_index >= 0
        window.navigation_list.setCurrentRow(reports_index)
        workspace = window.reports_workspace
        assert window.set_directory(str(reports))
        assert window.set_db_file(str(database))
        workspace.scan_button.click()
        _wait(application, lambda: workspace.preflight_thread is None, timeout_s=30.0)
        assert not database.exists()
        assert workspace.report_planner.model.counts["total"] == 5
        workspace.report_planner.clear.click()
        assert not workspace.parse_button.isEnabled()
        for row in range(workspace.report_planner.model.rowCount()):
            item = workspace.report_planner.model.item_at(row)
            if item is not None and item.display_name in {
                "REF001_2024-01-01_1.pdf",
                "REF001_2024-01-01_3.pdf",
            }:
                assert workspace.report_planner.model.setData(
                    workspace.report_planner.model.index(row, 0),
                    Qt.CheckState.Checked,
                    Qt.ItemDataRole.CheckStateRole,
                )
        started = []

        def observe_import():
            worker = workspace.parse_thread
            if worker is not None and not started:
                started.append(worker)

        # state_changed observes the actual worker before a fast completion can
        # clear parse_thread in the same GUI event dispatch as metadata handoff.
        workspace.state_changed.connect(observe_import)
        try:
            workspace.parse_button.click()
            _wait(application, lambda: bool(started) and workspace.parse_thread is None,
                  timeout_s=45.0)
        finally:
            workspace.state_changed.disconnect(observe_import)
        worker = started[0]
        assert worker.last_parse_result is not None
        assert worker.last_parse_result.imported_files == 2
        assert worker.last_parse_result.intentionally_excluded_files == 3
    finally:
        primary = sys.exc_info()[1]
        try:
            _close_window(application, window)
        except BaseException:
            if primary is None:
                raise
            primary.add_note("candidate_seed_cleanup_failed")
    return database, reports, hashes


@pytest.mark.parametrize("directory", ("plain", "owned # próba"))
def test_reopen_preserves_completed_import_after_real_window_close(application, tmp_path: Path, directory) -> None:
    root = tmp_path / directory
    root.mkdir()
    database, reports, hashes = _seed_completed_import(application, root)

    result = run_reopen_checks(database, reports, hashes)

    assert result["status"] == "passed", result
    assert result["facets"] == {"reopen_preserves_completed_import": "passed"}
    assert result["database"]["counts"] == {
        "source_files": 2,
        "active_locations": 2,
        "parsed_reports": 2,
        "metadata": 2,
        "measurements": 2,
    }
    assert result["database"]["sha256"] == _sha256(database)
    assert len(result["database"]["before_sha256"]) == 64
    assert result["database"]["schema_sha256"]
    assert result["database"]["logical_dump_sha256"]
    assert result["source_hashes"] == hashes
    assert not [database.with_name(database.name + suffix) for suffix in ("-wal", "-shm", "-journal") if database.with_name(database.name + suffix).exists()]


def test_count_observation_closes_its_connection_without_leaving_sidecars(application, tmp_path):
    from metroliza.app.windows_candidate_qualification import _database_observation

    database, _, _ = _seed_completed_import(application, tmp_path)
    before = _sha256(database)
    assert _database_observation(database) == {
        "source_files": 2, "active_locations": 2, "parsed_reports": 2,
        "metadata": 2, "measurements": 2,
    }
    assert _sha256(database) == before
    assert not any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


def test_reopen_rejects_a_sidecar_left_by_the_last_observation(application, tmp_path, monkeypatch):
    from metroliza.app import windows_candidate_reopen as operation

    database, reports, hashes = _seed_completed_import(application, tmp_path)
    original = operation._public_measurements
    calls = []

    def leave_sidecar_after_last_read(path):
        result = original(path)
        calls.append(path)
        if len(calls) == 2:
            path.with_name(path.name + "-journal").write_bytes(b"controlled adverse sidecar")
        return result

    monkeypatch.setattr(operation, "_public_measurements", leave_sidecar_after_last_read)
    result = operation.run_reopen_checks(database, reports, hashes)
    assert result["status"] == "failed"
    assert result["failure_code"] == "database_sidecars_created"


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    (
        (
            "UPDATE report_measurements SET meas = meas + 1 WHERE id = 1",
            "logical_dump_changed_after_reopen",
        ),
        (
            "CREATE TABLE w04_reopen_schema_control (value INTEGER)",
            "schema_changed_after_reopen",
        ),
    ),
)
def test_reopen_rejects_actual_semantic_mutation_after_real_window_rebind(
    application, tmp_path, monkeypatch, mutation, expected_failure
):
    from metroliza.app import windows_candidate_reopen as operation

    database, reports, hashes = _seed_completed_import(application, tmp_path)
    actual_reopen = operation._reopen_window

    def mutate_after_actual_reopen(path, sources):
        actual_reopen(path, sources)
        with closing(sqlite3.connect(path)) as connection:
            changed = connection.execute(mutation)
            if expected_failure == "logical_dump_changed_after_reopen":
                assert changed.rowcount == 1
            else:
                assert connection.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'w04_reopen_schema_control'"
                ).fetchone() == ("w04_reopen_schema_control",)
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")

    monkeypatch.setattr(operation, "_reopen_window", mutate_after_actual_reopen)
    result = operation.run_reopen_checks(database, reports, hashes)

    assert result["status"] == "failed"
    assert result["failure_code"] == expected_failure


@pytest.fixture
def gated_seed(monkeypatch):
    from threading import Event
    from types import SimpleNamespace

    from metroliza.parsing.metadata_review import MetadataReviewReader
    from metroliza.ui.parsing_dialog import _ReportOperations

    helpers = sys.modules[__name__]
    app = get_or_create_qapplication()
    entered, release = Event(), Event()
    owners, deletions, deferred = [], [], []
    read_one = MetadataReviewReader._read_one
    main_window, wait = helpers.MainWindow, helpers._wait
    start_import = _ReportOperations.show_loading_screen

    def read(reader, *args, **kwargs):
        entered.set()
        if not release.wait(20):
            raise RuntimeError("synthetic metadata barrier expired")
        return read_one(reader, *args, **kwargs)

    def create(*args, **kwargs):
        window = main_window(*args, **kwargs)
        owners.append(window)
        def deletion():
            workspace = window.reports_workspace
            deletions.append((workspace.pdf_workers_idle(), window.isVisible()))
        monkeypatch.setattr(window, "deleteLater", deletion)
        return window

    def review(application, predicate, *, timeout_s):
        wait(application, predicate, timeout_s=timeout_s)
        if timeout_s == 30.0:
            wait(application, entered.is_set, timeout_s=10)

    def start(workspace, **kwargs):
        try:
            start_import(workspace, **kwargs)
            deferred.append(workspace._start_pending)
        finally:
            release.set()

    monkeypatch.setattr(MetadataReviewReader, "_read_one", read)
    monkeypatch.setattr(helpers, "MainWindow", create)
    monkeypatch.setattr(helpers, "_wait", review)
    monkeypatch.setattr(_ReportOperations, "show_loading_screen", start)
    state = SimpleNamespace(app=app, entered=entered, release=release,
                            owners=owners, deletions=deletions, deferred=deferred,
                            review=review, start_import=start_import)
    try:
        yield state
    finally:
        release.set()
        for window in owners:
            workspace = window.reports_workspace
            workspace.request_shutdown()
            workspace._after_metadata_idle.clear()
            workspace._start_pending = False
            native.close_report_owner(window, app)
            # Bypass the deletion spy only after external cancellation/join/close.
            main_window.deleteLater(window)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("finish_in_dispatch", [False, True])
def test_actual_seed_waits_for_deferred_metadata_import(
    tmp_path, monkeypatch, gated_seed, finish_in_dispatch,
):
    from metroliza.ui.parsing_dialog import _ReportOperations

    completed = []
    if finish_in_dispatch:
        start = _ReportOperations.show_loading_screen

        def finish(workspace, **kwargs):
            start(workspace, **kwargs)
            worker = workspace.parse_thread
            if worker is not None:
                assert worker.wait(45000)
                gated_seed.app.processEvents()
                completed.append(workspace.parse_thread is None)

        monkeypatch.setattr(_ReportOperations, "show_loading_screen", finish)
    database, reports, hashes = _seed_completed_import(gated_seed.app, tmp_path)
    assert database.is_file()
    assert len(hashes) == 5 and len(list(reports.iterdir())) == 5
    assert gated_seed.deferred[0] is True
    assert completed == ([True] if finish_in_dispatch else [])
    assert gated_seed.deletions == [(True, False)]


@pytest.mark.parametrize("failed_join", [False, True])
def test_actual_seed_cleanup_preserves_primary_and_live_owner(
    tmp_path, monkeypatch, gated_seed, failed_join,
):
    state = gated_seed
    primary = AssertionError("synthetic seed primary")
    workers, original_waits = [], []

    def stop_after_review(application, predicate, *, timeout_s):
        state.review(application, predicate, timeout_s=timeout_s)
        if timeout_s == 30.0:
            workspace = state.owners[-1].reports_workspace
            workers.extend(workspace._metadata_threads)
            assert workers and workers[0].isRunning()
            if failed_join:
                original_waits.append(workers[0].wait)
                monkeypatch.setattr(workers[0], "wait", lambda _ms: False)
            else:
                # An event release at cancellation avoids a time-based retry.
                cancel = workspace._request_active_worker_cancellation
                def cancellation():
                    cancel()
                    state.release.set()
                monkeypatch.setattr(workspace, "_request_active_worker_cancellation", cancellation)
            raise primary

    monkeypatch.setattr(sys.modules[__name__], "_wait", stop_after_review)
    retained = len(native._UNJOINED_OWNERS)
    try:
        with pytest.raises(AssertionError) as caught:
            _seed_completed_import(state.app, tmp_path)
        assert caught.value is primary
        if failed_join:
            assert state.deletions == [], "deletion requested despite live metadata owner"
            assert native._UNJOINED_OWNERS[-1] is state.owners[-1]
            assert "candidate_seed_cleanup_failed" in primary.__notes__
        else:
            assert state.deletions == [(True, False)], "deletion preceded worker join/accepted close"
    finally:
        for worker, original_wait in zip(workers, original_waits):
            monkeypatch.setattr(worker, "wait", original_wait)
        state.release.set()
        del native._UNJOINED_OWNERS[retained:]


@pytest.mark.parametrize("already_stopped", [False, True])
def test_actual_close_suppresses_pending_import_before_pumping(
    tmp_path, monkeypatch, gated_seed, already_stopped,
):
    state = gated_seed
    primary = AssertionError("synthetic pending primary")
    admissions = []

    def stop_after_review(application, predicate, *, timeout_s):
        state.review(application, predicate, timeout_s=timeout_s)
        if timeout_s == 30.0:
            workspace = state.owners[-1].reports_workspace
            assert workspace._defer_until_metadata_idle(lambda: admissions.append(True), user_started=True)
            if already_stopped:
                state.release.set()
                for worker in tuple(workspace._metadata_threads):
                    assert worker.wait(20000)
            cancel = workspace._request_active_worker_cancellation
            def cancellation():
                cancel()
                state.release.set()
            monkeypatch.setattr(workspace, "_request_active_worker_cancellation", cancellation)
            raise primary

    monkeypatch.setattr(sys.modules[__name__], "_wait", stop_after_review)
    with pytest.raises(AssertionError) as caught:
        _seed_completed_import(state.app, tmp_path)
    state.release.set()
    workspace = state.owners[-1].reports_workspace
    for worker in tuple(workspace._metadata_threads):
        assert worker.wait(20000)
    state.app.processEvents()
    assert caught.value is primary
    assert admissions == []
    assert workspace._after_metadata_idle == [] and not workspace._start_pending
    assert state.deletions == [(True, False)]

"""W04 close/refusal/rebind checks using real product windows and workers."""

from __future__ import annotations

import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import sys
from threading import Event
import tempfile
import time
from typing import Any
from unittest.mock import patch
import uuid


FACETS = (
    "active_review_close",
    "active_export_close",
    "dirty_realtime_close_refusal",
    "active_dashboard_rebind",
)


class LifecycleChecksFailure(ValueError):
    """A stable, closed W04 failure code."""


_RETAINED_WINDOWS: list[object] = []


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise LifecycleChecksFailure(code)


def _wait(app, predicate, *, seconds: float, code: str) -> None:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    _require(bool(predicate()), code)


def _logical_sha256(database: Path) -> str:
    from metroliza.reports.db import sqlite_readonly_connection_scope

    _require(database.is_file(), "database_missing")
    with sqlite_readonly_connection_scope(str(database)) as db:
        # SQLite can recreate indexes in a different catalog order on reopen.
        # Preserve every statement and duplicate, while ignoring that order.
        payload = json.dumps(sorted(db.iterdump()), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _thread_running(thread) -> bool:
    if thread is None:
        return False
    try:
        return bool(thread.isRunning())
    except RuntimeError:
        return False


def _new_window(child: Path, label: str):
    from PyQt6.QtCore import QSettings
    from metroliza.app.ui_entrypoint import load_main_window_factory

    preferences_module = import_module("metroliza.ui.ui_preferences")
    settings = QSettings(str(child / f"{label}-settings.ini"), QSettings.Format.IniFormat)
    return load_main_window_factory()(
        f"candidate-{label}", None,
        ui_preferences=preferences_module.UiPreferences(settings),
    )


def _close_seed_owner(window, app) -> None:
    from metroliza.app.windows_candidate_native_check import close_report_owner

    try:
        close_report_owner(window, app)
    except Exception as error:
        _RETAINED_WINDOWS.append(window)
        raise LifecycleChecksFailure("seed_window_cleanup_failed") from error


def _join_report_workers(window, app) -> None:
    from metroliza.app.windows_candidate_native_check import abort_unavailable_after_join_failure

    workspace = getattr(window, "_reports_workspace", None)
    if workspace is None:
        return
    workers = tuple(worker for worker in (workspace.preflight_thread, workspace.parse_thread)
                    if worker is not None)
    workspace._request_active_worker_cancellation()
    if any(not worker.wait(20000) for worker in workers):
        _RETAINED_WINDOWS.append(window)
        abort_unavailable_after_join_failure(window)
        raise LifecycleChecksFailure("report_worker_join_deadline")
    app.processEvents()


def _join_owned_worker(worker, owner, code: str) -> None:
    """Join an owned worker or preserve its exact owner for Job teardown."""
    if not _thread_running(worker) or worker.wait(20000):
        return
    _RETAINED_WINDOWS.append(owner)
    from metroliza.app.windows_candidate_native_check import abort_unavailable_after_join_failure
    abort_unavailable_after_join_failure(owner)
    raise LifecycleChecksFailure(code)


def _review_close(app, child: Path, reports: Path, source_hashes: dict[str, str],
                  result: dict[str, Any]) -> None:
    from PyQt6.QtCore import QCoreApplication, QEvent
    from metroliza.parsing.preflight import ParsePreflightService

    database = child / "review-close.sqlite"
    window = _new_window(child, "review-close")
    entered, release = Event(), Event()
    original = ParsePreflightService.scan_source

    def gated_scan(service, **kwargs):
        entered.set()
        if not release.wait(15.0):
            raise RuntimeError("synthetic review barrier expired")
        return original(service, **kwargs)

    try:
        window.show()
        window._show_workspace_page("reports")
        _require(window.set_directory(str(reports)) and window.set_db_file(str(database)),
                 "review_context_rejected")
        workspace = window.reports_workspace
        with patch.object(ParsePreflightService, "scan_source", gated_scan):
            workspace.scan_button.click()
            worker = workspace.preflight_thread
            _require(worker is not None, "review_worker_missing")
            _wait(app, entered.is_set, seconds=15.0, code="review_barrier_deadline")
            _require(window.close() is False and window.isVisible()
                     and workspace.is_close_deferred(), "review_close_not_deferred")
            release.set()
            _wait(app, lambda: workspace.preflight_thread is None and not window.isVisible(),
                  seconds=45.0, code="review_close_deadline")
        _require(not database.exists(), "review_close_wrote_database")
        from metroliza.app.windows_candidate_import_guards import _source_hashes
        _require(_source_hashes(reports) == source_hashes, "review_close_changed_sources")
        result["facets"]["active_review_close"] = "passed"
        result["evidence"]["review_database_created"] = False
    finally:
        release.set()
        _join_report_workers(window, app)
        if window.isVisible() and not window.close():
            _RETAINED_WINDOWS.append(window)
            raise LifecycleChecksFailure("review_window_close_refused")
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def _seed_report_database(app, child: Path, reports: Path) -> Path:
    from metroliza.app.windows_candidate_import_guards import _select_names

    database = child / "reports.sqlite"
    window = _new_window(child, "seed-import")
    try:
        window.show()
        window._show_workspace_page("reports")
        _require(window.set_directory(str(reports)) and window.set_db_file(str(database)),
                 "seed_context_rejected")
        workspace = window.reports_workspace
        workspace.scan_button.click()
        _wait(app, lambda: workspace.preflight_thread is None, seconds=30.0,
              code="seed_review_deadline")
        model = workspace.report_planner.model
        _require(model.valid and model.counts["ready"] == 5, "seed_review_mismatch")
        _select_names(model, {"REF001_2024-01-01_1.pdf", "REF001_2024-01-01_3.pdf"})
        workspace.parse_button.click()
        worker = workspace.parse_thread
        _require(worker is not None, "seed_import_worker_missing")
        _wait(app, lambda: workspace.parse_thread is None, seconds=45.0,
              code="seed_import_deadline")
        outcome = worker.last_parse_result
        _require(outcome is not None and outcome.imported_files == 2,
                 "seed_import_outcome")
    finally:
        _close_seed_owner(window, app)
    return database


def _export_close(app, child: Path, database: Path, reports: Path,
                  source_hashes: dict[str, str], result: dict[str, Any]) -> None:
    from metroliza.exporting.export_backends import ExcelExportBackend
    from metroliza.exporting.export_outcomes import ExportRunStatus
    from metroliza.app.windows_candidate_ui_checks import _close_window_safely

    baseline = _logical_sha256(database)
    output = child / "cancelled-export.xlsx"
    window = _new_window(child, "export-close")
    entered, release = Event(), Event()
    original = ExcelExportBackend.run
    worker = None
    export_dialog_module = import_module("metroliza.ui.export_dialog")

    def gated_export(backend, thread):
        entered.set()
        if not release.wait(15.0):
            raise RuntimeError("synthetic export barrier expired")
        return original(backend, thread)

    try:
        window.show()
        _require(window.set_db_file(str(database)), "export_context_rejected")
        with patch.object(export_dialog_module.ExportDialog, "_load_dialog_config",
                          return_value={"selected_preset": "fast_diagnostics"}), patch.object(
            export_dialog_module, "save_export_dialog_config"
        ), patch.object(export_dialog_module, "show_export_result_message"), patch.object(
            ExcelExportBackend, "run", gated_export
        ):
            window.launch_export_dialog()
            dialog = window.export_dialog
            _require(dialog is not None and dialog.isVisible(), "export_dialog_missing")
            dialog.excel_file = output
            dialog._set_path_field_value(dialog.excel_file_text_label, output)
            dialog.show_loading_screen()
            worker = dialog.export_thread
            _require(worker is not None, "export_worker_missing")
            _wait(app, entered.is_set, seconds=15.0, code="export_barrier_deadline")
            _require(worker.isRunning(), "export_worker_not_running")
            _require(window.close() is False and window.isVisible()
                     and dialog.is_close_deferred(), "export_close_not_deferred")
            release.set()
            _wait(app, lambda: dialog.export_thread is None and not window.isVisible(),
                  seconds=60.0, code="export_close_deadline")
        run_result = worker.export_run_result
        _require(run_result is not None and run_result.status is ExportRunStatus.CANCELLED,
                 "export_not_cancelled")
        _require(not output.exists(), "cancelled_export_published")
        _require(not tuple(child.glob(".cancelled-export.tmp-*.xlsx")),
                 "cancelled_export_staging_retained")
        _require(_logical_sha256(database) == baseline, "export_changed_database")
        from metroliza.app.windows_candidate_import_guards import _source_hashes
        _require(_source_hashes(reports) == source_hashes, "export_changed_sources")
        result["facets"]["active_export_close"] = "passed"
        result["evidence"].update({
            "export_status": run_result.status.value,
            "cancelled_export_published": False,
            "committed_database_logical_sha256": baseline,
        })
    finally:
        release.set()
        _join_owned_worker(worker, window, "export_worker_join_deadline")
        app.processEvents()
        if window.isVisible():
            error = _close_window_safely(app, window)
            if error is not None:
                _RETAINED_WINDOWS.append(window)
                raise LifecycleChecksFailure(error)


def _realtime_refusal_and_rebind(app, child: Path, result: dict[str, Any]) -> None:
    from PyQt6.QtWidgets import QMessageBox
    from metroliza.app.windows_candidate_ui_checks import (
        _close_window_safely,
        _seed_synthetic_database,
    )
    from metroliza.industrial.realtime.realtime_dashboard_service import RealtimeDashboardService

    first, second = child / "realtime-first.sqlite", child / "realtime-second.sqlite"
    _seed_synthetic_database(first)
    _seed_synthetic_database(second)
    first_hash, second_hash = _logical_sha256(first), _logical_sha256(second)
    window = _new_window(child, "realtime-lifecycle")
    entered, release = Event(), Event()
    worker = None
    original = RealtimeDashboardService.dashboard_snapshot
    source_profiles_module = import_module("metroliza.ui.industrial_source_profiles_dialog")

    def gated_snapshot(service, **kwargs):
        entered.set()
        if not release.wait(15.0):
            raise RuntimeError("synthetic dashboard barrier expired")
        return original(service, **kwargs)

    try:
        window.show()
        _require(window.set_db_file(str(first)), "realtime_context_rejected")
        with patch.object(tempfile, "tempdir", str(child)):
            window.launch_realtime_industrial_monitoring_dialog()
        dialog = window.realtime_monitoring_dialog
        _require(dialog is not None and dialog.isVisible() and dialog.db_file == str(first),
                 "realtime_dialog_missing")
        dialog.open_source_profiles_dialog()
        app.processEvents()
        editor = dialog.source_window
        _require(editor is not None and editor.isVisible(), "source_editor_missing")
        editor.source_name_edit.setText("Unsaved synthetic source")
        with patch.object(source_profiles_module.QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            _require(window.close() is False and window.isVisible()
                     and editor.isVisible() and not window._close_deferred_for_realtime,
                     "dirty_source_close_not_refused")
        result["facets"]["dirty_realtime_close_refusal"] = "passed"

        with patch.object(source_profiles_module.QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            _require(editor.close(), "source_editor_discard_refused")
        app.processEvents()
        _require(window.isVisible() and dialog.source_window is None,
                 "dirty_refusal_armed_root_close")

        with patch.object(RealtimeDashboardService, "dashboard_snapshot", gated_snapshot):
            dialog._schedule_dashboard_write(open_after=False)
            _wait(app, entered.is_set, seconds=15.0, code="dashboard_barrier_deadline")
            worker = dialog.dashboard_thread
            _require(worker is not None and worker.isRunning(), "dashboard_worker_missing")
            _require(window.set_db_file(str(second)), "dashboard_workspace_rebind_rejected")
            _require(dialog.db_file == str(first)
                     and window._pending_realtime_database == str(second),
                     "dashboard_context_not_retained")
            release.set()
            _wait(app, lambda: dialog.dashboard_thread is None
                  and dialog.db_file == str(second)
                  and window._pending_realtime_database is None,
                  seconds=30.0, code="dashboard_rebind_deadline")
        _require(window.realtime_monitoring_dialog is dialog and dialog.isVisible(),
                 "realtime_owner_replaced")
        _require(_logical_sha256(first) == first_hash
                 and _logical_sha256(second) == second_hash,
                 "dashboard_rebind_changed_database")
        result["facets"]["active_dashboard_rebind"] = "passed"
        result["evidence"].update({
            "dirty_close_deferred": False,
            "dashboard_worker_class": type(worker).__name__,
            "rebound_same_dialog": True,
            "rebind_target_logical_sha256": second_hash,
        })
    finally:
        release.set()
        _join_owned_worker(worker, window, "dashboard_worker_join_deadline")
        app.processEvents()
        error = _close_window_safely(app, window)
        if error is not None:
            _RETAINED_WINDOWS.append(window)
            raise LifecycleChecksFailure(error)


def _run(scratch: Path, fixtures: Path, app, result: dict[str, Any]) -> None:
    from metroliza.app.windows_candidate_import_guards import _source_hashes
    from metroliza.app.windows_candidate_qualification import ScenarioFailure, _stage_reports

    child = scratch / f"lifecycle-checks-{uuid.uuid4().hex}"
    child.mkdir()
    try:
        reports, source_hashes = _stage_reports(fixtures, child)
    except ScenarioFailure as error:
        raise LifecycleChecksFailure("fixture_staging_failed") from error
    _require(_source_hashes(reports) == source_hashes, "fixture_hash_mismatch")
    result["evidence"]["relative_artifact_dir"] = child.name
    result["evidence"]["fixture_count"] = len(source_hashes)
    _review_close(app, child, reports, source_hashes, result)
    database = _seed_report_database(app, child, reports)
    _export_close(app, child, database, reports, source_hashes, result)
    _realtime_refusal_and_rebind(app, child, result)
    _require(_source_hashes(reports) == source_hashes, "final_source_hash_mismatch")


def run_lifecycle_checks(scratch_directory: str | Path,
                         fixture_directory: str | Path) -> dict[str, Any]:
    """Run real W04 worker ownership checks and return fixed, closed evidence."""
    from metroliza.app.bootstrap import get_or_create_qapplication

    result: dict[str, Any] = {
        "schema_version": 1,
        "runtime_context": "packaged" if getattr(sys, "frozen", False) else "source",
        "status": "failed",
        "facets": {name: "not_run" for name in FACETS},
        "error_codes": [],
        "evidence": {
            "relative_artifact_dir": None,
            "fixture_count": None,
            "review_database_created": None,
            "export_status": None,
            "cancelled_export_published": None,
            "committed_database_logical_sha256": None,
            "dirty_close_deferred": None,
            "dashboard_worker_class": None,
            "rebound_same_dialog": None,
            "rebind_target_logical_sha256": None,
            "qpa": None,
            "native_windows_assessed": False,
        },
    }
    try:
        scratch, fixtures = Path(scratch_directory), Path(fixture_directory)
        _require(scratch.is_dir() and not scratch.is_symlink(), "scratch_invalid")
        _require(fixtures.is_dir() and not fixtures.is_symlink(), "fixtures_invalid")
        app = get_or_create_qapplication()
        result["evidence"]["qpa"] = app.platformName()
        result["evidence"]["native_windows_assessed"] = (
            os.name == "nt" and app.platformName().casefold() == "windows"
        )
        _run(scratch, fixtures, app, result)
        _require(all(value == "passed" for value in result["facets"].values()),
                 "facet_incomplete")
        result["status"] = "passed"
    except LifecycleChecksFailure as error:
        result["error_codes"].append(str(error))
    except Exception:
        result["error_codes"].append("unexpected_exception")
    return result

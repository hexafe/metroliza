"""Synthetic W04 import guards through the ordinary Reports workspace.

The caller owns ``scratch`` and supplies the reviewed public fixture directory.
This callable is inert in normal startup.  A short barrier at the real parser
batch boundary makes the active-import close observation deterministic; the
ordinary worker, parser and repository still perform all work.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Event
import time
from metroliza.reports.db import sqlite_readonly_connection_scope

from typing import Any
from unittest.mock import patch
import uuid


FACETS = (
    "hidden_selection_import",
    "stale_source_rereview",
    "duplicate_review",
    "active_import_cancel_close",
)
_RETAINED_WINDOWS: list[object] = []


class ImportGuardsFailure(ValueError):
    """A closed, stable W04 failure code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ImportGuardsFailure(code)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wait(app, predicate, *, seconds: float, code: str) -> None:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    _require(bool(predicate()), code)


def _database_state(database: Path) -> dict[str, Any]:
    _require(database.is_file(), "committed_database_missing")
    # A legitimate duplicate review opens the WAL database read-only and may
    # leave an empty WAL and SHM. Read the full SQLite view, including any WAL,
    # while owned workers are joined; the host checks strict sidecar shape and
    # immutable contents only after the complete Job has exited.
    with sqlite_readonly_connection_scope(str(database)) as db:
        names = tuple(sorted(row[0] for row in db.execute(
            "SELECT file_name FROM source_file_locations WHERE is_active = 1"
        )))
        dump = "\n".join(db.iterdump()).encode("utf-8")
    return {
        "sha256": _sha256(database),
        "logical_sha256": hashlib.sha256(dump).hexdigest(),
        "active_file_names": names,
    }


def _committed_unchanged(database: Path, baseline: dict[str, Any]) -> bool:
    current = _database_state(database)
    return (current["logical_sha256"] == baseline["logical_sha256"]
            and current["active_file_names"] == baseline["active_file_names"])


def _source_hashes(reports: Path) -> dict[str, str]:
    return {path.name: _sha256(path) for path in sorted(reports.iterdir()) if path.is_file()}


def _review(app, workspace, *, ready: int, code: str) -> None:
    workspace.scan_button.click()
    _wait(app, lambda: workspace.preflight_thread is None, seconds=30.0, code=code + "_deadline")
    model = workspace.report_planner.model
    _require(model.valid and model.counts["total"] == 5 and model.counts["ready"] == ready,
             code + "_counts")


def _select_names(model, names: set[str]) -> tuple[str, ...]:
    from PyQt6.QtCore import Qt

    model.clear_selection()
    for row in range(model.rowCount()):
        item = model.item_at(row)
        if item is not None and item.display_name in names:
            _require(model.setData(model.index(row, 0), Qt.CheckState.Checked,
                                   Qt.ItemDataRole.CheckStateRole), "selection_rejected")
    selected = model.selected_ids
    _require(len(selected) == len(names), "selection_count_mismatch")
    return selected


def _check_duplicate_rows(model, expected_names) -> set[str]:
    from PyQt6.QtCore import Qt
    from metroliza.parsing.preflight import ParsePreflightStatus

    duplicate_names = set()
    for row in range(model.rowCount()):
        item = model.item_at(row)
        if item is not None and item.status is ParsePreflightStatus.DUPLICATE:
            duplicate_names.add(item.display_name)
            _require(not model.flags(model.index(row, 0))
                     & Qt.ItemFlag.ItemIsUserCheckable, "duplicate_checkable")
            _require(not model.setData(model.index(row, 0), Qt.CheckState.Checked,
                                       Qt.ItemDataRole.CheckStateRole), "duplicate_selected")
    _require(duplicate_names == expected_names and len(model.selected_ids) == 3,
             "duplicate_review_mismatch")
    return duplicate_names


def _run(scratch: Path, fixtures: Path, app, result: dict[str, Any]) -> None:
    from PyQt6.QtCore import QCoreApplication, QEvent, QSettings
    from metroliza.app.windows_candidate_qualification import ScenarioFailure, _stage_reports
    from metroliza.parsing import parse_reports_thread
    from importlib import import_module
    from metroliza.app.ui_entrypoint import load_main_window_factory

    MainWindow = load_main_window_factory()
    UiPreferences = import_module("metroliza.ui.ui_preferences").UiPreferences

    child = scratch / f"import-guards-{uuid.uuid4().hex}"
    child.mkdir()
    try:
        reports, staged_hashes = _stage_reports(fixtures, child)
    except ScenarioFailure as error:
        raise ImportGuardsFailure("fixture_staging_failed") from error
    database = child / "reports.sqlite"
    result["evidence"]["relative_artifact_dir"] = child.name
    settings = QSettings(str(child / "isolated-settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow("candidate-import-guards", None, ui_preferences=UiPreferences(settings))
    release = Event()
    try:
        window.show()
        app.processEvents()
        index = window.navigation_combo.findData("reports")
        _require(index >= 0, "reports_navigation_missing")
        window.navigation_list.setCurrentRow(index)
        workspace = window.reports_workspace
        _require(window.set_directory(str(reports)) and window.set_db_file(str(database)),
                 "workspace_context_rejected")
        _review(app, workspace, ready=5, code="initial_review")
        _require(not database.exists(), "review_wrote_database")

        # A filter hides both approved rows while the source model retains them.
        model = workspace.report_planner.model
        expected_names = {f"REF001_2024-01-01_{number}.pdf" for number in (1, 3)}
        selected = _select_names(model, expected_names)
        workspace.report_planner.search.setText("_0.pdf")
        _require(workspace.report_planner.proxy.rowCount() == 1, "filter_row_count")
        _require(model.selected_ids == selected and workspace.parse_button.isEnabled()
                 and workspace.parse_button.text() == "Import 2 selected reports",
                 "hidden_selection_lost")
        for page in ("home", "tools", "reports"):
            window._show_workspace_page(page)
            _require(window.reports_workspace is workspace and model.selected_ids == selected,
                     "navigation_selection_lost")
        workspace.parse_button.click()
        first_worker = workspace.parse_thread
        _require(first_worker is not None, "first_import_worker_missing")
        _wait(app, lambda: workspace.parse_thread is None, seconds=45.0,
              code="first_import_deadline")
        first_outcome = first_worker.last_parse_result
        _require(first_outcome is not None and first_outcome.imported_files == 2
                 and first_outcome.intentionally_excluded_files == 3,
                 "hidden_selection_import_outcome")
        committed = _database_state(database)
        _require(set(committed["active_file_names"]) == expected_names,
                 "hidden_selection_persisted_names")
        _require(_source_hashes(reports) == staged_hashes, "source_changed_after_import")
        result["facets"]["hidden_selection_import"] = "passed"
        result["evidence"]["initial_imported"] = first_outcome.imported_files

        workspace.report_planner.search.clear()
        _review(app, workspace, ready=3, code="duplicate_review")
        duplicate_names = _check_duplicate_rows(model, expected_names)
        _require(_committed_unchanged(database, committed), "duplicate_review_changed_database")
        result["facets"]["duplicate_review"] = "passed"
        result["evidence"]["duplicate_count"] = len(duplicate_names)

        # Change one staged source after review. The real import worker must
        # reject its reviewed fingerprint, then a fresh review must recover.
        drift_name = "REF001_2024-01-01_0.pdf"
        drift_path = reports / drift_name
        original_bytes = drift_path.read_bytes()
        _select_names(model, {drift_name})
        drift_worker = None
        try:
            drift_path.write_bytes(b"changed synthetic source after review")
            workspace.parse_button.click()
            drift_worker = workspace.parse_thread
            _require(drift_worker is not None, "drift_worker_missing")
            _wait(app, lambda: workspace.parse_thread is None, seconds=45.0,
                  code="drift_import_deadline")
            drift_outcome = drift_worker.last_parse_result
            _require(drift_outcome is not None and drift_outcome.imported_files == 0
                     and drift_outcome.preflight_changed_files == 1,
                     "drift_not_rejected")
            _require(not model.selected_ids and not workspace.parse_button.isEnabled(),
                     "drift_selection_not_cleared")
            _require(_committed_unchanged(database, committed), "drift_changed_database")
        finally:
            if workspace.parse_thread is not None:
                workspace.stop_parsing()
                if not workspace.parse_thread.wait(20000):
                    raise ImportGuardsFailure("drift_worker_join_deadline")
                app.processEvents()
            drift_path.write_bytes(original_bytes)
        _require(_source_hashes(reports) == staged_hashes, "drift_source_not_restored")
        _review(app, workspace, ready=3, code="drift_rereview")
        _require(model.valid and len(model.selected_ids) == 3,
                 "drift_rereview_selection")
        _require(_committed_unchanged(database, committed), "drift_rereview_changed_database")
        result["facets"]["stale_source_rereview"] = "passed"
        result["evidence"]["drift_rejected"] = drift_outcome.preflight_changed_files

        # Hold the *real* worker just before its real batch processing call.
        # Close requests cancellation while that worker is alive; releasing the
        # barrier lets its ordinary cancellation check decide the outcome.
        _select_names(model, {drift_name})
        entered = Event()
        real_batch = parse_reports_thread.parse_new_reports

        def gated_batch(*args, **kwargs):
            entered.set()
            if not release.wait(15.0):
                raise RuntimeError("synthetic batch barrier expired")
            return real_batch(*args, **kwargs)

        with patch.object(parse_reports_thread, "parse_new_reports", gated_batch):
            workspace.parse_button.click()
            active_worker = workspace.parse_thread
            _require(active_worker is not None, "active_import_worker_missing")
            _wait(app, entered.is_set, seconds=15.0, code="active_import_barrier_deadline")
            _require(active_worker.isRunning() and window.isVisible(),
                     "active_import_not_running")
            _require(window.close() is False and window.isVisible()
                     and workspace.is_close_deferred(), "active_close_not_deferred")
            release.set()
            _wait(app, lambda: workspace.parse_thread is None and not window.isVisible(),
                  seconds=45.0, code="active_close_deadline")
        active_outcome = active_worker.last_parse_result
        _require(active_outcome is not None and active_outcome.imported_files == 0
                 and active_outcome.cancelled_files >= 1,
                 "active_import_not_cancelled")
        _require(_committed_unchanged(database, committed),
                 "active_close_changed_committed_database")
        _require(_source_hashes(reports) == staged_hashes, "active_close_changed_sources")
        result["facets"]["active_import_cancel_close"] = "passed"
        result["evidence"].update({
            "cancelled_files": active_outcome.cancelled_files,
            "cancel_barrier_stage": "real_parse_batch_entry",
            "committed_database_sha256": committed["sha256"],
            "committed_logical_sha256": committed["logical_sha256"],
            "database_sha256_after_close": _sha256(database),
            "sidecars_after_window_close": [
                suffix for suffix in ("-wal", "-shm", "-journal")
                if database.with_name(database.name + suffix).exists()
            ],
            "source_hashes": staged_hashes,
        })
    finally:
        release.set()
        workspace = getattr(window, "_reports_workspace", None)
        live = () if workspace is None else tuple(
            worker for worker in (workspace.preflight_thread, workspace.parse_thread)
            if worker is not None
        )
        if workspace is not None:
            workspace._request_active_worker_cancellation()
        if any(not worker.wait(20000) for worker in live):
            _RETAINED_WINDOWS.append(window)
            from metroliza.app.windows_candidate_native_check import abort_unavailable_after_join_failure
            abort_unavailable_after_join_failure(window)
            raise ImportGuardsFailure("worker_join_deadline")
        app.processEvents()
        closed = window.close()
        if not closed or window.isVisible():
            _RETAINED_WINDOWS.append(window)
            raise ImportGuardsFailure("window_close_refused")
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def run_import_guard_checks(scratch_directory: str | Path, fixture_directory: str | Path) -> dict[str, Any]:
    """Execute W04 guards with public fixtures and return only closed evidence."""
    from metroliza.app.bootstrap import get_or_create_qapplication

    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "failed",
        "facets": {name: "not_run" for name in FACETS},
        "error_codes": [],
        "evidence": {
            "relative_artifact_dir": None,
            "initial_imported": None,
            "duplicate_count": None,
            "drift_rejected": None,
            "cancelled_files": None,
            "cancel_barrier_stage": None,
            "committed_database_sha256": None,
            "committed_logical_sha256": None,
            "database_sha256_after_close": None,
            "sidecars_after_window_close": None,
            "source_hashes": None,
        },
    }
    try:
        scratch, fixtures = Path(scratch_directory), Path(fixture_directory)
        _require(scratch.is_dir() and not scratch.is_symlink(), "scratch_invalid")
        _require(fixtures.is_dir() and not fixtures.is_symlink(), "fixtures_invalid")
        _run(scratch, fixtures, get_or_create_qapplication(), result)
        _require(all(status == "passed" for status in result["facets"].values()),
                 "facet_incomplete")
        result["status"] = "passed"
    except ImportGuardsFailure as error:
        result["error_codes"].append(str(error))
    except Exception:
        result["error_codes"].append("unexpected_exception")
    return result

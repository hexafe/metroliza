"""Bounded UI and private-dashboard observations for a Windows candidate.

The caller owns a private scratch directory. This callable uses synthetic local
SQLite only. It records generated HTML source, not browser layout or DOM proof.
Native geometry requires the caller's current Windows QPA and expected DPR.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any
from unittest.mock import patch
import uuid


class UiChecksFailure(ValueError):
    """A stable, closed failure code."""


_RETAINED_WINDOWS: list[object] = []


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise UiChecksFailure(code)


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


def _seed_synthetic_database(database: Path) -> int:
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
    from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition

    profile = IndustrialDataRepository(str(database)).upsert_source_profile(
        profile_key="synthetic_assembly",
        profile_name="Synthetic Assembly",
        source_db_alias="synthetic_local",
        database_type="mssql",
        source_object_name="synthetic_events",
    )
    repository = RealtimeSampleRepository(str(database))
    signal = repository.upsert_signal_definition(SignalDefinition(
        source_profile_id=profile.id,
        signal_key="cycle_time",
        metric_name="cycle_time_s",
        unit="s",
        nominal=10.0,
        usl=12.0,
    ))
    batch = repository.insert_samples([
        IndustrialSample(
            source_profile_id=profile.id, signal_id=signal.id,
            source_record_key="SYNTHETIC-1", event_time="2026-06-13T10:00:00Z",
            metric_name="cycle_time_s", value=10.25, station="S1",
        ),
        IndustrialSample(
            source_profile_id=profile.id, signal_id=signal.id,
            source_record_key="SYNTHETIC-2", event_time="2026-06-13T10:01:00Z",
            metric_name="cycle_time_s", value=11.0, station="S1",
        ),
    ])
    _require(batch.inserted == 2, "synthetic_samples_not_inserted")
    return signal.id


def _check_dashboard(app, window, child: Path, database: Path, result: dict[str, Any]) -> None:
    from metroliza.industrial.realtime.realtime_dashboard_service import RealtimeDashboardService

    snapshot = RealtimeDashboardService(str(database)).dashboard_snapshot()
    signals = snapshot.get("signals", [])
    _require(len(signals) == 1 and signals[0].get("signal_key") == "cycle_time"
             and len(signals[0].get("samples", [])) == 2,
             "synthetic_dashboard_snapshot_mismatch")

    # The real default output must be created under the caller's private job.
    # Only construction is redirected; the product still owns its directory
    # and all Windows handle/DACL validation performed by that constructor.
    with patch.object(tempfile, "tempdir", str(child)):
        window.launch_realtime_industrial_monitoring_dialog()
    dialog = window.realtime_monitoring_dialog
    _require(dialog is not None and dialog.isVisible() and dialog.db_file == str(database),
             "realtime_dialog_not_opened")
    owner = dialog._dashboard_temp_dir
    _require(owner is not None, "private_dashboard_owner_missing")
    private_dir = Path(owner.name)
    _require(private_dir.parent == child.resolve() and private_dir.is_dir(),
             "private_dashboard_directory_mismatch")
    if os.name == "nt":
        _require(bool(getattr(owner, "_handle", None)), "private_directory_pin_missing")
    else:
        _require(private_dir.stat().st_mode & 0o777 == 0o700,
                 "private_directory_mode_mismatch")

    dialog._schedule_dashboard_write(open_after=False)
    _wait(app, lambda: dialog.dashboard_thread is not None or dialog.last_dashboard_path is not None,
          seconds=5.0, code="dashboard_worker_not_started")
    _wait(app, lambda: dialog.dashboard_thread is None and dialog.last_dashboard_path is not None,
          seconds=20.0, code="dashboard_worker_deadline")
    private_html = dialog.last_dashboard_path
    _require(private_html == dialog._default_dashboard_path() and private_html.is_file(),
             "private_dashboard_output_missing")
    html = private_html.read_text(encoding="utf-8")
    _require(html.startswith("<!doctype html>")
             and 'data-section="signal-charts"' in html
             and "cycle_time_s" in html and "10.25" in html,
             "dashboard_source_content_mismatch")
    _require(not any(marker in html.lower() for marker in (
        "http://", "https://", "<script", "<link", "fetch(", "xmlhttprequest"
    )), "dashboard_source_external_dependency")
    retained = child / "dashboard.html"
    shutil.copyfile(private_html, retained)
    _require(_sha256(retained) == _sha256(private_html), "dashboard_copy_mismatch")
    result["facets"]["private_dashboard_generation"] = "passed"
    result["facets"]["offline_html_source"] = "passed"
    result["evidence"].update({
        "sample_count": 2,
        "dashboard_sha256": _sha256(private_html),
        "retained_html": retained.name,
        "owned_handle_observed": bool(getattr(owner, "_handle", None)) if os.name == "nt" else None,
        "private_directory_removed_after_close": None,
    })
    _require(dialog.close(), "realtime_dialog_close_refused")
    app.processEvents()
    _require(not private_dir.exists(), "private_dashboard_cleanup_failed")
    result["evidence"]["private_directory_removed_after_close"] = True


def _screen_evidence(app) -> dict[str, Any]:
    screen = app.primaryScreen()
    _require(screen is not None, "primary_screen_missing")
    dpr = float(screen.devicePixelRatio())
    size = screen.size()
    return {
        "qpa": app.platformName(),
        "dpr": round(dpr, 3),
        "physical_screen": [round(size.width() * dpr), round(size.height() * dpr)],
        "logical_screen": [size.width(), size.height()],
    }


def _geometry_dialog(dialog, app, controls: tuple[object, ...], *,
                     focus_controls: tuple[object, ...] = (), scroll=None) -> dict[str, Any]:
    from PyQt6.QtCore import QPoint, QRect
    from PyQt6.QtTest import QTest

    dialog.show()
    QTest.qWait(5)
    app.processEvents()
    available = dialog.screen().availableGeometry()
    requested = (
        min(max(760, dialog.minimumWidth()), available.width() - 40),
        min(max(480, dialog.minimumHeight()), available.height() - 40),
    )
    _require(requested[0] >= dialog.minimumWidth() and requested[1] >= dialog.minimumHeight(),
             "geometry_available_area_too_small")
    dialog.resize(*requested)
    app.processEvents()
    _require(dialog.size().width() == requested[0] and dialog.size().height() == requested[1],
             "geometry_resize_rejected")
    _require(available.contains(dialog.frameGeometry()), "geometry_frame_outside_screen")
    bounds = QRect(QPoint(0, 0), dialog.size())
    for control in controls:
        if scroll is not None and scroll.isAncestorOf(control):
            scroll.ensureWidgetVisible(control)
            app.processEvents()
            position = control.mapTo(scroll.viewport(), QPoint(0, 0))
            _require(0 <= position.y()
                     and position.y() + control.height() <= scroll.viewport().height(),
                     "geometry_scrolled_control_unreachable")
        _require(control.isVisibleTo(dialog), "geometry_control_unavailable")
        rectangle = QRect(control.mapTo(dialog, QPoint(0, 0)), control.size())
        _require(bounds.contains(rectangle), "geometry_control_clipped")
    for control in focus_controls:
        _require(control.isEnabled(), "geometry_focus_control_disabled")
        control.setFocus()
        app.processEvents()
        _require(control.hasFocus(), "geometry_control_not_focusable")
    return {
        "client": [dialog.width(), dialog.height()],
        "frame": [dialog.frameGeometry().width(), dialog.frameGeometry().height()],
    }


def _check_native_geometry(app, window, child: Path, database: Path,
                           expected_dpr: float | None, result: dict[str, Any]) -> None:
    from metroliza.ui.industrial_data_dialog import IndustrialDataDialog
    from metroliza.ui.industrial_source_profiles_dialog import IndustrialSourceProfilesDialog
    from metroliza.ui.industrial_sync_dialog import IndustrialSyncDialog

    _require(app.platformName().casefold() == "windows", "native_qpa_mismatch")
    _require(expected_dpr is not None and expected_dpr > 0, "expected_dpr_missing")
    screen = result["evidence"]["screen"]
    _require(abs(screen["dpr"] - expected_dpr) <= 0.05, "native_dpr_mismatch")
    _require(screen["physical_screen"] == [1920, 1080], "native_physical_screen_mismatch")
    _require(window.screen().availableGeometry().contains(window.frameGeometry()),
             "main_window_frame_outside_screen")
    config = child / "synthetic-sources.yaml"
    dialogs = (
        IndustrialDataDialog(db_file=str(database)),
        IndustrialSourceProfilesDialog(db_file=str(database), config_path=config),
        IndustrialSyncDialog(db_file=str(database), config_path=config),
    )
    try:
        data, profiles, sync = dialogs
        geometry = {
            "industrial_data": _geometry_dialog(
                data, app, (data.status_label, data.sync_button),
                focus_controls=(data.sync_button,), scroll=data.content_scroll,
            ),
            "source_profiles": _geometry_dialog(
                profiles, app, (profiles.status_label, profiles.timestamp_column_edit),
                focus_controls=(profiles.timestamp_column_edit,), scroll=profiles.form_scroll,
            ),
            "industrial_sync": _geometry_dialog(sync, app, (
                sync.select_all_sources_button, sync.current_source_only_button,
                sync.close_button, sync.test_connection_button, sync.sync_now_button,
                sync.fetch_csv_summary_button, sync.cancel_sync_button,
            ), focus_controls=(sync.select_all_sources_button,
                               sync.current_source_only_button, sync.close_button),
                scroll=sync.content_scroll),
        }
        first = sync.select_all_sources_button.geometry()
        second = sync.current_source_only_button.geometry()
        _require(first.intersected(second).isEmpty(), "sync_bulk_controls_overlap")
        result["evidence"]["dialog_geometry"] = geometry
        result["facets"]["industrial_geometry"] = "passed"
    finally:
        if not _close_dialogs_safely(app, dialogs):
            raise UiChecksFailure("geometry_dialog_cleanup_refused")


def _close_dialogs_safely(app, dialogs) -> bool:
    from PyQt6.QtCore import QCoreApplication, QEvent

    complete = True
    for dialog in dialogs:
        try:
            closed = dialog.close()
            app.processEvents()
            if not closed or dialog.isVisible():
                raise UiChecksFailure("dialog_close_refused")
        except Exception:
            _RETAINED_WINDOWS.append(dialog)
            complete = False
            continue
        dialog.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return complete


def _close_window_safely(app, window) -> str | None:
    """Never delete the Qt owner while its worker or close refusal remains."""
    from PyQt6.QtCore import QCoreApplication, QEvent

    dialog = getattr(window, "realtime_monitoring_dialog", None)
    if dialog is not None:
        dialog.request_shutdown()
        worker = getattr(dialog, "dashboard_thread", None)
        if worker is not None and not worker.wait(20000):
            _RETAINED_WINDOWS.append(window)
            return "dashboard_worker_join_deadline"
        app.processEvents()
    closed = window.close()
    app.processEvents()
    if not closed or window.isVisible():
        _RETAINED_WINDOWS.append(window)
        return "window_close_refused"
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    return None


def run_ui_checks(scratch_directory: str | Path, *, expected_dpr: float | None = None) -> dict[str, Any]:
    """Run real UI checks; native geometry is unassessed outside Windows."""
    from PyQt6.QtCore import QSettings
    from metroliza.app.bootstrap import get_or_create_qapplication
    from metroliza.ui.main_window import MainWindow
    from metroliza.ui.ui_preferences import UiPreferences

    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "failed",
        "facets": {
            "private_dashboard_generation": "not_run",
            "offline_html_source": "not_run",
            "industrial_geometry": "not_assessed",
            "browser_rendering": "not_assessed",
        },
        "error_codes": [],
        "evidence": {
            "relative_artifact_dir": None,
            "screen": None,
            "sample_count": None,
            "dashboard_sha256": None,
            "retained_html": None,
            "owned_handle_observed": None,
            "private_directory_removed_after_close": None,
            "dialog_geometry": None,
            "browser_rendered": False,
        },
    }
    window = None
    app = None
    try:
        scratch = Path(scratch_directory)
        _require(scratch.is_dir() and not scratch.is_symlink(), "scratch_invalid")
        child = scratch / f"ui-checks-{uuid.uuid4().hex}"
        child.mkdir()
        result["evidence"]["relative_artifact_dir"] = child.name
        database = child / "synthetic.sqlite"
        _seed_synthetic_database(database)
        app = get_or_create_qapplication()
        result["evidence"]["screen"] = _screen_evidence(app)
        settings = QSettings(str(child / "ui.ini"), QSettings.Format.IniFormat)
        window = MainWindow("candidate-ui-checks", None, ui_preferences=UiPreferences(settings))
        window.show()
        app.processEvents()
        _require(window.set_db_file(str(database)), "main_window_database_rejected")
        _check_dashboard(app, window, child, database, result)
        if sys.platform == "win32" and expected_dpr is not None:
            _check_native_geometry(app, window, child, database, expected_dpr, result)
        result["status"] = (
            "passed" if result["facets"]["industrial_geometry"] == "passed" else "partial"
        )
    except UiChecksFailure as error:
        result["error_codes"].append(str(error))
    except Exception:
        result["error_codes"].append("unexpected_exception")
    finally:
        if window is not None and app is not None:
            try:
                cleanup_error = _close_window_safely(app, window)
            except Exception:
                _RETAINED_WINDOWS.append(window)
                cleanup_error = "window_cleanup_exception"
            if cleanup_error is not None:
                result["error_codes"].append(cleanup_error)
                result["status"] = "failed"
    return result

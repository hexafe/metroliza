"""Gated, synthetic filesystem denial controls for real dashboard owners.

Only the caller's disposable directory is used. A Windows sharing-denial handle
causes actual cleanup failure; product ACL, cleanup and worker code are unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
from unittest.mock import patch
import uuid

from metroliza.app.windows_candidate_ui_checks import (
    _close_window_safely, _require, _seed_synthetic_database, _sha256, _wait,
)

FACETS = ("private_creation_denial", "explicit_output_survives", "unowned_sibling_survives",
          "idle_cleanup_denial_retry", "active_cleanup_denial_retry")


@contextmanager
def _window(child):
    from PyQt6.QtCore import QSettings
    from metroliza.app.bootstrap import get_or_create_qapplication
    from metroliza.ui.main_window import MainWindow
    from metroliza.ui.ui_preferences import UiPreferences

    child.mkdir()
    database = child / "synthetic.sqlite"
    _seed_synthetic_database(database)
    app = get_or_create_qapplication()
    settings = QSettings(str(child / "ui.ini"), QSettings.Format.IniFormat)
    window = MainWindow("candidate-privacy", None, ui_preferences=UiPreferences(settings))
    try:
        window.show()
        app.processEvents()
        _require(window.set_db_file(str(database)), "privacy_database_rejected")
        yield app, window
    finally:
        _require(_close_window_safely(app, window) is None, "privacy_window_cleanup_failed")


def _open_realtime(window, child, *, temporary_root):
    import metroliza.ui.realtime_industrial_monitoring_dialog as module

    with patch.object(tempfile, "tempdir", str(temporary_root)), patch.object(
        module, "default_industrial_source_config_path", return_value=child / "unused-sources.yaml"
    ):
        window.launch_realtime_industrial_monitoring_dialog()
    dialog = window.realtime_monitoring_dialog
    _require(dialog is not None and dialog.isVisible(), "privacy_dialog_missing")
    return dialog


def _creation_and_explicit_output(child, facets):
    import metroliza.ui.realtime_industrial_monitoring_dialog as module

    with _window(child) as (app, window):
        rejected_parent = child / "not-a-directory"
        rejected_parent.write_bytes(b"SYNTHETIC retained parent")
        sentinel = child / "unowned.txt"
        sentinel.write_bytes(b"SYNTHETIC retained sibling")
        dialog = _open_realtime(window, child, temporary_root=rejected_parent)
        _require(dialog._dashboard_temp_dir is None, "creation_denial_not_observed")
        _require(dialog.write_dashboard() is None and dialog.dashboard_thread is None,
                 "creation_denial_started_output")
        _require(not list(child.rglob("*.html")), "creation_denial_left_html")
        _require("Private temporary dashboard storage is unavailable" in dialog.dashboard_status_label.text(),
                 "creation_denial_notice_missing")
        _require(str(rejected_parent) not in dialog.dashboard_status_label.text()
                 and str(rejected_parent) not in dialog.diagnostics_text.toPlainText(),
                 "creation_denial_private_text_leaked")
        facets["private_creation_denial"] = "passed"
        destination = child / "explicit-output.html"
        with patch.object(module.QFileDialog, "getSaveFileName", return_value=(str(destination), "HTML files (*.html)")):
            dialog.choose_dashboard_path()
        _require(dialog.write_dashboard() == destination, "explicit_output_not_written")
        _require(b'data-section="signal-charts"' in destination.read_bytes(), "explicit_output_invalid")
        before = _sha256(destination)
        _require(window.close(), "explicit_output_close_refused")
        app.processEvents()
        _require(destination.is_file() and _sha256(destination) == before, "explicit_output_removed")
        _require(sentinel.read_bytes() == b"SYNTHETIC retained sibling"
                 and rejected_parent.read_bytes() == b"SYNTHETIC retained parent", "unowned_storage_changed")
        facets["explicit_output_survives"] = "passed"
        facets["unowned_sibling_survives"] = "passed"


@contextmanager
def _hold_without_delete_share(path):
    _require(os.name == "nt", "native_sharing_control_required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x3, None, 3, 0x80, None)
    _require(handle not in (None, ctypes.c_void_p(-1).value), "sharing_control_handle_unavailable")
    try:
        yield
    finally:
        primary = sys.exception()
        closed = bool(kernel.CloseHandle(handle))
        if primary is None:
            _require(closed, "sharing_control_handle_close_failed")


@contextmanager
def _active_writer(app, dialog, active):
    from metroliza.industrial.realtime.realtime_dashboard_service import RealtimeDashboardService
    from metroliza.app.windows_candidate_native_check import abort_unavailable_after_join_failure

    if not active:
        yield
        return
    entered, release = Event(), Event()
    original = RealtimeDashboardService.dashboard_snapshot
    worker = None

    def delayed_snapshot(service):
        entered.set()
        _require(release.wait(10), "privacy_writer_barrier_timeout")
        return original(service)

    with patch.object(RealtimeDashboardService, "dashboard_snapshot", delayed_snapshot):
        try:
            dialog._schedule_dashboard_write(open_after=False)
            _wait(app, entered.is_set, seconds=5, code="privacy_writer_not_started")
            worker = dialog.dashboard_thread
            _require(worker is not None and worker.isRunning(), "privacy_writer_not_running")
            yield
        finally:
            release.set()
            if worker is not None and not worker.wait(20000):
                abort_unavailable_after_join_failure(dialog)
                _require(False, "privacy_writer_join_failed")
            app.processEvents()


def _cleanup_denial(child, facets, *, active):
    with _window(child) as (app, window):
        sentinel = child / "unowned.txt"
        sentinel.write_bytes(b"SYNTHETIC preserved")
        dialog = _open_realtime(window, child, temporary_root=child)
        owner = dialog._dashboard_temp_dir
        _require(owner is not None and bool(getattr(owner, "_handle", None)), "privacy_pin_missing")
        directory = Path(owner.name)
        _require(directory.parent == child.resolve(), "privacy_owned_directory_mismatch")
        locked_file = directory / "delete-denial.txt"
        locked_file.write_bytes(b"SYNTHETIC sharing denial")
        with _hold_without_delete_share(locked_file):
            with _active_writer(app, dialog, active):
                _require(not window.close() and window.isVisible(), "privacy_close_not_refused")
                if active:
                    _require(dialog.is_close_deferred(), "privacy_active_close_not_deferred")
            _wait(app, dialog.dashboard_cleanup_retry_required, seconds=5, code="privacy_cleanup_failure_missing")
            _require(window.isVisible() and dialog._dashboard_temp_dir is owner and directory.is_dir(),
                     "privacy_owner_lost_on_denial")
            _require(window.workspace_notice_label.text() ==
                     "Private dashboard storage could not be removed. Close again to retry.",
                     "privacy_retry_notice_mismatch")
            _require(str(directory) not in window.workspace_notice_label.text(), "privacy_cleanup_path_leaked")
        _require(window.close(), "privacy_retry_close_refused")
        app.processEvents()
        _require(not directory.exists() and dialog._dashboard_temp_dir is None, "privacy_retry_not_removed")
        _require(sentinel.read_bytes() == b"SYNTHETIC preserved", "privacy_retry_changed_sibling")
        facets["active_cleanup_denial_retry" if active else "idle_cleanup_denial_retry"] = "passed"


def run_privacy_checks(scratch_directory):
    result = {"schema_version": 1, "status": "failed", "error_codes": [],
              "runtime_context": "packaged" if getattr(sys, "frozen", False) else "source",
              "facets": dict.fromkeys(FACETS, "not_run")}
    if any(os.getenv(name) != "1" for name in ("METROLIZA_STARTUP_SMOKE", "METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION")):
        result["error_codes"] = ["privacy_qualification_gate_missing"]
        return result
    try:
        scratch = Path(scratch_directory)
        _require(scratch.is_dir() and not scratch.is_symlink(), "privacy_scratch_invalid")
        child = scratch / ("privacy-checks-" + uuid.uuid4().hex)
        child.mkdir()
        _creation_and_explicit_output(child / "creation", result["facets"])
        if os.name == "nt":
            _cleanup_denial(child / "idle", result["facets"], active=False)
            _cleanup_denial(child / "active", result["facets"], active=True)
            result["status"] = "passed"
        else:
            result["facets"].update(idle_cleanup_denial_retry="not_assessed", active_cleanup_denial_retry="not_assessed")
            result["status"] = "partial"
    except Exception:
        result["error_codes"] = ["privacy_negative_control_failed"]
    return result

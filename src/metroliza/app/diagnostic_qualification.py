"""Explicit synthetic package qualification, gated by the existing startup smoke.

This is test tooling inside the executable, not an incident collector. Its only
input is a hash-pinned public PDF in an explicitly selected scratch directory.
It cannot select the application's measurement database or business reports.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from importlib import import_module
from pathlib import Path

SCENARIOS = frozenset(
    {"normal", "hard_exit", "handled_failure", "preview", "idle", "flood", "concurrent"}
)
FIXTURE_SHA256 = "ca500bd52afc2551560e7c0009851906a0d3bec6b35282e20703c1e298da608b"
FAILURE_STAGES = frozenset(
    {"root", "application", "workflows", "preview", "flood", "receipt"}
)
FAILURE_REASONS = frozenset(
    {
        "invalid_qualification_root",
        "qualification_barrier_timeout",
        "qualification_fixture_mismatch",
        "qualification_output_exists",
        "qualification_result_mismatch",
        "qualification_import_failed",
        "qualification_incident_missing",
        "qualification_measurements_missing",
        "qualification_export_failed",
        "qualification_export_unavailable",
        "qualification_filename_control_unavailable",
        "qualification_preview_unavailable",
        "qualification_menu_unavailable",
        "qualification_cleanup_failed",
        "unexpected",
    }
)
PREVIEW_CLEANUP_STATUSES = frozenset({"not_attempted", "complete", "failed"})


class _PreviewFailure(ValueError):
    def __init__(self, reason: str, cleanup: str):
        super().__init__(reason if reason in FAILURE_REASONS else "unexpected")
        self.cleanup = (
            cleanup if type(cleanup) is str and cleanup in PREVIEW_CLEANUP_STATUSES else "failed"
        )


def _failure_reason(error: Exception) -> str:
    candidate = error.args[0] if error.args and type(error.args[0]) is str else None
    return candidate if candidate in FAILURE_REASONS else "unexpected"


def requested_scenario() -> str | None:
    scenario = os.getenv("METROLIZA_DIAGNOSTIC_QUALIFICATION")
    if os.getenv("METROLIZA_STARTUP_SMOKE") == "1" and scenario in SCENARIOS:
        return scenario
    return None


def _root() -> Path:
    root = Path(os.environ["METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT"])
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("invalid_qualification_root")
    return root


def _ordinary_user() -> bool:
    if os.name == "nt":
        import ctypes

        return ctypes.windll.shell32.IsUserAnAdmin() == 0
    return os.geteuid() != 0


def _integrity_level() -> str:
    if os.name != "nt":
        return "not_windows"
    import ctypes
    from ctypes import wintypes

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [("Label", SID_AND_ATTRIBUTES)]

    class SID_IDENTIFIER_AUTHORITY(ctypes.Structure):
        _fields_ = [("Value", wintypes.BYTE * 6)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.IsValidSid.argtypes = [ctypes.c_void_p]
    advapi.GetSidIdentifierAuthority.argtypes = [ctypes.c_void_p]
    advapi.GetSidIdentifierAuthority.restype = ctypes.POINTER(SID_IDENTIFIER_AUTHORITY)
    advapi.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi.GetSidSubAuthorityCount.restype = ctypes.POINTER(wintypes.BYTE)
    advapi.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    advapi.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    token = wintypes.HANDLE()
    try:
        if not advapi.OpenProcessToken(
            kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)
        ):
            return "unavailable"
        required = wintypes.DWORD()
        advapi.GetTokenInformation(token, 25, None, 0, ctypes.byref(required))
        if not 0 < required.value <= 256:
            return "unavailable"
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi.GetTokenInformation(
            token, 25, buffer, required.value, ctypes.byref(required)
        ):
            return "unavailable"
        sid = ctypes.cast(buffer, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents.Label.Sid
        if not sid or not advapi.IsValidSid(sid):
            return "unavailable"
        authority = advapi.GetSidIdentifierAuthority(sid)
        count = advapi.GetSidSubAuthorityCount(sid)
        if (
            not authority
            or tuple(authority.contents.Value) != (0, 0, 0, 0, 0, 16)
            or not count
            or not 0 < count.contents.value <= 8
        ):
            return "unavailable"
        rid = advapi.GetSidSubAuthority(sid, count.contents.value - 1)
        if not rid:
            return "unavailable"
        return {
            0x1000: "low",
            0x2000: "medium",
            0x3000: "high",
            0x4000: "system",
        }.get(int(rid.contents.value), "other")
    except Exception:
        return "unavailable"
    finally:
        if token:
            kernel.CloseHandle(token)


def write_receipt(scenario: str, stage: str) -> None:
    if scenario not in SCENARIOS or stage not in {"startup_ready", "ready", "complete", "failed"}:
        raise ValueError("invalid_qualification_receipt")
    payload = {
        "schema_version": 1, "scenario": scenario, "stage": stage,
        "packaged": bool(getattr(sys, "frozen", False)),
        "console_none": sys.stdout is None and sys.stderr is None,
        "ordinary_user": _ordinary_user(),
        "integrity_level": _integrity_level(),
    }
    root = _root()
    stage_path = root / (".receipt-" + uuid.uuid4().hex)
    with stage_path.open("x", encoding="ascii") as stream:
        json.dump(payload, stream, sort_keys=True)
    names = {
        "startup_ready": "startup.json",
        "ready": "qualification-ready.json",
        "complete": "qualification-complete.json",
        "failed": "qualification-failed.json",
    }
    name = names[stage]
    stage_path.replace(root / name)


def _write_failure(root: Path, stage: str, error: Exception) -> None:
    if stage not in FAILURE_STAGES:
        stage = "application"
    payload = {"schema_version": 1, "stage": stage, "reason": _failure_reason(error)}
    if type(error) is _PreviewFailure:
        payload["cleanup"] = (
            error.cleanup
            if type(error.cleanup) is str and error.cleanup in PREVIEW_CLEANUP_STATUSES
            else "failed"
        )
    stage_path = root / (".failure-" + uuid.uuid4().hex)
    with stage_path.open("x", encoding="ascii") as stream:
        json.dump(payload, stream, sort_keys=True)
    stage_path.replace(root / "failure.json")


def _wait_for_finish(root: Path, *, seconds: float = 10) -> None:
    from PyQt6.QtWidgets import QApplication

    deadline = time.monotonic() + seconds
    while not (root / "finish").exists() and time.monotonic() < deadline:
        QApplication.instance().processEvents()
        time.sleep(0.02)


def _wait_for_concurrent_start(root: Path, *, seconds: float = 10) -> None:
    from PyQt6.QtWidgets import QApplication

    (root / "waiting").touch(exist_ok=False)
    deadline = time.monotonic() + seconds
    while not (root / "start").exists() and time.monotonic() < deadline:
        QApplication.instance().processEvents()
        time.sleep(0.02)
    if not (root / "start").is_file():
        raise ValueError("qualification_barrier_timeout")


def _workflows(root: Path, *, fail_import: bool) -> None:
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.parsing.parse_reports_thread import ParseReportsThread
    from metroliza.parsing.preflight import ImportPlan, ParsePreflightService
    from metroliza.reports.db import sqlite_connection_scope
    from metroliza.shared.parse_contracts import ParseRequest

    with (root / "fixture.pdf").open("rb") as stream:
        fixture = stream.read(128 * 1024 + 1)
    if hashlib.sha256(fixture).hexdigest() != FIXTURE_SHA256:
        raise ValueError("qualification_fixture_mismatch")
    source = root / "reports"
    source.mkdir()  # Exclusive scratch; never reuse an existing user operation.
    document = source / "synthetic.pdf"
    document.write_bytes(fixture)
    database, workbook = root / "scratch.sqlite", root / "scratch.xlsx"
    if database.exists() or workbook.exists():
        raise ValueError("qualification_output_exists")
    request = ParseRequest(
        source_directory=str(source),
        db_file=str(database),
        metadata_parsing_mode="light",
    )
    preflight = ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode="light",
    )
    worker = ParseReportsThread(ImportPlan.all_ready(request, preflight))
    if fail_import:
        document.unlink()
    worker.run()
    if fail_import:
        if worker.last_parse_result.imported_files != 0:
            raise ValueError("qualification_result_mismatch")
        return
    if worker.last_parse_result.imported_files != 1:
        raise ValueError("qualification_import_failed")
    with sqlite_connection_scope(str(database)) as connection:
        if connection.execute("SELECT COUNT(*) FROM report_measurements").fetchone()[0] < 1:
            raise ValueError("qualification_measurements_missing")
    export = ExportDataThread(ExportRequest(
        paths=AppPaths(db_file=str(database), excel_file=str(workbook)),
        options=ExportOptions(generate_summary_sheet=False),
    ))
    export.run()
    if not workbook.is_file() or export.export_run_result is None:
        raise ValueError("qualification_export_failed")


def _complete_preview_save_dialog(app, chosen: Path, deadline: float, automation) -> None:
    from PyQt6.QtWidgets import QDialogButtonBox, QFileDialog, QLineEdit

    for widget in app.topLevelWidgets():
        if not isinstance(widget, QFileDialog) or not widget.isVisible():
            continue
        buttons = widget.findChild(QDialogButtonBox)
        if buttons is None:
            continue
        if time.monotonic() >= deadline:
            buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
            return
        widget.selectFile(chosen.name)
        filename = widget.findChild(QLineEdit, "fileNameEdit")
        if filename is None:
            automation["filename_control_available"] = False
            buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
            return
        filename.setText(chosen.name)
        buttons.button(QDialogButtonBox.StandardButton.Save).click()
        return


def _preview_main_window(root: Path):
    from PyQt6.QtCore import QSettings

    main_module = import_module("metroliza.ui.main_window")
    preferences_module = import_module("metroliza.ui.ui_preferences")
    settings = QSettings(str(root / "qualification-ui.ini"), QSettings.Format.IniFormat)
    return main_module.MainWindow(
        "diagnostic-qualification", None,
        ui_preferences=preferences_module.UiPreferences(settings),
    )


def _preview_dialog_from_help(app, window):
    incident_module = import_module("metroliza.ui.incident_dialog")

    window.show()
    app.processEvents()
    menu = window.help_menu
    menu_action = menu.menuAction()
    if (
        not window.isVisible()
        or menu_action not in window.menuBar().actions()
        or not menu_action.isVisible()
        or not menu_action.isEnabled()
    ):
        raise ValueError("qualification_menu_unavailable")
    actions = [
        action for action in menu.actions()
        if action.text().replace("&", "").replace("…", "...") == "Diagnostic incidents..."
    ]
    if len(actions) != 1 or not actions[0].isEnabled() or not actions[0].isVisible():
        raise ValueError("qualification_menu_unavailable")
    actions[0].trigger()
    app.processEvents()
    dialogs = [
        dialog for dialog in window.findChildren(incident_module.IncidentDialog)
        if dialog.isVisible() and dialog.parent() is window
    ]
    if len(dialogs) != 1:
        raise ValueError("qualification_preview_unavailable")
    return dialogs[0]


def _close_preview_windows(window) -> str:
    from PyQt6.QtWidgets import QDialog

    if window is None:
        return "not_attempted"
    status = "complete"
    try:
        widgets = [*window.findChildren(QDialog), window]
    except Exception:
        widgets = [window]
        status = "failed"
    for widget in widgets:
        try:
            if not widget.close():
                status = "failed"
        except Exception:
            status = "failed"
    return status


def _export_preview_dialog(app, dialog, root: Path) -> None:
    from PyQt6.QtCore import Qt, QTimer

    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    if dialog.reports_table.rowCount() < 1:
        raise ValueError("qualification_incident_missing")
    dialog.reports_table.selectRow(0)
    app.processEvents()
    if not dialog.preview.toPlainText() or not dialog.export_button.isEnabled():
        raise ValueError("qualification_preview_unavailable")
    chosen = root / "selected.zip"
    timer = QTimer(dialog)
    timer.setInterval(50)
    deadline = time.monotonic() + 5
    automation = {"filename_control_available": True}

    def choose_file():
        _complete_preview_save_dialog(app, chosen, deadline, automation)

    timer.timeout.connect(choose_file)
    timer.start()
    dialog.export_button.click()
    timer.stop()
    if not automation["filename_control_available"]:
        raise ValueError("qualification_filename_control_unavailable")
    if not chosen.is_file():
        raise ValueError("qualification_export_unavailable")


def _preview_export(root: Path) -> None:
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    window = None
    failure = None
    try:
        window = _preview_main_window(root)
        dialog = _preview_dialog_from_help(app, window)
        _export_preview_dialog(app, dialog, root)
    except Exception as error:
        failure = _failure_reason(error)
    finally:
        cleanup = _close_preview_windows(window)
    if failure is not None:
        raise _PreviewFailure(failure, cleanup)
    if cleanup == "failed":
        raise _PreviewFailure("qualification_cleanup_failed", cleanup)


def _flood() -> None:
    from metroliza.shared.diagnostic_events import WorkflowOperation, WorkflowStage
    from metroliza.shared.workflow_diagnostics import start_workflow_trace

    trace = start_workflow_trace(WorkflowOperation.LOCAL_EXPORT)
    for _ in range(10_000):
        trace.stage(WorkflowStage.OUTPUT_STAGING)
    trace.finish_export(completed=True, cancelled=False)


def _run_work(scenario: str, root: Path) -> None:
    if scenario == "concurrent":
        _wait_for_concurrent_start(root)
    if scenario in {"normal", "hard_exit", "handled_failure", "concurrent"}:
        _workflows(root, fail_import=scenario == "handled_failure")
    elif scenario == "preview":
        _preview_export(root)
    elif scenario == "flood":
        _flood()


def run_qualification(scenario: str) -> int:
    if scenario != requested_scenario():
        return 20
    root: Path | None = None
    failure_stage = "application"
    try:
        from metroliza.app.bootstrap import get_or_create_qapplication

        app = get_or_create_qapplication()
        failure_stage = "root"
        root = _root()
        failure_stage = "receipt"
        write_receipt(scenario, "startup_ready")
        failure_stage = {
            "preview": "preview",
            "flood": "flood",
        }.get(scenario, "workflows")
        _run_work(scenario, root)
        failure_stage = "receipt"
        write_receipt(scenario, "ready")
        if scenario in {"handled_failure", "idle"}:
            failure_stage = "application"
            _wait_for_finish(root)
        if scenario in {"hard_exit", "concurrent"}:
            time.sleep(0.2)
            os._exit(9)  # Explicit test-owned synthetic scenario only.
        failure_stage = "receipt"
        write_receipt(scenario, "complete")
        app.processEvents()
        return 0
    except Exception as error:
        if root is not None:
            try:
                _write_failure(root, failure_stage, error)
            except Exception:
                pass
        try:
            write_receipt(scenario, "failed")
        except Exception:
            pass
        return 21

"""Explicit synthetic package qualification, gated by the existing startup smoke.

This is test tooling inside the executable, not an incident collector. Its only
input is a hash-pinned public PDF in an explicitly selected scratch directory.
It cannot select the application's measurement database or business reports.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid

SCENARIOS = frozenset({"normal", "hard_exit", "handled_failure", "preview", "idle", "flood"})
FIXTURE_SHA256 = "ca500bd52afc2551560e7c0009851906a0d3bec6b35282e20703c1e298da608b"


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


def write_receipt(scenario: str, stage: str) -> None:
    if scenario not in SCENARIOS or stage not in {"ready", "complete", "failed"}:
        raise ValueError("invalid_qualification_receipt")
    payload = {
        "schema_version": 1, "scenario": scenario, "stage": stage,
        "packaged": bool(getattr(sys, "frozen", False)),
        "console_none": sys.stdout is None and sys.stderr is None,
        "ordinary_user": _ordinary_user(),
    }
    root = _root()
    stage_path = root / (".receipt-" + uuid.uuid4().hex)
    with stage_path.open("x", encoding="ascii") as stream:
        json.dump(payload, stream, sort_keys=True)
    stage_path.replace(root / "qualification.json")


def _wait_for_finish(root: Path, *, seconds: float = 10) -> None:
    from PyQt6.QtWidgets import QApplication

    deadline = time.monotonic() + seconds
    while not (root / "finish").exists() and time.monotonic() < deadline:
        QApplication.instance().processEvents()
        time.sleep(0.02)


def _workflows(root: Path, *, fail_import: bool) -> None:
    from metroliza.parsing.parse_reports_thread import ParseReportsThread
    from metroliza.parsing.preflight import ImportPlan, ParsePreflightService
    from metroliza.shared.parse_contracts import ParseRequest
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.exporting.contracts import AppPaths, ExportRequest, ExportOptions

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
    request = ParseRequest(source_directory=str(source), db_file=str(database), metadata_parsing_mode="light")
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
    with sqlite3.connect(database) as connection:
        if connection.execute("SELECT COUNT(*) FROM report_measurements").fetchone()[0] < 1:
            raise ValueError("qualification_measurements_missing")
    export = ExportDataThread(ExportRequest(
        paths=AppPaths(db_file=str(database), excel_file=str(workbook)),
        options=ExportOptions(generate_summary_sheet=False),
    ))
    export.run()
    if not workbook.is_file() or export.export_run_result is None:
        raise ValueError("qualification_export_failed")


def _preview_export(root: Path) -> None:
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog
    from metroliza.ui.incident_dialog import open_incident_viewer

    app = QApplication.instance()
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    dialog = open_incident_viewer()
    app.processEvents()
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

    def choose_file():
        for widget in app.topLevelWidgets():
            if isinstance(widget, QFileDialog) and widget.isVisible():
                buttons = widget.findChild(QDialogButtonBox)
                if buttons is None:
                    continue
                if time.monotonic() >= deadline:
                    buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
                else:
                    widget.selectFile(str(chosen))
                    buttons.button(QDialogButtonBox.StandardButton.Save).click()

    timer.timeout.connect(choose_file)
    timer.start()
    dialog.export_button.click()
    timer.stop()
    dialog.close()
    if not chosen.is_file():
        raise ValueError("qualification_export_unavailable")


def _flood() -> None:
    from metroliza.shared.diagnostic_events import WorkflowOperation, WorkflowStage
    from metroliza.shared.workflow_diagnostics import start_workflow_trace

    trace = start_workflow_trace(WorkflowOperation.LOCAL_EXPORT)
    for _ in range(10_000):
        trace.stage(WorkflowStage.OUTPUT_STAGING)
    trace.finish_export(completed=True, cancelled=False)


def run_qualification(scenario: str) -> int:
    if scenario != requested_scenario():
        return 20
    try:
        from metroliza.app.bootstrap import get_or_create_qapplication

        app = get_or_create_qapplication()
        root = _root()
        if scenario in {"normal", "hard_exit", "handled_failure"}:
            _workflows(root, fail_import=scenario == "handled_failure")
        elif scenario == "preview":
            _preview_export(root)
        elif scenario == "flood":
            _flood()
        write_receipt(scenario, "ready")
        if scenario in {"handled_failure", "idle"}:
            _wait_for_finish(root)
        if scenario == "hard_exit":
            time.sleep(0.2)
            os._exit(9)  # Explicit test-owned synthetic scenario only.
        write_receipt(scenario, "complete")
        app.processEvents()
        return 0
    except Exception:
        try:
            write_receipt(scenario, "failed")
        except Exception:
            pass
        return 21

"""Safe OOXML parsing regressions for both acceptance-operation copies."""
from __future__ import annotations

import ast
import inspect
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest
from defusedxml.common import DefusedXmlException
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication
from threading import Event

from metroliza.exporting.execution import ExportOutcomeKind

from metroliza.app import windows_candidate_xlsx as application_xlsx
from scripts import windows_candidate_xlsx as standalone_xlsx


@pytest.mark.parametrize("module", (application_xlsx, standalone_xlsx))
def test_ooxml_reader_rejects_dtd_and_entity_payloads(tmp_path: Path, module) -> None:
    archive_path = tmp_path / "unsafe.xlsx"
    payload = b'<!DOCTYPE x [<!ENTITY expansion "unexpected">]><x>&expansion;</x>'
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("xl/workbook.xml", payload)

    with zipfile.ZipFile(archive_path) as archive, pytest.raises(DefusedXmlException):
        module._xml(archive, "xl/workbook.xml")


@pytest.mark.parametrize("module", (application_xlsx, standalone_xlsx))
def test_each_ooxml_copy_uses_safe_parser_at_both_parse_boundaries(module) -> None:
    source = inspect.getsource(module)
    calls = [
        ast.unparse(node.func)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
    ]

    assert calls.count("SafeET.fromstring") == 2
    assert "ET.fromstring" not in calls


def test_core_qualification_uses_only_the_canonical_xlsx_module() -> None:
    from metroliza.app import windows_candidate_qualification as qualification

    source = inspect.getsource(qualification)
    assert "from metroliza.app.windows_candidate_xlsx import run_export_checks" in source
    assert "from windows_candidate_xlsx import run_export_checks" not in source


@pytest.mark.skipif(os.name != "nt", reason="native Windows W07 discriminator")
def test_native_canonical_w07_export_and_cancellation(tmp_path: Path, candidate_application) -> None:
    result = application_xlsx.run_export_checks(tmp_path)
    assert result["status"] == "passed", (
        "native_w07_failed:"
        f"{result.get('failure_stage', 'unavailable')}:"
        f"{result.get('failure_code', 'unavailable')}"
    )
    assert set(result["facets"]) == {
        "literal_chart_titles_series_caches_references", "value_limit_order",
        "local_chart_cells_and_negative_control", "pre_cancelled_export_preserves_workbook",
        "active_export_cancellation_preserves_workbook",
        "oversized_label_rejection_preserves_workbook",
    }
    assert all(value == "passed" for value in result["facets"].values())


def test_canonical_w07_failure_reports_fixed_stage_without_exception_text(
    tmp_path: Path, candidate_application, monkeypatch,
) -> None:
    def reject_thread(*_args):
        raise RuntimeError("SYNTHETIC_PRIVATE_WORKBOOK_VALUE")

    monkeypatch.setattr(application_xlsx, "_make_thread", reject_thread)
    result = application_xlsx.run_export_checks(tmp_path)
    assert result["status"] == "failed"
    assert result["failure_stage"] == "complete_export"
    assert result["failure_code"] == "operation_failed"
    assert "SYNTHETIC_PRIVATE_WORKBOOK_VALUE" not in str(result)


@pytest.mark.parametrize("module", (application_xlsx, standalone_xlsx))
def test_missing_real_measurement_barrier_remains_a_safe_specific_receipt(module) -> None:
    failure = module.XlsxScenarioFailure("active_cancel_measurement_barrier_missing")
    assert module._safe_failure_code(failure) == "active_cancel_measurement_barrier_missing"


@pytest.mark.parametrize("module", (application_xlsx, standalone_xlsx))
def test_grouped_cancellation_seed_keeps_all_real_header_units(tmp_path, module, candidate_application) -> None:
    headers = tuple(f"Active cancellation {index:03d}" for index in range(96))
    database = tmp_path / "active.sqlite"
    module._make_thread(database, tmp_path / "output.xlsx", headers, group_headers=True)

    with sqlite3.connect(database) as connection:
        reports = connection.execute("SELECT COUNT(*) FROM parsed_reports").fetchone()[0]
        counts = connection.execute(
            "SELECT header, COUNT(*) FROM report_measurements GROUP BY header"
        ).fetchall()
    assert reports == 2
    assert counts == [(header, 2) for header in headers]


@pytest.fixture(scope="session")
def candidate_application():
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    return application


@pytest.mark.parametrize("module", (application_xlsx, standalone_xlsx))
def test_active_export_cancellation_preserves_completed_workbook(tmp_path: Path, module, candidate_application) -> None:
    """Cancel the actual QThread after its measurement stage has begun."""
    application = candidate_application
    workbook = tmp_path / "last-complete.xlsx"
    completed = module._make_thread(tmp_path / "complete.sqlite", workbook, ("Complete",))
    assert completed.get_export_backend().run(completed).kind is ExportOutcomeKind.COMPLETED
    completed_bytes = workbook.read_bytes()

    facets = module._verify_active_cancellation(tmp_path, workbook, application)

    assert facets == {"active_export_cancellation_preserves_workbook": "passed"}
    assert workbook.read_bytes() == completed_bytes


@pytest.mark.parametrize("module", (application_xlsx, standalone_xlsx))
@pytest.mark.parametrize("failure", ("deadline", "event_processing"))
def test_active_cancel_failure_joins_thread_before_unwinding(tmp_path, monkeypatch, candidate_application, module, failure):
    class SlowStop(QThread):
        update_progress = pyqtSignal(int)

        def __init__(self):
            super().__init__()
            self.stop_requested = Event()
            self.entered_run = Event()
            self.stopped = False

        def start(self):
            super().start()
            assert self.entered_run.wait(5), "controlled worker did not enter run"

        def stop_exporting(self):
            self.stop_requested.set()

        def run(self):
            self.entered_run.set()
            self.stop_requested.wait(5)
            self.msleep(1100)
            self.stopped = True

    worker = SlowStop()
    workbook = tmp_path / "completed.xlsx"
    workbook.write_bytes(b"preserved complete workbook")
    monkeypatch.setattr(module, "_make_thread", lambda *_, **__: worker)
    if failure == "deadline":
        monkeypatch.setattr(module, "DEADLINE_S", 0)
        application = candidate_application
        error = module.XlsxScenarioFailure
        message = "active_cancel_thread_deadline"
    else:
        class FailingEvents:
            def processEvents(self):
                raise RuntimeError("event processing failure")
        application = FailingEvents()
        error = RuntimeError
        message = "event processing failure"
    try:
        with pytest.raises(error, match=message):
            module._verify_active_cancellation(tmp_path, workbook, application)
        assert worker.stop_requested.is_set()
        assert worker.stopped
        assert not worker.isRunning()
        assert workbook.read_bytes() == b"preserved complete workbook"
    finally:
        worker.stop_exporting()
        worker.wait()

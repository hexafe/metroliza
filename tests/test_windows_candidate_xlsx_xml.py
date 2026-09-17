"""Safe OOXML parsing regressions for both acceptance-operation copies."""
from __future__ import annotations

import ast
import inspect
import zipfile
from pathlib import Path

import pytest
from defusedxml.common import DefusedXmlException
from PyQt6.QtCore import QCoreApplication

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


@pytest.mark.parametrize("module", (application_xlsx, standalone_xlsx))
def test_active_export_cancellation_preserves_completed_workbook(tmp_path: Path, module) -> None:
    """Cancel the actual QThread after its measurement stage has begun."""
    application = QCoreApplication.instance() or QCoreApplication([])
    workbook = tmp_path / "last-complete.xlsx"
    completed = module._make_thread(tmp_path / "complete.sqlite", workbook, ("Complete",))
    assert completed.get_export_backend().run(completed).kind is ExportOutcomeKind.COMPLETED
    completed_bytes = workbook.read_bytes()

    facets = module._verify_active_cancellation(tmp_path, workbook, application)

    assert facets == {"active_export_cancellation_preserves_workbook": "passed"}
    assert workbook.read_bytes() == completed_bytes

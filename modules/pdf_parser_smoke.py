"""Helpers for non-interactive packaged PDF parser smoke validation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile


def _load_cmm_report_parser_class():
    module_name = "modules.cmm_report_parser"
    module = sys.modules.get(module_name)
    parser_cls = getattr(module, "CMMReportParser", None) if module is not None else None
    if parser_cls is not None and getattr(parser_cls, "__module__", "") == module_name:
        return parser_cls

    if module is not None:
        sys.modules.pop(module_name, None)

    module = importlib.import_module(module_name)
    return module.CMMReportParser


def run_pdf_parser_smoke(fixture_path: str | Path, expected_text: str) -> None:
    """Parse a fixture PDF and assert that expected text is extracted."""
    fixture = Path(fixture_path).resolve()
    if not fixture.is_file():
        raise FileNotFoundError(f"PDF parser smoke fixture not found: {fixture}")

    expected_token = expected_text.strip()
    if not expected_token:
        raise ValueError("Expected PDF parser smoke text must be non-empty")

    CMMReportParser = _load_cmm_report_parser_class()

    with NamedTemporaryFile(suffix='.sqlite3') as temp_db:
        parser = CMMReportParser(str(fixture), temp_db.name)
        parser.open_report()

    extracted_text = "\n".join(parser.raw_text)
    if expected_token not in extracted_text:
        raise RuntimeError(
            f"Packaged PDF parser smoke failed: expected text {expected_token!r} was not extracted from {fixture.name}"
        )

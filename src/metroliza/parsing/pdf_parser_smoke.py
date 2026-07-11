"""Helpers for non-interactive packaged PDF parser smoke validation."""

from __future__ import annotations

import importlib
from pathlib import Path
from tempfile import NamedTemporaryFile


def _resolve_cmm_report_parser_class(fixture: Path):
    parser_factory = importlib.import_module("metroliza.parsing.report_parser_factory")
    diagnostics, registration = parser_factory._resolve_parser_with_registration(fixture)
    selected = diagnostics.selected
    if selected is None:
        raise RuntimeError(
            "Packaged PDF parser smoke failed during parser resolution: "
            f"{diagnostics.rejected_reason or 'no parser selected'}"
        )
    if selected.plugin_id != "cmm":
        raise RuntimeError(
            "Packaged PDF parser smoke selected an unexpected parser: "
            f"{selected.plugin_id}"
        )
    if registration is None:
        raise RuntimeError("Packaged PDF parser smoke lost its selected registration")
    return registration.parser_cls


def run_pdf_parser_smoke(fixture_path: str | Path, expected_text: str) -> None:
    """Parse a fixture PDF and assert that expected text is extracted."""
    fixture = Path(fixture_path).resolve()
    if not fixture.is_file():
        raise FileNotFoundError(f"PDF parser smoke fixture not found: {fixture}")

    expected_token = expected_text.strip()
    if not expected_token:
        raise ValueError("Expected PDF parser smoke text must be non-empty")

    CMMReportParser = _resolve_cmm_report_parser_class(fixture)

    with NamedTemporaryFile(suffix='.sqlite3') as temp_db:
        parser = CMMReportParser(str(fixture), temp_db.name)
        parser.open_report()

    extracted_text = "\n".join(parser.raw_text)
    if expected_token not in extracted_text:
        raise RuntimeError(
            f"Packaged PDF parser smoke failed: expected text {expected_token!r} was not extracted from {fixture.name}"
        )

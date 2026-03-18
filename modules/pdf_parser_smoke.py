"""Helpers for non-interactive packaged PDF parser smoke validation."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile



def run_pdf_parser_smoke(fixture_path: str | Path, expected_text: str) -> None:
    """Parse a fixture PDF and assert that expected text is extracted."""
    fixture = Path(fixture_path).resolve()
    if not fixture.is_file():
        raise FileNotFoundError(f"PDF parser smoke fixture not found: {fixture}")

    expected_token = expected_text.strip()
    if not expected_token:
        raise ValueError("Expected PDF parser smoke text must be non-empty")

    from modules.cmm_report_parser import CMMReportParser

    with NamedTemporaryFile(suffix='.sqlite3') as temp_db:
        parser = CMMReportParser(str(fixture), temp_db.name)
        parser.open_report()

    extracted_text = "\n".join(parser.raw_text)
    if expected_token not in extracted_text:
        raise RuntimeError(
            f"Packaged PDF parser smoke failed: expected text {expected_token!r} was not extracted from {fixture.name}"
        )

"""Helpers for non-interactive packaged PDF parser smoke validation."""

from __future__ import annotations

import importlib
from pathlib import Path
from tempfile import TemporaryDirectory

from metroliza.reports.db import execute_with_retry


def _resolve_cmm_report_parser(fixture: Path, database: Path):
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
    parser = registration.parser_cls(str(fixture), str(database))
    parser.source_inspection_context = diagnostics.source_inspection
    return parser


def run_pdf_parser_smoke(fixture_path: str | Path, expected_text: str) -> None:
    """Resolve, parse, and persist a fixture containing a canonical measurement."""
    fixture = Path(fixture_path).resolve()
    if not fixture.is_file():
        raise FileNotFoundError(f"PDF parser smoke fixture not found: {fixture}")

    expected_token = expected_text.strip()
    if not expected_token:
        raise ValueError("Expected PDF parser smoke text must be non-empty")

    with TemporaryDirectory(prefix="metroliza_pdf_parser_smoke_") as temp_dir:
        database = Path(temp_dir) / "parser-smoke.sqlite3"
        parser = _resolve_cmm_report_parser(fixture, database)
        parser.open_database_and_check_filename()

        measurement_rows = parser.parse_measurements()
        if not measurement_rows:
            raise RuntimeError(
                "Packaged PDF parser smoke failed: canonical CMM decoding produced no measurements"
            )

        persisted_measurements = int(
            execute_with_retry(
                str(database),
                "SELECT COUNT(*) FROM report_measurements",
            )[0][0]
        )
        if persisted_measurements < 1:
            raise RuntimeError(
                "Packaged PDF parser smoke failed: parsed measurements were not persisted"
            )

    extracted_text = "\n".join(parser.raw_text)
    if expected_token not in extracted_text:
        raise RuntimeError(
            f"Packaged PDF parser smoke failed: expected text {expected_token!r} was not extracted from {fixture.name}"
        )

from __future__ import annotations

from pathlib import Path

import pytest

from metroliza.parsing.pdf_parser_smoke import run_pdf_parser_smoke
from metroliza.reports.report_parser_factory import resolve_parser_with_diagnostics


FIXTURE = Path('tests/fixtures/pdf/cmm_smoke_fixture.pdf')
EXPECTED = 'METROLIZA PDF PARSER SMOKE'


def test_pdf_parser_smoke_resolves_cmm_parser_and_extracts_expected_text():
    diagnostics = resolve_parser_with_diagnostics(FIXTURE)
    assert diagnostics.selected is not None
    assert diagnostics.selected.plugin_id == "cmm"
    run_pdf_parser_smoke(FIXTURE, EXPECTED)


def test_pdf_parser_smoke_requires_expected_text():
    with pytest.raises(ValueError):
        run_pdf_parser_smoke(FIXTURE, '   ')

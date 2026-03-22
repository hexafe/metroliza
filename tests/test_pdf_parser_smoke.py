from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from modules.pdf_parser_smoke import run_pdf_parser_smoke


FIXTURE = Path('tests/fixtures/pdf/cmm_smoke_fixture.pdf')
EXPECTED = 'METROLIZA PDF PARSER SMOKE'


class _DummyCustomLogger:
    def __init__(self, *_args, **_kwargs):
        pass


def test_pdf_parser_smoke_extracts_expected_text(monkeypatch):
    custom_logger_stub = types.ModuleType('modules.custom_logger')
    custom_logger_stub.CustomLogger = _DummyCustomLogger
    monkeypatch.setitem(sys.modules, 'modules.custom_logger', custom_logger_stub)

    run_pdf_parser_smoke(FIXTURE, EXPECTED)


def test_pdf_parser_smoke_requires_expected_text():
    with pytest.raises(ValueError):
        run_pdf_parser_smoke(FIXTURE, '   ')

from __future__ import annotations

import importlib
import importlib.util
import sys
import textwrap
import types
from pathlib import Path

import pytest

from scripts.validate_packaged_pdf_parser import (
    PackagingValidationError,
    require_pdf_backend_available,
    validate_nuitka_report_has_pdf_backend,
)


def test_require_pdf_backend_available_prefers_pymupdf(monkeypatch):
    class _FakeSpec:
        pass

    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: _FakeSpec() if name in {'pymupdf', 'fitz'} else None)
    monkeypatch.setattr(
        importlib,
        'import_module',
        lambda name: {
            'pymupdf': types.SimpleNamespace(open=lambda *_args, **_kwargs: None),
            'fitz': types.SimpleNamespace(open=lambda *_args, **_kwargs: None),
        }[name],
    )

    assert require_pdf_backend_available() == 'pymupdf'


def test_require_pdf_backend_available_raises_when_backend_missing(monkeypatch):
    monkeypatch.setattr(importlib.util, 'find_spec', lambda _name: None)

    with pytest.raises(PackagingValidationError):
        require_pdf_backend_available()


def test_validate_nuitka_report_has_pdf_backend_accepts_report(tmp_path):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text(
        textwrap.dedent(
            '''
            <nuitka-report>
              <module name="modules.cmm_report_parser" />
              <module name="pymupdf" />
            </nuitka-report>
            '''
        ).strip(),
        encoding='utf-8',
    )

    assert validate_nuitka_report_has_pdf_backend(report) == ('pymupdf',)


def test_validate_nuitka_report_has_pdf_backend_rejects_missing_backend(tmp_path):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text('<nuitka-report><module name="modules.cmm_report_parser" /></nuitka-report>', encoding='utf-8')

    with pytest.raises(PackagingValidationError):
        validate_nuitka_report_has_pdf_backend(report)


def test_build_nuitka_script_fails_closed_by_default_and_names_unsafe_override():
    script = Path('packaging/build_nuitka.ps1').read_text(encoding='utf-8')

    assert '[switch]$AllowBrokenPdfParserBuild' in script
    assert 'PyMuPDF is required for packaged builds.' in script
    assert 'UNSAFE: continuing even though packaged PDF parsing may be broken.' in script
    assert 'validate_packaged_pdf_parser.py' in script

from __future__ import annotations

from dataclasses import dataclass

import pytest

from metroliza.parsing import source_inspection
from metroliza.parsing.source_inspection import (
    PdfSourceInspectionError,
    SourceInspectionContext,
    SourceInspectionLimitError,
)


@dataclass
class _Page:
    text: str

    def get_text(self):
        return self.text


class _Document(list):
    needs_pass = False

    def __init__(self, *pages):
        super().__init__(pages)
        self.closed = False

    def close(self):
        self.closed = True


def test_pdf_text_uses_canonical_backend_scans_all_pages_and_caches_success(
    monkeypatch,
    tmp_path,
):
    report = tmp_path / "report.pdf"
    report.write_bytes(b"synthetic container")
    document = _Document(_Page("title"), _Page("measurement"))
    opened: list[str] = []

    class _Backend:
        @staticmethod
        def open(path):
            opened.append(path)
            return document

    monkeypatch.setattr(source_inspection, "require_pdf_backend", lambda: _Backend)
    inspection = SourceInspectionContext.from_path(report, source_format="pdf")

    assert inspection.get_pdf_text(max_chars=100) == "title\nmeasurement"
    assert inspection.get_pdf_text(max_chars=100) == "title\nmeasurement"
    assert inspection.get_pdf_text(max_chars=1_000) == "title\nmeasurement"
    assert inspection.get_cached_pdf_text(max_chars=100) == "title\nmeasurement"
    with pytest.raises(SourceInspectionLimitError):
        inspection.get_cached_pdf_text(max_chars=5)
    assert opened == [str(report)]
    assert document.closed is True


def test_pdf_inspection_failure_is_typed_and_not_cached(monkeypatch, tmp_path):
    report = tmp_path / "broken.pdf"
    report.write_bytes(b"not a pdf")
    attempts = 0

    class _Backend:
        @staticmethod
        def open(_path):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("broken xref")

    monkeypatch.setattr(source_inspection, "require_pdf_backend", lambda: _Backend)
    inspection = SourceInspectionContext.from_path(report, source_format="pdf")

    for _ in range(2):
        with pytest.raises(PdfSourceInspectionError, match="broken xref"):
            inspection.get_pdf_text(max_chars=100)

    assert attempts == 2


def test_pdf_text_limit_failure_is_not_cached_and_higher_limit_retries(monkeypatch, tmp_path):
    report = tmp_path / "large.pdf"
    report.write_bytes(b"synthetic container")
    attempts = 0

    class _Backend:
        @staticmethod
        def open(_path):
            nonlocal attempts
            attempts += 1
            return _Document(_Page("more text than allowed"))

    monkeypatch.setattr(source_inspection, "require_pdf_backend", lambda: _Backend)
    inspection = SourceInspectionContext.from_path(report, source_format="pdf")

    with pytest.raises(SourceInspectionLimitError, match="10-character"):
        inspection.get_pdf_text(max_chars=10)

    assert attempts == 1
    assert inspection.get_pdf_text(max_chars=100) == "more text than allowed"
    assert attempts == 2


def test_openable_pdf_without_embedded_text_is_a_successful_empty_inspection(
    monkeypatch,
    tmp_path,
):
    report = tmp_path / "image-only.pdf"
    report.write_bytes(b"synthetic container")

    class _Backend:
        @staticmethod
        def open(_path):
            return _Document(_Page(""))

    monkeypatch.setattr(source_inspection, "require_pdf_backend", lambda: _Backend)
    inspection = SourceInspectionContext.from_path(report, source_format="pdf")

    assert inspection.get_pdf_text(max_chars=100) == ""


def test_password_protected_pdf_is_an_inspection_error(monkeypatch, tmp_path):
    report = tmp_path / "encrypted.pdf"
    report.write_bytes(b"synthetic container")
    document = _Document()
    document.needs_pass = True

    class _Backend:
        @staticmethod
        def open(_path):
            return document

    monkeypatch.setattr(source_inspection, "require_pdf_backend", lambda: _Backend)
    inspection = SourceInspectionContext.from_path(report, source_format="pdf")

    with pytest.raises(PdfSourceInspectionError, match="requires a password"):
        inspection.get_pdf_text(max_chars=100)

    assert document.closed is True

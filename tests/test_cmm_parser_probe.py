from __future__ import annotations

import shutil

import pytest

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.pdf_backend import require_pdf_backend
from metroliza.parsing.parser_plugin_contracts import ProbeContext, ProbeOutcome, ProbeResult
from metroliza.parsing.report_parser_factory import (
    ParserInspectionError,
    UnsupportedReportFormatError,
    get_parser,
    reset_probe_cache,
    resolve_parser_with_diagnostics,
)
from metroliza.parsing.source_inspection import SourceInspectionContext


def _pdf_context(path, *, source_inspection=None):
    return ProbeContext(
        source_path=str(path),
        source_format="pdf",
        source_inspection=source_inspection,
    )


def _write_pdf(path, *page_texts):
    backend = require_pdf_backend()
    document = backend.open()
    try:
        for text in page_texts:
            page = document.new_page()
            page.insert_text((72, 72), text)
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()
    return path


def _valid_cmm_text(*, title="CMM REPORT"):
    return (
        f"{title}\n"
        "REFERENCE: REF01\n"
        "DATE: 2026-06-23\n"
        "#FEATURE 1\n"
        "DIM\n"
        "X 10 0.2 -0.2 10.1 0.1 0\n"
    )


def _marker_heavy_non_cmm_text():
    return (
        "CMM REPORT\n"
        "REFERENCE: REF01\n"
        "DATE: 2026-06-23\n"
        "PART NAME: BRACKET\n"
        "MEASUREMENT MADE BY: OPERATOR\n"
        "NOMINAL TOL MEASURED DEVIATION OUTTOL BONUS\n"
        "X NOMINAL 10 +TOL 0.2 TOL -0.2 ACT 10.1 DEV 0.1 OUT 0 BONUS 0\n"
    )


def test_cmm_probe_rejects_generic_pdf_without_canonical_measurements(tmp_path):
    generic_pdf = _write_pdf(tmp_path / "generic.pdf", "Generic production report\n")

    probe = CMMReportParser.probe(generic_pdf, _pdf_context(generic_pdf))

    assert isinstance(probe, ProbeResult)
    assert probe.plugin_id == "cmm"
    assert probe.can_parse is False
    assert probe.confidence == 0
    assert probe.outcome is ProbeOutcome.NO_MATCH
    assert probe.semantic_row_count == 0
    assert "no_canonical_measurements" in probe.reasons


def test_cmm_probe_accepts_content_with_a_canonical_measurement(tmp_path):
    cmm_pdf = _write_pdf(tmp_path / "anything.pdf", _valid_cmm_text())

    probe = CMMReportParser.probe(cmm_pdf, _pdf_context(cmm_pdf))

    assert probe.can_parse is True
    assert probe.confidence >= 80
    assert probe.outcome is ProbeOutcome.MATCH
    assert probe.semantic_row_count == 1
    assert probe.matched_template_id == "default"
    assert "canonical_measurements" in probe.reasons
    assert "pdf_backend_text_probe" in probe.reasons


def test_cmm_probe_uses_decoded_pdf_text_when_raw_bytes_hide_content(tmp_path):
    cmm_pdf = _write_pdf(tmp_path / "encoded.pdf", _valid_cmm_text())

    assert b"CMM REPORT" not in cmm_pdf.read_bytes()[:65536].upper()

    probe = CMMReportParser.probe(cmm_pdf, _pdf_context(cmm_pdf))

    assert probe.can_parse is True
    assert "pdf_backend_text_probe" in probe.reasons
    assert "strong_cmm_marker" in probe.reasons


def test_cmm_resolver_selects_semantically_valid_pdf(tmp_path):
    cmm_pdf = _write_pdf(tmp_path / "encoded.pdf", _valid_cmm_text())
    reset_probe_cache()

    diagnostics = resolve_parser_with_diagnostics(cmm_pdf)

    assert diagnostics.selected is not None
    assert diagnostics.selected.plugin_id == "cmm"
    assert diagnostics.selected.confidence >= 80
    assert get_parser(cmm_pdf, database=":memory:").__class__ is CMMReportParser


def test_identical_pdf_bytes_resolve_identically_under_arbitrary_filenames(tmp_path):
    original = _write_pdf(tmp_path / "default.pdf", _valid_cmm_text())
    renamed_paths = [
        tmp_path / "VSPC015888_2017.05.22_01.PDF",
        tmp_path / "unrelated_G.pdf",
        tmp_path / "plain-name.pdf",
    ]
    for renamed in renamed_paths:
        shutil.copyfile(original, renamed)

    reset_probe_cache()
    probes = [CMMReportParser.probe(path, _pdf_context(path)) for path in renamed_paths]
    selected = [resolve_parser_with_diagnostics(path).selected for path in renamed_paths]

    assert probes[1:] == probes[:-1]
    assert all(candidate is not None for candidate in selected)
    assert [candidate.plugin_id for candidate in selected] == ["cmm", "cmm", "cmm"]
    assert len({candidate.confidence for candidate in selected}) == 1


@pytest.mark.parametrize("strict_matching", ["true", "false"])
def test_marker_heavy_pdf_without_canonical_rows_is_rejected_in_every_mode(
    tmp_path,
    monkeypatch,
    strict_matching,
):
    report = _write_pdf(tmp_path / "supplier_2026.07.16_01.pdf", _marker_heavy_non_cmm_text())
    monkeypatch.setenv("PARSER_STRICT_MATCHING", strict_matching)
    reset_probe_cache()

    probe = CMMReportParser.probe(report, _pdf_context(report))
    diagnostics = resolve_parser_with_diagnostics(report)

    assert "strong_cmm_marker" in probe.reasons
    assert "no_canonical_measurements" in probe.reasons
    assert probe.can_parse is False
    assert probe.confidence == 0
    assert probe.outcome is ProbeOutcome.NO_MATCH
    assert probe.semantic_row_count == 0
    assert diagnostics.selected is None
    assert diagnostics.rejected_reason == "no_plugin_can_parse"
    with pytest.raises(UnsupportedReportFormatError) as exc_info:
        get_parser(report, database=":memory:")
    assert exc_info.value.diagnostics.selected is None


def test_probe_scans_all_pages_before_classifying_report(tmp_path):
    report = _write_pdf(
        tmp_path / "multipage.pdf",
        "Supplier report title page\nNo measurements on this page\n",
        _valid_cmm_text(title="MEASUREMENT RESULTS"),
    )

    diagnostics = resolve_parser_with_diagnostics(report)

    assert diagnostics.selected is not None
    assert diagnostics.selected.plugin_id == "cmm"
    assert "canonical_measurements" in diagnostics.selected.reasons


def test_pdf_extraction_failure_is_not_classified_as_unsupported_content(
    tmp_path,
    monkeypatch,
):
    report = _write_pdf(tmp_path / "unreadable.pdf", _valid_cmm_text())

    def fail_inspection(_self, *, max_chars):
        raise OSError("simulated PDF read failure")

    monkeypatch.setattr(
        SourceInspectionContext,
        "get_pdf_text",
        fail_inspection,
    )
    reset_probe_cache()

    diagnostics = resolve_parser_with_diagnostics(report)

    assert diagnostics.selected is None
    assert diagnostics.rejected_reason == "parser_inspection_failed"
    assert diagnostics.candidates_considered[0].outcome is ProbeOutcome.INSPECTION_ERROR
    assert "content_inspection_failed" in diagnostics.candidates_considered[0].reasons
    assert any(
        "simulated PDF read failure" in warning
        for warning in diagnostics.candidates_considered[0].warnings
    )
    with pytest.raises(ParserInspectionError) as exc_info:
        get_parser(report, database=":memory:")
    assert exc_info.value.diagnostics == diagnostics


def test_resolver_and_parser_share_cached_embedded_text(tmp_path, monkeypatch):
    report = _write_pdf(tmp_path / "cached.pdf", _valid_cmm_text())
    inspection = SourceInspectionContext.from_path(report, source_format="pdf")
    original_loader = SourceInspectionContext.get_pdf_text
    load_count = 0

    def counting_loader(self, *, max_chars):
        nonlocal load_count
        load_count += 1
        return original_loader(self, max_chars=max_chars)

    monkeypatch.setattr(
        SourceInspectionContext,
        "get_pdf_text",
        counting_loader,
    )
    reset_probe_cache()

    diagnostics = resolve_parser_with_diagnostics(report, source_inspection=inspection)
    parser = get_parser(
        report,
        database=str(tmp_path / "cached.sqlite3"),
        metadata_parsing_mode="light",
        source_inspection=inspection,
    )
    parser.open_report()

    assert diagnostics.selected is not None
    assert load_count == 1
    assert any(line.startswith("X 10") for line in parser.raw_text)


def test_cmm_probe_rejects_non_pdf_source_format(tmp_path):
    report = tmp_path / "report.csv"
    report.write_text(_valid_cmm_text(), encoding="utf-8")

    probe = CMMReportParser.probe(
        report,
        ProbeContext(source_path=str(report), source_format="csv"),
    )

    assert probe.can_parse is False
    assert probe.reasons == ("unsupported_source_format",)

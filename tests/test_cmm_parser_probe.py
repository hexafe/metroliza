import os

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.parser_plugin_contracts import ProbeContext
from metroliza.reports import report_parser_factory


def _probe_pdf(path):
    return CMMReportParser.probe(
        path,
        ProbeContext(source_path=str(path), source_format="pdf"),
    )


def test_generic_pdf_probe_is_not_high_confidence(tmp_path):
    generic_pdf = tmp_path / "generic.pdf"
    generic_pdf.write_bytes(
        b"%PDF-1.4\n"
        b"Quarterly supplier overview\n"
        b"This file is an ordinary brochure without specialized markers.\n"
    )

    result = _probe_pdf(generic_pdf)

    assert result.confidence < 80
    assert result.confidence != 100
    assert result.can_parse is False
    assert result.matched_template_id is None
    assert "pdf_extension_only" in result.reasons


def test_synthetic_cmm_like_pdf_probe_is_high_confidence(tmp_path):
    cmm_pdf = tmp_path / "synthetic_cmm_report.pdf"
    cmm_pdf.write_bytes(
        b"%PDF-1.4\n"
        b"CMM REPORT\n"
        b"REFERENCE: AX-100\n"
        b"DATE: 2026-06-14\n"
        b"PART NAME: BRACKET\n"
        b"REV NUMBER: A\n"
        b"MEASUREMENT MADE BY: CMM OPERATOR A\n"
        b"NOMINAL TOL MEASURED DEVIATION OUTTOL\n"
    )

    result = _probe_pdf(cmm_pdf)

    assert result.can_parse is True
    assert result.confidence == 100
    assert result.matched_template_id == "default"
    assert "strong_cmm_markers" in result.reasons
    assert "metadata_header_markers" in result.reasons


def test_cmm_identity_filename_probe_is_low_without_content_markers(tmp_path):
    cmm_like_name = tmp_path / "REF01_2024-01-02_001.pdf"

    result = _probe_pdf(cmm_like_name)

    assert result.can_parse is False
    assert result.confidence < 80
    assert result.matched_template_id is None
    assert "cmm_identity_filename_pattern" in result.reasons


def test_cmm_identity_filename_probe_with_markers_remains_selectable(tmp_path):
    cmm_like_name = tmp_path / "REF01_2024-01-02_001.pdf"
    cmm_like_name.write_bytes(
        b"%PDF-1.4\n"
        b"REFERENCE: REF01\n"
        b"DATE: 2024-01-02\n"
        b"PART NAME: BRACKET\n"
        b"NOMINAL TOL MEASURED\n"
    )

    result = _probe_pdf(cmm_like_name)

    assert result.can_parse is True
    assert result.confidence == 82
    assert "cmm_identity_filename_pattern" in result.reasons


def test_default_resolver_rejects_generic_pdf_below_strict_threshold(tmp_path):
    generic_pdf = tmp_path / "generic_datasheet.pdf"
    generic_pdf.write_bytes(b"%PDF-1.7\nGeneric datasheet without report markers.\n")
    report_parser_factory.reset_probe_cache()

    diagnostics = report_parser_factory.resolve_parser_with_diagnostics(generic_pdf)

    assert diagnostics.selected is None
    assert diagnostics.rejected_reason == "no_plugin_can_parse"
    assert diagnostics.candidates_considered
    assert diagnostics.candidates_considered[0].plugin_id == "cmm"
    assert diagnostics.candidates_considered[0].can_parse is False
    assert diagnostics.candidates_considered[0].confidence < 80


def test_non_strict_resolver_keeps_explicit_pdf_extension_fallback(tmp_path, monkeypatch):
    generic_pdf = tmp_path / "generic_datasheet.pdf"
    generic_pdf.write_bytes(b"%PDF-1.7\nGeneric datasheet without report markers.\n")
    monkeypatch.setenv("PARSER_STRICT_MATCHING", "false")
    report_parser_factory.reset_probe_cache()

    diagnostics = report_parser_factory.resolve_parser_with_diagnostics(generic_pdf)

    assert diagnostics.selected is not None
    assert diagnostics.selected.plugin_id == "cmm"
    assert diagnostics.selected.can_parse is True
    assert diagnostics.selected.confidence < 80
    assert "non_strict_pdf_extension_fallback" in diagnostics.selected.reasons


def test_probe_cache_refreshes_when_pdf_content_changes(tmp_path):
    report_pdf = tmp_path / "mutable_report.pdf"
    cmm_bytes = (
        b"%PDF-1.7\n"
        b"CMM REPORT\n"
        b"REFERENCE: AX-100\n"
        b"DATE: 2026-06-14\n"
        b"PART NAME: BRACKET\n"
        b"REV NUMBER: A\n"
        b"MEASUREMENT MADE BY: CMM OPERATOR A\n"
        b"NOMINAL TOL MEASURED DEVIATION OUTTOL\n"
    )
    generic_bytes = b"%PDF-1.7\nGeneric datasheet without report markers.\n".ljust(
        len(cmm_bytes),
        b".",
    )
    report_pdf.write_bytes(generic_bytes)
    original_stat = report_pdf.stat()
    report_parser_factory.reset_probe_cache()

    initial = report_parser_factory.resolve_parser_with_diagnostics(report_pdf)
    assert initial.selected is None

    report_pdf.write_bytes(cmm_bytes)
    os.utime(report_pdf, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    updated = report_parser_factory.resolve_parser_with_diagnostics(report_pdf)

    assert updated.selected is not None
    assert updated.selected.plugin_id == "cmm"
    assert updated.selected.confidence == 100

from metroliza.parsing import cmm_report_parser
from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.pdf_backend import require_pdf_backend
from metroliza.parsing.parser_plugin_contracts import ProbeContext, ProbeResult
from metroliza.reports import report_parser_factory


def _pdf_context(path):
    return ProbeContext(source_path=str(path), source_format="pdf")


def _write_encoded_cmm_pdf(path):
    backend = require_pdf_backend()
    document = backend.open()
    try:
        page = document.new_page()
        page.insert_text(
            (72, 72),
            "CMM REPORT\n"
            "REFERENCE: REF01\n"
            "DATE: 2026-06-23\n"
            "PART NAME: BRACKET\n"
            "MEASUREMENT MADE BY: CMM OPERATOR A\n"
            "NOMINAL TOL MEASURED DEVIATION OUTTOL\n"
            "X NOMINAL 10 +TOL 0.1 ACT 10.02 DEV 0.02 OUTTOL 0",
        )
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()
    return path


def test_cmm_probe_does_not_give_generic_pdf_full_confidence(tmp_path):
    generic_pdf = tmp_path / "generic.pdf"
    generic_pdf.write_text(
        "%PDF-1.4\n"
        "1 0 obj\n"
        "<< /Type /Catalog >>\n"
        "endobj\n"
        "%%EOF\n",
        encoding="utf-8",
    )

    probe = CMMReportParser.probe(generic_pdf, _pdf_context(generic_pdf))

    assert isinstance(probe, ProbeResult)
    assert probe.plugin_id == "cmm"
    assert probe.confidence < 100
    assert probe.confidence < 80 or probe.can_parse is False


def test_cmm_probe_detects_cmm_like_synthetic_pdf_text(tmp_path):
    cmm_pdf = tmp_path / "synthetic_cmm.pdf"
    cmm_pdf.write_text(
        "%PDF-1.4\n"
        "#TOKEN LABELS\n"
        "DIM\n"
        "X NOMINAL 10 +TOL 0.2 TOL -0.2 ACT 10.1 DEV 0.1 OUT 0\n"
        "TP MMC NOM: 0 +TOL: 0.3 BONUS 0.05 MEAS 0.12 DEV 0.12 OUTTOL 0\n"
        "%%EOF\n",
        encoding="utf-8",
    )

    probe = CMMReportParser.probe(cmm_pdf, _pdf_context(cmm_pdf))

    assert probe.can_parse is True
    assert probe.confidence >= 80
    assert probe.matched_template_id == "default"
    assert "axis_value_marker" in probe.reasons


def test_cmm_probe_uses_pdf_text_when_raw_pdf_bytes_hide_markers(tmp_path):
    cmm_pdf = _write_encoded_cmm_pdf(tmp_path / "encoded_cmm.pdf")

    raw_probe_sample = cmm_pdf.read_bytes()[:65536].upper()
    assert b"CMM REPORT" not in raw_probe_sample

    probe = CMMReportParser.probe(cmm_pdf, _pdf_context(cmm_pdf))

    assert probe.can_parse is True
    assert probe.confidence >= 80
    assert probe.matched_template_id == "default"
    assert "pdf_backend_text_probe" in probe.reasons
    assert "strong_cmm_marker" in probe.reasons


def test_cmm_resolver_selects_encoded_cmm_pdf(tmp_path):
    cmm_pdf = _write_encoded_cmm_pdf(tmp_path / "encoded_cmm.pdf")
    report_parser_factory.reset_probe_cache()

    diagnostics = report_parser_factory.resolve_parser_with_diagnostics(cmm_pdf)

    assert diagnostics.selected is not None
    assert diagnostics.selected.plugin_id == "cmm"
    assert diagnostics.selected.confidence >= 80
    assert "pdf_backend_text_probe" in diagnostics.selected.reasons
    assert report_parser_factory.detect_format(cmm_pdf) == "cmm"
    assert report_parser_factory.get_parser(cmm_pdf, database=":memory:").__class__.__name__ == "CMMReportParser"


def test_cmm_probe_treats_extension_only_pdf_as_low_confidence_or_unsupported(tmp_path):
    extension_only_pdf = tmp_path / "extension_only.pdf"

    probe = CMMReportParser.probe(extension_only_pdf, _pdf_context(extension_only_pdf))

    assert probe.confidence < 80
    assert probe.can_parse is False


def test_cmm_probe_does_not_use_full_pdf_backend(tmp_path, monkeypatch):
    cmm_pdf = tmp_path / "synthetic_cmm.pdf"
    cmm_pdf.write_text(
        "%PDF-1.4\n"
        "#TOKEN LABELS\n"
        "DIM\n"
        "X NOMINAL 10 +TOL 0.2 TOL -0.2 ACT 10.1 DEV 0.1 OUT 0\n"
        "%%EOF\n",
        encoding="utf-8",
    )

    def fail_pdf_backend(*_args, **_kwargs):
        raise AssertionError("probe must not invoke the PDF parser backend")

    monkeypatch.setattr(cmm_report_parser, "_load_pdf_backend", fail_pdf_backend)
    monkeypatch.setattr(cmm_report_parser, "require_pdf_backend", fail_pdf_backend)

    probe = CMMReportParser.probe(cmm_pdf, _pdf_context(cmm_pdf))

    assert probe.can_parse is True
    assert probe.confidence >= 80

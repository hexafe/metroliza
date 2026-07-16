from __future__ import annotations

from types import SimpleNamespace

import pytest

from metroliza.parsing.cmm_report_parser import EmptyCMMReportError
from metroliza.parsing.parse_reports_thread import enrich_report_metadata, parse_new_reports
from metroliza.parsing.pdf_backend import require_pdf_backend
from metroliza.parsing.report_parser_factory import (
    ParserInspectionError,
    UnsupportedReportFormatError,
    get_parser,
    reset_probe_cache,
)
from metroliza.parsing.source_inspection import SourceInspectionContext
from metroliza.ui.parsing_dialog import ParsingDialog


def _write_pdf(path, text):
    backend = require_pdf_backend()
    document = backend.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), text)
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()
    return path


def _valid_cmm_text(feature):
    return (
        "CMM REPORT\n"
        f"#{feature}\n"
        "DIM\n"
        "X 10 0.2 -0.2 10.1 0.1 0\n"
    )


def _unsupported_marker_text():
    return (
        "CMM REPORT\n"
        "REFERENCE: REF01\n"
        "MEASUREMENT MADE BY: OPERATOR\n"
        "NOMINAL TOL MEASURED DEVIATION OUTTOL BONUS\n"
        "No canonical dimensional result rows follow.\n"
    )


def test_unsupported_format_error_preserves_resolver_diagnostics(tmp_path):
    report = _write_pdf(tmp_path / "not-cmm.pdf", _unsupported_marker_text())
    reset_probe_cache()

    with pytest.raises(UnsupportedReportFormatError) as exc_info:
        get_parser(report, database=":memory:")

    error = exc_info.value
    assert isinstance(error, ValueError)
    assert error.source_path == str(report)
    assert error.diagnostics.selected is None
    assert error.diagnostics.rejected_reason == "no_plugin_can_parse"
    assert any(
        "no_canonical_measurements" in candidate.reasons
        for candidate in error.diagnostics.candidates_considered
        if candidate.plugin_id == "cmm"
    )


@pytest.mark.parametrize("two_stage", [False, True])
def test_mixed_batch_separates_unsupported_skips_from_real_failures(tmp_path, two_stage):
    valid = _write_pdf(tmp_path / "valid.pdf", _valid_cmm_text("VALID"))
    unsupported = _write_pdf(tmp_path / "other-report.pdf", _unsupported_marker_text())
    selected_but_failed = _write_pdf(
        tmp_path / "selected-but-empty.pdf",
        _valid_cmm_text("UNEXPECTED EMPTY"),
    )
    database = tmp_path / "reports.sqlite3"
    fingerprints = set()
    failures = []
    progress = []
    reset_probe_cache()

    def parser_factory(path, *, source_inspection=None):
        return get_parser(
            path,
            database=str(database),
            metadata_parsing_mode="light",
            source_inspection=source_inspection,
        )

    def persist_report(parser):
        if parser._prepared_measurement_rows is None:
            parser.prepare_for_two_stage_pipeline()
        if parser.file_name == selected_but_failed.name:
            raise EmptyCMMReportError(parser.source_path)
        assert parser._prepared_measurement_rows

    result = parse_new_reports(
        [valid, unsupported, selected_but_failed],
        fingerprints,
        parser_factory=parser_factory,
        persist_report=persist_report,
        on_progress=lambda processed, total: progress.append((processed, total)),
        on_file_failed=lambda _path, exc, _processed, _total: failures.append(exc),
        enable_two_stage_pipeline=two_stage,
        worker_count=2,
        log_file_failures=False,
    )

    assert result.parsed_files == 1
    assert result.skipped_files == 1
    assert result.failed_files == 1
    assert result.total_files == 3
    assert len(fingerprints) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], EmptyCMMReportError)
    assert len(progress) == 3
    assert progress[-1] == (3, 3)


def test_batch_counts_content_inspection_errors_as_failures(tmp_path, monkeypatch):
    report = _write_pdf(tmp_path / "inspection-error.pdf", _valid_cmm_text("VALID"))
    database = tmp_path / "reports.sqlite3"
    failures = []

    def fail_inspection(_self, *, max_chars):
        raise OSError("simulated PDF read failure")

    monkeypatch.setattr(
        SourceInspectionContext,
        "get_pdf_text",
        fail_inspection,
    )
    reset_probe_cache()

    result = parse_new_reports(
        [report],
        set(),
        parser_factory=lambda path, *, source_inspection=None: get_parser(
            path,
            database=str(database),
            source_inspection=source_inspection,
        ),
        persist_report=lambda _parser: pytest.fail("inspection failure must not persist"),
        on_file_failed=lambda _path, exc, _processed, _total: failures.append(exc),
        log_file_failures=False,
    )

    assert result.parsed_files == 0
    assert result.skipped_files == 0
    assert result.failed_files == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ParserInspectionError)


def test_metadata_enrichment_keeps_unsupported_content_as_a_skip(tmp_path):
    report = _write_pdf(tmp_path / "unsupported.pdf", _unsupported_marker_text())
    database = tmp_path / "reports.sqlite3"
    warnings = []
    reset_probe_cache()

    result = enrich_report_metadata(
        [report],
        parser_factory=lambda path, *, source_inspection=None: get_parser(
            path,
            database=str(database),
            source_inspection=source_inspection,
        ),
        persist_enrichment=lambda _report, _parser: pytest.fail(
            "unsupported content must not reach enrichment persistence"
        ),
        on_warning=lambda _report, exc: warnings.append(exc),
    )

    assert result.enriched_files == 0
    assert result.skipped_files == 1
    assert result.failed_files == 0
    assert warnings == []


def test_completion_feedback_reports_skips_and_failures_separately():
    dialog = SimpleNamespace(
        db_file="/tmp/reports.sqlite3",
        parse_thread=SimpleNamespace(
            last_parse_result=SimpleNamespace(
                total_files=4,
                parsed_files=2,
                skipped_files=1,
                failed_files=1,
            )
        ),
        _report_file_label=lambda count: "report file" if count == 1 else "report files",
    )

    level, title, message = ParsingDialog._build_parse_completion_feedback(dialog)

    assert level == "warning"
    assert title == "Parsing completed with warnings"
    assert "1 report file could not be parsed" in message
    assert "Unsupported based on file contents and skipped: 1 report file" in message


def test_completion_feedback_explains_content_based_unsupported_skip():
    dialog = SimpleNamespace(
        db_file="/tmp/reports.sqlite3",
        parse_thread=SimpleNamespace(
            last_parse_result=SimpleNamespace(
                total_files=1,
                parsed_files=0,
                skipped_files=1,
                failed_files=0,
            )
        ),
        _report_file_label=lambda count: "report file" if count == 1 else "report files",
    )

    level, title, message = ParsingDialog._build_parse_completion_feedback(dialog)

    assert level == "warning"
    assert title == "No compatible reports parsed"
    assert "Parser recognition uses file contents, not filenames" in message

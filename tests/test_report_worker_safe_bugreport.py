"""Real preflight and metadata-review workers only record safe lifecycle facts."""

import shutil
import time
from pathlib import Path

import pytest

from metroliza.parsing.metadata_review import MODE_FAST, MODE_OCR, MetadataReviewReader, MetadataReadSummary
from metroliza.parsing.preflight import ParsePreflightService
from metroliza.shared.safe_bugreport import (
    BugReportAction,
    BugReportCategory,
    SafeBugReportRecorder,
    build_bug_report_markdown,
)
from metroliza.ui import metadata_review_worker, parser_preflight_worker
from metroliza.ui.metadata_review_worker import MetadataReviewThread
from metroliza.ui.parser_preflight_worker import ParsePreflightThread


FIXTURE = Path(__file__).parent / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"


@pytest.fixture
def trace(monkeypatch):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(parser_preflight_worker, "_bugreport_recorder", recorder)
    monkeypatch.setattr(metadata_review_worker, "_bugreport_recorder", recorder)
    return recorder


def _wait_for_worker(app, worker, timeout=40):
    worker.start()
    deadline = time.monotonic() + timeout
    while worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert not worker.isRunning(), "report worker did not stop before the deadline"
    assert worker.wait(1000)
    app.processEvents()


def _report_without_private_markers(trace, *markers):
    report = build_bug_report_markdown(BugReportCategory.OTHER, trace.snapshot())
    for marker in markers:
        assert marker not in report
    return report


def _preflight(source, database):
    return ParsePreflightService().scan_source(
        source_path=source,
        database_path=database,
        metadata_parsing_mode="light",
    )


def test_real_preflight_worker_records_completed_scan_without_source_identity(
    qapplication_session, trace, tmp_path
):
    marker = "private_preflight_marker_173"
    source = tmp_path / marker
    source.mkdir()
    shutil.copyfile(FIXTURE, source / f"{marker}.pdf")
    database = tmp_path / f"{marker}.sqlite"
    completed = []
    worker = ParsePreflightThread(
        source_path=str(source), database_path=str(database), metadata_parsing_mode="light"
    )
    worker.completed.connect(completed.append)

    _wait_for_worker(qapplication_session, worker)

    assert len(completed) == 1 and not completed[0].cancelled
    assert [event.action for event in trace.snapshot().events] == [
        BugReportAction.REPORT_PREFLIGHT_STARTED,
        BugReportAction.REPORT_PREFLIGHT_COMPLETED,
    ]
    _report_without_private_markers(trace, marker, str(source), str(database))


def test_real_preflight_worker_records_cooperative_cancel(qapplication_session, trace, tmp_path):
    marker = "private_cancel_marker_294"
    source = tmp_path / marker
    source.mkdir()
    shutil.copyfile(FIXTURE, source / "report.pdf")
    worker = ParsePreflightThread(
        source_path=str(source), database_path=str(tmp_path / "db.sqlite"), metadata_parsing_mode="light"
    )
    worker.stop_scan()
    completed = []
    worker.completed.connect(completed.append)

    _wait_for_worker(qapplication_session, worker)

    assert len(completed) == 1 and completed[0].cancelled
    assert [event.action for event in trace.snapshot().events] == [
        BugReportAction.REPORT_PREFLIGHT_STARTED,
        BugReportAction.REPORT_PREFLIGHT_CANCELLED,
    ]


def test_preflight_worker_failure_records_no_exception_text(monkeypatch, qapplication_session, trace):
    marker = "private_preflight_exception_marker_385"

    def fail(*_args, **_kwargs):
        raise RuntimeError(marker)

    monkeypatch.setattr(parser_preflight_worker.ParsePreflightService, "scan_source", fail)
    failures = []
    worker = ParsePreflightThread(
        source_path="private-source", database_path="private-db", metadata_parsing_mode="light"
    )
    worker.failed.connect(failures.append)

    _wait_for_worker(qapplication_session, worker)

    assert len(failures) == 1 and marker in failures[0]
    assert [event.action for event in trace.snapshot().events] == [
        BugReportAction.REPORT_PREFLIGHT_STARTED,
        BugReportAction.REPORT_PREFLIGHT_FAILED,
    ]
    _report_without_private_markers(trace, marker, "private-source", "private-db")


def _real_metadata_reader(tmp_path, marker):
    source = tmp_path / f"{marker}.pdf"
    shutil.copyfile(FIXTURE, source)
    preflight = _preflight(source, tmp_path / f"{marker}.sqlite")
    assert preflight.ready_files
    return MetadataReviewReader(preflight), preflight.ready_files[0].stable_occurrence_id, source


def test_unexpected_preflight_result_cannot_suppress_completed_signal(
    qapplication_session, trace, monkeypatch
):
    class UnexpectedResult:
        @property
        def cancelled(self):
            raise RuntimeError("private content must not be recorded")

    result = UnexpectedResult()
    monkeypatch.setattr(
        parser_preflight_worker.ParsePreflightService, "scan_source", lambda *_a, **_k: result
    )
    received = []
    worker = ParsePreflightThread(
        source_path="private-source", database_path="private-db", metadata_parsing_mode="light"
    )
    worker.completed.connect(received.append)
    _wait_for_worker(qapplication_session, worker)

    assert received == [result]
    assert trace.snapshot().events[-1].action is BugReportAction.REPORT_PREFLIGHT_RESULT_UNKNOWN
    _report_without_private_markers(trace, "private content", "private-source", "private-db")


def test_real_metadata_review_worker_records_completed_read_and_ocr_false(
    qapplication_session, trace, tmp_path
):
    marker = "private_metadata_marker_496"
    reader, occurrence_id, source = _real_metadata_reader(tmp_path, marker)
    summaries = []
    worker = MetadataReviewThread(reader, [occurrence_id], mode=MODE_FAST)
    worker.completed.connect(summaries.append)

    _wait_for_worker(qapplication_session, worker)

    assert len(summaries) == 1 and not summaries[0].cancelled
    events = trace.snapshot().events
    assert [(event.action, event.enabled) for event in events] == [
        (BugReportAction.REPORT_METADATA_REVIEW_STARTED, None),
        (BugReportAction.OPTION_REPORT_REVIEW_OCR, False),
        (BugReportAction.REPORT_METADATA_REVIEW_COMPLETED, None),
    ]
    _report_without_private_markers(trace, marker, str(source), occurrence_id)


def test_real_metadata_review_worker_records_cancelled_summary(
    qapplication_session, trace, tmp_path
):
    marker = "private_metadata_cancel_marker_597"
    reader, occurrence_id, _source = _real_metadata_reader(tmp_path, marker)
    summaries = []
    worker = MetadataReviewThread(reader, [occurrence_id], mode=MODE_FAST)
    worker.stop_reading()
    worker.completed.connect(summaries.append)

    _wait_for_worker(qapplication_session, worker)

    assert len(summaries) == 1 and summaries[0].cancelled == 1
    assert [event.action for event in trace.snapshot().events] == [
        BugReportAction.REPORT_METADATA_REVIEW_STARTED,
        BugReportAction.OPTION_REPORT_REVIEW_OCR,
        BugReportAction.REPORT_METADATA_REVIEW_CANCELLED,
    ]


def test_metadata_worker_error_is_generic_and_report_contains_no_exception(
    qapplication_session, trace, tmp_path
):
    marker = "private_metadata_exception_marker_608"
    reader, occurrence_id, source = _real_metadata_reader(tmp_path, "private_metadata_error_source")
    failures = []
    worker = MetadataReviewThread(reader, [occurrence_id], mode=marker)
    worker.failed.connect(failures.append)

    _wait_for_worker(qapplication_session, worker)

    assert failures == ["Metadata could not be read."]
    assert [event.action for event in trace.snapshot().events] == [
        BugReportAction.REPORT_METADATA_REVIEW_STARTED,
        BugReportAction.OPTION_REPORT_REVIEW_OCR,
        BugReportAction.REPORT_METADATA_REVIEW_FAILED,
    ]
    _report_without_private_markers(trace, marker, str(source), occurrence_id)


def test_metadata_review_records_ocr_mode_as_boolean_only(qapplication_session, trace):
    class SyntheticReader:
        def read(self, occurrence_ids, *, mode, **_kwargs):
            return MetadataReadSummary(len(tuple(occurrence_ids)), 0, 0, 0)

    worker = MetadataReviewThread(SyntheticReader(), ["private-occurrence"], mode=MODE_OCR)
    _wait_for_worker(qapplication_session, worker)

    assert [(event.action, event.enabled) for event in trace.snapshot().events] == [
        (BugReportAction.REPORT_METADATA_REVIEW_STARTED, None),
        (BugReportAction.OPTION_REPORT_REVIEW_OCR, True),
        (BugReportAction.REPORT_METADATA_REVIEW_COMPLETED, None),
    ]


def test_unexpected_metadata_summary_cannot_suppress_completed_signal(qapplication_session, trace):
    class UnexpectedSummary:
        @property
        def cancelled(self):
            raise RuntimeError("private content must not be recorded")

    summary = UnexpectedSummary()

    class SyntheticReader:
        def read(self, *_args, **_kwargs):
            return summary

    received = []
    worker = MetadataReviewThread(SyntheticReader(), [], mode=MODE_FAST)
    worker.completed.connect(received.append)
    _wait_for_worker(qapplication_session, worker)

    assert received == [summary]
    assert trace.snapshot().events[-1].action is BugReportAction.REPORT_METADATA_REVIEW_RESULT_UNKNOWN


@pytest.mark.parametrize(
    ("summary", "expected_action"),
    [
        (
            MetadataReadSummary(total=3, read=2, failed=1, cancelled=0),
            BugReportAction.REPORT_METADATA_REVIEW_COMPLETED_WITH_WARNINGS,
        ),
        (
            MetadataReadSummary(total=3, read=0, failed=3, cancelled=0),
            BugReportAction.REPORT_METADATA_REVIEW_FAILED,
        ),
        (
            MetadataReadSummary(total=0, read=0, failed=0, cancelled=0),
            BugReportAction.REPORT_METADATA_REVIEW_COMPLETED,
        ),
        (
            MetadataReadSummary(total=3, read=1, failed=1, cancelled=1),
            BugReportAction.REPORT_METADATA_REVIEW_CANCELLED,
        ),
    ],
)
def test_metadata_review_summary_maps_partial_failure_cancel_and_empty_results(
    qapplication_session, trace, summary, expected_action
):
    class SummaryReader:
        def read(self, *_args, **_kwargs):
            return summary

    completed = []
    worker = MetadataReviewThread(SummaryReader(), [], mode=MODE_FAST)
    worker.completed.connect(completed.append)

    _wait_for_worker(qapplication_session, worker)

    assert completed == [summary]
    assert [event.action for event in trace.snapshot().events] == [
        BugReportAction.REPORT_METADATA_REVIEW_STARTED,
        BugReportAction.OPTION_REPORT_REVIEW_OCR,
        expected_action,
    ]

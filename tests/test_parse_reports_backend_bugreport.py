"""CMM implementation details are reduced to closed per-operation backend events."""

from concurrent.futures import Future
from threading import Event

import pytest

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.parse_reports_thread import ParseReportsThread, parse_new_reports
from metroliza.shared.parse_contracts import ParseRequest
from metroliza.reports.report_repository import ReportImportDisposition
from metroliza.shared.safe_bugreport import (
    BugReportAction,
    BugReportCategory,
    SafeBugReportRecorder,
    build_bug_report_markdown,
)
from metroliza.parsing import parse_reports_thread as parse_thread_module


def _synthetic_cmm_parser(parse_backend, persistence_backend):
    parser = object.__new__(CMMReportParser)
    parser.parse_backend_used = parse_backend
    parser.persistence_backend_used = persistence_backend
    return parser


def test_cmm_backends_are_recorded_once_per_import_and_drop_dynamic_values(monkeypatch):
    marker = "confidential_backend_detail_882"
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(parse_thread_module, "_bugreport_recorder", recorder)
    thread = ParseReportsThread(ParseRequest("private-source", "private-db"))
    parsers = (
        _synthetic_cmm_parser("native", "python"),
        _synthetic_cmm_parser("native", "python"),
        _synthetic_cmm_parser("python", "native"),
        _synthetic_cmm_parser(marker, {marker: marker}),
    )

    for parser in parsers:
        thread._collect_cmm_backend_usage(parser)
    thread._collect_cmm_backend_usage(object())

    assert recorder.snapshot().events == ()
    thread._record_cmm_backend_actions_once()
    thread._record_cmm_backend_actions_once()

    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.CMM_PARSE_BACKEND_NATIVE_USED,
        BugReportAction.CMM_PARSE_BACKEND_PYTHON_USED,
        BugReportAction.CMM_PERSISTENCE_BACKEND_NATIVE_USED,
        BugReportAction.CMM_PERSISTENCE_BACKEND_PYTHON_USED,
    ]
    report = build_bug_report_markdown(BugReportCategory.OTHER, recorder.snapshot())
    for private_value in (marker, "private-source", "private-db"):
        assert private_value not in report


def test_import_seams_capture_backend_on_persistence_failure_and_cancel(
    monkeypatch, tmp_path
):
    marker = "confidential_parser_failure_marker_593"

    for two_stage in (False, True):
        for cancel_after_prepare in (False, True):
            recorder = SafeBugReportRecorder()
            monkeypatch.setattr(parse_thread_module, "_bugreport_recorder", recorder)
            thread = ParseReportsThread(ParseRequest("private-source", "private-db"))
            report = tmp_path / f"private-{two_stage}-{cancel_after_prepare}.pdf"
            report.write_bytes(b"synthetic source")
            cancellation = {"requested": False}
            parser_activity = Event()

            class SyntheticCMMParser(CMMReportParser):
                def __init__(self):
                    self.parse_backend_used = "unknown"
                    self.persistence_backend_used = "unknown"
                    self.stage_timings_s = {}

                def prepare_for_two_stage_pipeline(self):
                    self.parse_backend_used = "native"
                    cancellation["requested"] = cancel_after_prepare

            parser = SyntheticCMMParser()

            def on_parser_activity(current_parser):
                thread._collect_cmm_backend_usage(current_parser)
                parser_activity.set()

            def persist(current_parser):
                current_parser.persistence_backend_used = "python"
                raise RuntimeError(marker)

            result = parse_new_reports(
                [report],
                set(),
                parser_factory=lambda *_args, **_kwargs: parser,
                persist_report=persist,
                should_cancel=lambda: cancellation["requested"],
                enable_two_stage_pipeline=two_stage,
                require_typed_persistence_outcome=True,
                log_file_failures=False,
                on_parser_activity=on_parser_activity,
            )
            if two_stage:
                assert parser_activity.wait(5)
            thread._record_cmm_backend_actions_once()

            actions = [event.action for event in recorder.snapshot().events]
            assert BugReportAction.CMM_PARSE_BACKEND_NATIVE_USED in actions
            if cancel_after_prepare:
                assert BugReportAction.CMM_PERSISTENCE_BACKEND_PYTHON_USED not in actions
                assert result.cancelled_files == 1
            else:
                assert BugReportAction.CMM_PERSISTENCE_BACKEND_PYTHON_USED in actions
                assert result.failed_files == 1

            report_text = build_bug_report_markdown(
                BugReportCategory.OTHER, recorder.snapshot()
            )
            assert marker not in report_text
            assert str(report) not in report_text


def test_two_stage_cancel_flush_marks_observation_incomplete_without_late_events(
    monkeypatch, tmp_path
):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(parse_thread_module, "_bugreport_recorder", recorder)
    cancellation = {"requested": False}
    thread = ParseReportsThread(ParseRequest("private-source", "private-db"))
    second_worker_started = Event()
    allow_second_worker_to_finish = Event()
    observed_futures = {}

    class SyntheticCMMParser(CMMReportParser):
        def __init__(self, backend):
            self.backend = backend
            self.parse_backend_used = "unknown"
            self.persistence_backend_used = "unknown"
            self.stage_timings_s = {}

        def prepare_for_two_stage_pipeline(self):
            if self.backend == "python":
                second_worker_started.set()
                assert allow_second_worker_to_finish.wait(10)
            self.parse_backend_used = self.backend

    report_a = tmp_path / "private-report-a.pdf"
    report_b = tmp_path / "private-report-b.pdf"
    report_a.write_bytes(b"synthetic A")
    report_b.write_bytes(b"synthetic B")
    parsers = {
        str(report_a): SyntheticCMMParser("native"),
        str(report_b): SyntheticCMMParser("python"),
    }

    def controlled_as_completed(futures):
        first, second = tuple(futures)
        observed_futures["second"] = second
        assert second_worker_started.wait(5)
        first.result(timeout=5)
        yield first
        cancellation["requested"] = True
        yield second

    monkeypatch.setattr(parse_thread_module, "as_completed", controlled_as_completed)
    result = parse_new_reports(
        [report_a, report_b],
        set(),
        parser_factory=lambda path, **_kwargs: parsers[str(path)],
        persist_report=lambda _parser: ReportImportDisposition.IMPORTED,
        should_cancel=lambda: cancellation["requested"],
        enable_two_stage_pipeline=True,
        require_typed_persistence_outcome=True,
        on_parser_activity=thread._collect_cmm_backend_usage,
        on_parser_worker_state=thread._set_cmm_parser_worker_active,
    )

    assert result.imported_files == 1 and result.cancelled_files == 1
    thread._record_cmm_backend_actions_once()
    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.CMM_PARSE_BACKEND_NATIVE_USED,
        BugReportAction.CMM_BACKEND_OBSERVATION_INCOMPLETE,
    ]
    report = build_bug_report_markdown(BugReportCategory.OTHER, recorder.snapshot())
    assert "`cmm_backend_observation_incomplete`" in report

    # Import cancellation returned without waiting for worker B; its later result stays local.
    allow_second_worker_to_finish.set()
    observed_futures["second"].result(timeout=5)
    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.CMM_PARSE_BACKEND_NATIVE_USED,
        BugReportAction.CMM_BACKEND_OBSERVATION_INCOMPLETE,
    ]


def test_submitted_running_future_counts_before_worker_entry_and_pending_cancel_releases(
    monkeypatch, tmp_path
):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(parse_thread_module, "_bugreport_recorder", recorder)
    thread = ParseReportsThread(ParseRequest("private-source", "private-db"))
    cancellation = {"requested": False}

    class ControlledExecutor:
        def __init__(self, **_kwargs):
            self.futures = []

        def submit(self, _callback, *_args):
            future = Future()
            if not self.futures:
                # Submitted/running, but this executor deliberately has not entered the worker.
                assert future.set_running_or_notify_cancel()
            self.futures.append(future)
            return future

        def shutdown(self, *, wait, cancel_futures):
            assert wait is False
            assert cancel_futures is True

    executor_instances = []

    def make_executor(**kwargs):
        executor = ControlledExecutor(**kwargs)
        executor_instances.append(executor)
        return executor

    def cancel_before_worker_entry(futures):
        assert len(tuple(futures)) == 2
        cancellation["requested"] = True
        yield executor_instances[0].futures[0]

    monkeypatch.setattr(parse_thread_module, "ThreadPoolExecutor", make_executor)
    monkeypatch.setattr(parse_thread_module, "as_completed", cancel_before_worker_entry)
    reports = []
    for name in ("private-running.pdf", "private-pending.pdf"):
        report = tmp_path / name
        report.write_bytes(b"synthetic")
        reports.append(report)

    result = parse_new_reports(
        reports,
        set(),
        parser_factory=lambda *_args, **_kwargs: pytest.fail("worker must not start"),
        persist_report=lambda _parser: pytest.fail("persistence must not start"),
        should_cancel=lambda: cancellation["requested"],
        enable_two_stage_pipeline=True,
        require_typed_persistence_outcome=True,
        on_parser_activity=thread._collect_cmm_backend_usage,
        on_parser_worker_state=thread._set_cmm_parser_worker_active,
    )

    running, pending = executor_instances[0].futures
    assert running.running() and pending.cancelled()
    assert thread._cmm_active_parser_workers == 1
    assert result.cancelled_files == 2

    thread._record_cmm_backend_actions_once()
    report = build_bug_report_markdown(BugReportCategory.OTHER, recorder.snapshot())
    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.CMM_BACKEND_OBSERVATION_INCOMPLETE,
    ]
    assert "`cmm_backend_observation_incomplete`" in report

    # Once the never-entered running future completes, its callback releases the count.
    running.set_result(None)
    assert thread._cmm_active_parser_workers == 0
    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.CMM_BACKEND_OBSERVATION_INCOMPLETE,
    ]
    report = build_bug_report_markdown(BugReportCategory.OTHER, recorder.snapshot())
    assert "`cmm_backend_observation_incomplete`" in report

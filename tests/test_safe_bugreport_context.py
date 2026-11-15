"""Acceptance of the complete content-free v2 report and retained context."""
from dataclasses import replace
import json
from threading import Event
import uuid

import pytest

from metroliza.shared import safe_bugreport as s
from metroliza.shared.safe_bugreport_context import (
    BugReportContextSelection, ContextModule, ContextSymptom, ContextBehavior,
    ContextOperationOutcome, MAX_OPTION_SNAPSHOTS, OptionSnapshotKind,
    SafeBugReportProvenance, V2_PREFIX, parse_v2_report,
)
from metroliza.shared.workflow_diagnostics import WorkflowTrace
from metroliza.shared.diagnostic_events import WorkflowOperation, WorkflowError
from scripts.reproduce_safe_bugreport import match_safe_bugreport


def report(recorder, **kwargs):
    activity, context = recorder.report_snapshot()
    return s.build_bug_report_markdown(
        s.BugReportCategory.WRONG_OUTPUT, activity, release_version="0.8.0-dev.3",
        context=BugReportContextSelection(context, **kwargs),
    )


def test_safe_workflow_causes_and_correlations_are_no_longer_discarded(monkeypatch):
    observed = []
    for error in (WorkflowError.INPUT_REJECTED, WorkflowError.PROCESSING_FAILED):
        recorder = s.SafeBugReportRecorder()
        monkeypatch.setattr(s, "recorder", recorder)
        trace = WorkflowTrace(WorkflowOperation.SELECTED_IMPORT)
        trace.fail(error)
        raw = parse_v2_report(report(recorder))
        workflows = [event["workflow"] for event in raw["context"]["events"] if event["kind"] == "workflow"]
        assert workflows[0]["operation_id"] == workflows[-1]["operation_id"]
        assert workflows[-1]["duration_ms"] is not None
        observed.append(workflows[-1]["error"])
    assert observed == ["input_rejected", "processing_failed"]


def test_option_history_survives_action_churn_and_later_requests():
    recorder = s.SafeBugReportRecorder()
    token = recorder.record_option_snapshot(OptionSnapshotKind.CSV_ANALYSIS, {
        "workbook": True, "separate_parameter_sheets": True, "chart_histogram": False,
    })
    assert type(token) is uuid.UUID
    assert recorder.record_option_outcome(token, ContextOperationOutcome.FAILED)
    next_token = recorder.record_option_snapshot(OptionSnapshotKind.CSV_ANALYSIS, {"workbook": False})
    assert next_token != token
    for _ in range(s.MAX_EVENTS + 1):
        recorder.record(s.BugReportAction.LOG_ERROR_UI)
    raw = parse_v2_report(report(recorder))
    options = raw["context"]["options"]
    assert [item["operation_id"] for item in options] == [str(token), str(next_token)]
    assert options[0]["options"]["separate_parameter_sheets"] is True
    assert raw["context"]["events_lost"] is True
    assert raw["context"]["snapshots_lost"] is False


def test_option_snapshot_eviction_is_bounded_and_disclosed():
    recorder = s.SafeBugReportRecorder()
    for _ in range(MAX_OPTION_SNAPSHOTS + 1):
        recorder.record_option_snapshot(OptionSnapshotKind.CSV_ANALYSIS, {"workbook": True})
    raw = parse_v2_report(report(recorder))
    assert len(raw["context"]["options"]) == MAX_OPTION_SNAPSHOTS
    assert raw["context"]["snapshots_lost"] is True


def test_terminal_requires_own_live_token():
    recorder = s.SafeBugReportRecorder()
    token = recorder.record_option_snapshot(OptionSnapshotKind.CSV_ANALYSIS, {"workbook": True})
    assert not recorder.record_option_outcome(uuid.uuid4(), ContextOperationOutcome.COMPLETED)
    assert recorder.record_option_outcome(token, ContextOperationOutcome.CANCELLED)
    assert not recorder.record_option_outcome(token, ContextOperationOutcome.COMPLETED)


def test_context_restart_and_explicit_clear_remove_both_histories(tmp_path):
    root = tmp_path / "private-history"
    first = s.SafeBugReportRecorder()
    first.record(s.BugReportAction.APP_OPENED)
    assert first.configure_history(root)
    token = first.record_option_snapshot(OptionSnapshotKind.CSV_ANALYSIS, {"workbook": True})
    assert first.record_option_outcome(token, ContextOperationOutcome.FAILED)
    assert first.flush(5)
    assert first.close_history(5)
    second = s.SafeBugReportRecorder()
    try:
        assert second.configure_history(root)
        assert second.flush(5)
        raw = parse_v2_report(report(second))
        assert raw["context"]["options"][0]["operation_id"] == str(token)
        assert any(e.get("request", {}).get("outcome") == "failed" for e in raw["context"]["events"])
        old_generation = second.context_snapshot().generation
        assert second.clear_history()
        assert second.flush(5)
        assert second.history_generation() > old_generation
        raw = parse_v2_report(report(second))
        assert raw["context"]["events"] == raw["context"]["options"] == []
        assert json.loads((root / "context.json").read_text())["context"]["options"] == []
        assert json.loads((root / "activity.json").read_text())["events"] == []
    finally:
        second.close_history(5)


def test_first_history_write_makes_current_context_available(tmp_path):
    recorder = s.SafeBugReportRecorder()
    try:
        assert recorder.configure_history(tmp_path / "history")
        recorder.record(s.BugReportAction.APP_OPENED)
        assert recorder.flush(5)
        assert recorder.context_snapshot().snapshot_state == "available"
        assert "Inspect the source for the recorded actions" in report(recorder)
        assert "distinguish evidence, hypotheses and unverified behavior" in report(recorder)
    finally:
        recorder.close_history(5)


@pytest.mark.parametrize("write_kind", ["context", "activity"])
def test_stale_failed_write_and_callback_do_not_contaminate_cleared_context(tmp_path, monkeypatch, write_kind):
    recorder = s.SafeBugReportRecorder()
    assert recorder.configure_history(tmp_path / "history")
    assert recorder.flush(5)
    token = recorder.record_option_snapshot(OptionSnapshotKind.CSV_ANALYSIS, {"workbook": True})
    assert recorder.flush(5)
    entered, release = Event(), Event()
    calls = []
    if write_kind == "context":
        original = s.save_context_locked

        def blocked(*args, **kwargs):
            if not calls:
                calls.append(True)
                entered.set()
                release.wait(5)
                return False
            return original(*args, **kwargs)

        monkeypatch.setattr(s, "save_context_locked", blocked)
    else:
        original = s.LocalBugReportHistoryStore.append_locked

        def blocked(*args, **kwargs):
            if not calls:
                calls.append(True)
                entered.set()
                release.wait(5)
                return False
            return original(*args, **kwargs)

        monkeypatch.setattr(s.LocalBugReportHistoryStore, "append_locked", blocked)
    try:
        recorder.record(s.BugReportAction.LOG_ERROR_UI)
        assert entered.wait(3)
        assert recorder.clear_history()
        assert not recorder.record_option_outcome(token, ContextOperationOutcome.COMPLETED)
        release.set()
        assert recorder.flush(5)
        assert recorder.snapshot().clear_state == "complete"
        assert recorder.context_snapshot().events_lost is False
        assert recorder.context_snapshot().snapshot_state == "available"
        assert recorder.context_snapshot().options == ()
    finally:
        release.set()
        recorder.close_history(5)


@pytest.mark.parametrize("bad", ["CONFIDENTIAL", 1, None, [], {"secret": "SYNTHETIC_PRIVATE"}])
def test_context_option_values_never_accept_open_data(bad):
    recorder = s.SafeBugReportRecorder()
    assert recorder.record_option_snapshot(OptionSnapshotKind.CSV_ANALYSIS, {"workbook": bad}) is None
    assert "CONFIDENTIAL" not in report(recorder)
    assert "SYNTHETIC_PRIVATE" not in report(recorder)


def test_provenance_and_json_are_fail_closed():
    recorder = s.SafeBugReportRecorder()
    provenance = SafeBugReportProvenance(git_sha="a" * 64, platform="windows", python="3.11.16")
    valid = report(recorder, provenance=provenance)
    assert parse_v2_report(valid)["provenance"]["git_sha"] == "a" * 64
    invalid = report(recorder, provenance=replace(provenance, git_sha="SYNTHETIC_PRIVATE_PATH"))
    assert invalid == s.BUG_REPORT_UNAVAILABLE
    ambiguous = valid.replace('"schema": 2', '"schema": 9, "schema": 2')
    with pytest.raises(ValueError):
        parse_v2_report(ambiguous)
    with pytest.raises(ValueError):
        s._decode_history(b'{"schema":9,"schema":1,"events":[],"events_lost":false}')


def test_closed_problem_description_roundtrips_without_customer_text():
    recorder = s.SafeBugReportRecorder()
    raw = parse_v2_report(report(
        recorder, module=ContextModule.REPORTS, symptom=ContextSymptom.MISSING_CHARTS,
        expected=ContextBehavior.ALL_REQUESTED_OUTPUTS, observed=ContextBehavior.MISSING_OUTPUT,
    ))
    assert raw["selection"] == {
        "module": "reports", "symptom": "missing_charts",
        "expected": "all_requested_outputs", "observed": "missing_output",
    }
    assert match_safe_bugreport(report(recorder, module=ContextModule.DATABASE)).scenario == "none"


def test_preview_freezes_background_events_and_explicit_refresh(qapplication_session, monkeypatch):
    from metroliza.ui import safe_bugreport_dialog as ui
    recorder = s.SafeBugReportRecorder()
    recorder.record(s.BugReportAction.APP_OPENED)
    monkeypatch.setattr(ui, "recorder", recorder)
    dialog = ui.SafeBugReportDialog()
    try:
        preview = dialog.preview.toPlainText()
        assert preview.startswith(V2_PREFIX)
        recorder.record(s.BugReportAction.WORKSPACE_DATABASE_OPENED)
        dialog.copy_report()
        assert qapplication_session.clipboard().text() == preview
        dialog.refresh_snapshot()
        assert dialog.preview.toPlainText() != preview
    finally:
        dialog.close()


def test_clear_from_another_dialog_invalidates_frozen_preview(qapplication_session, monkeypatch, tmp_path):
    from metroliza.ui import safe_bugreport_dialog as ui
    recorder = s.SafeBugReportRecorder()
    assert recorder.configure_history(tmp_path / "history")
    recorder.record(s.BugReportAction.APP_OPENED)
    assert recorder.flush(5)
    monkeypatch.setattr(ui, "recorder", recorder)
    dialog = ui.SafeBugReportDialog()
    try:
        qapplication_session.clipboard().setText("synthetic-unchanged-clipboard")
        assert recorder.clear_history()
        assert recorder.flush(5)
        dialog.copy_report()
        assert qapplication_session.clipboard().text() == "synthetic-unchanged-clipboard"
        assert "cleared" in dialog.status_label.text().lower()
    finally:
        dialog.close()
        recorder.close_history(5)

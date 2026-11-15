"""Runner ordering, real receipts, cancellation, collision and privacy controls."""
from dataclasses import replace
import json
import threading
from uuid import UUID

import pytest

from metroliza.recipes.bindings import resolve_plan
from metroliza.recipes.builtin_recipes import (
    REPORTS_DASHBOARD_HTML, REPORTS_EXCEL_MAIN, builtin_binding,
)
from metroliza.recipes.contracts import StepKind
from metroliza.recipes.diagnostics import safe_run_projection
from metroliza.recipes.ports import PreflightResult, ResultCode, StepResult, StepStatus
from metroliza.recipes.run_state import RunState
from metroliza.recipes.runner import RecipeRunner


class FakePorts:
    def __init__(self, *, partial=False, cancel_step=None, missing_output=False):
        self.calls = []
        self.contexts = []
        self.partial = partial
        self.cancel_step = cancel_step
        self.missing_output = missing_output
        self.runner = None
        self.approvals = []

    def preflight(self, plan, context):
        self.calls.append("preflight")
        self.contexts.append(context)
        return PreflightResult(True)

    def approve(self, plan, decision):
        self.approvals.append(decision)
        return True

    def execute(self, step, plan, context):
        self.calls.append(step.kind)
        self.contexts.append(context)
        if step.kind is self.cancel_step:
            self.runner.cancel()
            return StepResult(StepStatus.COMPLETED, imported_count=1)
        if step.kind is StepKind.IMPORT_REPORTS:
            plan.database_file.parent.mkdir(parents=True, exist_ok=True)
            plan.database_file.write_bytes(b"synthetic db")
            if self.partial:
                return StepResult(StepStatus.PARTIAL, ResultCode.PARTIAL_IMPORT,
                                  imported_count=1, rejected_count=1)
        if step.kind in {StepKind.EXPORT_MAIN, StepKind.EXPORT_HTML} and not self.missing_output:
            plan.output_file.write_bytes(b"synthetic nonempty verified artifact")
        if step.kind is StepKind.VERIFY_OUTPUT:
            verified = plan.output_file.exists()
            return StepResult(StepStatus.COMPLETED if verified else StepStatus.FAILED,
                              ResultCode.SUCCESS if verified else ResultCode.OUTPUT_MISSING,
                              artifact_verified=verified)
        return StepResult(StepStatus.COMPLETED)

    def cancel(self):
        self.calls.append("cancel")


def make_plan(tmp_path, definition=REPORTS_EXCEL_MAIN):
    suffix = ".html" if definition is REPORTS_DASHBOARD_HTML else ".xlsx"
    return resolve_plan(definition, builtin_binding(definition, str(tmp_path / "source"),
        str(tmp_path / "output" / ("PRIVATE_SENTINEL" + suffix))))


@pytest.mark.parametrize("definition", [REPORTS_EXCEL_MAIN, REPORTS_DASHBOARD_HTML])
def test_linear_flow_waits_for_receipts_and_correlates_actual_calls(tmp_path, definition):
    plan = make_plan(tmp_path, definition)
    ports = FakePorts()
    events = []
    runner = RecipeRunner(ports, events.append)
    ports.runner = runner
    record = runner.start(plan)
    assert record.state is RunState.COMPLETED
    assert ports.calls == ["preflight", *(step.kind for step in definition.steps)]
    assert plan.database_file.exists() and plan.output_file.stat().st_size > 0
    assert len({c.step_id for c in ports.contexts}) == len(ports.contexts)
    for context in ports.contexts:
        assert UUID(context.step_id).version == 4 and context.run_id == record.run_id
    assert not record.ownership
    assert "PRIVATE_SENTINEL" not in json.dumps(safe_run_projection(record))
    assert str(tmp_path) not in json.dumps(safe_run_projection(record))


def test_partial_import_requires_explicit_continuation_and_keeps_provenance(tmp_path):
    ports = FakePorts(partial=True)
    runner = RecipeRunner(ports)
    plan = make_plan(tmp_path)
    try:
        record = runner.start(plan)
        assert record.state is RunState.REQUIRES_DECISION and record.partial_import
        assert StepKind.EXPORT_MAIN not in ports.calls
        assert runner.resume("continue").state is RunState.REQUIRES_DECISION
        done = runner.resume("continue_partial")
        assert done.state is RunState.COMPLETED_WITH_WARNINGS
        assert done.partial_import
        assert ports.calls.count("preflight") == 1
    finally:
        runner.cancel()


def test_cancel_stops_following_step_and_keeps_completed_import_receipt(tmp_path):
    ports = FakePorts(cancel_step=StepKind.IMPORT_REPORTS)
    runner = RecipeRunner(ports)
    ports.runner = runner
    record = runner.start(make_plan(tmp_path))
    assert record.state is RunState.CANCELLED
    assert StepKind.EXPORT_MAIN not in ports.calls
    assert record.steps[-1].result.imported_count == 1
    assert not record.ownership


def test_existing_database_requires_new_family_and_never_implicitly_appends(tmp_path):
    plan = make_plan(tmp_path)
    plan.database_file.parent.mkdir(parents=True)
    plan.database_file.write_bytes(b"PREVIOUS_COMPLETE")
    ports = FakePorts()
    runner = RecipeRunner(ports)
    try:
        assert runner.start(plan).state is RunState.REQUIRES_DECISION
        assert not ports.calls
        assert runner.resume("continue").state is RunState.REQUIRES_DECISION
        copy_ready = runner.resume("new_copy")
        assert copy_ready.state is RunState.REQUIRES_DECISION
        assert copy_ready.decision == "copy_ready"
        assert not ports.calls and not runner.plan.database_file.exists()
        result = runner.resume("continue")
        assert result.state is RunState.COMPLETED
        assert plan.database_file.read_bytes() == b"PREVIOUS_COMPLETE"
        assert runner.plan.database_file.stem == runner.plan.output_file.stem
    finally:
        runner.cancel()


def test_only_one_flow_owns_resources_including_decision_pause(tmp_path):
    first_plan = make_plan(tmp_path)
    first_plan.database_file.parent.mkdir(parents=True)
    first_plan.database_file.touch()
    first = RecipeRunner(FakePorts())
    second = RecipeRunner(FakePorts())
    try:
        assert first.start(first_plan).state is RunState.REQUIRES_DECISION
        assert second.start(make_plan(tmp_path / "other")).code is ResultCode.BUSY
    finally:
        first.cancel()
    assert second.start(make_plan(tmp_path / "other")).state is RunState.COMPLETED


def test_missing_output_and_tampered_snapshot_never_succeed(tmp_path):
    plan = make_plan(tmp_path)
    assert RecipeRunner(FakePorts(missing_output=True)).start(plan).state is RunState.FAILED
    tampered = replace(make_plan(tmp_path / "other"), database_file=tmp_path / "unbound.db")
    ports = FakePorts()
    assert RecipeRunner(ports).start(tampered).code is ResultCode.INVALID_PLAN
    assert not ports.calls


@pytest.mark.parametrize("field,value", [("elapsed_ms", True), ("elapsed_ms", float("nan")),
                                         ("partial_import", "PRIVATE_SENTINEL")])
def test_safe_projection_rejects_nonexact_runtime_types(tmp_path, field, value):
    record = RecipeRunner(FakePorts()).start(make_plan(tmp_path))
    with pytest.raises(ValueError):
        safe_run_projection(replace(record, **{field: value}))


def test_terminal_cleanup_runs_once_and_releases_owner(tmp_path):
    ports = FakePorts()
    cleaned = []
    ports.finish = lambda plan: cleaned.append(plan.run_id)
    runner = RecipeRunner(ports)
    record = runner.start(make_plan(tmp_path))
    runner.cancel()
    assert cleaned == [record.run_id]
    assert not record.ownership


def test_new_copy_cleans_old_identity_and_publishes_plan_before_any_effect(tmp_path):
    plan = make_plan(tmp_path)
    plan.database_file.parent.mkdir(parents=True)
    plan.database_file.write_bytes(b"OLD_DATABASE")
    ports = FakePorts()
    cleaned, observed = [], []
    runner = RecipeRunner(ports)
    ports.finish = lambda old: cleaned.append((old.run_id, runner.plan.run_id))
    runner.on_event = lambda event: observed.append((event.record, runner.plan))
    try:
        runner.start(plan)
        copied = runner.resume("new_copy")
        assert copied.decision == "copy_ready"
        assert copied.state is RunState.REQUIRES_DECISION
        assert cleaned == [(plan.run_id, plan.run_id)]
        assert copied.run_id != plan.run_id
        assert observed[-1][1].output_file == runner.plan.output_file
        assert observed[-1][1].database_file == runner.plan.database_file
        assert not ports.calls and not runner.plan.database_file.exists()
        assert runner.resume("continue").state is RunState.COMPLETED
        assert not ports.approvals  # New family obtains its own fresh preflight.
        assert plan.database_file.read_bytes() == b"OLD_DATABASE"
    finally:
        runner.cancel()


def test_large_committed_import_keeps_actual_success_and_bounds_only_diagnostics(tmp_path):
    class LargePorts(FakePorts):
        def execute(self, step, plan, context):
            result = super().execute(step, plan, context)
            return replace(result, imported_count=20_001) if step.kind is StepKind.IMPORT_REPORTS else result
    ports = LargePorts()
    record = RecipeRunner(ports).start(make_plan(tmp_path))
    assert record.state is RunState.COMPLETED
    imported = next(step for step in record.steps if step.kind is StepKind.IMPORT_REPORTS)
    assert imported.result.imported_count == 20_001
    safe = next(step for step in safe_run_projection(record)["steps"] if step["kind"] == "import_reports")
    assert safe["imported_count"] == 10_000 and safe["imported_count_truncated"] is True
    assert safe["rejected_count"] == 0 and safe["rejected_count_truncated"] is False


def test_cancel_between_ui_admission_and_worker_start_is_not_erased(tmp_path):
    ports = FakePorts()
    runner = RecipeRunner(ports)
    plan = make_plan(tmp_path)
    token = runner.admit_start(plan)
    runner.cancel()  # Deterministic UI cancellation before scheduled QThread entry.
    record = runner.start(plan, admission=token)
    assert record.state is RunState.CANCELLED and not record.ownership
    assert not ports.calls
    assert not plan.database_file.exists() and not plan.output_file.exists()


def test_cancellation_serializes_receipts_and_event_sequences_across_threads(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class BlockingPorts(FakePorts):
        def execute(self, step, plan, context):
            result = super().execute(step, plan, context)
            if step.kind is StepKind.IMPORT_REPORTS:
                entered.set()
                assert release.wait(5)
                return replace(result, imported_count=10_001)
            return result
    ports, events, returned = BlockingPorts(), [], []
    runner = RecipeRunner(ports, events.append)
    plan = make_plan(tmp_path)
    token = runner.admit_start(plan)
    worker = threading.Thread(target=lambda: returned.append(runner.start(plan, admission=token)))
    worker.start()
    try:
        assert entered.wait(5)
        runner.cancel()
        release.set()
        worker.join(5)
        assert not worker.is_alive()
        assert returned[0].state is RunState.CANCELLED
        assert returned[0].steps[-1].result.imported_count == 10_001
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert StepKind.EXPORT_MAIN not in ports.calls
    finally:
        release.set()
        worker.join(5)
        runner.cancel()


def test_cancel_at_return_boundary_overrides_stale_decision_receipt(tmp_path, monkeypatch):
    plan = make_plan(tmp_path)
    plan.database_file.parent.mkdir(parents=True)
    plan.database_file.touch()
    runner = RecipeRunner(FakePorts())
    release_execution = runner._release_execution
    def cancel_before_native_retirement():
        runner.cancel()  # Cancellation accepted after decision result was computed.
        return release_execution()
    monkeypatch.setattr(runner, "_release_execution", cancel_before_native_retirement)
    record = runner.start(plan)
    assert record.state is RunState.CANCELLED and not record.ownership
    assert runner.record is record

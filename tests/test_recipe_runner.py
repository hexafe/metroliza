"""Runner ordering, real receipts, cancellation, collision and privacy controls."""
from dataclasses import replace
import json
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
        result = runner.resume("new_copy")
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

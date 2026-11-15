"""Flow states are observable without names, paths, configuration or measurement rows."""
from dataclasses import replace
from uuid import uuid4

import pytest

from metroliza.recipes.flow_diagnostics import RecipeFlowTrace
from metroliza.recipes.ports import ResultCode
from metroliza.recipes.run_state import RunEvent, RunRecord, RunState
from metroliza.shared.diagnostic_events import (
    DiagnosticEventValidationError, RecipeFlowState, WorkflowDiagnosticEvent,
    WorkflowOperation, WorkflowOutcome, WorkflowStage,
)
from metroliza.shared.diagnostic_wire import decode_event, encode_event


def test_decision_partial_failure_and_cancel_reach_managed_wire(caplog):
    trace = RecipeFlowTrace()
    record = RunRecord(str(uuid4()), str(uuid4()), RunState.RUNNING)
    states = (RunState.RUNNING, RunState.REQUIRES_DECISION, RunState.CANCELLING, RunState.CANCELLED)
    with caplog.at_level("INFO"):
        for state in states:
            trace.observe(RunEvent(replace(record, state=state)))
        trace.observe(RunEvent(replace(record, run_id=str(uuid4()), state=RunState.PARTIAL,
                                      code=ResultCode.PARTIAL_IMPORT)))
        trace.observe(RunEvent(replace(record, run_id=str(uuid4()), state=RunState.FAILED,
                                      code=ResultCode.OUTPUT_MISSING)))
    events = [row.msg for row in caplog.records if type(row.msg) is WorkflowDiagnosticEvent]
    assert [row.flow_state.value for row in events] == [state.value for state in states] + ["partial", "failed"]
    for event in events:
        assert event.operation is WorkflowOperation.RECIPE_FLOW
        assert decode_event(encode_event(event)) == event
        assert event.selected_report_count is event.imported_report_count is None


def test_progress_is_not_per_measurement_diagnostic_and_no_private_fallback(caplog):
    trace = RecipeFlowTrace()
    event = RunEvent(RunRecord(str(uuid4()), str(uuid4()), RunState.RUNNING))
    with caplog.at_level("INFO"):
        trace.observe(event)
        for number in range(100):
            trace.observe(replace(event, completed=number, total=100))
        trace.observe({"private_name": "PRIVATE_SENTINEL"})
    assert len(caplog.records) == 1
    assert "PRIVATE_SENTINEL" not in encode_event(caplog.records[0].msg).decode()


def test_flow_state_requires_its_operation_correlation_and_consistent_terminal():
    event = WorkflowDiagnosticEvent(uuid4(), uuid4(), 1, WorkflowOperation.RECIPE_FLOW,
        WorkflowStage.FINISHED, WorkflowOutcome.COMPLETED, flow_id=uuid4(), run_id=uuid4(),
        step_id=uuid4(), flow_state=RecipeFlowState.COMPLETED)
    for fields in ({"flow_state": "PRIVATE_SENTINEL"}, {"flow_id": None},
                   {"flow_state": RecipeFlowState.REQUIRES_DECISION},
                   {"operation": WorkflowOperation.LOCAL_EXPORT}):
        with pytest.raises(DiagnosticEventValidationError):
            replace(event, **fields)

"""Runtime correlation is optional, UUID-only and survives the managed wire."""
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from metroliza.shared.diagnostic_events import (
    DiagnosticEventValidationError, WorkflowDiagnosticEvent, WorkflowOperation,
    WorkflowOutcome, WorkflowStage,
)
from metroliza.shared.diagnostic_wire import WireValidationError, decode_event, encode_event
from metroliza.shared.workflow_diagnostics import WorkflowTrace, recipe_workflow_scope


def _event(**kwargs):
    return WorkflowDiagnosticEvent(
        uuid4(), uuid4(), 1, WorkflowOperation.LOCAL_EXPORT,
        WorkflowStage.STARTED, WorkflowOutcome.STARTED, **kwargs,
    )


def test_legacy_wire_is_unchanged():
    event = _event()
    encoded = encode_event(event)
    assert "flow_id" not in json.loads(encoded)
    assert decode_event(encoded) == event


def test_runtime_triple_roundtrip():
    event = _event(flow_id=uuid4(), run_id=uuid4(), step_id=uuid4())
    assert decode_event(encode_event(event)) == event


@pytest.mark.parametrize("value", ["PRIVATE_PATH_SENTINEL", None, 42])
def test_incomplete_or_private_correlation_rejected(value):
    with pytest.raises(DiagnosticEventValidationError):
        _event(flow_id=value, run_id=uuid4(), step_id=uuid4())


def test_wire_rejects_partial_triple():
    payload = json.loads(encode_event(_event()))
    payload["run_id"] = uuid4().hex
    with pytest.raises(WireValidationError):
        decode_event(json.dumps(payload).encode("ascii"))


def test_nonruntime_uuid_and_shared_identifiers_rejected():
    event = _event(flow_id=uuid4(), run_id=uuid4(), step_id=uuid4())
    with pytest.raises(DiagnosticEventValidationError):
        replace(event, step_id=event.run_id)


def test_actual_trace_scope_restores_outer_correlation(caplog):
    identifiers = (uuid4(), uuid4(), uuid4())
    with caplog.at_level("INFO"):
        with recipe_workflow_scope(*identifiers):
            trace = WorkflowTrace(WorkflowOperation.LOCAL_EXPORT)
            trace.finish_export(completed=True, cancelled=False)
        WorkflowTrace(WorkflowOperation.LOCAL_EXPORT)
    events = [record.msg for record in caplog.records
              if type(record.msg) is WorkflowDiagnosticEvent]
    assert len(events) == 3
    assert all((event.flow_id, event.run_id, event.step_id) == identifiers for event in events[:2])
    assert events[-1].flow_id is None

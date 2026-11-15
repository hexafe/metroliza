"""Content-free flow transitions through the existing managed diagnostic wire."""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from metroliza.shared.diagnostic_events import (
    RecipeFlowState, WorkflowDiagnosticEvent, WorkflowError, WorkflowOperation,
    WorkflowOutcome, WorkflowStage,
)
from metroliza.shared.diagnostic_transport import supervised_invocation_id
from .ports import ResultCode
from .run_state import RunEvent, RunState

_TERMINAL = {
    RunState.COMPLETED: WorkflowOutcome.COMPLETED,
    RunState.COMPLETED_WITH_WARNINGS: WorkflowOutcome.COMPLETED_WITH_WARNINGS,
    RunState.PARTIAL: WorkflowOutcome.COMPLETED_WITH_WARNINGS,
    RunState.FAILED: WorkflowOutcome.FAILED,
    RunState.CANCELLED: WorkflowOutcome.CANCELLED,
}
_ERRORS = {
    ResultCode.IMPORT_FAILED: WorkflowError.PROCESSING_FAILED,
    ResultCode.PARTIAL_IMPORT: WorkflowError.PROCESSING_FAILED,
    ResultCode.EXPORT_FAILED: WorkflowError.OUTPUT_FAILED,
    ResultCode.OUTPUT_MISSING: WorkflowError.OUTPUT_FAILED,
    ResultCode.INVALID_PLAN: WorkflowError.INPUT_REJECTED,
    ResultCode.SOURCE_CHANGED: WorkflowError.INPUT_REJECTED,
    ResultCode.REVIEW_REQUIRED: WorkflowError.INPUT_REJECTED,
    ResultCode.UNSUPPORTED: WorkflowError.INPUT_REJECTED,
}


class RecipeFlowTrace:
    """One bounded active span; progress values and private configuration are omitted."""
    def __init__(self):
        self.run_id = None
        self.signature = None
        self.invocation_id = supervised_invocation_id() or uuid4()
        self.operation_id = uuid4()
        self.boundary_id = uuid4()
        self.sequence = 0

    def observe(self, event: RunEvent) -> None:
        try:
            if type(event) is not RunEvent:
                return
            record = event.record
            if record.run_id != self.run_id:
                self.run_id = record.run_id
                self.operation_id, self.boundary_id = uuid4(), uuid4()
                self.sequence, self.signature = 0, None
            signature = (record.state, record.code, len(record.steps), event.step_id)
            if signature == self.signature:
                return
            self._emit(event)
            self.signature = signature
        except Exception:
            # A diagnostic sink cannot alter a flow or stringify private failures.
            return

    def _emit(self, event: RunEvent) -> None:
        record = event.record
        outcome = _TERMINAL.get(record.state)
        stage = WorkflowStage.FINISHED if outcome is not None else WorkflowStage.PROCESSING
        if outcome is None:
            outcome = WorkflowOutcome.STARTED if self.sequence == 0 else WorkflowOutcome.MILESTONE
            if self.sequence == 0:
                stage = WorkflowStage.STARTED
        error = WorkflowError.NONE
        if record.state is RunState.FAILED:
            error = _ERRORS.get(record.code, WorkflowError.UNKNOWN)
        elif record.state is RunState.PARTIAL:
            error = WorkflowError.PROCESSING_FAILED
        self.sequence += 1
        step_id = event.step_id or (record.steps[-1].step_id if record.steps else str(self.boundary_id))
        encoded = WorkflowDiagnosticEvent(
            self.invocation_id, self.operation_id, self.sequence,
            WorkflowOperation.RECIPE_FLOW, stage, outcome, error=error,
            flow_id=UUID(record.flow_id), run_id=UUID(record.run_id), step_id=UUID(step_id),
            flow_state=RecipeFlowState(record.state.value),
            duration_ms=min(86_400_000, max(0, record.elapsed_ms)) if stage is WorkflowStage.FINISHED else None,
        )
        logging.getLogger(__name__).log(
            logging.ERROR if record.state is RunState.FAILED else logging.INFO, encoded,
        )

"""Small, best-effort adapters at whole-operation boundaries, never per measurement."""

from __future__ import annotations

import logging
import time
import uuid

from metroliza.shared.diagnostic_events import (
    WorkflowDiagnosticEvent, WorkflowError, WorkflowOperation, WorkflowOutcome, WorkflowStage,
)
from metroliza.shared.diagnostic_transport import supervised_invocation_id


class WorkflowTrace:
    def __init__(self, operation: WorkflowOperation):
        self.operation = operation
        self.sequence = 0
        self.finished = False
        self.selected_report_count: int | None = None
        self.started = time.monotonic()
        self.invocation_id = supervised_invocation_id() or uuid.uuid4()
        self.operation_id = uuid.uuid4()
        self.stage(WorkflowStage.STARTED)

    def stage(self, stage: WorkflowStage, *, selected_report_count: int | None = None) -> None:
        if stage is WorkflowStage.PREFLIGHT_COMPLETE:
            if type(selected_report_count) is int and 0 <= selected_report_count <= 10_000:
                self.selected_report_count = selected_report_count
        outcome = WorkflowOutcome.STARTED if stage is WorkflowStage.STARTED else WorkflowOutcome.MILESTONE
        self._emit(stage, outcome, selected_report_count=selected_report_count)

    def _emit(self, stage, outcome, *, error=WorkflowError.NONE, selected_report_count=None,
              imported_report_count=None):
        try:
            if self.finished:
                return
            self.sequence += 1
            count = selected_report_count
            if type(count) is not int or not 0 <= count <= 10_000:
                count = None
            imported = imported_report_count
            if type(imported) is not int or not 0 <= imported <= 10_000:
                imported = None
            elapsed = min(86_400_000, max(0, round((time.monotonic() - self.started) * 1000)))
            event = WorkflowDiagnosticEvent(
                self.invocation_id, self.operation_id, self.sequence, self.operation,
                stage, outcome, error=error, selected_report_count=count,
                imported_report_count=imported,
                duration_ms=elapsed if stage is WorkflowStage.FINISHED else None,
            )
            logging.getLogger(__name__).log(
                logging.ERROR if outcome is WorkflowOutcome.FAILED else logging.INFO, event,
            )
            if stage is WorkflowStage.FINISHED:
                self.finished = True
        except Exception:
            return

    def fail(self, error: WorkflowError) -> None:
        self._emit(WorkflowStage.FINISHED, WorkflowOutcome.FAILED, error=error)

    def finish_import(self, result, cancelled: bool) -> None:
        try:
            imported = getattr(result, "imported_files", 0)
            failed = getattr(result, "failed_files", 0)
            changed = getattr(result, "preflight_changed_files", 0)
            if cancelled or getattr(result, "cancelled_files", 0):
                outcome, error = WorkflowOutcome.CANCELLED, WorkflowError.NONE
            elif failed or changed:
                accepted = imported + getattr(result, "already_present_files", 0)
                outcome = WorkflowOutcome.COMPLETED_WITH_WARNINGS if accepted else WorkflowOutcome.FAILED
                error = WorkflowError.PROCESSING_FAILED if failed else WorkflowError.INPUT_REJECTED
            else:
                outcome, error = WorkflowOutcome.COMPLETED, WorkflowError.NONE
            self._emit(WorkflowStage.FINISHED, outcome, error=error, imported_report_count=imported,
                       selected_report_count=self.selected_report_count)
        except Exception:
            return

    def finish_export(self, *, completed: bool, cancelled: bool, fallback: bool = False,
                      omissions: bool = False) -> None:
        if cancelled:
            outcome, error = WorkflowOutcome.CANCELLED, WorkflowError.NONE
        elif completed:
            outcome = WorkflowOutcome.COMPLETED_WITH_FALLBACK if fallback else WorkflowOutcome.COMPLETED
            if omissions and not fallback:
                outcome = WorkflowOutcome.COMPLETED_WITH_OMISSIONS
            error = WorkflowError.NONE
        else:
            outcome, error = WorkflowOutcome.FAILED, WorkflowError.OUTPUT_FAILED
        self._emit(WorkflowStage.FINISHED, outcome, error=error)


class _UnavailableTrace:
    def stage(self, *_args, **_kwargs):
        return None

    def fail(self, *_args, **_kwargs):
        return None

    def finish_import(self, *_args, **_kwargs):
        return None

    def finish_export(self, *_args, **_kwargs):
        return None


def start_workflow_trace(operation: WorkflowOperation) -> WorkflowTrace | _UnavailableTrace:
    try:
        return WorkflowTrace(operation)
    except Exception:
        return _UnavailableTrace()

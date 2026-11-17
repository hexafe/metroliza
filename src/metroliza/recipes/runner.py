"""Single-owner linear runner. Ports return actual outcomes, never start receipts."""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from .bindings import new_output_copy, resolve_plan, validate_plan_paths
from .contracts import RecipeError, ResolvedRunPlan, StepKind
from .ports import PreparationPhase, PreflightResult, ReportsPorts, ResultCode, StepContext, StepResult, StepStatus
from .run_state import RunEvent, RunRecord, RunState, StepRecord
from .validation import validate_binding


class RecipeRunner:
    _owner_lock = threading.Lock()
    _owner: RecipeRunner | None = None

    def __init__(self, ports: ReportsPorts, on_event: Callable[[RunEvent], None] | None = None,
                 active_database: Path | None = None):
        self.ports = ports
        self.on_event = on_event
        self.active_database = active_database
        self.plan: ResolvedRunPlan | None = None
        self.record: RunRecord | None = None
        self.review: PreflightResult | None = None
        self._cancelled = threading.Event()
        self._execution = threading.Lock()
        self._state_lock = threading.RLock()
        self._admission: tuple[str, str] | None = None
        self._started = 0.0
        self._next_step = 0
        self._sequence = 0
        self._finished = False

    def _owns(self) -> bool:
        with self._owner_lock:
            return RecipeRunner._owner is self

    def _claim(self) -> bool:
        with self._owner_lock:
            if RecipeRunner._owner is not None:
                return False
            RecipeRunner._owner = self
            return True

    def _release(self) -> None:
        with self._owner_lock:
            if RecipeRunner._owner is self:
                RecipeRunner._owner = None

    def _publish(self, state: RunState | None = None, code: ResultCode | None = None,
                 *, step_id: str | None = None, step_kind: StepKind | None = None,
                 completed: int = 0, total: int = 0, decision: str = "",
                 phase: PreparationPhase | None = None) -> RunRecord:
        with self._state_lock:
            return self._publish_locked(state, code, step_id=step_id, step_kind=step_kind,
                completed=completed, total=total, decision=decision, phase=phase)

    def _cancelled_state(self, state, code):
        if not self._cancelled.is_set():
            return state, code
        if state is RunState.RUNNING:
            return RunState.CANCELLING, ResultCode.CANCELLED
        if state in {RunState.COMPLETED, RunState.COMPLETED_WITH_WARNINGS,
                     RunState.REQUIRES_DECISION, RunState.PARTIAL}:
            return RunState.CANCELLED, ResultCode.CANCELLED
        return state, code

    def _publish_locked(self, state: RunState | None = None, code: ResultCode | None = None,
                 *, step_id: str | None = None, step_kind: StepKind | None = None,
                 completed: int = 0, total: int = 0, decision: str = "",
                 phase: PreparationPhase | None = None) -> RunRecord:
        assert self.record is not None
        state, code = self._cancelled_state(state, code)
        terminal = state in {RunState.COMPLETED, RunState.COMPLETED_WITH_WARNINGS,
            RunState.PARTIAL, RunState.FAILED, RunState.CANCELLED}
        if terminal:
            if not self._finished and self.plan is not None:
                self._finished = True
                finish = getattr(self.ports, "finish", None)
                if finish is not None:
                    try:
                        finish(self.plan)
                    except Exception:
                        state, code = RunState.FAILED, ResultCode.INVALID_PLAN
            self._release()
        self.record = replace(self.record, state=state or self.record.state,
            code=code or self.record.code, elapsed_ms=max(0, round((time.monotonic()-self._started)*1000)),
            ownership=self._owns(), decision=decision)
        self._sequence += 1
        if self.on_event is not None:
            try:
                self.on_event(RunEvent(self.record, step_id, step_kind,
                    max(0, completed), max(0, total), self._sequence, phase))
            except Exception:
                # Presentation/telemetry cannot alter a completed effect.
                pass
        return self.record

    def _context(self, kind: StepKind | None = None) -> StepContext:
        assert self.plan is not None
        step_id = str(uuid4())
        phase = None
        last_update = float("-inf")

        def progress(done: int, total: int) -> None:
            nonlocal last_update
            now = time.monotonic()
            if now - last_update >= 0.05 or (total > 0 and done >= total):
                last_update = now
                self._publish(step_id=step_id, step_kind=kind, phase=phase,
                              completed=done, total=total)

        def set_phase(value: PreparationPhase) -> None:
            nonlocal phase, last_update
            phase, last_update = value, float("-inf")
            self._publish(step_id=step_id, step_kind=kind, phase=phase)

        return StepContext(self.plan.flow_id, self.plan.run_id, step_id,
                           self._cancelled.is_set, progress, set_phase)

    @staticmethod
    def _scope(context: StepContext):
        from metroliza.shared.workflow_diagnostics import recipe_workflow_scope
        return recipe_workflow_scope(UUID(context.flow_id), UUID(context.run_id), UUID(context.step_id))

    def admit_start(self, plan: ResolvedRunPlan) -> str:
        """Admit on the UI thread before scheduling; cancellation then stays latched."""
        with self._state_lock:
            if self._admission is not None or self._owns():
                raise RecipeError("busy")
            token = str(uuid4())
            self._cancelled.clear()
            self._admission = (token, plan.run_id)
            return token

    def withdraw_start(self, token: str) -> None:
        with self._state_lock:
            if self._admission is not None and self._admission[0] == token:
                self._admission = None
                self._cancelled.set()

    def _initialize(self, plan: ResolvedRunPlan, admission: str | None) -> RunRecord | None:
        with self._state_lock:
            if admission is None:
                try:
                    admission = self.admit_start(plan)
                except RecipeError:
                    return RunRecord(plan.flow_id, plan.run_id, RunState.FAILED, ResultCode.BUSY)
            if self._admission != (admission, plan.run_id):
                return RunRecord(plan.flow_id, plan.run_id, RunState.FAILED, ResultCode.INVALID_PLAN)
            self._admission = None
            if not self._claim():
                return RunRecord(plan.flow_id, plan.run_id, RunState.FAILED, ResultCode.BUSY)
            self._started = time.monotonic()
            self.plan, self.review = plan, None
            self._next_step, self._sequence = 0, 0
            self._finished = False
            self.record = RunRecord(plan.flow_id, plan.run_id, ownership=True)
            return None

    def _validate_snapshot(self, plan: ResolvedRunPlan) -> None:
        validate_binding(plan.definition, plan.binding, complete=True)
        resolved = resolve_plan(plan.definition, plan.binding)
        if any(getattr(plan, key) != getattr(resolved, key) for key in
               ("input_folder", "output_file", "database_file", "assets_dir")):
            raise RecipeError("snapshot_mismatch")
        validate_plan_paths(plan, self.active_database)
        for identity in (plan.flow_id, plan.run_id):
            if UUID(identity).version != 4:
                raise RecipeError("invalid_runtime_id")

    def _release_execution(self) -> RunRecord | None:
        with self._state_lock:
            cancelled = None
            if self._cancelled.is_set() and self._owns():
                cancelled = self._publish(RunState.CANCELLED, ResultCode.CANCELLED)
            self._execution.release()
            return cancelled

    def _start_admitted(self, plan: ResolvedRunPlan, admission: str | None) -> RunRecord:
        rejected = self._initialize(plan, admission)
        if rejected is not None:
            return rejected
        try:
            if self._cancelled.is_set():
                return self._publish(RunState.CANCELLED, ResultCode.CANCELLED)
            self._validate_snapshot(plan)
            self._publish(RunState.RUNNING)
            if self._database_collision():
                return self._publish(RunState.REQUIRES_DECISION, ResultCode.REVIEW_REQUIRED,
                                     decision="collision")
            return self._preflight_and_execute()
        except Exception:
            return self._publish(RunState.CANCELLED if self._cancelled.is_set() else RunState.FAILED,
                                 ResultCode.CANCELLED if self._cancelled.is_set() else ResultCode.INVALID_PLAN)

    def start(self, plan: ResolvedRunPlan, *, admission: str | None = None) -> RunRecord:
        if not self._execution.acquire(blocking=False):
            return RunRecord(plan.flow_id, plan.run_id, RunState.FAILED, ResultCode.BUSY)
        try:
            result = self._start_admitted(plan, admission)
        finally:
            cancelled = self._release_execution()
        return cancelled or result

    def _database_collision(self) -> bool:
        assert self.plan is not None
        # Existing input DB is read explicitly by a plan with no prepare/import.
        database = self.plan.database_file
        return self.plan.creates_database and database is not None and any(
            p.exists() or p.is_symlink() for p in
            (database, Path(str(database) + "-wal"), Path(str(database) + "-shm")))

    def _preflight_and_execute(self) -> RunRecord:
        assert self.plan is not None
        if self._cancelled.is_set():
            return self._publish(RunState.CANCELLED, ResultCode.CANCELLED)
        context = self._context()
        with self._scope(context):
            self.review = self.ports.preflight(self.plan, context)
        if (not isinstance(self.review, PreflightResult) or type(self.review.ready) is not bool or
                type(self.review.requires_decision) is not bool or
                type(self.review.recheck_on_continue) is not bool or
                not isinstance(self.review.code, ResultCode)):
            return self._publish(RunState.FAILED, ResultCode.INVALID_PLAN)
        if self._cancelled.is_set() or self.review.code is ResultCode.CANCELLED:
            return self._publish(RunState.CANCELLED, ResultCode.CANCELLED)
        if self.review.requires_decision:
            return self._publish(RunState.REQUIRES_DECISION, self.review.code, decision="review")
        if not self.review.ready:
            return self._publish(RunState.FAILED, self.review.code)
        return self._execute()

    def _prepare_new_copy(self) -> RunRecord:
        assert self.plan is not None
        candidate = new_output_copy(self.plan)
        # Finish the old run while its identity is still current. Never carry
        # approval or private review state across the new random run identity.
        finish = getattr(self.ports, "finish", None)
        with self._state_lock:
            self._finished = True
        if finish is not None:
            finish(self.plan)
        with self._state_lock:
            if self._cancelled.is_set():
                return self._publish(RunState.CANCELLED, ResultCode.CANCELLED)
            self.plan, self.review = candidate, None
            self.record = replace(self.record, run_id=candidate.run_id)
            self._finished = False
            return self._publish(RunState.REQUIRES_DECISION, ResultCode.REVIEW_REQUIRED,
                                 decision="copy_ready")

    def _continue_decision(self, pending: str, decision: str) -> RunRecord:
        assert self.plan is not None
        if decision not in {"continue", "continue_partial"}:
            raise RecipeError("invalid_decision")
        if pending == "copy_ready":
            self._publish(RunState.RUNNING, ResultCode.SUCCESS)
            return self._preflight_and_execute()
        if pending == "partial":
            self._publish(RunState.RUNNING, ResultCode.SUCCESS)
            return self._execute()
        if not self.ports.approve(self.plan, decision):
            return self._publish(RunState.REQUIRES_DECISION, ResultCode.REVIEW_REQUIRED,
                                 decision=pending)
        self._publish(RunState.RUNNING, ResultCode.SUCCESS)
        if self.review is not None and not self.review.recheck_on_continue:
            return self._execute()
        return self._preflight_and_execute()

    def _resume_decision(self, decision: str) -> RunRecord:
        assert self.record is not None and self.plan is not None
        pending = self.record.decision
        if decision == "new_copy" and self._next_step == 0:
            return self._prepare_new_copy()
        if pending == "collision":
            return self._publish(RunState.REQUIRES_DECISION, ResultCode.REVIEW_REQUIRED,
                                 decision="collision")
        if pending == "partial" and decision != "continue_partial":
            return self._publish(RunState.REQUIRES_DECISION, ResultCode.PARTIAL_IMPORT,
                                 decision="partial")
        return self._continue_decision(pending, decision)

    def _resume_admitted(self, decision: str) -> RunRecord:
        assert self.record is not None
        try:
            if self.record.state is not RunState.REQUIRES_DECISION or not self._owns():
                raise RecipeError("no_pending_decision")
            if self._cancelled.is_set():
                return self._publish(RunState.CANCELLED, ResultCode.CANCELLED)
            return self._resume_decision(decision)
        except RecipeError:
            raise
        except Exception:
            return self._publish(RunState.CANCELLED if self._cancelled.is_set() else RunState.FAILED,
                                 ResultCode.CANCELLED if self._cancelled.is_set() else ResultCode.INVALID_PLAN)

    def resume(self, decision: str) -> RunRecord:
        if self.record is None or self.plan is None:
            raise RecipeError("no_active_run")
        if not self._execution.acquire(blocking=False):
            return replace(self.record, code=ResultCode.BUSY)
        try:
            result = self._resume_admitted(decision)
        finally:
            cancelled = self._release_execution()
        return cancelled or result

    @staticmethod
    def _valid_result_values(result: StepResult) -> bool:
        return (type(result.warnings) is tuple and len(result.warnings) <= 32 and
                all(isinstance(w, ResultCode) for w in result.warnings) and
                all(type(n) is int and n >= 0
                    for n in (result.imported_count, result.rejected_count, result.duplicate_count)))

    @classmethod
    def _valid_result(cls, result: StepResult) -> bool:
        return (isinstance(result, StepResult) and isinstance(result.status, StepStatus) and
                isinstance(result.code, ResultCode) and type(result.artifact_verified) is bool and
                cls._valid_result_values(result))

    def _apply_result(self, kind: StepKind, result: StepResult) -> RunRecord | None:
        assert self.record is not None
        if self._cancelled.is_set() or result.status is StepStatus.CANCELLED:
            return self._publish(RunState.CANCELLED, ResultCode.CANCELLED)
        if result.status is StepStatus.FAILED:
            return self._publish(RunState.FAILED, result.code)
        if result.status is StepStatus.PARTIAL:
            if kind is StepKind.IMPORT_REPORTS:
                with self._state_lock:
                    self.record = replace(self.record, partial_import=True)
                return self._publish(RunState.REQUIRES_DECISION, ResultCode.PARTIAL_IMPORT,
                                     decision="partial")
            return self._publish(RunState.PARTIAL, result.code)
        if kind is StepKind.VERIFY_OUTPUT and not result.artifact_verified:
            return self._publish(RunState.FAILED, ResultCode.OUTPUT_MISSING)
        return None

    def _execute_step(self) -> RunRecord | None:
        assert self.plan is not None and self.record is not None
        step = self.plan.definition.steps[self._next_step]
        context = self._context(step.kind)
        self._publish(RunState.RUNNING, step_id=context.step_id, step_kind=step.kind)
        started = time.monotonic()
        with self._scope(context):
            result = self.ports.execute(step, self.plan, context)
        if not self._valid_result(result):
            return self._publish(RunState.FAILED, ResultCode.INVALID_PLAN)
        duration = min(86_400_000, max(0, round((time.monotonic()-started)*1000)))
        with self._state_lock:
            self.record = replace(self.record,
                steps=(*self.record.steps, StepRecord(context.step_id, step.kind, result, duration)))
            self._next_step += 1
        return self._apply_result(step.kind, result)

    def _complete_run(self) -> RunRecord:
        assert self.plan is not None and self.record is not None
        if not self.record.steps:
            return self._publish(RunState.FAILED, ResultCode.INVALID_PLAN)
        # Export paths may only succeed with an explicit verification receipt.
        exports = {StepKind.EXPORT_MAIN, StepKind.EXPORT_HTML, StepKind.ANALYZE_TABULAR}
        if any(s.kind in exports for s in self.plan.definition.steps):
            if not any(s.result.artifact_verified for s in self.record.steps):
                return self._publish(RunState.FAILED, ResultCode.OUTPUT_MISSING)
        warnings = self.record.partial_import or any(s.result.warnings for s in self.record.steps)
        return self._publish(RunState.COMPLETED_WITH_WARNINGS if warnings else RunState.COMPLETED,
                             ResultCode.PARTIAL_IMPORT if self.record.partial_import else ResultCode.SUCCESS)

    def _execute(self) -> RunRecord:
        assert self.plan is not None and self.record is not None
        while self._next_step < len(self.plan.definition.steps):
            if self._cancelled.is_set():
                return self._publish(RunState.CANCELLED, ResultCode.CANCELLED)
            if self._next_step == 0 and self._database_collision():
                return self._publish(RunState.REQUIRES_DECISION, ResultCode.REVIEW_REQUIRED,
                                     decision="collision")
            outcome = self._execute_step()
            if outcome is not None:
                return outcome
        return self._complete_run()

    def cancel(self) -> None:
        with self._state_lock:
            self._cancelled.set()
            if not self._owns():
                return
            self._publish(RunState.CANCELLING, ResultCode.CANCELLED)
        try:
            self.ports.cancel()
        finally:
            # Paused runs have no worker to finish cancellation and release ownership.
            if self._execution.acquire(blocking=False):
                try:
                    self._publish(RunState.CANCELLED, ResultCode.CANCELLED)
                finally:
                    self._execution.release()

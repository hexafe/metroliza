"""Truthful runtime state; completed effects survive a later cancellation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .contracts import StepKind
from .ports import PreparationPhase, ResultCode, StepResult


class RunState(str, Enum):
    READY = "ready"
    RUNNING = "running"
    REQUIRES_DECISION = "requires_decision"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class StepRecord:
    step_id: str
    kind: StepKind
    result: StepResult
    duration_ms: int


@dataclass(frozen=True)
class RunRecord:
    flow_id: str
    run_id: str
    state: RunState = RunState.READY
    code: ResultCode = ResultCode.SUCCESS
    steps: tuple[StepRecord, ...] = ()
    decision: str = ""
    elapsed_ms: int = 0
    ownership: bool = False
    # A pause after partial import retains provenance even if export succeeds.
    partial_import: bool = False


@dataclass(frozen=True)
class RunEvent:
    record: RunRecord
    step_id: str | None = None
    step_kind: StepKind | None = None
    completed: int = 0
    total: int = 0
    sequence: int = field(default=0)
    phase: PreparationPhase | None = None

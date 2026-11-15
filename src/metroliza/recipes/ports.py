"""Qt-free execution boundary; private review data stays in memory."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

from metroliza.recipes.contracts import ResolvedRunPlan, StepSpec


class StepStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResultCode(str, Enum):
    SUCCESS = "success"
    REVIEW_REQUIRED = "review_required"
    SOURCE_CHANGED = "source_changed"
    IMPORT_FAILED = "import_failed"
    CANCELLED = "cancelled"
    EXPORT_FAILED = "export_failed"
    OUTPUT_MISSING = "output_missing"
    UNSUPPORTED = "unsupported"
    INVALID_PLAN = "invalid_plan"
    PARTIAL_IMPORT = "partial_import"
    DUPLICATES = "duplicates"
    BUSY = "busy"


@dataclass(frozen=True)
class StepContext:
    flow_id: str
    run_id: str
    step_id: str
    cancelled: Callable[[], bool]
    progress: Callable[[int, int], None]


@dataclass(frozen=True)
class StepResult:
    status: StepStatus
    code: ResultCode = ResultCode.SUCCESS
    imported_count: int = 0
    rejected_count: int = 0
    warnings: tuple[ResultCode, ...] = ()
    artifact_verified: bool = False


@dataclass(frozen=True)
class PreflightResult:
    ready: bool
    code: ResultCode = ResultCode.SUCCESS
    requires_decision: bool = False
    decision_id: str = ""
    summary: tuple[str, ...] = field(default=(), repr=False)
    review: object | None = field(default=None, repr=False, compare=False)


class ReportsPorts(Protocol):
    def preflight(self, plan: ResolvedRunPlan, context: StepContext) -> PreflightResult: ...

    def approve(self, plan: ResolvedRunPlan, decision: str) -> bool: ...

    def execute(self, step: StepSpec, plan: ResolvedRunPlan, context: StepContext) -> StepResult: ...

    def cancel(self) -> None: ...

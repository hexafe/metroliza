"""Typed execution outcomes shared by export orchestrators and backends."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, TypeAlias


class ExportOutcomeKind(str, Enum):
    """Terminal state for one export execution boundary."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    CANCELED = "canceled"


@dataclass(frozen=True)
class ExportStageOutcome:
    """Structured result returned by an export pipeline or backend."""

    kind: ExportOutcomeKind
    warnings: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        """Return whether the primary export artifact completed."""

        return self.kind in {
            ExportOutcomeKind.COMPLETED,
            ExportOutcomeKind.COMPLETED_WITH_WARNINGS,
        }

    def __bool__(self) -> bool:
        """Preserve the legacy boolean contract during incremental migration."""

        return self.succeeded

    @classmethod
    def completed(cls) -> ExportStageOutcome:
        """Build a successful outcome without warnings."""

        return cls(ExportOutcomeKind.COMPLETED)

    @classmethod
    def completed_with_warnings(cls, *warnings: str) -> ExportStageOutcome:
        """Build a successful outcome carrying optional-artifact warnings."""

        normalized = tuple(str(warning).strip() for warning in warnings if str(warning).strip())
        return cls(ExportOutcomeKind.COMPLETED_WITH_WARNINGS, normalized)

    @classmethod
    def canceled(cls) -> ExportStageOutcome:
        """Build a cancellation outcome."""

        return cls(ExportOutcomeKind.CANCELED)


ExportOutcomeLike: TypeAlias = ExportStageOutcome | bool


def normalize_export_outcome(value: ExportOutcomeLike) -> ExportStageOutcome:
    """Normalize legacy boolean results at compatibility boundaries."""

    if isinstance(value, ExportStageOutcome):
        return value
    return ExportStageOutcome.completed() if value else ExportStageOutcome.canceled()


class ExportExecutionContext(Protocol):
    """Public orchestration surface used by concrete export backends."""

    excel_file: str
    html_dashboard_file: str | None

    def run_export_pipeline(self, writer: Any) -> ExportOutcomeLike:
        """Populate a workbook writer and return its terminal outcome."""

    def run_html_dashboard_pipeline(self, writer: Any) -> ExportOutcomeLike:
        """Populate a dashboard writer and return its terminal outcome."""

    def begin_workbook_close(self) -> None:
        """Notify the orchestrator that workbook finalization started."""

    def complete_workbook_close(self, elapsed: float) -> None:
        """Notify the orchestrator that workbook finalization completed."""

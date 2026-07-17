"""Typed UI outcomes and safe Qt presentation helpers.

The contracts in this module deliberately separate user-facing copy from the
exception retained for diagnostics.  Presenters must never interpolate the
exception into their primary message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Generic, Iterable, TypeVar
from uuid import uuid4

from PyQt6.QtWidgets import QMessageBox, QWidget


logger = logging.getLogger(__name__)
T = TypeVar("T")


class UiIssueSeverity(str, Enum):
    """User-visible severity independent of a specific Qt message-box icon."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class UiOutcomeStatus(str, Enum):
    """Terminal status shared by synchronous and asynchronous UI workflows."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class UiArtifact:
    """A durable output that can be offered to the user after an operation."""

    kind: str
    label: str
    path: Path | None = None
    uri: str | None = None

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("UI artifact kind must not be empty.")
        if not self.label.strip():
            raise ValueError("UI artifact label must not be empty.")
        if self.path is None and not str(self.uri or "").strip():
            raise ValueError("UI artifact must define either path or uri.")


@dataclass(frozen=True, slots=True)
class UiIssue:
    """A safe user-facing issue with an optional diagnostic-only exception."""

    code: str
    title: str
    message: str
    severity: UiIssueSeverity = UiIssueSeverity.ERROR
    recovery_action: str = ""
    diagnostic_id: str = ""
    cause: BaseException | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("UI issue code must not be empty.")
        if not self.title.strip():
            raise ValueError("UI issue title must not be empty.")
        if not self.message.strip():
            raise ValueError("UI issue message must not be empty.")

    @classmethod
    def unexpected(
        cls,
        cause: BaseException,
        *,
        operation: str,
        message: str = "The operation could not be completed. Check the application log for details.",
        recovery_action: str = "Retry the operation. If it fails again, provide the diagnostic ID.",
    ) -> UiIssue:
        """Build an issue without copying exception text into user-facing fields."""

        normalized_operation = str(operation or "operation").strip() or "operation"
        return cls(
            code="unexpected_error",
            title=f"Could not complete {normalized_operation}",
            message=message,
            severity=UiIssueSeverity.ERROR,
            recovery_action=recovery_action,
            diagnostic_id=uuid4().hex[:12],
            cause=cause,
        )


@dataclass(frozen=True, slots=True)
class UiOutcome(Generic[T]):
    """Immutable terminal result for a user-initiated operation."""

    status: UiOutcomeStatus
    value: T | None = None
    message: str = ""
    artifacts: tuple[UiArtifact, ...] = ()
    issues: tuple[UiIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.status is UiOutcomeStatus.FAILED and not self.issues:
            raise ValueError("A failed UI outcome must include at least one issue.")

    @classmethod
    def succeeded(
        cls,
        value: T | None = None,
        *,
        message: str = "",
        artifacts: Iterable[UiArtifact] = (),
        issues: Iterable[UiIssue] = (),
    ) -> UiOutcome[T]:
        return cls(
            status=UiOutcomeStatus.SUCCEEDED,
            value=value,
            message=str(message or ""),
            artifacts=tuple(artifacts),
            issues=tuple(issues),
        )

    @classmethod
    def failed(
        cls,
        issues: UiIssue | Iterable[UiIssue],
        *,
        message: str = "",
        artifacts: Iterable[UiArtifact] = (),
    ) -> UiOutcome[T]:
        normalized_issues = (issues,) if isinstance(issues, UiIssue) else tuple(issues)
        return cls(
            status=UiOutcomeStatus.FAILED,
            message=str(message or ""),
            artifacts=tuple(artifacts),
            issues=normalized_issues,
        )

    @classmethod
    def cancelled(
        cls,
        *,
        message: str = "Operation cancelled.",
        issue: UiIssue | None = None,
        artifacts: Iterable[UiArtifact] = (),
    ) -> UiOutcome[T]:
        return cls(
            status=UiOutcomeStatus.CANCELLED,
            message=str(message or "Operation cancelled."),
            artifacts=tuple(artifacts),
            issues=() if issue is None else (issue,),
        )


class SafeQtOutcomePresenter:
    """Present UI outcomes without exposing raw exceptions in primary copy."""

    _SEVERITY_ORDER = {
        UiIssueSeverity.INFO: 0,
        UiIssueSeverity.WARNING: 1,
        UiIssueSeverity.ERROR: 2,
        UiIssueSeverity.CRITICAL: 3,
    }

    def __init__(self, *, active_logger: logging.Logger | None = None) -> None:
        self._logger = active_logger or logger

    def present_issue(self, issue: UiIssue, *, parent: QWidget | None = None):
        """Log diagnostic context and show only the issue's safe public copy."""

        self._log_issue(issue)
        primary_copy = self._primary_copy(issue)
        presenter = self._message_box_presenter(issue.severity)
        return presenter(parent, issue.title, primary_copy)

    def present_outcome(
        self,
        outcome: UiOutcome[object],
        *,
        parent: QWidget | None = None,
        success_title: str = "Completed",
        cancelled_title: str = "Cancelled",
    ):
        """Present the most important issue, or a safe terminal summary."""

        if outcome.issues:
            issue = max(
                outcome.issues,
                key=lambda candidate: self._SEVERITY_ORDER[candidate.severity],
            )
            return self.present_issue(issue, parent=parent)
        if outcome.status is UiOutcomeStatus.SUCCEEDED:
            return QMessageBox.information(
                parent,
                success_title,
                outcome.message or "The operation completed successfully.",
            )
        if outcome.status is UiOutcomeStatus.CANCELLED:
            return QMessageBox.information(
                parent,
                cancelled_title,
                outcome.message or "The operation was cancelled.",
            )
        raise ValueError("Failed UI outcomes must include an issue.")

    def _log_issue(self, issue: UiIssue) -> None:
        if issue.cause is not None:
            self._logger.error(
                "UI issue code=%s diagnostic_id=%s cause_type=%s",
                issue.code,
                issue.diagnostic_id or "unassigned",
                type(issue.cause).__name__,
            )
            return
        log_method = self._logger.warning
        if issue.severity is UiIssueSeverity.INFO:
            log_method = self._logger.info
        elif issue.severity in {UiIssueSeverity.ERROR, UiIssueSeverity.CRITICAL}:
            log_method = self._logger.error
        log_method(
            "UI issue code=%s diagnostic_id=%s",
            issue.code,
            issue.diagnostic_id or "unassigned",
        )

    @staticmethod
    def _primary_copy(issue: UiIssue) -> str:
        parts = [issue.message.strip()]
        if issue.recovery_action.strip():
            parts.append(issue.recovery_action.strip())
        if issue.diagnostic_id.strip():
            parts.append(f"Diagnostic ID: {issue.diagnostic_id.strip()}")
        return "\n\n".join(parts)

    @staticmethod
    def _message_box_presenter(severity: UiIssueSeverity):
        if severity is UiIssueSeverity.INFO:
            return QMessageBox.information
        if severity is UiIssueSeverity.WARNING:
            return QMessageBox.warning
        return QMessageBox.critical


__all__ = [
    "SafeQtOutcomePresenter",
    "UiArtifact",
    "UiIssue",
    "UiIssueSeverity",
    "UiOutcome",
    "UiOutcomeStatus",
]

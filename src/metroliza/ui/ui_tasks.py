"""Exactly-once task lifecycle contracts for PyQt workflow controllers."""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from PyQt6.QtCore import QObject, pyqtSignal

from metroliza.ui.ui_outcomes import UiArtifact, UiIssue, UiOutcome, UiOutcomeStatus


class UiTaskState(str, Enum):
    """States in the one-shot task lifecycle."""

    IDLE = "idle"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UiTaskClosePolicy(str, Enum):
    """How a window should respond to a close request while its task is active."""

    BLOCK = "block"
    CANCEL_AND_DEFER = "cancel_and_defer"
    DETACH = "detach"


_ACTIVE_STATES = frozenset({UiTaskState.RUNNING, UiTaskState.CANCEL_REQUESTED})
_TERMINAL_STATES = frozenset(
    {UiTaskState.SUCCEEDED, UiTaskState.FAILED, UiTaskState.CANCELLED}
)


class UiTaskController(QObject):
    """Own a one-shot task state machine independent of a concrete QThread."""

    state_changed = pyqtSignal(object, object)
    cancel_requested = pyqtSignal()
    terminal = pyqtSignal(object)
    close_deferred = pyqtSignal()
    close_ready = pyqtSignal()

    def __init__(
        self,
        *,
        close_policy: UiTaskClosePolicy = UiTaskClosePolicy.CANCEL_AND_DEFER,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._close_policy = UiTaskClosePolicy(close_policy)
        self._state = UiTaskState.IDLE
        self._outcome: UiOutcome[object] | None = None
        self._close_is_deferred = False

    @property
    def state(self) -> UiTaskState:
        return self._state

    @property
    def close_policy(self) -> UiTaskClosePolicy:
        return self._close_policy

    @property
    def outcome(self) -> UiOutcome[object] | None:
        return self._outcome

    @property
    def is_active(self) -> bool:
        return self._state in _ACTIVE_STATES

    @property
    def is_terminal(self) -> bool:
        return self._state in _TERMINAL_STATES

    @property
    def cancellation_requested(self) -> bool:
        return self._state is UiTaskState.CANCEL_REQUESTED

    @property
    def close_is_deferred(self) -> bool:
        return self._close_is_deferred

    def start(self) -> None:
        """Start a new one-shot lifecycle.

        A terminal controller must be explicitly reset before it can be reused.
        """

        if self._state is not UiTaskState.IDLE:
            raise RuntimeError(f"Cannot start a UI task from state {self._state.value!r}.")
        self._outcome = None
        self._close_is_deferred = False
        self._set_state(UiTaskState.RUNNING)

    def request_cancel(self) -> bool:
        """Request cancellation once and return whether a new request was emitted."""

        if self._state is UiTaskState.CANCEL_REQUESTED:
            return False
        if self._state is not UiTaskState.RUNNING:
            return False
        self._set_state(UiTaskState.CANCEL_REQUESTED)
        self.cancel_requested.emit()
        return True

    def request_close(self) -> bool:
        """Return whether the owning window may close immediately."""

        if not self.is_active:
            return True
        if self._close_policy is UiTaskClosePolicy.DETACH:
            return True
        if self._close_policy is UiTaskClosePolicy.BLOCK:
            return False
        if not self._close_is_deferred:
            self._close_is_deferred = True
            self.close_deferred.emit()
        self.request_cancel()
        return False

    def succeed(
        self,
        value: object | None = None,
        *,
        message: str = "",
        artifacts: Iterable[UiArtifact] = (),
        issues: Iterable[UiIssue] = (),
    ) -> bool:
        return self.complete(
            UiOutcome.succeeded(
                value,
                message=message,
                artifacts=artifacts,
                issues=issues,
            )
        )

    def fail(
        self,
        issues: UiIssue | Iterable[UiIssue],
        *,
        message: str = "",
        artifacts: Iterable[UiArtifact] = (),
    ) -> bool:
        return self.complete(
            UiOutcome.failed(issues, message=message, artifacts=artifacts)
        )

    def cancel(
        self,
        *,
        message: str = "Operation cancelled.",
        issue: UiIssue | None = None,
        artifacts: Iterable[UiArtifact] = (),
    ) -> bool:
        """Confirm terminal cancellation after a worker has actually stopped."""

        return self.complete(
            UiOutcome.cancelled(message=message, issue=issue, artifacts=artifacts)
        )

    def complete(self, outcome: UiOutcome[object]) -> bool:
        """Record one terminal outcome, ignoring duplicate worker terminal signals."""

        if not self.is_active or self._outcome is not None:
            return False
        terminal_state = {
            UiOutcomeStatus.SUCCEEDED: UiTaskState.SUCCEEDED,
            UiOutcomeStatus.FAILED: UiTaskState.FAILED,
            UiOutcomeStatus.CANCELLED: UiTaskState.CANCELLED,
        }[outcome.status]
        self._outcome = outcome
        self._set_state(terminal_state)
        self.terminal.emit(outcome)
        if self._close_is_deferred:
            self.close_ready.emit()
        return True

    def reset(self) -> None:
        """Reset a completed controller for an intentional subsequent run."""

        if not self.is_terminal:
            raise RuntimeError("Only a terminal UI task can be reset.")
        self._outcome = None
        self._close_is_deferred = False
        self._set_state(UiTaskState.IDLE)

    def _set_state(self, state: UiTaskState) -> None:
        previous = self._state
        if previous is state:
            return
        self._state = state
        self.state_changed.emit(state, previous)


__all__ = ["UiTaskClosePolicy", "UiTaskController", "UiTaskState"]

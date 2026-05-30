"""Shared cancellation state for Qt worker threads."""

from __future__ import annotations

from typing import Any


class WorkerCancellationMixin:
    """Small mixin for workers that expose ``cancel`` and interruption checks."""

    _cancel_requested: bool

    def _init_cancellation_state(self) -> None:
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        token = getattr(self, "cancellation_token", None)
        if token is not None and hasattr(token, "cancel"):
            token.cancel()
        request_interruption = getattr(self, "requestInterruption", None)
        if callable(request_interruption):
            request_interruption()

    def _is_cancelled(self) -> bool:
        interruption_requested: Any = getattr(self, "isInterruptionRequested", None)
        return bool(self._cancel_requested) or (
            callable(interruption_requested) and bool(interruption_requested())
        )

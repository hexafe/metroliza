"""Bounded in-memory retention for already-safe diagnostic event bytes."""

from __future__ import annotations

import math
from dataclasses import dataclass

from metroliza.shared.diagnostic_events import (
    ExceptionDiagnosticEvent,
    InvalidDiagnosticEvent,
    LegacyLogSuppressedEvent,
    RuntimeProvenanceEvent,
    StartupDiagnosticEvent,
    StartupOutcome,
    WorkflowDiagnosticEvent,
    WorkflowOutcome,
)
from metroliza.shared.diagnostic_wire import WireValidationError, decode_event, encode_event


DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_EVENTS = 2000
DEFAULT_MAX_AGE_SECONDS = 300.0
DEFAULT_TERMINAL_RESERVE_BYTES = 64 * 1024
DEFAULT_TERMINAL_RESERVE_EVENTS = 32
DEFAULT_MAX_OPERATIONS = 128
# Covers the worst-case compact JSON for all saturated loss fields plus a small
# versioned envelope; it is charged inside the terminal/control reserve.
LOSS_ACCOUNTING_BYTES = 1024
_MAX_LOSS_COUNTER = 2**32 - 1


@dataclass(frozen=True, slots=True)
class RingLoss:
    """Saturated, content-free recorder loss accounting."""

    invalid_events: int = 0
    invalid_bytes: int = 0
    sequence_rejected_events: int = 0
    normal_count_dropped_events: int = 0
    normal_count_dropped_bytes: int = 0
    normal_byte_dropped_events: int = 0
    normal_byte_dropped_bytes: int = 0
    terminal_dropped_events: int = 0
    terminal_dropped_bytes: int = 0
    count_evicted_events: int = 0
    count_evicted_bytes: int = 0
    byte_evicted_events: int = 0
    byte_evicted_bytes: int = 0
    age_evicted_events: int = 0
    age_evicted_bytes: int = 0
    operation_evicted_events: int = 0
    operation_evicted_bytes: int = 0
    coalesced_events: int = 0
    coalesced_bytes: int = 0
    counters_saturated: bool = False


@dataclass(frozen=True, slots=True)
class RingSnapshot:
    """Immutable safe bytes and explicit loss state at one monotonic time."""

    events: tuple[bytes, ...]
    loss: RingLoss
    total_bytes: int


@dataclass(slots=True)
class _Entry:
    payload: bytes
    event: object
    received_at: float
    priority: bool


class DiagnosticRing:
    """Retain recent canonical events under byte, count, age, and operation caps."""

    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_events: int = DEFAULT_MAX_EVENTS,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        terminal_reserve_bytes: int = DEFAULT_TERMINAL_RESERVE_BYTES,
        terminal_reserve_events: int = DEFAULT_TERMINAL_RESERVE_EVENTS,
        max_operations: int = DEFAULT_MAX_OPERATIONS,
    ) -> None:
        integers = (
            max_bytes,
            max_events,
            terminal_reserve_bytes,
            terminal_reserve_events,
            max_operations,
        )
        if any(type(value) is not int or value <= 0 for value in integers):
            raise ValueError("invalid diagnostic ring limit")
        if type(max_age_seconds) not in (int, float) or not math.isfinite(max_age_seconds):
            raise ValueError("invalid diagnostic ring limit")
        if max_age_seconds <= 0 or terminal_reserve_bytes < LOSS_ACCOUNTING_BYTES:
            raise ValueError("invalid diagnostic ring limit")
        hard_maxima = (
            max_bytes <= DEFAULT_MAX_BYTES,
            max_events <= DEFAULT_MAX_EVENTS,
            max_age_seconds <= DEFAULT_MAX_AGE_SECONDS,
            terminal_reserve_bytes <= DEFAULT_TERMINAL_RESERVE_BYTES,
            terminal_reserve_events <= DEFAULT_TERMINAL_RESERVE_EVENTS,
            max_operations <= DEFAULT_MAX_OPERATIONS,
        )
        if not all(hard_maxima):
            raise ValueError("invalid diagnostic ring limit")
        if terminal_reserve_bytes >= max_bytes or terminal_reserve_events >= max_events:
            raise ValueError("invalid diagnostic ring reserve")
        self.max_bytes = max_bytes
        self.max_events = max_events
        self.max_age_seconds = float(max_age_seconds)
        self.terminal_reserve_bytes = terminal_reserve_bytes
        self.terminal_reserve_events = terminal_reserve_events
        self.max_operations = max_operations
        self._entries: list[_Entry] = []
        self._event_bytes = 0
        self._last_now: float | None = None
        self._loss_values = {
            name: 0 for name in RingLoss.__dataclass_fields__ if name != "counters_saturated"
        }
        self._counters_saturated = False

    def _increment(self, name: str, value: int = 1) -> None:
        current = self._loss_values[name]
        updated = min(_MAX_LOSS_COUNTER, current + max(0, value))
        if updated == _MAX_LOSS_COUNTER and current + max(0, value) > _MAX_LOSS_COUNTER:
            self._counters_saturated = True
        self._loss_values[name] = updated

    def _valid_now(self, now: object) -> float | None:
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            return None
        value = float(now)
        if self._last_now is not None and value < self._last_now:
            return None
        self._last_now = value
        return value

    @staticmethod
    def _priority(event: object) -> bool:
        if type(event) in (
            RuntimeProvenanceEvent,
            ExceptionDiagnosticEvent,
            InvalidDiagnosticEvent,
            LegacyLogSuppressedEvent,
        ):
            return True
        if type(event) is WorkflowDiagnosticEvent:
            return event.outcome in (
                WorkflowOutcome.COMPLETED,
                WorkflowOutcome.COMPLETED_WITH_FALLBACK,
                WorkflowOutcome.CANCELLED,
                WorkflowOutcome.FAILED,
            )
        if type(event) is StartupDiagnosticEvent:
            return event.outcome not in (
                StartupOutcome.INVOCATION_STARTED,
                StartupOutcome.MILESTONE,
            )
        return False

    @staticmethod
    def _sequence_key(event: object) -> tuple[str, object] | None:
        if type(event) is WorkflowDiagnosticEvent:
            return ("workflow", event.operation_id)
        if type(event) in (RuntimeProvenanceEvent, StartupDiagnosticEvent):
            return ("startup", event.startup_id)
        return None

    def _last_sequence(self, event: object) -> int | None:
        key = self._sequence_key(event)
        if key is None:
            return None
        sequences = [
            entry.event.sequence
            for entry in self._entries
            if self._sequence_key(entry.event) == key
        ]
        return max(sequences, default=None)

    @staticmethod
    def _coalesce_key(event: object) -> tuple[object, object] | None:
        if type(event) is WorkflowDiagnosticEvent and event.outcome is WorkflowOutcome.MILESTONE:
            return (event.operation_id, event.stage)
        return None

    def _coalesce_index(self, event: object) -> int | None:
        key = self._coalesce_key(event)
        if key is None:
            return None
        for index in range(len(self._entries) - 1, -1, -1):
            if self._coalesce_key(self._entries[index].event) == key:
                return index
        return None

    def _remove(self, index: int, reason: str) -> None:
        entry = self._entries.pop(index)
        size = len(entry.payload)
        self._event_bytes -= size
        self._increment(f"{reason}_events")
        self._increment(f"{reason}_bytes", size)

    def _expire(self, now: float) -> None:
        cutoff = now - self.max_age_seconds
        while self._entries and self._entries[0].received_at < cutoff:
            self._remove(0, "age_evicted")

    def _operation_ids(self) -> set[object]:
        return {
            entry.event.operation_id
            for entry in self._entries
            if type(entry.event) is WorkflowDiagnosticEvent
        }

    def _evict_oldest_operation(self) -> bool:
        operation_id = next(
            (
                entry.event.operation_id
                for entry in self._entries
                if type(entry.event) is WorkflowDiagnosticEvent
            ),
            None,
        )
        if operation_id is None:
            return False
        for index in range(len(self._entries) - 1, -1, -1):
            event = self._entries[index].event
            if type(event) is WorkflowDiagnosticEvent and event.operation_id == operation_id:
                self._remove(index, "operation_evicted")
        return True

    def _ordinary_totals(self, replacement: int | None) -> tuple[int, int]:
        entries = [
            entry
            for index, entry in enumerate(self._entries)
            if not entry.priority and index != replacement
        ]
        return len(entries), sum(len(entry.payload) for entry in entries)

    def _drop(self, reason: str, size: int) -> bool:
        self._increment(reason)
        if reason in (
            "normal_count_dropped_events",
            "normal_byte_dropped_events",
            "terminal_dropped_events",
        ):
            byte_reason = reason.replace("_events", "_bytes")
            if byte_reason in self._loss_values:
                self._increment(byte_reason, size)
        return False

    def add(self, payload: bytes, now: float) -> bool:
        """Revalidate and admit canonical bytes; return whether they were retained."""
        timestamp = self._valid_now(now)
        if timestamp is None:
            self._increment("invalid_events")
            self._increment("invalid_bytes", len(payload) if type(payload) is bytes else 0)
            return False
        self._expire(timestamp)
        try:
            event = decode_event(payload)
            canonical = encode_event(event)
        except WireValidationError:
            self._increment("invalid_events")
            self._increment("invalid_bytes", len(payload) if type(payload) is bytes else 0)
            return False

        last_sequence = self._last_sequence(event)
        if last_sequence is not None and event.sequence <= last_sequence:
            self._increment("sequence_rejected_events")
            return False

        priority = self._priority(event)
        if (
            type(event) is WorkflowDiagnosticEvent
            and event.operation_id not in self._operation_ids()
        ):
            if len(self._operation_ids()) >= self.max_operations:
                if not priority:
                    return self._drop("normal_count_dropped_events", len(canonical))
                if not self._evict_oldest_operation():
                    return self._drop("terminal_dropped_events", len(canonical))

        replacement = self._coalesce_index(event)
        replacement_size = 0 if replacement is None else len(self._entries[replacement].payload)
        projected_count = len(self._entries) + 1 - (replacement is not None)
        projected_bytes = (
            self._event_bytes + len(canonical) - replacement_size + LOSS_ACCOUNTING_BYTES
        )

        if not priority:
            ordinary_count, ordinary_bytes = self._ordinary_totals(replacement)
            if ordinary_count + 1 > self.max_events - self.terminal_reserve_events:
                return self._drop("normal_count_dropped_events", len(canonical))
            if ordinary_bytes + len(canonical) > self.max_bytes - self.terminal_reserve_bytes:
                return self._drop("normal_byte_dropped_events", len(canonical))
            if projected_count > self.max_events:
                return self._drop("normal_count_dropped_events", len(canonical))
            if projected_bytes > self.max_bytes:
                return self._drop("normal_byte_dropped_events", len(canonical))
        else:
            if len(canonical) + LOSS_ACCOUNTING_BYTES > self.max_bytes:
                return self._drop("terminal_dropped_events", len(canonical))
            while projected_count > self.max_events:
                index = next((i for i, entry in enumerate(self._entries) if not entry.priority), 0)
                self._remove(index, "count_evicted")
                if replacement is not None:
                    replacement = self._coalesce_index(event)
                    replacement_size = (
                        0 if replacement is None else len(self._entries[replacement].payload)
                    )
                projected_count = len(self._entries) + 1 - (replacement is not None)
            projected_bytes = (
                self._event_bytes + len(canonical) - replacement_size + LOSS_ACCOUNTING_BYTES
            )
            while projected_bytes > self.max_bytes:
                if not self._entries:
                    return self._drop("terminal_dropped_events", len(canonical))
                index = next((i for i, entry in enumerate(self._entries) if not entry.priority), 0)
                self._remove(index, "byte_evicted")
                if replacement is not None:
                    replacement = self._coalesce_index(event)
                    replacement_size = (
                        0 if replacement is None else len(self._entries[replacement].payload)
                    )
                projected_bytes = (
                    self._event_bytes + len(canonical) - replacement_size + LOSS_ACCOUNTING_BYTES
                )

        if replacement is not None:
            self._remove(replacement, "coalesced")
        self._entries.append(_Entry(canonical, event, timestamp, priority))
        self._event_bytes += len(canonical)
        return True

    def snapshot(self, now: float) -> RingSnapshot:
        """Return immutable retained bytes after applying the age limit."""
        timestamp = self._valid_now(now)
        if timestamp is None:
            raise ValueError("invalid diagnostic ring time")
        self._expire(timestamp)
        loss = RingLoss(**self._loss_values, counters_saturated=self._counters_saturated)
        return RingSnapshot(
            events=tuple(entry.payload for entry in self._entries),
            loss=loss,
            total_bytes=self._event_bytes + LOSS_ACCOUNTING_BYTES,
        )

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest

from metroliza.shared.diagnostic_events import (
    WorkflowDiagnosticEvent,
    WorkflowOperation,
    WorkflowOutcome,
    WorkflowStage,
)
from metroliza.shared.diagnostic_ring import (
    DEFAULT_MAX_AGE_SECONDS,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_EVENTS,
    LOSS_ACCOUNTING_BYTES,
    DiagnosticRing,
)
from metroliza.shared.diagnostic_wire import decode_event, encode_event


INVOCATION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _operation(value: int) -> uuid.UUID:
    return uuid.UUID(f"{value:08x}-0000-4000-8000-000000000000")


def _event(
    sequence: int,
    stage: WorkflowStage,
    outcome: WorkflowOutcome,
    *,
    operation_id: uuid.UUID | None = None,
) -> bytes:
    return encode_event(
        WorkflowDiagnosticEvent(
            invocation_id=INVOCATION_ID,
            operation_id=operation_id or _operation(1),
            sequence=sequence,
            operation=WorkflowOperation.LOCAL_EXPORT,
            stage=stage,
            outcome=outcome,
        )
    )


def test_ring_defaults_are_the_accepted_inclusive_limits() -> None:
    ring = DiagnosticRing()

    snapshot = ring.snapshot(0.0)

    assert ring.max_bytes == DEFAULT_MAX_BYTES == 2 * 1024 * 1024
    assert ring.max_events == DEFAULT_MAX_EVENTS == 2000
    assert ring.max_age_seconds == DEFAULT_MAX_AGE_SECONDS == 300.0
    assert snapshot.events == ()
    assert snapshot.total_bytes == LOSS_ACCOUNTING_BYTES
    assert snapshot.total_bytes <= ring.terminal_reserve_bytes < ring.max_bytes


def test_loss_accounting_covers_saturated_versioned_json_envelope() -> None:
    ring = DiagnosticRing()
    ring._loss_values = {name: 2**32 - 1 for name in ring._loss_values}
    ring._counters_saturated = True
    loss = ring.snapshot(0.0).loss
    encoded = json.dumps(
        {"version": 1, "loss": dataclasses.asdict(loss)},
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")

    assert len(encoded) <= LOSS_ACCOUNTING_BYTES


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_bytes": DEFAULT_MAX_BYTES + 1},
        {"max_events": DEFAULT_MAX_EVENTS + 1},
        {"max_age_seconds": DEFAULT_MAX_AGE_SECONDS + 0.1},
        {"max_operations": 129},
    ],
)
def test_ring_rejects_limits_above_accepted_hard_maxima(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="^invalid diagnostic ring limit$"):
        DiagnosticRing(**overrides)


def test_ring_revalidates_bytes_and_reports_rejection_without_payload_text() -> None:
    ring = DiagnosticRing()
    marker = b"C:/private/customer-report.xlsx"

    assert ring.add(marker, 1.0) is False
    snapshot = ring.snapshot(1.0)

    assert snapshot.events == ()
    assert snapshot.loss.invalid_events == 1
    assert snapshot.loss.invalid_bytes == len(marker)
    assert marker not in repr(snapshot.loss).encode("ascii")


def test_ring_coalesces_repeated_progress_but_retains_start_and_latest_stage() -> None:
    ring = DiagnosticRing()
    start = _event(1, WorkflowStage.STARTED, WorkflowOutcome.STARTED)
    first = _event(2, WorkflowStage.PROCESSING, WorkflowOutcome.MILESTONE)
    latest = _event(3, WorkflowStage.PROCESSING, WorkflowOutcome.MILESTONE)

    assert ring.add(start, 0.0)
    assert ring.add(first, 1.0)
    assert ring.add(latest, 2.0)
    snapshot = ring.snapshot(2.0)

    assert snapshot.events == (start, latest)
    assert snapshot.loss.coalesced_events == 1
    assert snapshot.loss.coalesced_bytes == len(first)


def test_ring_rejects_duplicate_and_regressing_operation_sequences() -> None:
    ring = DiagnosticRing()
    current = _event(3, WorkflowStage.PROCESSING, WorkflowOutcome.MILESTONE)

    assert ring.add(current, 1.0)
    assert not ring.add(current, 2.0)
    assert not ring.add(_event(2, WorkflowStage.OUTPUT_STAGING, WorkflowOutcome.MILESTONE), 3.0)

    snapshot = ring.snapshot(3.0)
    assert snapshot.events == (current,)
    assert snapshot.loss.sequence_rejected_events == 2


def test_normal_flood_cannot_consume_terminal_count_reserve() -> None:
    ring = DiagnosticRing(
        max_bytes=8192,
        max_events=4,
        terminal_reserve_bytes=1024,
        terminal_reserve_events=1,
    )
    normal = (
        _event(1, WorkflowStage.STARTED, WorkflowOutcome.STARTED),
        _event(2, WorkflowStage.PROCESSING, WorkflowOutcome.MILESTONE),
        _event(3, WorkflowStage.OUTPUT_STAGING, WorkflowOutcome.MILESTONE),
    )
    terminal = _event(5, WorkflowStage.FINISHED, WorkflowOutcome.COMPLETED)

    assert all(ring.add(payload, float(index)) for index, payload in enumerate(normal))
    assert not ring.add(_event(4, WorkflowStage.OUTPUT_PUBLISHED, WorkflowOutcome.MILESTONE), 4.0)
    assert ring.add(terminal, 5.0)
    snapshot = ring.snapshot(5.0)

    assert snapshot.events[-1] == terminal
    assert len(snapshot.events) == 4
    assert snapshot.loss.normal_count_dropped_events == 1
    assert snapshot.total_bytes <= ring.max_bytes


def test_normal_flood_cannot_consume_terminal_byte_reserve() -> None:
    first = _event(1, WorkflowStage.STARTED, WorkflowOutcome.STARTED)
    second = _event(2, WorkflowStage.PROCESSING, WorkflowOutcome.MILESTONE)
    terminal = _event(3, WorkflowStage.FINISHED, WorkflowOutcome.COMPLETED)
    ordinary_budget = len(first) + len(second)
    ring = DiagnosticRing(
        max_bytes=ordinary_budget + 1024,
        max_events=20,
        terminal_reserve_bytes=1024,
        terminal_reserve_events=2,
    )

    assert ring.add(first, 0.0)
    assert ring.add(second, 1.0)
    assert not ring.add(_event(3, WorkflowStage.OUTPUT_STAGING, WorkflowOutcome.MILESTONE), 2.0)
    assert ring.add(terminal, 3.0)

    snapshot = ring.snapshot(3.0)
    assert snapshot.events[-1] == terminal
    assert snapshot.loss.normal_byte_dropped_events == 1
    assert snapshot.total_bytes <= ring.max_bytes


def test_ring_applies_age_limit_and_counts_exact_expired_bytes() -> None:
    ring = DiagnosticRing(max_age_seconds=5.0)
    old = _event(1, WorkflowStage.STARTED, WorkflowOutcome.STARTED)
    boundary = _event(2, WorkflowStage.PROCESSING, WorkflowOutcome.MILESTONE)

    assert ring.add(old, 0.0)
    assert ring.add(boundary, 1.0)
    snapshot = ring.snapshot(6.0)

    assert snapshot.events == (boundary,)
    assert snapshot.loss.age_evicted_events == 1
    assert snapshot.loss.age_evicted_bytes == len(old)


def test_terminal_for_new_operation_evicts_old_operation_at_operation_cap() -> None:
    ring = DiagnosticRing(max_operations=1)
    old = _event(1, WorkflowStage.STARTED, WorkflowOutcome.STARTED, operation_id=_operation(1))
    blocked = _event(1, WorkflowStage.STARTED, WorkflowOutcome.STARTED, operation_id=_operation(2))
    terminal = _event(
        2, WorkflowStage.FINISHED, WorkflowOutcome.COMPLETED, operation_id=_operation(2)
    )

    assert ring.add(old, 0.0)
    assert not ring.add(blocked, 1.0)
    assert ring.add(terminal, 2.0)
    snapshot = ring.snapshot(2.0)

    assert snapshot.events == (terminal,)
    assert snapshot.loss.normal_count_dropped_events == 1
    assert snapshot.loss.operation_evicted_events == 1
    assert snapshot.loss.operation_evicted_bytes == len(old)


def test_snapshot_payloads_remain_canonical_validated_events() -> None:
    ring = DiagnosticRing()
    payload = _event(1, WorkflowStage.STARTED, WorkflowOutcome.STARTED)
    assert ring.add(payload, 0.0)

    snapshot = ring.snapshot(0.0)

    assert encode_event(decode_event(snapshot.events[0])) == snapshot.events[0]
    assert snapshot.total_bytes == len(payload) + LOSS_ACCOUNTING_BYTES


def test_ring_rejects_nonfinite_or_backward_time_conservatively() -> None:
    ring = DiagnosticRing()
    payload = _event(1, WorkflowStage.STARTED, WorkflowOutcome.STARTED)

    assert not ring.add(payload, float("nan"))
    assert ring.add(payload, 2.0)
    assert not ring.add(_event(2, WorkflowStage.PROCESSING, WorkflowOutcome.MILESTONE), 1.0)
    with pytest.raises(ValueError, match="^invalid diagnostic ring time$"):
        ring.snapshot(float("inf"))

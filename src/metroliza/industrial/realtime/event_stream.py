"""Typed contracts for durable realtime industrial stream events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


SAMPLE_BATCH_COMMITTED_EVENT_TYPE = "sample_batch_committed"
ANOMALY_EVENTS_COMMITTED_EVENT_TYPE = "anomaly_events_committed"
DEFAULT_DETECTOR_CONSUMER_KEY = "realtime_detector_consumer"


@dataclass(frozen=True)
class RealtimeStreamEvent:
    """One durable event emitted by a realtime industrial stream producer."""

    source_profile_id: int
    stream_key: str
    event_type: str
    idempotency_key: str
    aggregate_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    event_id: int | None = None
    aggregate_id: int | None = None
    sample_id: int | None = None
    anomaly_event_id: int | None = None
    event_time: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class RealtimeStreamAppendResult:
    """Summary of one idempotent event append operation."""

    processed: int
    inserted: int
    skipped: int
    event_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class RealtimeConsumerOffset:
    """Checkpoint for one consumer reading one realtime industrial stream."""

    consumer_key: str
    source_profile_id: int
    stream_key: str
    id: int | None = None
    last_event_id: int = 0
    last_success_at: str | None = None
    last_error: str | None = None
    failure_count: int = 0
    status: str = "idle"
    updated_at: str | None = None


@dataclass(frozen=True)
class RealtimeDeadLetter:
    """A permanently invalid stream event quarantined by one consumer."""

    id: int
    consumer_key: str
    source_profile_id: int
    stream_key: str
    event_id: int
    event_type: str
    error_summary: str
    payload: Mapping[str, Any]
    failed_at: str
    status: str = "quarantined"


@dataclass(frozen=True)
class RealtimeDetectorConsumerResult:
    """Operator-safe summary for one detector-consumer processing run."""

    status: str
    stream_events_processed: int = 0
    samples_loaded: int = 0
    detector_events_processed: int = 0
    detector_events_created: int = 0
    detector_events_skipped: int = 0
    stream_events_appended: int = 0
    last_event_id: int | None = None
    error: str | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

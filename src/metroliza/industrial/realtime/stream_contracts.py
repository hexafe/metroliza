"""Typed contracts for realtime industrial streams and samples."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class SignalDefinition:
    """One realtime metric definition for one industrial source profile."""

    source_profile_id: int
    signal_key: str
    metric_name: str
    id: int | None = None
    unit: str | None = None
    nominal: float | None = None
    lsl: float | None = None
    usl: float | None = None
    lower_warning: float | None = None
    upper_warning: float | None = None
    segment_fields: tuple[str, ...] = ()
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class IndustrialSample:
    """One append-only process sample in a realtime industrial stream."""

    source_profile_id: int
    signal_id: int
    source_record_key: str
    event_time: str
    metric_name: str
    value: float
    id: int | None = None
    ingest_time: str | None = None
    reference: str | None = None
    part_number: str | None = None
    revision: str | None = None
    station: str | None = None
    line: str | None = None
    work_order: str | None = None
    batch_lot: str | None = None
    segment_key: Mapping[str, Any] = field(default_factory=dict)
    quality_flags: tuple[str, ...] = ()
    raw_record: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class StreamOffset:
    """Persisted ingestion cursor for one source stream."""

    source_profile_id: int
    stream_key: str
    cursor_column: str
    id: int | None = None
    cursor_value: str | None = None
    event_time_watermark: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    lag_seconds: float | None = None
    status: str = "idle"


@dataclass(frozen=True)
class SampleBatchResult:
    """Summary of one idempotent sample insertion batch."""

    processed: int
    inserted: int
    skipped: int
    sample_ids: tuple[int, ...] = ()

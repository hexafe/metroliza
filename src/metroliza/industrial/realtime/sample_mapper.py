"""Map realtime source rows into append-only industrial samples."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterable, Mapping, Sequence

from metroliza.industrial.realtime.sample_repository import redact_sample_payload, utc_timestamp
from metroliza.industrial.realtime.stream_config import RealtimeStreamConfig
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


_SAMPLE_CONTEXT_FIELDS = (
    "reference",
    "part_number",
    "revision",
    "station",
    "line",
    "work_order",
    "batch_lot",
)


@dataclass(frozen=True)
class SignalSampleMapping:
    """Pair a validated stream config with its persisted signal definition."""

    config: RealtimeStreamConfig
    signal: SignalDefinition


@dataclass(frozen=True)
class SampleMappingStats:
    """Counters for one source-row to sample mapping batch."""

    rows_processed: int = 0
    samples_mapped: int = 0
    samples_skipped: int = 0
    missing_required: int = 0
    non_numeric: int = 0
    invalid_timestamp: int = 0


@dataclass(frozen=True)
class SampleMappingResult:
    """Mapped samples plus explicit skip counters."""

    samples: tuple[IndustrialSample, ...]
    stats: SampleMappingStats


def map_row_to_sample(
    row: Mapping[str, Any],
    mapping: SignalSampleMapping,
    *,
    ingest_time: str | None = None,
) -> tuple[IndustrialSample | None, str | None]:
    """Map one source row to one sample, returning a skip reason instead of raising."""

    config = mapping.config.validated()
    signal = mapping.signal
    if signal.id is None:
        raise ValueError("SignalDefinition.id is required before mapping realtime samples.")
    record_key = _text(row.get(config.record_key_column))
    event_time = _text(row.get(config.event_time_column))
    metric_raw = row.get(config.metric_column)
    if not record_key or not event_time or metric_raw in (None, ""):
        return None, "missing_required"
    normalized_event_time = _normalize_event_time(event_time)
    if normalized_event_time is None:
        return None, "invalid_timestamp"
    try:
        value = float(metric_raw)
    except (TypeError, ValueError):
        return None, "non_numeric"
    if not math.isfinite(value):
        return None, "non_numeric"

    segment_key = {
        field: _text(row.get(field))
        for field in config.segment_fields
        if _text(row.get(field))
    }
    context = {
        field: _text(row.get(field))
        for field in _SAMPLE_CONTEXT_FIELDS
        if _text(row.get(field))
    }
    raw_columns = {
        config.record_key_column,
        config.event_time_column,
        config.metric_column,
        *config.segment_fields,
        *config.context_columns,
        *_SAMPLE_CONTEXT_FIELDS,
    }
    raw_record = {
        key: row[key]
        for key in sorted(raw_columns)
        if key in row
    }
    return (
        IndustrialSample(
            source_profile_id=config.source_profile_id,
            signal_id=int(signal.id),
            source_record_key=record_key,
            event_time=normalized_event_time,
            ingest_time=ingest_time or utc_timestamp(),
            metric_name=signal.metric_name or config.metric_name or config.metric_column,
            value=value,
            reference=context.get("reference"),
            part_number=context.get("part_number"),
            revision=context.get("revision"),
            station=context.get("station"),
            line=context.get("line"),
            work_order=context.get("work_order"),
            batch_lot=context.get("batch_lot"),
            segment_key=segment_key,
            quality_flags=(),
            raw_record=redact_sample_payload(raw_record),
        ),
        None,
    )


def map_rows_to_samples(
    rows: Iterable[Mapping[str, Any]],
    mappings: SignalSampleMapping | Sequence[SignalSampleMapping],
    *,
    ingest_time: str | None = None,
) -> SampleMappingResult:
    """Map source rows to samples for one or more signal definitions."""

    mapping_list = _normalize_mappings(mappings)
    samples: list[IndustrialSample] = []
    rows_processed = 0
    missing_required = 0
    non_numeric = 0
    invalid_timestamp = 0
    for row in rows:
        rows_processed += 1
        for mapping in mapping_list:
            sample, reason = map_row_to_sample(row, mapping, ingest_time=ingest_time)
            if sample is not None:
                samples.append(sample)
                continue
            if reason == "missing_required":
                missing_required += 1
            elif reason == "invalid_timestamp":
                invalid_timestamp += 1
            elif reason == "non_numeric":
                non_numeric += 1
    skipped = missing_required + non_numeric + invalid_timestamp
    return SampleMappingResult(
        samples=tuple(samples),
        stats=SampleMappingStats(
            rows_processed=rows_processed,
            samples_mapped=len(samples),
            samples_skipped=skipped,
            missing_required=missing_required,
            non_numeric=non_numeric,
            invalid_timestamp=invalid_timestamp,
        ),
    )


def _normalize_mappings(
    mappings: SignalSampleMapping | Sequence[SignalSampleMapping],
) -> tuple[SignalSampleMapping, ...]:
    if isinstance(mappings, SignalSampleMapping):
        return (mappings,)
    return tuple(mappings)


def _normalize_event_time(value: str) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        parse_text = f"{text[:-1]}+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(parse_text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()

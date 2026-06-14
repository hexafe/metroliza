"""Map source database rows into realtime industrial samples."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping

from metroliza.industrial.industrial_data_repository import looks_sensitive_key, redact_sensitive_text
from metroliza.industrial.realtime.sample_repository import utc_timestamp
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


@dataclass(frozen=True)
class SampleMappingStats:
    """Counters for row-to-sample mapping."""

    rows_seen: int = 0
    mapped: int = 0
    skipped_missing: int = 0
    skipped_non_numeric: int = 0
    skipped_non_finite: int = 0


@dataclass(frozen=True)
class SampleMappingResult:
    """Mapped samples and cursor metadata from one source batch."""

    samples: tuple[IndustrialSample, ...]
    stats: SampleMappingStats
    cursor_value: str | None = None
    event_time_watermark: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


def map_rows_to_samples(
    rows: Iterable[Mapping[str, Any]],
    *,
    config: RealtimePollConfig,
    signals: Mapping[str, SignalDefinition],
    ingest_time: str | None = None,
) -> SampleMappingResult:
    """Map source rows into zero or more samples per row."""

    validated = config.validated()
    ingest_timestamp = ingest_time or utc_timestamp()
    samples: list[IndustrialSample] = []
    rows_seen = 0
    skipped_missing = 0
    skipped_non_numeric = 0
    skipped_non_finite = 0
    cursor_value: str | None = None
    watermark: str | None = None
    warnings: list[str] = []

    for row in rows:
        rows_seen += 1
        record_key = _text_or_none(row.get(validated.record_key_column))
        event_time = _text_or_none(row.get(validated.event_time_column))
        row_cursor = _text_or_none(row.get(validated.cursor_column))
        if row_cursor is not None:
            cursor_value = row_cursor
        if event_time is not None and (watermark is None or event_time > watermark):
            watermark = event_time
        if not record_key or not event_time:
            skipped_missing += len(validated.signal_keys)
            continue

        for signal_key in validated.signal_keys:
            signal = signals.get(signal_key)
            if signal is None or signal.id is None:
                warnings.append(f"Signal '{signal_key}' is not persisted; skipped row {record_key}.")
                skipped_missing += 1
                continue
            metric_column = validated.signal_columns[signal_key]
            raw_value = row.get(metric_column)
            if raw_value in (None, ""):
                skipped_missing += 1
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                skipped_non_numeric += 1
                continue
            if not math.isfinite(value):
                skipped_non_finite += 1
                continue
            samples.append(
                IndustrialSample(
                    source_profile_id=validated.source_profile_id,
                    signal_id=int(signal.id),
                    source_record_key=record_key,
                    event_time=event_time,
                    ingest_time=ingest_timestamp,
                    metric_name=signal.metric_name,
                    value=value,
                    reference=_text_or_none(row.get("reference")),
                    part_number=_text_or_none(row.get("part_number")),
                    revision=_text_or_none(row.get("revision")),
                    station=_text_or_none(row.get("station")),
                    line=_text_or_none(row.get("line")),
                    work_order=_text_or_none(row.get("work_order")),
                    batch_lot=_text_or_none(row.get("batch_lot")),
                    segment_key={
                        field_name: str(row[field_name])
                        for field_name in validated.segment_fields
                        if row.get(field_name) not in (None, "")
                    },
                    raw_record=_redacted_raw_record(
                        row,
                        allowed_columns=_raw_record_columns(validated, metric_column),
                    ),
                )
            )

    return SampleMappingResult(
        samples=tuple(samples),
        stats=SampleMappingStats(
            rows_seen=rows_seen,
            mapped=len(samples),
            skipped_missing=skipped_missing,
            skipped_non_numeric=skipped_non_numeric,
            skipped_non_finite=skipped_non_finite,
        ),
        cursor_value=cursor_value,
        event_time_watermark=watermark,
        warnings=tuple(warnings),
    )


def _raw_record_columns(config: RealtimePollConfig, metric_column: str) -> tuple[str, ...]:
    return (
        config.record_key_column,
        config.event_time_column,
        config.cursor_column,
        metric_column,
        *config.context_fields,
    )


def _redacted_raw_record(
    row: Mapping[str, Any],
    *,
    allowed_columns: Iterable[str],
) -> dict[str, Any]:
    allowed = tuple(dict.fromkeys(str(column) for column in allowed_columns))
    return {
        column: _redacted_value(column, row[column])
        for column in allowed
        if column in row
    }


def _redacted_value(key: str, value: Any) -> Any:
    if looks_sensitive_key(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {
            str(nested_key): _redacted_value(str(nested_key), nested_value)
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_redacted_value(key, item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value, max_len=None)
    return value


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None

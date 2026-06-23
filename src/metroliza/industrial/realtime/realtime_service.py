"""One-cycle realtime industrial polling service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from metroliza.industrial.anomaly.baseline_repository import BaselineRepository
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import (
    IndustrialSourceProfile,
    looks_sensitive_key,
    redact_sensitive_text,
)
from metroliza.industrial.realtime.db_poller import (
    SourceDbAdapter,
    SourceReadRequest,
    build_bounded_poll_query,
    safe_query_diagnostics,
)
from metroliza.industrial.realtime.offset_store import StreamOffsetStore
from metroliza.industrial.realtime.replay import run_detectors_for_samples
from metroliza.industrial.realtime.sample_mapper import map_rows_to_samples
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository, utc_timestamp
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import (
    IndustrialSample,
    SignalDefinition,
    StreamOffset,
)

DetectorRunner = Callable[
    [Iterable[IndustrialSample], SignalDefinition, tuple[str, ...]],
    list[Any],
]

_BASELINE_DETECTORS = frozenset({"iqr", "mad_zscore"})
_HISTORY_DETECTORS = frozenset({"rolling_zscore"})
_DETECTOR_HISTORY_LIMIT = 500


@dataclass(frozen=True)
class PollingCycleResult:
    """Operator-safe summary of one realtime polling cycle."""

    source_profile_id: int
    stream_key: str
    status: str
    rows_fetched: int = 0
    samples_processed: int = 0
    samples_inserted: int = 0
    samples_skipped: int = 0
    detector_events_created: int = 0
    cursor_value: str | None = None
    event_time_watermark: str | None = None
    lag_seconds: float | None = None
    error: str | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


def run_polling_cycle(
    *,
    database: str,
    profile: IndustrialSourceProfile,
    config: RealtimePollConfig,
    adapter: SourceDbAdapter,
    detector_runner: DetectorRunner | None = None,
) -> PollingCycleResult:
    """Poll one bounded source batch, persist samples/events, and update offset after success."""

    validated = config.validated()
    sample_repository = RealtimeSampleRepository(database)
    offset_store = StreamOffsetStore(database)
    event_repository = AnomalyEventRepository(database)
    baseline_repository = BaselineRepository(database)
    existing_offset = offset_store.get_offset(
        source_profile_id=validated.source_profile_id,
        stream_key=validated.stream_key,
    )
    try:
        query = build_bounded_poll_query(profile=profile, config=validated, offset=existing_offset)
    except Exception as exc:
        error = redact_sensitive_text(exc)
        diagnostics = _failure_diagnostics("query_build", error=error, offset=existing_offset)
        _record_failed_offset(offset_store, validated, existing_offset, error)
        return _result(
            validated,
            "failed",
            cursor_value=_offset_value(existing_offset),
            event_time_watermark=_watermark(existing_offset),
            error=error,
            diagnostics=diagnostics,
        )

    diagnostics = safe_query_diagnostics(query)
    try:
        read_result = adapter.fetch_rows(
            request=SourceReadRequest(
                profile=profile,
                config=validated,
                query=query,
                offset=existing_offset,
            )
        )
    except Exception as exc:
        error = redact_sensitive_text(exc)
        diagnostics = _failure_diagnostics(
            "source_fetch",
            error=error,
            diagnostics=diagnostics,
            offset=existing_offset,
        )
        _record_failed_offset(offset_store, validated, existing_offset, error)
        return _result(
            validated,
            "failed",
            cursor_value=_offset_value(existing_offset),
            event_time_watermark=_watermark(existing_offset),
            error=error,
            diagnostics=diagnostics,
        )

    diagnostics.update(_safe_mapping(read_result.diagnostics))
    if read_result.error:
        error = redact_sensitive_text(read_result.error)
        rows_fetched = len(read_result.rows)
        diagnostics = _failure_diagnostics(
            "source_read",
            error=error,
            diagnostics=diagnostics,
            rows_fetched=rows_fetched,
            offset=existing_offset,
        )
        _record_failed_offset(offset_store, validated, existing_offset, error)
        return _result(
            validated,
            "failed",
            rows_fetched=rows_fetched,
            cursor_value=_offset_value(existing_offset),
            event_time_watermark=_watermark(existing_offset),
            error=error,
            diagnostics=diagnostics,
        )

    try:
        signals = {
            signal_key: _ensure_signal_for_config(sample_repository, validated, signal_key)
            for signal_key in validated.signal_keys
        }
    except Exception as exc:
        error = redact_sensitive_text(exc)
        diagnostics = _failure_diagnostics(
            "signal_setup",
            error=error,
            diagnostics=diagnostics,
            rows_fetched=len(read_result.rows),
            offset=existing_offset,
        )
        _record_failed_offset(offset_store, validated, existing_offset, error)
        return _result(
            validated,
            "failed",
            rows_fetched=len(read_result.rows),
            error=error,
            diagnostics=diagnostics,
        )
    try:
        mapping = map_rows_to_samples(read_result.rows, config=validated, signals=signals)
    except Exception as exc:
        error = redact_sensitive_text(exc)
        diagnostics = _failure_diagnostics(
            "map_rows",
            error=error,
            diagnostics=diagnostics,
            rows_fetched=len(read_result.rows),
            offset=existing_offset,
        )
        _record_failed_offset(offset_store, validated, existing_offset, error)
        return _result(
            validated,
            "failed",
            rows_fetched=len(read_result.rows),
            error=error,
            diagnostics=diagnostics,
        )
    try:
        batch_result = sample_repository.insert_samples(mapping.samples)
    except Exception as exc:
        error = redact_sensitive_text(exc)
        diagnostics = _failure_diagnostics(
            "persist_samples",
            error=error,
            diagnostics=diagnostics,
            rows_fetched=len(read_result.rows),
            samples_processed=mapping.stats.mapped,
            cursor_value=mapping.cursor_value,
            event_time_watermark=mapping.event_time_watermark,
            offset=existing_offset,
        )
        _record_failed_offset(offset_store, validated, existing_offset, error)
        return _result(
            validated,
            "failed",
            rows_fetched=len(read_result.rows),
            samples_processed=mapping.stats.mapped,
            cursor_value=mapping.cursor_value or _offset_value(existing_offset),
            event_time_watermark=mapping.event_time_watermark or _watermark(existing_offset),
            error=error,
            diagnostics=diagnostics,
        )
    try:
        persisted_samples = _load_detection_samples(
            sample_repository,
            signals.values(),
            batch_result.sample_ids,
            detectors=validated.detectors,
        )
        detector_events = _score_detector_events(
            persisted_samples,
            signals=signals,
            detectors=validated.detectors,
            baseline_repository=baseline_repository,
            detector_runner=detector_runner,
            score_sample_ids=batch_result.sample_ids,
            diagnostics=diagnostics,
        )
        event_result = event_repository.insert_events(detector_events) if detector_events else None
    except Exception as exc:
        error = redact_sensitive_text(exc)
        diagnostics = _failure_diagnostics(
            "persist_events",
            error=error,
            diagnostics=diagnostics,
            rows_fetched=len(read_result.rows),
            samples_processed=mapping.stats.mapped,
            cursor_value=mapping.cursor_value,
            event_time_watermark=mapping.event_time_watermark,
            offset=existing_offset,
        )
        _record_failed_offset(offset_store, validated, existing_offset, error)
        return _result(
            validated,
            "failed",
            rows_fetched=len(read_result.rows),
            samples_processed=mapping.stats.mapped,
            cursor_value=mapping.cursor_value or _offset_value(existing_offset),
            event_time_watermark=mapping.event_time_watermark or _watermark(existing_offset),
            error=error,
            diagnostics=diagnostics,
        )

    lag_seconds = _lag_seconds(mapping.event_time_watermark)
    offset_store.upsert_offset(
        StreamOffset(
            source_profile_id=validated.source_profile_id,
            stream_key=validated.stream_key,
            cursor_column=validated.cursor_column,
            cursor_value=mapping.cursor_value or _offset_value(existing_offset),
            cursor_tie_breaker_column=validated.record_key_column,
            cursor_tie_breaker_value=mapping.cursor_tie_breaker_value
            or _offset_tie_breaker(existing_offset),
            event_time_watermark=mapping.event_time_watermark or _watermark(existing_offset),
            last_success_at=utc_timestamp(),
            last_error=None,
            lag_seconds=lag_seconds,
            status="idle",
        )
    )
    return _result(
        validated,
        "completed",
        rows_fetched=len(read_result.rows),
        samples_processed=batch_result.processed,
        samples_inserted=batch_result.inserted,
        samples_skipped=batch_result.skipped,
        detector_events_created=event_result.inserted if event_result is not None else 0,
        cursor_value=mapping.cursor_value or _offset_value(existing_offset),
        event_time_watermark=mapping.event_time_watermark or _watermark(existing_offset),
        lag_seconds=lag_seconds,
        diagnostics=diagnostics,
    )


def _ensure_signal_for_config(
    sample_repository: RealtimeSampleRepository,
    config: RealtimePollConfig,
    signal_key: str,
) -> SignalDefinition:
    existing = sample_repository.get_signal_definition(
        source_profile_id=config.source_profile_id,
        signal_key=signal_key,
    )
    return sample_repository.upsert_signal_definition(
        _signal_definition_for_config(config, signal_key, existing=existing)
    )


def _signal_definition_for_config(
    config: RealtimePollConfig,
    signal_key: str,
    *,
    existing: SignalDefinition | None = None,
) -> SignalDefinition:
    return SignalDefinition(
        id=existing.id if existing is not None else None,
        source_profile_id=config.source_profile_id,
        signal_key=signal_key,
        metric_name=config.signal_columns[signal_key],
        unit=existing.unit if existing is not None else None,
        nominal=existing.nominal if existing is not None else None,
        lsl=existing.lsl if existing is not None else None,
        usl=existing.usl if existing is not None else None,
        lower_warning=existing.lower_warning if existing is not None else None,
        upper_warning=existing.upper_warning if existing is not None else None,
        segment_fields=config.segment_fields,
    )


def _load_persisted_samples(
    sample_repository: RealtimeSampleRepository,
    signals: Iterable[SignalDefinition],
    sample_ids: tuple[int, ...],
) -> list[IndustrialSample]:
    signal_ids = {signal.id for signal in signals if signal.id is not None}
    if not signal_ids or not sample_ids:
        return []
    return [
        sample
        for sample in sample_repository.list_samples_by_ids(sample_ids)
        if sample.signal_id in signal_ids
    ]


def _load_detection_samples(
    sample_repository: RealtimeSampleRepository,
    signals: Iterable[SignalDefinition],
    sample_ids: tuple[int, ...],
    *,
    detectors: tuple[str, ...],
) -> list[IndustrialSample]:
    new_samples = _load_persisted_samples(sample_repository, signals, sample_ids)
    if not new_samples or not (_normalized_detector_set(detectors) & _HISTORY_DETECTORS):
        return new_samples
    grouped_keys = {
        (sample.signal_id, _segment_key_tuple(sample.segment_key))
        for sample in new_samples
    }
    combined: dict[int, IndustrialSample] = {}
    for signal_id, segment_key_items in grouped_keys:
        segment_key = dict(segment_key_items)
        for sample in sample_repository.list_recent_samples(
            signal_id=signal_id,
            segment_key=segment_key,
            limit=_DETECTOR_HISTORY_LIMIT,
        ):
            if sample.id is not None:
                combined[int(sample.id)] = sample
    for sample in new_samples:
        if sample.id is not None:
            combined[int(sample.id)] = sample
    return sorted(combined.values(), key=lambda sample: (str(sample.event_time or ""), sample.id or -1))


def _score_detector_events(
    samples: Iterable[IndustrialSample],
    *,
    signals: Mapping[str, SignalDefinition],
    detectors: tuple[str, ...],
    diagnostics: dict[str, Any],
    baseline_repository: BaselineRepository | None = None,
    detector_runner: DetectorRunner | None = None,
    score_sample_ids: tuple[int, ...] = (),
) -> list[Any]:
    by_signal_segment: dict[tuple[int, tuple[tuple[str, Any], ...]], list[IndustrialSample]] = {}
    for sample in samples:
        by_signal_segment.setdefault(
            (sample.signal_id, _segment_key_tuple(sample.segment_key)),
            [],
        ).append(sample)
    signal_by_id = {
        int(signal.id): signal
        for signal in signals.values()
        if signal.id is not None
    }
    events: list[Any] = []
    baseline_detectors_enabled = bool(_normalized_detector_set(detectors) & _BASELINE_DETECTORS)
    for (signal_id, segment_key_items), signal_samples in by_signal_segment.items():
        signal = signal_by_id.get(signal_id)
        if signal is None:
            continue
        baseline = {}
        if baseline_repository is not None and baseline_detectors_enabled:
            baseline = baseline_repository.latest_baseline(
                signal_id=signal_id,
                segment_key=dict(segment_key_items),
            ) or {}
        try:
            if detector_runner is not None:
                events.extend(detector_runner(signal_samples, signal, detectors))
            else:
                events.extend(
                    _default_detector_runner(
                        signal_samples,
                        signal,
                        detectors,
                        baseline=baseline,
                        score_sample_ids=score_sample_ids,
                    )
                )
        except Exception as exc:
            diagnostics.setdefault("warnings", [])
            diagnostics["warnings"].append(f"detector failure: {redact_sensitive_text(exc)}")
    return events


def _default_detector_runner(
    samples: Iterable[IndustrialSample],
    signal: SignalDefinition,
    detectors: tuple[str, ...],
    *,
    baseline: Mapping[str, Any] | None = None,
    score_sample_ids: tuple[int, ...] = (),
) -> list[Any]:
    return run_detectors_for_samples(
        samples,
        signal=signal,
        detectors=detectors,
        baseline=baseline or {},
        score_sample_ids=score_sample_ids or None,
    )


def _record_failed_offset(
    offset_store: StreamOffsetStore,
    config: RealtimePollConfig,
    existing_offset: StreamOffset | None,
    error: str,
) -> None:
    offset_store.upsert_offset(
        StreamOffset(
            source_profile_id=config.source_profile_id,
            stream_key=config.stream_key,
            cursor_column=config.cursor_column,
            cursor_value=_offset_value(existing_offset),
            cursor_tie_breaker_column=existing_offset.cursor_tie_breaker_column
            if existing_offset
            else None,
            cursor_tie_breaker_value=_offset_tie_breaker(existing_offset),
            event_time_watermark=_watermark(existing_offset),
            last_success_at=existing_offset.last_success_at if existing_offset else None,
            last_error=redact_sensitive_text(error, max_len=500),
            lag_seconds=existing_offset.lag_seconds if existing_offset else None,
            status="failed",
        )
    )


def _failure_diagnostics(
    stage: str,
    *,
    error: str,
    diagnostics: Mapping[str, Any] | None = None,
    rows_fetched: int | None = None,
    samples_processed: int | None = None,
    cursor_value: str | None = None,
    event_time_watermark: str | None = None,
    offset: StreamOffset | None = None,
) -> dict[str, Any]:
    safe = _safe_mapping(diagnostics or {})
    existing_stage = str(safe.get("stage") or "").strip()
    if existing_stage:
        safe["stage"] = existing_stage
        if existing_stage != stage:
            safe["failure_stage"] = stage
    else:
        safe["stage"] = stage
    safe["error"] = redact_sensitive_text(error, max_len=500)
    if rows_fetched is not None:
        safe["rows_fetched"] = int(rows_fetched)
    if samples_processed is not None:
        safe["samples_processed"] = int(samples_processed)
    cursor = cursor_value or _offset_value(offset)
    if cursor not in (None, ""):
        safe["cursor_value"] = redact_sensitive_text(cursor, max_len=160)
    watermark = event_time_watermark or _watermark(offset)
    if watermark not in (None, ""):
        safe["event_time_watermark"] = redact_sensitive_text(watermark, max_len=160)
    if "query_summary" not in safe:
        query_summary = _query_summary_from_diagnostics(safe)
        if query_summary:
            safe["query_summary"] = query_summary
    return safe


def _query_summary_from_diagnostics(diagnostics: Mapping[str, Any]) -> str | None:
    summary = diagnostics.get("summary")
    if not isinstance(summary, Mapping):
        return None
    stream_key = summary.get("stream_key") or "stream"
    dialect = summary.get("dialect") or "source"
    limit = summary.get("limit")
    cursor_column = summary.get("cursor_column") or "cursor"
    source_object = summary.get("source_object") or "configured source"
    parts = [f"bounded {dialect} poll", f"source={source_object}", f"stream={stream_key}"]
    if limit is not None:
        parts.append(f"limit={limit}")
    if cursor_column:
        parts.append(f"cursor={cursor_column}")
    return ", ".join(str(part) for part in parts)


def _result(
    config: RealtimePollConfig,
    status: str,
    *,
    rows_fetched: int = 0,
    samples_processed: int = 0,
    samples_inserted: int = 0,
    samples_skipped: int = 0,
    detector_events_created: int = 0,
    cursor_value: str | None = None,
    event_time_watermark: str | None = None,
    lag_seconds: float | None = None,
    error: str | None = None,
    diagnostics: Mapping[str, Any] | None = None,
) -> PollingCycleResult:
    return PollingCycleResult(
        source_profile_id=config.source_profile_id,
        stream_key=config.stream_key,
        status=status,
        rows_fetched=rows_fetched,
        samples_processed=samples_processed,
        samples_inserted=samples_inserted,
        samples_skipped=samples_skipped,
        detector_events_created=detector_events_created,
        cursor_value=cursor_value,
        event_time_watermark=event_time_watermark,
        lag_seconds=lag_seconds,
        error=error,
        diagnostics=dict(diagnostics or {}),
    )


def _offset_value(offset: StreamOffset | None) -> str | None:
    return offset.cursor_value if offset is not None else None


def _offset_tie_breaker(offset: StreamOffset | None) -> str | None:
    return offset.cursor_tie_breaker_value if offset is not None else None


def _watermark(offset: StreamOffset | None) -> str | None:
    return offset.event_time_watermark if offset is not None else None


def _normalized_detector_set(detectors: Iterable[str]) -> set[str]:
    return {str(detector or "").strip().lower() for detector in detectors if str(detector or "").strip()}


def _segment_key_tuple(segment_key: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted((str(key), value) for key, value in dict(segment_key or {}).items()))


def _safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, nested in dict(value or {}).items():
        key_text = str(key)
        safe_value = _safe_diagnostic_value(key_text, nested)
        if safe_value is _SKIP_DIAGNOSTIC:
            continue
        safe[key_text] = safe_value
    return safe


_SKIP_DIAGNOSTIC = object()


def _safe_diagnostic_value(key: str, value: Any) -> Any:
    key_text = str(key)
    if _is_raw_sql_diagnostic_key(key_text):
        return _SKIP_DIAGNOSTIC
    if looks_sensitive_key(key_text) and key_text not in {"credentials_source"}:
        return "<redacted>"
    if isinstance(value, Mapping):
        return _safe_mapping(value)
    if isinstance(value, list):
        return tuple(_safe_diagnostic_value("", item) for item in value)
    if isinstance(value, tuple):
        return tuple(_safe_diagnostic_value("", item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value, max_len=None)
    return value


def _is_raw_sql_diagnostic_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return normalized in {"sql", "sql_text", "raw_sql", "query", "query_sql", "sql_query", "parameters"}


def _lag_seconds(event_time: str | None) -> float | None:
    if not event_time:
        return None
    try:
        text = str(event_time)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())

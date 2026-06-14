"""One-cycle realtime industrial polling service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import (
    IndustrialSourceProfile,
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
    existing_offset = offset_store.get_offset(
        source_profile_id=validated.source_profile_id,
        stream_key=validated.stream_key,
    )
    try:
        query = build_bounded_poll_query(profile=profile, config=validated, offset=existing_offset)
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
        _record_failed_offset(offset_store, validated, existing_offset, error)
        return _result(validated, "failed", error=error)

    diagnostics = safe_query_diagnostics(query)
    diagnostics.update(_safe_mapping(read_result.diagnostics))
    if read_result.error:
        error = redact_sensitive_text(read_result.error)
        _record_failed_offset(offset_store, validated, existing_offset, error)
        return _result(validated, "failed", rows_fetched=len(read_result.rows), error=error)

    signals = {
        signal_key: _ensure_signal_for_config(sample_repository, validated, signal_key)
        for signal_key in validated.signal_keys
    }
    mapping = map_rows_to_samples(read_result.rows, config=validated, signals=signals)
    try:
        batch_result = sample_repository.insert_samples(mapping.samples)
        persisted_samples = _load_persisted_samples(sample_repository, signals.values(), batch_result.sample_ids)
        detector_events = _score_detector_events(
            persisted_samples,
            signals=signals,
            detectors=validated.detectors,
            detector_runner=detector_runner,
            diagnostics=diagnostics,
        )
        event_result = event_repository.insert_events(detector_events) if detector_events else None
    except Exception as exc:
        error = redact_sensitive_text(exc)
        _record_failed_offset(offset_store, validated, existing_offset, error)
        return _result(
            validated,
            "failed",
            rows_fetched=len(read_result.rows),
            samples_processed=mapping.stats.mapped,
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
    wanted = set(sample_ids)
    loaded: list[IndustrialSample] = []
    for signal in signals:
        if signal.id is None:
            continue
        loaded.extend(
            sample
            for sample in sample_repository.list_samples(signal_id=signal.id)
            if sample.id in wanted
        )
    return loaded


def _score_detector_events(
    samples: Iterable[IndustrialSample],
    *,
    signals: Mapping[str, SignalDefinition],
    detectors: tuple[str, ...],
    detector_runner: DetectorRunner | None,
    diagnostics: dict[str, Any],
) -> list[Any]:
    by_signal: dict[int, list[IndustrialSample]] = {}
    for sample in samples:
        by_signal.setdefault(sample.signal_id, []).append(sample)
    signal_by_id = {
        int(signal.id): signal
        for signal in signals.values()
        if signal.id is not None
    }
    events: list[Any] = []
    runner = detector_runner or _default_detector_runner
    for signal_id, signal_samples in by_signal.items():
        signal = signal_by_id.get(signal_id)
        if signal is None:
            continue
        try:
            events.extend(runner(signal_samples, signal, detectors))
        except Exception as exc:
            diagnostics.setdefault("warnings", [])
            diagnostics["warnings"].append(f"detector failure: {redact_sensitive_text(exc)}")
    return events


def _default_detector_runner(
    samples: Iterable[IndustrialSample],
    signal: SignalDefinition,
    detectors: tuple[str, ...],
) -> list[Any]:
    return run_detectors_for_samples(samples, signal=signal, detectors=detectors, baseline={})


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
            event_time_watermark=_watermark(existing_offset),
            last_error=redact_sensitive_text(error, max_len=500),
            lag_seconds=existing_offset.lag_seconds if existing_offset else None,
            status="failed",
        )
    )


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


def _watermark(offset: StreamOffset | None) -> str | None:
    return offset.event_time_watermark if offset is not None else None


def _safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): redact_sensitive_text(nested, max_len=None) if isinstance(nested, str) else nested
        for key, nested in dict(value or {}).items()
        if str(key) != "sql_text"
    }


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

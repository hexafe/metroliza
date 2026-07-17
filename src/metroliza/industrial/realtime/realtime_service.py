"""One-cycle realtime industrial polling service."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Mapping

from metroliza.industrial.anomaly.baseline_repository import BaselineRepository
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
from metroliza.industrial.realtime.event_stream_repository import RealtimeEventStreamRepository
from metroliza.industrial.realtime.offset_store import (
    StreamOffsetConflictError,
    StreamOffsetStore,
)
from metroliza.industrial.realtime.replay import run_detectors_for_samples
from metroliza.industrial.realtime.sample_mapper import map_rows_to_samples
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository, utc_timestamp
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import (
    IndustrialSample,
    SignalDefinition,
    StreamOffset,
)
from metroliza.industrial.realtime.timestamps import parse_utc_timestamp
from metroliza.reports.db import run_transaction_with_retry

DetectorRunner = Callable[
    [Iterable[IndustrialSample], SignalDefinition, tuple[str, ...]],
    list[Any],
]

_BASELINE_DETECTORS = frozenset({"iqr", "mad_zscore"})
_HISTORY_DETECTORS = frozenset({"rolling_zscore"})
_SOURCE_HEALTH_DETECTORS = frozenset({"stale_source"})
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
    stream_events_appended: int = 0
    detector_events_created: int = 0
    detector_consumer_status: str | None = None
    detector_consumer_error: str | None = None
    detector_consumer_last_event_id: int | None = None
    cursor_value: str | None = None
    event_time_watermark: str | None = None
    lag_seconds: float | None = None
    error: str | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class PollChunkPersistenceError(RuntimeError):
    """Identify which atomic chunk-persistence stage failed."""

    def __init__(self, stage: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.stage = stage
        self.cause = cause


def run_polling_cycle(
    *,
    database: str,
    profile: IndustrialSourceProfile,
    config: RealtimePollConfig,
    adapter: SourceDbAdapter,
    detector_runner: DetectorRunner | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> PollingCycleResult:
    """Poll bounded chunks until exhausted, stopped, or the per-cycle catch-up cap is reached."""

    validated = config.validated()
    offset_store = StreamOffsetStore(database)
    previous_offset = offset_store.get_offset(
        source_profile_id=validated.source_profile_id,
        stream_key=validated.stream_key,
    )
    remaining = validated.max_catchup_rows_per_cycle
    chunk_results: list[PollingCycleResult] = []
    aggregate_status = "completed"
    aggregate_error = None
    aggregate_warnings: list[str] = []

    while remaining > 0:
        if _stop_requested(stop_check):
            aggregate_status = "cancelled" if not chunk_results else "completed_with_warnings"
            aggregate_warnings.append("Realtime catch-up stopped by request before the next chunk.")
            break
        chunk_limit = min(validated.chunk_size, remaining)
        chunk_config = replace(validated, chunk_size=chunk_limit)
        result = _run_polling_chunk(
            database=database,
            profile=profile,
            config=chunk_config,
            adapter=adapter,
            detector_runner=detector_runner,
            stop_check=stop_check,
        )
        chunk_results.append(result)
        if result.status in {"failed", "cancelled"}:
            aggregate_status = result.status
            aggregate_error = result.error
            break
        if result.status == "completed_with_warnings":
            aggregate_status = "completed_with_warnings"

        current_offset = offset_store.get_offset(
            source_profile_id=validated.source_profile_id,
            stream_key=validated.stream_key,
        )
        progressed = _offset_checkpoint(current_offset) != _offset_checkpoint(previous_offset)
        remaining -= result.rows_fetched
        if result.rows_fetched < chunk_limit:
            previous_offset = current_offset
            break
        if not progressed:
            aggregate_status = "completed_with_warnings"
            aggregate_warnings.append(
                "Realtime catch-up stopped because a full source chunk made no cursor progress."
            )
            previous_offset = current_offset
            break
        previous_offset = current_offset

    if remaining <= 0 and chunk_results and chunk_results[-1].rows_fetched:
        aggregate_warnings.append(
            f"Realtime catch-up reached the configured {validated.max_catchup_rows_per_cycle}-row cap."
        )

    final_offset = offset_store.get_offset(
        source_profile_id=validated.source_profile_id,
        stream_key=validated.stream_key,
    )
    return _aggregate_polling_chunks(
        validated,
        chunk_results,
        status=aggregate_status,
        error=aggregate_error,
        warnings=aggregate_warnings,
        offset=final_offset,
    )


def _run_polling_chunk(
    *,
    database: str,
    profile: IndustrialSourceProfile,
    config: RealtimePollConfig,
    adapter: SourceDbAdapter,
    detector_runner: DetectorRunner | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> PollingCycleResult:
    """Fetch and atomically persist one bounded realtime source chunk."""

    validated = config.validated()
    sample_repository = RealtimeSampleRepository(database)
    offset_store = StreamOffsetStore(database)
    stream_repository = RealtimeEventStreamRepository(database)
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

    if len(read_result.rows) > query.limit:
        error = (
            f"Source adapter returned {len(read_result.rows)} rows for a bounded "
            f"{query.limit}-row request."
        )
        diagnostics = _failure_diagnostics(
            "source_row_bound",
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
            cursor_value=_offset_value(existing_offset),
            event_time_watermark=_watermark(existing_offset),
            error=error,
            diagnostics=diagnostics,
        )
    if _stop_requested(stop_check):
        return _result(
            validated,
            "cancelled",
            rows_fetched=len(read_result.rows),
            cursor_value=_offset_value(existing_offset),
            event_time_watermark=_watermark(existing_offset),
            diagnostics={**diagnostics, "stage": "stopped_before_persist"},
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
        mapping = map_rows_to_samples(
            read_result.rows,
            config=validated,
            signals=signals,
            event_time_watermark=_watermark(existing_offset),
        )
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
    lag_seconds = _lag_seconds(mapping.event_time_watermark)
    diagnostics["mapping"] = {
        "rows_seen": mapping.stats.rows_seen,
        "samples_mapped": mapping.stats.mapped,
        "skipped_missing": mapping.stats.skipped_missing,
        "skipped_non_numeric": mapping.stats.skipped_non_numeric,
        "skipped_non_finite": mapping.stats.skipped_non_finite,
        "skipped_late": mapping.stats.skipped_late,
        "allowed_lateness_seconds": validated.allowed_lateness_seconds,
    }
    if mapping.warnings:
        diagnostics.setdefault("warnings", [])
        diagnostics["warnings"].extend(mapping.warnings)
    if _stop_requested(stop_check):
        return _result(
            validated,
            "cancelled",
            rows_fetched=len(read_result.rows),
            samples_processed=mapping.stats.mapped,
            cursor_value=_offset_value(existing_offset),
            event_time_watermark=_watermark(existing_offset),
            diagnostics={**diagnostics, "stage": "stopped_before_persist"},
        )
    try:
        batch_result, stream_append_result, saved_offset = _commit_mapped_chunk(
            database=database,
            config=validated,
            mapping=mapping,
            signals=signals,
            rows_fetched=len(read_result.rows),
            lag_seconds=lag_seconds,
            expected_offset=existing_offset,
            sample_repository=sample_repository,
            stream_repository=stream_repository,
            offset_store=offset_store,
        )
    except PollChunkPersistenceError as exc:
        if isinstance(exc.cause, StreamOffsetConflictError):
            current_offset = offset_store.get_offset(
                source_profile_id=validated.source_profile_id,
                stream_key=validated.stream_key,
            )
            warning = (
                "Realtime chunk was rolled back because another poller advanced the "
                "source checkpoint first."
            )
            diagnostics["stage"] = "concurrent_offset_advance"
            diagnostics.setdefault("warnings", [])
            diagnostics["warnings"].append(warning)
            diagnostics["expected_cursor_value"] = _offset_value(existing_offset)
            diagnostics["current_cursor_value"] = _offset_value(current_offset)
            return _result(
                validated,
                "completed_with_warnings",
                rows_fetched=len(read_result.rows),
                samples_processed=mapping.stats.mapped,
                cursor_value=_offset_value(current_offset),
                event_time_watermark=_watermark(current_offset),
                lag_seconds=current_offset.lag_seconds if current_offset else None,
                diagnostics=diagnostics,
            )
        error = redact_sensitive_text(exc.cause)
        diagnostics = _failure_diagnostics(
            exc.stage,
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
            cursor_value=_offset_value(existing_offset),
            event_time_watermark=_watermark(existing_offset),
            error=error,
            diagnostics=diagnostics,
        )

    detector_consumer_result = _run_detector_consumer(
        database=database,
        config=validated,
        detector_runner=detector_runner,
        diagnostics=diagnostics,
    )
    return _result(
        validated,
        "completed",
        rows_fetched=len(read_result.rows),
        samples_processed=batch_result.processed,
        samples_inserted=batch_result.inserted,
        samples_skipped=batch_result.skipped,
        stream_events_appended=stream_append_result.inserted
        + detector_consumer_result.stream_events_appended,
        detector_events_created=detector_consumer_result.detector_events_created,
        detector_consumer_status=detector_consumer_result.status,
        detector_consumer_error=detector_consumer_result.error,
        detector_consumer_last_event_id=detector_consumer_result.last_event_id,
        cursor_value=saved_offset.cursor_value,
        event_time_watermark=saved_offset.event_time_watermark,
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


def _commit_mapped_chunk(
    *,
    database: str,
    config: RealtimePollConfig,
    mapping,
    signals: Mapping[str, SignalDefinition],
    rows_fetched: int,
    lag_seconds: float | None,
    expected_offset: StreamOffset | None,
    sample_repository: RealtimeSampleRepository,
    stream_repository: RealtimeEventStreamRepository,
    offset_store: StreamOffsetStore,
):
    cursor_value = mapping.cursor_value or _offset_value(expected_offset)
    cursor_tie_breaker_value = (
        mapping.cursor_tie_breaker_value or _offset_tie_breaker(expected_offset)
    )
    watermark = mapping.event_time_watermark or _watermark(expected_offset)
    candidate_offset = StreamOffset(
        source_profile_id=config.source_profile_id,
        stream_key=config.stream_key,
        cursor_column=config.cursor_column,
        cursor_value=cursor_value,
        cursor_tie_breaker_column=config.record_key_column,
        cursor_tie_breaker_value=cursor_tie_breaker_value,
        event_time_watermark=watermark,
        last_success_at=utc_timestamp(),
        last_error=None,
        lag_seconds=lag_seconds,
        status="idle",
    )
    stage = "persist_samples"

    def _commit(cursor):
        nonlocal stage
        stage = "persist_samples"
        batch_result = sample_repository.insert_samples(mapping.samples, _cursor=cursor)
        stage = "append_stream_event"
        stream_append_result = stream_repository.append_sample_batch_committed(
            source_profile_id=config.source_profile_id,
            stream_key=config.stream_key,
            sample_ids=batch_result.sample_ids,
            signal_ids=tuple(signal.id for signal in signals.values() if signal.id is not None),
            detectors=config.detectors,
            event_time=watermark or utc_timestamp(),
            payload={
                "rows_fetched": rows_fetched,
                "samples_processed": batch_result.processed,
                "samples_inserted": batch_result.inserted,
                "samples_skipped": batch_result.skipped,
                "cursor_column": config.cursor_column,
                "cursor_value": cursor_value,
                "cursor_tie_breaker_column": config.record_key_column,
                "cursor_tie_breaker_value": cursor_tie_breaker_value,
                "event_time_watermark": watermark,
                "lag_seconds": lag_seconds,
            },
            _cursor=cursor,
        )
        stage = "update_source_offset"
        saved_offset = offset_store.upsert_offset(
            candidate_offset,
            expected_offset=expected_offset,
            _cursor=cursor,
        )
        return batch_result, stream_append_result, saved_offset

    try:
        return run_transaction_with_retry(database, _commit)
    except Exception as exc:
        raise PollChunkPersistenceError(stage, exc) from exc


def _aggregate_polling_chunks(
    config: RealtimePollConfig,
    chunks: list[PollingCycleResult],
    *,
    status: str,
    error: str | None,
    warnings: list[str],
    offset: StreamOffset | None,
) -> PollingCycleResult:
    last = chunks[-1] if chunks else None
    diagnostics = dict(last.diagnostics) if last is not None else {}
    chunk_diagnostics = tuple(dict(chunk.diagnostics) for chunk in chunks)
    diagnostics["chunks_processed"] = len(chunks)
    diagnostics["chunk_diagnostics"] = chunk_diagnostics
    all_warnings = [
        str(warning)
        for chunk in chunks
        for warning in tuple(chunk.diagnostics.get("warnings") or ())
    ]
    all_warnings.extend(warnings)
    if all_warnings:
        diagnostics["warnings"] = tuple(dict.fromkeys(all_warnings))
    if warnings and any("row cap" in warning for warning in warnings):
        diagnostics["catchup_limit_reached"] = True
    return _result(
        config,
        status,
        rows_fetched=sum(chunk.rows_fetched for chunk in chunks),
        samples_processed=sum(chunk.samples_processed for chunk in chunks),
        samples_inserted=sum(chunk.samples_inserted for chunk in chunks),
        samples_skipped=sum(chunk.samples_skipped for chunk in chunks),
        stream_events_appended=sum(chunk.stream_events_appended for chunk in chunks),
        detector_events_created=sum(chunk.detector_events_created for chunk in chunks),
        detector_consumer_status=last.detector_consumer_status if last else None,
        detector_consumer_error=last.detector_consumer_error if last else None,
        detector_consumer_last_event_id=(last.detector_consumer_last_event_id if last else None),
        cursor_value=_offset_value(offset),
        event_time_watermark=_watermark(offset),
        lag_seconds=offset.lag_seconds if offset is not None else None,
        error=error,
        diagnostics=diagnostics,
    )


def _offset_checkpoint(offset: StreamOffset | None) -> tuple[str | None, str | None]:
    if offset is None:
        return None, None
    return offset.cursor_value, offset.cursor_tie_breaker_value


def _stop_requested(stop_check: Callable[[], bool] | None) -> bool:
    return bool(stop_check is not None and stop_check())


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
    grouped_samples: dict[tuple[int, tuple[tuple[str, Any], ...]], list[IndustrialSample]] = {}
    for sample in new_samples:
        grouped_samples.setdefault(
            (sample.signal_id, _segment_key_tuple(sample.segment_key)), []
        ).append(sample)
    combined: dict[int, IndustrialSample] = {}
    for (signal_id, segment_key_items), boundary_samples in grouped_samples.items():
        segment_key = dict(segment_key_items)
        earliest = min(
            boundary_samples,
            key=lambda sample: (str(sample.event_time or ""), int(sample.id or -1)),
        )
        if earliest.id is None:
            continue
        for sample in sample_repository.list_samples_before(
            signal_id=signal_id,
            before_event_time=earliest.event_time,
            before_sample_id=earliest.id,
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
    strict: bool = False,
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
    default_sample_detectors = tuple(
        detector
        for detector in detectors
        if str(detector or "").strip().lower() not in _SOURCE_HEALTH_DETECTORS
    )
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
            elif default_sample_detectors:
                events.extend(
                    _default_detector_runner(
                        signal_samples,
                        signal,
                        default_sample_detectors,
                        baseline=baseline,
                        score_sample_ids=score_sample_ids,
                    )
                )
        except Exception as exc:
            if strict:
                raise RuntimeError(f"detector failure: {redact_sensitive_text(exc)}") from exc
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
        now=utc_timestamp(),
        score_sample_ids=score_sample_ids or None,
    )


def _run_detector_consumer(
    *,
    database: str,
    config: RealtimePollConfig,
    detector_runner: DetectorRunner | None,
    diagnostics: dict[str, Any],
):
    from metroliza.industrial.realtime.detector_consumer import RealtimeDetectorConsumer

    consumer = RealtimeDetectorConsumer(database, detector_runner=detector_runner)
    result = consumer.process_once(config=config)
    diagnostics["detector_consumer_status"] = result.status
    if result.last_event_id is not None:
        diagnostics["detector_consumer_last_event_id"] = result.last_event_id
    if result.diagnostics:
        diagnostics["detector_consumer_diagnostics"] = _safe_mapping(result.diagnostics)
        warnings = result.diagnostics.get("warnings")
        if isinstance(warnings, list | tuple):
            diagnostics.setdefault("warnings", [])
            diagnostics["warnings"].extend(str(warning) for warning in warnings)
    if result.error:
        diagnostics.setdefault("warnings", [])
        diagnostics["warnings"].append(f"detector consumer failure: {result.error}")
    return result


def _record_failed_offset(
    offset_store: StreamOffsetStore,
    config: RealtimePollConfig,
    existing_offset: StreamOffset | None,
    error: str,
) -> None:
    offset_store.mark_failure(
        source_profile_id=config.source_profile_id,
        stream_key=config.stream_key,
        cursor_column=config.cursor_column,
        error=redact_sensitive_text(error, max_len=500),
        expected_offset=existing_offset,
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
    stream_events_appended: int = 0,
    detector_events_created: int = 0,
    detector_consumer_status: str | None = None,
    detector_consumer_error: str | None = None,
    detector_consumer_last_event_id: int | None = None,
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
        stream_events_appended=stream_events_appended,
        detector_events_created=detector_events_created,
        detector_consumer_status=detector_consumer_status,
        detector_consumer_error=detector_consumer_error,
        detector_consumer_last_event_id=detector_consumer_last_event_id,
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
        parsed = parse_utc_timestamp(event_time)
    except ValueError:
        return None
    now = parse_utc_timestamp(utc_timestamp())
    return max(0.0, (now - parsed).total_seconds())

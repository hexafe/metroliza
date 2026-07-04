"""Consume realtime sample-batch stream events and persist detector anomaly events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from metroliza.industrial.anomaly.baseline_repository import BaselineRepository
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import redact_sensitive_text
from metroliza.industrial.realtime.event_stream import (
    DEFAULT_DETECTOR_CONSUMER_KEY,
    SAMPLE_BATCH_COMMITTED_EVENT_TYPE,
    RealtimeDetectorConsumerResult,
    RealtimeStreamEvent,
)
from metroliza.industrial.realtime.event_stream_repository import RealtimeEventStreamRepository
from metroliza.industrial.realtime.realtime_service import (
    DetectorRunner,
    _load_detection_samples,
    _score_detector_events,
)
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


class RealtimeDetectorConsumer:
    """Run configured deterministic detectors as a local event-stream consumer."""

    def __init__(
        self,
        database: str,
        *,
        event_stream_repository: RealtimeEventStreamRepository | None = None,
        sample_repository: RealtimeSampleRepository | None = None,
        event_repository: AnomalyEventRepository | None = None,
        baseline_repository: BaselineRepository | None = None,
        consumer_key: str = DEFAULT_DETECTOR_CONSUMER_KEY,
        detector_runner: DetectorRunner | None = None,
    ) -> None:
        self.database = database
        self.event_stream_repository = event_stream_repository or RealtimeEventStreamRepository(database)
        self.sample_repository = sample_repository or RealtimeSampleRepository(database)
        self.event_repository = event_repository or AnomalyEventRepository(database)
        self.baseline_repository = baseline_repository or BaselineRepository(database)
        self.consumer_key = str(consumer_key or DEFAULT_DETECTOR_CONSUMER_KEY)
        self.detector_runner = detector_runner

    def process_once(
        self,
        *,
        config: RealtimePollConfig,
        limit: int = 500,
    ) -> RealtimeDetectorConsumerResult:
        """Process pending sample-batch events for one realtime stream."""

        validated = config.validated()
        try:
            offset = self.event_stream_repository.get_consumer_offset(
                consumer_key=self.consumer_key,
                source_profile_id=validated.source_profile_id,
                stream_key=validated.stream_key,
            )
        except Exception as exc:
            return self._failure_result(validated, exc, stage="read_consumer_offset")
        last_event_id = offset.last_event_id if offset is not None else 0
        try:
            stream_events = self.event_stream_repository.read_events_after(
                source_profile_id=validated.source_profile_id,
                stream_key=validated.stream_key,
                after_event_id=last_event_id,
                limit=limit,
                event_types=(SAMPLE_BATCH_COMMITTED_EVENT_TYPE,),
            )
        except Exception as exc:
            return self._failure_result(validated, exc, stage="read_stream_events")

        if not stream_events:
            return RealtimeDetectorConsumerResult(status="idle", last_event_id=last_event_id)

        processed_count = 0
        samples_loaded = 0
        detector_events_processed = 0
        detector_events_created = 0
        detector_events_skipped = 0
        stream_events_appended = 0
        current_event_id = last_event_id
        diagnostics: dict[str, Any] = {}

        for stream_event in stream_events:
            try:
                processed = self._process_sample_batch_event(stream_event, validated)
                current_event_id = int(stream_event.event_id or 0)
                self.event_stream_repository.update_consumer_offset(
                    consumer_key=self.consumer_key,
                    source_profile_id=validated.source_profile_id,
                    stream_key=validated.stream_key,
                    last_event_id=current_event_id,
                )
            except Exception as exc:
                error = redact_sensitive_text(exc, max_len=500)
                self.event_stream_repository.mark_consumer_failure(
                    consumer_key=self.consumer_key,
                    source_profile_id=validated.source_profile_id,
                    stream_key=validated.stream_key,
                    error=error,
                )
                return RealtimeDetectorConsumerResult(
                    status="failed",
                    stream_events_processed=processed_count,
                    samples_loaded=samples_loaded,
                    detector_events_processed=detector_events_processed,
                    detector_events_created=detector_events_created,
                    detector_events_skipped=detector_events_skipped,
                    stream_events_appended=stream_events_appended,
                    last_event_id=current_event_id,
                    error=error,
                    diagnostics={"stage": "process_stream_event", "error": error, **diagnostics},
                )

            processed_count += 1
            samples_loaded += processed["samples_loaded"]
            detector_events_processed += processed["detector_events_processed"]
            detector_events_created += processed["detector_events_created"]
            detector_events_skipped += processed["detector_events_skipped"]
            stream_events_appended += processed["stream_events_appended"]
            if processed["warnings"]:
                diagnostics.setdefault("warnings", [])
                diagnostics["warnings"].extend(processed["warnings"])

        return RealtimeDetectorConsumerResult(
            status="completed",
            stream_events_processed=processed_count,
            samples_loaded=samples_loaded,
            detector_events_processed=detector_events_processed,
            detector_events_created=detector_events_created,
            detector_events_skipped=detector_events_skipped,
            stream_events_appended=stream_events_appended,
            last_event_id=current_event_id,
            diagnostics=diagnostics,
        )

    def _process_sample_batch_event(
        self,
        stream_event: RealtimeStreamEvent,
        config: RealtimePollConfig,
    ) -> dict[str, Any]:
        if stream_event.event_id is None:
            raise ValueError("stream event id is required")
        payload = dict(stream_event.payload or {})
        sample_ids = _ids_from_payload(payload.get("sample_ids"))
        if not sample_ids:
            raise ValueError("sample_batch_committed payload requires sample_ids")

        samples = self.sample_repository.list_samples_by_ids(sample_ids)
        _ensure_all_samples_loaded(sample_ids, samples)
        signal_ids = _ids_from_payload(payload.get("signal_ids")) or tuple(
            sorted({int(sample.signal_id) for sample in samples})
        )
        signals = self.sample_repository.list_signal_definitions_by_ids(signal_ids)
        _ensure_all_signals_loaded(signal_ids, signals)
        detectors = _detectors_from_payload(payload, config.detectors)

        detection_samples = _load_detection_samples(
            self.sample_repository,
            signals,
            sample_ids,
            detectors=detectors,
        )
        score_diagnostics: dict[str, Any] = {}
        detector_events = _score_detector_events(
            detection_samples,
            signals={signal.signal_key: signal for signal in signals},
            detectors=detectors,
            baseline_repository=self.baseline_repository,
            detector_runner=self.detector_runner,
            score_sample_ids=sample_ids,
            diagnostics=score_diagnostics,
            strict=True,
        )
        event_result = self.event_repository.insert_events(detector_events) if detector_events else None
        stream_events_appended = 0
        if event_result is not None and event_result.event_ids:
            append_result = self.event_stream_repository.append_anomaly_events_committed(
                source_profile_id=config.source_profile_id,
                stream_key=config.stream_key,
                source_event_id=stream_event.event_id,
                anomaly_event_ids=event_result.event_ids,
                sample_ids=sample_ids,
                inserted=event_result.inserted,
                skipped=event_result.skipped,
            )
            stream_events_appended = append_result.inserted

        return {
            "samples_loaded": len(samples),
            "detector_events_processed": event_result.processed if event_result is not None else 0,
            "detector_events_created": event_result.inserted if event_result is not None else 0,
            "detector_events_skipped": event_result.skipped if event_result is not None else 0,
            "stream_events_appended": stream_events_appended,
            "warnings": tuple(score_diagnostics.get("warnings", ())),
        }

    def _failure_result(
        self,
        config: RealtimePollConfig,
        exc: Exception,
        *,
        stage: str,
    ) -> RealtimeDetectorConsumerResult:
        error = redact_sensitive_text(exc, max_len=500)
        try:
            offset = self.event_stream_repository.mark_consumer_failure(
                consumer_key=self.consumer_key,
                source_profile_id=config.source_profile_id,
                stream_key=config.stream_key,
                error=error,
            )
            last_event_id = offset.last_event_id
        except Exception as failure_exc:
            last_event_id = None
            return RealtimeDetectorConsumerResult(
                status="failed",
                last_event_id=last_event_id,
                error=error,
                diagnostics={
                    "stage": stage,
                    "error": error,
                    "failure_marking_error": redact_sensitive_text(failure_exc, max_len=500),
                },
            )
        return RealtimeDetectorConsumerResult(
            status="failed",
            last_event_id=last_event_id,
            error=error,
            diagnostics={"stage": stage, "error": error},
        )


def _ids_from_payload(raw_value: Any) -> tuple[int, ...]:
    if raw_value in (None, ""):
        return ()
    if isinstance(raw_value, str):
        raw_items: Iterable[Any] = [part.strip() for part in raw_value.split(",")]
    elif isinstance(raw_value, Mapping):
        raw_items = raw_value.values()
    else:
        raw_items = raw_value
    try:
        return tuple(dict.fromkeys(int(value) for value in raw_items if value not in (None, "")))
    except TypeError as exc:
        raise ValueError("payload IDs must be iterable") from exc


def _detectors_from_payload(
    payload: Mapping[str, Any],
    default_detectors: tuple[str, ...],
) -> tuple[str, ...]:
    raw_value = payload.get("detectors", payload.get("detector_keys"))
    if raw_value in (None, ""):
        return default_detectors
    if isinstance(raw_value, str):
        raw_items: Iterable[Any] = raw_value.split(",")
    else:
        raw_items = raw_value
    detectors = tuple(
        dict.fromkeys(
            str(detector or "").strip()
            for detector in raw_items
            if str(detector or "").strip()
        )
    )
    return detectors or default_detectors


def _ensure_all_samples_loaded(sample_ids: tuple[int, ...], samples: list[IndustrialSample]) -> None:
    loaded_ids = {int(sample.id) for sample in samples if sample.id is not None}
    missing = tuple(sample_id for sample_id in sample_ids if sample_id not in loaded_ids)
    if missing:
        raise ValueError(f"sample_batch_committed references missing sample IDs: {missing}")


def _ensure_all_signals_loaded(signal_ids: tuple[int, ...], signals: list[SignalDefinition]) -> None:
    loaded_ids = {int(signal.id) for signal in signals if signal.id is not None}
    missing = tuple(signal_id for signal_id in signal_ids if signal_id not in loaded_ids)
    if missing:
        raise ValueError(f"sample_batch_committed references missing signal IDs: {missing}")

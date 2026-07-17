"""Replay CSV industrial samples through deterministic realtime detectors."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field, replace
import math
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from metroliza.industrial.anomaly.contracts import DetectorContext, DetectorState, DetectionResult
from metroliza.industrial.anomaly.detectors import (
    IQRDetector,
    MadZScoreDetector,
    RollingZScoreDetector,
    SpecLimitDetector,
    StaleSourceDetector,
)
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.realtime.detector_registry import normalize_detector_keys
from metroliza.industrial.realtime.numeric_validation import exact_integral
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition
from metroliza.industrial.realtime.timestamps import canonical_utc_timestamp
from metroliza.industrial.realtime.timestamps import validate_source_timezone


@dataclass(frozen=True)
class ReplayRequest:
    input_file: str
    database: str
    source_profile_id: int
    signal_key: str
    metric_column: str
    event_time_column: str
    record_key_column: str
    detectors: tuple[str, ...] = ("spec_limits",)
    limit: int | None = None
    dry_run: bool = False
    lsl: float | None = None
    usl: float | None = None
    lower_warning: float | None = None
    upper_warning: float | None = None
    source_timezone: str = "UTC"
    batch_size: int = 500
    now: str | None = None


@dataclass(frozen=True)
class ReplaySummary:
    samples_processed: int
    samples_inserted: int
    samples_skipped: int
    detector_events_created: int
    event_counts: Mapping[str, int] = field(default_factory=dict)

    def as_lines(self) -> list[str]:
        lines = [
            f"samples processed: {self.samples_processed}",
            f"samples inserted: {self.samples_inserted}",
            f"samples skipped: {self.samples_skipped}",
            f"detector events created: {self.detector_events_created}",
        ]
        for key in sorted(self.event_counts):
            lines.append(f"{key}: {self.event_counts[key]}")
        return lines


def load_csv_rows(input_file: str, *, limit: int | None = None) -> list[dict[str, str]]:
    """Compatibility wrapper returning bounded CSV rows as a list."""

    return list(iter_csv_rows(input_file, limit=limit))


def iter_csv_rows(input_file: str, *, limit: int | None = None) -> Iterator[dict[str, str]]:
    """Yield CSV rows without materializing the replay input."""

    path = Path(input_file)
    if path.suffix.lower() != ".csv":
        raise ValueError("Replay MVP supports CSV input only.")
    validated_limit = (
        exact_integral(limit, field_name="Replay limit", minimum=1)
        if limit is not None
        else None
    )
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            yield dict(row)
            if validated_limit is not None and index >= validated_limit:
                break


def rows_to_samples(rows: Iterable[Mapping[str, Any]], request: ReplayRequest, signal_id: int) -> list[IndustrialSample]:
    return list(iter_rows_to_samples(rows, request, signal_id))


def iter_rows_to_samples(
    rows: Iterable[Mapping[str, Any]],
    request: ReplayRequest,
    signal_id: int,
) -> Iterator[IndustrialSample]:
    """Yield finite, canonical samples from replay source rows."""

    for row in rows:
        metric_raw = row.get(request.metric_column)
        event_time_raw = row.get(request.event_time_column)
        record_key = str(row.get(request.record_key_column) or "").strip()
        if metric_raw in (None, "") or event_time_raw in (None, "") or not record_key:
            continue
        event_time = canonical_utc_timestamp(
            event_time_raw,
            source_timezone=request.source_timezone,
        )
        try:
            value = float(metric_raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        yield IndustrialSample(
            source_profile_id=request.source_profile_id,
            signal_id=signal_id,
            source_record_key=record_key,
            event_time=event_time,
            metric_name=request.metric_column,
            value=value,
            reference=str(row.get("reference") or "") or None,
            part_number=str(row.get("part_number") or "") or None,
            revision=str(row.get("revision") or "") or None,
            station=str(row.get("station") or "") or None,
            line=str(row.get("line") or "") or None,
            work_order=str(row.get("work_order") or "") or None,
            batch_lot=str(row.get("batch_lot") or "") or None,
            segment_key={
                key: str(row[key])
                for key in ("reference", "part_number", "revision", "station", "line")
                if row.get(key) not in (None, "")
            },
            raw_record={
                key: row[key]
                for key in (
                    request.record_key_column,
                    request.event_time_column,
                    request.metric_column,
                    "reference",
                    "part_number",
                    "revision",
                    "station",
                    "line",
                    "work_order",
                    "batch_lot",
                )
                if key in row
            },
        )


def _detector_instances(keys: Iterable[str]):
    instances = []
    for normalized in normalize_detector_keys(keys):
        if normalized == "spec_limits":
            instances.append(SpecLimitDetector())
        elif normalized == "iqr":
            instances.append(IQRDetector())
        elif normalized == "mad_zscore":
            instances.append(MadZScoreDetector())
        elif normalized == "rolling_zscore":
            instances.append(RollingZScoreDetector())
        elif normalized == "stale_source":
            instances.append(StaleSourceDetector())
    return tuple(instances)


def _sample_sort_key(sample: IndustrialSample) -> tuple[str, int, str]:
    sample_id = sample.id if sample.id is not None else -1
    return (str(sample.event_time or ""), sample_id, sample.source_record_key)


def _unique_samples_for_detection(samples: Iterable[IndustrialSample]) -> list[IndustrialSample]:
    unique_samples: list[IndustrialSample] = []
    seen: set[tuple[Any, ...]] = set()
    for sample in samples:
        if sample.id is not None:
            key = ("id", sample.id)
        else:
            key = (
                "record",
                sample.source_profile_id,
                sample.signal_id,
                sample.source_record_key,
            )
        if key in seen:
            continue
        seen.add(key)
        unique_samples.append(sample)
    return unique_samples


def run_detectors_for_samples(
    samples: Iterable[IndustrialSample],
    *,
    signal: SignalDefinition,
    detectors: Iterable[str],
    baseline: Mapping[str, Any] | None = None,
    now: str | None = None,
    score_sample_ids: Iterable[int] | None = None,
) -> list[DetectionResult]:
    detector_objects = _detector_instances(detectors)
    sample_detectors = tuple(
        detector for detector in detector_objects if detector.detector_key != "stale_source"
    )
    source_detectors = tuple(
        detector for detector in detector_objects if detector.detector_key == "stale_source"
    )
    states: dict[str, DetectorState] = {}
    events: list[DetectionResult] = []
    scored_ids = None if score_sample_ids is None else {int(sample_id) for sample_id in score_sample_ids}
    sorted_samples = sorted(_unique_samples_for_detection(samples), key=_sample_sort_key)
    for sample in sorted_samples:
        for detector in sample_detectors:
            state = states.get(detector.detector_key, DetectorState())
            context = DetectorContext(
                signal=signal,
                baseline=dict(baseline or {}),
                state=state,
                now=now,
            )
            result = detector.score_one(sample, context)
            should_emit = scored_ids is None or (sample.id is not None and int(sample.id) in scored_ids)
            if result is not None and should_emit:
                events.append(result)
            states[detector.detector_key] = detector.update_one(sample, context)
    if sorted_samples:
        latest_sample = sorted_samples[-1]
        latest_is_eligible = scored_ids is None or (
            latest_sample.id is not None and int(latest_sample.id) in scored_ids
        )
        if latest_is_eligible:
            for detector in source_detectors:
                context = DetectorContext(
                    signal=signal,
                    baseline=dict(baseline or {}),
                    state=DetectorState(),
                    now=now,
                )
                result = detector.score_one(latest_sample, context)
                if result is not None:
                    events.append(result)
    return events


def replay_industrial_stream(request: ReplayRequest) -> ReplaySummary:
    request = _validated_replay_request(request)
    _validate_replay_input_order(request)
    sample_repository = RealtimeSampleRepository(request.database)
    existing_signal = sample_repository.get_signal_definition(
        source_profile_id=request.source_profile_id,
        signal_key=request.signal_key,
    )
    signal_candidate = SignalDefinition(
        id=existing_signal.id if existing_signal is not None else None,
        source_profile_id=request.source_profile_id,
        signal_key=request.signal_key,
        metric_name=request.metric_column,
        lsl=request.lsl if request.lsl is not None else _signal_attr(existing_signal, "lsl"),
        usl=request.usl if request.usl is not None else _signal_attr(existing_signal, "usl"),
        lower_warning=(
            request.lower_warning
            if request.lower_warning is not None
            else _signal_attr(existing_signal, "lower_warning")
        ),
        upper_warning=(
            request.upper_warning
            if request.upper_warning is not None
            else _signal_attr(existing_signal, "upper_warning")
        ),
    )
    if request.dry_run:
        signal = signal_candidate if signal_candidate.id is not None else SignalDefinition(
            id=-1,
            source_profile_id=request.source_profile_id,
            signal_key=request.signal_key,
            metric_name=request.metric_column,
            lsl=signal_candidate.lsl,
            usl=signal_candidate.usl,
            lower_warning=signal_candidate.lower_warning,
            upper_warning=signal_candidate.upper_warning,
        )
    else:
        signal = sample_repository.upsert_signal_definition(signal_candidate)
    assert signal.id is not None
    batch_size = request.batch_size
    detector_session = _ReplayDetectorSession(
        signal=signal,
        detectors=request.detectors,
        now=request.now,
    )
    processed = 0
    inserted = 0
    skipped = 0
    created = 0
    event_counts: dict[str, int] = {}
    event_repository = AnomalyEventRepository(request.database)
    rows = iter_csv_rows(request.input_file, limit=request.limit)
    for row_batch in _batched(rows, batch_size=batch_size):
        samples = rows_to_samples(row_batch, request, signal.id)
        processed += len(samples)
        if request.dry_run:
            persisted_samples = samples
        else:
            batch_result = sample_repository.insert_samples(samples)
            inserted += batch_result.inserted
            skipped += batch_result.skipped
            persisted_samples = sample_repository.list_samples_by_ids(batch_result.sample_ids)
        events = detector_session.score(persisted_samples)
        if not request.dry_run and events:
            event_result = event_repository.insert_events(events)
            created += event_result.inserted
        for event in events:
            key = f"{event.detector_key}/{event.severity}"
            event_counts[key] = event_counts.get(key, 0) + 1

    # Source staleness is a property of the final replay watermark, not of every historical
    # sample. Evaluate it once so deterministic replays do not manufacture one stale event per
    # old row.
    final_events = detector_session.finalize()
    if not request.dry_run and final_events:
        event_result = event_repository.insert_events(final_events)
        created += event_result.inserted
    for event in final_events:
        key = f"{event.detector_key}/{event.severity}"
        event_counts[key] = event_counts.get(key, 0) + 1

    return ReplaySummary(
        samples_processed=processed,
        samples_inserted=inserted,
        samples_skipped=skipped,
        detector_events_created=created,
        event_counts=event_counts,
    )


def _validate_replay_input_order(request: ReplayRequest) -> None:
    """Reject unordered replay input before any signal, sample, or event is persisted."""

    last_event_time: str | None = None
    rows = iter_csv_rows(request.input_file, limit=request.limit)
    for row_batch in _batched(rows, batch_size=request.batch_size):
        for sample in rows_to_samples(row_batch, request, signal_id=-1):
            if last_event_time is not None and sample.event_time < last_event_time:
                raise ValueError(
                    "Replay input must be ordered by event time for bounded streaming detection."
                )
            last_event_time = sample.event_time
    if request.now is not None and last_event_time is not None and request.now < last_event_time:
        raise ValueError(
            "Replay now must be at or after the final replay sample event time."
        )


def _validated_replay_request(request: ReplayRequest) -> ReplayRequest:
    detectors = normalize_detector_keys(request.detectors)
    now_text = str(request.now or "").strip()
    if "stale_source" in detectors and not now_text:
        raise ValueError("Replay now is required when stale_source is selected.")
    source_timezone = validate_source_timezone(request.source_timezone)
    return replace(
        request,
        detectors=detectors,
        source_profile_id=exact_integral(
            request.source_profile_id,
            field_name="Replay source_profile_id",
            minimum=1,
        ),
        limit=(
            exact_integral(request.limit, field_name="Replay limit", minimum=1)
            if request.limit is not None
            else None
        ),
        source_timezone=source_timezone,
        batch_size=exact_integral(
            request.batch_size,
            field_name="Replay batch_size",
            minimum=1,
        ),
        now=(
            canonical_utc_timestamp(now_text, source_timezone=source_timezone)
            if now_text
            else None
        ),
    )


def _signal_attr(signal: SignalDefinition | None, name: str) -> Any:
    return getattr(signal, name) if signal is not None else None


class _ReplayDetectorSession:
    """Bounded detector state carried across streamed replay batches."""

    def __init__(
        self,
        *,
        signal: SignalDefinition,
        detectors: Iterable[str],
        now: str | None,
    ) -> None:
        self.signal = signal
        detector_instances = _detector_instances(detectors)
        self.detectors = tuple(
            detector for detector in detector_instances if detector.detector_key != "stale_source"
        )
        self.stale_detector = next(
            (
                detector
                for detector in detector_instances
                if detector.detector_key == "stale_source"
            ),
            None,
        )
        self.now = now
        self.states: dict[str, DetectorState] = {}
        self.last_event_time: str | None = None
        self.latest_sample: IndustrialSample | None = None

    def score(self, samples: Iterable[IndustrialSample]) -> list[DetectionResult]:
        events: list[DetectionResult] = []
        for sample in sorted(_unique_samples_for_detection(samples), key=_sample_sort_key):
            if self.last_event_time is not None and sample.event_time < self.last_event_time:
                raise ValueError(
                    "Replay input must be ordered by event time for bounded streaming detection."
                )
            for detector in self.detectors:
                state = self.states.get(detector.detector_key, DetectorState())
                context = DetectorContext(signal=self.signal, state=state)
                result = detector.score_one(sample, context)
                if result is not None:
                    events.append(result)
                self.states[detector.detector_key] = detector.update_one(sample, context)
            self.last_event_time = sample.event_time
            self.latest_sample = sample
        return events

    def finalize(self) -> list[DetectionResult]:
        """Evaluate source-level detectors once against the final replay watermark."""

        if self.stale_detector is None or self.latest_sample is None:
            return []
        sample = self.latest_sample
        if sample.id is None:
            # Dry-run samples are intentionally not persisted, but the detector contract uses a
            # sample identity in its explainable result. The synthetic id never reaches storage.
            sample = replace(sample, id=-1)
        state = self.states.get(self.stale_detector.detector_key, DetectorState())
        context = DetectorContext(signal=self.signal, state=state, now=self.now)
        result = self.stale_detector.score_one(sample, context)
        return [result] if result is not None else []


def _batched(
    rows: Iterable[Mapping[str, Any]],
    *,
    batch_size: int,
) -> Iterator[tuple[Mapping[str, Any], ...]]:
    batch: list[Mapping[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            yield tuple(batch)
            batch.clear()
    if batch:
        yield tuple(batch)

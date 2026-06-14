"""Replay CSV industrial samples through deterministic realtime detectors."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from metroliza.industrial.anomaly.contracts import DetectorContext, DetectorState, DetectionResult
from metroliza.industrial.anomaly.detectors import (
    IQRDetector,
    MadZScoreDetector,
    RollingZScoreDetector,
    SpecLimitDetector,
    StaleSourceDetector,
)
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


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
    path = Path(input_file)
    if path.suffix.lower() != ".csv":
        raise ValueError("Replay MVP supports CSV input only.")
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(dict(row))
            if limit is not None and len(rows) >= int(limit):
                break
    return rows


def rows_to_samples(rows: Iterable[Mapping[str, Any]], request: ReplayRequest, signal_id: int) -> list[IndustrialSample]:
    samples: list[IndustrialSample] = []
    for row in rows:
        metric_raw = row.get(request.metric_column)
        event_time = str(row.get(request.event_time_column) or "").strip()
        record_key = str(row.get(request.record_key_column) or "").strip()
        if metric_raw in (None, "") or not event_time or not record_key:
            continue
        try:
            value = float(metric_raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        samples.append(
            IndustrialSample(
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
        )
    return samples


def _detector_instances(keys: Iterable[str]):
    instances = []
    for key in keys:
        normalized = str(key).strip().lower()
        if not normalized:
            continue
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
        else:
            raise ValueError(f"Unsupported detector: {key}")
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
) -> list[DetectionResult]:
    detector_objects = _detector_instances(detectors)
    states: dict[str, DetectorState] = {}
    events: list[DetectionResult] = []
    for sample in sorted(_unique_samples_for_detection(samples), key=_sample_sort_key):
        for detector in detector_objects:
            state = states.get(detector.detector_key, DetectorState())
            context = DetectorContext(
                signal=signal,
                baseline=dict(baseline or {}),
                state=state,
                now=now,
            )
            result = detector.score_one(sample, context)
            if result is not None:
                events.append(result)
            states[detector.detector_key] = detector.update_one(sample, context)
    return events


def replay_industrial_stream(request: ReplayRequest) -> ReplaySummary:
    rows = load_csv_rows(request.input_file, limit=request.limit)
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
    samples = rows_to_samples(rows, request, signal.id)
    if request.dry_run:
        persisted_samples = samples
        inserted = 0
        skipped = 0
    else:
        batch_result = sample_repository.insert_samples(samples)
        inserted = batch_result.inserted
        skipped = batch_result.skipped
        loaded_by_id = {
            sample.id: sample
            for sample in sample_repository.list_samples(signal_id=signal.id)
            if sample.id is not None
        }
        persisted_samples = [loaded_by_id[sample_id] for sample_id in batch_result.sample_ids]

    events = run_detectors_for_samples(
        persisted_samples,
        signal=signal,
        detectors=request.detectors,
        baseline={},
    )
    created = 0
    event_counts: dict[str, int] = {}
    if not request.dry_run and events:
        event_result = AnomalyEventRepository(request.database).insert_events(events)
        created = event_result.inserted
        for event in events:
            key = f"{event.detector_key}/{event.severity}"
            event_counts[key] = event_counts.get(key, 0) + 1
    else:
        for event in events:
            key = f"{event.detector_key}/{event.severity}"
            event_counts[key] = event_counts.get(key, 0) + 1

    return ReplaySummary(
        samples_processed=len(samples),
        samples_inserted=inserted,
        samples_skipped=skipped,
        detector_events_created=created,
        event_counts=event_counts,
    )


def _signal_attr(signal: SignalDefinition | None, name: str) -> Any:
    return getattr(signal, name) if signal is not None else None

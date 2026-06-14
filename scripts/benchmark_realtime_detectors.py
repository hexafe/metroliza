#!/usr/bin/env python3
"""Benchmark deterministic realtime industrial detector throughput."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter

from metroliza.industrial.anomaly.contracts import Detector, DetectorContext, DetectorState
from metroliza.industrial.anomaly.detectors import (
    IQRDetector,
    MadZScoreDetector,
    RollingZScoreDetector,
    SpecLimitDetector,
    StaleSourceDetector,
)
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


DEFAULT_SIZES = (1_000, 10_000, 100_000)
DEFAULT_DETECTORS = (
    "spec_limits",
    "iqr",
    "mad_zscore",
    "rolling_zscore",
    "stale_source",
)

BASELINE = {
    "n": 500,
    "q1": 9.85,
    "q3": 10.15,
    "iqr": 0.30,
    "median": 10.0,
    "mad": 0.10,
}

DETECTOR_FACTORIES: Mapping[str, Callable[[], Detector]] = {
    "spec_limits": SpecLimitDetector,
    "iqr": IQRDetector,
    "mad_zscore": MadZScoreDetector,
    "rolling_zscore": RollingZScoreDetector,
    "stale_source": StaleSourceDetector,
}


@dataclass(frozen=True)
class DetectorTiming:
    detector_key: str
    seconds: float
    event_count: int
    event_counts: Mapping[str, int]

    def samples_per_second(self, sample_count: int) -> float:
        return _safe_rate(sample_count, self.seconds)

    def events_per_second(self) -> float:
        return _safe_rate(self.event_count, self.seconds)


@dataclass(frozen=True)
class BenchmarkResult:
    sample_count: int
    detector_timings: tuple[DetectorTiming, ...]

    @property
    def seconds(self) -> float:
        return sum(timing.seconds for timing in self.detector_timings)

    @property
    def event_count(self) -> int:
        return sum(timing.event_count for timing in self.detector_timings)

    @property
    def event_counts(self) -> Mapping[str, int]:
        counts: Counter[str] = Counter()
        for timing in self.detector_timings:
            counts.update(timing.event_counts)
        return dict(sorted(counts.items()))

    def samples_per_second(self) -> float:
        return _safe_rate(self.sample_count, self.seconds)

    def detector_calls_per_second(self) -> float:
        calls = self.sample_count * len(self.detector_timings)
        return _safe_rate(calls, self.seconds)

    def events_per_second(self) -> float:
        return _safe_rate(self.event_count, self.seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        default=",".join(str(size) for size in DEFAULT_SIZES),
        help="Comma-separated sample counts to benchmark. Default: 1000,10000,100000.",
    )
    parser.add_argument(
        "--detectors",
        default=",".join(DEFAULT_DETECTORS),
        help=(
            "Comma-separated detector keys. Default: "
            f"{','.join(DEFAULT_DETECTORS)}."
        ),
    )
    return parser


def run_benchmark(
    *,
    sizes: Iterable[int],
    detector_keys: Iterable[str],
) -> tuple[BenchmarkResult, ...]:
    keys = tuple(_normalize_detector_keys(detector_keys))
    _warm_detector_paths(keys)
    results: list[BenchmarkResult] = []
    for size in sizes:
        samples = _build_samples(size)
        timings = tuple(_benchmark_detector(key, samples) for key in keys)
        results.append(BenchmarkResult(sample_count=size, detector_timings=timings))
    return tuple(results)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sizes = tuple(_parse_sizes(args.sizes))
    detector_keys = tuple(_parse_csv(args.detectors))
    results = run_benchmark(sizes=sizes, detector_keys=detector_keys)
    _print_results(results, detector_keys=tuple(_normalize_detector_keys(detector_keys)))
    return 0


def _benchmark_detector(detector_key: str, samples: tuple[IndustrialSample, ...]) -> DetectorTiming:
    detector = DETECTOR_FACTORIES[detector_key]()
    signal = _signal_definition()
    baseline = BASELINE
    state = DetectorState()
    event_counts: Counter[str] = Counter()

    started = perf_counter()
    for sample in samples:
        context = DetectorContext(
            signal=signal,
            baseline=baseline,
            state=state,
            now=sample.event_time if detector_key == "stale_source" else None,
        )
        result = detector.score_one(sample, context)
        if result is not None:
            event_counts[f"{result.detector_key}/{result.severity}"] += 1
        state = detector.update_one(sample, context)
    elapsed = perf_counter() - started

    return DetectorTiming(
        detector_key=detector_key,
        seconds=elapsed,
        event_count=sum(event_counts.values()),
        event_counts=dict(sorted(event_counts.items())),
    )


def _build_samples(sample_count: int) -> tuple[IndustrialSample, ...]:
    base_time = datetime(2026, 6, 13, tzinfo=timezone.utc)
    return tuple(_sample(index, base_time=base_time) for index in range(sample_count))


def _sample(index: int, *, base_time: datetime) -> IndustrialSample:
    event_time = (base_time + timedelta(seconds=index)).isoformat().replace("+00:00", "Z")
    sample_id = index + 1
    return IndustrialSample(
        id=sample_id,
        source_profile_id=1,
        signal_id=101,
        source_record_key=f"SYN-{sample_id}",
        event_time=event_time,
        metric_name="cycle_time_s",
        value=_synthetic_value(index),
        reference="BENCH",
        station="SYNTHETIC",
        line="L1",
    )


def _synthetic_value(index: int) -> float:
    if index > 0 and index % 3_899 == 0:
        return 7.60
    if index > 0 and index % 997 == 0:
        return 12.80
    if index > 0 and index % 503 == 0:
        return 10.75
    return 10.0 + ((((index * 17) % 41) - 20) * 0.01)


def _signal_definition() -> SignalDefinition:
    return SignalDefinition(
        id=101,
        source_profile_id=1,
        signal_key="cycle_time",
        metric_name="cycle_time_s",
        unit="s",
        nominal=10.0,
        lsl=8.0,
        usl=12.0,
        lower_warning=9.5,
        upper_warning=10.5,
    )


def _warm_detector_paths(detector_keys: tuple[str, ...]) -> None:
    samples = _build_samples(256)
    for key in detector_keys:
        _benchmark_detector(key, samples)


def _parse_sizes(raw: str) -> tuple[int, ...]:
    sizes: list[int] = []
    for part in _parse_csv(raw):
        try:
            size = int(part)
        except ValueError as exc:
            raise SystemExit(f"Invalid benchmark size: {part!r}") from exc
        if size <= 0:
            raise SystemExit(f"Benchmark sizes must be positive: {part!r}")
        sizes.append(size)
    if not sizes:
        raise SystemExit("At least one benchmark size is required.")
    return tuple(sizes)


def _parse_csv(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _normalize_detector_keys(detector_keys: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for key in detector_keys:
        detector_key = key.strip().lower()
        if not detector_key:
            continue
        if detector_key not in DETECTOR_FACTORIES:
            supported = ", ".join(sorted(DETECTOR_FACTORIES))
            raise SystemExit(f"Unsupported detector {key!r}. Supported: {supported}.")
        normalized.append(detector_key)
    if not normalized:
        raise SystemExit("At least one detector is required.")
    return tuple(normalized)


def _print_results(
    results: tuple[BenchmarkResult, ...],
    *,
    detector_keys: tuple[str, ...],
) -> None:
    print("Metroliza realtime detector benchmark")
    print("Synthetic samples are prebuilt; timings cover DetectorContext + score/update.")
    print(f"Detectors: {', '.join(_normalize_detector_keys(detector_keys))}")
    print()

    for result in results:
        print(f"size: {result.sample_count:,} samples")
        print(f"  total_seconds: {result.seconds:.6f}")
        print(f"  samples/sec: {_format_rate(result.samples_per_second())}")
        print(f"  detector_calls/sec: {_format_rate(result.detector_calls_per_second())}")
        print(f"  events/sec: {_format_rate(result.events_per_second())}")
        print(f"  events: {result.event_count:,}")
        print(f"  event_counts: {_format_event_counts(result.event_counts)}")
        print("  per_detector:")
        print(
            "    "
            f"{'detector':<16} {'seconds':>10} {'samples/sec':>13} "
            f"{'events':>8} {'events/sec':>12} {'share':>8}"
        )
        for timing in result.detector_timings:
            share = _safe_rate(timing.seconds * 100.0, result.seconds)
            print(
                "    "
                f"{timing.detector_key:<16} "
                f"{timing.seconds:>10.6f} "
                f"{_format_rate(timing.samples_per_second(result.sample_count)):>13} "
                f"{timing.event_count:>8,} "
                f"{_format_rate(timing.events_per_second()):>12} "
                f"{share:>7.1f}%"
            )
        print()


def _format_event_counts(event_counts: Mapping[str, int]) -> str:
    if not event_counts:
        return "none"
    return ", ".join(f"{key}={value:,}" for key, value in event_counts.items())


def _format_rate(value: float) -> str:
    if value >= 100:
        return f"{value:,.0f}"
    if value >= 10:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def _safe_rate(numerator: float, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return numerator / seconds


if __name__ == "__main__":
    raise SystemExit(main())

"""Dependency-free feature extraction for industrial anomaly models."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from statistics import fmean, median

from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


@dataclass(frozen=True)
class IndustrialSampleFeatures:
    """Deterministic numeric features derived from one sample and prior history."""

    raw_value: float
    deviation_from_nominal: float | None
    tolerance_band_percent: float | None
    rolling_mean: float | None
    rolling_std: float | None
    rolling_median: float | None
    rolling_mad: float | None
    delta_from_previous: float | None
    seconds_since_previous: float | None


def extract_sample_features(
    sample: IndustrialSample,
    previous_samples: Iterable[IndustrialSample] = (),
    *,
    signal: SignalDefinition | None = None,
    window_size: int | None = None,
) -> IndustrialSampleFeatures:
    """Return features for ``sample`` using only samples that came before it."""

    value = _finite_float(sample.value, field_name="sample.value")
    previous = _previous_window(tuple(previous_samples), window_size)
    previous_values = tuple(
        parsed
        for parsed in (_finite_float_or_none(item.value) for item in previous)
        if parsed is not None
    )
    previous_value = _finite_float_or_none(previous[-1].value) if previous else None

    return IndustrialSampleFeatures(
        raw_value=value,
        deviation_from_nominal=_deviation_from_nominal(value, signal),
        tolerance_band_percent=_tolerance_band_percent(value, signal),
        rolling_mean=_mean(previous_values),
        rolling_std=_population_std(previous_values),
        rolling_median=_median(previous_values),
        rolling_mad=_mad(previous_values),
        delta_from_previous=value - previous_value if previous_value is not None else None,
        seconds_since_previous=_seconds_since_previous(sample, previous[-1] if previous else None),
    )


def extract_history_features(
    samples: Iterable[IndustrialSample],
    *,
    signal: SignalDefinition | None = None,
    window_size: int | None = None,
) -> tuple[IndustrialSampleFeatures, ...]:
    """Return per-sample features, preserving input order and using prior samples only."""

    history: list[IndustrialSample] = []
    features: list[IndustrialSampleFeatures] = []
    for sample in samples:
        features.append(
            extract_sample_features(sample, history, signal=signal, window_size=window_size)
        )
        history.append(sample)
    return tuple(features)


def _previous_window(
    previous_samples: Sequence[IndustrialSample],
    window_size: int | None,
) -> tuple[IndustrialSample, ...]:
    if window_size is None:
        return tuple(previous_samples)
    if window_size < 1:
        raise ValueError("window_size must be positive")
    return tuple(previous_samples[-window_size:])


def _deviation_from_nominal(value: float, signal: SignalDefinition | None) -> float | None:
    if signal is None:
        return None
    nominal = _finite_float_or_none(signal.nominal)
    return value - nominal if nominal is not None else None


def _tolerance_band_percent(value: float, signal: SignalDefinition | None) -> float | None:
    if signal is None:
        return None
    lower = _finite_float_or_none(signal.lsl)
    upper = _finite_float_or_none(signal.usl)
    if lower is None or upper is None or upper <= lower or math.isclose(lower, upper):
        return None
    return ((value - lower) / (upper - lower)) * 100.0


def _mean(values: Sequence[float]) -> float | None:
    return fmean(values) if values else None


def _population_std(values: Sequence[float]) -> float | None:
    if not values:
        return None
    mean_value = fmean(values)
    return math.sqrt(fmean(tuple((value - mean_value) ** 2 for value in values)))


def _median(values: Sequence[float]) -> float | None:
    return float(median(values)) if values else None


def _mad(values: Sequence[float]) -> float | None:
    if not values:
        return None
    median_value = float(median(values))
    deviations = tuple(abs(value - median_value) for value in values)
    return float(median(deviations))


def _seconds_since_previous(
    sample: IndustrialSample,
    previous_sample: IndustrialSample | None,
) -> float | None:
    if previous_sample is None:
        return None
    current_time = _parse_utc_timestamp(sample.event_time)
    previous_time = _parse_utc_timestamp(previous_sample.event_time)
    return (current_time - previous_time).total_seconds()


def _parse_utc_timestamp(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _finite_float_or_none(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _finite_float(value: object, *, field_name: str) -> float:
    parsed = _finite_float_or_none(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be a finite number")
    return parsed

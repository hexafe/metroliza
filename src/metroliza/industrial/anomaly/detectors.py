"""Pure deterministic realtime industrial anomaly detectors."""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import fmean, pstdev
from typing import Any

from metroliza.industrial.anomaly.contracts import (
    DetectionResult,
    DetectorContext,
    DetectorState,
)
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition
from metroliza.industrial.realtime.timestamps import parse_utc_timestamp


def _finite_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _signal_id(sample: IndustrialSample, signal: SignalDefinition | None) -> int:
    if signal is not None and signal.id is not None:
        return int(signal.id)
    return int(sample.signal_id)


def _signal_key(signal: SignalDefinition | None) -> str | None:
    return signal.signal_key if signal is not None else None


def _result(
    *,
    detector_key: str,
    sample: IndustrialSample,
    context: DetectorContext,
    severity: str,
    score: float,
    expected_value: float | None,
    threshold: dict[str, Any],
    explanation: str,
    extra_context: dict[str, Any] | None = None,
) -> DetectionResult:
    return DetectionResult(
        detector_key=detector_key,
        sample_id=sample.id,
        signal_id=_signal_id(sample, context.signal),
        signal_key=_signal_key(context.signal),
        event_time=sample.event_time,
        severity=severity,
        score=float(score),
        observed_value=float(sample.value),
        expected_value=expected_value,
        threshold=threshold,
        explanation=explanation,
        context=extra_context or {},
    )


@dataclass(frozen=True)
class SpecLimitDetector:
    detector_key: str = "spec_limits"
    warning_severity: str = "warning"

    def score_one(
        self,
        sample: IndustrialSample,
        context: DetectorContext,
    ) -> DetectionResult | None:
        signal = context.signal
        if signal is None:
            return None
        value = _finite_float_or_none(sample.value)
        if value is None:
            return None
        thresholds = {
            "lsl": signal.lsl,
            "usl": signal.usl,
            "lower_warning": signal.lower_warning,
            "upper_warning": signal.upper_warning,
        }
        if signal.lsl is not None and value < signal.lsl:
            return _result(
                detector_key=self.detector_key,
                sample=sample,
                context=context,
                severity="critical",
                score=abs(value - signal.lsl),
                expected_value=signal.nominal,
                threshold=thresholds,
                explanation=f"Observed value {value:g} is below LSL {signal.lsl:g}.",
            )
        if signal.usl is not None and value > signal.usl:
            return _result(
                detector_key=self.detector_key,
                sample=sample,
                context=context,
                severity="critical",
                score=abs(value - signal.usl),
                expected_value=signal.nominal,
                threshold=thresholds,
                explanation=f"Observed value {value:g} is above USL {signal.usl:g}.",
            )
        if signal.lower_warning is not None and value < signal.lower_warning:
            return _result(
                detector_key=self.detector_key,
                sample=sample,
                context=context,
                severity=self.warning_severity,
                score=abs(value - signal.lower_warning),
                expected_value=signal.nominal,
                threshold=thresholds,
                explanation=f"Observed value {value:g} is below warning limit {signal.lower_warning:g}.",
            )
        if signal.upper_warning is not None and value > signal.upper_warning:
            return _result(
                detector_key=self.detector_key,
                sample=sample,
                context=context,
                severity=self.warning_severity,
                score=abs(value - signal.upper_warning),
                expected_value=signal.nominal,
                threshold=thresholds,
                explanation=f"Observed value {value:g} is above warning limit {signal.upper_warning:g}.",
            )
        return None

    def update_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectorState:
        return DetectorState(
            values=context.state.values,
            last_event_time=sample.event_time,
            last_sample_id=sample.id,
        )


@dataclass(frozen=True)
class IQRDetector:
    detector_key: str = "iqr"
    min_n: int = 20
    fence_multiplier: float = 1.5

    def score_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectionResult | None:
        baseline = context.baseline
        n = int(baseline.get("n") or 0)
        q1 = baseline.get("q1")
        q3 = baseline.get("q3")
        iqr = baseline.get("iqr")
        if n < self.min_n or q1 is None or q3 is None or not iqr:
            return None
        q1_value = _finite_float_or_none(q1)
        q3_value = _finite_float_or_none(q3)
        iqr_value = _finite_float_or_none(iqr)
        value = _finite_float_or_none(sample.value)
        if (
            q1_value is None
            or q3_value is None
            or iqr_value is None
            or iqr_value <= 0
            or q1_value > q3_value
            or value is None
        ):
            return None
        lower = q1_value - self.fence_multiplier * iqr_value
        upper = q3_value + self.fence_multiplier * iqr_value
        if lower <= value <= upper:
            return None
        distance = lower - value if value < lower else value - upper
        return _result(
            detector_key=self.detector_key,
            sample=sample,
            context=context,
            severity="major",
            score=distance / iqr_value,
            expected_value=(q1_value + q3_value) / 2.0,
            threshold={"lower_fence": lower, "upper_fence": upper, "iqr": iqr_value, "n": n},
            explanation=f"Observed value {value:g} is outside IQR fence [{lower:g}, {upper:g}].",
        )

    def update_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectorState:
        return DetectorState(
            values=context.state.values,
            last_event_time=sample.event_time,
            last_sample_id=sample.id,
        )


@dataclass(frozen=True)
class MadZScoreDetector:
    detector_key: str = "mad_zscore"
    min_n: int = 20
    threshold: float = 3.5

    def score_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectionResult | None:
        baseline = context.baseline
        n = int(baseline.get("n") or 0)
        median = baseline.get("median")
        mad = baseline.get("mad")
        if n < self.min_n or median is None or not mad:
            return None
        median_value = _finite_float_or_none(median)
        mad_value = _finite_float_or_none(mad)
        value = _finite_float_or_none(sample.value)
        if median_value is None or mad_value is None or mad_value <= 0 or value is None:
            return None
        robust_z = 0.6745 * (value - median_value) / mad_value
        if abs(robust_z) < self.threshold:
            return None
        return _result(
            detector_key=self.detector_key,
            sample=sample,
            context=context,
            severity="major",
            score=abs(robust_z),
            expected_value=median_value,
            threshold={"robust_z": self.threshold, "median": median_value, "mad": mad_value, "n": n},
            explanation=f"Observed value {value:g} has robust z-score {robust_z:.2f}.",
            extra_context={"robust_z": robust_z},
        )

    def update_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectorState:
        return DetectorState(
            values=context.state.values,
            last_event_time=sample.event_time,
            last_sample_id=sample.id,
        )


@dataclass(frozen=True)
class RollingZScoreDetector:
    detector_key: str = "rolling_zscore"
    min_n: int = 30
    threshold: float = 3.0
    max_window: int = 500

    def score_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectionResult | None:
        values = tuple(_finite_float_or_none(value) for value in context.state.values)
        if any(value is None for value in values):
            return None
        finite_values = tuple(value for value in values if value is not None)
        if len(finite_values) < self.min_n:
            return None
        value = _finite_float_or_none(sample.value)
        if value is None:
            return None
        std = pstdev(finite_values)
        if math.isclose(std, 0.0):
            return None
        mean = fmean(finite_values)
        z_score = (value - mean) / std
        if abs(z_score) < self.threshold:
            return None
        return _result(
            detector_key=self.detector_key,
            sample=sample,
            context=context,
            severity="major",
            score=abs(z_score),
            expected_value=mean,
            threshold={"z": self.threshold, "mean": mean, "std": std, "n": len(finite_values)},
            explanation=f"Observed value {value:g} has rolling z-score {z_score:.2f}.",
            extra_context={"z_score": z_score},
        )

    def update_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectorState:
        value = _finite_float_or_none(sample.value)
        if value is None:
            return context.state
        values = (*context.state.values, value)[-self.max_window :]
        return DetectorState(
            values=values,
            last_event_time=sample.event_time,
            last_sample_id=sample.id,
        )


@dataclass(frozen=True)
class StaleSourceDetector:
    detector_key: str = "stale_source"
    warning_seconds: float = 300.0
    major_seconds: float = 900.0

    def score_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectionResult | None:
        if sample.id is None:
            return None
        now_text = context.now
        if not now_text:
            return None
        last_time = parse_utc_timestamp(sample.event_time)
        now = parse_utc_timestamp(now_text)
        stale_seconds = max(0.0, (now - last_time).total_seconds())
        if stale_seconds < self.warning_seconds:
            return None
        severity = "major" if stale_seconds >= self.major_seconds else "warning"
        threshold = {"warning_seconds": self.warning_seconds, "major_seconds": self.major_seconds}
        return _result(
            detector_key=self.detector_key,
            sample=sample,
            context=context,
            severity=severity,
            score=stale_seconds,
            expected_value=0.0,
            threshold=threshold,
            explanation=(
                f"No new samples for {stale_seconds:.0f} seconds since {sample.event_time}."
            ),
            extra_context={
                "source_level": True,
                "last_sample_id": sample.id,
                "last_event_time": sample.event_time,
                "now": now_text,
                "stale_seconds": stale_seconds,
            },
        )

    def update_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectorState:
        return DetectorState(
            values=context.state.values,
            last_event_time=sample.event_time,
            last_sample_id=sample.id,
        )

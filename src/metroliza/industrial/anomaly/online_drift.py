"""Dependency-light online drift detectors for realtime industrial samples."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import importlib.util
import math
from statistics import fmean
from typing import Any, Iterable, Mapping

from metroliza.industrial.anomaly.contracts import (
    DetectionResult,
    DetectorContext,
    DetectorState,
)
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


def _finite_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _finite_history(values: Iterable[float]) -> tuple[float, ...]:
    finite_values: list[float] = []
    for value in values:
        parsed = _finite_float_or_none(value)
        if parsed is None:
            return ()
        finite_values.append(parsed)
    return tuple(finite_values)


def _signal_id(sample: IndustrialSample, signal: SignalDefinition | None) -> int:
    if signal is not None and signal.id is not None:
        return int(signal.id)
    return int(sample.signal_id)


def _signal_key(signal: SignalDefinition | None) -> str | None:
    return signal.signal_key if signal is not None else None


def _metric_label(sample: IndustrialSample, signal: SignalDefinition | None) -> str:
    if signal is not None and signal.metric_name:
        return signal.metric_name
    return sample.metric_name


def _detection_result(
    *,
    detector_key: str,
    sample: IndustrialSample,
    context: DetectorContext,
    severity: str,
    score: float,
    expected_value: float | None,
    threshold: Mapping[str, Any],
    explanation: str,
    extra_context: Mapping[str, Any],
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
        context=extra_context,
    )


@dataclass(frozen=True)
class PageHinkleyState:
    """Compact serializable state for two-sided Page-Hinkley drift tracking."""

    n: int = 0
    mean: float = 0.0
    upward_sum: float = 0.0
    upward_min: float = 0.0
    downward_sum: float = 0.0
    downward_min: float = 0.0

    @classmethod
    def from_detector_state(cls, state: DetectorState) -> PageHinkleyState:
        values = _finite_history(state.values)
        if not values:
            return cls()
        if len(values) != 6:
            return cls()
        n = max(0, int(round(values[0])))
        return cls(
            n=n,
            mean=values[1],
            upward_sum=values[2],
            upward_min=values[3],
            downward_sum=values[4],
            downward_min=values[5],
        )

    def advance(self, value: float, *, delta: float) -> PageHinkleyState:
        n = self.n + 1
        mean = value if n == 1 else self.mean + ((value - self.mean) / n)
        upward_sum = self.upward_sum + value - mean - delta
        downward_sum = self.downward_sum + mean - value - delta
        return PageHinkleyState(
            n=n,
            mean=mean,
            upward_sum=upward_sum,
            upward_min=min(self.upward_min, upward_sum),
            downward_sum=downward_sum,
            downward_min=min(self.downward_min, downward_sum),
        )

    def to_detector_state(self, sample: IndustrialSample) -> DetectorState:
        return DetectorState(
            values=(
                float(self.n),
                self.mean,
                self.upward_sum,
                self.upward_min,
                self.downward_sum,
                self.downward_min,
            ),
            last_event_time=sample.event_time,
            last_sample_id=sample.id,
        )

    @property
    def upward_score(self) -> float:
        return max(0.0, self.upward_sum - self.upward_min)

    @property
    def downward_score(self) -> float:
        return max(0.0, self.downward_sum - self.downward_min)


@dataclass(frozen=True)
class PageHinkleyOnlineDriftDetector:
    """Explainable, dependency-free online drift detector for numeric samples."""

    detector_key: str = "online_drift"
    min_n: int = 30
    delta: float = 0.05
    info_threshold: float = 20.0
    warning_threshold: float = 50.0
    info_severity: str = "info"
    warning_severity: str = "warning"

    def score_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectionResult | None:
        value = _finite_float_or_none(sample.value)
        if value is None:
            return None

        state = PageHinkleyState.from_detector_state(context.state)
        if state.n < self.min_n:
            return None

        next_state = state.advance(value, delta=self.delta)
        upward_score = next_state.upward_score
        downward_score = next_state.downward_score
        score = max(upward_score, downward_score)
        if score < self.info_threshold:
            return None

        direction = "upward" if upward_score >= downward_score else "downward"
        threshold_value = self.warning_threshold
        severity = self.warning_severity
        if score < self.warning_threshold:
            threshold_value = self.info_threshold
            severity = self.info_severity

        metric = _metric_label(sample, context.signal)
        article = "an" if direction == "upward" else "a"
        explanation = (
            f"Online drift detector saw {article} {direction} process shift for {metric}: "
            f"value {value:g} compared with running mean {state.mean:g}; cumulative "
            f"shift score {score:.2f} reached {severity} threshold {threshold_value:g}."
        )
        threshold = {
            "algorithm": "page_hinkley",
            "min_n": self.min_n,
            "delta": self.delta,
            "info_threshold": self.info_threshold,
            "warning_threshold": self.warning_threshold,
        }
        return _detection_result(
            detector_key=self.detector_key,
            sample=sample,
            context=context,
            severity=severity,
            score=score,
            expected_value=state.mean if state.n else None,
            threshold=threshold,
            explanation=explanation,
            extra_context={
                "algorithm": "page_hinkley",
                "direction": direction,
                "samples_seen": state.n,
                "samples_after_update": next_state.n,
                "mean_before": state.mean,
                "mean_after": next_state.mean,
                "upward_score": upward_score,
                "downward_score": downward_score,
            },
        )

    def update_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectorState:
        value = _finite_float_or_none(sample.value)
        if value is None:
            return context.state
        state = PageHinkleyState.from_detector_state(context.state)
        return state.advance(value, delta=self.delta).to_detector_state(sample)


class RiverUnavailableError(RuntimeError):
    """Raised when the optional River drift backend is requested but unavailable."""


def river_available() -> bool:
    """Return whether River can be imported without importing it at module load time."""

    return importlib.util.find_spec("river") is not None


def _load_river_detector_class(module_name: str, class_name: str) -> type[Any]:
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RiverUnavailableError(
            "River is required for RiverOnlineDriftDetector but is not installed."
        ) from exc
    try:
        detector_class = getattr(module, class_name)
    except AttributeError as exc:
        raise RiverUnavailableError(
            f"River detector {module_name}.{class_name} is not available."
        ) from exc
    return detector_class


def _river_update(detector: Any, value: float) -> Any:
    updated = detector.update(value)
    return detector if updated is None else updated


def _river_drift_detected(detector: Any) -> bool:
    detected = getattr(detector, "drift_detected", False)
    if callable(detected):
        detected = detected()
    return bool(detected)


@dataclass(frozen=True)
class RiverOnlineDriftDetector:
    """Optional River wrapper with lazy import and bounded replay state."""

    detector_key: str = "river_online_drift"
    detector_module: str = "river.drift"
    detector_class: str = "PageHinkley"
    detector_kwargs: Mapping[str, Any] = field(default_factory=dict)
    min_n: int = 30
    max_history: int = 1_000
    severity: str = "warning"

    def score_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectionResult | None:
        value = _finite_float_or_none(sample.value)
        history = _finite_history(context.state.values)
        if value is None or len(history) < self.min_n:
            return None

        detector_class = _load_river_detector_class(self.detector_module, self.detector_class)
        river_detector = detector_class(**dict(self.detector_kwargs))
        for history_value in history:
            river_detector = _river_update(river_detector, history_value)
        river_detector = _river_update(river_detector, value)
        if not _river_drift_detected(river_detector):
            return None

        metric = _metric_label(sample, context.signal)
        threshold = {
            "algorithm": "river",
            "detector": f"{self.detector_module}.{self.detector_class}",
            "min_n": self.min_n,
            "parameters": dict(self.detector_kwargs),
        }
        explanation = (
            f"River {self.detector_class} detected a process-distribution drift signal "
            f"for {metric}; review recent operating conditions before adjusting controls."
        )
        return _detection_result(
            detector_key=self.detector_key,
            sample=sample,
            context=context,
            severity=self.severity,
            score=1.0,
            expected_value=fmean(history),
            threshold=threshold,
            explanation=explanation,
            extra_context={
                "algorithm": "river",
                "river_detector": self.detector_class,
                "history_n": len(history),
                "optional_dependency": "river",
            },
        )

    def update_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectorState:
        value = _finite_float_or_none(sample.value)
        if value is None:
            return context.state
        history = (*_finite_history(context.state.values), value)[-self.max_history :]
        return DetectorState(
            values=history,
            last_event_time=sample.event_time,
            last_sample_id=sample.id,
        )

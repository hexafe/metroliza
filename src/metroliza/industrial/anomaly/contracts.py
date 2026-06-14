"""Contracts for deterministic industrial anomaly detectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition

ANOMALY_SEVERITIES = ("info", "warning", "major", "critical")


@dataclass(frozen=True)
class DetectionResult:
    """Explainable detector output suitable for operator review and persistence."""

    detector_key: str
    event_time: str
    severity: str
    score: float
    observed_value: float
    expected_value: float | None
    threshold: Mapping[str, Any]
    explanation: str
    context: Mapping[str, Any] = field(default_factory=dict)
    signal_id: int | None = None
    signal_key: str | None = None
    sample_id: int | None = None


@dataclass(frozen=True)
class DetectorState:
    """Explicit detector state passed through pure scoring/update calls."""

    values: tuple[float, ...] = ()
    last_event_time: str | None = None
    last_sample_id: int | None = None


@dataclass(frozen=True)
class DetectorConfig:
    """Persistable detector configuration for one deterministic detector."""

    detector_key: str
    detector_type: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    severity_map: Mapping[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class DetectorContext:
    """Static and stateful context used by pure detector calls."""

    signal: SignalDefinition | None = None
    baseline: Mapping[str, Any] = field(default_factory=dict)
    state: DetectorState = field(default_factory=DetectorState)
    now: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)


class Detector(Protocol):
    """Protocol implemented by deterministic realtime anomaly detectors."""

    detector_key: str

    def score_one(
        self,
        sample: IndustrialSample,
        context: DetectorContext,
    ) -> DetectionResult | None:
        """Score a sample before any state update."""

    def update_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectorState:
        """Return updated detector state after scoring."""

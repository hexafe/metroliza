"""Optional scikit-learn Isolation Forest detector for industrial samples."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from metroliza.industrial.anomaly.contracts import (
    DetectionResult,
    DetectorContext,
    DetectorState,
)
from metroliza.industrial.anomaly.model_registry import (
    ModelArtifact,
    ModelArtifactRegistry,
    UnsafeModelArtifactError,
)
from metroliza.industrial.anomaly.optional_dependencies import load_sklearn_ensemble
from metroliza.industrial.realtime.stream_contracts import IndustrialSample


MODEL_TYPE = "sklearn_isolation_forest"
DEFAULT_DETECTOR_KEY = "isolation_forest"


class OptionalDependencyMissingError(RuntimeError):
    """Raised when optional ML scoring is requested without scikit-learn installed."""


@dataclass(frozen=True)
class IsolationForestModelSpec:
    """Training and safety settings for one optional Isolation Forest artifact."""

    artifact_key: str
    detector_key: str = DEFAULT_DETECTOR_KEY
    signal_id: int | None = None
    contamination: float | str = "auto"
    n_estimators: int = 100
    max_samples: int | float | str = "auto"
    random_state: int | None = 0
    min_samples: int = 20
    score_threshold: float = 0.0
    major_score: float = 0.05
    critical_score: float = 0.15
    shadow_mode: bool = True
    calibrated: bool = False
    critical_allowed: bool = False


@dataclass(frozen=True)
class IsolationForestTrainingResult:
    """Result returned after fitting and registering an Isolation Forest artifact."""

    artifact: ModelArtifact
    feature_names: tuple[str, ...]
    sample_count: int


@dataclass(frozen=True)
class IsolationForestAnomalyDetector:
    """Score samples with a registered Isolation Forest model artifact."""

    model: Any
    artifact: ModelArtifact
    feature_names: tuple[str, ...] = ("value",)
    detector_key: str = DEFAULT_DETECTOR_KEY

    def score_one(
        self,
        sample: IndustrialSample,
        context: DetectorContext,
    ) -> DetectionResult | None:
        value = _finite_float_or_none(sample.value)
        if value is None:
            return None
        decision_score = _decision_score(self.model, [[value]])
        prediction = _prediction(self.model, [[value]], decision_score)
        anomaly_score = max(0.0, -decision_score)
        parameters = _merged_parameters(self.artifact, context)
        score_threshold = _float_parameter(parameters, "score_threshold", 0.0)
        if prediction != -1 and anomaly_score <= score_threshold:
            return None
        if anomaly_score <= score_threshold:
            return None

        severity = _ml_severity(
            anomaly_score=anomaly_score,
            parameters=parameters,
            artifact=self.artifact,
        )
        expected_value = _finite_float_or_none(self.artifact.metrics.get("training_mean"))
        threshold = {
            "decision_threshold": score_threshold,
            "major_score": _float_parameter(parameters, "major_score", 0.05),
            "critical_score": _float_parameter(parameters, "critical_score", 0.15),
            "shadow_mode": self.artifact.shadow_mode,
            "calibrated": self.artifact.calibrated,
            "critical_allowed": self.artifact.critical_allowed,
        }
        return DetectionResult(
            detector_key=str(parameters.get("detector_key") or self.detector_key),
            sample_id=sample.id,
            signal_id=_signal_id(sample, context),
            signal_key=context.signal.signal_key if context.signal is not None else None,
            event_time=sample.event_time,
            severity=severity,
            score=anomaly_score,
            observed_value=value,
            expected_value=expected_value,
            threshold=threshold,
            explanation=(
                f"Isolation Forest flagged value {value:g} "
                f"with anomaly score {anomaly_score:.4f}."
            ),
            context={
                "model_artifact_id": self.artifact.id,
                "artifact_key": self.artifact.artifact_key,
                "model_type": self.artifact.model_type,
                "prediction": prediction,
                "decision_score": decision_score,
                "shadow_mode": self.artifact.shadow_mode,
                "calibrated": self.artifact.calibrated,
                "critical_allowed": self.artifact.critical_allowed,
                "feature_names": self.feature_names,
            },
        )

    def update_one(self, sample: IndustrialSample, context: DetectorContext) -> DetectorState:
        return DetectorState(
            values=context.state.values,
            last_event_time=sample.event_time,
            last_sample_id=sample.id,
        )


def sklearn_isolation_forest_available() -> bool:
    """Return True when scikit-learn's IsolationForest can be imported lazily."""

    return _load_sklearn_isolation_forest_class() is not None


def train_isolation_forest_model(
    samples: Iterable[IndustrialSample],
    registry: ModelArtifactRegistry,
    spec: IsolationForestModelSpec,
) -> IsolationForestTrainingResult:
    """Reject pickle-backed training until a safe serializer is adopted."""

    del samples, registry, spec
    raise UnsafeModelArtifactError(
        "Isolation Forest training is disabled because the legacy artifact format used pickle. "
        "A safe serializer must be adopted before training is re-enabled."
    )


def load_isolation_forest_detector(
    registry: ModelArtifactRegistry,
    *,
    artifact_id: int | None = None,
    artifact_key: str | None = None,
) -> IsolationForestAnomalyDetector:
    """Load a registered Isolation Forest model artifact for scoring."""

    if artifact_id is None and artifact_key is None:
        raise ValueError("artifact_id or artifact_key is required")
    artifact = (
        registry.get_artifact(artifact_id)
        if artifact_id is not None
        else registry.latest_artifact(artifact_key=artifact_key, model_type=MODEL_TYPE)
    )
    if artifact is None:
        raise FileNotFoundError("Isolation Forest model artifact is not registered")
    registry.archive_artifact(artifact)
    raise UnsafeModelArtifactError(
        "Isolation Forest artifact loading is disabled because legacy artifacts use pickle. "
        "The artifact was archived without deserializing it."
    )


def _load_sklearn_isolation_forest_class():
    try:
        ensemble = load_sklearn_ensemble()
    except ImportError:
        return None
    return getattr(ensemble, "IsolationForest", None)


def _feature_rows(samples: Iterable[IndustrialSample]) -> list[list[float]]:
    rows: list[list[float]] = []
    for sample in samples:
        value = _finite_float_or_none(sample.value)
        if value is not None:
            rows.append([value])
    return rows


def _decision_score(model: Any, feature_rows: list[list[float]]) -> float:
    if not hasattr(model, "decision_function"):
        raise ValueError("Isolation Forest model must provide decision_function")
    score = model.decision_function(feature_rows)[0]
    return float(score)


def _prediction(model: Any, feature_rows: list[list[float]], decision_score: float) -> int:
    if hasattr(model, "predict"):
        return int(model.predict(feature_rows)[0])
    return -1 if decision_score < 0 else 1


def _merged_parameters(
    artifact: ModelArtifact,
    context: DetectorContext,
) -> dict[str, Any]:
    parameters = dict(artifact.parameters)
    parameters.update(dict(context.parameters))
    return parameters


def _ml_severity(
    *,
    anomaly_score: float,
    parameters: Mapping[str, Any],
    artifact: ModelArtifact,
) -> str:
    if artifact.shadow_mode:
        return "info"
    major_score = _float_parameter(parameters, "major_score", 0.05)
    critical_score = _float_parameter(parameters, "critical_score", 0.15)
    if anomaly_score >= critical_score:
        if artifact.calibrated and artifact.critical_allowed:
            return "critical"
        return "major"
    if anomaly_score >= major_score:
        return "major"
    return "warning"


def _float_parameter(parameters: Mapping[str, Any], key: str, default: float) -> float:
    value = _finite_float_or_none(parameters.get(key))
    return default if value is None else value


def _finite_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _signal_id(sample: IndustrialSample, context: DetectorContext) -> int | None:
    if context.signal is not None and context.signal.id is not None:
        return int(context.signal.id)
    return int(sample.signal_id) if sample.signal_id is not None else None

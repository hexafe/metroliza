from dataclasses import replace

import pytest

from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.isolation_forest import (
    IsolationForestAnomalyDetector,
    IsolationForestModelSpec,
    OptionalDependencyMissingError,
    load_isolation_forest_detector,
    sklearn_isolation_forest_available,
    train_isolation_forest_model,
)
from metroliza.industrial.anomaly.model_registry import ModelArtifact, ModelArtifactRegistry
from metroliza.industrial.realtime.stream_contracts import IndustrialSample


class _AlwaysOutlierModel:
    def decision_function(self, _rows):
        return [-1.25]

    def predict(self, _rows):
        return [-1]


def _sample(value: float, *, sample_id: int = 1) -> IndustrialSample:
    return IndustrialSample(
        id=sample_id,
        source_profile_id=1,
        signal_id=7,
        source_record_key=f"ROW-{sample_id}",
        event_time=f"2026-06-13T10:{sample_id:02d}:00Z",
        metric_name="cycle_time_s",
        value=value,
    )


def _artifact(**overrides) -> ModelArtifact:
    artifact = ModelArtifact(
        id=12,
        artifact_key="cycle_time",
        model_type="sklearn_isolation_forest",
        artifact_path="/tmp/cycle_time.pkl",
        checksum_sha256="0" * 64,
        parameters={"score_threshold": 0.0, "major_score": 0.1, "critical_score": 0.2},
        metrics={"training_mean": 10.0},
    )
    return replace(artifact, **overrides)


def test_isolation_forest_spec_defaults_to_shadow_mode():
    spec = IsolationForestModelSpec(artifact_key="cycle_time")

    assert spec.shadow_mode is True
    assert spec.calibrated is False
    assert spec.critical_allowed is False
    assert isinstance(sklearn_isolation_forest_available(), bool)


def test_isolation_forest_shadow_mode_emits_info_with_model_context():
    detector = IsolationForestAnomalyDetector(
        model=_AlwaysOutlierModel(),
        artifact=_artifact(shadow_mode=True, calibrated=True, critical_allowed=True),
    )

    result = detector.score_one(_sample(25.0), DetectorContext())

    assert result is not None
    assert result.severity == "info"
    assert result.context["shadow_mode"] is True
    assert result.context["model_artifact_id"] == 12
    assert result.expected_value == 10.0


def test_isolation_forest_never_returns_critical_without_calibration_and_allow_flag():
    detector = IsolationForestAnomalyDetector(
        model=_AlwaysOutlierModel(),
        artifact=_artifact(shadow_mode=False, calibrated=False, critical_allowed=False),
    )

    result = detector.score_one(_sample(25.0), DetectorContext())

    assert result is not None
    assert result.severity == "major"
    assert result.threshold["critical_allowed"] is False


def test_isolation_forest_can_return_critical_when_calibrated_and_allowed():
    detector = IsolationForestAnomalyDetector(
        model=_AlwaysOutlierModel(),
        artifact=_artifact(shadow_mode=False, calibrated=True, critical_allowed=True),
    )

    result = detector.score_one(_sample(25.0), DetectorContext())

    assert result is not None
    assert result.severity == "critical"


def test_train_reports_optional_dependency_when_sklearn_loader_missing(tmp_path, monkeypatch):
    from metroliza.industrial.anomaly import isolation_forest  # noqa: PLC0415

    monkeypatch.setattr(isolation_forest, "_load_sklearn_isolation_forest_class", lambda: None)
    registry = ModelArtifactRegistry(
        str(tmp_path / "models.db"),
        artifact_root=tmp_path / "artifacts",
    )

    with pytest.raises(OptionalDependencyMissingError, match="scikit-learn"):
        train_isolation_forest_model(
            [_sample(10.0, sample_id=index) for index in range(1, 25)],
            registry,
            IsolationForestModelSpec(artifact_key="cycle_time"),
        )


def test_train_and_score_isolation_forest_with_optional_sklearn(tmp_path):
    pytest.importorskip("sklearn.ensemble")
    registry = ModelArtifactRegistry(
        str(tmp_path / "models.db"),
        artifact_root=tmp_path / "artifacts",
    )
    samples = [
        _sample(10.0 + ((index % 5) * 0.02), sample_id=index)
        for index in range(1, 81)
    ]
    spec = IsolationForestModelSpec(
        artifact_key="cycle_time",
        min_samples=20,
        contamination=0.05,
        random_state=42,
    )

    training = train_isolation_forest_model(samples, registry, spec)
    detector = load_isolation_forest_detector(registry, artifact_id=training.artifact.id)
    result = detector.score_one(_sample(50.0, sample_id=99), DetectorContext())

    assert training.sample_count == 80
    assert training.artifact.shadow_mode is True
    assert result is not None
    assert result.severity == "info"
    assert result.context["artifact_key"] == "cycle_time"

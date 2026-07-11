from contextlib import closing
from dataclasses import replace

import pytest

from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.isolation_forest import (
    IsolationForestAnomalyDetector,
    IsolationForestModelSpec,
    load_isolation_forest_detector,
    sklearn_isolation_forest_available,
    train_isolation_forest_model,
)
from metroliza.industrial.anomaly.model_registry import (
    ModelArtifact,
    ModelArtifactRegistry,
    UnsafeModelArtifactError,
)
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


def test_train_rejects_legacy_pickle_artifact_format(tmp_path):
    registry = ModelArtifactRegistry(
        str(tmp_path / "models.db"),
        artifact_root=tmp_path / "artifacts",
    )

    with pytest.raises(UnsafeModelArtifactError, match="legacy artifact format used pickle"):
        train_isolation_forest_model(
            [_sample(10.0, sample_id=index) for index in range(1, 25)],
            registry,
            IsolationForestModelSpec(artifact_key="cycle_time"),
        )


def test_train_stays_disabled_even_when_optional_sklearn_is_available(tmp_path):
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

    with pytest.raises(UnsafeModelArtifactError, match="safe serializer"):
        train_isolation_forest_model(samples, registry, spec)


def test_load_archives_legacy_pickle_without_deserializing(tmp_path):
    db_path = str(tmp_path / "models.db")
    artifact_root = tmp_path / "artifacts"
    legacy_path = artifact_root / "legacy.pkl"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"not actually a pickle")
    registry = ModelArtifactRegistry(db_path, artifact_root=artifact_root)
    registry.ensure_schema()
    import sqlite3  # noqa: PLC0415

    with closing(sqlite3.connect(db_path)) as connection, connection:
        with connection:
            connection.execute(
                """
                INSERT INTO industrial_model_artifacts (
                    artifact_key, model_type, artifact_path, checksum_sha256,
                    training_sample_count, shadow_mode, calibrated, critical_allowed,
                    status, created_at, updated_at
                )
                VALUES ('legacy', 'sklearn_isolation_forest', ?, 'ignored', 1, 1, 0, 0,
                        'active', '2026-07-09T10:00:00Z', '2026-07-09T10:00:00Z')
                """,
                (str(legacy_path),),
            )

    with pytest.raises(UnsafeModelArtifactError, match="archived without deserializing"):
        load_isolation_forest_detector(registry, artifact_key="legacy")

    assert registry.list_artifacts(status="active") == []
    assert registry.list_artifacts(status="archived")[0].artifact_key == "legacy"

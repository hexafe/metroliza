from pathlib import Path
import sqlite3

import pytest

from metroliza.industrial.anomaly.model_registry import ModelArtifactRegistry


def test_model_registry_stores_file_artifact_with_sqlite_metadata(tmp_path):
    db_path = str(tmp_path / "models.db")
    artifact_root = tmp_path / "artifacts"
    registry = ModelArtifactRegistry(db_path, artifact_root=artifact_root)

    artifact = registry.store_artifact(
        artifact_key="cycle_time/line-a",
        model_type="sklearn_isolation_forest",
        payload=b"serialized model",
        parameters={"score_threshold": 0.0},
        metrics={"training_mean": 10.0},
        training_sample_count=40,
    )

    assert artifact.id is not None
    assert Path(artifact.artifact_path).is_file()
    assert Path(artifact.artifact_path).is_relative_to(artifact_root)
    assert artifact.shadow_mode is True
    assert artifact.calibrated is False
    assert artifact.critical_allowed is False
    assert artifact.parameters == {"score_threshold": 0.0}
    assert artifact.metrics == {"training_mean": 10.0}
    assert registry.load_artifact_bytes(artifact) == b"serialized model"

    latest = registry.latest_artifact(artifact_key="cycle_time/line-a")

    assert latest is not None
    assert latest.id == artifact.id
    assert latest.training_sample_count == 40


def test_model_registry_schema_is_idempotent_and_lists_by_type(tmp_path):
    db_path = str(tmp_path / "models.db")
    registry = ModelArtifactRegistry(db_path, artifact_root=tmp_path / "artifacts")

    registry.ensure_schema()
    registry.ensure_schema()
    first = registry.store_artifact(
        artifact_key="cycle_time",
        model_type="sklearn_isolation_forest",
        payload=b"model-one",
        created_at="2026-06-13T10:00:00Z",
    )
    second = registry.store_artifact(
        artifact_key="temperature",
        model_type="other_model",
        payload=b"model-two",
        created_at="2026-06-13T11:00:00Z",
    )

    isolation_forest_artifacts = registry.list_artifacts(model_type="sklearn_isolation_forest")

    assert [artifact.id for artifact in isolation_forest_artifacts] == [first.id]
    assert registry.get_artifact(second.id).artifact_key == "temperature"
    with sqlite3.connect(db_path) as connection:
        table_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table' AND name = 'industrial_model_artifacts'
            """
        ).fetchone()[0]
    assert table_count == 1


def test_model_registry_detects_artifact_checksum_mismatch(tmp_path):
    registry = ModelArtifactRegistry(
        str(tmp_path / "models.db"),
        artifact_root=tmp_path / "artifacts",
    )
    artifact = registry.store_artifact(
        artifact_key="cycle_time",
        model_type="sklearn_isolation_forest",
        payload=b"original",
    )
    Path(artifact.artifact_path).write_bytes(b"tampered")

    with pytest.raises(ValueError, match="checksum mismatch"):
        registry.load_artifact_bytes(artifact)

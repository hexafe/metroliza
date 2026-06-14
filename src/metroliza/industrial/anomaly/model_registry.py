"""File-backed model artifact registry for optional industrial ML detectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import os
import re
from typing import Any, Mapping

from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.realtime.sample_repository import from_json, to_json, utc_timestamp
from metroliza.reports.db import run_transaction_with_retry


MODEL_ARTIFACT_STATUSES = ("active", "archived", "failed")

_SAFE_PATH_PART = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class ModelArtifact:
    """SQLite metadata for one file-based industrial ML model artifact."""

    artifact_key: str
    model_type: str
    artifact_path: str
    checksum_sha256: str
    id: int | None = None
    signal_id: int | None = None
    segment_key: Mapping[str, Any] = field(default_factory=dict)
    training_window_start: str | None = None
    training_window_end: str | None = None
    training_sample_count: int = 0
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    shadow_mode: bool = True
    calibrated: bool = False
    critical_allowed: bool = False
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None


class ModelArtifactRegistry:
    """Store model bytes on disk and searchable artifact metadata in SQLite."""

    def __init__(
        self,
        database: str,
        *,
        artifact_root: str | Path | None = None,
        connection=None,
    ):
        self.database = database
        self.connection = connection
        self.artifact_root = Path(artifact_root) if artifact_root is not None else _default_root(database)

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

        def _ensure(cursor) -> None:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS industrial_model_artifacts (
                    id INTEGER PRIMARY KEY,
                    artifact_key TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    checksum_sha256 TEXT NOT NULL,
                    signal_id INTEGER,
                    segment_key_json TEXT NOT NULL DEFAULT '{}',
                    training_window_start TEXT,
                    training_window_end TEXT,
                    training_sample_count INTEGER NOT NULL DEFAULT 0,
                    parameters_json TEXT NOT NULL DEFAULT '{}',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    shadow_mode INTEGER NOT NULL DEFAULT 1 CHECK (shadow_mode IN (0, 1)),
                    calibrated INTEGER NOT NULL DEFAULT 0 CHECK (calibrated IN (0, 1)),
                    critical_allowed INTEGER NOT NULL DEFAULT 0 CHECK (critical_allowed IN (0, 1)),
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'archived', 'failed')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (signal_id)
                        REFERENCES industrial_signal_definitions(id) ON DELETE SET NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_industrial_model_artifacts_key_created
                ON industrial_model_artifacts(artifact_key, created_at DESC, id DESC)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_industrial_model_artifacts_signal_created
                ON industrial_model_artifacts(signal_id, created_at DESC, id DESC)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_industrial_model_artifacts_status
                ON industrial_model_artifacts(status)
                """
            )

        run_transaction_with_retry(self.database, _ensure, connection=self.connection)

    def store_artifact(
        self,
        *,
        artifact_key: str,
        model_type: str,
        payload: bytes,
        file_extension: str = ".pkl",
        signal_id: int | None = None,
        segment_key: Mapping[str, Any] | None = None,
        training_window_start: str | None = None,
        training_window_end: str | None = None,
        training_sample_count: int = 0,
        parameters: Mapping[str, Any] | None = None,
        metrics: Mapping[str, Any] | None = None,
        shadow_mode: bool = True,
        calibrated: bool = False,
        critical_allowed: bool = False,
        status: str = "active",
        created_at: str | None = None,
    ) -> ModelArtifact:
        """Write model bytes to disk and insert a metadata row."""

        _validate_non_empty("artifact_key", artifact_key)
        _validate_non_empty("model_type", model_type)
        _validate_status(status)
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        created = created_at or utc_timestamp()
        checksum = hashlib.sha256(payload).hexdigest()
        artifact_path = self._write_payload(
            artifact_key=artifact_key,
            model_type=model_type,
            checksum=checksum,
            payload=payload,
            file_extension=file_extension,
            created_at=created,
        )
        return self.register_artifact(
            artifact_key=artifact_key,
            model_type=model_type,
            artifact_path=artifact_path,
            checksum_sha256=checksum,
            signal_id=signal_id,
            segment_key=segment_key,
            training_window_start=training_window_start,
            training_window_end=training_window_end,
            training_sample_count=training_sample_count,
            parameters=parameters,
            metrics=metrics,
            shadow_mode=shadow_mode,
            calibrated=calibrated,
            critical_allowed=critical_allowed,
            status=status,
            created_at=created,
        )

    def register_artifact(
        self,
        *,
        artifact_key: str,
        model_type: str,
        artifact_path: str | Path,
        checksum_sha256: str | None = None,
        signal_id: int | None = None,
        segment_key: Mapping[str, Any] | None = None,
        training_window_start: str | None = None,
        training_window_end: str | None = None,
        training_sample_count: int = 0,
        parameters: Mapping[str, Any] | None = None,
        metrics: Mapping[str, Any] | None = None,
        shadow_mode: bool = True,
        calibrated: bool = False,
        critical_allowed: bool = False,
        status: str = "active",
        created_at: str | None = None,
    ) -> ModelArtifact:
        """Register an existing model file in SQLite metadata."""

        self.ensure_schema()
        _validate_non_empty("artifact_key", artifact_key)
        _validate_non_empty("model_type", model_type)
        _validate_status(status)
        path = Path(artifact_path).resolve(strict=False)
        checksum = checksum_sha256 or _sha256_file(path)
        created = created_at or utc_timestamp()
        updated = utc_timestamp()
        segment_json = to_json(dict(segment_key or {}))
        parameters_json = to_json(dict(parameters or {}))
        metrics_json = to_json(dict(metrics or {}))

        def _insert(cursor) -> ModelArtifact:
            cursor.execute(
                """
                INSERT INTO industrial_model_artifacts (
                    artifact_key,
                    model_type,
                    artifact_path,
                    checksum_sha256,
                    signal_id,
                    segment_key_json,
                    training_window_start,
                    training_window_end,
                    training_sample_count,
                    parameters_json,
                    metrics_json,
                    shadow_mode,
                    calibrated,
                    critical_allowed,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_key,
                    model_type,
                    str(path),
                    checksum,
                    signal_id,
                    segment_json,
                    training_window_start,
                    training_window_end,
                    int(training_sample_count),
                    parameters_json,
                    metrics_json,
                    int(bool(shadow_mode)),
                    int(bool(calibrated)),
                    int(bool(critical_allowed)),
                    status,
                    created,
                    updated,
                ),
            )
            cursor.execute(
                """
                SELECT *
                FROM industrial_model_artifacts
                WHERE id = ?
                """,
                (int(cursor.lastrowid),),
            )
            row = cursor.fetchone()
            assert row is not None
            return _row_to_artifact(row)

        return run_transaction_with_retry(self.database, _insert, connection=self.connection)

    def get_artifact(self, artifact_id: int) -> ModelArtifact | None:
        self.ensure_schema()

        def _get(cursor) -> ModelArtifact | None:
            cursor.execute(
                """
                SELECT *
                FROM industrial_model_artifacts
                WHERE id = ?
                """,
                (int(artifact_id),),
            )
            row = cursor.fetchone()
            return _row_to_artifact(row) if row is not None else None

        return run_transaction_with_retry(self.database, _get, connection=self.connection)

    def latest_artifact(
        self,
        *,
        artifact_key: str | None = None,
        model_type: str | None = None,
        signal_id: int | None = None,
        status: str = "active",
    ) -> ModelArtifact | None:
        artifacts = self.list_artifacts(
            artifact_key=artifact_key,
            model_type=model_type,
            signal_id=signal_id,
            status=status,
            limit=1,
        )
        return artifacts[0] if artifacts else None

    def list_artifacts(
        self,
        *,
        artifact_key: str | None = None,
        model_type: str | None = None,
        signal_id: int | None = None,
        status: str | None = "active",
        limit: int | None = None,
    ) -> list[ModelArtifact]:
        self.ensure_schema()
        if status is not None:
            _validate_status(status)

        def _list(cursor) -> list[ModelArtifact]:
            where_clauses: list[str] = []
            params: list[Any] = []
            if artifact_key is not None:
                where_clauses.append("artifact_key = ?")
                params.append(artifact_key)
            if model_type is not None:
                where_clauses.append("model_type = ?")
                params.append(model_type)
            if signal_id is not None:
                where_clauses.append("signal_id = ?")
                params.append(int(signal_id))
            if status is not None:
                where_clauses.append("status = ?")
                params.append(status)
            where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            limit_clause = ""
            if limit is not None:
                limit_clause = "LIMIT ?"
                params.append(_positive_limit(limit))
            cursor.execute(
                f"""
                SELECT *
                FROM industrial_model_artifacts
                {where}
                ORDER BY created_at DESC, id DESC
                {limit_clause}
                """,
                tuple(params),
            )
            return [_row_to_artifact(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def load_artifact_bytes(self, artifact: ModelArtifact | int, *, verify_checksum: bool = True) -> bytes:
        record = self.get_artifact(artifact) if isinstance(artifact, int) else artifact
        if record is None:
            raise FileNotFoundError(f"Model artifact {artifact!r} is not registered")
        path = Path(record.artifact_path)
        payload = path.read_bytes()
        if verify_checksum:
            checksum = hashlib.sha256(payload).hexdigest()
            if checksum != record.checksum_sha256:
                raise ValueError(
                    f"Model artifact checksum mismatch for {record.artifact_key}: "
                    f"expected {record.checksum_sha256}, got {checksum}"
                )
        return payload

    def _write_payload(
        self,
        *,
        artifact_key: str,
        model_type: str,
        checksum: str,
        payload: bytes,
        file_extension: str,
        created_at: str,
    ) -> Path:
        extension = file_extension if file_extension.startswith(".") else f".{file_extension}"
        safe_model_type = _safe_path_part(model_type)
        safe_key = _safe_path_part(artifact_key)
        safe_created = _safe_path_part(created_at)
        artifact_path = (
            self.artifact_root
            / safe_model_type
            / safe_key
            / f"{safe_created}-{checksum[:12]}{extension}"
        )
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = artifact_path.with_name(f".{artifact_path.name}.{os.getpid()}.tmp")
        temporary_path.write_bytes(payload)
        temporary_path.replace(artifact_path)
        return artifact_path


def _default_root(database: str) -> Path:
    if database == ":memory:":
        return Path.cwd() / "industrial_model_artifacts"
    db_path = Path(database).resolve(strict=False)
    return db_path.parent / "industrial_model_artifacts"


def _safe_path_part(value: str) -> str:
    safe = _SAFE_PATH_PART.sub("_", str(value).strip()).strip("._")
    return (safe or "artifact")[:120]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_non_empty(field_name: str, value: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"{field_name} must not be empty")


def _validate_status(status: str) -> None:
    if status not in MODEL_ARTIFACT_STATUSES:
        allowed = ", ".join(MODEL_ARTIFACT_STATUSES)
        raise ValueError(f"status must be one of: {allowed}")


def _positive_limit(limit: int) -> int:
    parsed = int(limit)
    if parsed <= 0:
        raise ValueError("limit must be positive")
    return parsed


def _row_to_artifact(row) -> ModelArtifact:
    return ModelArtifact(
        id=int(row[0]),
        artifact_key=str(row[1]),
        model_type=str(row[2]),
        artifact_path=str(row[3]),
        checksum_sha256=str(row[4]),
        signal_id=int(row[5]) if row[5] is not None else None,
        segment_key=dict(from_json(row[6], {})),
        training_window_start=row[7],
        training_window_end=row[8],
        training_sample_count=int(row[9]),
        parameters=dict(from_json(row[10], {})),
        metrics=dict(from_json(row[11], {})),
        shadow_mode=bool(row[12]),
        calibrated=bool(row[13]),
        critical_allowed=bool(row[14]),
        status=str(row[15]),
        created_at=str(row[16]),
        updated_at=str(row[17]),
    )

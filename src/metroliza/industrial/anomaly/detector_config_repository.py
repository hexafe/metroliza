"""Persistence helpers for realtime industrial detector configurations."""

from __future__ import annotations

from dataclasses import replace
import math

from metroliza.industrial.anomaly.contracts import ANOMALY_SEVERITIES, DetectorConfig
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.industrial_workflow_state import require_identifier
from metroliza.industrial.realtime.detector_registry import normalize_detector_keys
from metroliza.industrial.realtime.sample_repository import from_json, to_json, utc_timestamp
from metroliza.reports.db import run_transaction_with_retry


class DetectorConfigRepository:
    """Store deterministic detector configuration records."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

    def upsert_config(self, config: DetectorConfig) -> DetectorConfig:
        self.ensure_schema()
        config = _validated_config(config)
        now = utc_timestamp()

        def _upsert(cursor) -> DetectorConfig:
            cursor.execute(
                """
                INSERT INTO industrial_detector_configs (
                    detector_key,
                    detector_type,
                    parameters_json,
                    enabled,
                    severity_map_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(detector_key) DO UPDATE SET
                    detector_type = excluded.detector_type,
                    parameters_json = excluded.parameters_json,
                    enabled = excluded.enabled,
                    severity_map_json = excluded.severity_map_json,
                    updated_at = excluded.updated_at
                """,
                (
                    config.detector_key,
                    config.detector_type,
                    to_json(dict(config.parameters)),
                    int(bool(config.enabled)),
                    to_json(dict(config.severity_map)),
                    now,
                    now,
                ),
            )
            cursor.execute(
                """
                SELECT
                    id,
                    detector_key,
                    detector_type,
                    parameters_json,
                    enabled,
                    severity_map_json,
                    created_at,
                    updated_at
                FROM industrial_detector_configs
                WHERE detector_key = ?
                """,
                (config.detector_key,),
            )
            row = cursor.fetchone()
            assert row is not None
            return _row_to_config(row)

        return run_transaction_with_retry(self.database, _upsert, connection=self.connection)

    def list_configs(self, *, include_disabled: bool = False) -> list[DetectorConfig]:
        self.ensure_schema()

        def _list(cursor) -> list[DetectorConfig]:
            where = "" if include_disabled else "WHERE enabled = 1"
            cursor.execute(
                f"""
                SELECT
                    id,
                    detector_key,
                    detector_type,
                    parameters_json,
                    enabled,
                    severity_map_json,
                    created_at,
                    updated_at
                FROM industrial_detector_configs
                {where}
                ORDER BY detector_key ASC
                """
            )
            return [_row_to_config(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)


def _row_to_config(row) -> DetectorConfig:
    return DetectorConfig(
        id=int(row[0]),
        detector_key=str(row[1]),
        detector_type=str(row[2]),
        parameters=dict(from_json(row[3], {})),
        enabled=bool(row[4]),
        severity_map=dict(from_json(row[5], {})),
        created_at=str(row[6]),
        updated_at=str(row[7]),
    )


def _validated_config(config: DetectorConfig) -> DetectorConfig:
    detector_key = str(config.detector_key or "").strip()
    require_identifier("detector key", detector_key)
    detector_types = normalize_detector_keys((config.detector_type,))
    if not detector_types:
        raise ValueError("detector type is required")
    detector_type = detector_types[0]
    if type(config.enabled) is not bool:
        raise ValueError("detector enabled setting must be true or false")
    parameters = dict(config.parameters)
    severity_map = dict(config.severity_map)
    invalid_severities = {
        str(value)
        for value in severity_map.values()
        if str(value) not in ANOMALY_SEVERITIES
    }
    if invalid_severities:
        raise ValueError(
            f"unsupported detector severity mapping: {', '.join(sorted(invalid_severities))}"
        )
    for key, value in parameters.items():
        if key in {
            "min_n",
            "max_window",
            "threshold",
            "fence_multiplier",
            "warning_seconds",
            "major_seconds",
        }:
            _positive_finite_parameter(key, value)
    if detector_type == "stale_source":
        warning = float(parameters.get("warning_seconds", 300.0))
        major = float(parameters.get("major_seconds", 900.0))
        if major <= warning:
            raise ValueError("stale_source major_seconds must be greater than warning_seconds")
    if detector_type == "rolling_zscore":
        min_n = int(parameters.get("min_n", 30))
        max_window = int(parameters.get("max_window", 500))
        if max_window < min_n:
            raise ValueError("rolling_zscore max_window must be greater than or equal to min_n")
    return replace(
        config,
        detector_key=detector_key,
        detector_type=detector_type,
        parameters=parameters,
        severity_map=severity_map,
    )


def _positive_finite_parameter(name: str, value) -> None:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"detector parameter {name} must be numeric") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"detector parameter {name} must be positive and finite")

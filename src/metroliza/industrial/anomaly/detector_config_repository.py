"""Persistence helpers for realtime industrial detector configurations."""

from __future__ import annotations

from metroliza.industrial.anomaly.contracts import DetectorConfig
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
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

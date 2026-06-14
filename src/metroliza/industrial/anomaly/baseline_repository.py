"""Persistence helpers for realtime industrial statistical baselines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.realtime.sample_repository import to_json, utc_timestamp
from metroliza.reports.db import run_transaction_with_retry


@dataclass(frozen=True)
class IndustrialBaseline:
    signal_id: int
    baseline_version: str
    n: int
    id: int | None = None
    segment_key: dict[str, Any] | None = None
    window_start: str | None = None
    window_end: str | None = None
    mean: float | None = None
    std: float | None = None
    median: float | None = None
    mad: float | None = None
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    p01: float | None = None
    p99: float | None = None
    model_artifact_id: int | None = None
    created_at: str | None = None


class BaselineRepository:
    """Append and load statistical baselines for deterministic detectors."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

    def insert_baseline(self, baseline: IndustrialBaseline) -> int:
        self.ensure_schema()
        created_at = baseline.created_at or utc_timestamp()

        def _insert(cursor) -> int:
            cursor.execute(
                """
                INSERT INTO industrial_baselines (
                    signal_id,
                    segment_key_json,
                    baseline_version,
                    window_start,
                    window_end,
                    n,
                    mean,
                    std,
                    median,
                    mad,
                    q1,
                    q3,
                    iqr,
                    p01,
                    p99,
                    model_artifact_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    baseline.signal_id,
                    to_json(dict(baseline.segment_key or {})),
                    baseline.baseline_version,
                    baseline.window_start,
                    baseline.window_end,
                    int(baseline.n),
                    baseline.mean,
                    baseline.std,
                    baseline.median,
                    baseline.mad,
                    baseline.q1,
                    baseline.q3,
                    baseline.iqr,
                    baseline.p01,
                    baseline.p99,
                    baseline.model_artifact_id,
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

        return run_transaction_with_retry(self.database, _insert, connection=self.connection)

    def latest_baseline(self, *, signal_id: int, segment_key: dict[str, Any] | None = None) -> dict[str, Any] | None:
        self.ensure_schema()
        segment_json = to_json(dict(segment_key or {}))

        def _latest(cursor) -> dict[str, Any] | None:
            cursor.execute(
                """
                SELECT
                    id,
                    signal_id,
                    baseline_version,
                    n,
                    mean,
                    std,
                    median,
                    mad,
                    q1,
                    q3,
                    iqr,
                    p01,
                    p99,
                    window_start,
                    window_end,
                    created_at
                FROM industrial_baselines
                WHERE signal_id = ? AND segment_key_json = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (signal_id, segment_json),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": int(row[0]),
                "signal_id": int(row[1]),
                "baseline_version": str(row[2]),
                "n": int(row[3]),
                "mean": row[4],
                "std": row[5],
                "median": row[6],
                "mad": row[7],
                "q1": row[8],
                "q3": row[9],
                "iqr": row[10],
                "p01": row[11],
                "p99": row[12],
                "window_start": row[13],
                "window_end": row[14],
                "created_at": str(row[15]),
            }

        return run_transaction_with_retry(self.database, _latest, connection=self.connection)

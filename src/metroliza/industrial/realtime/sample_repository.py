"""Persistence helpers for realtime industrial signal definitions and samples."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from typing import Any, Iterable

from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.industrial_data_repository import looks_sensitive_key, redact_sensitive_text
from metroliza.industrial.realtime.stream_contracts import (
    IndustrialSample,
    SampleBatchResult,
    SignalDefinition,
)
from metroliza.reports.db import run_transaction_with_retry


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for SQLite text columns."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def from_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def redact_sample_payload(value: Any) -> Any:
    """Redact credential-like fields before persisting raw realtime source rows."""

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key)
            if looks_sensitive_key(key_text):
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = redact_sample_payload(nested)
        return redacted
    if isinstance(value, list):
        return [redact_sample_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sample_payload(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


class RealtimeSampleRepository:
    """Repository for realtime signal definitions and append-only samples."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

    def upsert_signal_definition(self, signal: SignalDefinition) -> SignalDefinition:
        self.ensure_schema()
        now = utc_timestamp()

        def _upsert(cursor) -> SignalDefinition:
            cursor.execute(
                """
                INSERT INTO industrial_signal_definitions (
                    source_profile_id,
                    signal_key,
                    metric_name,
                    unit,
                    nominal,
                    lsl,
                    usl,
                    lower_warning,
                    upper_warning,
                    segment_fields_json,
                    enabled,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_profile_id, signal_key) DO UPDATE SET
                    metric_name = excluded.metric_name,
                    unit = excluded.unit,
                    nominal = excluded.nominal,
                    lsl = excluded.lsl,
                    usl = excluded.usl,
                    lower_warning = excluded.lower_warning,
                    upper_warning = excluded.upper_warning,
                    segment_fields_json = excluded.segment_fields_json,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    signal.source_profile_id,
                    signal.signal_key,
                    signal.metric_name,
                    signal.unit,
                    signal.nominal,
                    signal.lsl,
                    signal.usl,
                    signal.lower_warning,
                    signal.upper_warning,
                    to_json(list(signal.segment_fields)),
                    int(bool(signal.enabled)),
                    now,
                    now,
                ),
            )
            cursor.execute(
                """
                SELECT
                    id,
                    source_profile_id,
                    signal_key,
                    metric_name,
                    unit,
                    nominal,
                    lsl,
                    usl,
                    lower_warning,
                    upper_warning,
                    segment_fields_json,
                    enabled,
                    created_at,
                    updated_at
                FROM industrial_signal_definitions
                WHERE source_profile_id = ? AND signal_key = ?
                """,
                (signal.source_profile_id, signal.signal_key),
            )
            row = cursor.fetchone()
            assert row is not None
            return SignalDefinition(
                id=int(row[0]),
                source_profile_id=int(row[1]),
                signal_key=str(row[2]),
                metric_name=str(row[3]),
                unit=row[4],
                nominal=float(row[5]) if row[5] is not None else None,
                lsl=float(row[6]) if row[6] is not None else None,
                usl=float(row[7]) if row[7] is not None else None,
                lower_warning=float(row[8]) if row[8] is not None else None,
                upper_warning=float(row[9]) if row[9] is not None else None,
                segment_fields=tuple(from_json(row[10], [])),
                enabled=bool(row[11]),
                created_at=str(row[12]),
                updated_at=str(row[13]),
            )

        return run_transaction_with_retry(self.database, _upsert, connection=self.connection)

    def get_signal_definition(
        self,
        *,
        source_profile_id: int,
        signal_key: str,
    ) -> SignalDefinition | None:
        self.ensure_schema()

        def _get(cursor) -> SignalDefinition | None:
            cursor.execute(
                """
                SELECT
                    id,
                    source_profile_id,
                    signal_key,
                    metric_name,
                    unit,
                    nominal,
                    lsl,
                    usl,
                    lower_warning,
                    upper_warning,
                    segment_fields_json,
                    enabled,
                    created_at,
                    updated_at
                FROM industrial_signal_definitions
                WHERE source_profile_id = ? AND signal_key = ?
                """,
                (source_profile_id, signal_key),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return SignalDefinition(
                id=int(row[0]),
                source_profile_id=int(row[1]),
                signal_key=str(row[2]),
                metric_name=str(row[3]),
                unit=row[4],
                nominal=float(row[5]) if row[5] is not None else None,
                lsl=float(row[6]) if row[6] is not None else None,
                usl=float(row[7]) if row[7] is not None else None,
                lower_warning=float(row[8]) if row[8] is not None else None,
                upper_warning=float(row[9]) if row[9] is not None else None,
                segment_fields=tuple(from_json(row[10], [])),
                enabled=bool(row[11]),
                created_at=str(row[12]),
                updated_at=str(row[13]),
            )

        return run_transaction_with_retry(self.database, _get, connection=self.connection)

    def insert_samples(self, samples: Iterable[IndustrialSample]) -> SampleBatchResult:
        self.ensure_schema()
        sample_batch = tuple(samples)
        now = utc_timestamp()

        def _insert(cursor) -> SampleBatchResult:
            processed = 0
            inserted = 0
            sample_ids: list[int] = []
            for sample in sample_batch:
                processed += 1
                ingest_time = sample.ingest_time or now
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO industrial_samples (
                        source_profile_id,
                        signal_id,
                        source_record_key,
                        event_time,
                        ingest_time,
                        metric_name,
                        value,
                        reference,
                        part_number,
                        revision,
                        station,
                        line,
                        work_order,
                        batch_lot,
                        segment_key_json,
                        quality_flags_json,
                        raw_record_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sample.source_profile_id,
                        sample.signal_id,
                        sample.source_record_key,
                        sample.event_time,
                        ingest_time,
                        sample.metric_name,
                        float(sample.value),
                        sample.reference,
                        sample.part_number,
                        sample.revision,
                        sample.station,
                        sample.line,
                        sample.work_order,
                        sample.batch_lot,
                        to_json(dict(sample.segment_key)),
                        to_json(list(sample.quality_flags)),
                        (
                            to_json(redact_sample_payload(dict(sample.raw_record or {})))
                            if sample.raw_record is not None
                            else None
                        ),
                    ),
                )
                if cursor.rowcount:
                    inserted += 1
                cursor.execute(
                    """
                    SELECT id FROM industrial_samples
                    WHERE source_profile_id = ? AND signal_id = ? AND source_record_key = ?
                    """,
                    (sample.source_profile_id, sample.signal_id, sample.source_record_key),
                )
                row = cursor.fetchone()
                if row is not None:
                    sample_ids.append(int(row[0]))
            return SampleBatchResult(
                processed=processed,
                inserted=inserted,
                skipped=processed - inserted,
                sample_ids=tuple(sample_ids),
            )

        return run_transaction_with_retry(self.database, _insert, connection=self.connection)

    def list_samples(self, *, signal_id: int, limit: int | None = None) -> list[IndustrialSample]:
        self.ensure_schema()

        def _list(cursor) -> list[IndustrialSample]:
            sql = """
                SELECT
                    id,
                    source_profile_id,
                    signal_id,
                    source_record_key,
                    event_time,
                    ingest_time,
                    metric_name,
                    value,
                    reference,
                    part_number,
                    revision,
                    station,
                    line,
                    work_order,
                    batch_lot,
                    segment_key_json,
                    quality_flags_json,
                    raw_record_json
                FROM industrial_samples
                WHERE signal_id = ?
                ORDER BY event_time ASC, id ASC
            """
            params: tuple[Any, ...] = (signal_id,)
            if limit is not None:
                sql += " LIMIT ?"
                params = (signal_id, int(limit))
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [
                IndustrialSample(
                    id=int(row[0]),
                    source_profile_id=int(row[1]),
                    signal_id=int(row[2]),
                    source_record_key=str(row[3]),
                    event_time=str(row[4]),
                    ingest_time=str(row[5]),
                    metric_name=str(row[6]),
                    value=float(row[7]),
                    reference=row[8],
                    part_number=row[9],
                    revision=row[10],
                    station=row[11],
                    line=row[12],
                    work_order=row[13],
                    batch_lot=row[14],
                    segment_key=from_json(row[15], {}),
                    quality_flags=tuple(from_json(row[16], [])),
                    raw_record=from_json(row[17], {}) if row[17] else None,
                )
                for row in rows
            ]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def list_recent_samples(self, *, signal_id: int, limit: int) -> list[IndustrialSample]:
        self.ensure_schema()

        def _list(cursor) -> list[IndustrialSample]:
            cursor.execute(
                """
                SELECT
                    id,
                    source_profile_id,
                    signal_id,
                    source_record_key,
                    event_time,
                    ingest_time,
                    metric_name,
                    value,
                    reference,
                    part_number,
                    revision,
                    station,
                    line,
                    work_order,
                    batch_lot,
                    segment_key_json,
                    quality_flags_json,
                    raw_record_json
                FROM industrial_samples
                WHERE signal_id = ?
                ORDER BY event_time DESC, id DESC
                LIMIT ?
                """,
                (signal_id, max(1, int(limit))),
            )
            rows = list(reversed(cursor.fetchall()))
            return [
                IndustrialSample(
                    id=int(row[0]),
                    source_profile_id=int(row[1]),
                    signal_id=int(row[2]),
                    source_record_key=str(row[3]),
                    event_time=str(row[4]),
                    ingest_time=str(row[5]),
                    metric_name=str(row[6]),
                    value=float(row[7]),
                    reference=row[8],
                    part_number=row[9],
                    revision=row[10],
                    station=row[11],
                    line=row[12],
                    work_order=row[13],
                    batch_lot=row[14],
                    segment_key=from_json(row[15], {}),
                    quality_flags=tuple(from_json(row[16], [])),
                    raw_record=from_json(row[17], {}) if row[17] else None,
                )
                for row in rows
            ]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    @staticmethod
    def with_sample_id(sample: IndustrialSample, sample_id: int) -> IndustrialSample:
        return replace(sample, id=sample_id)

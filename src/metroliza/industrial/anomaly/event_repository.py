"""Persistence helpers for realtime industrial anomaly events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from metroliza.industrial.anomaly.contracts import ANOMALY_SEVERITIES, DetectionResult
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.realtime.sample_repository import from_json, to_json, utc_timestamp
from metroliza.reports.db import run_transaction_with_retry

ANOMALY_EVENT_STATUSES = ("open", "acknowledged", "resolved", "false_positive")


@dataclass(frozen=True)
class PersistedAnomalyEvent:
    id: int
    sample_id: int
    signal_id: int
    event_time: str
    detector_key: str
    severity: str
    score: float
    observed_value: float
    expected_value: float | None
    threshold: dict[str, Any]
    explanation: str
    context: dict[str, Any]
    status: str
    created_at: str
    ack_by: str | None = None
    ack_at: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class EventBatchResult:
    processed: int
    inserted: int
    skipped: int
    event_ids: tuple[int, ...]


class AnomalyEventRepository:
    """Persist explainable anomaly events with sample/detector deduplication."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

    def insert_events(self, events: Iterable[DetectionResult]) -> EventBatchResult:
        self.ensure_schema()
        event_batch = tuple(events)
        created_at = utc_timestamp()

        def _insert(cursor) -> EventBatchResult:
            processed = 0
            inserted = 0
            event_ids: list[int] = []
            for event in event_batch:
                processed += 1
                if event.sample_id is None:
                    raise ValueError("DetectionResult.sample_id is required for persistence")
                if event.signal_id is None:
                    raise ValueError("DetectionResult.signal_id is required for persistence")
                cursor.execute(
                    """
                    SELECT id
                    FROM industrial_anomaly_events
                    WHERE sample_id = ? AND detector_key = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (event.sample_id, event.detector_key),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    event_ids.append(int(existing[0]))
                    continue
                cursor.execute(
                    """
                    INSERT INTO industrial_anomaly_events (
                        sample_id,
                        signal_id,
                        event_time,
                        detector_key,
                        severity,
                        score,
                        observed_value,
                        expected_value,
                        threshold_json,
                        explanation,
                        context_json,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                    """,
                    (
                        event.sample_id,
                        event.signal_id,
                        event.event_time,
                        event.detector_key,
                        event.severity,
                        float(event.score),
                        float(event.observed_value),
                        event.expected_value,
                        to_json(dict(event.threshold)),
                        event.explanation,
                        to_json(dict(event.context)),
                        created_at,
                    ),
                )
                inserted += 1
                event_ids.append(int(cursor.lastrowid))
            return EventBatchResult(
                processed=processed,
                inserted=inserted,
                skipped=processed - inserted,
                event_ids=tuple(event_ids),
            )

        return run_transaction_with_retry(self.database, _insert, connection=self.connection)

    def list_events(
        self,
        *,
        detector_key: str | None = None,
        signal_id: int | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[PersistedAnomalyEvent]:
        self.ensure_schema()

        def _list(cursor) -> list[PersistedAnomalyEvent]:
            where_clauses: list[str] = []
            params: list[Any] = []
            if detector_key is not None:
                where_clauses.append("detector_key = ?")
                params.append(detector_key)
            if signal_id is not None:
                where_clauses.append("signal_id = ?")
                params.append(int(signal_id))
            if status is not None:
                _validate_status(status)
                where_clauses.append("status = ?")
                params.append(status)
            where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            limit_clause = ""
            if limit is not None:
                limit_clause = "LIMIT ?"
                params.append(_positive_limit(limit))
            cursor.execute(
                f"""
                SELECT
                    id,
                    sample_id,
                    signal_id,
                    event_time,
                    detector_key,
                    severity,
                    score,
                    observed_value,
                    expected_value,
                    threshold_json,
                    explanation,
                    context_json,
                    status,
                    created_at,
                    ack_by,
                    ack_at,
                    comment
                FROM industrial_anomaly_events
                {where}
                ORDER BY event_time ASC, id ASC
                {limit_clause}
                """,
                tuple(params),
            )
            return [_row_to_event(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def list_open_events(
        self,
        *,
        signal_id: int | None = None,
        detector_key: str | None = None,
        limit: int | None = None,
    ) -> list[PersistedAnomalyEvent]:
        return self.list_events(
            signal_id=signal_id,
            detector_key=detector_key,
            status="open",
            limit=limit,
        )

    def count_by_severity(self, *, status: str | None = None) -> dict[str, int]:
        self.ensure_schema()

        def _count(cursor) -> dict[str, int]:
            params: tuple[Any, ...] = ()
            where = ""
            if status is not None:
                _validate_status(status)
                where = "WHERE status = ?"
                params = (status,)
            cursor.execute(
                f"""
                SELECT severity, COUNT(*)
                FROM industrial_anomaly_events
                {where}
                GROUP BY severity
                """,
                params,
            )
            counts = {severity: 0 for severity in ANOMALY_SEVERITIES}
            counts.update({str(row[0]): int(row[1]) for row in cursor.fetchall()})
            return counts

        return run_transaction_with_retry(self.database, _count, connection=self.connection)

    def count_by_detector(self, *, status: str | None = None) -> dict[str, int]:
        self.ensure_schema()

        def _count(cursor) -> dict[str, int]:
            params: tuple[Any, ...] = ()
            where = ""
            if status is not None:
                _validate_status(status)
                where = "WHERE status = ?"
                params = (status,)
            cursor.execute(
                f"""
                SELECT detector_key, COUNT(*)
                FROM industrial_anomaly_events
                {where}
                GROUP BY detector_key
                ORDER BY detector_key ASC
                """,
                params,
            )
            return {str(row[0]): int(row[1]) for row in cursor.fetchall()}

        return run_transaction_with_retry(self.database, _count, connection=self.connection)

    def recent_events_by_signal(
        self,
        *,
        signal_id: int,
        limit: int = 50,
        status: str | None = None,
    ) -> list[PersistedAnomalyEvent]:
        self.ensure_schema()

        def _list(cursor) -> list[PersistedAnomalyEvent]:
            where = ["signal_id = ?"]
            params: list[Any] = [int(signal_id)]
            if status is not None:
                _validate_status(status)
                where.append("status = ?")
                params.append(status)
            params.append(_positive_limit(limit))
            cursor.execute(
                f"""
                SELECT
                    id,
                    sample_id,
                    signal_id,
                    event_time,
                    detector_key,
                    severity,
                    score,
                    observed_value,
                    expected_value,
                    threshold_json,
                    explanation,
                    context_json,
                    status,
                    created_at,
                    ack_by,
                    ack_at,
                    comment
                FROM industrial_anomaly_events
                WHERE {' AND '.join(where)}
                ORDER BY event_time DESC, id DESC
                LIMIT ?
                """,
                tuple(params),
            )
            return [_row_to_event(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def acknowledge_event(
        self,
        *,
        event_id: int,
        ack_by: str,
        comment: str | None = None,
        ack_at: str | None = None,
    ) -> None:
        self.update_event_status(
            event_id=event_id,
            status="acknowledged",
            operator=ack_by,
            comment=comment,
            updated_at=ack_at,
        )

    def resolve_event(
        self,
        *,
        event_id: int,
        resolved_by: str,
        comment: str | None = None,
        resolved_at: str | None = None,
    ) -> None:
        self.update_event_status(
            event_id=event_id,
            status="resolved",
            operator=resolved_by,
            comment=comment,
            updated_at=resolved_at,
        )

    def mark_event_false_positive(
        self,
        *,
        event_id: int,
        marked_by: str,
        comment: str | None = None,
        marked_at: str | None = None,
    ) -> None:
        self.update_event_status(
            event_id=event_id,
            status="false_positive",
            operator=marked_by,
            comment=comment,
            updated_at=marked_at,
        )

    def update_event_status(
        self,
        *,
        event_id: int,
        status: str,
        operator: str,
        comment: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        self.ensure_schema()
        _validate_status(status)
        updated_at = updated_at or utc_timestamp()
        normalized_operator = str(operator or "").strip()
        if not normalized_operator:
            raise ValueError("operator is required for anomaly event status updates")

        def _update(cursor) -> None:
            cursor.execute(
                """
                UPDATE industrial_anomaly_events
                SET status = ?, ack_by = ?, ack_at = ?, comment = ?
                WHERE id = ?
                """,
                (status, normalized_operator, updated_at, comment, int(event_id)),
            )
            if cursor.rowcount < 1:
                raise ValueError(f"anomaly event not found: {event_id}")

        run_transaction_with_retry(self.database, _update, connection=self.connection)


def _positive_limit(limit: int) -> int:
    value = int(limit)
    if value < 1:
        raise ValueError("limit must be positive")
    return value


def _validate_status(status: str) -> None:
    if status not in ANOMALY_EVENT_STATUSES:
        raise ValueError(f"unsupported anomaly event status: {status}")


def _row_to_event(row) -> PersistedAnomalyEvent:
    return PersistedAnomalyEvent(
        id=int(row[0]),
        sample_id=int(row[1]),
        signal_id=int(row[2]),
        event_time=str(row[3]),
        detector_key=str(row[4]),
        severity=str(row[5]),
        score=float(row[6]),
        observed_value=float(row[7]),
        expected_value=float(row[8]) if row[8] is not None else None,
        threshold=dict(from_json(row[9], {})),
        explanation=str(row[10]),
        context=dict(from_json(row[11], {})),
        status=str(row[12]),
        created_at=str(row[13]),
        ack_by=row[14],
        ack_at=row[15],
        comment=row[16],
    )

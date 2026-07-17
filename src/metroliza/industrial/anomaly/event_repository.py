"""Persistence helpers for realtime industrial anomaly events."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

from metroliza.industrial.anomaly.contracts import ANOMALY_SEVERITIES, DetectionResult
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.realtime.sample_repository import from_json, to_json, utc_timestamp
from metroliza.industrial.realtime.numeric_validation import exact_integral
from metroliza.industrial.realtime.timestamps import canonical_utc_timestamp
from metroliza.reports.db import run_transaction_with_retry

ANOMALY_EVENT_STATUSES = ("open", "acknowledged", "resolved", "false_positive")


class AnomalyEventStatusConflictError(RuntimeError):
    """Raised when an event changed after an operator loaded it for review."""

    def __init__(self, event_id: int, expected_status: str, actual_status: str):
        self.event_id = int(event_id)
        self.expected_status = expected_status
        self.actual_status = actual_status
        super().__init__(
            f"anomaly event {self.event_id} status changed from "
            f"{self.expected_status} to {self.actual_status}"
        )


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
        if not event_batch:
            return EventBatchResult(processed=0, inserted=0, skipped=0, event_ids=())
        created_at = utc_timestamp()

        def _insert(cursor) -> EventBatchResult:
            insert_rows = tuple(_event_insert_row(event, created_at) for event in event_batch)
            processed = len(event_batch)
            before_changes = cursor.connection.total_changes
            cursor.executemany(
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
                ON CONFLICT(sample_id, detector_key) DO NOTHING
                """,
                insert_rows,
            )
            inserted = cursor.connection.total_changes - before_changes
            event_ids = _lookup_event_ids(cursor, event_batch)
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
        expected_status: str | None = None,
    ) -> None:
        self.update_event_status(
            event_id=event_id,
            status="acknowledged",
            operator=ack_by,
            comment=comment,
            updated_at=ack_at,
            expected_status=expected_status,
        )

    def resolve_event(
        self,
        *,
        event_id: int,
        resolved_by: str,
        comment: str | None = None,
        resolved_at: str | None = None,
        expected_status: str | None = None,
    ) -> None:
        self.update_event_status(
            event_id=event_id,
            status="resolved",
            operator=resolved_by,
            comment=comment,
            updated_at=resolved_at,
            expected_status=expected_status,
        )

    def mark_event_false_positive(
        self,
        *,
        event_id: int,
        marked_by: str,
        comment: str | None = None,
        marked_at: str | None = None,
        expected_status: str | None = None,
    ) -> None:
        self.update_event_status(
            event_id=event_id,
            status="false_positive",
            operator=marked_by,
            comment=comment,
            updated_at=marked_at,
            expected_status=expected_status,
        )

    def update_event_status(
        self,
        *,
        event_id: int,
        status: str,
        operator: str,
        comment: str | None = None,
        updated_at: str | None = None,
        expected_status: str | None = None,
    ) -> None:
        self.ensure_schema()
        _validate_status(status)
        updated_at = canonical_utc_timestamp(updated_at or utc_timestamp())
        normalized_operator = str(operator or "").strip()
        if not normalized_operator:
            raise ValueError("operator is required for anomaly event status updates")
        if expected_status is not None:
            _validate_status(expected_status)

        def _update(cursor) -> None:
            params = [status, normalized_operator, updated_at, comment, int(event_id)]
            if expected_status is None:
                cursor.execute(
                    """
                    UPDATE industrial_anomaly_events
                    SET status = ?, ack_by = ?, ack_at = ?, comment = ?
                    WHERE id = ?
                    """,
                    tuple(params),
                )
            else:
                cursor.execute(
                    """
                    UPDATE industrial_anomaly_events
                    SET status = ?, ack_by = ?, ack_at = ?, comment = ?
                    WHERE id = ? AND status = ?
                    """,
                    (*params, expected_status),
                )
            if cursor.rowcount < 1:
                cursor.execute(
                    "SELECT status FROM industrial_anomaly_events WHERE id = ?",
                    (int(event_id),),
                )
                row = cursor.fetchone()
                if row is not None and expected_status is not None:
                    raise AnomalyEventStatusConflictError(
                        int(event_id),
                        expected_status,
                        str(row[0]),
                    )
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


def _event_insert_row(event: DetectionResult, created_at: str) -> tuple[Any, ...]:
    sample_id = _positive_id("DetectionResult.sample_id", event.sample_id)
    signal_id = _positive_id("DetectionResult.signal_id", event.signal_id)
    detector_key = str(event.detector_key or "").strip()
    if not detector_key:
        raise ValueError("DetectionResult.detector_key is required for persistence")
    severity = str(event.severity or "").strip().lower()
    if severity not in ANOMALY_SEVERITIES:
        raise ValueError(f"unsupported anomaly severity: {event.severity}")
    event_time = canonical_utc_timestamp(event.event_time)
    score = _finite_number("DetectionResult.score", event.score)
    observed_value = _finite_number("DetectionResult.observed_value", event.observed_value)
    expected_value = (
        None
        if event.expected_value is None
        else _finite_number("DetectionResult.expected_value", event.expected_value)
    )
    explanation = str(event.explanation or "").strip()
    if not explanation:
        raise ValueError("DetectionResult.explanation is required for persistence")
    return (
        sample_id,
        signal_id,
        event_time,
        detector_key,
        severity,
        score,
        observed_value,
        expected_value,
        to_json(dict(event.threshold)),
        explanation,
        to_json(dict(event.context)),
        canonical_utc_timestamp(created_at),
    )


def _positive_id(field_name: str, value: Any) -> int:
    if value is None:
        raise ValueError(f"{field_name} is required for persistence")
    try:
        return exact_integral(value, field_name=field_name, minimum=1)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be positive") from exc


def _finite_number(field_name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _lookup_event_ids(cursor, events: tuple[DetectionResult, ...]) -> list[int]:
    cursor.execute("DROP TABLE IF EXISTS temp._metroliza_event_key_lookup")
    cursor.execute(
        """
        CREATE TEMP TABLE _metroliza_event_key_lookup (
            event_order INTEGER PRIMARY KEY,
            sample_id INTEGER NOT NULL,
            detector_key TEXT NOT NULL
        )
        """
    )
    cursor.executemany(
        """
        INSERT INTO _metroliza_event_key_lookup (
            event_order,
            sample_id,
            detector_key
        )
        VALUES (?, ?, ?)
        """,
        (
            (index, int(event.sample_id), event.detector_key)
            for index, event in enumerate(events)
        ),
    )
    cursor.execute(
        """
        SELECT lookup.event_order, events.id
        FROM _metroliza_event_key_lookup AS lookup
        JOIN industrial_anomaly_events AS events
          ON events.sample_id = lookup.sample_id
         AND events.detector_key = lookup.detector_key
        ORDER BY lookup.event_order ASC
        """
    )
    rows = cursor.fetchall()
    cursor.execute("DROP TABLE IF EXISTS temp._metroliza_event_key_lookup")
    return [int(row[1]) for row in rows]


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

"""Repository for durable realtime industrial stream events and consumer offsets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import math
from typing import Any

from metroliza.industrial.industrial_data_repository import (
    looks_sensitive_key,
    redact_payload_text,
    redact_sensitive_text,
)
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.json_safety import to_json_storage_text
from metroliza.industrial.realtime.event_stream import (
    ANOMALY_EVENTS_COMMITTED_EVENT_TYPE,
    SAMPLE_BATCH_COMMITTED_EVENT_TYPE,
    RealtimeConsumerOffset,
    RealtimeStreamAppendResult,
    RealtimeStreamEvent,
)
from metroliza.industrial.realtime.sample_repository import utc_timestamp
from metroliza.reports.db import run_transaction_with_retry

_SQL_PAYLOAD_KEYS = frozenset({"sql", "sqltext", "sql_text", "statement", "query", "rawsql", "raw_sql"})


class RealtimeEventStreamRepository:
    """Append and consume durable realtime industrial stream events."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

    def append_event(self, event: RealtimeStreamEvent) -> RealtimeStreamAppendResult:
        return self.append_events((event,))

    def append_events(self, events: Iterable[RealtimeStreamEvent]) -> RealtimeStreamAppendResult:
        self.ensure_schema()
        event_batch = tuple(events)
        if not event_batch:
            return RealtimeStreamAppendResult(processed=0, inserted=0, skipped=0)
        created_at = utc_timestamp()

        def _append(cursor) -> RealtimeStreamAppendResult:
            processed = len(event_batch)
            before_changes = cursor.connection.total_changes
            cursor.executemany(
                """
                INSERT OR IGNORE INTO industrial_realtime_stream_events (
                    source_profile_id,
                    stream_key,
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    sample_id,
                    anomaly_event_id,
                    idempotency_key,
                    event_time,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(_event_insert_row(event, created_at) for event in event_batch),
            )
            inserted = cursor.connection.total_changes - before_changes
            event_ids = _lookup_event_ids(cursor, event_batch)
            return RealtimeStreamAppendResult(
                processed=processed,
                inserted=inserted,
                skipped=processed - inserted,
                event_ids=tuple(event_ids),
            )

        return run_transaction_with_retry(self.database, _append, connection=self.connection)

    def append_sample_batch_committed(
        self,
        *,
        source_profile_id: int,
        stream_key: str,
        sample_ids: Iterable[int],
        signal_ids: Iterable[int] = (),
        detectors: Iterable[str] = (),
        idempotency_key: str | None = None,
        event_time: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> RealtimeStreamAppendResult:
        normalized_sample_ids = tuple(_positive_int("sample_id", sample_id) for sample_id in sample_ids)
        if not normalized_sample_ids:
            return RealtimeStreamAppendResult(processed=0, inserted=0, skipped=0)
        normalized_signal_ids = tuple(dict.fromkeys(_positive_int("signal_id", signal_id) for signal_id in signal_ids))
        normalized_detectors = tuple(
            dict.fromkeys(str(detector).strip() for detector in detectors if str(detector).strip())
        )
        event_payload = dict(payload or {})
        event_payload.update(
            {
                "source_profile_id": _positive_int("source_profile_id", source_profile_id),
                "stream_key": _required_text("stream_key", stream_key),
                "sample_ids": list(normalized_sample_ids),
                "sample_count": len(normalized_sample_ids),
            }
        )
        if normalized_signal_ids:
            event_payload["signal_ids"] = list(normalized_signal_ids)
        if normalized_detectors:
            event_payload["detectors"] = list(normalized_detectors)
        event = RealtimeStreamEvent(
            source_profile_id=source_profile_id,
            stream_key=stream_key,
            event_type=SAMPLE_BATCH_COMMITTED_EVENT_TYPE,
            aggregate_type="sample_batch",
            aggregate_id=normalized_sample_ids[0],
            sample_id=normalized_sample_ids[0],
            idempotency_key=idempotency_key
            or sample_batch_idempotency_key(
                source_profile_id=source_profile_id,
                stream_key=stream_key,
                sample_ids=normalized_sample_ids,
                event_time=event_time,
                payload=event_payload,
            ),
            event_time=event_time or utc_timestamp(),
            payload=event_payload,
        )
        return self.append_event(event)

    def append_anomaly_events_committed(
        self,
        *,
        source_profile_id: int,
        stream_key: str,
        source_event_id: int,
        anomaly_event_ids: Iterable[int],
        sample_ids: Iterable[int] = (),
        inserted: int = 0,
        skipped: int = 0,
    ) -> RealtimeStreamAppendResult:
        normalized_event_ids = tuple(_positive_int("anomaly_event_id", event_id) for event_id in anomaly_event_ids)
        if not normalized_event_ids:
            return RealtimeStreamAppendResult(processed=0, inserted=0, skipped=0)
        normalized_sample_ids = tuple(_positive_int("sample_id", sample_id) for sample_id in sample_ids)
        payload = {
            "source_profile_id": _positive_int("source_profile_id", source_profile_id),
            "stream_key": _required_text("stream_key", stream_key),
            "sample_batch_event_id": _positive_int("source_event_id", source_event_id),
            "sample_ids": list(normalized_sample_ids),
            "anomaly_event_ids": list(normalized_event_ids),
            "detector_events_inserted": int(inserted),
            "detector_events_skipped": int(skipped),
        }
        event = RealtimeStreamEvent(
            source_profile_id=source_profile_id,
            stream_key=stream_key,
            event_type=ANOMALY_EVENTS_COMMITTED_EVENT_TYPE,
            aggregate_type="anomaly_event_batch",
            aggregate_id=normalized_event_ids[0],
            sample_id=normalized_sample_ids[0] if normalized_sample_ids else None,
            anomaly_event_id=normalized_event_ids[0],
            idempotency_key=f"{ANOMALY_EVENTS_COMMITTED_EVENT_TYPE}:{int(source_event_id)}",
            event_time=utc_timestamp(),
            payload=payload,
        )
        return self.append_event(event)

    def read_events_after(
        self,
        *,
        source_profile_id: int,
        stream_key: str,
        after_event_id: int = 0,
        limit: int = 500,
        event_types: Iterable[str] | None = None,
    ) -> list[RealtimeStreamEvent]:
        self.ensure_schema()
        safe_after_event_id = _non_negative_int("after_event_id", after_event_id)
        safe_limit = _positive_int("limit", limit)
        normalized_event_types = tuple(
            dict.fromkeys(str(event_type).strip() for event_type in (event_types or ()) if str(event_type).strip())
        )

        def _read(cursor) -> list[RealtimeStreamEvent]:
            params: list[Any] = [
                _positive_int("source_profile_id", source_profile_id),
                _required_text("stream_key", stream_key),
                safe_after_event_id,
            ]
            event_type_clause = ""
            if normalized_event_types:
                placeholders = ", ".join("?" for _ in normalized_event_types)
                event_type_clause = f"AND event_type IN ({placeholders})"
                params.extend(normalized_event_types)
            params.append(safe_limit)
            cursor.execute(
                f"""
                SELECT
                    event_id,
                    source_profile_id,
                    stream_key,
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    sample_id,
                    anomaly_event_id,
                    idempotency_key,
                    event_time,
                    payload_json,
                    created_at
                FROM industrial_realtime_stream_events
                WHERE source_profile_id = ?
                  AND stream_key = ?
                  AND event_id > ?
                  {event_type_clause}
                ORDER BY event_id ASC
                LIMIT ?
                """,
                tuple(params),
            )
            return [_row_to_event(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _read, connection=self.connection)

    def get_consumer_offset(
        self,
        *,
        consumer_key: str,
        source_profile_id: int,
        stream_key: str,
    ) -> RealtimeConsumerOffset | None:
        self.ensure_schema()

        def _get(cursor) -> RealtimeConsumerOffset | None:
            return _select_consumer_offset(
                cursor,
                consumer_key=_required_text("consumer_key", consumer_key),
                source_profile_id=_positive_int("source_profile_id", source_profile_id),
                stream_key=_required_text("stream_key", stream_key),
            )

        return run_transaction_with_retry(self.database, _get, connection=self.connection)

    def update_consumer_offset(
        self,
        *,
        consumer_key: str,
        source_profile_id: int,
        stream_key: str,
        last_event_id: int,
        updated_at: str | None = None,
    ) -> RealtimeConsumerOffset:
        self.ensure_schema()
        now = updated_at or utc_timestamp()

        def _update(cursor) -> RealtimeConsumerOffset:
            normalized_consumer_key = _required_text("consumer_key", consumer_key)
            normalized_source_profile_id = _positive_int("source_profile_id", source_profile_id)
            normalized_stream_key = _required_text("stream_key", stream_key)
            cursor.execute(
                """
                INSERT INTO industrial_realtime_consumer_offsets (
                    consumer_key,
                    source_profile_id,
                    stream_key,
                    last_event_id,
                    last_success_at,
                    last_error,
                    failure_count,
                    status,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, 0, 'idle', ?)
                ON CONFLICT(consumer_key, source_profile_id, stream_key) DO UPDATE SET
                    last_event_id = excluded.last_event_id,
                    last_success_at = excluded.last_success_at,
                    last_error = NULL,
                    failure_count = 0,
                    status = 'idle',
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_consumer_key,
                    normalized_source_profile_id,
                    normalized_stream_key,
                    _non_negative_int("last_event_id", last_event_id),
                    now,
                    now,
                ),
            )
            offset = _select_consumer_offset(
                cursor,
                consumer_key=normalized_consumer_key,
                source_profile_id=normalized_source_profile_id,
                stream_key=normalized_stream_key,
            )
            assert offset is not None
            return offset

        return run_transaction_with_retry(self.database, _update, connection=self.connection)

    def mark_consumer_failure(
        self,
        *,
        consumer_key: str,
        source_profile_id: int,
        stream_key: str,
        error: Any,
        updated_at: str | None = None,
    ) -> RealtimeConsumerOffset:
        self.ensure_schema()
        now = updated_at or utc_timestamp()
        normalized_error = redact_sensitive_text(error, max_len=500)

        def _failure(cursor) -> RealtimeConsumerOffset:
            normalized_consumer_key = _required_text("consumer_key", consumer_key)
            normalized_source_profile_id = _positive_int("source_profile_id", source_profile_id)
            normalized_stream_key = _required_text("stream_key", stream_key)
            existing = _select_consumer_offset(
                cursor,
                consumer_key=normalized_consumer_key,
                source_profile_id=normalized_source_profile_id,
                stream_key=normalized_stream_key,
            )
            existing_event_id = existing.last_event_id if existing is not None else 0
            cursor.execute(
                """
                INSERT INTO industrial_realtime_consumer_offsets (
                    consumer_key,
                    source_profile_id,
                    stream_key,
                    last_event_id,
                    last_success_at,
                    last_error,
                    failure_count,
                    status,
                    updated_at
                )
                VALUES (?, ?, ?, ?, NULL, ?, 1, 'failed', ?)
                ON CONFLICT(consumer_key, source_profile_id, stream_key) DO UPDATE SET
                    last_error = excluded.last_error,
                    failure_count = industrial_realtime_consumer_offsets.failure_count + 1,
                    status = 'failed',
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_consumer_key,
                    normalized_source_profile_id,
                    normalized_stream_key,
                    existing_event_id,
                    normalized_error,
                    now,
                ),
            )
            offset = _select_consumer_offset(
                cursor,
                consumer_key=normalized_consumer_key,
                source_profile_id=normalized_source_profile_id,
                stream_key=normalized_stream_key,
            )
            assert offset is not None
            return offset

        return run_transaction_with_retry(self.database, _failure, connection=self.connection)


def sample_batch_idempotency_key(
    *,
    source_profile_id: int,
    stream_key: str,
    sample_ids: Sequence[int],
    event_time: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> str:
    payload_parts = {
        "event_time": event_time,
        "cursor_value": (payload or {}).get("cursor_value"),
        "cursor_tie_breaker_value": (payload or {}).get("cursor_tie_breaker_value"),
        "event_time_watermark": (payload or {}).get("event_time_watermark"),
        "sample_ids": tuple(int(sample_id) for sample_id in sample_ids),
    }
    digest = hashlib.sha256(json.dumps(payload_parts, sort_keys=True, default=str).encode()).hexdigest()
    return f"{SAMPLE_BATCH_COMMITTED_EVENT_TYPE}:{int(source_profile_id)}:{stream_key}:{digest[:32]}"


def _event_insert_row(event: RealtimeStreamEvent, default_created_at: str) -> tuple[Any, ...]:
    event_time = event.event_time or event.created_at or default_created_at
    return (
        _positive_int("source_profile_id", event.source_profile_id),
        _required_text("stream_key", event.stream_key),
        _required_text("event_type", event.event_type),
        _required_text("aggregate_type", event.aggregate_type),
        _optional_positive_int("aggregate_id", event.aggregate_id),
        _optional_positive_int("sample_id", event.sample_id),
        _optional_positive_int("anomaly_event_id", event.anomaly_event_id),
        _required_text("idempotency_key", event.idempotency_key),
        event_time,
        _payload_to_json(event.payload),
        event.created_at or default_created_at,
    )


def _lookup_event_ids(cursor, events: tuple[RealtimeStreamEvent, ...]) -> list[int]:
    cursor.execute("DROP TABLE IF EXISTS temp._metroliza_stream_event_key_lookup")
    cursor.execute(
        """
        CREATE TEMP TABLE _metroliza_stream_event_key_lookup (
            event_order INTEGER PRIMARY KEY,
            source_profile_id INTEGER NOT NULL,
            stream_key TEXT NOT NULL,
            idempotency_key TEXT NOT NULL
        )
        """
    )
    cursor.executemany(
        """
        INSERT INTO _metroliza_stream_event_key_lookup (
            event_order,
            source_profile_id,
            stream_key,
            idempotency_key
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            (
                index,
                _positive_int("source_profile_id", event.source_profile_id),
                _required_text("stream_key", event.stream_key),
                _required_text("idempotency_key", event.idempotency_key),
            )
            for index, event in enumerate(events)
        ),
    )
    cursor.execute(
        """
        SELECT lookup.event_order, events.event_id
        FROM _metroliza_stream_event_key_lookup AS lookup
        JOIN industrial_realtime_stream_events AS events
          ON events.source_profile_id = lookup.source_profile_id
         AND events.stream_key = lookup.stream_key
         AND events.idempotency_key = lookup.idempotency_key
        ORDER BY lookup.event_order ASC
        """
    )
    rows = cursor.fetchall()
    cursor.execute("DROP TABLE IF EXISTS temp._metroliza_stream_event_key_lookup")
    return [int(row[1]) for row in rows]


def _select_consumer_offset(
    cursor,
    *,
    consumer_key: str,
    source_profile_id: int,
    stream_key: str,
) -> RealtimeConsumerOffset | None:
    cursor.execute(
        """
        SELECT
            id,
            consumer_key,
            source_profile_id,
            stream_key,
            last_event_id,
            last_success_at,
            last_error,
            failure_count,
            status,
            updated_at
        FROM industrial_realtime_consumer_offsets
        WHERE consumer_key = ?
          AND source_profile_id = ?
          AND stream_key = ?
        """,
        (consumer_key, source_profile_id, stream_key),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_to_consumer_offset(row)


def _row_to_event(row: tuple[Any, ...]) -> RealtimeStreamEvent:
    payload = _from_json(row[10], {})
    if not isinstance(payload, Mapping):
        payload = {"value": payload}
    return RealtimeStreamEvent(
        event_id=int(row[0]),
        source_profile_id=int(row[1]),
        stream_key=str(row[2]),
        event_type=str(row[3]),
        aggregate_type=str(row[4]),
        aggregate_id=int(row[5]) if row[5] is not None else None,
        sample_id=int(row[6]) if row[6] is not None else None,
        anomaly_event_id=int(row[7]) if row[7] is not None else None,
        idempotency_key=str(row[8]),
        event_time=str(row[9]),
        payload=dict(payload),
        created_at=str(row[11]),
    )


def _row_to_consumer_offset(row: tuple[Any, ...]) -> RealtimeConsumerOffset:
    return RealtimeConsumerOffset(
        id=int(row[0]),
        consumer_key=str(row[1]),
        source_profile_id=int(row[2]),
        stream_key=str(row[3]),
        last_event_id=int(row[4]),
        last_success_at=row[5],
        last_error=row[6],
        failure_count=int(row[7]),
        status=str(row[8]),
        updated_at=str(row[9]),
    )


def _payload_to_json(payload: Mapping[str, Any]) -> str:
    redacted_payload = _redact_json_payload(dict(payload or {}))
    return to_json_storage_text(redacted_payload) or "{}"


def _redact_json_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key)
            if looks_sensitive_key(key_text) or _compact_key(key_text) in _SQL_PAYLOAD_KEYS:
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = _redact_json_payload(nested)
        return redacted
    if isinstance(value, list | tuple):
        return [_redact_json_payload(item) for item in value]
    if isinstance(value, set | frozenset):
        return [_redact_json_payload(item) for item in sorted(value, key=repr)]
    if isinstance(value, BaseException):
        return redact_sensitive_text(value, max_len=None)
    if isinstance(value, str):
        return redact_payload_text(value, max_len=None)
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _from_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, dict | list):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _required_text(field_name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _positive_int(field_name: str, value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def _optional_positive_int(field_name: str, value: Any) -> int | None:
    if value is None:
        return None
    return _positive_int(field_name, value)


def _non_negative_int(field_name: str, value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be zero or greater") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be zero or greater")
    return parsed


def _compact_key(key: str) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())

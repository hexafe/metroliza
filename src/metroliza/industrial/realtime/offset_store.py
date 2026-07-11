"""Persistence helpers for realtime industrial stream offsets."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.realtime.stream_contracts import StreamOffset
from metroliza.industrial.realtime.timestamps import (
    canonical_utc_timestamp,
    parse_utc_timestamp,
)
from metroliza.reports.db import run_transaction_with_retry

_EXPECTED_NOT_SET = object()


class StreamOffsetConflictError(RuntimeError):
    """Raised when a stale or regressive writer tries to replace a source checkpoint."""


class StreamOffsetStore:
    """Store and retrieve idempotent source stream cursors."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

    def upsert_offset(
        self,
        offset: StreamOffset,
        *,
        expected_offset: StreamOffset | None | object = _EXPECTED_NOT_SET,
        _cursor=None,
    ) -> StreamOffset:
        """Persist a monotonic offset, optionally comparing against the reader's checkpoint."""

        if _cursor is None:
            self.ensure_schema()

        def _upsert(cursor) -> StreamOffset:
            existing = _select_offset(
                cursor,
                source_profile_id=offset.source_profile_id,
                stream_key=offset.stream_key,
            )
            if expected_offset is not _EXPECTED_NOT_SET and not _same_checkpoint(
                existing,
                expected_offset,
            ):
                raise StreamOffsetConflictError(
                    "Realtime source offset changed after it was read; stale writer rejected."
                )
            normalized = _normalized_offset(offset)
            if existing is not None:
                _require_monotonic_progress(existing, normalized)
                cursor.execute(
                    """
                    UPDATE industrial_stream_offsets
                    SET cursor_column = ?, cursor_value = ?, cursor_tie_breaker_column = ?,
                        cursor_tie_breaker_value = ?, event_time_watermark = ?,
                        last_success_at = ?, last_error = ?, lag_seconds = ?, status = ?
                    WHERE id = ?
                    """,
                    (
                        normalized.cursor_column,
                        normalized.cursor_value,
                        normalized.cursor_tie_breaker_column,
                        normalized.cursor_tie_breaker_value,
                        normalized.event_time_watermark,
                        normalized.last_success_at,
                        normalized.last_error,
                        normalized.lag_seconds,
                        normalized.status,
                        existing.id,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO industrial_stream_offsets (
                        source_profile_id, stream_key, cursor_column, cursor_value,
                        cursor_tie_breaker_column, cursor_tie_breaker_value,
                        event_time_watermark, last_success_at, last_error, lag_seconds, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized.source_profile_id,
                        normalized.stream_key,
                        normalized.cursor_column,
                        normalized.cursor_value,
                        normalized.cursor_tie_breaker_column,
                        normalized.cursor_tie_breaker_value,
                        normalized.event_time_watermark,
                        normalized.last_success_at,
                        normalized.last_error,
                        normalized.lag_seconds,
                        normalized.status,
                    ),
                )
            saved = _select_offset(
                cursor,
                source_profile_id=offset.source_profile_id,
                stream_key=offset.stream_key,
            )
            assert saved is not None
            return saved

        if _cursor is not None:
            return _upsert(_cursor)
        return run_transaction_with_retry(self.database, _upsert, connection=self.connection)

    def mark_failure(
        self,
        *,
        source_profile_id: int,
        stream_key: str,
        cursor_column: str,
        error: str,
        expected_offset: StreamOffset | None | object = _EXPECTED_NOT_SET,
    ) -> StreamOffset | None:
        """Mark a stream failed only if its checkpoint still matches the failed attempt."""

        self.ensure_schema()

        def _mark(cursor) -> StreamOffset:
            existing = _select_offset(
                cursor,
                source_profile_id=source_profile_id,
                stream_key=stream_key,
            )
            if expected_offset is not _EXPECTED_NOT_SET and not _same_checkpoint(
                existing,
                expected_offset,
            ):
                return existing
            if existing is None:
                candidate = StreamOffset(
                    source_profile_id=source_profile_id,
                    stream_key=stream_key,
                    cursor_column=cursor_column,
                    last_error=error,
                    status="failed",
                )
                return self.upsert_offset(candidate, expected_offset=None, _cursor=cursor)
            cursor.execute(
                """
                UPDATE industrial_stream_offsets
                SET last_error = ?, status = 'failed'
                WHERE id = ?
                """,
                (error, existing.id),
            )
            saved = _select_offset(
                cursor,
                source_profile_id=source_profile_id,
                stream_key=stream_key,
            )
            assert saved is not None
            return saved

        return run_transaction_with_retry(self.database, _mark, connection=self.connection)

    def get_offset(
        self,
        *,
        source_profile_id: int,
        stream_key: str,
        _ensure: bool = True,
    ) -> StreamOffset | None:
        if _ensure:
            self.ensure_schema()

        def _get(cursor) -> StreamOffset | None:
            cursor.execute(
                """
                SELECT
                    id,
                    source_profile_id,
                    stream_key,
                    cursor_column,
                    cursor_value,
                    cursor_tie_breaker_column,
                    cursor_tie_breaker_value,
                    event_time_watermark,
                    last_success_at,
                    last_error,
                    lag_seconds,
                    status
                FROM industrial_stream_offsets
                WHERE source_profile_id = ? AND stream_key = ?
                """,
                (source_profile_id, stream_key),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_offset(row)

        return run_transaction_with_retry(self.database, _get, connection=self.connection)


def _select_offset(cursor, *, source_profile_id: int, stream_key: str) -> StreamOffset | None:
    cursor.execute(
        """
        SELECT
            id, source_profile_id, stream_key, cursor_column, cursor_value,
            cursor_tie_breaker_column, cursor_tie_breaker_value, event_time_watermark,
            last_success_at, last_error, lag_seconds, status
        FROM industrial_stream_offsets
        WHERE source_profile_id = ? AND stream_key = ?
        """,
        (source_profile_id, stream_key),
    )
    row = cursor.fetchone()
    return _row_to_offset(row) if row is not None else None


def _row_to_offset(row) -> StreamOffset:
    return StreamOffset(
        id=int(row[0]),
        source_profile_id=int(row[1]),
        stream_key=str(row[2]),
        cursor_column=str(row[3]),
        cursor_value=row[4],
        cursor_tie_breaker_column=row[5],
        cursor_tie_breaker_value=row[6],
        event_time_watermark=row[7],
        last_success_at=row[8],
        last_error=row[9],
        lag_seconds=float(row[10]) if row[10] is not None else None,
        status=str(row[11]),
    )


def _canonical_optional(value: str | None) -> str | None:
    return canonical_utc_timestamp(value) if value else None


def _normalized_offset(offset: StreamOffset) -> StreamOffset:
    return StreamOffset(
        id=offset.id,
        source_profile_id=offset.source_profile_id,
        stream_key=offset.stream_key,
        cursor_column=offset.cursor_column,
        cursor_value=offset.cursor_value,
        cursor_tie_breaker_column=offset.cursor_tie_breaker_column,
        cursor_tie_breaker_value=offset.cursor_tie_breaker_value,
        event_time_watermark=_canonical_optional(offset.event_time_watermark),
        last_success_at=_canonical_optional(offset.last_success_at),
        last_error=offset.last_error,
        lag_seconds=offset.lag_seconds,
        status=offset.status,
    )


def _same_checkpoint(existing: StreamOffset | None, expected: Any) -> bool:
    if existing is None or expected is None:
        return existing is expected
    if not isinstance(expected, StreamOffset):
        return False
    return (
        existing.id,
        existing.cursor_column,
        existing.cursor_value,
        existing.cursor_tie_breaker_column,
        existing.cursor_tie_breaker_value,
        existing.event_time_watermark,
    ) == (
        expected.id,
        expected.cursor_column,
        expected.cursor_value,
        expected.cursor_tie_breaker_column,
        expected.cursor_tie_breaker_value,
        _canonical_optional(expected.event_time_watermark),
    )


def _require_monotonic_progress(existing: StreamOffset, candidate: StreamOffset) -> None:
    existing_cursor = (existing.cursor_value, existing.cursor_tie_breaker_value)
    candidate_cursor = (candidate.cursor_value, candidate.cursor_tie_breaker_value)
    if _compare_composite(candidate_cursor, existing_cursor) < 0:
        raise StreamOffsetConflictError("Realtime source cursor regression rejected.")
    if existing.event_time_watermark and not candidate.event_time_watermark:
        raise StreamOffsetConflictError("Realtime event-time watermark regression rejected.")
    if (
        existing.event_time_watermark
        and candidate.event_time_watermark
        and candidate.event_time_watermark < existing.event_time_watermark
    ):
        raise StreamOffsetConflictError("Realtime event-time watermark regression rejected.")


def _compare_composite(left: tuple[Any, Any], right: tuple[Any, Any]) -> int:
    primary = _compare_scalar(left[0], right[0])
    return primary if primary else _compare_scalar(left[1], right[1])


def _compare_scalar(left: Any, right: Any) -> int:
    if left in (None, "") or right in (None, ""):
        return (left not in (None, "")) - (right not in (None, ""))
    left_text = str(left)
    right_text = str(right)
    try:
        left_decimal = Decimal(left_text)
        right_decimal = Decimal(right_text)
        if left_decimal.is_finite() and right_decimal.is_finite():
            return (left_decimal > right_decimal) - (left_decimal < right_decimal)
    except InvalidOperation:
        pass
    try:
        left_time = parse_utc_timestamp(left_text)
        right_time = parse_utc_timestamp(right_text)
        return (left_time > right_time) - (left_time < right_time)
    except ValueError:
        return (left_text > right_text) - (left_text < right_text)

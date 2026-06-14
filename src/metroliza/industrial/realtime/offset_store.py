"""Persistence helpers for realtime industrial stream offsets."""

from __future__ import annotations

from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.realtime.sample_repository import utc_timestamp
from metroliza.industrial.realtime.stream_contracts import StreamOffset
from metroliza.reports.db import run_transaction_with_retry


class StreamOffsetStore:
    """Store and retrieve idempotent source stream cursors."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

    def upsert_offset(self, offset: StreamOffset) -> StreamOffset:
        self.ensure_schema()

        def _upsert(cursor) -> StreamOffset:
            cursor.execute(
                """
                INSERT INTO industrial_stream_offsets (
                    source_profile_id,
                    stream_key,
                    cursor_column,
                    cursor_value,
                    event_time_watermark,
                    last_success_at,
                    last_error,
                    lag_seconds,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_profile_id, stream_key) DO UPDATE SET
                    cursor_column = excluded.cursor_column,
                    cursor_value = excluded.cursor_value,
                    event_time_watermark = excluded.event_time_watermark,
                    last_success_at = excluded.last_success_at,
                    last_error = excluded.last_error,
                    lag_seconds = excluded.lag_seconds,
                    status = excluded.status
                """,
                (
                    offset.source_profile_id,
                    offset.stream_key,
                    offset.cursor_column,
                    offset.cursor_value,
                    offset.event_time_watermark,
                    offset.last_success_at or utc_timestamp(),
                    offset.last_error,
                    offset.lag_seconds,
                    offset.status,
                ),
            )
            cursor.execute(
                """
                SELECT
                    id,
                    source_profile_id,
                    stream_key,
                    cursor_column,
                    cursor_value,
                    event_time_watermark,
                    last_success_at,
                    last_error,
                    lag_seconds,
                    status
                FROM industrial_stream_offsets
                WHERE source_profile_id = ? AND stream_key = ?
                """,
                (offset.source_profile_id, offset.stream_key),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_offset(row)

        result = run_transaction_with_retry(self.database, _upsert, connection=self.connection)
        assert result is not None
        return result

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


def _row_to_offset(row) -> StreamOffset:
    return StreamOffset(
        id=int(row[0]),
        source_profile_id=int(row[1]),
        stream_key=str(row[2]),
        cursor_column=str(row[3]),
        cursor_value=row[4],
        event_time_watermark=row[5],
        last_success_at=row[6],
        last_error=row[7],
        lag_seconds=float(row[8]) if row[8] is not None else None,
        status=str(row[9]),
    )

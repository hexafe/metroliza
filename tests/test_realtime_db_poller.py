from __future__ import annotations

import pytest

from metroliza.industrial.industrial_source_config import build_source_profile
from metroliza.industrial.realtime.db_poller import (
    SourceReadResult,
    build_poll_query,
    with_computed_watermarks,
)
from metroliza.industrial.realtime.stream_config import (
    RealtimeStreamConfig,
    RealtimeStreamConfigError,
    StreamPollPolicy,
    safe_query_diagnostics,
)
from metroliza.industrial.realtime.stream_contracts import StreamOffset


def _profile(database_type: str = "mysql"):
    return build_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="line_a",
        database_type=database_type,
        host="db.example.invalid",
        port=3306 if database_type == "mysql" else 1433,
        database_name="process",
        source_object_name="measurements",
        allowed_columns=("record_id", "process_timestamp", "metric_value", "station"),
        timestamp_column="process_timestamp",
        default_pagination_column="record_id",
    )


def _config(policy: StreamPollPolicy | None = None):
    return RealtimeStreamConfig(
        source_profile_id=1,
        stream_key="diameter",
        signal_key="diameter",
        metric_column="metric_value",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        segment_fields=("station",),
        policy=policy or StreamPollPolicy(batch_limit=25, timeout_seconds=8),
    )


def test_build_poll_query_generates_bounded_mysql_sql_without_raw_diagnostics():
    query = build_poll_query(
        _profile("mysql"),
        _config(),
        StreamOffset(
            source_profile_id=1,
            stream_key="diameter",
            cursor_column="record_id",
            cursor_value="100",
        ),
    )

    assert "SELECT `record_id`, `process_timestamp`, `metric_value`, `station`" in query.sql_text
    assert "WHERE `record_id` > '100'" in query.sql_text
    assert "ORDER BY `record_id` ASC LIMIT 25" in query.sql_text
    assert query.limit == 25
    assert query.timeout_seconds == 8
    assert query.summary["limit"] == 25
    diagnostics = safe_query_diagnostics(sql_text=query.sql_text, query_summary=query.summary)
    assert "sql_hash" in diagnostics
    assert "select" not in repr(diagnostics).lower()


def test_build_poll_query_generates_bounded_mssql_sql():
    query = build_poll_query(_profile("mssql"), _config(), None)

    assert query.sql_text.startswith("SELECT TOP 25 [record_id], [process_timestamp]")
    assert "ORDER BY [record_id] ASC" in query.sql_text
    assert "LIMIT" not in query.sql_text


def test_build_poll_query_rejects_initial_poll_without_cursor_when_disabled():
    with pytest.raises(RealtimeStreamConfigError, match="stored cursor"):
        build_poll_query(
            _profile("mysql"),
            _config(StreamPollPolicy(allow_initial_poll_without_cursor=False)),
            None,
        )


def test_source_read_result_watermarks_are_computed_from_rows():
    result = with_computed_watermarks(
        SourceReadResult(
            rows=(
                {"record_id": "100", "process_timestamp": "2026-06-13T10:00:00Z"},
                {"record_id": "101", "process_timestamp": "2026-06-13T10:01:00Z"},
            )
        ),
        _config(),
    )

    assert result.row_count == 2
    assert result.cursor_value == "101"
    assert result.event_time_watermark == "2026-06-13T10:01:00Z"

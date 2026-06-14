"""Bounded source database polling primitives for realtime industrial streams."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol

from metroliza.industrial.industrial_data_repository import (
    IndustrialSourceProfile,
    redact_sensitive_text,
)
from metroliza.industrial.industrial_workflow_state import require_identifier
from metroliza.industrial.oznak_adapter import fetch_oznak_records_for_source_sql
from metroliza.industrial.realtime.stream_config import (
    RealtimeStreamConfig,
    RealtimeStreamConfigError,
    hash_sql_text,
    realtime_source_columns,
    safe_query_diagnostics,
    validate_stream_config,
)
from metroliza.industrial.realtime.stream_contracts import StreamOffset


@dataclass(frozen=True)
class PollQuery:
    """Generated bounded SQL for one realtime polling read."""

    sql_text: str
    limit: int
    timeout_seconds: float
    sql_hash: str
    summary: Mapping[str, Any]


@dataclass(frozen=True)
class SourceReadRequest:
    """Read request passed to source database reader implementations."""

    profile: IndustrialSourceProfile
    config: RealtimeStreamConfig
    offset: StreamOffset | None
    query: PollQuery


@dataclass(frozen=True)
class SourceReadResult:
    """Rows fetched from a source database plus redacted diagnostics."""

    rows: tuple[Mapping[str, Any], ...] = ()
    row_count: int = 0
    cursor_value: str | None = None
    event_time_watermark: str | None = None
    diagnostics: Mapping[str, Any] | None = None
    error: str | None = None


class SourceDbReader(Protocol):
    """Protocol for test fakes and production Oznak-backed readers."""

    def fetch_rows(self, request: SourceReadRequest) -> SourceReadResult:
        """Fetch rows for one bounded realtime query."""


def build_poll_query(
    profile: IndustrialSourceProfile,
    config: RealtimeStreamConfig,
    offset: StreamOffset | None,
) -> PollQuery:
    """Build safe generated SQL for one bounded realtime polling cycle."""

    validated = validate_stream_config(config, profile)
    if offset is None and not validated.policy.allow_initial_poll_without_cursor:
        raise RealtimeStreamConfigError(
            "Realtime stream requires a stored cursor before polling this source."
        )
    columns = realtime_source_columns(validated)
    table_name = _quote_table_name(profile.source_object_name, profile.database_type)
    column_list = ", ".join(_quote_identifier(column, profile.database_type) for column in columns)
    cursor_column = _quote_identifier(validated.record_key_column, profile.database_type)
    where_clause = ""
    if offset is not None and offset.cursor_value not in (None, ""):
        where_clause = f" WHERE {cursor_column} > {_sql_literal(offset.cursor_value)}"
    limit = int(validated.policy.batch_limit)
    if _dialect(profile) == "mssql":
        sql_text = (
            f"SELECT TOP {limit} {column_list} FROM {table_name}"
            f"{where_clause} ORDER BY {cursor_column} ASC"
        )
    else:
        sql_text = (
            f"SELECT {column_list} FROM {table_name}"
            f"{where_clause} ORDER BY {cursor_column} ASC LIMIT {limit}"
        )
    summary = {
        "source_profile_id": profile.id,
        "source_alias": profile.source_db_alias,
        "stream_key": validated.stream_key,
        "columns": columns,
        "cursor_column": validated.record_key_column,
        "has_cursor": bool(offset and offset.cursor_value not in (None, "")),
        "limit": limit,
        "timeout_seconds": validated.policy.timeout_seconds,
    }
    return PollQuery(
        sql_text=sql_text,
        limit=limit,
        timeout_seconds=validated.policy.timeout_seconds,
        sql_hash=hash_sql_text(sql_text),
        summary=summary,
    )


def summarize_source_rows(
    rows: tuple[Mapping[str, Any], ...],
    config: RealtimeStreamConfig,
) -> tuple[str | None, str | None]:
    """Return cursor and event-time watermark from fetched rows."""

    validated = config.validated()
    cursor_value: str | None = None
    event_time_watermark: str | None = None
    for row in rows:
        raw_cursor = row.get(validated.record_key_column)
        if raw_cursor not in (None, ""):
            cursor_value = str(raw_cursor)
        raw_event_time = row.get(validated.event_time_column)
        if raw_event_time not in (None, ""):
            event_time_watermark = str(raw_event_time)
    return cursor_value, event_time_watermark


def with_computed_watermarks(result: SourceReadResult, config: RealtimeStreamConfig) -> SourceReadResult:
    """Fill missing cursor and event-time watermark values from fetched rows."""

    cursor_value, event_time_watermark = summarize_source_rows(result.rows, config)
    return replace(
        result,
        row_count=result.row_count or len(result.rows),
        cursor_value=result.cursor_value if result.cursor_value not in (None, "") else cursor_value,
        event_time_watermark=(
            result.event_time_watermark
            if result.event_time_watermark not in (None, "")
            else event_time_watermark
        ),
    )


class OznakSqlSourceDbReader:
    """Source reader that delegates bounded generated SQL to the existing Oznak adapter."""

    def __init__(
        self,
        *,
        username: str,
        password: str,
        cancellation_token: Any = None,
        progress_callback: Any = None,
    ):
        self.username = username
        self.password = password
        self.cancellation_token = cancellation_token
        self.progress_callback = progress_callback

    def fetch_rows(self, request: SourceReadRequest) -> SourceReadResult:
        result = fetch_oznak_records_for_source_sql(
            request.profile,
            username=self.username,
            password=self.password,
            sql_text=request.query.sql_text,
            limit=request.query.limit,
            timeout_seconds=request.query.timeout_seconds,
            mode="fetch",
            cancellation_token=self.cancellation_token,
            progress_callback=self.progress_callback,
        )
        rows = tuple(result.records or ())
        cursor_value, event_time_watermark = summarize_source_rows(rows, request.config)
        diagnostics = safe_query_diagnostics(
            sql_text=request.query.sql_text,
            query_summary={
                **dict(request.query.summary),
                "adapter_stage": (result.diagnostics or {}).get("stage"),
                "adapter_error": result.error,
                "implemented": result.implemented,
            },
        )
        return SourceReadResult(
            rows=rows,
            row_count=result.row_count or len(rows),
            cursor_value=cursor_value,
            event_time_watermark=event_time_watermark,
            diagnostics=diagnostics,
            error=redact_sensitive_text(result.error) if result.error else None,
        )


def _quote_table_name(name: str, database_type: str) -> str:
    parts = tuple(part.strip() for part in str(name or "").split(".") if part.strip())
    if not parts:
        raise RealtimeStreamConfigError("Realtime source table/view name must not be empty.")
    for part in parts:
        try:
            require_identifier("source table/view name", part)
        except ValueError as exc:
            raise RealtimeStreamConfigError(str(exc)) from exc
    return ".".join(_quote_identifier(part, database_type) for part in parts)


def _quote_identifier(name: str, database_type: str) -> str:
    try:
        require_identifier("source column", name)
    except ValueError as exc:
        raise RealtimeStreamConfigError(str(exc)) from exc
    if _dialect_name(database_type) == "mssql":
        return f"[{name}]"
    return f"`{name}`"


def _sql_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _dialect(profile: IndustrialSourceProfile) -> str:
    return _dialect_name(profile.database_type)


def _dialect_name(database_type: str) -> str:
    return str(database_type or "").strip().lower()

"""Bounded source database polling helpers for realtime industrial streams."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Mapping, Protocol

from metroliza.industrial.industrial_data_repository import IndustrialSourceProfile
from metroliza.industrial.industrial_workflow_state import require_dotted_identifier, require_identifier
from metroliza.industrial.realtime.stream_config import (
    RealtimePollConfig,
    RealtimeStreamConfigError,
)
from metroliza.industrial.realtime.stream_contracts import StreamOffset


@dataclass(frozen=True)
class PollQuery:
    """Generated bounded source query plus safe diagnostics."""

    sql_text: str
    parameters: tuple[Any, ...]
    limit: int
    timeout_seconds: float
    sql_hash: str
    summary: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceReadRequest:
    """Request passed to a realtime source adapter."""

    profile: IndustrialSourceProfile
    config: RealtimePollConfig
    query: PollQuery
    offset: StreamOffset | None = None


@dataclass(frozen=True)
class SourceReadResult:
    """Rows returned by a realtime source adapter."""

    rows: tuple[Mapping[str, Any], ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None


class SourceDbAdapter(Protocol):
    """Narrow adapter boundary for test fakes and future Oznak realtime readers."""

    def fetch_rows(self, request: SourceReadRequest) -> SourceReadResult:
        """Fetch rows for one bounded realtime source read."""


def build_bounded_poll_query(
    *,
    profile: IndustrialSourceProfile,
    config: RealtimePollConfig,
    offset: StreamOffset | None = None,
) -> PollQuery:
    """Build a generated, bounded SELECT query for one realtime polling cycle."""

    validated = config.validated()
    table_name = _quote_dotted_identifier("source object", profile.source_object_name)
    selected_columns = _validated_selected_columns(profile, validated)
    cursor = _quote_identifier("cursor column", validated.cursor_column)
    where = ""
    parameters: list[Any] = []
    if offset is not None and offset.cursor_value not in (None, ""):
        where = f" WHERE {cursor} > ?"
        parameters.append(offset.cursor_value)
    limit = validated.cycle_limit
    dialect = _normalized_dialect(profile.database_type)
    columns_sql = ", ".join(_quote_identifier("selected column", column) for column in selected_columns)
    if dialect == "mssql":
        parameters = [limit, *parameters]
        sql_text = f"SELECT TOP (?) {columns_sql} FROM {table_name}{where} ORDER BY {cursor} ASC"
    else:
        parameters.append(limit)
        sql_text = f"SELECT {columns_sql} FROM {table_name}{where} ORDER BY {cursor} ASC LIMIT ?"
    sql_hash = hashlib.sha256(sql_text.encode("utf-8")).hexdigest()
    return PollQuery(
        sql_text=sql_text,
        parameters=tuple(parameters),
        limit=limit,
        timeout_seconds=validated.timeout_seconds,
        sql_hash=sql_hash,
        summary={
            "source_profile_id": validated.source_profile_id,
            "source_object": profile.source_object_name,
            "stream_key": validated.stream_key,
            "cursor_column": validated.cursor_column,
            "limit": limit,
            "dialect": dialect,
            "has_cursor": bool(offset and offset.cursor_value not in (None, "")),
            "selected_columns": selected_columns,
            "sql_hash": sql_hash,
        },
    )


def safe_query_diagnostics(query: PollQuery) -> dict[str, Any]:
    """Return operator-safe diagnostics without raw SQL text."""

    return {
        "sql_hash": query.sql_hash,
        "limit": query.limit,
        "timeout_seconds": query.timeout_seconds,
        "summary": dict(query.summary),
    }


def _validated_selected_columns(
    profile: IndustrialSourceProfile,
    config: RealtimePollConfig,
) -> tuple[str, ...]:
    columns = (
        config.record_key_column,
        config.event_time_column,
        config.cursor_column,
        *config.signal_columns.values(),
        *config.context_fields,
    )
    selected = tuple(dict.fromkeys(column for column in columns if column))
    allowed = set(profile.allowed_columns or ())
    if allowed:
        missing = sorted(column for column in selected if column not in allowed)
        if missing:
            raise RealtimeStreamConfigError(
                "Realtime stream references columns outside the source allowlist: "
                + ", ".join(missing)
            )
    return selected


def _quote_identifier(field_name: str, value: str) -> str:
    try:
        require_identifier(field_name, value)
    except ValueError as exc:
        raise RealtimeStreamConfigError(str(exc)) from exc
    return f'"{value}"'


def _quote_dotted_identifier(field_name: str, value: str) -> str:
    try:
        require_dotted_identifier(field_name, value)
    except ValueError as exc:
        raise RealtimeStreamConfigError(str(exc)) from exc
    return ".".join(f'"{part}"' for part in str(value).split("."))


def _normalized_dialect(database_type: str | None) -> str:
    dialect = str(database_type or "").strip().lower()
    if dialect in {"sqlserver", "sql_server", "mssql", "ms_sql"}:
        return "mssql"
    if dialect in {"mysql", "mariadb"}:
        return "mysql"
    if dialect in {"sqlite", "sqlite3"}:
        return "sqlite"
    return dialect or "unknown"

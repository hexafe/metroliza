"""Bridge cached industrial rows into the shared CSV Summary tabular workflow."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4

import pandas as pd

from metroliza.industrial.industrial_analytics_service import ProductionMetricCandidate
from metroliza.industrial.industrial_analytics_state import production_field_label
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.reports.db import sqlite_connection_scope
from metroliza.tabular.tabular_analytics_service import (
    TABULAR_SQLITE_PREVIEW_ROWS,
    TabularAnalyticsLoadResult,
    TabularSqliteStore,
    discover_tabular_metric_candidates,
)


_INDUSTRIAL_TABULAR_TABLE = "industrial_tabular_rows"
_INDUSTRIAL_TABULAR_METADATA_TABLE = "industrial_tabular_metadata_cache"
_INDUSTRIAL_TABULAR_VALUE_FACETS_TABLE = "industrial_tabular_value_facets"
_SAFE_COLUMN_RE = re.compile(r"[^A-Za-z0-9_]+")
_BASE_INDUSTRIAL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source", "COALESCE(NULLIF(profiles.profile_name, ''), records.source_db_alias)"),
    ("source_db_alias", "records.source_db_alias"),
    ("source_profile_id", "records.source_profile_id"),
    ("sync_run_id", "records.sync_run_id"),
    ("source_record_key", "records.source_record_key"),
    ("process_timestamp", "records.process_timestamp"),
    ("process_datetime", "records.process_timestamp"),
    ("reference", "records.reference"),
    ("part_number", "records.part_number"),
    ("part_name", "records.part_name"),
    ("revision", "records.revision"),
    ("serial", "records.serial"),
    ("batch_lot", "records.batch_lot"),
    ("work_order", "records.work_order"),
    ("station", "records.station"),
    ("line", "records.line"),
    ("operator_name", "records.operator_name"),
    ("process_status", "records.process_status"),
)
_METRIC_NUMERIC_THRESHOLD = 0.8
_METRIC_MIN_NUMERIC_COUNT = 2
_INDUSTRIAL_PREVIEW_DYNAMIC_COLUMN_LIMIT = 32
_INDUSTRIAL_PREVIEW_BASE_COLUMNS = (
    "source_row_number",
    "source",
    "source_db_alias",
    "source_profile_id",
    "process_datetime",
    "reference",
    "part_number",
    "part_name",
    "revision",
    "serial",
    "batch_lot",
    "work_order",
    "station",
    "line",
    "operator_name",
    "process_status",
)


@dataclass(frozen=True)
class _IndustrialTabularMetadata:
    scope_key: str
    row_count: int
    dynamic_fields: tuple[str, ...]
    dynamic_stats: dict[str, dict[str, Any]]


def load_industrial_cache_tabular_result(
    db_file: str | Path,
    *,
    source_profile_ids: tuple[int, ...] | list[int] | None = None,
    source_db_aliases: tuple[str, ...] | list[str] | None = None,
) -> TabularAnalyticsLoadResult:
    """Load cached industrial rows as a SQLite-backed CSV Summary input."""

    database = str(db_file)
    ensure_industrial_data_schema(database)
    normalized_source_profile_ids = tuple(int(item) for item in (source_profile_ids or ()))
    normalized_source_db_aliases = tuple(str(item) for item in (source_db_aliases or ()))
    summary_profile_id = None
    if len(normalized_source_profile_ids) == 1:
        summary_profile_id = normalized_source_profile_ids[0]
    cache_summary = IndustrialDataRepository(database).summarize_counts(
        source_profile_id=summary_profile_id
    ).as_dict()
    where_parts: list[str] = []
    params: list[Any] = []
    if normalized_source_profile_ids:
        placeholders = ", ".join("?" for _item in normalized_source_profile_ids)
        where_parts.append(f"records.source_profile_id IN ({placeholders})")
        params.extend(normalized_source_profile_ids)
    if normalized_source_db_aliases:
        placeholders = ", ".join("?" for _item in normalized_source_db_aliases)
        where_parts.append(f"records.source_db_alias IN ({placeholders})")
        params.extend(normalized_source_db_aliases)
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    view_name, columns, row_count, scope_key, metadata_metric_candidates = (
        _prepare_tabular_view_from_industrial_cache(
            database,
            where_sql=where_sql,
            view_where_sql=_literal_where_sql(where_parts, params),
            params=tuple(params),
        )
    )
    store = TabularSqliteStore(
        path=database,
        table_name=view_name,
        columns=columns,
        source_columns=columns,
        row_count=row_count,
        date_filter_columns={"process_datetime": "process_datetime"},
        owns_file=False,
        indexable=False,
        value_facet_table=_INDUSTRIAL_TABULAR_VALUE_FACETS_TABLE,
        value_facet_scope_key=scope_key,
        cleanup_sql=(f"DROP VIEW IF EXISTS {_quote_identifier(view_name)}",),
    )
    preview = store.read_dataframe(
        columns=_industrial_preview_columns(columns),
        limit=TABULAR_SQLITE_PREVIEW_ROWS,
    )
    preview_metric_candidates = discover_tabular_metric_candidates(
        preview,
        reserved_columns=(
            "source",
            "source_db_alias",
            "source_profile_id",
            "sync_run_id",
            "source_record_key",
        ),
    )
    metric_candidates = _merge_metric_candidates(preview_metric_candidates, metadata_metric_candidates)
    return TabularAnalyticsLoadResult(
        dataframe=preview,
        metric_candidates=metric_candidates,
        diagnostics=(),
        column_mapping={column: column for column in columns},
        source_file=str(db_file),
        sheet_name="Industrial cache",
        timestamp_column="process_datetime",
        reference_column="reference",
        csv_config={
            "source": "industrial_cache",
            "storage": "sqlite",
            "cache_summary": cache_summary,
        },
        source_files=(str(db_file),),
        storage_mode="sqlite",
        sqlite_store=store,
        row_count=row_count,
    )


def _write_tabular_sqlite_from_industrial_cache(
    database: str,
    *,
    where_sql: str,
    params: tuple[Any, ...],
) -> tuple[str, tuple[str, ...], int]:
    temp = tempfile.NamedTemporaryFile(prefix="metroliza-industrial-tabular-", suffix=".sqlite", delete=False)
    temp.close()
    sqlite_path = temp.name
    with sqlite_connection_scope(sqlite_path) as connection:
        connection.create_function("metroliza_dynamic_value", 2, _dynamic_value)
        connection.execute("ATTACH DATABASE ? AS source_db", (database,))
        row_count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM source_db.industrial_records records {where_sql}",
                params,
            ).fetchone()[0]
            or 0
        )
        if row_count <= 0:
            columns = tuple(str(column) for column in _empty_industrial_tabular_frame().columns)
            _create_tabular_table(connection, columns)
            connection.commit()
            connection.execute("DETACH DATABASE source_db")
            return sqlite_path, columns, 0

        dynamic_fields = _dynamic_field_names(
            connection,
            where_sql=where_sql,
            params=params,
            schema_prefix="source_db",
        )
        columns, dynamic_columns = _industrial_tabular_columns(dynamic_fields)
        _create_tabular_table(connection, columns)
        _insert_industrial_tabular_rows(
            connection,
            where_sql=where_sql,
            params=params,
            columns=columns,
            dynamic_fields=dynamic_fields,
            dynamic_columns=dynamic_columns,
        )
        _create_tabular_indexes(connection, columns)
        connection.commit()
        connection.execute("DETACH DATABASE source_db")
    return sqlite_path, columns, row_count


def _prepare_tabular_view_from_industrial_cache(
    database: str,
    *,
    where_sql: str,
    view_where_sql: str,
    params: tuple[Any, ...],
) -> tuple[str, tuple[str, ...], int, str, tuple[ProductionMetricCandidate, ...]]:
    view_name = f"{_INDUSTRIAL_TABULAR_TABLE}_{uuid4().hex}"
    with sqlite_connection_scope(database) as connection:
        _prune_stale_industrial_tabular_views(connection)
        metadata = _load_or_refresh_tabular_metadata(connection, where_sql=where_sql, params=params)
        row_count = metadata.row_count
        if row_count <= 0:
            columns = tuple(str(column) for column in _empty_industrial_tabular_frame().columns)
            _create_industrial_tabular_view(
                connection,
                view_name=view_name,
                columns=columns,
                dynamic_fields=(),
                dynamic_columns=(),
                view_where_sql=view_where_sql,
            )
            connection.commit()
            return view_name, columns, 0, metadata.scope_key, ()

        dynamic_fields = metadata.dynamic_fields
        columns, dynamic_columns = _industrial_tabular_columns(dynamic_fields)
        _create_industrial_tabular_view(
            connection,
            view_name=view_name,
            columns=columns,
            dynamic_fields=dynamic_fields,
            dynamic_columns=dynamic_columns,
            view_where_sql=view_where_sql,
        )
        metric_candidates = _metadata_metric_candidates(
            dynamic_fields=dynamic_fields,
            dynamic_columns=dynamic_columns,
            dynamic_stats=metadata.dynamic_stats,
        )
        connection.commit()
        return view_name, columns, row_count, metadata.scope_key, metric_candidates


def _load_or_refresh_tabular_metadata(
    connection,
    *,
    where_sql: str,
    params: tuple[Any, ...],
) -> _IndustrialTabularMetadata:
    _ensure_tabular_metadata_cache(connection)
    scope_key = _metadata_scope_key(where_sql=where_sql, params=params)
    row_count, max_record_id, max_updated_at, value_count, max_value_id = _metadata_scope_fingerprint(
        connection,
        where_sql=where_sql,
        params=params,
    )
    cached = connection.execute(
        f"""
        SELECT
            row_count,
            max_record_id,
            max_updated_at,
            value_count,
            max_value_id,
            dynamic_fields_json,
            dynamic_stats_json
        FROM {_quote_identifier(_INDUSTRIAL_TABULAR_METADATA_TABLE)}
        WHERE scope_key = ?
        """,
        (scope_key,),
    ).fetchone()
    if cached is not None and (
        int(cached[0]) == row_count
        and int(cached[1] or 0) == max_record_id
        and str(cached[2] or "") == max_updated_at
        and int(cached[3] or 0) == value_count
        and int(cached[4] or 0) == max_value_id
    ):
        metadata = _metadata_from_json(scope_key, row_count, cached[5], cached[6])
        _ensure_value_facets_for_scope(
            connection,
            scope_key=scope_key,
            row_count=row_count,
            where_sql=where_sql,
            params=params,
            dynamic_fields=metadata.dynamic_fields,
        )
        return metadata

    dynamic_fields, dynamic_stats = _dynamic_field_metadata(
        connection,
        where_sql=where_sql,
        params=params,
    )
    connection.execute(
        f"""
        INSERT INTO {_quote_identifier(_INDUSTRIAL_TABULAR_METADATA_TABLE)} (
            scope_key,
            row_count,
            max_record_id,
            max_updated_at,
            value_count,
            max_value_id,
            dynamic_fields_json,
            dynamic_stats_json,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(scope_key) DO UPDATE SET
            row_count = excluded.row_count,
            max_record_id = excluded.max_record_id,
            max_updated_at = excluded.max_updated_at,
            value_count = excluded.value_count,
            max_value_id = excluded.max_value_id,
            dynamic_fields_json = excluded.dynamic_fields_json,
            dynamic_stats_json = excluded.dynamic_stats_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            scope_key,
            row_count,
            max_record_id,
            max_updated_at,
            value_count,
            max_value_id,
            json.dumps(dynamic_fields, ensure_ascii=False),
            json.dumps(dynamic_stats, ensure_ascii=False, sort_keys=True),
        ),
    )
    _refresh_value_facets(
        connection,
        scope_key=scope_key,
        row_count=row_count,
        where_sql=where_sql,
        params=params,
        dynamic_fields=dynamic_fields,
    )
    return _IndustrialTabularMetadata(
        scope_key=scope_key,
        row_count=row_count,
        dynamic_fields=dynamic_fields,
        dynamic_stats=dynamic_stats,
    )


def _ensure_tabular_metadata_cache(connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_quote_identifier(_INDUSTRIAL_TABULAR_METADATA_TABLE)} (
            scope_key TEXT PRIMARY KEY,
            row_count INTEGER NOT NULL,
            max_record_id INTEGER NOT NULL,
            max_updated_at TEXT NOT NULL,
            value_count INTEGER NOT NULL DEFAULT 0,
            max_value_id INTEGER NOT NULL DEFAULT 0,
            dynamic_fields_json TEXT NOT NULL,
            dynamic_stats_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    _ensure_table_column(
        connection,
        table_name=_INDUSTRIAL_TABULAR_METADATA_TABLE,
        column_name="value_count",
        definition="INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_table_column(
        connection,
        table_name=_INDUSTRIAL_TABULAR_METADATA_TABLE,
        column_name="max_value_id",
        definition="INTEGER NOT NULL DEFAULT 0",
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_quote_identifier(_INDUSTRIAL_TABULAR_VALUE_FACETS_TABLE)} (
            scope_key TEXT NOT NULL,
            column_name TEXT NOT NULL,
            normalized_value TEXT NOT NULL,
            display_value TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (scope_key, column_name, normalized_value, display_value)
        )
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_quote_identifier('idx_industrial_tabular_value_facets_lookup')}
        ON {_quote_identifier(_INDUSTRIAL_TABULAR_VALUE_FACETS_TABLE)}
            (scope_key, column_name, normalized_value)
        """
    )


def _metadata_scope_key(*, where_sql: str, params: tuple[Any, ...]) -> str:
    payload = json.dumps(
        {"where_sql": where_sql, "params": list(params)},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _metadata_scope_fingerprint(
    connection,
    *,
    where_sql: str,
    params: tuple[Any, ...],
) -> tuple[int, int, str, int, int]:
    row = connection.execute(
        f"""
        SELECT
            COUNT(*),
            COALESCE(MAX(records.id), 0),
            COALESCE(MAX(records.updated_at), '')
        FROM industrial_records records
        {where_sql}
        """,
        params,
    ).fetchone()
    value_row = connection.execute(
        f"""
        SELECT
            COUNT(values_row.id),
            COALESCE(MAX(values_row.id), 0)
        FROM industrial_record_values values_row
        JOIN industrial_records records
            ON records.id = values_row.record_id
        {where_sql}
        """,
        params,
    ).fetchone()
    return (
        int(row[0] or 0),
        int(row[1] or 0),
        str(row[2] or ""),
        int(value_row[0] or 0),
        int(value_row[1] or 0),
    )


def _ensure_table_column(
    connection,
    *,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    rows = connection.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    if any(str(row[1]) == column_name for row in rows):
        return
    connection.execute(
        f"ALTER TABLE {_quote_identifier(table_name)} "
        f"ADD COLUMN {_quote_identifier(column_name)} {definition}"
    )


def _metadata_from_json(
    scope_key: str,
    row_count: int,
    dynamic_fields_json: str,
    dynamic_stats_json: str,
) -> _IndustrialTabularMetadata:
    try:
        dynamic_fields = tuple(str(item) for item in json.loads(dynamic_fields_json or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        dynamic_fields = ()
    try:
        raw_stats = json.loads(dynamic_stats_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        raw_stats = {}
    dynamic_stats: dict[str, dict[str, Any]] = {}
    if isinstance(raw_stats, dict):
        for field_name, stats in raw_stats.items():
            if isinstance(stats, dict):
                dynamic_stats[str(field_name)] = dict(stats)
    return _IndustrialTabularMetadata(
        scope_key=scope_key,
        row_count=row_count,
        dynamic_fields=dynamic_fields,
        dynamic_stats=dynamic_stats,
    )


def _ensure_value_facets_for_scope(
    connection,
    *,
    scope_key: str,
    row_count: int,
    where_sql: str,
    params: tuple[Any, ...],
    dynamic_fields: tuple[str, ...],
) -> None:
    if row_count <= 0:
        return
    cached = connection.execute(
        f"""
        SELECT 1
        FROM {_quote_identifier(_INDUSTRIAL_TABULAR_VALUE_FACETS_TABLE)}
        WHERE scope_key = ?
        LIMIT 1
        """,
        (scope_key,),
    ).fetchone()
    if cached is not None:
        return
    _refresh_value_facets(
        connection,
        scope_key=scope_key,
        row_count=row_count,
        where_sql=where_sql,
        params=params,
        dynamic_fields=dynamic_fields,
    )


def _refresh_value_facets(
    connection,
    *,
    scope_key: str,
    row_count: int,
    where_sql: str,
    params: tuple[Any, ...],
    dynamic_fields: tuple[str, ...],
) -> None:
    connection.execute(
        f"DELETE FROM {_quote_identifier(_INDUSTRIAL_TABULAR_VALUE_FACETS_TABLE)} WHERE scope_key = ?",
        (scope_key,),
    )
    if row_count <= 0:
        return
    connection.execute("DROP TABLE IF EXISTS temp_industrial_tabular_scope_records")
    connection.execute("CREATE TEMP TABLE temp_industrial_tabular_scope_records (record_id INTEGER PRIMARY KEY)")
    connection.execute(
        f"""
        INSERT INTO temp_industrial_tabular_scope_records (record_id)
        SELECT records.id
        FROM industrial_records records
        {where_sql}
        """,
        params,
    )
    columns, dynamic_columns = _industrial_tabular_columns(dynamic_fields)
    _insert_base_value_facets(connection, scope_key=scope_key, columns=columns)
    for field_name, output_column in zip(dynamic_fields, dynamic_columns, strict=False):
        _insert_dynamic_value_facets(
            connection,
            scope_key=scope_key,
            field_name=field_name,
            output_column=output_column,
        )
    connection.execute("DROP TABLE IF EXISTS temp_industrial_tabular_scope_records")
    connection.execute("PRAGMA optimize")


def _insert_base_value_facets(connection, *, scope_key: str, columns: tuple[str, ...]) -> None:
    available_columns = set(columns)
    for column, expression in _BASE_INDUSTRIAL_COLUMNS:
        if column not in available_columns:
            continue
        normalized_expr = _normalized_value_sql(expression)
        connection.execute(
            f"""
            INSERT OR REPLACE INTO {_quote_identifier(_INDUSTRIAL_TABULAR_VALUE_FACETS_TABLE)} (
                scope_key,
                column_name,
                normalized_value,
                display_value,
                row_count,
                updated_at
            )
            SELECT
                ?,
                ?,
                {normalized_expr} AS normalized_value,
                {normalized_expr} AS display_value,
                COUNT(*) AS row_count,
                CURRENT_TIMESTAMP
            FROM temp_industrial_tabular_scope_records scope_records
            JOIN industrial_records records
                ON records.id = scope_records.record_id
            LEFT JOIN industrial_source_profiles profiles
                ON profiles.id = records.source_profile_id
            GROUP BY normalized_value, display_value
            """,
            (scope_key, column),
        )


def _insert_dynamic_value_facets(
    connection,
    *,
    scope_key: str,
    field_name: str,
    output_column: str,
) -> None:
    value_expr = "COALESCE(NULLIF(values_row.field_value_text, ''), values_row.field_value_json)"
    normalized_expr = _normalized_value_sql(value_expr)
    connection.execute(
        f"""
        INSERT OR REPLACE INTO {_quote_identifier(_INDUSTRIAL_TABULAR_VALUE_FACETS_TABLE)} (
            scope_key,
            column_name,
            normalized_value,
            display_value,
            row_count,
            updated_at
        )
        SELECT
            ?,
            ?,
            {normalized_expr} AS normalized_value,
            {normalized_expr} AS display_value,
            COUNT(*) AS row_count,
            CURRENT_TIMESTAMP
        FROM temp_industrial_tabular_scope_records scope_records
        LEFT JOIN industrial_record_values values_row
            ON values_row.record_id = scope_records.record_id
            AND values_row.field_name = ?
        GROUP BY normalized_value, display_value
        """,
        (scope_key, output_column, field_name),
    )


def _dynamic_field_metadata(
    connection,
    *,
    where_sql: str,
    params: tuple[Any, ...],
) -> tuple[tuple[str, ...], dict[str, dict[str, Any]]]:
    connection.create_function("metroliza_is_numeric_text", 1, _is_numeric_text)
    value_expr = "TRIM(COALESCE(NULLIF(values_row.field_value_text, ''), values_row.field_value_json, ''))"
    rows = connection.execute(
        f"""
        WITH field_values AS (
            SELECT
                values_row.field_name AS field_name,
                {value_expr} AS field_value
            FROM industrial_record_values values_row
            JOIN industrial_records records
                ON records.id = values_row.record_id
            {where_sql}
        )
        SELECT
            field_name,
            COUNT(NULLIF(field_value, '')) AS non_null_count,
            COALESCE(SUM(
                CASE
                    WHEN field_value <> '' AND metroliza_is_numeric_text(field_value)
                    THEN 1
                    ELSE 0
                END
            ), 0) AS numeric_count,
            MIN(NULLIF(field_value, '')) AS sample_value
        FROM field_values
        GROUP BY field_name
        ORDER BY field_name COLLATE NOCASE
        """,
        params,
    ).fetchall()
    dynamic_fields: list[str] = []
    dynamic_stats: dict[str, dict[str, Any]] = {}
    for field_name_raw, non_null_count, numeric_count, sample_value in rows:
        field_name = str(field_name_raw or "").strip()
        if not field_name:
            continue
        dynamic_fields.append(field_name)
        sample_values = [str(sample_value)] if sample_value not in (None, "") else []
        dynamic_stats[field_name] = {
            "non_null_count": int(non_null_count or 0),
            "numeric_count": int(numeric_count or 0),
            "sample_values": sample_values,
        }
    return tuple(dynamic_fields), dynamic_stats


def _is_numeric_text(value: Any) -> int:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return int(math.isfinite(number))


def _metadata_metric_candidates(
    *,
    dynamic_fields: tuple[str, ...],
    dynamic_columns: tuple[str, ...],
    dynamic_stats: dict[str, dict[str, Any]],
) -> tuple[ProductionMetricCandidate, ...]:
    candidates: list[ProductionMetricCandidate] = []
    for field_name, output_column in zip(dynamic_fields, dynamic_columns, strict=False):
        stats = dynamic_stats.get(field_name) or {}
        non_null_count = int(stats.get("non_null_count") or 0)
        numeric_count = int(stats.get("numeric_count") or 0)
        if non_null_count <= 0:
            continue
        numeric_ratio = numeric_count / non_null_count
        if (
            numeric_count < _METRIC_MIN_NUMERIC_COUNT
            or numeric_ratio < _METRIC_NUMERIC_THRESHOLD
        ):
            continue
        sample_values = tuple(str(value) for value in (stats.get("sample_values") or ()) if str(value))
        warning_flags = ("contains_non_numeric_values",) if numeric_count < non_null_count else ()
        candidates.append(
            ProductionMetricCandidate(
                field_name=output_column,
                display_label=production_field_label(output_column),
                source_kind="dynamic",
                non_null_count=non_null_count,
                numeric_count=numeric_count,
                numeric_ratio=round(numeric_ratio, 4),
                sample_values=sample_values,
                warning_flags=warning_flags,
            )
        )
    return tuple(sorted(candidates, key=lambda item: item.display_label.lower()))


def _industrial_preview_columns(columns: tuple[str, ...]) -> tuple[str, ...]:
    available = set(columns)
    preview_columns = [
        column
        for column in _INDUSTRIAL_PREVIEW_BASE_COLUMNS
        if column in available
    ]
    base_columns = set(preview_columns)
    dynamic_columns = [
        column
        for column in columns
        if column not in base_columns
    ][: _INDUSTRIAL_PREVIEW_DYNAMIC_COLUMN_LIMIT]
    return tuple(dict.fromkeys((*preview_columns, *dynamic_columns))) or columns


def _merge_metric_candidates(
    preview_candidates: tuple[ProductionMetricCandidate, ...],
    metadata_candidates: tuple[ProductionMetricCandidate, ...],
) -> tuple[ProductionMetricCandidate, ...]:
    merged: dict[str, ProductionMetricCandidate] = {
        candidate.field_name: candidate for candidate in preview_candidates
    }
    for candidate in metadata_candidates:
        existing = merged.get(candidate.field_name)
        if existing is None or candidate.non_null_count > existing.non_null_count:
            merged[candidate.field_name] = candidate
    return tuple(sorted(merged.values(), key=lambda item: item.display_label.lower()))


def _create_industrial_tabular_view(
    connection,
    *,
    view_name: str,
    columns: tuple[str, ...],
    dynamic_fields: tuple[str, ...],
    dynamic_columns: tuple[str, ...],
    view_where_sql: str,
) -> None:
    selected_columns = [
        "ROW_NUMBER() OVER (ORDER BY records.id) AS "
        f"{_quote_identifier('source_row_number')}"
    ]
    selected_columns.extend(
        f"{expression} AS {_quote_identifier(column)}"
        for column, expression in _BASE_INDUSTRIAL_COLUMNS
        if column in columns
    )
    selected_columns.extend(
        _dynamic_field_view_expression(field_name, output_column)
        for field_name, output_column in zip(dynamic_fields, dynamic_columns, strict=False)
    )
    connection.execute(f"DROP VIEW IF EXISTS {_quote_identifier(view_name)}")
    connection.execute(
        f"""
        CREATE VIEW {_quote_identifier(view_name)} AS
        SELECT {', '.join(selected_columns)}
        FROM industrial_records records
        LEFT JOIN industrial_source_profiles profiles
            ON profiles.id = records.source_profile_id
        {view_where_sql}
        """
    )


def _prune_stale_industrial_tabular_views(connection) -> None:
    prefix = f"{_INDUSTRIAL_TABULAR_TABLE}_"
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'view'
          AND name LIKE ?
        """,
        (f"{prefix}%",),
    ).fetchall()
    for row in rows:
        view_name = str(row[0] or "")
        if not view_name.startswith(prefix):
            continue
        connection.execute(f"DROP VIEW IF EXISTS {_quote_identifier(view_name)}")


def _dynamic_field_view_expression(field_name: str, output_column: str) -> str:
    return (
        "(SELECT COALESCE(NULLIF(values_row.field_value_text, ''), values_row.field_value_json) "
        "FROM industrial_record_values values_row "
        "WHERE values_row.record_id = records.id "
        f"AND values_row.field_name = {_sql_literal(field_name)} "
        "LIMIT 1) "
        f"AS {_quote_identifier(output_column)}"
    )


def _literal_where_sql(where_parts: list[str], params: list[Any]) -> str:
    if not where_parts:
        return ""
    iterator = iter(params)
    literal_parts: list[str] = []
    for part in where_parts:
        literal = part
        while "?" in literal:
            literal = literal.replace("?", _sql_literal(next(iterator)), 1)
        literal_parts.append(literal)
    return f"WHERE {' AND '.join(literal_parts)}"


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _dynamic_field_names(
    connection,
    *,
    where_sql: str,
    params: tuple[Any, ...],
    schema_prefix: str = "",
) -> tuple[str, ...]:
    prefix = f"{schema_prefix}." if schema_prefix else ""
    records = connection.execute(
        f"""
        SELECT DISTINCT values_row.field_name
        FROM {prefix}industrial_record_values values_row
        JOIN {prefix}industrial_records records
            ON records.id = values_row.record_id
        {where_sql}
        ORDER BY values_row.field_name COLLATE NOCASE
        """,
        params,
    ).fetchall()
    return tuple(str(row[0]) for row in records if str(row[0] or "").strip())


def _industrial_tabular_columns(dynamic_fields: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    raw_columns = ("source_row_number", *(column for column, _expr in _BASE_INDUSTRIAL_COLUMNS), *dynamic_fields)
    columns = _deduplicated_column_names(raw_columns)
    dynamic_offset = 1 + len(_BASE_INDUSTRIAL_COLUMNS)
    return columns, columns[dynamic_offset:]


def _insert_industrial_tabular_rows(
    connection,
    *,
    where_sql: str,
    params: tuple[Any, ...],
    columns: tuple[str, ...],
    dynamic_fields: tuple[str, ...],
    dynamic_columns: tuple[str, ...],
) -> None:
    selected_columns = [
        "records.id AS record_id",
        "ROW_NUMBER() OVER (ORDER BY records.id) AS source_row_number",
    ]
    selected_columns.extend(
        f"{expression} AS {_quote_identifier(column)}"
        for column, expression in _BASE_INDUSTRIAL_COLUMNS
    )
    output_columns = ", ".join(_quote_identifier(column) for column in columns)
    selected_output_columns = [
        f"selected.{_quote_identifier(column)}"
        for column in columns[: 1 + len(_BASE_INDUSTRIAL_COLUMNS)]
    ]
    selected_output_columns.extend(
        "MAX(CASE WHEN values_row.field_name = ? "
        "THEN metroliza_dynamic_value(values_row.field_value_text, values_row.field_value_json) "
        f"END) AS {_quote_identifier(output_column)}"
        for output_column in dynamic_columns
    )
    query = f"""
        WITH selected AS (
            SELECT {', '.join(selected_columns)}
            FROM source_db.industrial_records records
            LEFT JOIN source_db.industrial_source_profiles profiles
                ON profiles.id = records.source_profile_id
            {where_sql}
            ORDER BY records.id
        )
        INSERT INTO {_quote_identifier(_INDUSTRIAL_TABULAR_TABLE)} ({output_columns})
        SELECT {', '.join(selected_output_columns)}
        FROM selected
        LEFT JOIN source_db.industrial_record_values values_row
            ON values_row.record_id = selected.record_id
        GROUP BY selected.record_id
        ORDER BY selected.record_id
    """
    connection.execute(query, (*params, *dynamic_fields))


def _dynamic_value(text: Any, json_value: Any) -> str | None:
    if text is not None and str(text) != "":
        return str(text)
    if json_value is None or str(json_value) == "":
        return None
    try:
        return json.dumps(json.loads(str(json_value)), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError, json.JSONDecodeError):
        return str(json_value)


def _normalized_value_sql(expression: str) -> str:
    return f"COALESCE(NULLIF(TRIM(CAST({expression} AS TEXT)), ''), '(blank)')"


def _empty_industrial_tabular_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "source_row_number",
            "source",
            "source_db_alias",
            "source_profile_id",
            "sync_run_id",
            "source_record_key",
            "process_timestamp",
            "process_datetime",
            "reference",
        ]
    )


def _deduplicate_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    columns = _deduplicated_column_names(tuple(str(column) for column in dataframe.columns))
    return dataframe.rename(columns=dict(zip(dataframe.columns, columns, strict=False)))


def _deduplicated_column_names(raw_columns: tuple[str, ...]) -> tuple[str, ...]:
    used: set[str] = set()
    columns: list[str] = []
    for column in raw_columns:
        base = _safe_column_name(column)
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        columns.append(candidate)
    return tuple(columns)


def _safe_column_name(value: str) -> str:
    name = _SAFE_COLUMN_RE.sub("_", value.strip()).strip("_").lower()
    return name or "column"


def _quote_identifier(identifier: str) -> str:
    escaped = str(identifier).replace('"', '""')
    return f'"{escaped}"'


def _create_tabular_table(connection, columns: tuple[str, ...]) -> None:
    column_defs = []
    for column in columns:
        column_type = "INTEGER" if column == "source_row_number" else "TEXT"
        column_defs.append(f"{_quote_identifier(column)} {column_type}")
    connection.execute(
        f"CREATE TABLE {_quote_identifier(_INDUSTRIAL_TABULAR_TABLE)} ({', '.join(column_defs)})"
    )


def _create_tabular_indexes(connection, columns: tuple[str, ...]) -> None:
    for column in (
        "source_row_number",
        "source",
        "source_db_alias",
        "source_profile_id",
        "process_datetime",
        "reference",
    ):
        if column not in columns:
            continue
        index_name = f"idx_{_INDUSTRIAL_TABULAR_TABLE}_{column}"
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {_quote_identifier(index_name)} "
            f"ON {_quote_identifier(_INDUSTRIAL_TABULAR_TABLE)} ({_quote_identifier(column)})"
        )


__all__ = ["load_industrial_cache_tabular_result"]

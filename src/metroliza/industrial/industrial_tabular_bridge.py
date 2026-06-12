"""Bridge cached industrial rows into the shared CSV Summary tabular workflow."""

from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
from typing import Any

import pandas as pd

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
    sqlite_path, columns, row_count = _write_tabular_sqlite_from_industrial_cache(
        database,
        where_sql=where_sql,
        params=tuple(params),
    )
    store = TabularSqliteStore(
        path=sqlite_path,
        table_name=_INDUSTRIAL_TABULAR_TABLE,
        columns=columns,
        source_columns=columns,
        row_count=row_count,
        date_filter_columns={"process_datetime": "process_datetime"},
    )
    preview = store.read_dataframe(limit=TABULAR_SQLITE_PREVIEW_ROWS)
    metric_candidates = discover_tabular_metric_candidates(
        preview,
        reserved_columns=(
            "source",
            "source_db_alias",
            "source_profile_id",
            "sync_run_id",
            "source_record_key",
        ),
    )
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

        dynamic_fields = _dynamic_field_names(connection, where_sql=where_sql, params=params)
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


def _dynamic_field_names(connection, *, where_sql: str, params: tuple[Any, ...]) -> tuple[str, ...]:
    records = connection.execute(
        f"""
        SELECT DISTINCT values_row.field_name
        FROM source_db.industrial_record_values values_row
        JOIN source_db.industrial_records records
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

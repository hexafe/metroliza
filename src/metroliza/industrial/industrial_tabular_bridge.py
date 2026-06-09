"""Bridge cached industrial rows into the shared CSV Summary tabular workflow."""

from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
from typing import Any

import pandas as pd

from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.reports.db import read_sql_dataframe, sqlite_connection_scope
from metroliza.tabular.tabular_analytics_service import (
    TABULAR_SQLITE_PREVIEW_ROWS,
    TabularAnalyticsLoadResult,
    TabularSqliteStore,
    discover_tabular_metric_candidates,
)


_INDUSTRIAL_TABULAR_TABLE = "industrial_tabular_rows"
_SAFE_COLUMN_RE = re.compile(r"[^A-Za-z0-9_]+")


def load_industrial_cache_tabular_result(
    db_file: str | Path,
    *,
    source_profile_ids: tuple[int, ...] | list[int] | None = None,
    source_db_aliases: tuple[str, ...] | list[str] | None = None,
) -> TabularAnalyticsLoadResult:
    """Load cached industrial rows as a SQLite-backed CSV Summary input."""

    database = str(db_file)
    ensure_industrial_data_schema(database)
    where_parts: list[str] = []
    params: list[Any] = []
    if source_profile_ids:
        placeholders = ", ".join("?" for _item in source_profile_ids)
        where_parts.append(f"records.source_profile_id IN ({placeholders})")
        params.extend(int(item) for item in source_profile_ids)
    if source_db_aliases:
        placeholders = ", ".join("?" for _item in source_db_aliases)
        where_parts.append(f"records.source_db_alias IN ({placeholders})")
        params.extend(str(item) for item in source_db_aliases)
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    records = read_sql_dataframe(
        database,
        f"""
        SELECT
            records.id AS record_id,
            COALESCE(NULLIF(profiles.profile_name, ''), records.source_db_alias) AS source,
            records.source_db_alias,
            records.source_profile_id,
            records.sync_run_id,
            records.source_record_key,
            records.process_timestamp,
            records.process_timestamp AS process_datetime,
            records.reference,
            records.part_number,
            records.part_name,
            records.revision,
            records.serial,
            records.batch_lot,
            records.work_order,
            records.station,
            records.line,
            records.operator_name,
            records.process_status
        FROM industrial_records records
        LEFT JOIN industrial_source_profiles profiles
            ON profiles.id = records.source_profile_id
        {where_sql}
        ORDER BY records.id
        """,
        params=params,
    )
    if records.empty:
        dataframe = _empty_industrial_tabular_frame()
    else:
        dataframe = records.copy()
        dataframe.insert(0, "source_row_number", range(1, len(dataframe.index) + 1))
        dataframe = _merge_dynamic_values(database, dataframe)
        dataframe = dataframe.drop(columns=["record_id"], errors="ignore")
    dataframe = _deduplicate_columns(dataframe)
    columns = tuple(str(column) for column in dataframe.columns)
    sqlite_path = _write_tabular_sqlite(dataframe, columns=columns)
    store = TabularSqliteStore(
        path=sqlite_path,
        table_name=_INDUSTRIAL_TABULAR_TABLE,
        columns=columns,
        source_columns=columns,
        row_count=int(len(dataframe.index)),
        date_filter_columns={"process_datetime": "process_datetime"},
    )
    preview = dataframe.head(TABULAR_SQLITE_PREVIEW_ROWS).copy()
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
        csv_config={"source": "industrial_cache", "storage": "sqlite"},
        source_files=(str(db_file),),
        storage_mode="sqlite",
        sqlite_store=store,
        row_count=int(len(dataframe.index)),
    )


def _merge_dynamic_values(database: str, dataframe: pd.DataFrame) -> pd.DataFrame:
    record_ids = tuple(int(value) for value in dataframe["record_id"].tolist())
    if not record_ids:
        return dataframe
    placeholders = ", ".join("?" for _item in record_ids)
    values = read_sql_dataframe(
        database,
        f"""
        SELECT record_id, field_name, field_value_text, field_value_json
        FROM industrial_record_values
        WHERE record_id IN ({placeholders})
        ORDER BY record_id, field_name
        """,
        params=list(record_ids),
    )
    if values.empty:
        return dataframe
    values["__value"] = [
        _dynamic_value(text, json_value)
        for text, json_value in zip(
            values["field_value_text"].tolist(),
            values["field_value_json"].tolist(),
            strict=False,
        )
    ]
    wide = values.pivot_table(
        index="record_id",
        columns="field_name",
        values="__value",
        aggfunc="first",
    ).reset_index()
    return dataframe.merge(wide, how="left", on="record_id")


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
    used: set[str] = set()
    renamed: dict[Any, str] = {}
    for column in dataframe.columns:
        base = _safe_column_name(str(column))
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        renamed[column] = candidate
    return dataframe.rename(columns=renamed)


def _safe_column_name(value: str) -> str:
    name = _SAFE_COLUMN_RE.sub("_", value.strip()).strip("_").lower()
    return name or "column"


def _write_tabular_sqlite(dataframe: pd.DataFrame, *, columns: tuple[str, ...]) -> str:
    temp = tempfile.NamedTemporaryFile(prefix="metroliza-industrial-tabular-", suffix=".sqlite", delete=False)
    temp.close()
    sqlite_path = temp.name
    output = dataframe.copy()
    for column in columns:
        if column == "source_row_number":
            output[column] = pd.to_numeric(output[column], errors="coerce").fillna(0).astype(int)
        else:
            output[column] = output[column].where(output[column].notna(), None)
    with sqlite_connection_scope(sqlite_path) as connection:
        output.to_sql(_INDUSTRIAL_TABULAR_TABLE, connection, index=False, if_exists="replace")
        connection.commit()
    return sqlite_path


__all__ = ["load_industrial_cache_tabular_result"]

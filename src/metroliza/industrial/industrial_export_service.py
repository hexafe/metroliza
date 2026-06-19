"""Export cached Oznak industrial production-line data with summaries and charts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from metroliza.industrial.industrial_data_repository import redact_sensitive_text
from metroliza.reports.db import read_sql_dataframe, sqlite_connection_scope
from metroliza.industrial.industrial_workflow_state import (
    IndustrialFilterState,
    IndustrialGroupingState,
    IndustrialQueryFilter,
    require_identifier,
)
from metroliza.industrial.oznak_adapter import fetch_oznak_records_for_source_profile
from metroliza.charts.xlsx_chart_utils import apply_chart_options, create_workbook_chart, insert_chart

CancelCheck = Callable[[], bool]

INDUSTRIAL_EXPORT_COLUMNS = (
    "source_db_alias",
    "source_record_key",
    "process_timestamp",
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
INDUSTRIAL_FILTER_RECORD_COLUMNS = frozenset(INDUSTRIAL_EXPORT_COLUMNS)
_CACHE_RECORD_ID_COLUMN = "__industrial_record_id"
_EXPORT_SCOPE_TABLE = "temp_industrial_export_scope"
_EXPORT_REFERENCE_FILTER_TABLE = "temp_industrial_reference_filter"
_EXPORT_BATCH_SIZE = 1000


class IndustrialExportCancelled(Exception):
    """Raised when a cached industrial export is cancelled before finalization."""


def load_cached_industrial_dataframe(
    db_file: str,
    *,
    filter_state: IndustrialFilterState | None = None,
) -> pd.DataFrame:
    """Load cached industrial rows, optionally scoped to selected references."""

    filter_state = filter_state or IndustrialFilterState()
    select_columns = ", ".join(
        (
            f"ir.id AS {_CACHE_RECORD_ID_COLUMN}",
            *(f"ir.{column}" for column in INDUSTRIAL_EXPORT_COLUMNS),
            "ir.raw_record_json",
        )
    )
    base_query = f"""
        SELECT {select_columns}
        FROM industrial_records ir
    """
    references = tuple(filter_state.references)
    query_filters = _validated_export_query_filters(filter_state)
    with sqlite_connection_scope(db_file) as conn:
        if references:
            reference_column = _resolve_filter_column(conn, filter_state.reference_column)
            conn.execute("DROP TABLE IF EXISTS temp_industrial_reference_filter")
            conn.execute(
                "CREATE TEMP TABLE temp_industrial_reference_filter (reference TEXT PRIMARY KEY)"
            )
            conn.executemany(
                "INSERT OR IGNORE INTO temp_industrial_reference_filter(reference) VALUES (?)",
                [(reference,) for reference in references],
            )
            if reference_column in INDUSTRIAL_FILTER_RECORD_COLUMNS:
                filter_sql, filter_params = _cached_query_filter_where_clause(
                    conn,
                    query_filters,
                    table_alias="ir",
                )
                query = (
                    f"{base_query} "
                    f"JOIN temp_industrial_reference_filter rf ON rf.reference = ir.{reference_column} "
                    f"{filter_sql} "
                    "ORDER BY ir.reference COLLATE NOCASE, ir.process_timestamp, ir.id"
                )
                dataframe = read_sql_dataframe(
                    db_file,
                    query,
                    params=filter_params,
                    connection=conn,
                )
                return _append_cached_dynamic_columns(conn, dataframe)

            filter_sql, filter_params = _cached_query_filter_where_clause(
                conn,
                query_filters,
                table_alias="ir",
            )
            query = (
                f"{base_query} "
                "WHERE EXISTS ("
                "  SELECT 1"
                "  FROM industrial_record_values rv"
                "  JOIN temp_industrial_reference_filter rf"
                "    ON rf.reference = COALESCE(rv.field_value_text, rv.field_value_json, '')"
                "  WHERE rv.record_id = ir.id AND rv.field_name = ?"
                ")"
                f"{_append_filter_sql(filter_sql)} "
                "ORDER BY ir.reference COLLATE NOCASE, ir.process_timestamp, ir.id"
            )
            dataframe = read_sql_dataframe(
                db_file,
                query,
                params=(reference_column, *filter_params),
                connection=conn,
            )
            return _append_cached_dynamic_columns(conn, dataframe)

        filter_sql, filter_params = _cached_query_filter_where_clause(
            conn,
            query_filters,
            table_alias="ir",
        )
        query = f"{base_query} {filter_sql} ORDER BY ir.reference COLLATE NOCASE, ir.process_timestamp, ir.id"
        dataframe = read_sql_dataframe(db_file, query, params=filter_params, connection=conn)
        return _append_cached_dynamic_columns(conn, dataframe)


def _append_cached_dynamic_columns(conn, dataframe: pd.DataFrame) -> pd.DataFrame:
    if _CACHE_RECORD_ID_COLUMN not in dataframe.columns:
        return dataframe
    record_ids = tuple(
        int(value)
        for value in dataframe[_CACHE_RECORD_ID_COLUMN].tolist()
        if pd.notna(value)
    )
    if not record_ids:
        return dataframe.drop(columns=[_CACHE_RECORD_ID_COLUMN])

    dynamic_rows: list[tuple[int, str, Any]] = []
    for start in range(0, len(record_ids), 800):
        chunk = record_ids[start : start + 800]
        placeholders = ", ".join("?" for _item in chunk)
        dynamic_rows.extend(
            (
                int(row[0]),
                str(row[1]),
                _cached_dynamic_export_value(row[2], row[3]),
            )
            for row in conn.execute(
                f"""
                SELECT record_id, field_name, field_value_text, field_value_json
                FROM industrial_record_values
                WHERE record_id IN ({placeholders})
                ORDER BY record_id, field_name COLLATE NOCASE
                """,
                chunk,
            ).fetchall()
        )

    if dynamic_rows:
        dynamic_frame = pd.DataFrame(
            dynamic_rows,
            columns=[_CACHE_RECORD_ID_COLUMN, "field_name", "field_value"],
        )
        dynamic_wide = (
            dynamic_frame.pivot_table(
                index=_CACHE_RECORD_ID_COLUMN,
                columns="field_name",
                values="field_value",
                aggfunc="first",
            )
            .reset_index()
            .rename_axis(None, axis=1)
        )
        dynamic_columns = [
            str(column)
            for column in dynamic_wide.columns
            if column != _CACHE_RECORD_ID_COLUMN and str(column) not in dataframe.columns
        ]
        if dynamic_columns:
            dataframe = dataframe.merge(
                dynamic_wide[[_CACHE_RECORD_ID_COLUMN, *dynamic_columns]],
                on=_CACHE_RECORD_ID_COLUMN,
                how="left",
            )
    return dataframe.drop(columns=[_CACHE_RECORD_ID_COLUMN])


def _cached_dynamic_export_value(value_text: Any, value_json: Any) -> Any:
    if value_text is not None and str(value_text) != "":
        return value_text
    if value_json is None or str(value_json) == "":
        return None
    try:
        return json.dumps(json.loads(str(value_json)), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError, json.JSONDecodeError):
        return str(value_json)


def build_industrial_summary(
    dataframe: pd.DataFrame,
    *,
    grouping_state: IndustrialGroupingState | None = None,
) -> pd.DataFrame:
    """Build grouped counts for cached industrial rows."""

    grouping_state = grouping_state or IndustrialGroupingState()
    if dataframe.empty:
        return pd.DataFrame(columns=["group", "record_count"])

    requested_fields = grouping_state.validated_fields()
    group_fields = [field for field in requested_fields if field in dataframe.columns]
    if not group_fields:
        if "process_status" in dataframe.columns and dataframe["process_status"].notna().any():
            group_fields = ["process_status"]
        elif "source_db_alias" in dataframe.columns:
            group_fields = ["source_db_alias"]

    if not group_fields:
        return pd.DataFrame({"group": ["All records"], "record_count": [len(dataframe.index)]})

    grouped = (
        dataframe.fillna("")
        .groupby(group_fields, dropna=False)
        .size()
        .reset_index(name="record_count")
        .sort_values("record_count", ascending=False)
        .reset_index(drop=True)
    )
    grouped.insert(
        0,
        "group",
        grouped[group_fields].astype(str).agg(" | ".join, axis=1),
    )
    return grouped


def export_cached_industrial_workbook(
    *,
    db_file: str,
    output_file: str,
    filter_state: IndustrialFilterState | None = None,
    grouping_state: IndustrialGroupingState | None = None,
    include_charts: bool = True,
    include_raw_data: bool = True,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    """Write cached Oznak data, grouped summary, diagnostics, and basic charts."""

    _raise_if_cancelled(cancel_check)
    return _export_cached_industrial_workbook_streaming(
        db_file=db_file,
        output_file=output_file,
        filter_state=filter_state,
        grouping_state=grouping_state,
        include_charts=include_charts,
        include_raw_data=include_raw_data,
        cancel_check=cancel_check,
    )


def _export_cached_industrial_workbook_streaming(
    *,
    db_file: str,
    output_file: str,
    filter_state: IndustrialFilterState | None,
    grouping_state: IndustrialGroupingState | None,
    include_charts: bool,
    include_raw_data: bool,
    cancel_check: CancelCheck | None,
) -> dict[str, Any]:
    filter_state = filter_state or IndustrialFilterState()
    grouping_state = grouping_state or IndustrialGroupingState()
    output_path = Path(output_file)
    if output_path.suffix.lower() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_name(f".{output_path.stem}.tmp{output_path.suffix}")
    if temp_output_path.exists():
        temp_output_path.unlink()

    summary_counts: dict[str, int] = {}
    row_count = 0
    raw_sheet_rows = 0

    try:
        with sqlite_connection_scope(db_file) as conn:
            _raise_if_cancelled(cancel_check)
            row_total = _prepare_cached_export_scope(conn, filter_state=filter_state)
            dynamic_fields = _cached_export_dynamic_fields(conn)
            export_columns = _cached_export_columns(
                dynamic_fields,
                include_raw_data=include_raw_data,
            )
            raw_columns = _cached_raw_export_columns(dynamic_fields) if include_raw_data else []
            group_fields = _cached_summary_group_fields(
                export_columns,
                grouping_state=grouping_state,
            )
            _raise_if_cancelled(cancel_check)

            with pd.ExcelWriter(temp_output_path, engine="xlsxwriter") as writer:
                data_sheet = writer.book.add_worksheet("Industrial Data")
                writer.sheets["Industrial Data"] = data_sheet
                _write_excel_row(data_sheet, 0, export_columns)
                raw_sheet = None
                if raw_columns:
                    raw_sheet = writer.book.add_worksheet("Raw Data")
                    writer.sheets["Raw Data"] = raw_sheet
                    _write_excel_row(raw_sheet, 0, raw_columns)

                data_row_index = 1
                raw_row_index = 1
                for batch in _iter_cached_export_batches(conn, dynamic_fields=dynamic_fields):
                    _raise_if_cancelled(cancel_check)
                    for row in batch:
                        row_count += 1
                        _write_excel_row(
                            data_sheet,
                            data_row_index,
                            [row.get(column) for column in export_columns],
                        )
                        data_row_index += 1
                        if raw_sheet is not None:
                            _write_excel_row(
                                raw_sheet,
                                raw_row_index,
                                [row.get(column) for column in raw_columns],
                            )
                            raw_row_index += 1
                            raw_sheet_rows += 1
                        group = _cached_summary_group_label(row, group_fields=group_fields)
                        summary_counts[group] = summary_counts.get(group, 0) + 1

                _raise_if_cancelled(cancel_check)
                summary = _cached_summary_dataframe(summary_counts, row_count=row_count)
                diagnostics = pd.DataFrame(
                    [
                        {
                            "row_count": int(row_count),
                            "filter_references": len(tuple(filter_state.references)),
                            "grouping": grouping_state.summary(),
                            "charts": bool(include_charts),
                            "raw_data": bool(include_raw_data),
                            "raw_sheet_rows": int(raw_sheet_rows),
                            "source_kind": "cached",
                            "storage": "sqlite_streaming",
                            "scope_rows": int(row_total),
                        }
                    ]
                )
                summary.to_excel(writer, sheet_name="Industrial Summary", index=False)
                _raise_if_cancelled(cancel_check)
                diagnostics.to_excel(writer, sheet_name="Diagnostics", index=False)
                _raise_if_cancelled(cancel_check)
                if include_charts:
                    _write_industrial_charts(writer, summary)
                    _raise_if_cancelled(cancel_check)
            _raise_if_cancelled(cancel_check)
        temp_output_path.replace(output_path)
    except IndustrialExportCancelled:
        temp_output_path.unlink(missing_ok=True)
        raise
    except Exception:
        temp_output_path.unlink(missing_ok=True)
        raise

    return {
        "output_file": str(output_path),
        "row_count": int(row_count),
        "summary_rows": int(len(summary_counts)),
        "charts": bool(include_charts),
        "raw_data": bool(include_raw_data),
        "raw_sheet_rows": int(raw_sheet_rows),
    }


def _prepare_cached_export_scope(
    conn,
    *,
    filter_state: IndustrialFilterState,
) -> int:
    query_filters = _validated_export_query_filters(filter_state)
    conn.execute(f"DROP TABLE IF EXISTS {_EXPORT_SCOPE_TABLE}")
    conn.execute(f"CREATE TEMP TABLE {_EXPORT_SCOPE_TABLE} (record_id INTEGER PRIMARY KEY)")
    references = tuple(filter_state.references)
    if references:
        reference_column = _resolve_filter_column(conn, filter_state.reference_column)
        conn.execute(f"DROP TABLE IF EXISTS {_EXPORT_REFERENCE_FILTER_TABLE}")
        conn.execute(
            f"CREATE TEMP TABLE {_EXPORT_REFERENCE_FILTER_TABLE} (reference TEXT PRIMARY KEY)"
        )
        conn.executemany(
            f"INSERT OR IGNORE INTO {_EXPORT_REFERENCE_FILTER_TABLE}(reference) VALUES (?)",
            [(reference,) for reference in references],
        )
        if reference_column in INDUSTRIAL_FILTER_RECORD_COLUMNS:
            filter_sql, filter_params = _cached_query_filter_where_clause(
                conn,
                query_filters,
                table_alias="ir",
            )
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {_EXPORT_SCOPE_TABLE} (record_id)
                SELECT ir.id
                FROM industrial_records ir
                JOIN {_EXPORT_REFERENCE_FILTER_TABLE} rf
                    ON rf.reference = ir.{reference_column}
                {filter_sql}
                """
                ,
                filter_params,
            )
        else:
            filter_sql, filter_params = _cached_query_filter_where_clause(
                conn,
                query_filters,
                table_alias="ir",
            )
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {_EXPORT_SCOPE_TABLE} (record_id)
                SELECT rv.record_id
                FROM industrial_record_values rv
                JOIN industrial_records ir
                    ON ir.id = rv.record_id
                JOIN {_EXPORT_REFERENCE_FILTER_TABLE} rf
                    ON rf.reference = COALESCE(NULLIF(rv.field_value_text, ''), rv.field_value_json, '')
                WHERE rv.field_name = ?
                {_append_filter_sql(filter_sql)}
                """,
                (reference_column, *filter_params),
            )
    else:
        filter_sql, filter_params = _cached_query_filter_where_clause(
            conn,
            query_filters,
            table_alias="ir",
        )
        conn.execute(
            f"""
            INSERT INTO {_EXPORT_SCOPE_TABLE} (record_id)
            SELECT ir.id
            FROM industrial_records ir
            {filter_sql}
            """,
            filter_params,
        )
    return int(conn.execute(f"SELECT COUNT(*) FROM {_EXPORT_SCOPE_TABLE}").fetchone()[0] or 0)


def _validated_export_query_filters(filter_state: IndustrialFilterState) -> tuple[IndustrialQueryFilter, ...]:
    return tuple(filter_state.validated() for filter_state in (filter_state.query_filters or ()))


def _cached_query_filter_where_clause(
    conn,
    query_filters: tuple[IndustrialQueryFilter, ...],
    *,
    table_alias: str,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    for filter_state in query_filters:
        clause, filter_params = _cached_query_filter_clause(
            conn,
            filter_state,
            table_alias=table_alias,
        )
        if clause:
            clauses.append(clause)
            params.extend(filter_params)
    if not clauses:
        return "", ()
    return f"WHERE {' AND '.join(clauses)}", tuple(params)


def _append_filter_sql(filter_sql: str) -> str:
    filter_clause = str(filter_sql or "").strip()
    if not filter_clause:
        return ""
    if filter_clause.upper().startswith("WHERE "):
        return f" AND {filter_clause[6:]}"
    return f" AND {filter_clause}"


def _cached_query_filter_clause(
    conn,
    filter_state: IndustrialQueryFilter,
    *,
    table_alias: str,
) -> tuple[str, tuple[Any, ...]]:
    column = _resolve_filter_column(conn, filter_state.column)
    operator = filter_state.operator
    values = tuple(filter_state.values)
    if column in INDUSTRIAL_FILTER_RECORD_COLUMNS:
        expression = f"{table_alias}.{column}"
    else:
        expression = (
            "SELECT COALESCE(NULLIF(rv_filter.field_value_text, ''), rv_filter.field_value_json, '') "
            "FROM industrial_record_values rv_filter "
            f"WHERE rv_filter.record_id = {table_alias}.id "
            "AND rv_filter.field_name = ? "
            "LIMIT 1"
        )
        expression = f"({expression})"
        values = (column, *values)
    value_params: tuple[Any, ...]
    if operator in {"IS NULL", "IS NOT NULL"}:
        return f"{expression} {operator}", values
    if operator in {"IN", "NOT IN"}:
        placeholders = ", ".join("?" for _value in filter_state.values)
        value_params = values
        return f"{expression} {operator} ({placeholders})", value_params
    value_params = values
    return f"{expression} {operator} ?", value_params


def _cached_export_dynamic_fields(conn) -> tuple[str, ...]:
    rows = conn.execute(
        f"""
        SELECT DISTINCT rv.field_name
        FROM industrial_record_values rv
        JOIN {_EXPORT_SCOPE_TABLE} scope
            ON scope.record_id = rv.record_id
        ORDER BY rv.field_name COLLATE NOCASE
        """
    ).fetchall()
    reserved = {*INDUSTRIAL_EXPORT_COLUMNS, "raw_record_json"}
    return tuple(
        str(row[0])
        for row in rows
        if str(row[0] or "").strip() and str(row[0]) not in reserved
    )


def _cached_export_columns(dynamic_fields: tuple[str, ...], *, include_raw_data: bool) -> list[str]:
    columns = list(INDUSTRIAL_EXPORT_COLUMNS)
    if include_raw_data:
        columns.append("raw_record_json")
    columns.extend(dynamic_fields)
    return columns


def _cached_raw_export_columns(dynamic_fields: tuple[str, ...]) -> list[str]:
    leading_columns = ["source_db_alias", "source_record_key", "reference", "process_timestamp"]
    return [*leading_columns, "raw_record_json", *dynamic_fields]


def _cached_summary_group_fields(
    columns: list[str],
    *,
    grouping_state: IndustrialGroupingState,
) -> list[str]:
    requested_fields = grouping_state.validated_fields()
    group_fields = [field for field in requested_fields if field in columns]
    if group_fields:
        return group_fields
    if "process_status" in columns:
        return ["process_status"]
    if "source_db_alias" in columns:
        return ["source_db_alias"]
    return []


def _iter_cached_export_batches(
    conn,
    *,
    dynamic_fields: tuple[str, ...],
    batch_size: int = _EXPORT_BATCH_SIZE,
):
    select_columns = ", ".join(
        (
            "ir.id",
            *(f"ir.{column}" for column in INDUSTRIAL_EXPORT_COLUMNS),
            "ir.raw_record_json",
        )
    )
    cursor = conn.execute(
        f"""
        SELECT {select_columns}
        FROM {_EXPORT_SCOPE_TABLE} scope
        JOIN industrial_records ir
            ON ir.id = scope.record_id
        ORDER BY ir.reference COLLATE NOCASE, ir.process_timestamp, ir.id
        """
    )
    column_names = ("record_id", *INDUSTRIAL_EXPORT_COLUMNS, "raw_record_json")
    while True:
        records = cursor.fetchmany(batch_size)
        if not records:
            break
        batch = [dict(zip(column_names, record, strict=False)) for record in records]
        if dynamic_fields:
            _attach_cached_dynamic_values(conn, batch, dynamic_fields=dynamic_fields)
        yield batch


def _attach_cached_dynamic_values(
    conn,
    batch: list[dict[str, Any]],
    *,
    dynamic_fields: tuple[str, ...],
) -> None:
    record_ids = tuple(int(row["record_id"]) for row in batch)
    if not record_ids:
        return
    row_by_id = {int(row["record_id"]): row for row in batch}
    id_placeholders = ", ".join("?" for _item in record_ids)
    field_placeholders = ", ".join("?" for _item in dynamic_fields)
    rows = conn.execute(
        f"""
        SELECT record_id, field_name, field_value_text, field_value_json
        FROM industrial_record_values
        WHERE record_id IN ({id_placeholders})
          AND field_name IN ({field_placeholders})
        ORDER BY record_id, field_name COLLATE NOCASE
        """,
        (*record_ids, *dynamic_fields),
    ).fetchall()
    for record_id, field_name, value_text, value_json in rows:
        row = row_by_id.get(int(record_id))
        if row is not None:
            row[str(field_name)] = _cached_dynamic_export_value(value_text, value_json)


def _cached_summary_group_label(row: Mapping[str, Any], *, group_fields: list[str]) -> str:
    if not group_fields:
        return "All records"
    values = [
        str(row.get(field) if row.get(field) not in (None, "") else "(blank)")
        for field in group_fields
    ]
    return " | ".join(values) or "All records"


def _cached_summary_dataframe(summary_counts: Mapping[str, int], *, row_count: int) -> pd.DataFrame:
    if row_count <= 0:
        return pd.DataFrame(columns=["group", "record_count"])
    if not summary_counts:
        return pd.DataFrame({"group": ["All records"], "record_count": [int(row_count)]})
    rows = sorted(summary_counts.items(), key=lambda item: (-int(item[1]), str(item[0]).casefold()))
    return pd.DataFrame(
        [{"group": group, "record_count": int(count)} for group, count in rows],
        columns=["group", "record_count"],
    )


def _write_excel_row(worksheet, row_index: int, values: list[Any] | tuple[Any, ...]) -> None:
    for column_index, value in enumerate(values):
        worksheet.write(row_index, column_index, _excel_cell_value(value))


def export_live_industrial_workbook(
    *,
    profile: Any,
    username: str,
    password: str,
    output_file: str,
    limit: int,
    timeout_seconds: int,
    filter_state: IndustrialFilterState | None = None,
    grouping_state: IndustrialGroupingState | None = None,
    include_charts: bool = True,
    include_raw_data: bool = True,
    cancellation_token: Any = None,
    progress_callback: Any = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    """Fetch live Oznak rows for one source profile and write an industrial workbook."""

    filter_state = filter_state or IndustrialFilterState()
    _raise_if_cancelled(cancel_check)
    result = fetch_oznak_records_for_source_profile(
        profile,
        username=username,
        password=password,
        limit=int(limit),
        timeout_seconds=int(timeout_seconds),
        reference_filter_column=filter_state.reference_column if filter_state.references else None,
        reference_values=filter_state.references,
        query_filters=filter_state.query_filters,
        cancellation_token=cancellation_token,
        progress_callback=progress_callback,
    )
    _raise_if_cancelled(cancel_check)
    if result.error and not result.records:
        raise ValueError(redact_sensitive_text(result.error))

    warning_detail = _live_fetch_warning_detail(result.diagnostics, result.error)
    dataframe = industrial_records_to_export_dataframe(result.records, profile=profile)
    workbook_result = export_industrial_dataframe_workbook(
        dataframe=dataframe,
        output_file=output_file,
        filter_state=filter_state,
        grouping_state=grouping_state,
        include_charts=include_charts,
        include_raw_data=include_raw_data,
        cancel_check=cancel_check,
        diagnostics_extra={
            "source_kind": "live_oznak",
            "source_profile": str(getattr(profile, "profile_key", "") or ""),
            "fetch_status": "completed_with_warnings" if warning_detail else "succeeded",
            "fetch_error": warning_detail or "",
        },
    )
    workbook_result.update(
        {
            "status": "completed_with_warnings" if warning_detail else "succeeded",
            "error": warning_detail,
            "diagnostics": result.diagnostics,
        }
    )
    return workbook_result


def industrial_records_to_export_dataframe(records: Any, *, profile: Any) -> pd.DataFrame:
    """Convert mapped Oznak industrial records into workbook-friendly export rows."""

    rows: list[dict[str, Any]] = []
    raw_columns: list[str] = []
    seen_raw_columns: set[str] = set()
    canonical_columns = set(INDUSTRIAL_EXPORT_COLUMNS)

    for record in records or ():
        if not isinstance(record, Mapping):
            continue
        row = {column: _canonical_export_value(record, column, profile=profile) for column in INDUSTRIAL_EXPORT_COLUMNS}
        raw_record = record.get("raw_record")
        if isinstance(raw_record, Mapping):
            for raw_key, raw_value in raw_record.items():
                column = str(raw_key).strip()
                if not column or column in canonical_columns:
                    continue
                if column not in seen_raw_columns:
                    seen_raw_columns.add(column)
                    raw_columns.append(column)
                row[column] = _excel_cell_value(raw_value)
        rows.append(row)

    columns = list(INDUSTRIAL_EXPORT_COLUMNS) + raw_columns
    return pd.DataFrame(rows, columns=columns)


def export_industrial_dataframe_workbook(
    *,
    dataframe: pd.DataFrame,
    output_file: str,
    filter_state: IndustrialFilterState | None = None,
    grouping_state: IndustrialGroupingState | None = None,
    include_charts: bool = True,
    include_raw_data: bool = True,
    cancel_check: CancelCheck | None = None,
    diagnostics_extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write industrial rows, grouped summary, diagnostics, and charts to a workbook."""

    output_path = Path(output_file)
    if output_path.suffix.lower() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_name(f".{output_path.stem}.tmp{output_path.suffix}")
    if temp_output_path.exists():
        temp_output_path.unlink()

    _raise_if_cancelled(cancel_check)
    export_frame = _industrial_export_dataframe(dataframe, include_raw_data=include_raw_data)
    raw_frame = _industrial_raw_export_dataframe(dataframe) if include_raw_data else pd.DataFrame()
    summary = build_industrial_summary(export_frame, grouping_state=grouping_state)
    _raise_if_cancelled(cancel_check)
    diagnostics_row = {
        "row_count": int(len(export_frame.index)),
        "filter_references": len(tuple((filter_state or IndustrialFilterState()).references)),
        "grouping": (grouping_state or IndustrialGroupingState()).summary(),
        "charts": bool(include_charts),
        "raw_data": bool(include_raw_data),
        "raw_sheet_rows": int(len(raw_frame.index)),
    }
    if diagnostics_extra:
        diagnostics_row.update(dict(diagnostics_extra))
    diagnostics = pd.DataFrame([diagnostics_row])

    try:
        with pd.ExcelWriter(temp_output_path, engine="xlsxwriter") as writer:
            export_frame.to_excel(writer, sheet_name="Industrial Data", index=False)
            _raise_if_cancelled(cancel_check)
            if include_raw_data and not raw_frame.empty:
                raw_frame.to_excel(writer, sheet_name="Raw Data", index=False)
            _raise_if_cancelled(cancel_check)
            summary.to_excel(writer, sheet_name="Industrial Summary", index=False)
            _raise_if_cancelled(cancel_check)
            diagnostics.to_excel(writer, sheet_name="Diagnostics", index=False)
            _raise_if_cancelled(cancel_check)
            if include_charts:
                _write_industrial_charts(writer, summary)
                _raise_if_cancelled(cancel_check)
        _raise_if_cancelled(cancel_check)
        temp_output_path.replace(output_path)
    except IndustrialExportCancelled:
        temp_output_path.unlink(missing_ok=True)
        raise
    except Exception:
        temp_output_path.unlink(missing_ok=True)
        raise

    return {
        "output_file": str(output_path),
        "row_count": int(len(export_frame.index)),
        "summary_rows": int(len(summary.index)),
        "charts": bool(include_charts),
        "raw_data": bool(include_raw_data),
        "raw_sheet_rows": int(len(raw_frame.index)),
    }


def _industrial_export_dataframe(dataframe: pd.DataFrame, *, include_raw_data: bool) -> pd.DataFrame:
    if include_raw_data:
        return dataframe.copy()
    return dataframe.drop(columns=["raw_record_json"], errors="ignore").copy()


def _industrial_raw_export_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    raw_columns = [
        column
        for column in dataframe.columns
        if column == "raw_record_json" or column not in INDUSTRIAL_EXPORT_COLUMNS
    ]
    if not raw_columns:
        return pd.DataFrame()
    leading_columns = [
        column
        for column in ("source_db_alias", "source_record_key", "reference", "process_timestamp")
        if column in dataframe.columns
    ]
    columns = [*leading_columns, *(column for column in raw_columns if column not in leading_columns)]
    raw_frame = dataframe.loc[:, columns].copy()
    return raw_frame.dropna(axis=1, how="all")


def _canonical_export_value(record: Mapping[str, Any], column: str, *, profile: Any) -> Any:
    if column == "source_db_alias":
        return (
            record.get("source_db_alias")
            or record.get("source_database_alias")
            or getattr(profile, "source_db_alias", "")
        )
    if column == "source_record_key":
        return record.get("source_record_key") or record.get("source_primary_key")
    if column == "batch_lot":
        return record.get("batch_lot") or record.get("batch") or record.get("lot")
    if column == "operator_name":
        return record.get("operator_name") or record.get("operator")
    if column == "process_status":
        return record.get("process_status") or record.get("status")
    return record.get(column)


def _excel_cell_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _live_fetch_warning_detail(diagnostics: Mapping[str, Any], error: str | None) -> str | None:
    candidates: list[Any] = []
    if isinstance(diagnostics, Mapping):
        candidates.extend(diagnostics.get("errors") or ())
        candidates.extend(diagnostics.get("warnings") or ())
        if diagnostics.get("partial_success") or diagnostics.get("completed_with_warnings"):
            candidates.append("Oznak completed with warnings. Check export diagnostics for details.")
    if error:
        candidates.append(error)
    for candidate in candidates:
        text = redact_sensitive_text(candidate)
        if text:
            return text
    return None


def _write_industrial_charts(writer: pd.ExcelWriter, summary: pd.DataFrame) -> None:
    workbook = writer.book
    chart_sheet = workbook.add_worksheet("Industrial Charts")
    chart_sheet.write(0, 0, "Industrial production-line records")
    if summary.empty:
        chart_sheet.write(2, 0, "No cached industrial rows matched the selected filter.")
        return

    count_col = int(summary.columns.get_loc("record_count"))
    chart = create_workbook_chart(workbook, "column")
    last_row = len(summary.index)
    chart.add_series(
        {
            "name": "Record count",
            "categories": ["Industrial Summary", 1, 0, last_row, 0],
            "values": ["Industrial Summary", 1, count_col, last_row, count_col],
        }
    )
    apply_chart_options(
        chart,
        title={"name": "Record count by group"},
        x_axis={"name": "Group"},
        y_axis={"name": "Records"},
        legend={"none": True},
    )
    insert_chart(chart_sheet, 2, 0, chart, x_scale=1.6, y_scale=1.25)


def _resolve_filter_column(conn, reference_column: str) -> str:
    column = str(reference_column or "reference").strip()
    require_identifier("reference column", column)
    if column in INDUSTRIAL_FILTER_RECORD_COLUMNS:
        return column
    row = conn.execute(
        "SELECT 1 FROM industrial_record_values WHERE field_name = ? LIMIT 1",
        (column,),
    ).fetchone()
    if row is not None:
        return column
    raise ValueError(f"Unsupported industrial filter column: {column}")


def _raise_if_cancelled(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise IndustrialExportCancelled("Industrial export was cancelled.")

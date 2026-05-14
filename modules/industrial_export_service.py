"""Export cached Oznak industrial production-line data with summaries and charts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from modules.industrial_data_repository import redact_sensitive_text
from modules.db import sqlite_connection_scope
from modules.industrial_workflow_state import (
    IndustrialFilterState,
    IndustrialGroupingState,
    require_identifier,
)
from modules.oznak_adapter import fetch_oznak_records_for_source_profile

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


class IndustrialExportCancelled(Exception):
    """Raised when a cached industrial export is cancelled before finalization."""


def load_cached_industrial_dataframe(
    db_file: str,
    *,
    filter_state: IndustrialFilterState | None = None,
) -> pd.DataFrame:
    """Load cached industrial rows, optionally scoped to selected references."""

    filter_state = filter_state or IndustrialFilterState()
    select_columns = ", ".join(f"ir.{column}" for column in INDUSTRIAL_EXPORT_COLUMNS)
    base_query = f"""
        SELECT {select_columns}
        FROM industrial_records ir
    """
    references = tuple(filter_state.references)
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
                query = (
                    f"{base_query} "
                    f"JOIN temp_industrial_reference_filter rf ON rf.reference = ir.{reference_column} "
                    "ORDER BY ir.reference COLLATE NOCASE, ir.process_timestamp, ir.id"
                )
                return pd.read_sql_query(query, conn)

            query = (
                f"{base_query} "
                "WHERE EXISTS ("
                "  SELECT 1"
                "  FROM industrial_record_values rv"
                "  JOIN temp_industrial_reference_filter rf"
                "    ON rf.reference = COALESCE(rv.field_value_text, rv.field_value_json, '')"
                "  WHERE rv.record_id = ir.id AND rv.field_name = ?"
                ") "
                "ORDER BY ir.reference COLLATE NOCASE, ir.process_timestamp, ir.id"
            )
            return pd.read_sql_query(query, conn, params=(reference_column,))

        query = f"{base_query} ORDER BY ir.reference COLLATE NOCASE, ir.process_timestamp, ir.id"
        return pd.read_sql_query(query, conn)


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
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    """Write cached Oznak data, grouped summary, diagnostics, and basic charts."""

    _raise_if_cancelled(cancel_check)
    dataframe = load_cached_industrial_dataframe(db_file, filter_state=filter_state)
    return export_industrial_dataframe_workbook(
        dataframe=dataframe,
        output_file=output_file,
        filter_state=filter_state,
        grouping_state=grouping_state,
        include_charts=include_charts,
        cancel_check=cancel_check,
        diagnostics_extra={"source_kind": "cached"},
    )


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
    summary = build_industrial_summary(dataframe, grouping_state=grouping_state)
    _raise_if_cancelled(cancel_check)
    diagnostics_row = {
        "row_count": int(len(dataframe.index)),
        "filter_references": len(tuple((filter_state or IndustrialFilterState()).references)),
        "grouping": (grouping_state or IndustrialGroupingState()).summary(),
        "charts": bool(include_charts),
    }
    if diagnostics_extra:
        diagnostics_row.update(dict(diagnostics_extra))
    diagnostics = pd.DataFrame([diagnostics_row])

    try:
        with pd.ExcelWriter(temp_output_path, engine="xlsxwriter") as writer:
            dataframe.to_excel(writer, sheet_name="Industrial Data", index=False)
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
        "row_count": int(len(dataframe.index)),
        "summary_rows": int(len(summary.index)),
        "charts": bool(include_charts),
    }


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
    chart = workbook.add_chart({"type": "column"})
    last_row = len(summary.index)
    chart.add_series(
        {
            "name": "Record count",
            "categories": ["Industrial Summary", 1, 0, last_row, 0],
            "values": ["Industrial Summary", 1, count_col, last_row, count_col],
        }
    )
    chart.set_title({"name": "Record count by group"})
    chart.set_x_axis({"name": "Group"})
    chart.set_y_axis({"name": "Records"})
    chart.set_legend({"none": True})
    chart_sheet.insert_chart(2, 0, chart, {"x_scale": 1.6, "y_scale": 1.25})


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

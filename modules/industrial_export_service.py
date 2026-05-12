"""Export cached Oznak industrial production-line data with summaries and charts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd

from modules.db import sqlite_connection_scope
from modules.industrial_workflow_state import (
    IndustrialFilterState,
    IndustrialGroupingState,
    require_identifier,
)

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

    output_path = Path(output_file)
    if output_path.suffix.lower() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_name(f".{output_path.stem}.tmp{output_path.suffix}")
    if temp_output_path.exists():
        temp_output_path.unlink()

    _raise_if_cancelled(cancel_check)
    dataframe = load_cached_industrial_dataframe(db_file, filter_state=filter_state)
    _raise_if_cancelled(cancel_check)
    summary = build_industrial_summary(dataframe, grouping_state=grouping_state)
    _raise_if_cancelled(cancel_check)
    diagnostics = pd.DataFrame(
        [
            {
                "row_count": int(len(dataframe.index)),
                "filter_references": len(tuple((filter_state or IndustrialFilterState()).references)),
                "grouping": (grouping_state or IndustrialGroupingState()).summary(),
                "charts": bool(include_charts),
            }
        ]
    )

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

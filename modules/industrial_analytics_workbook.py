"""Workbook writer for production analytics dataframes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from modules.excel_sheet_utils import unique_sheet_name
from modules.industrial_analytics_service import (
    ProductionAggregationResult,
    ProductionAnalyticsDiagnostic,
    ProductionGroupstatsResult,
)
from modules.industrial_analytics_state import ProductionMetricSelection
from modules.industrial_analytics_state import ProductionChartSelection
from modules.industrial_analytics_workbook_charts import add_analytics_workbook_charts


@dataclass(frozen=True)
class IndustrialAnalyticsWorkbookResult:
    """Workbook export result for production analytics."""

    output_file: str
    sheet_names: tuple[str, ...]
    parameter_sheet_count: int


def export_production_analytics_workbook(
    *,
    dataframe: pd.DataFrame,
    metric_selection: tuple[ProductionMetricSelection, ...],
    output_file: str | Path,
    aggregation_result: ProductionAggregationResult | None = None,
    groupstats_result: ProductionGroupstatsResult | None = None,
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = (),
    separate_parameter_sheets: bool = True,
    chart_selection: ProductionChartSelection | None = None,
) -> IndustrialAnalyticsWorkbookResult:
    """Write production analytics workbook output."""

    output_path = Path(output_file)
    if output_path.suffix.lower() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    sheet_names: list[str] = []
    safe_dataframe = _excel_safe_dataframe(_public_dataframe(dataframe))
    safe_aggregation_frame = (
        _excel_safe_dataframe(aggregation_result.dataframe)
        if aggregation_result is not None
        else None
    )

    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        data_sheet = unique_sheet_name("Production Data", used_names)
        safe_dataframe.to_excel(writer, sheet_name=data_sheet, index=False)
        sheet_names.append(data_sheet)

        if safe_aggregation_frame is not None and not safe_aggregation_frame.empty:
            aggregate_sheet = unique_sheet_name("Aggregates", used_names)
            safe_aggregation_frame.to_excel(writer, sheet_name=aggregate_sheet, index=False)
            sheet_names.append(aggregate_sheet)

        metric_sheet = unique_sheet_name("Metrics", used_names)
        _metric_summary_dataframe(safe_dataframe, metric_selection).to_excel(
            writer,
            sheet_name=metric_sheet,
            index=False,
        )
        sheet_names.append(metric_sheet)

        add_analytics_workbook_charts(
            writer=writer,
            dataframe=safe_dataframe,
            metric_selection=metric_selection,
            chart_selection=chart_selection,
            data_sheet_name=data_sheet,
            used_names=used_names,
            sheet_names=sheet_names,
        )

        if groupstats_result is not None and groupstats_result.metrics:
            stats_sheet = unique_sheet_name("Groupstats", used_names)
            _groupstats_dataframe(groupstats_result).to_excel(
                writer,
                sheet_name=stats_sheet,
                index=False,
            )
            sheet_names.append(stats_sheet)

        diagnostics_sheet = unique_sheet_name("Diagnostics", used_names)
        _diagnostics_dataframe(diagnostics).to_excel(writer, sheet_name=diagnostics_sheet, index=False)
        sheet_names.append(diagnostics_sheet)

        parameter_sheet_count = 0
        if separate_parameter_sheets:
            for metric in metric_selection:
                if metric.field_name not in safe_dataframe.columns:
                    continue
                parameter_sheet = unique_sheet_name(metric.display_label, used_names)
                _parameter_dataframe(safe_dataframe, metric.field_name).to_excel(
                    writer,
                    sheet_name=parameter_sheet,
                    index=False,
                )
                sheet_names.append(parameter_sheet)
                parameter_sheet_count += 1

    return IndustrialAnalyticsWorkbookResult(
        output_file=str(output_path),
        sheet_names=tuple(sheet_names),
        parameter_sheet_count=parameter_sheet_count,
    )


def _excel_safe_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    safe_frame = dataframe.copy()
    for column in safe_frame.columns:
        if isinstance(safe_frame[column].dtype, pd.DatetimeTZDtype):
            safe_frame[column] = safe_frame[column].dt.tz_convert(None)
    return safe_frame


def _public_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    return dataframe.drop(columns=["raw_record_json"], errors="ignore").copy()


def _metric_summary_dataframe(
    dataframe: pd.DataFrame,
    metric_selection: tuple[ProductionMetricSelection, ...],
) -> pd.DataFrame:
    rows = []
    for metric in metric_selection:
        if metric.field_name not in dataframe.columns:
            continue
        values = pd.to_numeric(dataframe[metric.field_name], errors="coerce").dropna()
        rows.append(
            {
                "metric": metric.display_label,
                "field_name": metric.field_name,
                "source_kind": metric.source_kind,
                "n": int(values.count()),
                "mean": float(values.mean()) if not values.empty else None,
                "median": float(values.median()) if not values.empty else None,
                "std": float(values.std(ddof=1)) if len(values.index) > 1 else None,
                "min": float(values.min()) if not values.empty else None,
                "max": float(values.max()) if not values.empty else None,
            }
        )
    return pd.DataFrame(rows)


def _groupstats_dataframe(groupstats_result: ProductionGroupstatsResult) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for metric in groupstats_result.metrics:
        metric_name = metric.get("metric") or metric.get("field_name")
        for row in metric.get("descriptive_stats") or []:
            rows.append(
                {
                    "metric": metric_name,
                    "row_type": "descriptive",
                    "group": row.get("group"),
                    "n": row.get("n"),
                    "mean": row.get("mean"),
                    "std": row.get("std"),
                    "median": row.get("median"),
                    "iqr": row.get("iqr"),
                    "min": row.get("min"),
                    "max": row.get("max"),
                }
            )
        for row in metric.get("pairwise_rows") or []:
            rows.append(
                {
                    "metric": metric_name,
                    "row_type": "pairwise",
                    "group": f"{row.get('group_a')} vs {row.get('group_b')}",
                    "p_value": row.get("p_value"),
                    "adjusted_p_value": row.get("adjusted_p_value"),
                    "effect_size": row.get("effect_size"),
                    "test_used": row.get("test_used"),
                    "significant": row.get("significant"),
                }
            )
    if not rows:
        rows.append({"row_type": "info", "message": "No groupstats rows available."})
    return pd.DataFrame(rows)


def _diagnostics_dataframe(diagnostics: tuple[ProductionAnalyticsDiagnostic, ...]) -> pd.DataFrame:
    if not diagnostics:
        return pd.DataFrame([{"severity": "info", "code": "ok", "message": "No diagnostics."}])
    return pd.DataFrame(
        [
            {
                "severity": diagnostic.severity,
                "code": diagnostic.code,
                "message": diagnostic.message,
                "context": diagnostic.context,
            }
            for diagnostic in diagnostics
        ]
    )


def _parameter_dataframe(dataframe: pd.DataFrame, metric_field: str) -> pd.DataFrame:
    context_columns = [
        column
        for column in (
            "industrial_record_id",
            "source_row_number",
            "process_datetime",
            "reference",
            "source_db_alias",
            "station",
            "line",
            "operator_name",
            "process_status",
            "source_file",
            "source_sheet",
        )
        if column in dataframe.columns
    ]
    columns = list(dict.fromkeys(context_columns + [metric_field]))
    parameter_frame = dataframe.loc[:, columns].copy()
    parameter_frame[metric_field] = pd.to_numeric(parameter_frame[metric_field], errors="coerce")
    return parameter_frame


__all__ = [
    "IndustrialAnalyticsWorkbookResult",
    "export_production_analytics_workbook",
]

"""Workbook writer for production analytics dataframes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from metroliza.shared.excel_sheet_utils import unique_sheet_name
from metroliza.industrial.industrial_analytics_service import (
    ProductionAggregationResult,
    ProductionAnalyticsDiagnostic,
    ProductionGroupstatsResult,
)
from metroliza.industrial.industrial_analytics_helpers import diagnostics_dataframe
from metroliza.industrial.industrial_analytics_state import ProductionMetricSelection
from metroliza.industrial.industrial_analytics_state import ProductionChartSelection
from metroliza.industrial.industrial_analytics_workbook_charts import add_analytics_workbook_charts


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
    group_fields: tuple[str, ...] = (),
    include_raw_data: bool = False,
) -> IndustrialAnalyticsWorkbookResult:
    """Write production analytics workbook output."""

    output_path = Path(output_file)
    if output_path.suffix.lower() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    sheet_names: list[str] = []
    safe_dataframe = _excel_safe_dataframe(
        _analytics_workbook_dataframe(dataframe, include_raw_data=include_raw_data)
    )
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
            group_fields=group_fields,
        )

        if groupstats_result is not None and groupstats_result.metrics:
            stats_sheet = unique_sheet_name("Groupstats", used_names)
            groupstats_result_dataframe(groupstats_result).to_excel(
                writer,
                sheet_name=stats_sheet,
                index=False,
            )
            sheet_names.append(stats_sheet)

        diagnostics_sheet = unique_sheet_name("Diagnostics", used_names)
        diagnostics_dataframe(diagnostics).to_excel(writer, sheet_name=diagnostics_sheet, index=False)
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


def _analytics_workbook_dataframe(dataframe: pd.DataFrame, *, include_raw_data: bool) -> pd.DataFrame:
    if include_raw_data:
        return dataframe.copy()
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


def groupstats_result_dataframe(groupstats_result: ProductionGroupstatsResult) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for metric in groupstats_result.metrics:
        metric_name = metric.get("metric") or metric.get("field_name")
        insight = metric.get("primary_insight") if isinstance(metric.get("primary_insight"), dict) else {}
        insight_text = str(
            insight.get("headline")
            or insight.get("first_action")
            or insight.get("summary")
            or ""
        ).strip()
        if insight_text:
            rows.append(
                {
                    "metric": metric_name,
                    "row_type": "insight",
                    "message": insight_text,
                    "why": insight.get("why"),
                    "first_action": insight.get("first_action"),
                    "status_class": insight.get("status_class"),
                }
            )
        metric_summary = metric.get("metric_summary") if isinstance(metric.get("metric_summary"), dict) else {}
        rows.append(
            {
                "metric": metric_name,
                "row_type": "metric_summary",
                "backend_used": metric.get("backend_used") or metric_summary.get("backend_used"),
                "selection_detail": metric.get("selection_detail") or metric_summary.get("selection_detail"),
                "posthoc_family": metric.get("posthoc_family") or metric_summary.get("posthoc_family"),
                "posthoc_method_name": metric.get("posthoc_method_name")
                or metric_summary.get("posthoc_method_name"),
                "pairwise_strategy": metric.get("pairwise_strategy"),
                "posthoc_strategy": metric.get("posthoc_strategy") or metric_summary.get("posthoc_strategy"),
                "capability_strategy": metric.get("capability_strategy")
                or metric_summary.get("capability_strategy"),
                "correction_method": metric.get("correction_method") or metric_summary.get("correction_method"),
                "correction_policy": metric.get("correction_policy") or metric_summary.get("correction_policy"),
                "analysis_restriction_label": metric.get("analysis_restriction_label")
                or metric_summary.get("analysis_restriction_label"),
                "distribution_flags": "; ".join(metric.get("distribution_flags") or []),
                "simulation_validation": metric.get("simulation_validation")
                or metric_summary.get("simulation_validation"),
                "capability_benchmark": metric.get("capability_benchmark"),
            }
        )
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
                    "cp": row.get("cp"),
                    "cpk": row.get("cpk"),
                    "capability": row.get("capability"),
                    "nok_count": row.get("nok_count"),
                    "nok_percent": row.get("nok_percent"),
                    "warnings": "; ".join(row.get("warnings") or []),
                }
            )
        for row in metric.get("capability_rows") or []:
            rows.append(
                {
                    "metric": metric_name,
                    "row_type": "capability",
                    "group": row.get("group"),
                    "n": row.get("n"),
                    "mean": row.get("mean"),
                    "sigma": row.get("sigma"),
                    "lsl": row.get("lsl"),
                    "nominal": row.get("nominal"),
                    "usl": row.get("usl"),
                    "cp": row.get("cp"),
                    "cpl": row.get("cpl"),
                    "cpu": row.get("cpu"),
                    "cpk": row.get("cpk"),
                    "cp_ci": row.get("cp_ci"),
                    "cpk_ci": row.get("cpk_ci"),
                    "warnings": "; ".join(row.get("warnings") or []),
                }
            )
        for row in metric.get("distribution_rows") or []:
            rows.append(
                {
                    "metric": metric_name,
                    "row_type": "distribution",
                    "group": row.get("group"),
                    "n": row.get("n"),
                    "skewness": row.get("skewness"),
                    "excess_kurtosis": row.get("excess_kurtosis"),
                    "normality_test": row.get("normality_test"),
                    "normality_p_value": row.get("normality_p_value"),
                    "normality_status": row.get("normality_status"),
                    "warnings": "; ".join(row.get("warnings") or []),
                }
            )
        omnibus = metric.get("omnibus") if isinstance(metric.get("omnibus"), dict) else {}
        if omnibus:
            rows.append(
                {
                    "metric": metric_name,
                    "row_type": "overall",
                    "group": "All groups",
                    "p_value": omnibus.get("p_value"),
                    "effect_size": omnibus.get("effect_size"),
                    "effect_type": omnibus.get("effect_type"),
                    "test_used": omnibus.get("test_name"),
                    "significant": omnibus.get("significant"),
                }
            )
        for row in metric.get("pairwise_rows") or []:
            rows.append(
                {
                    "metric": metric_name,
                    "row_type": "pairwise",
                    "group": f"{row.get('group_a')} vs {row.get('group_b')}",
                    "delta_mean": row.get("delta_mean"),
                    "p_value": row.get("p_value"),
                    "adjusted_p_value": row.get("adjusted_p_value"),
                    "effect_size": row.get("effect_size"),
                    "effect_type": row.get("effect_type"),
                    "test_used": row.get("test_used"),
                    "method_family": row.get("method_family"),
                    "comparison_estimate": row.get("comparison_estimate"),
                    "comparison_estimate_label": row.get("comparison_estimate_label"),
                    "comparison_ci": row.get("comparison_ci"),
                    "effect_size_ci": row.get("effect_size_ci"),
                    "significant": row.get("significant"),
                    "warnings": "; ".join(row.get("warnings") or []),
                }
            )
        for row in metric.get("posthoc_rows") or []:
            rows.append(
                {
                    "metric": metric_name,
                    "row_type": "posthoc",
                    "group": f"{row.get('group_a')} vs {row.get('group_b')}",
                    "p_value": row.get("raw_p_value"),
                    "adjusted_p_value": row.get("adjusted_p_value"),
                    "effect_size": row.get("effect_size"),
                    "effect_type": row.get("effect_type"),
                    "test_used": row.get("method_name"),
                    "method_family": row.get("family"),
                    "comparison_estimate": row.get("comparison_estimate"),
                    "comparison_estimate_label": row.get("comparison_estimate_label"),
                    "comparison_ci": row.get("comparison_ci"),
                    "effect_size_ci": row.get("effect_size_ci"),
                    "significant": row.get("significant"),
                    "warnings": "; ".join(row.get("warnings") or []),
                }
            )
    if not rows:
        rows.append({"row_type": "info", "message": "No groupstats rows available."})
    return pd.DataFrame(rows)


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
    "groupstats_result_dataframe",
]

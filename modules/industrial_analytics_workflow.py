"""End-to-end analytics workflow for cached production and CSV/Excel sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from modules.industrial_analytics_dashboard import (
    build_production_dashboard_manifest,
    write_production_dashboard,
)
from modules.industrial_analytics_service import (
    ProductionAnalyticsDiagnostic,
    ProductionGroupstatsResult,
    aggregate_production_frame,
    analyze_production_groupstats,
    apply_reference_cohorts,
    discover_production_metric_candidates,
    load_production_analytics_frame,
)
from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionFilterState,
    ProductionMetricSelection,
    ReferenceCohortState,
)
from modules.industrial_analytics_workbook import (
    IndustrialAnalyticsWorkbookResult,
    export_production_analytics_workbook,
)
from modules.tabular_analytics_service import (
    TabularAnalyticsWorkbookResult,
    export_tabular_analytics_workbook,
    load_tabular_analytics_file,
)

AnalyticsSourceKind = Literal["production_cache", "tabular_file"]


@dataclass(frozen=True)
class IndustrialAnalyticsRunResult:
    """End-to-end analytics run result."""

    source_kind: AnalyticsSourceKind
    html_dashboard_path: str
    html_dashboard_assets_path: str
    html_dashboard_chart_count: int
    workbook_path: str = ""
    workbook_sheet_names: tuple[str, ...] = ()
    parameter_sheet_count: int = 0
    row_count: int = 0
    aggregate_row_count: int = 0
    metric_count: int = 0
    groupstats_metric_count: int = 0
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = field(default_factory=tuple)


def run_production_cache_analytics(
    *,
    db_file: str,
    output_dashboard_file: str,
    metric_selection: tuple[ProductionMetricSelection, ...] = (),
    filter_state: ProductionFilterState | None = None,
    aggregation_state: ProductionAggregationState | None = None,
    cohort_state: ReferenceCohortState | None = None,
    chart_selection: ProductionChartSelection | None = None,
    output_workbook_file: str | None = None,
    separate_parameter_sheets: bool = True,
) -> IndustrialAnalyticsRunResult:
    """Run production analytics from the local Oznak cache."""

    metrics = metric_selection or tuple(
        candidate.to_selection()
        for candidate in discover_production_metric_candidates(db_file)[:5]
    )
    aggregation = aggregation_state or ProductionAggregationState()
    charts = chart_selection or ProductionChartSelection()
    cohort = cohort_state or ReferenceCohortState()

    loaded = load_production_analytics_frame(
        db_file,
        filter_state=filter_state,
        metric_selection=metrics,
    )
    cohorted = apply_reference_cohorts(loaded.dataframe, cohort)
    aggregated = aggregate_production_frame(cohorted.dataframe, aggregation, metrics)
    groupstats = _analyze_groupstats_if_enabled(
        cohorted.dataframe,
        metrics,
        aggregation_state=aggregation,
        cohort_state=cohort,
        chart_selection=charts,
    )
    diagnostics = (
        loaded.diagnostics
        + cohorted.diagnostics
        + aggregated.diagnostics
        + groupstats.diagnostics
    )
    dashboard = _write_dashboard(
        frame=cohorted.dataframe,
        metrics=metrics,
        aggregation=aggregation,
        aggregated=aggregated,
        groupstats=groupstats,
        charts=charts,
        cohort=cohort,
        diagnostics=diagnostics,
        output_dashboard_file=output_dashboard_file,
    )
    workbook = None
    if output_workbook_file:
        workbook = export_production_analytics_workbook(
            dataframe=cohorted.dataframe,
            metric_selection=metrics,
            output_file=output_workbook_file,
            aggregation_result=aggregated,
            groupstats_result=groupstats,
            diagnostics=diagnostics,
            separate_parameter_sheets=separate_parameter_sheets,
        )
    return _run_result(
        source_kind="production_cache",
        dashboard=dashboard,
        workbook=workbook,
        row_count=len(cohorted.dataframe.index),
        aggregate_row_count=aggregated.output_row_count,
        metric_count=len(metrics),
        groupstats_metric_count=groupstats.analyzed_metric_count,
        diagnostics=diagnostics,
    )


def run_tabular_file_analytics(
    *,
    input_file: str,
    output_dashboard_file: str,
    metric_selection: tuple[ProductionMetricSelection, ...] = (),
    sheet_name: str | int | None = None,
    timestamp_column: str | None = None,
    reference_column: str | None = None,
    aggregation_state: ProductionAggregationState | None = None,
    cohort_state: ReferenceCohortState | None = None,
    chart_selection: ProductionChartSelection | None = None,
    output_workbook_file: str | None = None,
    separate_parameter_sheets: bool = True,
) -> IndustrialAnalyticsRunResult:
    """Run analytics from a CSV or Excel file."""

    loaded = load_tabular_analytics_file(
        input_file,
        sheet_name=sheet_name,
        timestamp_column=timestamp_column,
        reference_column=reference_column,
    )
    metrics = metric_selection or tuple(candidate.to_selection() for candidate in loaded.metric_candidates[:5])
    aggregation = aggregation_state or ProductionAggregationState()
    charts = chart_selection or ProductionChartSelection()
    cohort = cohort_state or ReferenceCohortState()
    cohorted = apply_reference_cohorts(loaded.dataframe, cohort)
    aggregated = aggregate_production_frame(cohorted.dataframe, aggregation, metrics)
    groupstats = _analyze_groupstats_if_enabled(
        cohorted.dataframe,
        metrics,
        aggregation_state=aggregation,
        cohort_state=cohort,
        chart_selection=charts,
    )
    diagnostics = (
        loaded.diagnostics
        + cohorted.diagnostics
        + aggregated.diagnostics
        + groupstats.diagnostics
    )
    dashboard = _write_dashboard(
        frame=cohorted.dataframe,
        metrics=metrics,
        aggregation=aggregation,
        aggregated=aggregated,
        groupstats=groupstats,
        charts=charts,
        cohort=cohort,
        diagnostics=diagnostics,
        output_dashboard_file=output_dashboard_file,
    )
    workbook = None
    if output_workbook_file:
        selected_fields = {metric.field_name for metric in metrics}
        selected_candidates = tuple(
            candidate for candidate in loaded.metric_candidates if candidate.field_name in selected_fields
        )
        workbook = export_tabular_analytics_workbook(
            dataframe=cohorted.dataframe,
            metric_candidates=selected_candidates,
            output_file=output_workbook_file,
            aggregation_result=aggregated,
            diagnostics=diagnostics,
            separate_parameter_sheets=separate_parameter_sheets,
        )
    return _run_result(
        source_kind="tabular_file",
        dashboard=dashboard,
        workbook=workbook,
        row_count=len(cohorted.dataframe.index),
        aggregate_row_count=aggregated.output_row_count,
        metric_count=len(metrics),
        groupstats_metric_count=groupstats.analyzed_metric_count,
        diagnostics=diagnostics,
    )


def _analyze_groupstats_if_enabled(
    dataframe,
    metrics: tuple[ProductionMetricSelection, ...],
    *,
    aggregation_state: ProductionAggregationState,
    cohort_state: ReferenceCohortState,
    chart_selection: ProductionChartSelection,
) -> ProductionGroupstatsResult:
    if not chart_selection.groupstats:
        return ProductionGroupstatsResult()
    return analyze_production_groupstats(
        dataframe,
        metrics,
        aggregation_state=aggregation_state,
        cohort_state=cohort_state,
    )


def _write_dashboard(
    *,
    frame,
    metrics: tuple[ProductionMetricSelection, ...],
    aggregation: ProductionAggregationState,
    aggregated,
    groupstats: ProductionGroupstatsResult,
    charts: ProductionChartSelection,
    cohort: ReferenceCohortState,
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...],
    output_dashboard_file: str,
) -> dict[str, object]:
    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=metrics,
        aggregation_state=aggregation,
        aggregation_result=aggregated,
        groupstats_result=groupstats,
        chart_selection=charts,
        cohort_state=cohort,
        diagnostics=diagnostics,
    )
    return write_production_dashboard(manifest, output_dashboard_file)


def _run_result(
    *,
    source_kind: AnalyticsSourceKind,
    dashboard: dict[str, object],
    workbook: IndustrialAnalyticsWorkbookResult | TabularAnalyticsWorkbookResult | None,
    row_count: int,
    aggregate_row_count: int,
    metric_count: int,
    groupstats_metric_count: int,
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...],
) -> IndustrialAnalyticsRunResult:
    workbook_path = ""
    workbook_sheet_names: tuple[str, ...] = ()
    parameter_sheet_count = 0
    if workbook is not None:
        workbook_path = str(workbook.output_file)
        workbook_sheet_names = tuple(workbook.sheet_names)
        parameter_sheet_count = int(workbook.parameter_sheet_count)
    return IndustrialAnalyticsRunResult(
        source_kind=source_kind,
        html_dashboard_path=str(dashboard.get("html_dashboard_path") or ""),
        html_dashboard_assets_path=str(dashboard.get("html_dashboard_assets_path") or ""),
        html_dashboard_chart_count=int(dashboard.get("html_dashboard_chart_count") or 0),
        workbook_path=workbook_path,
        workbook_sheet_names=workbook_sheet_names,
        parameter_sheet_count=parameter_sheet_count,
        row_count=int(row_count),
        aggregate_row_count=int(aggregate_row_count),
        metric_count=int(metric_count),
        groupstats_metric_count=int(groupstats_metric_count),
        diagnostics=diagnostics,
    )


def default_dashboard_path(base_file: str | Path, *, suffix: str = "analytics") -> str:
    path = Path(base_file)
    stem = path.stem or "analytics"
    return str(path.with_name(f"{stem}_{suffix}.html"))


def default_workbook_path(base_file: str | Path, *, suffix: str = "analytics") -> str:
    path = Path(base_file)
    stem = path.stem or "analytics"
    return str(path.with_name(f"{stem}_{suffix}.xlsx"))


__all__ = [
    "IndustrialAnalyticsRunResult",
    "default_dashboard_path",
    "default_workbook_path",
    "run_production_cache_analytics",
    "run_tabular_file_analytics",
]

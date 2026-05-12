"""End-to-end analytics workflow for cached production and CSV/Excel sources."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

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
from modules.progress_status import build_three_line_status
from modules.tabular_analytics_service import (
    TABULAR_GROUP_COLUMN,
    TabularAnalyticsWorkbookResult,
    apply_tabular_grouping,
    export_tabular_analytics_workbook,
    load_tabular_analytics_file,
)

AnalyticsSourceKind = Literal["production_cache", "tabular_file"]
CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[str], None]


class AnalyticsCancelled(RuntimeError):
    """Raised when an analytics run is canceled before output finalization."""


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
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
) -> IndustrialAnalyticsRunResult:
    """Run production analytics from the local Oznak cache."""

    start_time = time.perf_counter()
    total_steps = 6 if output_workbook_file else 5
    _emit_progress(
        progress_callback,
        "Loading production data...",
        "Reading cached rows and selected metrics",
        step=1,
        total_steps=total_steps,
        start_time=start_time,
    )
    _raise_if_cancelled(cancel_check)
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
    _emit_progress(
        progress_callback,
        "Applying references...",
        "Marking selected comparison cohorts",
        step=2,
        total_steps=total_steps,
        start_time=start_time,
    )
    _raise_if_cancelled(cancel_check)
    cohorted = apply_reference_cohorts(loaded.dataframe, cohort)
    _emit_progress(
        progress_callback,
        "Aggregating metrics...",
        "Computing selected grouping and time buckets",
        step=3,
        total_steps=total_steps,
        start_time=start_time,
    )
    _raise_if_cancelled(cancel_check)
    aggregated = aggregate_production_frame(cohorted.dataframe, aggregation, metrics)
    _emit_progress(
        progress_callback,
        "Running statistical analysis...",
        "Analyzing selected metrics" if charts.groupstats else "Groupstats disabled for this run",
        step=4,
        total_steps=total_steps,
        start_time=start_time,
    )
    _raise_if_cancelled(cancel_check)
    groupstats = _analyze_groupstats_if_enabled(
        cohorted.dataframe,
        metrics,
        aggregation_state=aggregation,
        cohort_state=cohort,
        chart_selection=charts,
    )
    _raise_if_cancelled(cancel_check)
    diagnostics = (
        loaded.diagnostics
        + cohorted.diagnostics
        + aggregated.diagnostics
        + groupstats.diagnostics
    )
    _emit_progress(
        progress_callback,
        "Writing dashboard...",
        "Rendering HTML dashboard and chart payloads",
        step=5,
        total_steps=total_steps,
        start_time=start_time,
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
        dashboard_title="Production Analytics",
        dashboard_subtitle="Cached production data dashboard generated by Metroliza.",
        cancel_check=cancel_check,
    )
    workbook = None
    if output_workbook_file:
        _emit_progress(
            progress_callback,
            "Writing workbook...",
            "Creating Excel sheets and selected plots",
            step=6,
            total_steps=total_steps,
            start_time=start_time,
        )
        _raise_if_cancelled(cancel_check)
        workbook = _export_production_workbook_with_temp(
            output_workbook_file=output_workbook_file,
            dataframe=cohorted.dataframe,
            metric_selection=metrics,
            aggregation_result=aggregated,
            groupstats_result=groupstats,
            diagnostics=diagnostics,
            separate_parameter_sheets=separate_parameter_sheets,
            chart_selection=charts,
            group_fields=aggregation.group_fields,
            cancel_check=cancel_check,
        )
    _emit_complete(
        progress_callback,
        start_time=start_time,
        includes_workbook=bool(output_workbook_file),
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
    grouping_df=None,
    aggregation_state: ProductionAggregationState | None = None,
    cohort_state: ReferenceCohortState | None = None,
    chart_selection: ProductionChartSelection | None = None,
    output_workbook_file: str | None = None,
    separate_parameter_sheets: bool = True,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
) -> IndustrialAnalyticsRunResult:
    """Run analytics from a CSV or Excel file."""

    start_time = time.perf_counter()
    total_steps = 6 if output_workbook_file else 5
    _emit_progress(
        progress_callback,
        "Loading CSV/Excel data...",
        "Reading rows and detecting metric columns",
        step=1,
        total_steps=total_steps,
        start_time=start_time,
    )
    _raise_if_cancelled(cancel_check)
    loaded = load_tabular_analytics_file(
        input_file,
        sheet_name=sheet_name,
        timestamp_column=timestamp_column,
        reference_column=reference_column,
    )
    grouped = apply_tabular_grouping(loaded.dataframe, grouping_df)
    _emit_progress(
        progress_callback,
        "Applying groups and references...",
        "Assigning manual groups and comparison cohorts",
        step=2,
        total_steps=total_steps,
        start_time=start_time,
    )
    _raise_if_cancelled(cancel_check)
    metrics = metric_selection or tuple(candidate.to_selection() for candidate in loaded.metric_candidates[:5])
    aggregation = _aggregation_with_tabular_grouping(
        aggregation_state or ProductionAggregationState(),
        grouping_applied=grouped.applied,
    )
    charts = chart_selection or ProductionChartSelection()
    cohort = cohort_state or ReferenceCohortState()
    cohorted = apply_reference_cohorts(grouped.dataframe, cohort)
    _emit_progress(
        progress_callback,
        "Aggregating metrics...",
        "Computing selected grouping and time buckets",
        step=3,
        total_steps=total_steps,
        start_time=start_time,
    )
    _raise_if_cancelled(cancel_check)
    aggregated = aggregate_production_frame(cohorted.dataframe, aggregation, metrics)
    _emit_progress(
        progress_callback,
        "Running statistical analysis...",
        "Analyzing selected metrics" if charts.groupstats else "Groupstats disabled for this run",
        step=4,
        total_steps=total_steps,
        start_time=start_time,
    )
    _raise_if_cancelled(cancel_check)
    groupstats = _analyze_groupstats_if_enabled(
        cohorted.dataframe,
        metrics,
        aggregation_state=aggregation,
        cohort_state=cohort,
        chart_selection=charts,
    )
    _raise_if_cancelled(cancel_check)
    diagnostics = (
        loaded.diagnostics
        + grouped.diagnostics
        + cohorted.diagnostics
        + aggregated.diagnostics
        + groupstats.diagnostics
    )
    _emit_progress(
        progress_callback,
        "Writing dashboard...",
        "Rendering HTML dashboard and chart payloads",
        step=5,
        total_steps=total_steps,
        start_time=start_time,
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
        dashboard_title="CSV / Excel Analytics",
        dashboard_subtitle="CSV/Excel data dashboard generated by Metroliza.",
        cancel_check=cancel_check,
    )
    workbook = None
    if output_workbook_file:
        _emit_progress(
            progress_callback,
            "Writing workbook...",
            "Creating Excel sheets and selected plots",
            step=6,
            total_steps=total_steps,
            start_time=start_time,
        )
        _raise_if_cancelled(cancel_check)
        selected_fields = {metric.field_name for metric in metrics}
        selected_candidates = tuple(
            candidate for candidate in loaded.metric_candidates if candidate.field_name in selected_fields
        )
        workbook = _export_tabular_workbook_with_temp(
            output_workbook_file=output_workbook_file,
            dataframe=cohorted.dataframe,
            metric_candidates=selected_candidates,
            aggregation_result=aggregated,
            diagnostics=diagnostics,
            separate_parameter_sheets=separate_parameter_sheets,
            chart_selection=charts,
            group_fields=aggregation.group_fields,
            cancel_check=cancel_check,
        )
    _emit_complete(
        progress_callback,
        start_time=start_time,
        includes_workbook=bool(output_workbook_file),
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


def _emit_progress(
    progress_callback: ProgressCallback | None,
    stage_line: str,
    detail_line: str,
    *,
    step: int,
    total_steps: int,
    start_time: float,
) -> None:
    if progress_callback is None:
        return
    safe_step = max(1, min(step, total_steps))
    progress_callback(
        build_three_line_status(
            stage_line,
            f"{detail_line} ({safe_step}/{total_steps})",
            _progress_timing_line(
                completed_steps=safe_step - 1,
                total_steps=total_steps,
                start_time=start_time,
            ),
        )
    )


def _emit_complete(
    progress_callback: ProgressCallback | None,
    *,
    start_time: float,
    includes_workbook: bool,
) -> None:
    if progress_callback is None:
        return
    detail_line = "Dashboard and workbook generated" if includes_workbook else "Dashboard generated"
    progress_callback(
        build_three_line_status(
            "Analytics complete",
            detail_line,
            f"{_format_duration(time.perf_counter() - start_time)} elapsed, ETA 0:00",
        )
    )


def _progress_timing_line(
    *,
    completed_steps: int,
    total_steps: int,
    start_time: float,
) -> str:
    elapsed_seconds = max(0.0, time.perf_counter() - start_time)
    elapsed_display = _format_duration(elapsed_seconds)
    if completed_steps <= 0:
        return f"{elapsed_display} elapsed, ETA --"
    remaining_steps = max(total_steps - completed_steps, 0)
    if remaining_steps <= 0:
        return f"{elapsed_display} elapsed, ETA 0:00"
    seconds_per_step = elapsed_seconds / completed_steps
    return f"{elapsed_display} elapsed, ETA {_format_duration(seconds_per_step * remaining_steps)}"


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    minutes, remainder = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{remainder:02d}"
    return f"{minutes:d}:{remainder:02d}"


def _aggregation_with_tabular_grouping(
    aggregation: ProductionAggregationState,
    *,
    grouping_applied: bool,
) -> ProductionAggregationState:
    if not grouping_applied:
        return aggregation
    if TABULAR_GROUP_COLUMN in aggregation.group_fields:
        return aggregation
    return replace(aggregation, group_fields=(TABULAR_GROUP_COLUMN, *aggregation.group_fields))


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
    dashboard_title: str,
    dashboard_subtitle: str,
    cancel_check: CancelCheck | None,
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
        dashboard_title=dashboard_title,
        dashboard_subtitle=dashboard_subtitle,
    )
    _raise_if_cancelled(cancel_check)
    target_path = _html_output_path(output_dashboard_file)
    temp_path = _temporary_output_path(target_path)
    try:
        dashboard = write_production_dashboard(
            manifest,
            temp_path,
            assets_dir=_dashboard_assets_dir(target_path),
        )
        _raise_if_cancelled(cancel_check)
        Path(dashboard["html_dashboard_path"]).replace(target_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    dashboard["html_dashboard_path"] = str(target_path)
    return dashboard


def _export_production_workbook_with_temp(
    *,
    output_workbook_file: str,
    dataframe,
    metric_selection: tuple[ProductionMetricSelection, ...],
    aggregation_result,
    groupstats_result: ProductionGroupstatsResult,
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...],
    separate_parameter_sheets: bool,
    chart_selection: ProductionChartSelection,
    group_fields: tuple[str, ...],
    cancel_check: CancelCheck | None,
) -> IndustrialAnalyticsWorkbookResult:
    target_path = _workbook_output_path(output_workbook_file)
    temp_path = _temporary_output_path(target_path)
    try:
        workbook = export_production_analytics_workbook(
            dataframe=dataframe,
            metric_selection=metric_selection,
            output_file=temp_path,
            aggregation_result=aggregation_result,
            groupstats_result=groupstats_result,
            diagnostics=diagnostics,
            separate_parameter_sheets=separate_parameter_sheets,
            chart_selection=chart_selection,
            group_fields=group_fields,
        )
        _raise_if_cancelled(cancel_check)
        Path(workbook.output_file).replace(target_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return replace(workbook, output_file=str(target_path))


def _export_tabular_workbook_with_temp(
    *,
    output_workbook_file: str,
    dataframe,
    metric_candidates,
    aggregation_result,
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...],
    separate_parameter_sheets: bool,
    chart_selection: ProductionChartSelection,
    group_fields: tuple[str, ...],
    cancel_check: CancelCheck | None,
) -> TabularAnalyticsWorkbookResult:
    target_path = _workbook_output_path(output_workbook_file)
    temp_path = _temporary_output_path(target_path)
    try:
        workbook = export_tabular_analytics_workbook(
            dataframe=dataframe,
            metric_candidates=metric_candidates,
            output_file=temp_path,
            aggregation_result=aggregation_result,
            diagnostics=diagnostics,
            separate_parameter_sheets=separate_parameter_sheets,
            chart_selection=chart_selection,
            group_fields=group_fields,
        )
        _raise_if_cancelled(cancel_check)
        Path(workbook.output_file).replace(target_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return replace(workbook, output_file=str(target_path))


def _raise_if_cancelled(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise AnalyticsCancelled("Analytics generation was canceled.")


def _html_output_path(output_file: str | Path) -> Path:
    path = Path(output_file)
    if path.suffix.lower() != ".html":
        path = path.with_suffix(".html")
    return path


def _workbook_output_path(output_file: str | Path) -> Path:
    path = Path(output_file)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    return path


def _temporary_output_path(target_path: Path) -> Path:
    return target_path.with_name(f".{target_path.stem}.{uuid4().hex}.tmp{target_path.suffix}")


def _dashboard_assets_dir(target_path: Path) -> Path:
    return target_path.with_name(f"{target_path.stem}_assets")


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
    "AnalyticsCancelled",
    "IndustrialAnalyticsRunResult",
    "default_dashboard_path",
    "default_workbook_path",
    "run_production_cache_analytics",
    "run_tabular_file_analytics",
]

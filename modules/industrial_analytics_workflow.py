"""End-to-end analytics workflow for cached production and CSV/Excel sources."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from modules.contracts import IndustrialAnalyticsRequest, validate_industrial_analytics_request
from modules.chart_render_service import deterministic_grouped_downsample_frame
from modules.dashboard_visual_options import dashboard_visual_settings_to_plotly_settings
from modules.industrial_analytics_dashboard import (
    DASHBOARD_RAW_POINT_LIMIT,
    build_production_dashboard_manifest,
    write_production_dashboard,
)
from modules.industrial_analytics_service import (
    ProductionAnalyticsDiagnostic,
    ProductionGroupstatsCancelled,
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
    TabularAnalyticsLoadResult,
    TabularAnalyticsWorkbookResult,
    TabularColumnFilter,
    apply_tabular_grouping,
    export_tabular_analytics_workbook,
    load_tabular_analytics_file,
    materialize_tabular_dataframe,
)

AnalyticsSourceKind = Literal["production_cache", "tabular_file"]
CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[str], None]
TABULAR_FAST_DASHBOARD_ROW_LIMIT = DASHBOARD_RAW_POINT_LIMIT


class AnalyticsCancelled(RuntimeError):
    """Raised when an analytics run is canceled before output finalization."""


@dataclass(frozen=True)
class IndustrialAnalyticsRunResult:
    """End-to-end analytics run result."""

    source_kind: AnalyticsSourceKind
    html_dashboard_path: str
    html_dashboard_assets_path: str
    html_dashboard_chart_count: int
    html_dashboard_interactive_chart_count: int = 0
    html_dashboard_plotly_spec_count: int = 0
    html_dashboard_embedded_plotly_spec_count: int = 0
    html_dashboard_plotly_serialized_json_bytes: int = 0
    html_dashboard_embedded_plotly_serialized_json_bytes: int = 0
    html_dashboard_html_bytes: int = 0
    html_dashboard_plotly_budget_status: str = "within_budget"
    html_dashboard_plotly_budget_reason: str = ""
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
    dashboard_visual_settings: dict | None = None,
) -> IndustrialAnalyticsRunResult:
    """Run production analytics from the local Oznak cache."""

    request = validate_industrial_analytics_request(
        IndustrialAnalyticsRequest(
            source_kind="production_cache",
            db_file=db_file,
            output_dashboard_file=output_dashboard_file,
            output_workbook_file=output_workbook_file or "",
            metric_selection=tuple(metric_selection or ()),
            filter_state=filter_state,
            aggregation_state=aggregation_state,
            cohort_state=cohort_state,
            chart_selection=chart_selection,
            separate_parameter_sheets=separate_parameter_sheets,
            dashboard_visual_settings=dashboard_visual_settings,
        ),
        require_runnable=True,
    )

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
    metrics = request.metric_selection or tuple(
        candidate.to_selection()
        for candidate in discover_production_metric_candidates(request.db_file)[:5]
    )
    aggregation = request.aggregation_state
    charts = request.chart_selection
    cohort = request.cohort_state

    loaded = load_production_analytics_frame(
        request.db_file,
        filter_state=request.filter_state,
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
        cancel_check=cancel_check,
        progress_callback=progress_callback,
        start_time=start_time,
        step=4,
        total_steps=total_steps,
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
        output_dashboard_file=request.output_dashboard_file,
        dashboard_title="Production Analytics",
        dashboard_subtitle="Cached production data dashboard generated by Metroliza.",
        cancel_check=cancel_check,
        plotly_visual_settings=dashboard_visual_settings_to_plotly_settings(
            request.dashboard_visual_settings
        ),
        dashboard_visual_settings=request.dashboard_visual_settings,
    )
    workbook = None
    if request.output_workbook_file:
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
            output_workbook_file=request.output_workbook_file,
            dataframe=cohorted.dataframe,
            metric_selection=metrics,
            aggregation_result=aggregated,
            groupstats_result=groupstats,
            diagnostics=diagnostics,
            separate_parameter_sheets=request.separate_parameter_sheets,
            chart_selection=charts,
            group_fields=aggregation.group_fields,
            cancel_check=cancel_check,
        )
    _emit_complete(
        progress_callback,
        start_time=start_time,
        includes_workbook=bool(request.output_workbook_file),
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
    tabular_load_result: TabularAnalyticsLoadResult | None = None,
    metric_selection: tuple[ProductionMetricSelection, ...] = (),
    sheet_name: str | int | None = None,
    timestamp_column: str | None = None,
    reference_column: str | None = None,
    tabular_filter_columns: tuple[str, ...] | list[str] | None = None,
    tabular_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
    tabular_column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None = None,
    dashboard_detail_mode: str = "fast",
    grouping_df=None,
    aggregation_state: ProductionAggregationState | None = None,
    cohort_state: ReferenceCohortState | None = None,
    chart_selection: ProductionChartSelection | None = None,
    output_workbook_file: str | None = None,
    separate_parameter_sheets: bool = True,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    dashboard_visual_settings: dict | None = None,
) -> IndustrialAnalyticsRunResult:
    """Run analytics from a CSV or Excel file."""

    request = validate_industrial_analytics_request(
        IndustrialAnalyticsRequest(
            source_kind="tabular_file",
            input_file=input_file,
            output_dashboard_file=output_dashboard_file,
            output_workbook_file=output_workbook_file or "",
            metric_selection=tuple(metric_selection or ()),
            aggregation_state=aggregation_state,
            cohort_state=cohort_state,
            chart_selection=chart_selection,
            separate_parameter_sheets=separate_parameter_sheets,
            sheet_name=sheet_name,
            timestamp_column=timestamp_column,
            reference_column=reference_column,
            tabular_load_result=tabular_load_result,
            tabular_filter_columns=tabular_filter_columns or (),
            tabular_filter_keys=tabular_filter_keys or (),
            tabular_column_filters=tabular_column_filters or (),
            dashboard_detail_mode=dashboard_detail_mode,
            grouping_df=grouping_df,
            dashboard_visual_settings=dashboard_visual_settings,
        ),
        require_runnable=True,
    )

    start_time = time.perf_counter()
    total_steps = 6 if output_workbook_file else 5
    _emit_progress(
        progress_callback,
        "Loading CSV/Excel data...",
        "Checking loaded rows and metric columns"
        if tabular_load_result is not None
        else "Reading rows and detecting metric columns",
        step=1,
        total_steps=total_steps,
        start_time=start_time,
    )
    _raise_if_cancelled(cancel_check)
    if request.tabular_load_result is not None:
        _validate_tabular_load_snapshot(
            request.tabular_load_result,
            input_file=request.input_file,
            sheet_name=request.sheet_name,
            timestamp_column=request.timestamp_column,
            reference_column=request.reference_column,
        )
        loaded = request.tabular_load_result
    else:
        loaded = load_tabular_analytics_file(
            request.input_file,
            sheet_name=request.sheet_name,
            timestamp_column=request.timestamp_column,
            reference_column=request.reference_column,
        )
    metrics = request.metric_selection or tuple(
        candidate.to_selection() for candidate in loaded.metric_candidates[:5]
    )
    required_columns = (
        None
        if request.output_workbook_file
        else _tabular_required_columns_for_analytics(
            metrics=metrics,
            aggregation_state=request.aggregation_state,
            filter_columns=request.tabular_filter_columns,
            column_filters=request.tabular_column_filters,
            grouping_df=request.grouping_df,
        )
    )
    filtered = materialize_tabular_dataframe(
        loaded,
        filter_columns=request.tabular_filter_columns,
        selected_filter_keys=request.tabular_filter_keys,
        column_filters=request.tabular_column_filters,
        required_columns=required_columns,
    )
    projection_diagnostic = _tabular_projection_diagnostic(
        loaded=loaded,
        required_columns=required_columns,
    )
    grouped = apply_tabular_grouping(filtered.dataframe, request.grouping_df)
    _emit_progress(
        progress_callback,
        "Applying groups and references...",
        "Assigning manual groups and comparison cohorts",
        step=2,
        total_steps=total_steps,
        start_time=start_time,
    )
    _raise_if_cancelled(cancel_check)
    aggregation = _aggregation_with_tabular_grouping(
        request.aggregation_state,
        grouping_applied=grouped.applied,
    )
    charts = request.chart_selection
    cohort = request.cohort_state
    if charts.groupstats and not _tabular_groupstats_can_form_groups(
        grouped_group_count=grouped.group_count,
        aggregation=aggregation,
        cohort=cohort,
    ):
        charts = replace(charts, groupstats=False)
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
        cancel_check=cancel_check,
        progress_callback=progress_callback,
        start_time=start_time,
        step=4,
        total_steps=total_steps,
    )
    _raise_if_cancelled(cancel_check)
    diagnostics = (
        loaded.diagnostics
        + projection_diagnostic
        + filtered.diagnostics
        + grouped.diagnostics
        + cohorted.diagnostics
        + aggregated.diagnostics
        + groupstats.diagnostics
    )
    dashboard_frame, dashboard_diagnostics = _tabular_dashboard_frame_for_detail_mode(
        cohorted.dataframe,
        detail_mode=request.dashboard_detail_mode,
    )
    diagnostics = diagnostics + dashboard_diagnostics
    _emit_progress(
        progress_callback,
        "Writing dashboard...",
        (
            "Rendering full-detail HTML dashboard and chart payloads"
            if request.dashboard_detail_mode == "full"
            else "Rendering fast HTML dashboard and bounded chart payloads"
        ),
        step=5,
        total_steps=total_steps,
        start_time=start_time,
    )
    dashboard = _write_dashboard(
        frame=dashboard_frame,
        metrics=metrics,
        aggregation=aggregation,
        aggregated=aggregated,
        groupstats=groupstats,
        charts=charts,
        cohort=cohort,
        diagnostics=diagnostics,
        output_dashboard_file=request.output_dashboard_file,
        dashboard_title="CSV / Excel Analytics",
        dashboard_subtitle="CSV/Excel data dashboard generated by Metroliza.",
        cancel_check=cancel_check,
        plotly_visual_settings=dashboard_visual_settings_to_plotly_settings(
            request.dashboard_visual_settings
        ),
        dashboard_visual_settings=request.dashboard_visual_settings,
    )
    workbook = None
    if request.output_workbook_file:
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
            output_workbook_file=request.output_workbook_file,
            dataframe=cohorted.dataframe,
            metric_candidates=selected_candidates,
            aggregation_result=aggregated,
            groupstats_result=groupstats,
            diagnostics=diagnostics,
            separate_parameter_sheets=request.separate_parameter_sheets,
            chart_selection=charts,
            group_fields=aggregation.group_fields,
            cancel_check=cancel_check,
        )
    _emit_complete(
        progress_callback,
        start_time=start_time,
        includes_workbook=bool(request.output_workbook_file),
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


def _tabular_dashboard_frame_for_detail_mode(
    dataframe,
    *,
    detail_mode: str,
) -> tuple[object, tuple[ProductionAnalyticsDiagnostic, ...]]:
    if str(detail_mode or "").strip().casefold() != "fast":
        return dataframe, ()
    row_count = int(len(getattr(dataframe, "index", ())))
    limit = int(TABULAR_FAST_DASHBOARD_ROW_LIMIT)
    if row_count <= limit:
        return dataframe, ()
    if TABULAR_GROUP_COLUMN in dataframe.columns:
        sampled = deterministic_grouped_downsample_frame(
            dataframe,
            limit,
            grouping_key=TABULAR_GROUP_COLUMN,
            value_column=None,
        )
    else:
        sampled = dataframe.sample(n=limit, random_state=20260518).sort_index(kind="stable")
    sampled = sampled.reset_index(drop=True)
    diagnostic = ProductionAnalyticsDiagnostic(
        severity="info",
        code="tabular_dashboard_fast_sample",
        message=(
            f"Fast CSV/Excel dashboard detail rendered {len(sampled.index):,} sampled rows "
            f"from {row_count:,}; aggregate tables, groupstats, and workbook output use all rows."
        ),
        context={
            "detail_mode": "fast",
            "input_row_count": row_count,
            "dashboard_row_count": int(len(sampled.index)),
        },
    )
    return sampled, (diagnostic,)


def _tabular_groupstats_can_form_groups(
    *,
    grouped_group_count: int,
    aggregation: ProductionAggregationState,
    cohort: ReferenceCohortState,
) -> bool:
    """Return whether tabular groupstats has a configured grouping source."""

    if int(grouped_group_count or 0) >= 2:
        return True
    if aggregation.time_bucket != "none" or bool(aggregation.group_fields):
        return True
    return bool(cohort.is_applied and cohort.mode in {"compare_rest", "group_selected"})


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


def _tabular_required_columns_for_analytics(
    *,
    metrics: tuple[ProductionMetricSelection, ...],
    aggregation_state: ProductionAggregationState,
    filter_columns: tuple[str, ...] | list[str] | None,
    column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None,
    grouping_df,
) -> tuple[str, ...]:
    required: list[str] = [
        "source_row_number",
        "source_file",
        "source_sheet",
        "process_datetime",
        "reference",
    ]
    required.extend(metric.field_name for metric in metrics)
    required.extend(aggregation_state.group_fields)
    required.extend(str(column) for column in (filter_columns or ()))
    for column_filter in column_filters or ():
        if isinstance(column_filter, TabularColumnFilter):
            required.append(column_filter.column)
    if grouping_df is not None:
        required.append("source_row_number")
    return tuple(dict.fromkeys(column for column in required if str(column or "").strip()))


def _tabular_projection_diagnostic(
    *,
    loaded: TabularAnalyticsLoadResult,
    required_columns: tuple[str, ...] | None,
) -> tuple[ProductionAnalyticsDiagnostic, ...]:
    if required_columns is None or loaded.sqlite_store is None:
        return ()
    available_count = int(len(loaded.sqlite_store.columns))
    projected_count = int(len(required_columns))
    if projected_count >= available_count:
        return ()
    return (
        ProductionAnalyticsDiagnostic(
            severity="info",
            code="tabular_sqlite_column_pruning",
            message=(
                "CSV/Excel analytics projected a reduced SQLite column set before "
                "materialization to keep large-data runs responsive."
            ),
            context={
                "available_column_count": available_count,
                "projected_column_count": projected_count,
                "projected_columns": list(required_columns),
            },
        ),
    )


def _validate_tabular_load_snapshot(
    loaded: TabularAnalyticsLoadResult,
    *,
    input_file: str,
    sheet_name: str | int | None,
    timestamp_column: str | None,
    reference_column: str | None,
) -> None:
    if loaded.source_snapshots:
        _validate_tabular_source_snapshots(loaded.source_snapshots)
        if len(loaded.source_snapshots) == 1:
            source_path = Path(input_file)
            loaded_path = Path(loaded.source_snapshots[0].path)
            if loaded_path.resolve() != source_path.resolve():
                raise ValueError("Reload CSV/Excel data before export: selected source file changed.")
        if sheet_name is not None and loaded.sheet_name is not None and str(sheet_name) != loaded.sheet_name:
            raise ValueError("Reload CSV/Excel data before export: selected Excel sheet changed.")
        if timestamp_column is not None and loaded.timestamp_column != str(timestamp_column):
            raise ValueError("Reload CSV/Excel data before export: selected time column changed.")
        if reference_column is not None and loaded.reference_column != str(reference_column):
            raise ValueError("Reload CSV/Excel data before export: selected part/id column changed.")
        return

    source_path = Path(input_file)
    loaded_path = Path(loaded.source_file) if loaded.source_file else source_path
    try:
        current_stat = source_path.stat()
    except OSError as exc:
        raise ValueError(f"Reload CSV/Excel data before export: source file is unavailable ({exc}).") from exc
    if loaded_path.resolve() != source_path.resolve():
        raise ValueError("Reload CSV/Excel data before export: selected source file changed.")
    if loaded.source_size is not None and int(current_stat.st_size) != int(loaded.source_size):
        raise ValueError("Reload CSV/Excel data before export: source file size changed.")
    if loaded.source_mtime_ns is not None and int(current_stat.st_mtime_ns) != int(loaded.source_mtime_ns):
        raise ValueError("Reload CSV/Excel data before export: source file timestamp changed.")
    if sheet_name is not None and loaded.sheet_name is not None and str(sheet_name) != loaded.sheet_name:
        raise ValueError("Reload CSV/Excel data before export: selected Excel sheet changed.")
    if timestamp_column is not None and loaded.timestamp_column != str(timestamp_column):
        raise ValueError("Reload CSV/Excel data before export: selected time column changed.")
    if reference_column is not None and loaded.reference_column != str(reference_column):
        raise ValueError("Reload CSV/Excel data before export: selected part/id column changed.")


def _validate_tabular_source_snapshots(snapshots) -> None:
    for snapshot in snapshots:
        source_path = Path(snapshot.path)
        try:
            current_stat = source_path.stat()
        except OSError as exc:
            raise ValueError(
                f"Reload CSV/Excel data before export: source file is unavailable ({exc})."
            ) from exc
        if int(current_stat.st_size) != int(snapshot.size):
            raise ValueError("Reload CSV/Excel data before export: source file size changed.")
        if int(current_stat.st_mtime_ns) != int(snapshot.mtime_ns):
            raise ValueError("Reload CSV/Excel data before export: source file timestamp changed.")


def _analyze_groupstats_if_enabled(
    dataframe,
    metrics: tuple[ProductionMetricSelection, ...],
    *,
    aggregation_state: ProductionAggregationState,
    cohort_state: ReferenceCohortState,
    chart_selection: ProductionChartSelection,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    start_time: float | None = None,
    step: int = 4,
    total_steps: int = 5,
) -> ProductionGroupstatsResult:
    if not chart_selection.groupstats:
        return ProductionGroupstatsResult()

    def emit_metric_progress(message: str) -> None:
        _emit_progress(
            progress_callback,
            "Running statistical analysis...",
            str(message or "Analyzing selected metrics"),
            step=step,
            total_steps=total_steps,
            start_time=start_time if start_time is not None else time.perf_counter(),
        )

    try:
        return analyze_production_groupstats(
            dataframe,
            metrics,
            aggregation_state=aggregation_state,
            cohort_state=cohort_state,
            progress_callback=emit_metric_progress,
            cancel_check=cancel_check,
        )
    except ProductionGroupstatsCancelled as exc:
        raise AnalyticsCancelled("Analytics run was canceled.") from exc


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
    plotly_visual_settings: dict[str, object] | None = None,
    dashboard_visual_settings: dict[str, object] | None = None,
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
        plotly_visual_settings=plotly_visual_settings,
    )
    _raise_if_cancelled(cancel_check)
    target_path = _html_output_path(output_dashboard_file)
    temp_path = _temporary_output_path(target_path)
    try:
        dashboard = write_production_dashboard(
            manifest,
            temp_path,
            assets_dir=_dashboard_assets_dir(target_path),
            dashboard_visual_settings=dashboard_visual_settings,
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
    groupstats_result: ProductionGroupstatsResult,
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
    budget = (
        dashboard.get("html_dashboard_plotly_budget")
        if isinstance(dashboard.get("html_dashboard_plotly_budget"), dict)
        else {}
    )
    return IndustrialAnalyticsRunResult(
        source_kind=source_kind,
        html_dashboard_path=str(dashboard.get("html_dashboard_path") or ""),
        html_dashboard_assets_path=str(dashboard.get("html_dashboard_assets_path") or ""),
        html_dashboard_chart_count=int(dashboard.get("html_dashboard_chart_count") or 0),
        html_dashboard_interactive_chart_count=int(
            dashboard.get("html_dashboard_interactive_chart_count") or 0
        ),
        html_dashboard_plotly_spec_count=int(dashboard.get("html_dashboard_plotly_spec_count") or 0),
        html_dashboard_embedded_plotly_spec_count=int(
            dashboard.get("html_dashboard_embedded_plotly_spec_count") or 0
        ),
        html_dashboard_plotly_serialized_json_bytes=int(
            dashboard.get("html_dashboard_plotly_serialized_json_bytes") or 0
        ),
        html_dashboard_embedded_plotly_serialized_json_bytes=int(
            dashboard.get("html_dashboard_embedded_plotly_serialized_json_bytes") or 0
        ),
        html_dashboard_html_bytes=int(dashboard.get("html_dashboard_html_bytes") or 0),
        html_dashboard_plotly_budget_status=str(budget.get("status") or "within_budget"),
        html_dashboard_plotly_budget_reason=str(budget.get("reason") or ""),
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
    return str(_unique_default_output_path(path.with_name(f"{stem}_{suffix}.html")))


def default_workbook_path(base_file: str | Path, *, suffix: str = "analytics") -> str:
    path = Path(base_file)
    stem = path.stem or "analytics"
    return str(_unique_default_output_path(path.with_name(f"{stem}_{suffix}.xlsx")))


def _unique_default_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = path.suffix
    stem = path.stem
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


__all__ = [
    "AnalyticsCancelled",
    "IndustrialAnalyticsRunResult",
    "default_dashboard_path",
    "default_workbook_path",
    "run_production_cache_analytics",
    "run_tabular_file_analytics",
]

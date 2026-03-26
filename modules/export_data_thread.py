"""Orchestrate threaded export workflows, rendering helpers, and Excel writing operations.

This module coordinates data retrieval (`modules.export_query_service`), grouping
(`modules.export_grouping_utils`), chart and summary planning
(`modules.export_chart_writer`, `modules.export_summary_utils`,
`modules.export_summary_sheet_planner`), and workbook output through
`modules.export_backends`.
"""

import logging
import inspect
import re
import sqlite3
import textwrap
import statistics
from io import BytesIO
import os
import time
from concurrent.futures import ProcessPoolExecutor
import matplotlib
import pandas as pd
import numpy as np

matplotlib.use('Agg')

import importlib.util

import matplotlib.pyplot as plt
import matplotlib.transforms as mtransforms
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal

from modules.contracts import ExportRequest, validate_export_request
import modules.custom_logger as custom_logger
from modules.db import execute_select_with_columns, read_sql_dataframe, sqlite_connection_scope
from modules.excel_sheet_utils import unique_sheet_name
from modules.export_backends import ExcelExportBackend
from modules.google_drive_export import (
    GoogleDriveAuthError,
    GoogleDriveCanceledError,
    GoogleDriveExportError,
    upload_and_convert_workbook,
)
from modules.export_google_result_utils import (
    build_google_conversion_metadata,
    build_google_fallback_metadata,
    build_google_stage_message,
)
from modules.progress_status import build_three_line_status
from modules.log_context import (
    build_google_conversion_log_extra,
    get_operation_logger,
)
from modules.export_logging_service import (
    build_export_context as _build_export_context_payload,
    log_export_stage as _log_export_stage_message,
    log_google_issue as _log_google_issue_message,
)
from modules.export_summary_utils import (
    apply_shared_x_axis_label_strategy as _apply_shared_x_axis_label_strategy,
    prepare_categorical_x_axis as _prepare_categorical_x_axis,
    resolve_extended_chart_fig_width as _resolve_extended_chart_fig_width,
    build_histogram_density_curve_payload as _build_histogram_density_curve_payload,
    build_sparse_unique_labels as _build_sparse_unique_labels,
    build_summary_panel_labels as _build_summary_panel_labels,
    build_trend_plot_payload as _build_trend_plot_payload,
    resolve_histogram_bin_count,
    normalize_plot_axis_values as _normalize_plot_axis_values,
    resolve_nominal_and_limits,
    render_spec_reference_lines as _render_spec_reference_lines,
    render_tolerance_band as _render_tolerance_band,
    build_tolerance_reference_legend_handles as _build_tolerance_reference_legend_handles,
)
from modules.export_summary_sheet_planner import (
    build_histogram_annotation_specs as _build_histogram_annotation_specs,
    compute_histogram_annotation_rows as _compute_histogram_annotation_rows,
    build_summary_image_anchor_plan as _build_summary_image_anchor_plan,
    build_summary_sheet_position_plan as _build_summary_sheet_position_plan,
)
from modules.export_chart_writer import (
    build_measurement_chart_format_policy as _build_measurement_chart_format_policy,
    build_measurement_chart_range_specs as _build_measurement_chart_range_specs,
    build_measurement_chart_series_specs as _build_measurement_chart_series_specs,
    build_sheet_series_range as _build_sheet_series_range,
    build_horizontal_limit_line_specs as _build_horizontal_limit_line_specs,
    insert_measurement_chart,
)
from modules.export_query_service import (
    build_export_dataframe as _build_export_dataframe,
    build_measurement_export_dataframe as _build_measurement_export_dataframe,
    execute_export_query as _execute_export_query,
    fetch_partition_header_counts,
    fetch_partition_values,
    fetch_sql_measurement_summary,
    fetch_sql_measurement_summaries,
    load_measurement_export_partition_dataframe,
)
from modules.export_grouping_utils import (
    add_group_key as _add_group_key,
    apply_group_assignments as _apply_group_assignments,
    keys_have_usable_values as _keys_have_usable_values,
    prepare_grouping_dataframe as _prepare_grouping_dataframe,
    resolve_group_merge_keys as _resolve_group_merge_keys,
)
from modules.group_analysis_service import build_group_analysis_payload
from modules.group_analysis_writer import (
    write_group_analysis_diagnostics_sheet as _write_internal_group_analysis_diagnostics_sheet,
    write_group_analysis_sheet,
)
from modules.summary_plot_palette import (
    SUMMARY_PLOT_PALETTE,
    EMPHASIS_TABLE_ROWS,
    STATUS_BORDER_STYLE_BY_PALETTE,
    STATUS_ICON_PREFIX_BY_PALETTE,
)
from modules.stats_number_formatting import (
    format_probability_percent,
)


from modules.export_chart_payload_helpers import (
    build_histogram_table_data as _build_histogram_table_data,
    build_histogram_table_render_data as _build_histogram_table_render_data,
    compute_scaled_y_limits as _compute_scaled_y_limits,
    resolve_summary_annotation_strategy as _resolve_summary_annotation_strategy,
)
from modules.export_workbook_planning_helpers import (
    compute_histogram_font_sizes as _compute_histogram_font_sizes,
    compute_histogram_table_layout as _compute_histogram_table_layout,
    compute_histogram_three_region_layout as _compute_histogram_three_region_layout,
)
from modules.export_histogram_layout import (
    assert_non_overlapping_rectangles as _assert_non_overlapping_rectangles,
    build_table_row_heights as _build_table_row_heights,
    compute_row_line_count as _compute_row_line_count,
    compute_histogram_panel_layout as _compute_histogram_panel_layout,
    compute_histogram_plot_with_right_info_layout as _compute_histogram_plot_with_right_info_layout,
    resolve_required_histogram_figure_height_for_complete_right_tables as _resolve_required_histogram_figure_height_for_complete_right_tables,
    resolve_histogram_dashboard_row_metrics as _resolve_histogram_dashboard_row_metrics,
    resolve_inner_table_rect as _resolve_inner_table_rect,
    resolve_table_row_line_count as _resolve_table_row_line_count,
)
from modules.export_summary_composition_service import (
    build_summary_table_composition as _build_summary_table_composition,
    build_summary_panel_subtitle as _build_summary_panel_subtitle,
    classify_capability_status as _classify_capability_status,
    classify_capability_value as _classify_capability_value,
    classify_nok_severity as _classify_nok_severity,
    classify_normality_status as _classify_normality_status,
)
from modules.export_summary_sheet_compute import (
    append_group_sample_counts as _append_group_sample_counts_compute,
    build_summary_worksheet_plan as _build_summary_worksheet_plan_compute,
    compute_group_sample_counts as _compute_group_sample_counts_compute,
    finalize_histogram_summary_payload as _finalize_histogram_summary_payload_compute,
    normalize_summary_group_frame as _normalize_summary_group_frame_compute,
    prepare_summary_chart_payloads as _prepare_summary_chart_payloads_compute,
    resolve_sampling_context as _resolve_sampling_context_compute,
    retrieve_summary_statistics as _retrieve_summary_statistics_compute,
)
from modules.export_group_analysis_annotation_service import (
    build_violin_group_annotation_payload as _build_violin_group_annotation_payload,
)
from modules.export_row_aggregation_utils import (
    all_measurements_within_limits as _all_measurements_within_limits,
    build_violin_group_stats_rows as _build_violin_group_stats_rows,
)
from modules.export_sheet_writer import (
    build_measurement_block_plan as _build_measurement_block_plan,
    build_measurement_header_block_plan as _build_measurement_header_block_plan,
    build_measurement_stat_formulas as _build_measurement_stat_formulas,
    build_measurement_stat_row_specs as _build_measurement_stat_row_specs,
    build_measurement_write_bundle as _build_measurement_write_bundle,
    build_measurement_write_bundle_cached as _build_measurement_write_bundle_cached,
    build_spec_limit_anchor_rows as _build_spec_limit_anchor_rows,
    create_measurement_formats,
    write_measurement_block,
)
from modules.stats_utils import is_one_sided_geometric_tolerance
# Canonical violin payload builder lives in `modules/chart_render_service.py`.
from modules.chart_render_service import (
    BoundedWorkerPool,
    build_violin_payload_vectorized,
    resolve_chart_sampling_policy,
    deterministic_downsample_frame,
)
from modules.chart_renderer import (
    build_chart_renderer,
    build_distribution_native_payload,
    build_histogram_native_payload,
    native_histogram_backend_available,
    resolve_chart_renderer_backend,
)
from modules.backend_diagnostics import (
    build_backend_diagnostic_summary,
    format_backend_diagnostic_lines,
)
from modules.distribution_fit_service import fit_measurement_distribution

_HAS_SEABORN = importlib.util.find_spec('seaborn') is not None
if _HAS_SEABORN:
    import seaborn as sns


logger = get_operation_logger(logging.getLogger(__name__), "export_data")
logging.getLogger('matplotlib').setLevel(logging.WARNING)
logging.getLogger('matplotlib.category').setLevel(logging.ERROR)

# Backward-compatible module-level alias used by tests/patch points in this module.
# Export histogram selection now uses histogram-specific capability semantics.
native_chart_backend_available = native_histogram_backend_available


_INTERNAL_GROUP_ANALYSIS_DIAGNOSTICS_ENV_VAR = 'METROLIZA_EXPORT_GROUP_ANALYSIS_DIAGNOSTICS'


def _internal_group_analysis_diagnostics_enabled():
    """Return True when internal-only Group Analysis diagnostics sheet emission is enabled."""
    return os.getenv(_INTERNAL_GROUP_ANALYSIS_DIAGNOSTICS_ENV_VAR, '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _uses_symbol_font_fallback(text):
    """Return True when text contains symbols often missing from Arial on Windows."""

    return any(icon in str(text) for icon in ('✓', '×'))


_HISTOGRAM_X_MARGIN_RATIO = 0.10

_SELECTED_MODEL_CURVE_STYLE_BY_QUALITY = {
    'strong': {'alpha': 0.80, 'linewidth': 1.72},
    'medium': {'alpha': 0.68, 'linewidth': 1.55},
    'weak': {'alpha': 0.48, 'linewidth': 1.30},
    'unreliable': {'alpha': 0.28, 'linewidth': 1.05},
}


_DISTRIBUTION_FIT_COMPACT_LABELS = {
    'Best fit': 'Model',
    'Selected model': 'Model',
    'Estimated P(X < LSL)': 'P(<LSL)',
    'Estimated P(X > USL)': 'P(>USL)',
    'Estimated NOK %': 'Est. NOK %',
    'Estimated NOK (PPM)': 'Est. PPM',
    'NOK % (obs vs est)': 'Obs vs Est NOK %',
    'NOK % Δ (abs/rel)': 'NOK % Δ',
    'Model fit quality': 'Fit quality',
}


def _compact_distribution_fit_label(label):
    """Return compact distribution-fit labels used in tables and notes."""
    normalized_label = str(label or '').strip()
    return _DISTRIBUTION_FIT_COMPACT_LABELS.get(normalized_label, normalized_label)


def resolve_selected_model_curve_style(distribution_fit_result):
    """Resolve fitted-model curve style from fit-quality tiers.

    Tiers intentionally maintain histogram visual hierarchy:
    - strong: dominant model curve style
    - weak: softened (slightly lighter/thinner)
    - unreliable: clearly downgraded dominance
    """

    fit_quality = (distribution_fit_result or {}).get('fit_quality') or {}
    quality_label = str(fit_quality.get('label') or '').strip().lower()
    if quality_label not in _SELECTED_MODEL_CURVE_STYLE_BY_QUALITY:
        quality_label = 'strong'
    style = _SELECTED_MODEL_CURVE_STYLE_BY_QUALITY[quality_label]
    return {'alpha': float(style['alpha']), 'linewidth': float(style['linewidth'])}


# Query wrappers keep the thread-facing import path stable while delegating
# implementation to `export_query_service`, allowing tests to patch this module
# without importing lower-level services directly.
def build_export_dataframe(data, column_names):
    """Build an export DataFrame from raw query rows and column metadata.

    Args:
        data (Sequence[Sequence[object]]): Raw database rows.
        column_names (Sequence[str]): Column labels aligned with each row value.

    Returns:
        pandas.DataFrame: Normalized frame ready for export writing.

    Side Effects:
        Delegates implementation to `modules.export_query_service`.
    """

    return _build_export_dataframe(data, column_names)


def execute_export_query(db_file, export_query, select_reader=execute_select_with_columns):
    """Execute an export SQL query and return rows with ordered column names.

    Args:
        db_file (str): SQLite database file path.
        export_query (str): SQL query string to execute.
        select_reader (Callable): Query executor with the `execute_select_with_columns`
            contract.

    Returns:
        tuple[list[tuple], list[str]]: Query rows and associated column names.

    Raises:
        sqlite3.Error: Propagated when query execution fails.
    """

    return _execute_export_query(db_file, export_query, select_reader=select_reader)


def build_measurement_export_dataframe(df):
    """Normalize measurement export rows into a plotting-friendly DataFrame.

    Args:
        df (pandas.DataFrame): Raw measurement export frame.

    Returns:
        pandas.DataFrame: Frame with standardized columns used by export rendering.
    """

    return _build_measurement_export_dataframe(df)


# Chart wrappers preserve existing call signatures used throughout this file and
# by tests, while centralizing chart-spec logic in `export_chart_writer`.
def build_sheet_series_range(sheet_name, first_row, last_row, column_index):
    """Build an Excel chart range string for a worksheet column slice.

    Args:
        sheet_name (str): Worksheet name.
        first_row (int): First 1-based row index in the range.
        last_row (int): Last 1-based row index in the range.
        column_index (int): Zero-based worksheet column index.

    Returns:
        str: A fully-qualified A1-style sheet range string.
    """

    return _build_sheet_series_range(sheet_name, first_row, last_row, column_index)


def build_spec_limit_anchor_rows(usl, lsl):
    """Resolve optional USL/LSL anchor rows used for chart limit lines.

    Args:
        usl (float | None): Upper specification limit.
        lsl (float | None): Lower specification limit.

    Returns:
        dict[str, int | None]: Anchor row indexes keyed by limit type.
    """

    return _build_spec_limit_anchor_rows(usl, lsl)


def build_measurement_stat_formulas(summary_col, stats_col, data_range_y, nom_cell, usl_cell, lsl_cell, nom_value, lsl_value):
    """Create Excel formula strings for the measurement statistics block.

    Args:
        summary_col (str): Column letter for summary labels.
        stats_col (str): Column letter for statistic formulas.
        data_range_y (str): A1-style range containing measurement values.
        nom_cell (str): Nominal value cell reference.
        usl_cell (str): Upper spec limit cell reference.
        lsl_cell (str): Lower spec limit cell reference.
        nom_value (float | None): Nominal numeric value.
        lsl_value (float | None): Lower spec limit numeric value.

    Returns:
        dict[str, str]: Statistic-keyed Excel formulas for worksheet writing.
    """

    return _build_measurement_stat_formulas(summary_col, stats_col, data_range_y, nom_cell, usl_cell, lsl_cell, nom_value, lsl_value)


def build_measurement_stat_row_specs(stat_formulas):
    """Convert stat formulas into ordered row specs for worksheet output.

    Args:
        stat_formulas (dict[str, str]): Formula map from
            `build_measurement_stat_formulas`.

    Returns:
        list[dict[str, object]]: Row descriptors consumed by sheet writers.
    """

    return _build_measurement_stat_row_specs(stat_formulas)


def build_measurement_block_plan(*, base_col, sample_size):
    """Build the layout plan for one horizontal measurement export block."""

    return _build_measurement_block_plan(base_col=base_col, sample_size=sample_size)


def build_measurement_header_block_plan(header_group, base_col):
    """Build worksheet header placement details for a measurement block."""

    return _build_measurement_header_block_plan(header_group, base_col)


def build_measurement_chart_range_specs(*, sheet_name, first_data_row, last_data_row, x_column, y_column):
    """Build data range specs used to insert one measurement chart."""

    return _build_measurement_chart_range_specs(
        sheet_name=sheet_name,
        first_data_row=first_data_row,
        last_data_row=last_data_row,
        x_column=x_column,
        y_column=y_column,
    )


def build_measurement_chart_series_specs(*, header, sheet_name, first_data_row, last_data_row, x_column, y_column):
    """Build chart series definitions for a measurement header group."""

    return _build_measurement_chart_series_specs(
        header=header,
        sheet_name=sheet_name,
        first_data_row=first_data_row,
        last_data_row=last_data_row,
        x_column=x_column,
        y_column=y_column,
    )


def build_measurement_chart_format_policy(header):
    """Resolve chart formatting options for a measurement header."""

    return _build_measurement_chart_format_policy(header)


def build_horizontal_limit_line_specs(usl, lsl, **style):
    """Build chart series specs for optional horizontal spec-limit lines."""

    return _build_horizontal_limit_line_specs(usl, lsl, **style)


# Worksheet-plan/write wrappers maintain a thin compatibility layer around
# `export_sheet_writer` so callers keep one orchestration module API surface.
def build_measurement_write_bundle(header, header_group, base_col):
    """Assemble the worksheet write bundle for one measurement group."""

    return _build_measurement_write_bundle(header, header_group, base_col)


def build_measurement_write_bundle_cached(header, header_group, base_col, cache=None):
    """Return a cached measurement write bundle when available."""

    return _build_measurement_write_bundle_cached(header, header_group, base_col, cache=cache)


def run_export_steps(steps, should_cancel):
    """Execute export callables sequentially until completion or cancellation.

    Args:
        steps (Sequence[Callable[[], None]]): Ordered export actions.
        should_cancel (Callable[[], bool]): Cancellation predicate.

    Ordering Assumptions:
        `steps` must already be topologically ordered. This helper intentionally
        does not reorder or retry work because later stages can depend on prior
        worksheet mutations.

    Returns:
        bool: `True` when all steps run without a cancellation request.
    """

    for step in steps:
        if should_cancel():
            return False
        step()
    return not should_cancel()


def all_measurements_within_limits(measurements, lower_limit, upper_limit):
    """Check whether every measurement value falls between inclusive limits."""

    return _all_measurements_within_limits(measurements, lower_limit, upper_limit)


def build_sparse_unique_labels(labels):
    """Collapse repeated labels while preserving first occurrences for display."""

    return _build_sparse_unique_labels(labels)


def build_summary_panel_labels(labels, *, grouping_active=False):
    """Build summary-panel labels and suppress duplicates when grouping is active."""

    return _build_summary_panel_labels(labels, grouping_active=grouping_active)


def build_trend_plot_payload(header_group, *, grouping_active=False, label_column=None):
    """Prepare x/y label payload data for summary trend plotting."""

    return _build_trend_plot_payload(
        header_group,
        grouping_active=grouping_active,
        label_column=label_column,
    )


def build_histogram_density_curve_payload(measurements, point_count=100, *, mode='normal_fit'):
    """Build smooth density-curve payload arrays for histogram overlays."""

    return _build_histogram_density_curve_payload(measurements, point_count=point_count, mode=mode)


def apply_shared_x_axis_label_strategy(ax, labels, **kwargs):
    """Apply shared x-axis tick labeling policy to a matplotlib axis."""

    return _apply_shared_x_axis_label_strategy(ax, labels, **kwargs)


def prepare_categorical_x_axis(labels, **kwargs):
    """Resolve shared categorical axis layout metadata for extended charts."""

    return _prepare_categorical_x_axis(labels, **kwargs)


def resolve_extended_chart_fig_width(n_groups, **kwargs):
    """Resolve a dynamic figure width for extended categorical charts."""

    return _resolve_extended_chart_fig_width(n_groups, **kwargs)


def render_tolerance_band(ax, nom, lsl, usl, *, one_sided=False, orientation='horizontal'):
    """Render tolerance band shading on summary charts."""

    return _render_tolerance_band(
        ax,
        nom,
        lsl,
        usl,
        one_sided=one_sided,
        orientation=orientation,
    )


def render_spec_reference_lines(ax, nom, lsl, usl, *, orientation='horizontal', include_nominal=True):
    """Render nominal/LSL/USL reference lines on summary charts."""

    return _render_spec_reference_lines(
        ax,
        nom,
        lsl,
        usl,
        orientation=orientation,
        include_nominal=include_nominal,
    )


def build_tolerance_reference_legend_handles(*, include_nominal=True):
    """Return reusable legend handles for tolerance/spec references."""

    return _build_tolerance_reference_legend_handles(include_nominal=include_nominal)


def build_histogram_table_data(summary_stats):
    """Build stable, display-ready statistics rows and row metadata for histograms."""

    return _build_histogram_table_data(summary_stats)

def build_histogram_table_render_data(table_data, *, three_column=False):
    """Build render rows for histogram summary tables."""

    return _build_histogram_table_render_data(table_data, three_column=three_column)

def compute_scaled_y_limits(current_limits, scale_factor):
    """Return y-axis limits expanded by a symmetric scale factor."""
    return _compute_scaled_y_limits(current_limits, scale_factor)


def build_summary_sheet_position_plan(base_col):
    """Build summary-sheet column placement metadata for exports."""

    return _build_summary_sheet_position_plan(base_col)


def build_summary_image_anchor_plan(base_col):
    """Resolve image anchor cells for summary chart insertion."""

    return _build_summary_image_anchor_plan(base_col)


def build_histogram_annotation_specs(average, usl, lsl, y_max):
    """Build annotation descriptors for histogram mean and spec-limit markers."""

    return _build_histogram_annotation_specs(average, usl, lsl, y_max)


def compute_histogram_annotation_rows(annotation_specs, distance_threshold, **kwargs):
    """Compute collision-safe row assignments and text y-axis locations."""

    return _compute_histogram_annotation_rows(annotation_specs, distance_threshold, **kwargs)


def build_histogram_mean_line_style():
    """Return style contract for histogram mean reference line."""
    return {
        'color': SUMMARY_PLOT_PALETTE['central_tendency'],
        'linestyle': '--',
        'linewidth': 1.3,
        'alpha': 0.48,
        'zorder': 2,
    }


def render_histogram_figure_title(
    fig,
    title,
    *,
    fontsize=12.0,
    color='#2f3b4a',
    fontweight='bold',
    x=0.06,
    ha='left',
):
    """Render histogram title in figure space so layout can reserve a stable top band."""

    if not title:
        return None
    return fig.text(
        x,
        0.985,
        str(title),
        ha=ha,
        va='top',
        fontsize=fontsize,
        fontweight=fontweight,
        color=color,
        zorder=14,
        clip_on=False,
    )


def render_histogram_title(ax, title, *, slot='title_band', fontsize=10.0, fontweight='bold'):
    """Backward-compatible wrapper for figure-level histogram title rendering."""

    del slot
    fig = getattr(ax, 'figure', None)
    if fig is None:
        return None
    return render_histogram_figure_title(
        fig,
        title,
        fontsize=fontsize,
        color=SUMMARY_PLOT_PALETTE['distribution_foreground'],
        fontweight=fontweight,
    )


def resolve_edge_safe_label_anchor(x_data, x_min, x_max, edge_fraction=0.06):
    """Resolve alignment and horizontal offset for labels near x-axis edges."""
    try:
        x_value = float(x_data)
        left_edge = float(x_min)
        right_edge = float(x_max)
        edge_ratio = max(0.0, float(edge_fraction))
    except (TypeError, ValueError):
        return {'ha': 'center', 'x_offset_points': 0.0}

    if right_edge < left_edge:
        left_edge, right_edge = right_edge, left_edge
    x_span = right_edge - left_edge
    if x_span <= 0:
        return {'ha': 'center', 'x_offset_points': 0.0}

    edge_delta = x_span * edge_ratio
    if x_value <= (left_edge + edge_delta):
        return {'ha': 'left', 'x_offset_points': 6.0}
    if x_value >= (right_edge - edge_delta):
        return {'ha': 'right', 'x_offset_points': -6.0}
    return {'ha': 'center', 'x_offset_points': 0.0}


def resolve_histogram_x_view(values, *, lsl=None, usl=None, mean_value=None, margin_ratio=_HISTOGRAM_X_MARGIN_RATIO):
    """Resolve histogram x framing with local span + small fallback safety margin."""

    finite_values = pd.to_numeric(pd.Series(values), errors='coerce').dropna().to_numpy(dtype=float)
    if finite_values.size == 0:
        return {'x_min': 0.0, 'x_max': 1.0, 'mode': 'full'}

    data_min = float(np.min(finite_values))
    data_max = float(np.max(finite_values))

    left_limit = None
    right_limit = None
    for raw_limit, side in ((lsl, 'left'), (usl, 'right')):
        if raw_limit is None:
            continue
        try:
            limit_value = float(raw_limit)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(limit_value):
            continue
        if side == 'left':
            left_limit = limit_value
        else:
            right_limit = limit_value

    left_ref = data_min if left_limit is None else min(data_min, left_limit)
    right_ref = data_max if right_limit is None else max(data_max, right_limit)

    data_span = max(data_max - data_min, 0.0)
    if left_limit is not None and right_limit is not None:
        spec_span = max(right_limit - left_limit, 0.0)
    else:
        spec_span = max(right_ref - left_ref, 0.0)

    mean_magnitude = 0.0
    if mean_value is not None:
        try:
            candidate_mean = float(mean_value)
            if np.isfinite(candidate_mean):
                mean_magnitude = abs(candidate_mean)
        except (TypeError, ValueError):
            pass
    ref_magnitude = max(mean_magnitude, abs(data_min), abs(data_max), 1.0)
    fallback_span = max(1e-6, 1e-4 * ref_magnitude)

    effective_span = max(data_span, spec_span, fallback_span)
    margin = effective_span * max(0.0, float(margin_ratio))

    return {
        'x_min': left_ref - margin,
        'x_max': right_ref + margin,
        'mode': 'full',
    }


def render_histogram_annotations(ax, annotation_specs, *, annotation_fontsize, annotation_box):
    """Render histogram annotations with consistent font sizing policy."""
    def _resolve_plot_rect_display_bounds(fig, plot_rect):
        if not isinstance(plot_rect, dict):
            return None
        try:
            left = float(plot_rect['x']) * float(fig.bbox.width)
            bottom = float(plot_rect['y']) * float(fig.bbox.height)
            right = left + (float(plot_rect['width']) * float(fig.bbox.width))
            top = bottom + (float(plot_rect['height']) * float(fig.bbox.height))
        except (KeyError, TypeError, ValueError):
            return None
        return left, right, bottom, top

    def _resolve_annotation_safe_bounds(fig, plot_rect, *, extra_top_px=92.0, extra_side_px=8.0):
        bounds = _resolve_plot_rect_display_bounds(fig, plot_rect)
        if bounds is None:
            return None
        left, right, bottom, top = bounds
        return (
            left + float(extra_side_px),
            right - float(extra_side_px),
            bottom + 2.0,
            top + float(extra_top_px),
        )

    def _bbox_fits_plot_rect(bbox, bounds, *, padding_px=2.0):
        if bbox is None or bounds is None:
            return True
        left, right, bottom, top = bounds
        return (
            bbox.x0 >= (left + padding_px)
            and bbox.x1 <= (right - padding_px)
            and bbox.y0 >= (bottom + padding_px)
            and bbox.y1 <= (top - padding_px)
        )

    def _build_candidate_offsets(annotation_kind):
        if annotation_kind == 'mean':
            return [(0.0, 0.0), (0.0, -6.0), (0.0, -12.0), (-8.0, -6.0), (8.0, -6.0)]
        if annotation_kind in {'lsl', 'usl'}:
            return [
                (0.0, 0.0),
                (-8.0, -6.0),
                (8.0, -6.0),
                (-12.0, -10.0),
                (12.0, -10.0),
                (0.0, -14.0),
            ]
        return [(0.0, 0.0), (0.0, -6.0), (0.0, -12.0)]

    def _resolve_ha_from_offset(default_ha, x_offset_points):
        if x_offset_points > 6.0:
            return 'left'
        if x_offset_points < -6.0:
            return 'right'
        return default_ha

    rendered = []
    transform = ax.get_xaxis_transform()
    figure = ax.figure
    x_min, x_max = ax.get_xlim()
    plot_rect = annotation_box.get('plot_rect') if isinstance(annotation_box, dict) else None
    title_artist = annotation_box.get('title_artist') if isinstance(annotation_box, dict) else None
    plot_rect_bounds = _resolve_annotation_safe_bounds(figure, plot_rect)
    title_bbox = None
    if title_artist is not None:
        figure.canvas.draw()
        title_bbox = title_artist.get_window_extent(renderer=figure.canvas.get_renderer())
    priority_sorted = sorted(
        list(enumerate(annotation_specs or [])),
        key=lambda item: (-int(item[1].get('priority', 100)), item[0]),
    )
    accepted = {}
    accepted_bboxes = []
    accepted_rows = []
    for index, annotation in priority_sorted:
        annotation_kind = str(annotation.get('kind') or '').lower()
        resolved_ha = annotation.get('ha', 'center')
        x_offset_points = 0.0
        if annotation_kind in {'lsl', 'usl'}:
            edge_anchor = resolve_edge_safe_label_anchor(
                annotation.get('x'),
                x_min,
                x_max,
            )
            edge_ha = edge_anchor.get('ha', 'center')
            edge_offset_points = float(edge_anchor.get('x_offset_points', 0.0))
            if edge_offset_points != 0.0:
                resolved_ha = edge_ha
                x_offset_points = edge_offset_points
        placed_artist = None
        placed_bbox = None
        annotation_row = annotation.get('row_index')
        base_y_axes = annotation.get('text_y_axes', 1.02)
        for extra_x_offset, extra_y_offset in _build_candidate_offsets(annotation_kind):
            total_x_offset = x_offset_points + float(extra_x_offset)
            candidate_ha = _resolve_ha_from_offset(resolved_ha, total_x_offset)
            needs_leader_line = abs(total_x_offset) >= 8.0 or abs(float(extra_y_offset)) >= 6.0
            candidate_fontfamily = 'DejaVu Sans' if _uses_symbol_font_fallback(annotation['text']) else None
            if abs(total_x_offset) < 1e-9 and abs(float(extra_y_offset)) < 1e-9:
                candidate_artist = ax.text(
                    annotation['x'],
                    base_y_axes,
                    annotation['text'],
                    transform=transform,
                    color=annotation['color'],
                    ha=candidate_ha,
                    va='bottom',
                    fontsize=annotation_fontsize,
                    bbox={k: v for k, v in annotation_box.items() if k not in {'plot_rect', 'title_artist'}},
                    zorder=10,
                    clip_on=False,
                    fontfamily=candidate_fontfamily,
                )
            else:
                candidate_artist = ax.annotate(
                    annotation['text'],
                    xy=(annotation['x'], base_y_axes),
                    xycoords=transform,
                    xytext=(total_x_offset, float(extra_y_offset)),
                    textcoords='offset points',
                    color=annotation['color'],
                    ha=candidate_ha,
                    va='bottom',
                    fontsize=annotation_fontsize,
                    bbox={k: v for k, v in annotation_box.items() if k not in {'plot_rect', 'title_artist'}},
                    arrowprops=(
                        {
                            'arrowstyle': '-',
                            'color': annotation['color'],
                            'linewidth': 0.75,
                            'alpha': 0.65,
                            'shrinkA': 0,
                            'shrinkB': 2,
                        }
                        if needs_leader_line
                        else None
                    ),
                    zorder=10,
                    clip_on=False,
                    fontfamily=candidate_fontfamily,
                )
            figure.canvas.draw()
            candidate_bbox = candidate_artist.get_window_extent(renderer=figure.canvas.get_renderer())
            is_safe = _bbox_fits_plot_rect(candidate_bbox, plot_rect_bounds)
            if is_safe and title_bbox is not None and candidate_bbox.overlaps(title_bbox):
                is_safe = False
            if is_safe and accepted_bboxes:
                if any(candidate_bbox.overlaps(existing_bbox) for existing_bbox in accepted_bboxes):
                    is_safe = False
            if is_safe:
                placed_artist = candidate_artist
                placed_bbox = candidate_bbox
                break
            candidate_artist.remove()

        if placed_artist is not None:
            accepted[index] = placed_artist
            accepted_bboxes.append(placed_bbox)
            accepted_rows.append(annotation_row)

    for index, _annotation in enumerate(annotation_specs or []):
        text_artist = accepted.get(index)
        if text_artist is not None:
            rendered.append(text_artist)
    return rendered


def resolve_summary_annotation_strategy(*, x_point_count):
    """Resolve a low-overhead annotation strategy based on x-axis point density."""
    return _resolve_summary_annotation_strategy(x_point_count=x_point_count)


def build_summary_panel_subtitle_text(summary_stats):
    """Generate subtitle text displayed under summary panel titles."""

    return _build_summary_panel_subtitle(summary_stats)


def build_summary_table_composition(summary_stats, histogram_table_payload):
    """Build summary-table badges/subtitle contract from pure inputs."""

    return _build_summary_table_composition(summary_stats, histogram_table_payload)


def compute_histogram_font_sizes(
    figure_size=(6, 4),
    *,
    has_table=True,
    readability_scale=None,
):
    """Compute histogram annotation/table font sizes for summary-sheet embedding."""
    return _compute_histogram_font_sizes(
        figure_size=figure_size,
        has_table=has_table,
        readability_scale=readability_scale,
    )

def compute_histogram_table_layout(
    figure_size=(6, 4),
    *,
    table_fontsize=8.0,
    has_table=True,
):
    """Compute table bbox width and subplot right margin for histogram layouts."""
    return _compute_histogram_table_layout(
        figure_size=figure_size,
        table_fontsize=table_fontsize,
        has_table=has_table,
    )


def compute_histogram_three_region_layout(
    figure_size=(6, 4),
    *,
    table_fontsize=8.0,
):
    """Compute compact geometry for left/center/right histogram rendering regions."""
    return _compute_histogram_three_region_layout(
        figure_size=figure_size,
        table_fontsize=table_fontsize,
    )


def compute_histogram_panel_layout(
    figure_size=(6, 4),
    *,
    table_fontsize=8.0,
    left_row_count=0,
    right_row_count=0,
    note_line_count=0,
    left_panel_width_hint=None,
    right_panel_width_hint=None,
):
    """Compute non-overlapping histogram panel rectangles."""
    return _compute_histogram_panel_layout(
        figure_size=figure_size,
        table_fontsize=table_fontsize,
        left_row_count=left_row_count,
        right_row_count=right_row_count,
        note_line_count=note_line_count,
        left_panel_width_hint=left_panel_width_hint,
        right_panel_width_hint=right_panel_width_hint,
    )


def compute_histogram_plot_with_right_info_layout(
    figure_size=(8.4, 4.0),
    *,
    table_fontsize=8.0,
    fit_row_count=0,
    stats_row_count=0,
    fit_rows=None,
    stats_rows=None,
    note_line_count=0,
    right_container_width_hint=None,
    dpi=100.0,
):
    """Compute plot + right info-column rectangles for histogram exports."""
    return _compute_histogram_plot_with_right_info_layout(
        figure_size=figure_size,
        table_fontsize=table_fontsize,
        fit_row_count=fit_row_count,
        stats_row_count=stats_row_count,
        fit_rows=fit_rows,
        stats_rows=stats_rows,
        note_line_count=note_line_count,
        right_container_width_hint=right_container_width_hint,
        dpi=dpi,
    )


def compute_row_line_count(text):
    """Return line count for a table cell value."""
    return _compute_row_line_count(text)


def resolve_table_row_line_count(label_text, value_text):
    """Return row line count based on both label and value text."""
    return _resolve_table_row_line_count(label_text, value_text)


def resolve_histogram_dashboard_row_metrics(*, table_fontsize, dpi):
    """Return shared row metrics for histogram dashboard tables."""
    return _resolve_histogram_dashboard_row_metrics(table_fontsize=table_fontsize, dpi=dpi)


def resolve_required_histogram_figure_height_for_complete_right_tables(
    *,
    fit_rows=None,
    stats_rows=None,
    fit_row_count=0,
    stats_row_count=0,
    table_fontsize=8.0,
    dpi=100.0,
    minimum_height=4.4,
):
    """Return figure height needed to keep both histogram right-column tables complete."""
    return _resolve_required_histogram_figure_height_for_complete_right_tables(
        fit_rows=fit_rows,
        stats_rows=stats_rows,
        fit_row_count=fit_row_count,
        stats_row_count=stats_row_count,
        table_fontsize=table_fontsize,
        dpi=dpi,
        minimum_height=minimum_height,
    )


def assert_non_overlapping_rectangles(rectangles):
    """Assert that provided rectangles do not intersect."""
    return _assert_non_overlapping_rectangles(rectangles)


def _format_percent(value, *, decimals=4):
    if value is None:
        return 'N/A'
    try:
        return f"{float(value):.{int(decimals)}f}%"
    except (TypeError, ValueError):
        return 'N/A'


def _format_probability_percent(probability, *, decimals=4):
    return format_probability_percent(probability, decimals=decimals, threshold_percent=0.0001)


def _is_effectively_zero(value, tolerance=1e-12):
    try:
        return abs(float(value)) <= tolerance
    except (TypeError, ValueError):
        return False


def _as_float_or_none(value):
    if isinstance(value, str):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _resolve_capability_status(*, cp=None, cpk=None, ppk=None, nok_ratio=None):
    capability_values = [
        value
        for value in (_as_float_or_none(cp), _as_float_or_none(cpk), _as_float_or_none(ppk))
        if value is not None
    ]
    nok_value = _as_float_or_none(nok_ratio)

    capability_tier = None
    if capability_values:
        limiting_index = min(capability_values)
        if limiting_index >= 1.67:
            capability_tier = 'capable'
        elif limiting_index > 1.33:
            capability_tier = 'good'
        elif limiting_index >= 1.0:
            capability_tier = 'marginal'
        else:
            capability_tier = 'risk'

    nok_tier = None
    if nok_value is not None:
        if nok_value <= 0.003:
            nok_tier = 'good'
        elif nok_value <= 0.05:
            nok_tier = 'marginal'
        else:
            nok_tier = 'risk'

    tier_rank = {'capable': 0, 'good': 1, 'marginal': 2, 'risk': 3}
    selected_tier = None
    for tier in (capability_tier, nok_tier):
        if tier is None:
            continue
        if selected_tier is None or tier_rank[tier] > tier_rank[selected_tier]:
            selected_tier = tier

    if selected_tier is None:
        return {'label': 'N/A', 'palette_key': 'quality_unknown'}
    if selected_tier in {'capable', 'good'}:
        return {'label': selected_tier.title(), 'palette_key': 'quality_capable'}
    if selected_tier == 'marginal':
        return {'label': 'Marginal', 'palette_key': 'quality_marginal'}
    return {'label': 'Risk', 'palette_key': 'quality_risk'}


def _fit_quality_sample_size_ceiling(sample_size):
    if sample_size is None:
        return None
    n = max(0, int(sample_size or 0))
    if 0 < n < 10:
        return 'unreliable'
    if n < 25:
        return 'medium'
    return None


def _apply_fit_quality_sample_size_guard(quality_key, sample_size):
    order = {'unreliable': 0, 'weak': 1, 'medium': 2, 'strong': 3}
    normalized_quality = quality_key if quality_key in order else quality_key
    if normalized_quality not in order:
        return normalized_quality
    ceiling = _fit_quality_sample_size_ceiling(sample_size)
    if ceiling is None:
        return normalized_quality
    return min(normalized_quality, ceiling, key=lambda item: order[item])


def _build_distribution_fit_table_rows(distribution_fit_result, *, lsl=None, usl=None, summary_stats=None):
    selected_model = distribution_fit_result.get('selected_model') or {}
    fit_quality = distribution_fit_result.get('fit_quality') or {}
    risk_estimates = distribution_fit_result.get('risk_estimates') or {}
    inferred_support_mode = distribution_fit_result.get('inferred_support_mode')

    spec_type = str(risk_estimates.get('spec_type', 'none'))
    below_lsl = risk_estimates.get('below_lsl_probability')
    above_usl = risk_estimates.get('above_usl_probability')
    sample_size = (summary_stats or {}).get('sample_size')

    raw_rows = [
        ('Model', selected_model.get('display_name', 'N/A')),
    ]

    quality_key = str(fit_quality.get('label') or '').strip().lower()
    display_quality = _apply_fit_quality_sample_size_guard(quality_key, sample_size)
    show_modeled_risk_rows = display_quality not in {'weak', 'unreliable'}

    est_nok_value = None
    if show_modeled_risk_rows:
        side_parts = []
        allow_lower_tail = spec_type in {'bilateral', 'lower_only'} and lsl is not None
        lower_tail_value = below_lsl
        if inferred_support_mode == 'one_sided_zero_bound_positive' and _is_effectively_zero(lsl):
            lower_tail_value = 0.0
        if allow_lower_tail:
            side_parts.append(f"L: {_format_probability_percent(lower_tail_value, decimals=4)}")
        if spec_type in {'bilateral', 'upper_only'} and usl is not None:
            side_parts.append(f"U: {_format_probability_percent(above_usl, decimals=4)}")

        est_nok_numeric = _as_float_or_none(risk_estimates.get('nok_percent'))
        est_nok_value = _format_percent(risk_estimates.get('nok_percent'), decimals=4)
        if side_parts and (est_nok_numeric is None or est_nok_numeric >= 0.0001):
            est_nok_value = f"{est_nok_value}\n{', '.join(side_parts)}"
        raw_rows.append(('Estimated NOK %', est_nok_value))

    raw_rows.append(('Model fit quality', display_quality.title()))

    warning_parts = []
    sample_size_value = int(sample_size) if sample_size is not None else None
    if sample_size_value is not None and 0 < sample_size_value < 10:
        warning_parts.append('fit unreliable')
    elif sample_size_value is not None and sample_size_value < 25:
        warning_parts.append('small sample')

    if display_quality == 'weak':
        warning_parts.append('fit weak')
    elif display_quality == 'unreliable':
        if 'fit unreliable' not in warning_parts:
            warning_parts.append('fit unreliable')
        warning_parts.append('observed NOK only')

    if sample_size_value is not None and 0 < sample_size_value < 25 and display_quality != 'unreliable':
        if 'small sample' not in warning_parts:
            warning_parts.insert(0, 'small sample')
        warning_parts.append('capability uncertain')

    warning_parts = [part for part in warning_parts if part]
    if len(warning_parts) > 2:
        if 'fit unreliable' in warning_parts and 'observed NOK only' in warning_parts:
            warning_parts = ['fit unreliable', 'observed NOK only']
        elif 'small sample' in warning_parts and 'capability uncertain' in warning_parts:
            warning_parts = ['small sample', 'capability uncertain']
        elif 'fit weak' in warning_parts:
            warning_parts = ['fit weak']
        else:
            warning_parts = warning_parts[:2]

    if warning_parts:
        raw_rows.append(('Warning', '; '.join(warning_parts)))

    return [(_compact_distribution_fit_label(label), value) for label, value in raw_rows]


def _build_unified_histogram_dashboard_rows(*, statistics_rows, distribution_fit_rows):
    """Return unified right-panel rows in process-then-model order."""

    return list(statistics_rows or []) + list(distribution_fit_rows or [])


def _build_histogram_native_visual_metadata(*, summary_stats, lsl, usl, nominal):
    """Build stable visual-metadata payload contract for native histogram rendering."""
    histogram_table_payload = _build_histogram_table_data(summary_stats)
    rendered_rows = histogram_table_payload.get('rows') or []

    annotation_specs = _build_histogram_annotation_specs(summary_stats.get('average'), usl, lsl, 1.0)
    finite_points = [
        float(item)
        for item in (summary_stats.get('average'), lsl, usl)
        if isinstance(item, (int, float)) and np.isfinite(float(item))
    ]
    x_span = abs(max(finite_points) - min(finite_points)) if len(finite_points) >= 2 else 1.0
    annotation_specs, _ = _compute_histogram_annotation_rows(
        annotation_specs,
        distance_threshold=0.04,
        threshold_mode='axis_fraction',
        x_span=max(x_span, 1e-12),
        base_text_y_axes=1.01,
        row_step=0.025,
    )

    def _line(label, value, *, role):
        return {
            'id': role,
            'label': label,
            'value': None if value is None else float(value),
            'enabled': value is not None,
            'style_hint': {'orientation': 'vertical', 'line_role': role},
        }

    return {
        'schema_version': 1,
        'specification_lines': [
            _line('LSL', lsl, role='lsl'),
            _line('USL', usl, role='usl'),
            _line('Nominal', nominal, role='nominal'),
        ],
        'summary_stats_table': {
            'title': 'Parameter',
            'columns': ['Parameter', 'Value'],
            'rows': [
                {'label': str(label), 'value': str(value), 'row_kind': 'summary_metric'}
                for label, value in rendered_rows
            ],
        },
        'annotation_rows': [
            {
                'label': spec.get('label'),
                'x': spec.get('x'),
                'y': spec.get('y'),
                'xytext': spec.get('xytext'),
                'placement_hint': {
                    'textcoords': spec.get('textcoords', 'data'),
                    'va': spec.get('va', 'bottom'),
                    'ha': spec.get('ha', 'center'),
                },
            }
            for spec in annotation_specs
        ],
        'modeled_overlays': {
            'advanced_annotations_enabled': False,
            'overlays_enabled': False,
            'rows': [],
            'status': 'disabled',
        },
    }


def _apply_table_section_separator(ax_table, table_data, *, transition_label='Model'):
    """Add subtle visual grouping by drawing a mild separator above transition row."""

    if ax_table is None:
        return

    transition_index = None
    for idx, row in enumerate(table_data or [], start=1):
        if str(row[0]).strip() == transition_label:
            transition_index = idx
            break
    if transition_index is None:
        return

    cell_map = ax_table.get_celld()
    column_indexes = sorted({col for (row, col) in cell_map.keys() if row == 0}) or [0, 1]
    for col_index in column_indexes:
        cell = cell_map.get((transition_index, col_index))
        if cell is None:
            continue
        cell.set_edgecolor('#d5dbe3')
        cell.set_linewidth(max(0.75, float(cell.get_linewidth())))


def _build_distribution_fit_info_note(distribution_fit_result, *, summary_stats):
    inferred_support = distribution_fit_result.get('inferred_support_mode') or 'unknown'
    spec_handling_text = {
        'one_sided_zero_bound_positive': 'one-sided upper',
        'one_sided_zero_bound_negative': 'one-sided lower',
        'bilateral_signed': 'two-sided (both LSL and USL active)',
    }.get(inferred_support, 'based on active limits')
    fit_quality = distribution_fit_result.get('fit_quality') or {}
    fit_warning = distribution_fit_result.get('warning')

    note_items = [
        {
            'label': 'Spec handling',
            'compact_label': 'Spec handling',
            'value': spec_handling_text,
            'compact_value': spec_handling_text,
            'priority': 90,
            'tooltip': 'How limits are applied when computing estimated NOK and capability metrics.',
        },
    ]

    normality_text = summary_stats.get('normality_text')
    if normality_text:
        note_items.append({
            'label': 'Reference normality',
            'compact_label': 'Normality',
            'value': normality_text,
            'compact_value': str(normality_text).splitlines()[-1],
            'priority': 60,
        })

    quality_label = str(fit_quality.get('label', '')).lower()
    is_poor_fit = quality_label in {'weak', 'unreliable'}
    if is_poor_fit:
        note_items.append({
            'label': 'Warning',
            'compact_label': 'Warning',
            'value': f'fit {quality_label}',
            'compact_value': f'fit {quality_label}',
            'priority': 30,
        })
    if fit_warning:
        note_items.append({
            'label': 'Warning',
            'value': 'fit warning',
            'compact_value': 'fit warning',
            'priority': 20,
            'expanded_only': True,
        })

    return note_items, is_poor_fit



def _build_compact_histogram_note_lines(distribution_fit_result, *, summary_stats=None):
    """Build compact right-panel note lines for histogram export context."""

    fit_result = distribution_fit_result or {}
    lines = []

    mode = fit_result.get('inferred_support_mode')
    if mode == 'one_sided_zero_bound_positive':
        lines.append('Spec handling: one-sided upper')
        lines.append('Tooltip: Uses only USL for tail risk and capability decisions (Cp suppressed; Cpk shown as Cpu)')
    elif mode == 'one_sided_zero_bound_negative':
        lines.append('Spec handling: one-sided lower')
        lines.append('Tooltip: Uses only LSL for tail risk and capability decisions (Cp suppressed; Cpk shown as Cpl)')
    elif mode == 'bilateral_signed':
        lines.append('Spec handling: two-sided (both LSL and USL active)')
        lines.append('Tooltip: Uses both tails; Cp and Cpk summarize spread and centering versus both limits')

    fit_quality = ((fit_result.get('fit_quality') or {}).get('label') or '').strip().lower()
    is_poor_fit = fit_quality in {'weak', 'unreliable'}
    sample_size = (summary_stats or {}).get('sample_size')
    sample_size_value = int(sample_size) if sample_size is not None else 0
    low_n_severe = 0 < sample_size_value < 10
    low_n_warning = 10 <= sample_size_value < 25

    if low_n_severe:
        lines.append(f'Warning: low sample size (n={sample_size_value})')
    elif low_n_warning:
        lines.append(f'Warning: limited sample size (n={sample_size_value})')

    if is_poor_fit:
        lines.append(f'Warning: fit {fit_quality}')
    elif low_n_severe:
        lines.append('Fit reliability: low (sample-limited)')
    elif low_n_warning:
        lines.append('Fit reliability: guarded (n<25)')
    elif fit_quality == 'medium':
        lines.append('Fit reliability: medium')
    if fit_quality in {'medium', 'good', 'strong'} and not is_poor_fit:
        lines.append('Tooltip: Fit reliability reflects distribution adequacy; lower reliability increases uncertainty in estimated NOK/PPM')

    gof_metrics = fit_result.get('gof_metrics') or {}
    reference_normality = str(gof_metrics.get('reference_normality_label') or '').strip()
    normality_is_concise = reference_normality and len(reference_normality) <= 24
    normality_adds_context = reference_normality.lower() not in {'normal', 'gaussian-like'}
    if (not is_poor_fit) and fit_quality not in {'medium'} and normality_is_concise and normality_adds_context:
        lines.append(f'Normality: {reference_normality}')

    if low_n_severe or low_n_warning:
        threshold_text = 'n<10 severe instability' if low_n_severe else 'n<25 broad uncertainty'
        lines.append(f'Rationale: {threshold_text}; capability shown as low-confidence estimate')

    lines.extend([
        'Help: NOK obs/est gaps can indicate model mismatch, subgroup effects, or insufficient data',
        'Help: model fit quality = statistical adequacy of chosen distribution',
        'Help: capability status = conformance risk against specs',
    ])

    return lines[:7]

def _is_non_normal_capability_reference_model(distribution_fit_result):
    selected_model = (distribution_fit_result or {}).get('selected_model') or {}
    model_name = str(selected_model.get('model') or '').strip().lower()
    if not model_name:
        return False
    return model_name not in {'norm'}


def _should_use_capability_reference_label(distribution_fit_result, *, summary_stats=None):
    fit_quality = ((distribution_fit_result or {}).get('fit_quality') or {}).get('label')
    quality_key = str(fit_quality or '').strip().lower()
    sample_size = (summary_stats or {}).get('sample_size')
    display_quality = _apply_fit_quality_sample_size_guard(quality_key, sample_size)
    return _is_non_normal_capability_reference_model(distribution_fit_result) or display_quality in {'weak', 'unreliable'}


def _apply_non_normal_cpk_reference_label(histogram_table_payload, distribution_fit_result, *, summary_stats=None):
    if not _should_use_capability_reference_label(distribution_fit_result, summary_stats=summary_stats):
        return histogram_table_payload

    payload = dict(histogram_table_payload or {})
    rows = []
    for label, value in payload.get('rows', []):
        if label in {'Cpu', 'Cpl', 'Cpu 95% CI', 'Cpl 95% CI'}:
            rows.append((f'{label} (ref)', value))
            continue
        rows.append(
            ('Cpk (ref)', value)
            if label in {'Cpk', 'Cpk+'}
            else ('Cpk (ref) 95% CI', value)
            if label in {'Cpk 95% CI', 'Cpk+ 95% CI'}
            else ('Cp (ref)', value)
            if label == 'Cp'
            else ('Cp (ref) 95% CI', value)
            if label == 'Cp 95% CI'
            else (label, value)
        )
    payload['rows'] = rows

    capability_rows = dict(payload.get('capability_rows') or {})
    for key in ('Cp', 'Cpk', 'Cpk+', 'Cpu', 'Cpl'):
        cpk_meta = dict(capability_rows.get(key) or {})
        if cpk_meta:
            if key == 'Cp':
                cpk_meta['label'] = 'Cp (ref)'
            elif key in {'Cpu', 'Cpl'}:
                cpk_meta['label'] = f'{key} (ref)'
            else:
                cpk_meta['label'] = 'Cpk (ref)'
            capability_rows[key] = cpk_meta

    if capability_rows:
        payload['capability_rows'] = capability_rows
    return payload


def render_histogram_note_panel(
    *,
    ax,
    note_items,
    style_options=None,
    available_height_px=None,
):
    """Render histogram fit note panel as multiline textbox with graceful truncation."""

    options = dict(style_options or {})
    fontsize = float(options.get('fontsize', 7.0))
    min_fontsize = float(options.get('min_fontsize', 6.2))
    max_fontsize = float(options.get('max_fontsize', 9.0))
    fontsize = min(max(fontsize, min_fontsize), max_fontsize)
    header_fontweight = options.get('header_fontweight', 'normal')
    line_spacing = float(options.get('line_spacing', 1.18))
    pad_x = float(options.get('pad_x', 0.03))
    pad_y = float(options.get('pad_y', 0.04))

    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    line_height_px = _measure_text_extent(fig, renderer, 'Ag', fontsize=fontsize, fontweight=header_fontweight)[1]
    max_height_px = max(1.0, available_height_px if available_height_px is not None else float(ax.bbox.height))
    usable_height_px = max(1.0, max_height_px - ((pad_y * 2.0) * float(ax.bbox.height)))
    line_capacity = max(1, int(usable_height_px // max(1.0, line_height_px)))

    normalized_items = []
    for index, item in enumerate(note_items or []):
        if not isinstance(item, dict):
            continue
        normalized_items.append({
            'index': index,
            'label': str(item.get('label', '')).strip(),
            'value': str(item.get('value', '')).strip(),
            'compact_label': str(item.get('compact_label', item.get('label', ''))).strip(),
            'compact_value': str(item.get('compact_value', item.get('value', ''))).strip(),
            'priority': int(item.get('priority', 0)),
            'expanded_only': bool(item.get('expanded_only', False)),
        })

    compact_items = [item for item in normalized_items if not item['expanded_only']]
    expanded_items = list(normalized_items)
    using_compact = len(expanded_items) > line_capacity
    selected_items = compact_items if using_compact else expanded_items

    omitted_items = []
    if len(selected_items) > line_capacity:
        to_drop = len(selected_items) - line_capacity
        ranked_for_drop = sorted(selected_items, key=lambda item: (item['priority'], -item['index']))
        dropped_keys = {item['index'] for item in ranked_for_drop[:to_drop]}
        omitted_items = [item for item in selected_items if item['index'] in dropped_keys]
        selected_items = [item for item in selected_items if item['index'] not in dropped_keys]

    rendered_lines = []
    for item in selected_items:
        if using_compact:
            label = item['compact_label']
            value = item['compact_value']
        else:
            label = item['label']
            value = item['value']
        if label and value:
            rendered_lines.append(f"{label}: {value}")
        elif value:
            rendered_lines.append(value)

    if not rendered_lines:
        rendered_lines = ['N/A']

    ax.set_axis_off()
    text_artist = ax.text(
        pad_x,
        1.0 - pad_y,
        '\n'.join(rendered_lines),
        transform=ax.transAxes,
        ha='left',
        va='top',
        fontsize=fontsize,
        linespacing=line_spacing,
        color=options.get('text_color', SUMMARY_PLOT_PALETTE['axis_text']),
        bbox={
            'boxstyle': 'round,pad=0.25',
            'facecolor': options.get('box_facecolor', 'white'),
            'edgecolor': options.get('box_edgecolor', SUMMARY_PLOT_PALETTE['annotation_box_edge']),
            'linewidth': float(options.get('box_linewidth', 0.6)),
            'alpha': float(options.get('box_alpha', 0.95)),
        },
        clip_on=True,
    )

    return {
        'text_artist': text_artist,
        'rendered_lines': rendered_lines,
        'omitted_items': omitted_items,
        'variant': 'compact' if using_compact else 'expanded',
    }

def apply_summary_plot_theme():
    """Apply a consistent summary plotting theme."""
    if _HAS_SEABORN:
        sns.set_theme(style='white', context='paper')
    plt.rcParams.update({
        'font.size': 8,
        'axes.labelsize': 8,
        'axes.titlesize': 10,
        'axes.edgecolor': SUMMARY_PLOT_PALETTE['axis_spine'],
        'axes.linewidth': 0.9,
        'axes.labelcolor': SUMMARY_PLOT_PALETTE['axis_text'],
        'axes.titlecolor': SUMMARY_PLOT_PALETTE['annotation_text'],
        'xtick.color': SUMMARY_PLOT_PALETTE['axis_text'],
        'ytick.color': SUMMARY_PLOT_PALETTE['axis_text'],
        'grid.color': SUMMARY_PLOT_PALETTE['grid'],
        'grid.linewidth': 0.5,
        'grid.alpha': 0.4,
    })


def apply_minimal_axis_style(ax, grid_axis='y'):
    """Apply a clean, minimal visual style on a chart axis."""
    ax.set_facecolor('white')
    ax.grid(
        True,
        axis=grid_axis,
        linestyle='-',
        linewidth=0.5,
        color=SUMMARY_PLOT_PALETTE['grid'],
        alpha=0.4,
    )
    if grid_axis == 'y':
        ax.grid(False, axis='x')
    elif grid_axis == 'x':
        ax.grid(False, axis='y')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(SUMMARY_PLOT_PALETTE['axis_spine'])
    ax.spines['bottom'].set_color(SUMMARY_PLOT_PALETTE['axis_spine'])
    ax.tick_params(axis='both', colors=SUMMARY_PLOT_PALETTE['axis_text'])


def build_violin_group_stats_rows(labels, values):
    """Return per-group stats rows with p-values against a reference distribution."""

    return _build_violin_group_stats_rows(labels, values)

def resolve_violin_annotation_style(
    *,
    group_count,
    x_limits,
    figure_size=(6, 4),
    mode='auto',
    readability_scale=None,
):
    """Resolve violin annotation style based on density and readability scaling."""
    mode_styles = {
        'full': {
            'font_size': 7.4,
            'minmax_marker_size': 16,
            'mean_marker_size': 22,
            'offsets': {
                'min': (4, -10),
                'mean': (4, 2),
                'max': (4, 2),
                'sigma_low': (4, -10),
                'sigma_high': (4, 2),
            },
            'show_minmax': True,
            'show_sigma': True,
            'sigma_line_width': 0.9,
        },
        'compact': {
            'font_size': 6.8,
            'minmax_marker_size': 12,
            'mean_marker_size': 16,
            'offsets': {
                'min': (2, -8),
                'mean': (2, 1),
                'max': (2, 1),
                'sigma_low': (2, -8),
                'sigma_high': (2, 1),
            },
            'show_minmax': True,
            'show_sigma': True,
            'sigma_line_width': 0.7,
        },
    }

    safe_group_count = max(0, int(group_count))
    if safe_group_count <= 0:
        style = dict(mode_styles['compact'])
        style['offsets'] = dict(style['offsets'])
        style['mode'] = 'compact'
        return style

    x_min, x_max = x_limits
    x_range = max(float(x_max - x_min), 1e-9)
    x_spacing = x_range / safe_group_count

    resolved_mode = mode
    if mode == 'auto':
        resolved_mode = 'full' if (safe_group_count <= 4 and x_spacing >= 0.75) else 'compact'

    style = dict(mode_styles.get(resolved_mode, mode_styles['compact']))
    style['offsets'] = dict(style.get('offsets', {}))

    fig_width = figure_size[0] if isinstance(figure_size, (tuple, list)) and figure_size else 6
    fig_width = max(float(fig_width), 1.0)
    width_scale = min(1.25, max(0.9, fig_width / 6.0))

    optional_readability = 0.0 if readability_scale is None else float(readability_scale)
    readability_bonus = optional_readability * 0.22

    scaled_font_size = (style.get('font_size', 6.8) * width_scale) + readability_bonus
    style['font_size'] = min(10.8, max(6.8, scaled_font_size))

    marker_scale = min(1.35, max(0.85, width_scale + (optional_readability * 0.1)))
    style['minmax_marker_size'] = max(0, int(round(style.get('minmax_marker_size', 0) * marker_scale)))
    style['mean_marker_size'] = max(8, int(round(style.get('mean_marker_size', 12) * marker_scale)))

    if resolved_mode == 'compact' and (safe_group_count > 12 or x_spacing < 0.55):
        style['show_sigma'] = False

    style['mode'] = resolved_mode
    return style


def annotate_violin_group_stats(
    ax,
    labels,
    values,
    positions,
    *,
    nom=None,
    lsl=None,
    one_sided=None,
    epsilon=None,
    readability_scale=None,
    annotation_mode='auto',
    use_dynamic_offsets=True,
):
    """Annotate group summary statistics on violin plots.

    Modes:
    - full: min/mean/max + ±3σ
    - compact: mean + optional ±3σ
    - auto: chooses full/compact based on group count and x-spacing
    """

    group_count = max(len(values), len(labels))
    epsilon_value = 1e-12 if epsilon is None else float(epsilon)
    explicit_one_sided_mode = one_sided is not None
    if explicit_one_sided_mode:
        one_sided_sigma_mode = bool(one_sided)
    else:
        one_sided_sigma_mode = False
        if nom is not None and lsl is not None:
            try:
                nom_value = float(nom)
                lsl_value = float(lsl)
                one_sided_sigma_mode = bool(is_one_sided_geometric_tolerance(nom_value, lsl_value))
                if not one_sided_sigma_mode:
                    one_sided_sigma_mode = abs(nom_value) <= epsilon_value and abs(lsl_value) <= epsilon_value
            except (TypeError, ValueError):
                one_sided_sigma_mode = False

    style = resolve_violin_annotation_style(
        group_count=group_count,
        x_limits=ax.get_xlim(),
        figure_size=ax.figure.get_size_inches(),
        mode=annotation_mode,
        readability_scale=readability_scale,
    )
    style['one_sided_sigma_mode'] = one_sided_sigma_mode
    style['one_sided_sigma_explicit'] = explicit_one_sided_mode
    annotation_boxes = []
    preview_text = None
    renderer = None

    dense_group_threshold = 16
    if group_count > dense_group_threshold:
        stride = max(1, int(np.ceil(group_count / 12)))
        for idx, group_values in enumerate(values):
            arr = np.asarray(group_values, dtype=float)
            if arr.size == 0:
                continue
            xpos = positions[idx]
            mean_val = float(np.mean(arr))
            ax.scatter([xpos], [mean_val], color=SUMMARY_PLOT_PALETTE['central_tendency'], s=style['mean_marker_size'], marker='o', zorder=4)
            if idx % stride == 0:
                ax.annotate(
                    f"μ={mean_val:.3f}",
                    (xpos, mean_val),
                    textcoords='offset points',
                    xytext=style['offsets']['mean'],
                    fontsize=style['font_size'],
                    bbox={'boxstyle': 'round,pad=0.2', 'fc': 'white', 'ec': SUMMARY_PLOT_PALETTE['annotation_box_edge'], 'alpha': 0.9},
                )
        style['show_minmax'] = False
        style['show_sigma'] = False
        style['mode'] = 'dense'
        return style

    if use_dynamic_offsets:
        ax.figure.canvas.draw()
        renderer = ax.figure.canvas.get_renderer()
        preview_text = ax.text(0, 0, '', alpha=0)

    def _resolve_annotation_offset(point_xy, text, base_offset, *, fontsize, color=None, bbox=None):
        """Return a collision-free text offset while preserving deterministic behavior."""
        candidate_offsets = [
            tuple(base_offset),
            (base_offset[0], base_offset[1] + 8),
            (base_offset[0], base_offset[1] - 8),
            (base_offset[0] + 8, base_offset[1]),
            (base_offset[0] - 8, base_offset[1]),
            (base_offset[0] + 12, base_offset[1] + 8),
            (base_offset[0] - 12, base_offset[1] - 8),
            (base_offset[0], base_offset[1] + 16),
            (base_offset[0], base_offset[1] - 16),
            (base_offset[0] + 16, base_offset[1]),
            (base_offset[0] - 16, base_offset[1]),
        ]

        if not use_dynamic_offsets:
            return tuple(base_offset)

        selected_bbox = None
        selected_offset = candidate_offsets[0]
        for candidate_offset in candidate_offsets:
            preview_text.set_text(text)
            preview_text.set_position(point_xy)
            preview_text.set_fontsize(fontsize)
            preview_text.set_color(color if color is not None else SUMMARY_PLOT_PALETTE['annotation_text'])
            preview_text.set_bbox(
                dict(bbox)
                if bbox is not None
                else {'boxstyle': 'square,pad=0', 'fc': 'none', 'ec': 'none', 'alpha': 0.0}
            )
            preview_text.set_transform(
                mtransforms.offset_copy(
                    ax.transData,
                    fig=ax.figure,
                    x=candidate_offset[0],
                    y=candidate_offset[1],
                    units='points',
                )
            )
            bbox_display = preview_text.get_window_extent(renderer=renderer).expanded(1.03, 1.08)

            if not any(bbox_display.overlaps(existing_box['display']) for existing_box in annotation_boxes):
                selected_bbox = bbox_display
                selected_offset = candidate_offset
                break

            if selected_bbox is None:
                selected_bbox = bbox_display

        if selected_bbox is not None:
            bbox_corners = selected_bbox.get_points()
            data_points = ax.transData.inverted().transform(bbox_corners)
            annotation_boxes.append(
                {
                    'display': selected_bbox,
                    'data_bounds': (
                        float(data_points[0][0]),
                        float(data_points[0][1]),
                        float(data_points[1][0]),
                        float(data_points[1][1]),
                    ),
                }
            )
        return selected_offset

    annotation_payload = _build_violin_group_annotation_payload(
        values,
        positions,
        show_sigma=style['show_sigma'],
        one_sided_sigma_mode=one_sided_sigma_mode,
    )

    for item in annotation_payload:
        xpos = item['position']
        min_val = item['minimum']
        max_val = item['maximum']
        mean_val = item['mean']

        text_box = {'boxstyle': 'round,pad=0.2', 'fc': 'white', 'ec': SUMMARY_PLOT_PALETTE['annotation_box_edge'], 'alpha': 0.9}

        if style['show_minmax']:
            ax.scatter([xpos], [min_val], color=SUMMARY_PLOT_PALETTE['annotation_text'], s=style['minmax_marker_size'], marker='v', zorder=4)
            ax.annotate(
                f"min={min_val:.3f}",
                (xpos, min_val),
                textcoords='offset points',
                xytext=_resolve_annotation_offset(
                    (xpos, min_val),
                    f"min={min_val:.3f}",
                    style['offsets']['min'],
                    fontsize=style['font_size'],
                    bbox=text_box,
                ),
                fontsize=style['font_size'],
                bbox=text_box,
            )

        ax.scatter([xpos], [mean_val], color=SUMMARY_PLOT_PALETTE['central_tendency'], s=style['mean_marker_size'], marker='o', zorder=4)
        ax.annotate(
            f"μ={mean_val:.3f}",
            (xpos, mean_val),
            textcoords='offset points',
            xytext=_resolve_annotation_offset(
                (xpos, mean_val),
                f"μ={mean_val:.3f}",
                style['offsets']['mean'],
                fontsize=style['font_size'],
                bbox=text_box,
            ),
            fontsize=style['font_size'],
            bbox=text_box,
        )

        if style['show_minmax']:
            ax.scatter([xpos], [max_val], color=SUMMARY_PLOT_PALETTE['annotation_text'], s=style['minmax_marker_size'], marker='^', zorder=4)
            ax.annotate(
                f"max={max_val:.3f}",
                (xpos, max_val),
                textcoords='offset points',
                xytext=_resolve_annotation_offset(
                    (xpos, max_val),
                    f"max={max_val:.3f}",
                    style['offsets']['max'],
                    fontsize=style['font_size'],
                    bbox=text_box,
                ),
                fontsize=style['font_size'],
                bbox=text_box,
            )

        if item['show_sigma_segment']:
            ax.vlines(
                xpos,
                item['sigma_start'],
                item['sigma_high'],
                colors=SUMMARY_PLOT_PALETTE['sigma_band'],
                linestyles=':',
                linewidth=style['sigma_line_width'],
                alpha=0.8,
                zorder=3,
            )

    if preview_text is not None:
        preview_text.remove()

    return style


def add_violin_annotation_legend(ax, style, *, include_tolerance_refs=False):
    """Render a legend that explains violin annotation markers and symbols."""
    handles = [
        Line2D([0], [0], marker='o', linestyle='None', markersize=5.5, color=SUMMARY_PLOT_PALETTE['central_tendency'], label='Mean marker (μ)'),
    ]
    if style.get('show_minmax'):
        handles.extend([
            Line2D([0], [0], marker='v', linestyle='None', markersize=5.0, color=SUMMARY_PLOT_PALETTE['annotation_text'], label='Min marker'),
            Line2D([0], [0], marker='^', linestyle='None', markersize=5.0, color=SUMMARY_PLOT_PALETTE['annotation_text'], label='Max marker'),
        ])
    if style.get('show_sigma'):
        sigma_label = '+3σ span (visual)' if style.get('one_sided_sigma_mode') else '±3σ span (visual)'
        handles.append(
            Line2D([0], [0], linestyle=':', linewidth=max(style.get('sigma_line_width', 0.7), 0.7), color=SUMMARY_PLOT_PALETTE['sigma_band'], label=sigma_label),
        )

    if include_tolerance_refs:
        handles.extend(build_tolerance_reference_legend_handles())

    ax.legend(
        handles=handles,
        loc='upper left',
        bbox_to_anchor=(1.0, 1.0),
        borderaxespad=0.0,
        frameon=True,
        fontsize=max(style.get('font_size', 6.8) - 0.2, 6.6),
    )


def move_legend_to_figure(ax):
    """Move an axis legend to the parent figure's top-right corner."""

    fig = ax.figure
    handles, labels = ax.get_legend_handles_labels()
    existing_legend = ax.legend_

    if existing_legend is not None:
        existing_legend.remove()

    if not handles and existing_legend is not None:
        handles = list(getattr(existing_legend, 'legend_handles', []) or getattr(existing_legend, 'legendHandles', []))
        labels = [text.get_text() for text in existing_legend.get_texts()]

    if not handles:
        return None

    figure_legend = fig.legend(
        handles,
        labels,
        loc="upper right",
        bbox_to_anchor=(0.99, 0.975),
        bbox_transform=fig.transFigure,
    )
    fig.subplots_adjust(top=0.82)
    return figure_legend


def finalize_extended_chart_layout(fig, ax, *, legend=None, strategy=None):
    """Run a final artist-bounds-driven layout pass for extended charts."""

    if fig is None or ax is None:
        return

    strategy_bottom_margin = None
    if strategy and strategy.get('bottom_margin'):
        strategy_bottom_margin = float(strategy['bottom_margin'])
        fig.subplots_adjust(bottom=strategy_bottom_margin)

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    artists = []
    artists.extend(ax.get_xticklabels())
    artists.extend(ax.get_yticklabels())

    if ax.xaxis.label is not None:
        artists.append(ax.xaxis.label)
    if ax.yaxis.label is not None:
        artists.append(ax.yaxis.label)
    if ax.title is not None:
        artists.append(ax.title)

    legend_artist = legend
    if legend_artist is None and getattr(fig, 'legends', None):
        legend_artist = fig.legends[-1]
    if legend_artist is not None:
        artists.append(legend_artist)

    fig_w_px = max(1.0, fig.get_figwidth() * fig.dpi)
    fig_h_px = max(1.0, fig.get_figheight() * fig.dpi)

    left_px = 24.0
    right_px = 22.0
    top_px = 20.0
    bottom_px = 20.0

    for artist in artists:
        if artist is None or not getattr(artist, 'get_visible', lambda: True)():
            continue
        try:
            bbox = artist.get_window_extent(renderer=renderer)
        except Exception:
            continue
        left_px = max(left_px, max(0.0, -bbox.x0) + 8.0)
        right_px = max(right_px, max(0.0, bbox.x1 - fig_w_px) + 8.0)
        bottom_px = max(bottom_px, max(0.0, -bbox.y0) + 8.0)
        top_px = max(top_px, max(0.0, bbox.y1 - fig_h_px) + 8.0)

    proposed_left = min(0.22, max(0.08, left_px / fig_w_px))
    proposed_right = max(0.76, min(0.98, 1.0 - (right_px / fig_w_px)))
    proposed_bottom = min(0.36, max(0.14, bottom_px / fig_h_px))
    if strategy_bottom_margin is not None:
        proposed_bottom = max(proposed_bottom, strategy_bottom_margin)
    proposed_top = max(0.68, min(0.95, 1.0 - (top_px / fig_h_px)))

    if proposed_right <= proposed_left + 0.25:
        proposed_right = min(0.98, proposed_left + 0.25)
    if proposed_top <= proposed_bottom + 0.20:
        proposed_top = min(0.98, proposed_bottom + 0.20)

    fig.subplots_adjust(
        left=proposed_left,
        right=proposed_right,
        bottom=proposed_bottom,
        top=proposed_top,
    )


def build_wrapped_chart_title(title, *, width=42, max_lines=3):
    """Wrap long chart titles so figure-level legends do not overlap plot headers."""

    safe_title = str(title or '').strip()
    if not safe_title:
        return ''

    wrapped_lines = textwrap.wrap(
        safe_title,
        width=max(20, int(width)),
        break_long_words=False,
        break_on_hyphens=False,
    )
    if len(wrapped_lines) > max_lines:
        wrapped_lines = wrapped_lines[:max_lines]
        wrapped_lines[-1] = wrapped_lines[-1].rstrip(' .') + '…'
    return '\n'.join(wrapped_lines)

def render_violin(
    ax,
    values,
    labels,
    *,
    nom=None,
    lsl=None,
    usl=None,
    one_sided=None,
    epsilon=None,
    readability_scale=None,
    use_dynamic_offsets=True,
    show_annotation_legend=True,
):
    """Render violin plots and optional group-stat annotations on the provided axis."""

    if _HAS_SEABORN:
        positions = list(range(len(labels)))
        sns.violinplot(data=values, inner=None, cut=0, linewidth=0.9, color=SUMMARY_PLOT_PALETTE['distribution_base'], ax=ax)
        ax.set_xticks(positions)
    else:
        positions = list(range(1, len(labels) + 1))
        ax.violinplot(values, showmeans=False, showmedians=False, showextrema=False)
        ax.set_xticks(positions)
    ax.set_xticklabels(labels)
    if lsl is not None and usl is not None:
        render_tolerance_band(ax, nom, lsl, usl, one_sided=one_sided, orientation='horizontal')
        render_spec_reference_lines(ax, nom, lsl, usl, orientation='horizontal', include_nominal=False)

    style = annotate_violin_group_stats(
        ax,
        labels,
        values,
        positions,
        nom=nom,
        lsl=lsl,
        one_sided=one_sided,
        epsilon=epsilon,
        readability_scale=readability_scale,
        use_dynamic_offsets=use_dynamic_offsets,
    )
    if show_annotation_legend:
        add_violin_annotation_legend(
            ax,
            style,
            include_tolerance_refs=False,
        )


def render_scatter(ax, data=None, x=None, y=None):
    """Render a scatter plot from DataFrame columns on a matplotlib axis."""

    ax.scatter(data[x], data[y], color=SUMMARY_PLOT_PALETTE['distribution_foreground'], marker='.', s=18)


def render_scatter_numeric(ax, x_values, y_values):
    """Render a scatter plot from numeric coordinate arrays."""

    normalized_x = _normalize_plot_axis_values(list(x_values))
    normalized_y = _normalize_plot_axis_values(list(y_values))
    ax.scatter(normalized_x, normalized_y, color=SUMMARY_PLOT_PALETTE['distribution_foreground'], marker='.', s=18)


def render_histogram(ax, header_group, *, lsl=None, usl=None, group_column=None):
    """Render a histogram and density overlays for one measurement group."""

    normalized_meas = _normalize_plot_axis_values(list(header_group['MEAS']))
    histogram_values = pd.to_numeric(pd.Series(normalized_meas), errors='coerce').dropna().to_numpy(dtype=float)
    if histogram_values.size == 0:
        return {'is_grouped': False, 'group_labels': []}

    binning = resolve_histogram_bin_count(histogram_values)
    bin_count = int(binning['bin_count'])

    if _HAS_SEABORN:
        sns.histplot(
            x=histogram_values,
            bins=bin_count,
            stat='count',
            alpha=0.72,
            color=SUMMARY_PLOT_PALETTE['distribution_base'],
            edgecolor=(1.0, 1.0, 1.0, 0.72),
            linewidth=0.5,
            ax=ax,
        )
    else:
        ax.hist(
            histogram_values,
            bins=bin_count,
            density=False,
            alpha=0.72,
            color=SUMMARY_PLOT_PALETTE['distribution_base'],
            edgecolor=(1.0, 1.0, 1.0, 0.72),
            linewidth=0.5,
        )

    x_view = resolve_histogram_x_view(histogram_values, lsl=lsl, usl=usl)
    ax.set_xlim(x_view['x_min'], x_view['x_max'])
    enforce_minimum_histogram_bar_width(ax)
    lock_histogram_y_axis_to_bar_heights(ax)

    bin_widths = [
        float(patch.get_width())
        for patch in ax.patches
        if np.isfinite(patch.get_width()) and patch.get_width() > 0
    ]
    representative_bin_width = float(np.median(bin_widths)) if bin_widths else None
    count_scale_factor = None
    if representative_bin_width is not None and histogram_values.size > 0:
        count_scale_factor = float(histogram_values.size) * representative_bin_width

    return {
        'is_grouped': False,
        'group_labels': [],
        'count_scale_factor': count_scale_factor,
    }


def lock_histogram_y_axis_to_bar_heights(ax, *, top_padding_ratio=0.08):
    """Anchor histogram y-axis limits to rendered bar heights.

    Overlay curves (normal/KDE) are informational and should not drive y-axis
    scaling because bar counts are the primary chart reference.
    """

    if ax is None:
        return

    y_candidates = []
    for patch in ax.patches:
        height = patch.get_height()
        if np.isfinite(height) and height >= 0:
            y_candidates.append(float(height))

    for line in ax.lines:
        y_data = np.asarray(line.get_ydata(), dtype=float)
        finite_y = y_data[np.isfinite(y_data)]
        if finite_y.size > 0:
            y_candidates.append(float(np.max(finite_y)))

    if not y_candidates:
        return

    max_height = max(y_candidates)
    if max_height <= 0:
        max_height = 1.0

    top_padding = max_height * max(0.0, float(top_padding_ratio))
    ax.set_ylim(0.0, max_height + top_padding)


def enforce_minimum_histogram_bar_width(ax, *, min_width_fraction=0.015):
    """Widen ultra-thin histogram bars so at least one bar remains legible."""

    if ax is None:
        return

    x_limits = ax.get_xlim()
    x_span = x_limits[1] - x_limits[0]
    if not np.isfinite(x_span) or x_span <= 0:
        return

    minimum_width = x_span * max(0.0, float(min_width_fraction))
    if minimum_width <= 0:
        return

    for patch in ax.patches:
        bar_width = patch.get_width()
        if not np.isfinite(bar_width) or bar_width <= 0 or bar_width >= minimum_width:
            continue
        bar_center = patch.get_x() + (bar_width / 2.0)
        patch.set_width(minimum_width)
        patch.set_x(bar_center - (minimum_width / 2.0))


def render_iqr_boxplot(ax, values, labels):
    """Render a standard 1.5*IQR box plot used for outlier detection."""
    safe_values = values if isinstance(values, list) else []
    safe_labels = labels if isinstance(labels, list) else []

    normalized_values = []
    for group_values in safe_values:
        if isinstance(group_values, (list, tuple, np.ndarray, pd.Series)):
            group_list = _normalize_plot_axis_values(list(group_values))
            numeric_group = pd.to_numeric(pd.Series(group_list), errors='coerce').dropna().to_list()
            if numeric_group:
                normalized_values.append(numeric_group)

    if not normalized_values:
        return

    if not safe_labels:
        safe_labels = [f'Group {index + 1}' for index in range(len(normalized_values))]

    if len(safe_labels) != len(normalized_values):
        min_length = min(len(safe_labels), len(normalized_values))
        if min_length == 0:
            safe_labels = [f'Group {index + 1}' for index in range(len(normalized_values))]
        else:
            logger.warning(
                "IQR boxplot label/value length mismatch; applying deterministic truncation.",
                extra={'label_count': len(safe_labels), 'value_count': len(normalized_values)},
            )
            safe_labels = safe_labels[:min_length]
            normalized_values = normalized_values[:min_length]

    positions = list(range(1, len(normalized_values) + 1))
    boxplot_kwargs = {
        'whis': 1.5,
        'patch_artist': True,
        'boxprops': {'facecolor': SUMMARY_PLOT_PALETTE['distribution_base'], 'edgecolor': SUMMARY_PLOT_PALETTE['distribution_foreground'], 'linewidth': 0.9, 'alpha': 0.45},
        'medianprops': {'color': SUMMARY_PLOT_PALETTE['central_tendency'], 'linewidth': 1.1},
        'whiskerprops': {'color': SUMMARY_PLOT_PALETTE['distribution_foreground'], 'linewidth': 0.9},
        'capprops': {'color': SUMMARY_PLOT_PALETTE['distribution_foreground'], 'linewidth': 0.9},
        'flierprops': {'marker': 'o', 'markersize': 3, 'markerfacecolor': SUMMARY_PLOT_PALETTE['outlier'], 'markeredgecolor': SUMMARY_PLOT_PALETTE['outlier'], 'alpha': 0.9},
    }
    label_values = [str(label) for label in safe_labels]
    try:
        ax.boxplot(normalized_values, tick_labels=label_values, **boxplot_kwargs)
    except TypeError:
        ax.boxplot(normalized_values, labels=label_values, **boxplot_kwargs)
    ax.set_xticks(positions)
    ax.set_xticklabels([str(label) for label in safe_labels])


def build_iqr_legend_handles():
    """Build stable legend handles for the summary-sheet IQR boxplot."""
    return [
        Patch(
            facecolor=SUMMARY_PLOT_PALETTE['distribution_base'],
            edgecolor=SUMMARY_PLOT_PALETTE['distribution_foreground'],
            linewidth=0.9,
            alpha=0.45,
            label='IQR range (Q1-Q3)',
        ),
        Line2D(
            [0],
            [0],
            color=SUMMARY_PLOT_PALETTE['central_tendency'],
            linewidth=1.1,
            label='Median',
        ),
        Line2D(
            [0],
            [0],
            color=SUMMARY_PLOT_PALETTE['distribution_foreground'],
            linewidth=0.9,
            label='Whiskers (1.5 IQR rule)',
        ),
        Line2D(
            [0],
            [0],
            marker='o',
            linestyle='None',
            markersize=4,
            markerfacecolor=SUMMARY_PLOT_PALETTE['outlier'],
            markeredgecolor=SUMMARY_PLOT_PALETTE['outlier'],
            alpha=0.9,
            label='Outliers',
        ),
    ]


def add_iqr_boxplot_legend(ax, *, include_tolerance_refs=False):
    """Attach a compact, non-overlapping legend for summary-sheet sized images."""
    handles = build_iqr_legend_handles()
    if include_tolerance_refs:
        handles.extend(build_tolerance_reference_legend_handles())

    ax.legend(
        handles=handles,
        loc='upper left',
        bbox_to_anchor=(1.0, 1.0),
        fontsize=7,
        framealpha=0.9,
        facecolor='white',
        edgecolor=SUMMARY_PLOT_PALETTE['distribution_foreground'],
        borderaxespad=0.0,
        handlelength=1.5,
        labelspacing=0.25,
    )


def render_density_line(ax, x, p, *, color=None, alpha=1.0, linewidth=1.4, linestyle='-'):
    """Render a count-scaled reference/model line on the primary y-axis."""

    if ax is None:
        return None

    line_color = color or SUMMARY_PLOT_PALETTE['density_line']
    if _HAS_SEABORN:
        sns.lineplot(
            x=x,
            y=p,
            color=line_color,
            linewidth=linewidth,
            linestyle=linestyle,
            alpha=alpha,
            ax=ax,
        )
    else:
        ax.plot(x, p, color=line_color, linewidth=linewidth, linestyle=linestyle, alpha=alpha)

    return ax


def render_modeled_tail_shading(ax, distribution_fit_result, *, lsl=None, usl=None):
    """Shade count-scaled modeled tails beyond active specification limits."""

    selected_model_curve = (distribution_fit_result or {}).get('selected_model_pdf') or {}
    x_values = np.asarray(selected_model_curve.get('x', []), dtype=float)
    density_values = np.asarray(selected_model_curve.get('y', []), dtype=float)
    if x_values.size < 2 or density_values.size != x_values.size:
        return

    parsed_lsl = None
    parsed_usl = None
    try:
        if lsl is not None:
            parsed_lsl = float(lsl)
    except (TypeError, ValueError):
        parsed_lsl = None
    try:
        if usl is not None:
            parsed_usl = float(usl)
    except (TypeError, ValueError):
        parsed_usl = None

    for limit_value, mask in (
        (parsed_lsl, x_values <= parsed_lsl if parsed_lsl is not None else None),
        (parsed_usl, x_values >= parsed_usl if parsed_usl is not None else None),
    ):
        if limit_value is None or mask is None:
            continue
        if np.count_nonzero(mask) < 2:
            continue
        ax.fill_between(
            x_values[mask],
            density_values[mask],
            0.0,
            color=SUMMARY_PLOT_PALETTE['spec_limit'],
            alpha=0.12,
            linewidth=0.0,
            zorder=2,
        )


_EXTENDED_HISTOGRAM_PANEL_ROW_HEIGHT = 0.155
_EXTENDED_HISTOGRAM_TABLE_ROW_HEIGHT_SCALE = 3.15
_EXTENDED_HISTOGRAM_STATISTIC_COL_WIDTH_RATIO = 0.39
_UNIFIED_HISTOGRAM_LABEL_FRACTION = 0.44
_UNIFIED_HISTOGRAM_VALUE_FRACTION = 0.56


def style_histogram_stats_table(ax_table, table_data, *, capability_badge=None, capability_row_badges=None):
    """Apply semantic emphasis colors to the histogram summary table."""
    if ax_table is None:
        return

    cell_map = ax_table.get_celld()
    column_indexes = sorted({col for (row, col) in cell_map.keys() if row == 0})
    if not column_indexes:
        column_indexes = [0, 1]

    for col_index in column_indexes:
        cell = cell_map.get((0, col_index))
        if cell is None:
            continue
        cell.set_facecolor(SUMMARY_PLOT_PALETTE['table_header_bg'])
        cell.get_text().set_color(SUMMARY_PLOT_PALETTE['table_header_text'])

    normalized_rows = []
    for row in table_data:
        if len(row) >= 3:
            label, _label_part2, value = row[0], row[1], row[2]
        else:
            label, value = row[0], row[1]
        normalized_rows.append((label, value))

    cp_cpk_rows = {'Cp', 'Cpk', 'Cpk+', 'Cpu', 'Cpl'}
    for row_index, (label, value) in enumerate(normalized_rows, start=1):
        if capability_row_badges and label in capability_row_badges:
            _apply_table_row_badge(ax_table, row_index, capability_row_badges[label]['palette_key'])
            continue
        if capability_badge and label in cp_cpk_rows:
            _apply_table_row_badge(ax_table, row_index, capability_badge['palette_key'])
            continue

        if label not in EMPHASIS_TABLE_ROWS:
            continue
        for col_index in column_indexes:
            cell = cell_map.get((row_index, col_index))
            if cell is None:
                continue
            cell.set_facecolor(SUMMARY_PLOT_PALETTE['table_emphasis_bg'])
            cell.get_text().set_color(SUMMARY_PLOT_PALETTE['table_emphasis_text'])



def adjust_histogram_stats_table_geometry(
    ax_table,
    *,
    statistic_col_width_ratio=0.72,
    row_height_scale=1.12,
    explicit_row_heights=None,
):
    """Increase histogram stats-table readability via column and row geometry."""
    if ax_table is None:
        return

    table_cells = ax_table.get_celld()
    header_columns = sorted({col for (row, col) in table_cells.keys() if row == 0})
    has_three_columns = 2 in header_columns

    statistic_area_ratio = min(0.82, max(0.5, float(statistic_col_width_ratio)))
    label_col0_ratio = statistic_area_ratio * 0.78
    label_col1_ratio = statistic_area_ratio * 0.22
    value_ratio = 1.0 - statistic_area_ratio
    del row_height_scale
    border_linewidth = 0.45
    cell_padding = 0.12

    full_width_rows = set()
    if has_three_columns:
        full_width_rows = {
            row
            for row in sorted({row for (row, col) in table_cells.keys() if row > 0 and col == 0})
            if table_cells.get((row, 0)) is not None
            and table_cells[(row, 0)].get_visible()
            and table_cells.get((row, 1)) is not None
            and not table_cells[(row, 1)].get_visible()
            and table_cells.get((row, 2)) is not None
            and not table_cells[(row, 2)].get_visible()
        }

    for (row_index, col_index), cell in table_cells.items():
        if not cell.get_visible():
            continue

        if has_three_columns:
            if row_index in full_width_rows and col_index == 0:
                pass
            elif col_index == 0:
                cell.set_width(label_col0_ratio)
            elif col_index == 1:
                cell.set_width(label_col1_ratio)
            elif col_index == 2:
                cell.set_width(value_ratio)
                text = cell.get_text()
                text.set_ha('right')
                text.set_x(0.94)
        else:
            if col_index == 0:
                cell.set_width(statistic_area_ratio)
            elif col_index == 1:
                cell.set_width(value_ratio)
                text = cell.get_text()
                text.set_ha('right')
                text.set_x(0.94)

        cell.set_edgecolor(SUMMARY_PLOT_PALETTE['annotation_box_edge'])
        cell.set_linewidth(border_linewidth)
        cell.PAD = cell_padding

    if explicit_row_heights:
        apply_explicit_table_row_heights(
            ax_table,
            row_heights=list(explicit_row_heights),
            ncols=(3 if has_three_columns else 2),
        )


def apply_explicit_table_row_heights(table, *, row_heights, ncols):
    """Apply explicit heights to every table row/cell."""
    for row_index, row_height in enumerate(row_heights):
        for col_index in range(max(1, int(ncols))):
            cell = table.get_celld().get((row_index, col_index))
            if cell is None or not cell.get_visible():
                continue
            cell.set_height(float(row_height))


def _measure_text_extent(fig, renderer, text, *, fontsize, fontweight='normal'):
    """Measure text extents in display pixels for sizing-aware panel layout."""

    probe_kwargs = {
        'fontsize': fontsize,
        'fontweight': fontweight,
        'alpha': 0.0,
    }
    if _uses_symbol_font_fallback(text):
        probe_kwargs['fontfamily'] = 'DejaVu Sans'

    probe = fig.text(0.0, 0.0, str(text), **probe_kwargs)
    try:
        extent = probe.get_window_extent(renderer=renderer)
        return extent.width, extent.height
    finally:
        probe.remove()


def _wrap_table_value_text(value_text, *, width):
    """Wrap table values while preserving explicit line breaks."""

    text = str(value_text)
    if width <= 0:
        return text

    wrapped_lines = []
    for line in text.splitlines() or ['']:
        wrapped_lines.append(textwrap.fill(line, width=width) if line else '')
    return '\n'.join(wrapped_lines)


def render_panel_table(
    *,
    ax,
    fig,
    title,
    rows,
    rect,
    style_options=None,
):
    """Render a non-overlapping side panel table with dynamic width/height fitting.

    Returns metadata describing used bounds, overflow, deferred rows, and fallbacks.
    """

    options = dict(style_options or {})
    base_fontsize = float(options.get('fontsize', 8.0))
    min_fontsize = float(options.get('min_fontsize', 6.8))
    max_fontsize = float(options.get('max_fontsize', 9.0))
    fontsize = min(max(base_fontsize, min_fontsize), max_fontsize)

    min_label_fraction = float(options.get('min_label_fraction', 0.52))
    min_value_fraction = float(options.get('min_value_fraction', 0.22))
    header_fontweight = options.get('header_fontweight', 'bold')
    compact_label_mapping = dict(options.get('compact_label_mapping') or {})
    value_wrap_width = int(options.get('value_wrap_width', 0) or 0)
    cell_padding_points = float(options.get('cell_padding_points', 2.2))
    explicit_row_heights = options.get('explicit_row_heights')
    shared_row_metrics = options.get('shared_row_metrics')
    explicit_label_fraction = options.get('explicit_label_fraction')
    explicit_value_fraction = options.get('explicit_value_fraction')

    normalized_rows = []
    for row in rows or []:
        if len(row) >= 2:
            label_text = str(row[0])
            value_text = str(row[-1])
            if value_wrap_width > 0:
                value_text = _wrap_table_value_text(value_text, width=value_wrap_width)
            normalized_rows.append((label_text, value_text))

    # Ensure renderer-backed text metrics are current.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    ax_height_px = max(1.0, float(ax.bbox.height))
    available_height_px = max(1.0, rect['height'] * ax_height_px)
    cell_padding_px = cell_padding_points * (fig.dpi / 72.0)

    state_rows = list(normalized_rows)
    applied_fallbacks = []
    using_compact_labels = False

    def _measure_layout(candidate_rows, candidate_fontsize):
        label_header_w, header_h = _measure_text_extent(fig, renderer, title, fontsize=candidate_fontsize, fontweight=header_fontweight)
        value_header_w, _ = _measure_text_extent(fig, renderer, 'Value', fontsize=candidate_fontsize, fontweight=header_fontweight)
        line_h = _measure_text_extent(fig, renderer, 'Ag', fontsize=candidate_fontsize)[1]

        label_max = label_header_w
        value_max = value_header_w
        for label, value in candidate_rows:
            label_max = max(label_max, _measure_text_extent(fig, renderer, label, fontsize=candidate_fontsize)[0])
            value_max = max(value_max, _measure_text_extent(fig, renderer, value, fontsize=candidate_fontsize)[0])

        required_total_w = label_max + value_max + (4.0 * cell_padding_px)
        dynamic_label_fraction = (label_max + (2.0 * cell_padding_px)) / required_total_w if required_total_w > 0 else 0.5
        dynamic_value_fraction = (value_max + (2.0 * cell_padding_px)) / required_total_w if required_total_w > 0 else 0.5

        if explicit_label_fraction is not None and explicit_value_fraction is not None:
            label_fraction = max(0.0, float(explicit_label_fraction))
            value_fraction = max(0.0, float(explicit_value_fraction))
        else:
            label_fraction = max(min_label_fraction, dynamic_label_fraction)
            value_fraction = max(min_value_fraction, dynamic_value_fraction)
        total_fraction = label_fraction + value_fraction
        if total_fraction <= 0.0:
            label_fraction = 0.5
            value_fraction = 0.5
        elif total_fraction != 1.0:
            label_fraction /= total_fraction
            value_fraction /= total_fraction

        if shared_row_metrics:
            header_height_px = float(shared_row_metrics['header_row_height_px'])
            row_height_px = float(shared_row_metrics['base_row_height_px'])
            extra_line_height_px = float(shared_row_metrics['extra_line_height_px'])
        else:
            header_height_px = header_h + (2.0 * cell_padding_px)
            row_height_px = line_h + (2.0 * cell_padding_px)
            extra_line_height_px = row_height_px
        required_rows_height_px = 0.0
        for label, value in candidate_rows:
            line_count = resolve_table_row_line_count(label, value)
            required_rows_height_px += row_height_px + ((line_count - 1) * extra_line_height_px)
        required_height_px = header_height_px + required_rows_height_px

        return {
            'label_fraction': label_fraction,
            'value_fraction': value_fraction,
            'required_height_px': required_height_px,
            'row_height_px': row_height_px,
        }

    metrics = _measure_layout(state_rows, fontsize)

    if metrics['required_height_px'] > available_height_px and compact_label_mapping:
        compacted_rows = [(compact_label_mapping.get(label, label), value) for (label, value) in state_rows]
        compact_metrics = _measure_layout(compacted_rows, fontsize)
        if compact_metrics['required_height_px'] <= metrics['required_height_px']:
            state_rows = compacted_rows
            metrics = compact_metrics
            using_compact_labels = True
            applied_fallbacks.append('compact_label_mapping')

    while metrics['required_height_px'] > available_height_px and fontsize > min_fontsize:
        fontsize = max(min_fontsize, fontsize - 0.4)
        metrics = _measure_layout(state_rows, fontsize)
    if fontsize < base_fontsize:
        applied_fallbacks.append('reduced_fontsize')

    overflow_rows = []
    deferred_rows = []

    table = ax.table(
        cellText=state_rows,
        colLabels=[title, 'Value'],
        cellLoc='center',
        colWidths=[metrics['label_fraction'], metrics['value_fraction']],
        bbox=[rect['x'], rect['y'], rect['width'], rect['height']],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(fontsize)

    for (row_index, col_index), cell in table.get_celld().items():
        cell.PAD = max(cell.PAD, cell_padding_points / 10.0)
        txt = cell.get_text()
        if row_index == 0:
            txt.set_fontweight(header_fontweight)
            txt.set_fontsize(fontsize * 1.05)
        else:
            txt.set_fontsize(fontsize)
        if col_index == 0:
            txt.set_ha('left')
        else:
            txt.set_ha('right')
        txt.set_va('center')
        if _uses_symbol_font_fallback(txt.get_text()):
            txt.set_fontfamily('DejaVu Sans')

    row_heights = None
    if explicit_row_heights:
        row_heights = [float(v) for v in explicit_row_heights]
        apply_explicit_table_row_heights(table, row_heights=row_heights, ncols=2)

    return {
        'table': table,
        'used_bounds': dict(rect),
        'overflow': metrics['required_height_px'] > available_height_px,
        'overflow_rows': overflow_rows,
        'deferred_rows': deferred_rows,
        'rendered_rows': state_rows,
        'font_size': fontsize,
        'used_compact_labels': using_compact_labels,
        'fallbacks_applied': applied_fallbacks,
        'explicit_row_heights': row_heights,
    }


def render_panel_table_in_panel_axes(
    *,
    ax,
    title,
    rows,
    style_options=None,
    row_height=None,
    header_rows=1,
    pad_y=0.02,
    valign='top',
):
    """Render a side-panel table using panel-local axes coordinates.

    The table always fills the provided panel axes (`[0, 0, 1, 1]`).
    """

    panel_rect = {'x': 0.0, 'y': 0.0, 'width': 1.0, 'height': 1.0}
    del row_height
    fig = ax.figure
    fig.canvas.draw()
    row_metrics = resolve_histogram_dashboard_row_metrics(
        table_fontsize=float((style_options or {}).get('fontsize', 8.0)),
        dpi=float(fig.dpi),
    )
    value_wrap_width = int(((style_options or {}).get('value_wrap_width', 0) or 0))
    row_line_counts = []
    for label, value in (rows or []):
        label_text = str(label)
        value_text = str(value)
        if value_wrap_width > 0:
            value_text = _wrap_table_value_text(value_text, width=value_wrap_width)
        row_line_counts.append(resolve_table_row_line_count(label_text, value_text))
    row_heights = _build_table_row_heights(
        row_line_counts,
        header_row_height_px=row_metrics['header_row_height_px'],
        base_row_height_px=row_metrics['base_row_height_px'],
        extra_line_height_px=row_metrics['extra_line_height_px'],
        fig_height_px=float(ax.bbox.height),
    )
    content_height = sum(row_heights)
    inner_rect = _resolve_inner_table_rect(
        panel_rect,
        row_count=len(rows or []),
        row_height=content_height / max(1, len(row_heights)),
        header_rows=header_rows,
        pad_y=pad_y,
        valign=valign,
    )
    inner_rect['height'] = min(1.0, content_height)

    return render_panel_table(
        ax=ax,
        fig=ax.figure,
        title=title,
        rows=rows,
        rect=inner_rect,
        style_options={
            **(style_options or {}),
            'shared_row_metrics': row_metrics,
            'explicit_row_heights': row_heights,
        },
    )

def classify_capability_status(cp, cpk):
    """Classify capability readiness into scan-friendly quality tiers."""

    return _classify_capability_status(cp, cpk)


def classify_capability_value(value, *, label_prefix='Capability'):
    """Classify a single Cp/Cpk value for independent row highlighting."""

    return _classify_capability_value(value, label_prefix=label_prefix)


def classify_nok_severity(nok_pct):
    """Classify NOK ratio severity for chart title cueing."""

    return _classify_nok_severity(nok_pct)


def classify_normality_status(normality_status):
    """Map normality status to dedicated pastel normality palettes."""

    return _classify_normality_status(normality_status)


def build_summary_panel_subtitle(summary_stats):
    """Return compact panel subtitle text showing sample size and NOK share."""

    return _build_summary_panel_subtitle(summary_stats)


def _apply_table_row_badge(ax_table, row_index, palette_key):
    cell_map = ax_table.get_celld()
    column_indexes = sorted({col for (row, col) in cell_map.keys() if row == 0})
    if not column_indexes:
        column_indexes = [0, 1]
    for col_index in column_indexes:
        cell = cell_map.get((row_index, col_index))
        if cell is None:
            continue
        cell.set_facecolor(SUMMARY_PLOT_PALETTE[f'{palette_key}_bg'])
        border_style = STATUS_BORDER_STYLE_BY_PALETTE.get(palette_key, {})
        cell.set_edgecolor(SUMMARY_PLOT_PALETTE[f'{palette_key}_text'])
        cell.set_linestyle(border_style.get('linestyle', 'solid'))
        cell.set_linewidth(float(border_style.get('linewidth', 0.9)))
        cell.set_hatch('')
        text = cell.get_text()
        text.set_color(SUMMARY_PLOT_PALETTE[f'{palette_key}_text'])


def _merge_table_row_cells(ax_table, row_index, col_index=0, *, col_span, text=None, palette_key=None, height_scale=1.0):
    """Merge adjacent cells in one row into a single styled cell."""
    if col_span <= 1:
        return

    cell_map = ax_table.get_celld()
    primary_cell = cell_map.get((row_index, col_index))
    if primary_cell is None:
        return

    merged_width = primary_cell.get_width()
    for offset in range(1, col_span):
        sibling = cell_map.get((row_index, col_index + offset))
        if sibling is None:
            continue
        merged_width += sibling.get_width()
        if palette_key:
            sibling.set_facecolor(SUMMARY_PLOT_PALETTE[f'{palette_key}_bg'])
            sibling.get_text().set_color(SUMMARY_PLOT_PALETTE[f'{palette_key}_text'])
        sibling.set_visible(False)
        sibling.set_width(0)

    primary_cell.set_width(merged_width)
    primary_cell.set_height(primary_cell.get_height() * height_scale)

    primary_text = primary_cell.get_text()
    if text is not None:
        primary_text.set_text(text)

    if palette_key:
        primary_cell.set_facecolor(SUMMARY_PLOT_PALETTE[f'{palette_key}_bg'])
        primary_text.set_color(SUMMARY_PLOT_PALETTE[f'{palette_key}_text'])
        primary_text.set_linespacing(1.2)


def add_quality_title_badge(ax, label, palette_key, *, x=0.01, y=1.02):
    """Render a subtle colored quality badge near the chart title area."""
    prefix = STATUS_ICON_PREFIX_BY_PALETTE.get(palette_key)
    if prefix and label and not str(label).startswith((f'{prefix} ', '✓ ', '! ', '× ')):
        label = f'{prefix} {label}'
    border_style = STATUS_BORDER_STYLE_BY_PALETTE.get(palette_key, {})
    ax.text(
        x,
        y,
        label,
        transform=ax.transAxes,
        ha='left',
        va='bottom',
        fontsize=7.4,
        color=SUMMARY_PLOT_PALETTE[f'{palette_key}_text'],
        fontfamily='DejaVu Sans' if _uses_symbol_font_fallback(label) else None,
        bbox={
            'boxstyle': 'round,pad=0.16',
            'fc': SUMMARY_PLOT_PALETTE[f'{palette_key}_bg'],
            'ec': SUMMARY_PLOT_PALETTE[f'{palette_key}_text'],
            'linestyle': border_style.get('linestyle', 'solid'),
            'linewidth': float(border_style.get('linewidth', 0.9)),
            'hatch': border_style.get('hatch', ''),
            'alpha': 0.95,
        },
        zorder=6,
    )


class ExportDataThread(QThread):
    """Background worker thread that executes the full export pipeline.

    The thread queries report data, applies grouping/filters, writes Excel sheets,
    renders charts, and emits UI progress, status, and completion signals.
    """

    PROGRESS_STAGE_RANGES = {
        'preparing_query': (0, 10),
        'filtered_sheet_write': (10, 30),
        'measurement_sheets_charts': (30, 95),
        'finalize': (95, 100),
    }

    update_label = pyqtSignal(str)
    update_progress = pyqtSignal(int)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, export_request: ExportRequest):

        super().__init__()

        validated_request = validate_export_request(export_request)
        self.db_file = validated_request.paths.db_file
        self.excel_file = validated_request.paths.excel_file

        default_filter_query = """
            SELECT MEASUREMENTS.AX, MEASUREMENTS.NOM, MEASUREMENTS."+TOL", 
                MEASUREMENTS."-TOL", MEASUREMENTS.BONUS, MEASUREMENTS.MEAS, 
                MEASUREMENTS.DEV, MEASUREMENTS.OUTTOL, MEASUREMENTS.HEADER, REPORTS.REFERENCE, 
                REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE, REPORTS.SAMPLE_NUMBER 
            FROM MEASUREMENTS
            JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
            WHERE 1=1
            """
        self.filter_query = validated_request.filter_query or default_filter_query
        self.df_for_grouping = validated_request.grouping_df
        self.selected_export_type = validated_request.options.export_type
        self.export_target = validated_request.options.export_target
        self.backend_target = validated_request.options.backend_target
        self._active_backend = None
        self.selected_sorting_parameter = validated_request.options.sorting_parameter
        self.violin_plot_min_samplesize = validated_request.options.violin_plot_min_samplesize
        self.summary_plot_scale = validated_request.options.summary_plot_scale
        self.hide_ok_results = validated_request.options.hide_ok_results
        self.generate_summary_sheet = validated_request.options.generate_summary_sheet
        self.allow_non_essential_chart_skipping = validated_request.options.allow_non_essential_chart_skipping
        self.chart_worker_count = validated_request.options.chart_worker_count
        self.chart_worker_queue_size = validated_request.options.chart_worker_queue_size
        self.group_analysis_level = validated_request.options.group_analysis_level
        self.group_analysis_scope = validated_request.options.group_analysis_scope
        self.export_canceled = False
        self._cancel_signal_emitted = False
        self._prepared_grouping_df = None
        self.completion_metadata = {
            "local_xlsx_path": self.excel_file,
            "converted_url": None,
            "fallback_message": "",
            "conversion_warnings": [],
            "conversion_warning_details": [],
            "converted_tab_titles": [],
            "backend_diagnostics": {},
            "backend_diagnostics_lines": [],
        }
        self._exported_sheet_names = []
        self._exported_sheet_name_set = set()
        self._last_emitted_progress = -1
        self._stage_timings = {
            'summary_stat_retrieval': 0.0,
            'transform_grouping': 0.0,
            'sampling_plan_resolution': 0.0,
            'chart_payload_preparation': 0.0,
            'worksheet_write_planning': 0.0,
            'worksheet_writes': 0.0,
            'chart_rendering': 0.0,
        }
        self._chart_render_backend_counts = {'native': 0, 'matplotlib': 0}
        self._chart_render_backend_counts_by_type = {
            'distribution': {'native': 0, 'matplotlib': 0},
            'iqr': {'native': 0, 'matplotlib': 0},
            'histogram': {'native': 0, 'matplotlib': 0},
            'trend': {'native': 0, 'matplotlib': 0},
        }
        self._chart_render_timings_by_type = {
            'distribution': [],
            'iqr': [],
            'histogram': [],
            'trend': [],
        }
        self._optimization_toggles = {
            'chart_density_mode': 'full',
            'defer_non_essential_charts': False,
            'summary_sheet_minimum_charts': {'distribution', 'iqr', 'histogram', 'trend'},
            'enable_chart_multiprocessing': os.getenv('METROLIZA_EXPORT_CHART_MP', '').lower() in {'1', 'true', 'yes', 'on'} and os.name != 'nt',
        }
        self._chart_executor = None
        self._summary_prep_executor = None
        self._chart_renderer = build_chart_renderer()
        self._active_chart_images = []
        self._summary_sheet_failed = False
        self._summary_sheet_skip_warning_emitted = False
        self._db_connection = None
        self._snapshot_table_name = None
        self._active_export_query = self.filter_query
        self._cached_export_filtered_df = None
        self._sql_measurement_summary_cache = {}
        self._distribution_fit_memo = {}
        self._backend_diagnostic_summary = build_backend_diagnostic_summary()
        self.completion_metadata["backend_diagnostics"] = dict(self._backend_diagnostic_summary)
        self.completion_metadata["backend_diagnostics_lines"] = format_backend_diagnostic_lines(self._backend_diagnostic_summary)

    def _register_chart_image(self, payload: bytes):
        image_data = BytesIO(payload)
        image_data.seek(0)
        self._active_chart_images.append(image_data)
        return image_data

    def _cleanup_chart_images(self):
        self._active_chart_images.clear()

    def _ensure_chart_executor(self):
        if not self._optimization_toggles.get('enable_chart_multiprocessing'):
            return None
        if self._chart_executor is None:
            self._chart_executor = ProcessPoolExecutor(max_workers=self.chart_worker_count)
        return self._chart_executor

    def _shutdown_chart_executor(self):
        if self._chart_executor is None:
            return
        try:
            self._chart_executor.shutdown(wait=True)
        finally:
            self._chart_executor = None

    def _ensure_summary_prep_executor(self):
        if self._summary_prep_executor is None:
            self._summary_prep_executor = BoundedWorkerPool(
                max_workers=self.chart_worker_count,
                max_queue_size=self.chart_worker_queue_size,
            )
        return self._summary_prep_executor

    def _shutdown_summary_prep_executor(self):
        if self._summary_prep_executor is None:
            return
        try:
            self._summary_prep_executor.shutdown(wait=True)
        finally:
            self._summary_prep_executor = None


    def _prepare_export_snapshot(self):
        if self._db_connection is None:
            self._active_export_query = self.filter_query
            self._cached_export_filtered_df = None
            return

        snapshot_table_name = f'_export_snapshot_{int(time.time() * 1000)}_{id(self)}'
        create_snapshot_query = (
            f'CREATE TEMP TABLE "{snapshot_table_name}" AS '
            f'SELECT * FROM ({self.filter_query}) AS export_scope'
        )
        try:
            with self._db_connection:
                self._db_connection.execute(create_snapshot_query)
        except Exception:
            logger.warning(
                'Export snapshot materialization failed; falling back to live query scope.',
                exc_info=True,
            )
            self._snapshot_table_name = None
            self._active_export_query = self.filter_query
            self._cached_export_filtered_df = None
            return

        self._snapshot_table_name = snapshot_table_name
        self._active_export_query = f'SELECT * FROM "{snapshot_table_name}"'
        self._cached_export_filtered_df = None

    def _cleanup_export_snapshot(self):
        if self._db_connection is None or not self._snapshot_table_name:
            self._active_export_query = self.filter_query
            self._snapshot_table_name = None
            self._cached_export_filtered_df = None
            return

        try:
            with self._db_connection:
                self._db_connection.execute(f'DROP TABLE IF EXISTS "{self._snapshot_table_name}"')
        except sqlite3.ProgrammingError:
            logger.debug(
                'Skipping export snapshot cleanup because database connection is already closed.',
                exc_info=True,
            )
        finally:
            self._snapshot_table_name = None
            self._active_export_query = self.filter_query
            self._cached_export_filtered_df = None
            self._sql_measurement_summary_cache.clear()

    def _iter_reference_partitions(self):
        partition_values = fetch_partition_values(
            self.db_file,
            self._active_export_query,
            partition_column='REFERENCE',
            connection=self._db_connection,
        )
        for partition_value in partition_values:
            partition_df = load_measurement_export_partition_dataframe(
                self.db_file,
                self._active_export_query,
                partition_value,
                partition_column='REFERENCE',
                connection=self._db_connection,
            )
            yield partition_value, partition_df

    def _build_export_filtered_dataframe(self):
        if self._cached_export_filtered_df is None:
            self._cached_export_filtered_df = read_sql_dataframe(self.db_file, self._active_export_query, connection=self._db_connection)
        return self._cached_export_filtered_df

    def _record_stage_timing(self, stage_name, elapsed):
        if stage_name in self._stage_timings:
            self._stage_timings[stage_name] += max(0.0, float(elapsed))

    def _record_chart_render_timing(self, chart_type, elapsed, *, backend='matplotlib'):
        elapsed_s = max(0.0, float(elapsed))
        self._record_stage_timing('chart_rendering', elapsed_s)
        if chart_type in self._chart_render_timings_by_type:
            self._chart_render_timings_by_type[chart_type].append(elapsed_s)
        if backend in self._chart_render_backend_counts:
            self._chart_render_backend_counts[backend] += 1
        if chart_type in self._chart_render_backend_counts_by_type and backend in self._chart_render_backend_counts_by_type[chart_type]:
            self._chart_render_backend_counts_by_type[chart_type][backend] += 1

    def build_export_observability_summary(self, *, high_header_threshold=64):
        """Build structured telemetry for one export run.

        Args:
            high_header_threshold (int): Distinct-header threshold used to flag
                high-cardinality partitions.

        Returns:
            dict[str, object]: Observability payload containing:
                - ``stage_timings_s``: chart prep/render/write stage totals.
                - ``chart_backend_distribution``: native/matplotlib counts and rates.
                - ``per_chart_type_timing_medians_s``: median render times per
                  summary chart type.
                - ``high_header_cardinality_scenario``: threshold, max headers,
                  detection flag, and stage timing snapshot (when available).
        """
        chart_backend_total = sum(self._chart_render_backend_counts.values())
        chart_backend_distribution = {
            'counts': dict(self._chart_render_backend_counts),
            'rates': {
                backend: (count / chart_backend_total) if chart_backend_total else 0.0
                for backend, count in self._chart_render_backend_counts.items()
            },
        }
        per_chart_type_timing_medians_s = {
            chart_type: (
                float(statistics.median(samples))
                if samples
                else 0.0
            )
            for chart_type, samples in self._chart_render_timings_by_type.items()
        }
        per_chart_type_runtime_totals_s = {
            chart_type: float(sum(samples))
            for chart_type, samples in self._chart_render_timings_by_type.items()
        }
        per_chart_type_backend_distribution = {}
        for chart_type, backend_counts in self._chart_render_backend_counts_by_type.items():
            total = sum(int(v) for v in backend_counts.values())
            per_chart_type_backend_distribution[chart_type] = {
                'counts': {k: int(v) for k, v in backend_counts.items()},
                'rates': {
                    backend: (int(count) / total) if total else 0.0
                    for backend, count in backend_counts.items()
                },
            }
        high_header_cardinality = {
            'threshold': int(high_header_threshold),
            'max_headers_per_partition': 0,
            'detected': False,
            'timings_s': {},
        }
        try:
            header_counts = fetch_partition_header_counts(
                self.db_file,
                self._active_export_query,
                connection=self._db_connection,
            )
            max_headers = max((int(v) for v in header_counts.values()), default=0)
            high_header_cardinality = {
                'threshold': int(high_header_threshold),
                'max_headers_per_partition': max_headers,
                'detected': max_headers >= int(high_header_threshold),
                'timings_s': {
                    'chart_payload_preparation': float(self._stage_timings.get('chart_payload_preparation', 0.0)),
                    'chart_rendering': float(self._stage_timings.get('chart_rendering', 0.0)),
                    'worksheet_writes': float(self._stage_timings.get('worksheet_writes', 0.0)),
                },
            }
        except Exception:
            logger.debug("Unable to resolve high-header-cardinality summary metrics.", exc_info=True)

        return {
            'stage_timings_s': {
                'chart_payload_preparation': float(self._stage_timings.get('chart_payload_preparation', 0.0)),
                'chart_rendering': float(self._stage_timings.get('chart_rendering', 0.0)),
                'worksheet_writes': float(self._stage_timings.get('worksheet_writes', 0.0)),
            },
            'chart_backend_distribution': chart_backend_distribution,
            'per_chart_type_timing_medians_s': per_chart_type_timing_medians_s,
            'per_chart_type_runtime_totals_s': per_chart_type_runtime_totals_s,
            'per_chart_type_backend_distribution': per_chart_type_backend_distribution,
            'high_header_cardinality_scenario': high_header_cardinality,
            'backend_diagnostics': dict(self._backend_diagnostic_summary),
        }

    def _update_completion_chart_telemetry(self):
        """Persist per-chart timing/backend counters into completion metadata."""
        summary = self.build_export_observability_summary()
        self.completion_metadata['chart_observability_summary'] = summary
        self.completion_metadata['chart_native_usage_by_type'] = {
            chart_type: int(data.get('counts', {}).get('native', 0))
            for chart_type, data in summary.get('per_chart_type_backend_distribution', {}).items()
        }
        self.completion_metadata['chart_runtime_seconds_by_type'] = {
            chart_type: float(value)
            for chart_type, value in summary.get('per_chart_type_runtime_totals_s', {}).items()
        }

    def _apply_bottleneck_optimizations(self):
        total = sum(self._stage_timings.values())
        if total <= 0.0:
            return

        chart_share = self._stage_timings['chart_rendering'] / total
        if chart_share >= 0.65:
            self._optimization_toggles['chart_density_mode'] = 'reduced'
            self._optimization_toggles['defer_non_essential_charts'] = True
            if self.allow_non_essential_chart_skipping:
                self._optimization_toggles['summary_sheet_minimum_charts'] = {'distribution', 'iqr', 'histogram'}
            else:
                self._optimization_toggles['summary_sheet_minimum_charts'] = {'distribution', 'iqr', 'histogram', 'trend'}
        elif chart_share >= 0.45:
            self._optimization_toggles['chart_density_mode'] = 'reduced'

    def _chart_sample_limit(self):
        policy = resolve_chart_sampling_policy(density_mode=self._optimization_toggles['chart_density_mode'])
        return policy.distribution_limit

    def _summary_chart_required(self, chart_name):
        required_charts = self._optimization_toggles.get('summary_sheet_minimum_charts', set())
        return chart_name in required_charts

    def _lookup_sql_measurement_summary(self, *, reference, header, ax, usl, lsl):
        if reference is not None:
            reference_cache = self._sql_measurement_summary_cache.get(reference)
            if reference_cache is None:
                reference_cache = fetch_sql_measurement_summaries(
                    self.db_file,
                    self._active_export_query,
                    reference=reference,
                    connection=self._db_connection,
                )
                self._sql_measurement_summary_cache[reference] = reference_cache
            cached_summary = reference_cache.get((reference, header, ax))
            if cached_summary is not None:
                return cached_summary

        return fetch_sql_measurement_summary(
            self.db_file,
            self._active_export_query,
            reference=reference,
            header=header,
            ax=ax,
            usl=usl,
            lsl=lsl,
            connection=self._db_connection,
        )

    def _save_summary_chart(self, fig, mode='workbook', *, chart_type=None, native_payload=None):
        """Persist summary-sheet charts with a workbook-friendly rendering policy."""
        def _normalize_render_result(raw_result, *, default_backend='matplotlib'):
            if hasattr(raw_result, 'png_bytes'):
                png_bytes = raw_result.png_bytes
                backend = getattr(raw_result, 'backend', default_backend)
            else:
                png_bytes = raw_result
                backend = default_backend
            return type("RenderResult", (), {"png_bytes": png_bytes, "backend": backend})()

        if chart_type == 'histogram' and native_payload is not None:
            render_result = self._chart_renderer.render_histogram_png(
                native_payload,
                fallback_fig=fig,
                mode=mode,
            )
            return _normalize_render_result(render_result, default_backend='native')

        if chart_type == 'distribution' and native_payload is not None and hasattr(self._chart_renderer, 'render_distribution_png'):
            render_result = self._chart_renderer.render_distribution_png(
                native_payload,
                fallback_fig=fig,
                mode=mode,
            )
            return _normalize_render_result(render_result, default_backend='native')

        render_result = self._chart_renderer.render_figure_png(fig, mode=mode, chart_type=chart_type)
        return _normalize_render_result(render_result, default_backend='matplotlib')

    @staticmethod
    def _resolve_chart_cell_span(
        fig,
        *,
        px_per_col=110.0,
        px_per_row=20.0,
        padding_cols=0,
        padding_rows=1,
        export_dpi=150.0,
    ):
        """Translate rendered figure size into worksheet cell spans."""

        if fig is None:
            return {'col_span': 1, 'row_span': 1}
        resolved_export_dpi = max(1.0, float(export_dpi))
        width_px = max(1.0, fig.get_figwidth() * resolved_export_dpi)
        height_px = max(1.0, fig.get_figheight() * resolved_export_dpi)
        return {
            'col_span': max(1, int(np.ceil(width_px / float(px_per_col))) + int(padding_cols)),
            'row_span': max(1, int(np.ceil(height_px / float(px_per_row))) + int(padding_rows)),
        }

    @staticmethod
    def _insert_summary_image(worksheet, slot, image_data):
        """Insert summary image and guard against missing worksheet backends."""

        worksheet.insert_image(slot['row'], slot['col'], '', {'image_data': image_data})

    def _build_iqr_plot_payload(self, labels, values, sampled_group, *, grouping_active=False):
        strategy_labels = build_summary_panel_labels(labels or ['All'], grouping_active=grouping_active)
        boxplot_labels = strategy_labels
        boxplot_values = values if values else [list(sampled_group['MEAS'])]

        if len(boxplot_labels) != len(boxplot_values):
            if sampled_group is not None and 'MEAS' in sampled_group:
                logger.warning(
                    "IQR payload labels/values mismatch detected; rebuilding fallback payload.",
                    extra={'label_count': len(boxplot_labels), 'value_count': len(boxplot_values)},
                )
                boxplot_labels = ['All']
                boxplot_values = [list(sampled_group['MEAS'])]
            else:
                min_length = min(len(boxplot_labels), len(boxplot_values))
                logger.warning(
                    "IQR payload labels/values mismatch detected; applying deterministic truncation.",
                    extra={'label_count': len(boxplot_labels), 'value_count': len(boxplot_values), 'selected_length': min_length},
                )
                boxplot_labels = boxplot_labels[:min_length]
                boxplot_values = boxplot_values[:min_length]

        if self._optimization_toggles['chart_density_mode'] != 'reduced':
            return boxplot_labels, boxplot_values

        max_groups = 24
        if len(boxplot_labels) <= max_groups:
            return boxplot_labels, boxplot_values

        stride = max(1, int(np.ceil(len(boxplot_labels) / max_groups)))
        return boxplot_labels[::stride], boxplot_values[::stride]

    @staticmethod
    def _compute_group_sample_counts(sampled_group, grouping_key):
        return _compute_group_sample_counts_compute(sampled_group, grouping_key)

    @staticmethod
    def _append_group_sample_counts(labels, sample_counts):
        return _append_group_sample_counts_compute(labels, sample_counts)

    @staticmethod
    def _downsample_frame(df, sample_limit):
        return deterministic_downsample_frame(df, sample_limit)

    @staticmethod
    def _clamp_progress(value):
        return max(0, min(100, int(round(value))))

    def _emit_progress(self, value):
        clamped_value = self._clamp_progress(value)
        progress_value = max(clamped_value, self._last_emitted_progress)
        if progress_value == self._last_emitted_progress:
            return
        self._last_emitted_progress = progress_value
        self.update_progress.emit(progress_value)

    def _emit_stage_progress(self, stage_name, fraction=1.0):
        start, end = self.PROGRESS_STAGE_RANGES[stage_name]
        safe_fraction = max(0.0, min(1.0, float(fraction)))
        stage_progress = start + ((end - start) * safe_fraction)
        self._emit_progress(stage_progress)

    def _record_exported_sheet_name(self, sheet_name):
        if isinstance(sheet_name, str) and sheet_name.strip():
            if sheet_name in self._exported_sheet_name_set:
                return
            self._exported_sheet_name_set.add(sheet_name)
            self._exported_sheet_names.append(sheet_name)

    def _build_expected_sheet_names(self):
        if isinstance(self._exported_sheet_names, list):
            return list(self._exported_sheet_names)
        # Backward-compatible fallback for tests that patch internals directly.
        return sorted(self._exported_sheet_names)

    @staticmethod
    def _format_elapsed_or_eta(seconds):
        safe_seconds = max(0, int(seconds))
        minutes, remaining_seconds = divmod(safe_seconds, 60)
        hours, remaining_minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{remaining_minutes:02d}:{remaining_seconds:02d}"
        return f"{remaining_minutes:d}:{remaining_seconds:02d}"

    def _build_measurement_label(self, *, ref_index, total_references, completed_header_units, total_header_units, start_time):
        stage_line = "Building measurement sheets..."
        if total_header_units <= 0:
            detail_line = f"Ref {ref_index}/{total_references}, Headers remaining 0"
            return build_three_line_status(stage_line, detail_line, "ETA --")

        remaining_headers = max(0, total_header_units - completed_header_units)
        detail_line = (
            f"Ref {ref_index}/{total_references}, "
            f"Headers remaining {remaining_headers}/{total_header_units}"
        )

        elapsed_seconds = max(0.0, time.perf_counter() - start_time)
        if completed_header_units < 5 or elapsed_seconds < 2.0:
            return build_three_line_status(stage_line, detail_line, "ETA --")

        headers_per_second = completed_header_units / elapsed_seconds if elapsed_seconds > 0 else 0.0
        if headers_per_second <= 0:
            return build_three_line_status(stage_line, detail_line, "ETA --")

        eta_seconds = remaining_headers / headers_per_second
        elapsed_display = self._format_elapsed_or_eta(elapsed_seconds)
        eta_display = self._format_elapsed_or_eta(eta_seconds)
        eta_line = f"{elapsed_display} elapsed, ETA {eta_display}"
        return build_three_line_status(stage_line, detail_line, eta_line)

    @property
    def prepared_grouping_df(self):
        """Handle `prepared_grouping_df` for `ExportDataThread`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        if self._prepared_grouping_df is None:
            self._prepared_grouping_df = self._prepare_grouping_df()
        return self._prepared_grouping_df

    @staticmethod
    def _is_sample_sort_mode(sort_mode):
        return sort_mode in {"sample", "sample #", "sample number", "part #", "part number"}

    @staticmethod
    def _ensure_sample_number_column(df):
        if 'SAMPLE_NUMBER' in df.columns:
            return df

        normalized_df = df.copy()
        normalized_df['SAMPLE_NUMBER'] = [str(index + 1) for index in range(len(normalized_df))]
        return normalized_df

    @staticmethod
    def _build_violin_payload(header_group, group_column, min_samplesize):
        """Backward-compatible wrapper around the canonical vectorized builder."""

        return build_violin_payload_vectorized(
            header_group,
            group_column,
            min_samplesize=min_samplesize,
        )

    @staticmethod
    def _build_summary_scatter_payload(header_group, x_column, *, grouping_active=False):
        scatter_frame = header_group.dropna(subset=['MEAS']).copy()
        if scatter_frame.empty:
            return np.array([]), np.array([]), []

        raw_labels = scatter_frame[x_column].tolist()
        strategy_labels = build_summary_panel_labels(raw_labels, grouping_active=grouping_active)

        normalized_y = _normalize_plot_axis_values(list(scatter_frame['MEAS']))
        y_numeric = pd.to_numeric(pd.Series(normalized_y), errors='coerce').to_numpy(dtype=float)

        normalized_x = _normalize_plot_axis_values(raw_labels)
        has_datetime_values = any(isinstance(value, (pd.Timestamp, np.datetime64)) or hasattr(value, 'year') for value in normalized_x)
        if has_datetime_values and all(not isinstance(value, str) for value in normalized_x):
            datetime_series = pd.to_datetime(pd.Series(normalized_x), errors='coerce')
            if datetime_series.notna().all():
                x_values = datetime_series.dt.to_pydatetime()
            else:
                x_values = np.arange(len(scatter_frame), dtype=float)
        else:
            x_numeric = pd.to_numeric(pd.Series(normalized_x), errors='coerce').to_numpy(dtype=float)
            if np.isnan(x_numeric).any():
                x_values = np.arange(len(scatter_frame), dtype=float)
            else:
                x_values = x_numeric

        return x_values, y_numeric, strategy_labels

    @staticmethod
    def _build_grouped_summary_scatter_payload(header_group, x_column, *, grouping_active=False):
        """Build grouped trend points and labels, including per-group sample counts.

        Rationale:
            Grouped trend panels aggregate to one point per category to avoid
            overplotting and to make between-group central tendency easier to
            compare.

        Fallback behavior:
            Returns empty arrays/lists when no finite grouped measurements are
            available after filtering NaNs.
        """
        scatter_frame = header_group.dropna(subset=['MEAS', x_column]).copy()
        if scatter_frame.empty:
            return np.array([]), np.array([]), []

        grouped_measurements = scatter_frame.groupby(x_column, sort=False)['MEAS'].mean()
        if grouped_measurements.empty:
            return np.array([]), np.array([]), []

        raw_labels = list(grouped_measurements.index)
        if grouping_active:
            group_sizes = scatter_frame.groupby(x_column, sort=False)['MEAS'].size()
            raw_labels = [f"{label} (n={int(group_sizes.loc[label])})" for label in raw_labels]
        strategy_labels = build_summary_panel_labels(raw_labels, grouping_active=grouping_active)
        normalized_y = _normalize_plot_axis_values(list(grouped_measurements.values))
        y_numeric = pd.to_numeric(pd.Series(normalized_y), errors='coerce').to_numpy(dtype=float)
        x_values = np.arange(len(grouped_measurements), dtype=float)
        return x_values, y_numeric, strategy_labels

    def _sort_header_group(self, header_group):
        sort_mode = self.selected_sorting_parameter.strip().lower()
        sorted_group = header_group.copy()

        if self._is_sample_sort_mode(sort_mode):
            sample_numeric = pd.to_numeric(sorted_group['SAMPLE_NUMBER'], errors='coerce')
            if sample_numeric.notna().any():
                sorted_group = sorted_group.assign(_sample_numeric=sample_numeric)
                sorted_group = sorted_group.sort_values(by=['_sample_numeric', 'SAMPLE_NUMBER'], kind='mergesort')
                sorted_group = sorted_group.drop(columns=['_sample_numeric'])
            else:
                sorted_group = sorted_group.sort_values(by='SAMPLE_NUMBER', kind='mergesort')
        else:
            date_series = pd.to_datetime(sorted_group['DATE'], errors='coerce')
            if date_series.notna().any():
                sorted_group = sorted_group.assign(_date_sort=date_series)
                sorted_group = sorted_group.sort_values(by=['_date_sort', 'SAMPLE_NUMBER'], kind='mergesort')
                sorted_group = sorted_group.drop(columns=['_date_sort'])
            else:
                sorted_group = sorted_group.sort_values(by=['DATE', 'SAMPLE_NUMBER'], kind='mergesort')

        return sorted_group

    def _prepare_grouping_df(self):
        return _prepare_grouping_dataframe(self.df_for_grouping)

    def _warn_duplicate_group_assignments(self, grouping_df, merge_keys):
        duplicated_mask = grouping_df.duplicated(subset=merge_keys, keep=False)
        duplicate_count = int(duplicated_mask.sum())
        if duplicate_count == 0:
            return

        message = (
            f"Detected {duplicate_count} grouping assignment rows with duplicate merge key(s) "
            f"{merge_keys}. Keeping the latest assignment per key."
        )
        logger.warning(message)
        self.update_label.emit(build_three_line_status("Building measurement sheets...", "Grouping data contains duplicate keys; using latest assignment.", "ETA --"))

    def _apply_group_assignments(self, header_group, grouping_df, *, group_analysis_mode=False, fallback_group_label=None):
        merged_group, grouping_applied, merge_keys, duplicate_count = _apply_group_assignments(
            header_group,
            grouping_df,
            group_analysis_mode=group_analysis_mode,
            fallback_group_label=fallback_group_label,
        )
        if grouping_applied and duplicate_count:
            self._warn_duplicate_group_assignments(grouping_df, merge_keys)
        return merged_group, grouping_applied

    @staticmethod
    def _add_group_key(df):
        return _add_group_key(df)

    @staticmethod
    def _keys_have_usable_values(df, keys):
        return _keys_have_usable_values(df, keys)

    @staticmethod
    def _resolve_group_merge_keys(header_group, grouping_df):
        return _resolve_group_merge_keys(header_group, grouping_df)

    def stop_exporting(self):
        """Handle `stop_exporting` for `ExportDataThread`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        self.export_canceled = True

    def _check_canceled(self):
        if self.export_canceled:
            if not self._cancel_signal_emitted:
                self.update_label.emit(build_three_line_status("Export canceled.", "No further work will be processed.", "ETA --"))
                self._log_export_stage("Export cancellation observed", stage="canceled", cancel_flag=True)
                self.canceled.emit()
                self._cancel_signal_emitted = True
            return True
        return False

    def run_export_pipeline(self, excel_writer):
        """Handle `run_export_pipeline` for `ExportDataThread`.

        Args:
            excel_writer (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        # Stage order is deliberate: measurement sheets create workbook context
        # consumed by filtered export and progress reporting.
        return run_export_steps(
            [
                lambda: (
                    self.update_label.emit(build_three_line_status("Building measurement sheets...", "Preparing measurement worksheets", "ETA --")),
                    self._emit_stage_progress('measurement_sheets_charts', 0.0),
                    self.add_measurements_horizontal_sheet(excel_writer),
                    self._emit_stage_progress('measurement_sheets_charts', 1.0),
                ),
                lambda: (
                    self.update_label.emit(build_three_line_status("Exporting filtered data...", "Writing MEASUREMENTS worksheet", "ETA --")),
                    self._emit_stage_progress('preparing_query', 1.0),
                    self._emit_stage_progress('filtered_sheet_write', 0.0),
                    self.export_filtered_data(excel_writer),
                    self._emit_stage_progress('filtered_sheet_write', 1.0),
                ),
                lambda: (
                    self.update_label.emit(build_three_line_status("Building group analysis...", "Writing Group Analysis worksheet", "ETA --")),
                    self._write_group_analysis_outputs(excel_writer),
                ),
            ],
            should_cancel=self._check_canceled,
        )

    def get_export_backend(self):
        """Handle `get_export_backend` for `ExportDataThread`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        target_to_backend = {
            'excel_xlsx': ExcelExportBackend(),
            'google_sheets_drive_convert': ExcelExportBackend(),
        }
        return target_to_backend[self.export_target]

    def _emit_google_stage(self, stage, detail=""):
        stage_message = build_google_stage_message(stage, detail=detail)
        if not stage_message:
            return
        self.update_label.emit(build_three_line_status(stage_message, "Exporting data...", "ETA --"))

    def _build_export_context(self, *, stage, fallback_reason=""):
        return _build_export_context_payload(
            export_target=self.export_target,
            output_path=self.excel_file,
            stage=stage,
            fallback_reason=fallback_reason,
        )

    def _log_export_stage(self, message, *, stage, level="info", fallback_reason="", **extra):
        _log_export_stage_message(
            logger,
            message,
            export_target=self.export_target,
            output_path=self.excel_file,
            stage=stage,
            level=level,
            fallback_reason=fallback_reason,
            **extra,
        )

    def _log_google_issue(self, context, *, fallback_message="", warnings=None, error=None):
        _log_google_issue_message(
            logger,
            context,
            output_path=self.excel_file,
            export_target=self.export_target,
            fallback_message=fallback_message,
            warnings=warnings,
            error=error,
        )

    def run(self):
        """Handle `run` for `ExportDataThread`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            if self._check_canceled():
                return

            self._ensure_chart_executor()
            self._ensure_summary_prep_executor()

            with sqlite_connection_scope(self.db_file) as connection:
                self._db_connection = connection
                self._prepare_export_snapshot()

                self._emit_stage_progress('preparing_query', 0.0)
                self.update_label.emit(build_three_line_status("Preparing export...", "Loading data and configuring stages", "ETA --"))
                self._log_export_stage("Export started", stage="started")
                logger.info(
                    "Backend diagnostic summary: %s",
                    "; ".join(self.completion_metadata.get("backend_diagnostics_lines", [])),
                )
                if self.export_target == "google_sheets_drive_convert":
                    self._emit_google_stage("generating")

                backend = self.get_export_backend()
                self._active_backend = backend
                completed = backend.run(self)
                if not completed:
                    return

            if self.export_target == "google_sheets_drive_convert":
                stage_attempts = {
                    "uploading": 0,
                    "converting": 0,
                    "validating": 0,
                }
                stage_attempt_totals = {}

                def _log_google_conversion_stage(stage_name):
                    stage_attempts[stage_name] += 1
                    attempt_index = stage_attempts[stage_name]
                    attempt_total = stage_attempt_totals.get(stage_name)
                    stage_message = "Google conversion stage"
                    if attempt_total and attempt_total > 1:
                        stage_message = f"Google conversion stage (attempt {attempt_index}/{attempt_total})"
                    self._log_export_stage(stage_message, stage=stage_name)

                def _stage_callback(stage_message):
                    if stage_message == "uploading":
                        self._emit_google_stage("uploading")
                        _log_google_conversion_stage("uploading")
                        return
                    if stage_message == "converting":
                        self._emit_google_stage("converting")
                        _log_google_conversion_stage("converting")
                        return
                    if stage_message == "validating":
                        self._emit_google_stage("validating")
                        _log_google_conversion_stage("validating")
                        return
                    if stage_message.startswith("uploading retry"):
                        retry_match = re.match(r"^uploading retry\s+(\d+)/(\d+),\s+elapsed\s+\d{2}:\d{2}", stage_message)
                        if retry_match:
                            try:
                                stage_attempt_totals["uploading"] = int(retry_match.group(2))
                            except ValueError:
                                self._log_export_stage(
                                    "Unable to parse Google upload retry attempt total",
                                    stage="uploading_retry_parse",
                                    level="warning",
                                    raw_message=stage_message,
                                )
                        self._emit_google_stage("uploading", detail=stage_message)
                        self._log_export_stage("Google conversion upload retry", stage="uploading_retry", level="warning")

                conversion = upload_and_convert_workbook(
                    self.excel_file,
                    expected_sheet_names=self._build_expected_sheet_names(),
                    status_callback=_stage_callback,
                    should_cancel=lambda: self.export_canceled,
                )

                self.completion_metadata.update(build_google_conversion_metadata(conversion))
                self._log_export_stage(
                    "Google conversion returned",
                    stage="google_conversion",
                    fallback_reason=conversion.fallback_message,
                    **build_google_conversion_log_extra(
                        file_ref=conversion.web_url or conversion.file_id,
                        outcome="warnings" if conversion.warnings else "success",
                    ),
                )
                for warning in conversion.warnings:
                    self.update_label.emit(build_three_line_status(f"Warning: {warning}", "Exporting data...", "ETA --"))

                if conversion.warnings:
                    self._log_google_issue(
                        "conversion completed with warnings",
                        fallback_message=conversion.fallback_message,
                        warnings=conversion.warnings,
                    )
                    self._emit_google_stage("fallback", detail=conversion.fallback_message)
                else:
                    self._emit_google_stage("completed", detail=conversion.web_url)
                    self._log_export_stage(
                        "Google conversion completed",
                        stage="completed",
                        **build_google_conversion_log_extra(
                            file_ref=conversion.web_url,
                            outcome="success",
                        ),
                    )

            self._emit_stage_progress('finalize', 1.0)
            self._update_completion_chart_telemetry()
            self.update_label.emit(build_three_line_status("Export completed successfully.", "Workbook and metadata finalized", "ETA 0:00"))
            self._log_export_stage("Export completed successfully", stage="completed")
            self.finished.emit()
            QCoreApplication.processEvents()
        except GoogleDriveCanceledError:
            self.export_canceled = True
            self._check_canceled()
            return
        except GoogleDriveExportError as e:
            if self.export_target == "google_sheets_drive_convert":
                self.completion_metadata.update(build_google_fallback_metadata(excel_file=self.excel_file, error=e))
                self._emit_google_stage("fallback", detail=self.completion_metadata["fallback_message"])
                self.update_label.emit(build_three_line_status(f"Warning: {e}", "Exporting data...", "ETA --"))
                self._update_completion_chart_telemetry()
                self.update_label.emit(build_three_line_status("Export completed successfully.", "Workbook and metadata finalized", "ETA 0:00"))
                self._log_export_stage("Export completed with local fallback after Google conversion failure", stage="fallback", level="warning", fallback_reason=self.completion_metadata["fallback_message"])
                self.finished.emit()
                QCoreApplication.processEvents()
                self._log_google_issue(
                    "conversion failed and fell back to local xlsx",
                    fallback_message=self.completion_metadata["fallback_message"],
                    warnings=self.completion_metadata.get("conversion_warnings", []),
                    error=e,
                )
                if isinstance(e, GoogleDriveAuthError):
                    return
                return
            self.log_and_exit(e)
        except Exception as e:
            self.update_label.emit(
                build_three_line_status(
                    "Export failed during local workbook generation.",
                    "Export aborted before cloud conversion.",
                    "ETA --",
                )
            )
            self._log_export_stage(
                "Export failed during local workbook generation",
                stage="local_export_failed",
                level="error",
            )
            self.log_and_exit(e)
        finally:
            self._cleanup_export_snapshot()
            self._shutdown_chart_executor()
            self._shutdown_summary_prep_executor()
            self._cleanup_chart_images()
            self._db_connection = None

    def add_measurements_horizontal_sheet(self, excel_writer):
        """Handle `add_measurements_horizontal_sheet` for `ExportDataThread`.

        Args:
            excel_writer (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            partition_header_counts = fetch_partition_header_counts(
                self.db_file,
                self._active_export_query,
                partition_column='REFERENCE',
                connection=self._db_connection,
            )
            total_references = len(partition_header_counts)
            total_header_units = sum(partition_header_counts.values())
            completed_header_units = 0
            measurement_stage_start = time.perf_counter()
            label_emit_every_headers = 10
            label_emit_min_interval_seconds = 0.4
            last_label_emit_time = 0.0
            last_label_emit_header_count = 0
            backend = self._active_backend or self.get_export_backend()
            workbook = backend.get_workbook(excel_writer)
            used_sheet_names = backend.list_sheet_names(excel_writer)

            formats = create_measurement_formats(workbook)
            column_width = 12

            for ref_index, (ref, ref_group) in enumerate(self._iter_reference_partitions(), start=1):
                if self._check_canceled():
                    return

                # Each measurement block consumes 5 worksheet columns in the
                # exported layout (limits/stats/data). Keep the pre-format
                # range aligned with the actual generated columns so widths and
                # centering stay consistent for all populated blocks.
                header_block_count = len(ref_group['HEADER - AX'].unique())
                max_col = max((header_block_count * 5) - 1, 0)

                self.update_label.emit(
                    self._build_measurement_label(
                        ref_index=ref_index,
                        total_references=total_references,
                        completed_header_units=completed_header_units,
                        total_header_units=total_header_units,
                        start_time=measurement_stage_start,
                    )
                )

                col = 0
                safe_ref_sheet_name = unique_sheet_name(ref, used_sheet_names)
                worksheet = workbook.add_worksheet(safe_ref_sheet_name)
                self._record_exported_sheet_name(safe_ref_sheet_name)
                summary_worksheet = None
                if self.generate_summary_sheet:
                    summary_sheet_name = unique_sheet_name(f"{safe_ref_sheet_name}_summary", used_sheet_names)
                    summary_worksheet = workbook.add_worksheet(summary_sheet_name)
                    self._record_exported_sheet_name(summary_sheet_name)

                worksheet.set_column(0, max_col, column_width, cell_format=formats['default'])

                header_groups = ref_group.groupby('HEADER - AX', as_index=False)
                header_count = ref_group['HEADER - AX'].nunique(dropna=False)
                optimization_cache = {}
                timing_enabled = os.getenv('METROLIZA_EXPORT_TIMING', '').lower() in {'1', 'true', 'yes', 'on'}
                build_bundle_elapsed = 0.0
                chart_insert_elapsed = 0.0
                precompute_start = time.perf_counter()
                precomputed_header_entries = []
                for (header, header_group) in header_groups:
                    if self._check_canceled():
                        return

                    header_group = self._sort_header_group(header_group)
                    base_col = len(precomputed_header_entries) * 5
                    build_bundle_start = time.perf_counter()
                    write_bundle = _build_measurement_write_bundle_cached(
                        header,
                        header_group,
                        base_col,
                        cache=optimization_cache,
                    )
                    build_bundle_elapsed += time.perf_counter() - build_bundle_start
                    precomputed_header_entries.append((header, header_group, write_bundle))
                self._record_stage_timing('transform_grouping', time.perf_counter() - precompute_start)

                for (header, header_group, write_bundle) in precomputed_header_entries:
                    if self._check_canceled():
                        return

                    base_col = col
                    header_plan = write_bundle['header_plan']
                    write_start = time.perf_counter()
                    measurement_plan = write_measurement_block(worksheet, write_bundle, formats, base_col=base_col)

                    col += 5
                    header_col_end = col - 1
                    worksheet.set_column(header_col_end, header_col_end, None, cell_format=formats['border'])
                    self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)

                    chart_insert_start = time.perf_counter()
                    insert_measurement_chart(
                        workbook,
                        worksheet,
                        chart_type=self.selected_export_type,
                        header=header,
                        sheet_name=safe_ref_sheet_name,
                        measurement_plan=measurement_plan,
                        chart_anchor_col=col - 5,
                        cache=optimization_cache,
                    )

                    chart_insert_time = time.perf_counter() - chart_insert_start
                    if timing_enabled:
                        chart_insert_elapsed += chart_insert_time
                    self._record_stage_timing('chart_rendering', chart_insert_time)

                    if self._check_canceled():
                        return

                    if self.generate_summary_sheet:
                        if self._summary_sheet_failed:
                            if not self._summary_sheet_skip_warning_emitted:
                                self.update_label.emit(
                                    build_three_line_status(
                                        "Warning: summary charts skipped after earlier error.",
                                        "Continuing export without summary panel rendering",
                                        "ETA --",
                                    )
                                )
                                self._summary_sheet_skip_warning_emitted = True
                        else:
                            self.summary_sheet_fill(summary_worksheet, header, header_group, col)
                        if self._check_canceled():
                            return

                    self._apply_bottleneck_optimizations()

                    if self.hide_ok_results:
                        hide_columns = all_measurements_within_limits(header_group['MEAS'], header_plan['lsl'], header_plan['usl'])
                        if hide_columns:
                            worksheet.set_column(col - 3, col - 1, 0)

                    completed_header_units += 1
                    if total_header_units > 0:
                        self._emit_stage_progress(
                            'measurement_sheets_charts',
                            completed_header_units / total_header_units,
                        )

                    now = time.perf_counter()
                    should_emit_progress_label = (
                        completed_header_units == total_header_units
                        or completed_header_units - last_label_emit_header_count >= label_emit_every_headers
                        or (now - last_label_emit_time) >= label_emit_min_interval_seconds
                    )
                    if should_emit_progress_label:
                        self.update_label.emit(
                            self._build_measurement_label(
                                ref_index=ref_index,
                                total_references=total_references,
                                completed_header_units=completed_header_units,
                                total_header_units=total_header_units,
                                start_time=measurement_stage_start,
                            )
                        )
                        last_label_emit_time = now
                        last_label_emit_header_count = completed_header_units

                if timing_enabled:
                    logger.debug(
                        'Export timing [ref=%s]: bundle_build=%.6fs chart_insert=%.6fs headers=%d',
                        ref,
                        build_bundle_elapsed,
                        chart_insert_elapsed,
                        header_count,
                    )
                    dominant_stage = max(self._stage_timings, key=self._stage_timings.get)
                    logger.debug(
                        "Export stage totals [ref=%s]: timings=%s dominant_stage=%s dominant_elapsed=%.3fs toggles=%s",
                        ref,
                        self._stage_timings,
                        dominant_stage,
                        self._stage_timings.get(dominant_stage, 0.0),
                        self._optimization_toggles,
                    )
                    if self._stage_timings['chart_rendering'] > (self._stage_timings['transform_grouping'] * 2) and self._stage_timings['chart_rendering'] > self._stage_timings['worksheet_writes']:
                        logger.info(
                            "Export bottleneck analysis [ref=%s]: chart rendering dominates; remaining pure-math kernels are not currently dominant, so native code is not recommended yet.",
                            ref,
                        )

                worksheet.freeze_panes(7, 0)

            # Temporarily disabled for this RC run; resume in a future release cycle.
            # self._write_group_comparison_sheet(workbook, used_sheet_names)

            if total_references == 0 or total_header_units == 0:
                self._emit_stage_progress('measurement_sheets_charts', 1.0)
        except Exception as e:
            self.log_and_exit(e)
            raise

    def _write_group_analysis_message_sheet(self, worksheet, message):
        from modules.group_analysis_writer import (
            GROUP_ANALYSIS_MANUAL_GITHUB_URL,
            GROUP_ANALYSIS_MANUAL_PDF_GITHUB_URL,
        )

        worksheet.write(0, 0, 'Group Analysis')
        worksheet.write(1, 0, str(message or 'Group Analysis skipped.'))
        worksheet.write(3, 0, 'Markdown guide (GitHub)')
        worksheet.write_url(
            3,
            1,
            GROUP_ANALYSIS_MANUAL_GITHUB_URL,
            string='Open Markdown manual',
            tip='Open the plain-English Group Analysis guide in the GitHub repository.',
        )
        worksheet.write(4, 0, 'Printable companion (local PDF)')
        worksheet.write_url(
            4,
            1,
            GROUP_ANALYSIS_MANUAL_PDF_GITHUB_URL,
            string='Open local PDF companion',
            tip='Open the printable Group Analysis PDF companion in the GitHub repository.',
        )

    @staticmethod
    def _render_group_analysis_plot_asset(metric_row, plot_key):
        """Build an in-memory chart asset for Group Analysis worksheet insertion."""
        chart_payload = metric_row.get('chart_payload') if isinstance(metric_row, dict) else None
        if not isinstance(chart_payload, dict):
            return {}

        groups = chart_payload.get('groups') or []
        if not groups:
            return {}

        grouped_entries = []
        for entry in groups:
            label = str(entry.get('group') or '')
            values = pd.to_numeric(pd.Series(entry.get('values') or []), errors='coerce').to_numpy(dtype=float)
            finite_values = values[np.isfinite(values)]
            grouped_entries.append((label, finite_values))

        filtered_entries = [(label, values) for (label, values) in grouped_entries if values.size > 0]
        if not filtered_entries:
            return {}

        group_labels = [label for (label, _) in filtered_entries]
        grouped_values = [values for (_, values) in filtered_entries]

        spec_limits = chart_payload.get('spec_limits') or {}
        fig, ax = plt.subplots(figsize=(6.2, 3.2))
        try:
            if plot_key == 'violin':
                if _HAS_SEABORN:
                    sns.violinplot(data=grouped_values, inner='quartile', cut=0, linewidth=0.9, color=SUMMARY_PLOT_PALETTE['distribution_base'], ax=ax)
                    ax.set_xticks(range(len(group_labels)))
                    ax.set_xticklabels(group_labels)
                else:
                    positions = range(1, len(group_labels) + 1)
                    ax.violinplot(grouped_values, showmeans=False, showmedians=True, showextrema=False, positions=positions)
                    ax.set_xticks(list(positions))
                    ax.set_xticklabels(group_labels)

                nominal_value = spec_limits.get('nominal')
                lsl_value = spec_limits.get('lsl')
                usl_value = spec_limits.get('usl')
                render_spec_reference_lines(
                    ax,
                    nominal_value,
                    lsl_value,
                    usl_value,
                    orientation='horizontal',
                    include_nominal=nominal_value is not None,
                )

                annotation_transform = mtransforms.blended_transform_factory(ax.transAxes, ax.transData)
                annotation_specs = (
                    ('USL', usl_value, SUMMARY_PLOT_PALETTE['spec_limit'], (6, 8)),
                    ('Nominal', nominal_value, SUMMARY_PLOT_PALETTE['annotation_emphasis'], (6, 0)),
                    ('LSL', lsl_value, SUMMARY_PLOT_PALETTE['spec_limit'], (6, -8)),
                )
                annotation_box = {
                    'boxstyle': 'round,pad=0.16',
                    'fc': 'white',
                    'ec': SUMMARY_PLOT_PALETTE['annotation_box_edge'],
                    'alpha': 0.82,
                    'linewidth': 0.6,
                }
                for label, limit_value, color, offset in annotation_specs:
                    if limit_value is None:
                        continue
                    ax.annotate(
                        f"{label}={float(limit_value):.3f}",
                        xy=(1.0, float(limit_value)),
                        xycoords=annotation_transform,
                        textcoords='offset points',
                        xytext=offset,
                        ha='left',
                        va='center',
                        color=color,
                        fontsize=7.0,
                        bbox=annotation_box,
                        clip_on=False,
                    )
                ax.set_title(f"{metric_row.get('metric')} - Violin")
            elif plot_key == 'histogram':
                all_values = np.concatenate(grouped_values)
                bin_edges = np.histogram_bin_edges(all_values, bins='auto')
                histogram_palette = [
                    SUMMARY_PLOT_PALETTE['distribution_base'],
                    SUMMARY_PLOT_PALETTE['distribution_foreground'],
                    SUMMARY_PLOT_PALETTE['density_line'],
                    SUMMARY_PLOT_PALETTE['spec_limit'],
                    SUMMARY_PLOT_PALETTE['sigma_band'],
                ]
                for index, (label, values) in enumerate(zip(group_labels, grouped_values)):
                    ax.hist(
                        values,
                        bins=bin_edges,
                        edgecolor='black',
                        alpha=0.42,
                        color=histogram_palette[index % len(histogram_palette)],
                        label=label,
                    )
                ax.legend(loc='upper left', frameon=True, fontsize=7.0)

                for limit_key, style in (
                    ('lsl', {'linestyle': '--', 'color': '#B45309'}),
                    ('nominal', {'linestyle': ':', 'color': '#0F766E'}),
                    ('usl', {'linestyle': '--', 'color': '#B45309'}),
                ):
                    limit_value = spec_limits.get(limit_key)
                    if limit_value is not None:
                        ax.axvline(float(limit_value), linewidth=1.0, alpha=0.9, **style)

                ax.set_title(f"{metric_row.get('metric')} - Histogram")
            else:
                return {}

            ax.grid(axis='y', alpha=0.25)
            fig.tight_layout()
            image_data = BytesIO()
            fig.savefig(image_data, format='png', dpi=120)
            image_data.seek(0)
            return {'image_data': image_data, 'row_span': 16}
        except Exception:
            logger.debug('Failed to render group-analysis %s plot for %r', plot_key, metric_row.get('metric'), exc_info=True)
            return {}
        finally:
            plt.close(fig)

    def _build_group_analysis_plot_assets(self, payload, *, mode):
        """Prepare optional chart assets keyed by metric for worksheet insertion."""
        if str(mode or '').strip().lower() != 'standard':
            return {'metrics': {}}

        metrics_assets = {}
        for metric_row in payload.get('metric_rows', []):
            metric_name = metric_row.get('metric')
            if not metric_name:
                continue
            eligibility = metric_row.get('plot_eligibility') or {}
            per_metric_assets = {}
            for plot_key in ('violin', 'histogram'):
                plot_meta = eligibility.get(plot_key) or {}
                if bool(plot_meta.get('eligible')):
                    per_metric_assets[plot_key] = self._render_group_analysis_plot_asset(metric_row, plot_key)
                else:
                    per_metric_assets[plot_key] = {}
            metrics_assets[metric_name] = per_metric_assets

        return {'metrics': metrics_assets}

    def _write_group_analysis_outputs(self, excel_writer):
        mode = str(self.group_analysis_level or 'off').strip().lower()
        if mode == 'off':
            return

        if mode not in {'light', 'standard'}:
            logger.warning('Unknown group analysis level %r; skipping Group Analysis output.', mode)
            return

        backend = self._active_backend or self.get_export_backend()
        workbook = backend.get_workbook(excel_writer)
        used_sheet_names = backend.list_sheet_names(excel_writer)

        grouped_export_df = self._build_export_filtered_dataframe()
        grouped_export_df = self._ensure_sample_number_column(grouped_export_df)
        grouped_export_df, _ = self._apply_group_assignments(
            grouped_export_df,
            self.prepared_grouping_df,
            group_analysis_mode=True,
            fallback_group_label='POPULATION',
        )

        requested_scope = str(self.group_analysis_scope or 'auto').strip().lower()
        payload = build_group_analysis_payload(
            grouped_export_df,
            requested_scope=requested_scope,
            analysis_level=mode,
            alias_db_path=self.db_file,
        )

        group_sheet_name = unique_sheet_name('Group Analysis', used_sheet_names)
        group_worksheet = workbook.add_worksheet(group_sheet_name)
        self._record_exported_sheet_name(group_sheet_name)

        readiness = payload.get('readiness') or {}
        skip_reason = readiness.get('skip_reason') or payload.get('skip_reason') or {}
        skip_code = str(skip_reason.get('code') or '')
        if skip_code in {
            'forced_single_reference_scope_mismatch',
            'forced_multi_reference_scope_mismatch',
        }:
            short_message = str(skip_reason.get('message') or 'Group Analysis skipped.')
            self._write_group_analysis_message_sheet(group_worksheet, short_message)
        else:
            plot_assets = self._build_group_analysis_plot_assets(payload, mode=mode)
            write_group_analysis_sheet(group_worksheet, payload, plot_assets=plot_assets)

        if _internal_group_analysis_diagnostics_enabled():
            diagnostics_sheet_name = unique_sheet_name('Diagnostics', used_sheet_names)
            diagnostics_worksheet = workbook.add_worksheet(diagnostics_sheet_name)
            self._record_exported_sheet_name(diagnostics_sheet_name)
            # Internal/debug-only worksheet for payload verification. Normal exports
            # intentionally keep diagnostics folded into the user-facing Group Analysis
            # content instead of adding a separate worksheet.
            _write_internal_group_analysis_diagnostics_sheet(diagnostics_worksheet, payload['diagnostics'])

    def export_filtered_data(self, excel_writer):
        """Handle `export_filtered_data` for `ExportDataThread`.

        Args:
            excel_writer (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            if self._check_canceled():
                return
            export_df = self._build_export_filtered_dataframe()
            self.write_data_to_excel(export_df, "MEASUREMENTS", excel_writer)
        except Exception as e:
            self.log_and_exit(e)
            raise

    def write_data_to_excel(self, df, table_name, excel_writer):
        """Handle `write_data_to_excel` for `ExportDataThread`.

        Args:
            df (object): Method input value.
            table_name (object): Method input value.
            excel_writer (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            if self._check_canceled():
                return
            backend = self._active_backend or self.get_export_backend()
            safe_table_name = unique_sheet_name(table_name, backend.list_sheet_names(excel_writer))
            backend.write_dataframe(excel_writer, df, safe_table_name)
            self._record_exported_sheet_name(safe_table_name)
            worksheet = backend.get_worksheet(excel_writer, safe_table_name)

            worksheet.autofilter(0, 0, df.shape[0], df.shape[1] - 1)
            worksheet.freeze_panes(1, 0)
            for i, column in enumerate(df.columns):
                if self._check_canceled():
                    return
                column_width = self.calculate_column_width(df[column])
                worksheet.set_column(i, i, column_width)
        except Exception as e:
            self.log_and_exit(e)

    def calculate_column_width(self, data):
        """Handle `calculate_column_width` for `ExportDataThread`.

        Args:
            data (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            if data.empty:
                return 12  # Return a default width 12 if the data is empty

            # Vectorized string-length calculation for improved performance on large exports.
            column_width = data.astype(str).str.len().max()
            column_width = min(column_width, 40)
            column_width = max(column_width, 12)
            return column_width
        except Exception as e:
            self.log_and_exit(e)
    
    def summary_sheet_fill(self, summary_worksheet, header, header_group, col):
        """Handle `summary_sheet_fill` for `ExportDataThread`.

        Args:
            summary_worksheet (object): Method input value.
            header (object): Method input value.
            header_group (object): Method input value.
            col (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            if self._check_canceled():
                return

            header_group = self._ensure_sample_number_column(header_group)

            summary_start = time.perf_counter()
            limits = resolve_nominal_and_limits(header_group)
            nom = limits['nom']
            USL = limits['usl']
            LSL = limits['lsl']
            reference_value = header_group['REFERENCE'].iloc[0] if 'REFERENCE' in header_group.columns and not header_group.empty else None
            header_value = header_group['HEADER'].iloc[0] if 'HEADER' in header_group.columns and not header_group.empty else None
            axis_value = header_group['AX'].iloc[0] if 'AX' in header_group.columns and not header_group.empty else None
            sql_summary = None
            if reference_value is not None and header_value is not None and axis_value is not None:
                sql_summary = self._lookup_sql_measurement_summary(
                    reference=reference_value,
                    header=header_value,
                    ax=axis_value,
                    usl=USL,
                    lsl=LSL,
                )
            summary_stats = _retrieve_summary_statistics_compute(
                header_group,
                sql_summary=sql_summary,
                nom=nom,
                usl=USL,
                lsl=LSL,
            )
            average = summary_stats['average']
            self._record_stage_timing('summary_stat_retrieval', time.perf_counter() - summary_start)

            grouping_start = time.perf_counter()
            grouping_df = self.prepared_grouping_df
            header_group, grouping_applied = self._apply_group_assignments(header_group, grouping_df)
            distribution_key = 'GROUP' if grouping_applied else 'SAMPLE_NUMBER'
            scatter_key = distribution_key
            normalized_group = _normalize_summary_group_frame_compute(header_group, grouping_key=distribution_key)
            self._record_stage_timing('transform_grouping', time.perf_counter() - grouping_start)

            sampling_start = time.perf_counter()
            sampling_policy = resolve_chart_sampling_policy(density_mode=self._optimization_toggles['chart_density_mode'])
            sampling_context = _resolve_sampling_context_compute(
                normalized_group,
                grouping_applied=grouping_applied,
                sampling_policy=sampling_policy,
                violin_plot_min_samplesize=self.violin_plot_min_samplesize,
            )
            sampled_distribution_group = sampling_context['sampled_frames']['distribution']
            sampled_iqr_group = sampling_context['sampled_frames']['iqr']
            sampled_histogram_group = sampling_context['sampled_frames']['histogram']
            sampled_trend_group = sampling_context['sampled_frames']['trend']
            self._record_stage_timing('sampling_plan_resolution', time.perf_counter() - sampling_start)

            chart_prep_start = time.perf_counter()
            chart_mp_enabled = self._chart_executor is not None and len(normalized_group) >= 2500
            precomputed_distribution_fit = None
            precomputed_trend_payload = sampling_context['trend_payload']['payload']
            if chart_mp_enabled:
                try:
                    distribution_fit_future = self._chart_executor.submit(
                        fit_measurement_distribution,
                        sampling_context['histogram_payload']['measurements'],
                        lsl=LSL,
                        usl=USL,
                        nom=nom,
                        point_count=40 if self._optimization_toggles['chart_density_mode'] == 'reduced' else 100,
                        include_kde_reference=self._optimization_toggles['chart_density_mode'] != 'reduced',
                    )
                    trend_future = self._chart_executor.submit(
                        build_trend_plot_payload,
                        sampled_trend_group,
                        grouping_active=grouping_applied,
                        label_column=distribution_key,
                    )
                    precomputed_distribution_fit = distribution_fit_future.result()
                    precomputed_trend_payload = trend_future.result()
                except Exception:
                    precomputed_distribution_fit = None

            distribution_labels = sampling_context['distribution_payload']['labels']
            distribution_values = sampling_context['distribution_payload']['values']
            can_render_violin = sampling_context['distribution_payload']['can_render_violin']
            iqr_labels = sampling_context['iqr_payload']['labels']
            iqr_values = sampling_context['iqr_payload']['values']

            prep_executor = self._summary_prep_executor
            if prep_executor is not None:
                try:
                    distribution_future = prep_executor.submit(
                        build_violin_payload_vectorized,
                        sampled_distribution_group,
                        distribution_key,
                        self.violin_plot_min_samplesize,
                    )
                    iqr_future = prep_executor.submit(
                        build_violin_payload_vectorized,
                        sampled_iqr_group,
                        distribution_key,
                        self.violin_plot_min_samplesize,
                    )
                    distribution_labels, distribution_values, can_render_violin = distribution_future.result()
                    iqr_labels, iqr_values, _ = iqr_future.result()
                    sampling_context['distribution_payload'] = {
                        'labels': distribution_labels,
                        'values': distribution_values,
                        'can_render_violin': can_render_violin,
                    }
                    sampling_context['iqr_payload'] = {
                        'labels': iqr_labels,
                        'values': iqr_values,
                    }
                except Exception:
                    logger.debug(
                        "Summary prep executor failed; falling back to in-process payload generation.",
                        exc_info=True,
                    )

            chart_payloads = _prepare_summary_chart_payloads_compute(
                header=header,
                grouping_applied=grouping_applied,
                sampling_context=sampling_context,
                summary_stats=summary_stats,
            )
            histogram_table_payload = chart_payloads['histogram']['histogram_table_payload']
            summary_table_composition = chart_payloads['composition']
            capability_badge = summary_table_composition['capability_badge']
            histogram_row_badges = summary_table_composition['histogram_row_badges']
            panel_subtitle = summary_table_composition['panel_subtitle']
            distribution_labels = chart_payloads['distribution']['labels']
            distribution_values = chart_payloads['distribution']['values']
            can_render_violin = chart_payloads['distribution']['can_render_violin']
            iqr_labels = chart_payloads['iqr']['labels']
            iqr_values = chart_payloads['iqr']['values']
            trend_payload = precomputed_trend_payload or chart_payloads['trend']
            self._record_stage_timing('chart_payload_preparation', time.perf_counter() - chart_prep_start)

            label_positions = None
            x_values = None
            y_values = None
            distribution_x_axis_label = 'Group' if grouping_applied else 'Sample #'
            distribution_title = chart_payloads['distribution']['title']
            if not can_render_violin:
                x_values, y_values, distribution_labels = self._build_grouped_summary_scatter_payload(
                    sampled_distribution_group,
                    scatter_key,
                    grouping_active=grouping_applied,
                )
                label_positions = list(x_values)

            annotation_strategy = chart_payloads['annotation_strategy']
            force_sparse_x_labels = annotation_strategy['label_mode'] == 'sparse'
            use_dynamic_annotation_offsets = annotation_strategy['annotation_mode'] == 'dynamic'
            show_violin_annotation_legend = annotation_strategy['show_violin_legend']

            write_plan_start = time.perf_counter()
            worksheet_plan = _build_summary_worksheet_plan_compute(
                header=header,
                col=col,
                panel_subtitle=panel_subtitle,
            )
            header_cell = worksheet_plan['header_cell']
            default_image_slots = worksheet_plan['image_slots']
            distribution_overflow_cols = 0
            self._record_stage_timing('worksheet_write_planning', time.perf_counter() - write_plan_start)

            def _reserve_summary_image_slot(chart_name, fig):
                nonlocal distribution_overflow_cols

                default_slot = dict(default_image_slots.get(chart_name, default_image_slots['distribution']))
                if chart_name == 'distribution':
                    span = self._resolve_chart_cell_span(fig)
                    distribution_end_col = int(default_slot['col']) + int(span.get('col_span', 1))
                    default_iqr_col = int(default_image_slots.get('iqr', default_slot)['col'])
                    distribution_overflow_cols = max(0, distribution_end_col - default_iqr_col)
                    return default_slot

                if chart_name == 'iqr':
                    return {
                        'row': default_slot['row'],
                        'col': int(default_slot['col']) + int(distribution_overflow_cols),
                    }

                return default_slot

            write_start = time.perf_counter()
            summary_worksheet.write(header_cell['row'], header_cell['col'], header_cell['value'])
            summary_worksheet.write(header_cell['row'], header_cell['col'] + 1, worksheet_plan['subtitle_value'])
            self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)

            if self._summary_chart_required('distribution'):
                try:
                    apply_summary_plot_theme()
                    chart_start = time.perf_counter()

                    categorical_strategy = prepare_categorical_x_axis(distribution_labels)
                    fig, ax = plt.subplots(figsize=(categorical_strategy['recommended_fig_width'], 4))
                    if can_render_violin:
                        render_violin(
                            ax,
                            distribution_values,
                            distribution_labels,
                            nom=nom,
                            lsl=LSL,
                            usl=USL,
                            one_sided=is_one_sided_geometric_tolerance(nom, LSL),
                            readability_scale=self.summary_plot_scale,
                            use_dynamic_offsets=use_dynamic_annotation_offsets,
                            show_annotation_legend=show_violin_annotation_legend,
                        )
                    else:
                        render_scatter_numeric(ax, x_values, y_values)
                        if LSL is not None and USL is not None:
                            render_tolerance_band(
                                ax,
                                nom,
                                LSL,
                                USL,
                                one_sided=is_one_sided_geometric_tolerance(nom, LSL),
                            )
                        if LSL is not None or USL is not None:
                            render_spec_reference_lines(ax, nom, LSL, USL, include_nominal=False)

                    apply_minimal_axis_style(ax, grid_axis='y')
                    axis_layout = apply_shared_x_axis_label_strategy(
                        ax,
                        distribution_labels,
                        positions=label_positions,
                        force_sparse=force_sparse_x_labels,
                    )

                    current_y_limits = ax.get_ylim()
                    y_min, y_max = compute_scaled_y_limits(current_y_limits, self.summary_plot_scale)
                    ax.set_ylim(y_min, y_max)
                    ax.set_xlabel(distribution_x_axis_label)
                    ax.set_ylabel('Measurement')
                    ax.set_title(build_wrapped_chart_title(distribution_title), pad=20)
                    figure_legend = move_legend_to_figure(ax)
                    finalize_extended_chart_layout(fig, ax, legend=figure_legend, strategy=axis_layout)
                    distribution_native_payload = build_distribution_native_payload(
                        values=distribution_values,
                        labels=distribution_labels,
                        title=build_wrapped_chart_title(distribution_title),
                        lsl=LSL,
                        usl=USL,
                    )
                    distribution_render_result = self._save_summary_chart(
                        fig,
                        chart_type='distribution',
                        native_payload=distribution_native_payload,
                    )
                    image_data = self._register_chart_image(distribution_render_result.png_bytes)
                    self._record_chart_render_timing(
                        'distribution',
                        time.perf_counter() - chart_start,
                        backend=distribution_render_result.backend,
                    )

                    distribution_slot = _reserve_summary_image_slot('distribution', fig)
                    write_start = time.perf_counter()
                    self._insert_summary_image(summary_worksheet, distribution_slot, image_data)
                    self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)

                    if self._check_canceled():
                        plt.close(fig)
                        return
                    plt.close(fig)
                finally:
                    pass

            if self._check_canceled():
                return

            if self._summary_chart_required('iqr'):
                try:
                    chart_start = time.perf_counter()
                    boxplot_labels, boxplot_values = self._build_iqr_plot_payload(
                        iqr_labels,
                        iqr_values,
                        sampled_iqr_group,
                        grouping_active=grouping_applied,
                    )
                    iqr_strategy = prepare_categorical_x_axis(boxplot_labels)
                    fig, ax = plt.subplots(figsize=(iqr_strategy['recommended_fig_width'], 4))
                    render_iqr_boxplot(ax, boxplot_values, boxplot_labels)
                    render_tolerance_band(
                        ax,
                        nom,
                        LSL,
                        USL,
                        one_sided=is_one_sided_geometric_tolerance(nom, LSL),
                    )
                    render_spec_reference_lines(ax, nom, LSL, USL, include_nominal=False)
                    add_iqr_boxplot_legend(ax, include_tolerance_refs=False)
                    figure_legend = move_legend_to_figure(ax)
                    apply_minimal_axis_style(ax, grid_axis='y')
                    axis_layout = apply_shared_x_axis_label_strategy(
                        ax,
                        boxplot_labels,
                        positions=list(range(1, len(boxplot_labels) + 1)),
                        force_sparse=force_sparse_x_labels,
                    )
                    ax.set_xlabel('Group')
                    ax.set_ylabel('Measurement')
                    ax.set_title(build_wrapped_chart_title(header), pad=20)

                    current_y_limits = ax.get_ylim()
                    y_min, y_max = compute_scaled_y_limits(current_y_limits, self.summary_plot_scale)
                    ax.set_ylim(y_min, y_max)
                    finalize_extended_chart_layout(fig, ax, legend=figure_legend, strategy=axis_layout)

                    iqr_render_result = self._save_summary_chart(fig, chart_type='iqr')
                    image_data = self._register_chart_image(iqr_render_result.png_bytes)
                    self._record_chart_render_timing('iqr', time.perf_counter() - chart_start, backend=iqr_render_result.backend)
                    iqr_slot = _reserve_summary_image_slot('iqr', fig)
                    write_start = time.perf_counter()
                    self._insert_summary_image(summary_worksheet, iqr_slot, image_data)
                    self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)

                    if self._check_canceled():
                        plt.close(fig)
                        return
                    plt.close(fig)
                finally:
                    pass

            if self._summary_chart_required('histogram'):
                try:
                    base_histogram_figsize = (8.8, 4.0)
                    chart_start = time.perf_counter()
                    histogram_values = sampling_context['histogram_payload']['measurements']
                    histogram_title = build_wrapped_chart_title(header)
                    histogram_bin_count = resolve_histogram_bin_count(histogram_values).get('bin_count')

                    native_histogram_capable = False
                    if native_chart_backend_available():
                        try:
                            native_histogram_capable = resolve_chart_renderer_backend() == 'native'
                        except RuntimeError:
                            native_histogram_capable = False

                    if native_histogram_capable:
                        native_histogram_payload = build_histogram_native_payload(
                            values=histogram_values,
                            lsl=LSL,
                            usl=USL,
                            title=histogram_title,
                            bin_count=histogram_bin_count,
                        )
                        visual_metadata = _build_histogram_native_visual_metadata(
                            summary_stats=summary_stats,
                            lsl=LSL,
                            usl=USL,
                            nominal=nom,
                        )
                        native_histogram_payload.update(
                            {
                                'limits': {
                                    'lsl': None if LSL is None else float(LSL),
                                    'usl': None if USL is None else float(USL),
                                    'nominal': None if nom is None else float(nom),
                                },
                                'summary': {
                                    'count': float(summary_stats.get('n', 0) or 0),
                                    'mean': summary_stats.get('avg'),
                                    'std': summary_stats.get('std_dev'),
                                    'min': summary_stats.get('min'),
                                    'max': summary_stats.get('max'),
                                },
                                'style': {
                                    'axis_label_x': 'Measurement',
                                    'axis_label_y': 'Count',
                                    'grid_axis': 'y',
                                },
                                'visual_metadata': visual_metadata,
                                'advanced_annotations_enabled': False,
                                'overlays_enabled': False,
                            }
                        )

                        histogram_render_result = self._save_summary_chart(
                            None,
                            chart_type='histogram',
                            native_payload=native_histogram_payload,
                        )
                        image_data = self._register_chart_image(histogram_render_result.png_bytes)
                        self._record_chart_render_timing(
                            'histogram',
                            time.perf_counter() - chart_start,
                            backend=histogram_render_result.backend,
                        )
                        slot_fig = plt.figure(figsize=base_histogram_figsize)
                        histogram_slot = _reserve_summary_image_slot('histogram', slot_fig)
                        plt.close(slot_fig)
                        write_start = time.perf_counter()
                        self._insert_summary_image(summary_worksheet, histogram_slot, image_data)
                        self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)
                        if self._check_canceled():
                            return
                    else:
                        distribution_fit_result = precomputed_distribution_fit
                        if distribution_fit_result is None:
                            distribution_fit_result = fit_measurement_distribution(
                                histogram_values,
                                lsl=LSL,
                                usl=USL,
                                nom=nom,
                                point_count=40 if self._optimization_toggles['chart_density_mode'] == 'reduced' else 100,
                                include_kde_reference=self._optimization_toggles['chart_density_mode'] != 'reduced',
                                memoization_cache=self._distribution_fit_memo,
                            )

                        histogram_summary_payload = _finalize_histogram_summary_payload_compute(
                            summary_stats,
                            distribution_fit_result,
                            lsl=LSL,
                            usl=USL,
                        )
                        summary_stats = histogram_summary_payload['summary_stats']
                        histogram_table_payload = histogram_summary_payload['histogram_table_payload']
                        summary_table_composition = histogram_summary_payload['summary_table_composition']
                        histogram_row_badges = summary_table_composition['histogram_row_badges']
                        capability_badge = summary_table_composition['capability_badge']
                        histogram_table_payload = _apply_non_normal_cpk_reference_label(
                            histogram_table_payload,
                            distribution_fit_result,
                            summary_stats=summary_stats,
                        )
                        non_normal_reference_mode = _is_non_normal_capability_reference_model(distribution_fit_result)
                        statistics_rows = histogram_table_payload['rows']
                        distribution_fit_rows = _build_distribution_fit_table_rows(
                            distribution_fit_result,
                            lsl=LSL,
                            usl=USL,
                            summary_stats=summary_stats,
                        )
                        unified_rows = _build_unified_histogram_dashboard_rows(
                            statistics_rows=statistics_rows,
                            distribution_fit_rows=distribution_fit_rows,
                        )

                        histogram_figsize = base_histogram_figsize
                        fig = plt.figure(figsize=histogram_figsize)
                        histogram_font_sizes = compute_histogram_font_sizes(
                            histogram_figsize,
                            has_table=True,
                            readability_scale=self.summary_plot_scale,
                        )

                        panel_rects = compute_histogram_plot_with_right_info_layout(
                            histogram_figsize,
                            table_fontsize=histogram_font_sizes['table_fontsize'],
                            fit_row_count=0,
                            stats_row_count=len(unified_rows),
                            fit_rows=[],
                            stats_rows=unified_rows,
                            note_line_count=0,
                            right_container_width_hint=0.34,
                            dpi=fig.dpi,
                        )
                        assert_non_overlapping_rectangles(
                            {
                                'plot_rect': panel_rects['plot_rect'],
                                'right_table_rect': panel_rects['right_container_rect'],
                                'footer_rect': panel_rects['footer_rect'],
                            }
                        )

                        plot_rect = panel_rects['plot_rect']
                        right_table_rect = panel_rects['right_container_rect']

                        plot_ax = fig.add_axes([
                            plot_rect['x'],
                            plot_rect['y'],
                            plot_rect['width'],
                            plot_rect['height'],
                        ])
                        right_table_ax = fig.add_axes([
                            right_table_rect['x'],
                            right_table_rect['y'],
                            right_table_rect['width'],
                            right_table_rect['height'],
                        ])
                        right_table_ax.set_axis_off()

                        histogram_render_meta = render_histogram(
                            plot_ax,
                            sampled_histogram_group,
                            lsl=LSL,
                            usl=USL,
                            group_column=distribution_key if grouping_applied else None,
                        )

                        table_style_options = {
                            'fontsize': histogram_font_sizes['table_fontsize'],
                            'min_fontsize': 7.4,
                            'max_fontsize': 10.4,
                            'cell_padding_points': 2.2,
                            'compact_label_mapping': {
                                **_DISTRIBUTION_FIT_COMPACT_LABELS,
                                'Normality': 'Norm.',
                            },
                        }

                        unified_table_meta = render_panel_table_in_panel_axes(
                            ax=right_table_ax,
                            title='Parameter',
                            rows=unified_rows,
                            style_options={
                                **table_style_options,
                                'explicit_label_fraction': _UNIFIED_HISTOGRAM_LABEL_FRACTION,
                                'explicit_value_fraction': _UNIFIED_HISTOGRAM_VALUE_FRACTION,
                                'value_wrap_width': 26,
                                'low_priority_labels': {'Est. PPM', 'NOK (PPM)', 'Yield %'},
                            },
                            row_height=_EXTENDED_HISTOGRAM_PANEL_ROW_HEIGHT,
                            pad_y=0.0,
                            valign='top',
                        )
                        unified_table = unified_table_meta['table']

                        non_normal_row_badges = dict(histogram_row_badges or {})
                        if non_normal_reference_mode:
                            for label in ('Cp (ref)', 'Cpk (ref)'):
                                non_normal_row_badges[label] = {'palette_key': 'quality_unknown'}

                        fit_quality_value = None
                        for label, value in unified_table_meta.get('rendered_rows', []):
                            if label == 'Fit quality':
                                fit_quality_value = str(value).strip().lower()
                                break

                        fit_quality_palette = None
                        if fit_quality_value in {'weak', 'unreliable'}:
                            fit_quality_palette = 'fit_quality_low'
                        elif fit_quality_value in {'medium', 'marginal'}:
                            fit_quality_palette = 'fit_quality_medium'
                        elif fit_quality_value in {'good', 'strong', 'capable'}:
                            fit_quality_palette = 'fit_quality_high'
                        if fit_quality_palette:
                            non_normal_row_badges['Fit quality'] = {'palette_key': fit_quality_palette}

                        style_histogram_stats_table(
                            unified_table,
                            unified_table_meta['rendered_rows'],
                            capability_badge=capability_badge,
                            capability_row_badges=non_normal_row_badges,
                        )
                        _apply_table_section_separator(
                            unified_table,
                            unified_table_meta['rendered_rows'],
                            transition_label='Model',
                        )
                        adjust_histogram_stats_table_geometry(
                            unified_table,
                            statistic_col_width_ratio=_EXTENDED_HISTOGRAM_STATISTIC_COL_WIDTH_RATIO,
                            row_height_scale=_EXTENDED_HISTOGRAM_TABLE_ROW_HEIGHT_SCALE,
                            explicit_row_heights=unified_table_meta.get('explicit_row_heights'),
                        )

                        selected_model_curve = distribution_fit_result.get('selected_model_pdf')
                        annotation_specs = build_histogram_annotation_specs(average, USL, LSL, 1.0)
                        x_left, x_right = plot_ax.get_xlim()
                        x_span = abs(float(x_right) - float(x_left))
                        annotation_specs, _ = compute_histogram_annotation_rows(
                            annotation_specs,
                            distance_threshold=0.04,
                            threshold_mode='axis_fraction',
                            x_span=x_span,
                            base_text_y_axes=1.01,
                            row_step=0.025,
                        )

                        if selected_model_curve is not None:
                            model_curve_style = resolve_selected_model_curve_style(distribution_fit_result)
                            model_curve_y = np.asarray(selected_model_curve['y'], dtype=float)
                            count_scale_factor = histogram_render_meta.get('count_scale_factor')
                            if count_scale_factor is not None:
                                model_curve_y = model_curve_y * float(count_scale_factor)
                            render_density_line(
                                plot_ax,
                                selected_model_curve['x'],
                                model_curve_y,
                                alpha=model_curve_style['alpha'],
                                linewidth=model_curve_style['linewidth'],
                            )
                            distribution_fit_result['selected_model_pdf'] = {
                                **selected_model_curve,
                                'y': model_curve_y,
                            }
                            render_modeled_tail_shading(plot_ax, distribution_fit_result, lsl=LSL, usl=USL)
                        kde_reference_curve = distribution_fit_result.get('kde_reference_pdf')
                        if kde_reference_curve is not None:
                            kde_curve_y = np.asarray(kde_reference_curve['y'], dtype=float)
                            count_scale_factor = histogram_render_meta.get('count_scale_factor')
                            if count_scale_factor is not None:
                                kde_curve_y = kde_curve_y * float(count_scale_factor)
                            render_density_line(
                                plot_ax,
                                kde_reference_curve['x'],
                                kde_curve_y,
                                color=SUMMARY_PLOT_PALETTE['density_line'],
                                alpha=0.22,
                                linewidth=0.9,
                                linestyle='--',
                            )
                            plot_ax.text(
                                0.02,
                                0.02,
                                'Dashed KDE: descriptive only',
                                transform=plot_ax.transAxes,
                                ha='left',
                                va='bottom',
                                fontsize=max(6.5, histogram_font_sizes['table_fontsize'] - 1.0),
                                color='#4d5968',
                                bbox={
                                    'boxstyle': 'round,pad=0.16',
                                    'facecolor': (1.0, 1.0, 1.0, 0.74),
                                    'edgecolor': '#c7ced7',
                                    'linewidth': 0.45,
                                },
                                zorder=8,
                            )

                        lock_histogram_y_axis_to_bar_heights(plot_ax)

                        fit_warning = distribution_fit_result.get('warning')
                        if fit_warning:
                            logger.warning("%s Header=%s", fit_warning, header)

                        mean_line_style = build_histogram_mean_line_style()
                        plot_ax.axvline(average, **mean_line_style)
                        render_tolerance_band(
                            plot_ax,
                            nom,
                            LSL,
                            USL,
                            one_sided=is_one_sided_geometric_tolerance(nom, LSL),
                            orientation='vertical',
                        )
                        render_spec_reference_lines(plot_ax, nom, LSL, USL, orientation='vertical', include_nominal=False)
                        plot_ax.set_xlabel('Measurement')
                        if not histogram_render_meta.get('is_grouped'):
                            plot_ax.set_ylabel('Count')
                        title_artist = render_histogram_title(
                            plot_ax,
                            build_wrapped_chart_title(header),
                            fontsize=max(histogram_font_sizes['annotation_fontsize'] + 1.1, 8.8),
                        )
                        apply_minimal_axis_style(plot_ax, grid_axis='y')

                        annotation_box = {
                            'boxstyle': 'round,pad=0.15',
                            'fc': 'white',
                            'ec': SUMMARY_PLOT_PALETTE['annotation_box_edge'],
                            'alpha': 0.94,
                            'plot_rect': plot_rect,
                            'title_artist': title_artist,
                        }
                        render_histogram_annotations(
                            plot_ax,
                            annotation_specs,
                            annotation_fontsize=histogram_font_sizes['annotation_fontsize'],
                            annotation_box=annotation_box,
                        )
                        native_histogram_payload = build_histogram_native_payload(
                            values=histogram_values,
                            lsl=LSL,
                            usl=USL,
                            title=histogram_title,
                            bin_count=histogram_bin_count,
                        )
                        native_histogram_payload.update(
                            {
                                'visual_metadata': _build_histogram_native_visual_metadata(
                                    summary_stats=summary_stats,
                                    lsl=LSL,
                                    usl=USL,
                                    nominal=nom,
                                ),
                                'advanced_annotations_enabled': False,
                                'overlays_enabled': False,
                            }
                        )
                        histogram_render_result = self._save_summary_chart(
                            fig,
                            chart_type='histogram',
                            native_payload=native_histogram_payload,
                        )
                        image_data = self._register_chart_image(histogram_render_result.png_bytes)
                        self._record_chart_render_timing(
                            'histogram',
                            time.perf_counter() - chart_start,
                            backend=histogram_render_result.backend,
                        )
                        histogram_slot = _reserve_summary_image_slot('histogram', fig)
                        write_start = time.perf_counter()
                        self._insert_summary_image(summary_worksheet, histogram_slot, image_data)
                        self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)

                        if self._check_canceled():
                            plt.close(fig)
                            return
                        plt.close(fig)
                finally:
                    pass

            if self._summary_chart_required('trend'):
                try:
                    apply_summary_plot_theme()

                    chart_start = time.perf_counter()
                    data_x = trend_payload['x']
                    data_y = trend_payload['y']
                    unique_labels = trend_payload['labels']

                    trend_label_count = len(unique_labels)
                    trend_figure_width = 6
                    if trend_label_count > 24:
                        trend_figure_width = 8
                    if trend_label_count > 40:
                        trend_figure_width = 10

                    fig, ax = plt.subplots(figsize=(trend_figure_width, 4))
                    ax.scatter(data_x, data_y, color=SUMMARY_PLOT_PALETTE['distribution_foreground'], marker='.', s=20)
                    for line_spec in build_horizontal_limit_line_specs(USL, LSL):
                        ax.axhline(**line_spec)

                    ax.set_xlabel(distribution_x_axis_label)
                    ax.set_ylabel('Measurement')
                    ax.set_title(build_wrapped_chart_title(header), pad=20)
                    apply_minimal_axis_style(ax, grid_axis='y')
                    apply_shared_x_axis_label_strategy(
                        ax,
                        unique_labels,
                        positions=data_x,
                        force_sparse=force_sparse_x_labels,
                        allow_thinning=False,
                    )

                    current_y_limits = ax.get_ylim()
                    y_min, y_max = compute_scaled_y_limits(current_y_limits, self.summary_plot_scale)
                    ax.set_ylim(y_min, y_max)

                    trend_render_result = self._save_summary_chart(fig, chart_type='trend')
                    image_data = self._register_chart_image(trend_render_result.png_bytes)
                    self._record_chart_render_timing('trend', time.perf_counter() - chart_start, backend=trend_render_result.backend)
                    trend_slot = _reserve_summary_image_slot('trend', fig)
                    write_start = time.perf_counter()
                    self._insert_summary_image(summary_worksheet, trend_slot, image_data)
                    self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)
                    if self._check_canceled():
                        plt.close(fig)
                        return
                    plt.close(fig)
                finally:
                    pass

        except Exception as e:
            self.log_and_exit(e)
            self._summary_sheet_failed = True

    def log_and_exit(self, exception):
        """Handle `log_and_exit` for `ExportDataThread`.

        Args:
            exception (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        caller = inspect.stack()[1].function
        context = f"export operation ({caller})"
        self._log_export_stage(
            "Export operation failed",
            stage="error",
            level="error",
            exception_class=type(exception).__name__,
            operation_context=context,
        )
        if hasattr(custom_logger, "handle_exception") and hasattr(custom_logger, "LOG_ONLY"):
            custom_logger.handle_exception(
                exception,
                behavior=custom_logger.LOG_ONLY,
                logger_name=logger.logger.name,
                context=context,
                reraise=False,
            )
        else:
            try:
                custom_logger.CustomLogger(exception, reraise=False)
            except Exception:
                logger.exception("Failed to invoke fallback custom logger for %s", context)
        self.error_occurred.emit(f"{context}: {exception}")

import logging
import warnings
import inspect
import os
import time
from concurrent.futures import ProcessPoolExecutor
import matplotlib
import pandas as pd
import numpy as np

matplotlib.use('Agg')

import importlib.util
from io import BytesIO

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal
from scipy.stats import ttest_ind

from modules.contracts import ExportRequest, validate_export_request
import modules.CustomLogger as custom_logger
from modules.db import execute_select_with_columns, read_sql_dataframe
from modules.excel_sheet_utils import unique_sheet_name
from modules.export_backends import ExcelExportBackend
from modules.google_drive_export import GoogleDriveAuthError, GoogleDriveExportError, upload_and_convert_workbook
from modules.progress_status import build_three_line_status
from modules.log_context import (
    build_export_log_extra,
    build_google_conversion_log_extra,
    get_operation_logger,
)
from modules.export_summary_utils import (
    apply_shared_x_axis_label_strategy as _apply_shared_x_axis_label_strategy,
    build_histogram_density_curve_payload as _build_histogram_density_curve_payload,
    build_sparse_unique_labels as _build_sparse_unique_labels,
    build_trend_plot_payload as _build_trend_plot_payload,
    compute_measurement_summary,
    resolve_nominal_and_limits,
)
from modules.export_summary_sheet_planner import (
    build_histogram_annotation_specs as _build_histogram_annotation_specs,
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
    build_measurement_export_dataframe,
    execute_export_query as _execute_export_query,
)
from modules.export_grouping_utils import (
    add_group_key as _add_group_key,
    apply_group_assignments as _apply_group_assignments,
    keys_have_usable_values as _keys_have_usable_values,
    prepare_grouping_dataframe as _prepare_grouping_dataframe,
    resolve_group_merge_keys as _resolve_group_merge_keys,
)
from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE, EMPHASIS_TABLE_ROWS
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
    build_summary_panel_write_plan,
)

_HAS_SEABORN = importlib.util.find_spec('seaborn') is not None
if _HAS_SEABORN:
    import seaborn as sns


logger = get_operation_logger(logging.getLogger(__name__), "export_data")


def build_export_dataframe(data, column_names):
    return _build_export_dataframe(data, column_names)


def execute_export_query(db_file, export_query, select_reader=execute_select_with_columns):
    return _execute_export_query(db_file, export_query, select_reader=select_reader)


def build_sheet_series_range(sheet_name, first_row, last_row, column_index):
    return _build_sheet_series_range(sheet_name, first_row, last_row, column_index)


def build_spec_limit_anchor_rows(usl, lsl):
    return _build_spec_limit_anchor_rows(usl, lsl)


def build_measurement_stat_formulas(summary_col, data_range_y, nom_cell, usl_cell, lsl_cell, nom_value, lsl_value):
    return _build_measurement_stat_formulas(summary_col, data_range_y, nom_cell, usl_cell, lsl_cell, nom_value, lsl_value)


def build_measurement_stat_row_specs(stat_formulas):
    return _build_measurement_stat_row_specs(stat_formulas)


def build_measurement_block_plan(*, base_col, sample_size):
    return _build_measurement_block_plan(base_col=base_col, sample_size=sample_size)


def build_measurement_header_block_plan(header_group, base_col):
    return _build_measurement_header_block_plan(header_group, base_col)


def build_measurement_chart_range_specs(*, sheet_name, first_data_row, last_data_row, x_column, y_column):
    return _build_measurement_chart_range_specs(
        sheet_name=sheet_name,
        first_data_row=first_data_row,
        last_data_row=last_data_row,
        x_column=x_column,
        y_column=y_column,
    )


def build_measurement_chart_series_specs(*, header, sheet_name, first_data_row, last_data_row, x_column, y_column):
    return _build_measurement_chart_series_specs(
        header=header,
        sheet_name=sheet_name,
        first_data_row=first_data_row,
        last_data_row=last_data_row,
        x_column=x_column,
        y_column=y_column,
    )


def build_measurement_chart_format_policy(header):
    return _build_measurement_chart_format_policy(header)


def build_horizontal_limit_line_specs(usl, lsl, **style):
    return _build_horizontal_limit_line_specs(usl, lsl, **style)


def build_measurement_write_bundle(header, header_group, base_col):
    return _build_measurement_write_bundle(header, header_group, base_col)


def build_measurement_write_bundle_cached(header, header_group, base_col, cache=None):
    return _build_measurement_write_bundle_cached(header, header_group, base_col, cache=cache)


def run_export_steps(steps, should_cancel):
    for step in steps:
        if should_cancel():
            return False
        step()
    return not should_cancel()


def all_measurements_within_limits(measurements, lower_limit, upper_limit):
    series = pd.Series(measurements)
    return series.between(lower_limit, upper_limit, inclusive='both').all()


def build_sparse_unique_labels(labels):
    return _build_sparse_unique_labels(labels)


def build_trend_plot_payload(header_group):
    return _build_trend_plot_payload(header_group)


def build_histogram_density_curve_payload(measurements, point_count=100):
    return _build_histogram_density_curve_payload(measurements, point_count=point_count)


def apply_shared_x_axis_label_strategy(ax, labels, **kwargs):
    return _apply_shared_x_axis_label_strategy(ax, labels, **kwargs)


def build_histogram_table_data(summary_stats):
    """Build stable, display-ready statistics rows for histogram summary tables."""

    def _rounded_or_text(value, digits):
        return value if isinstance(value, str) else round(value, digits)

    return [
        ('Min', round(summary_stats['minimum'], 3)),
        ('Max', round(summary_stats['maximum'], 3)),
        ('Mean', round(summary_stats['average'], 3)),
        ('Median', round(summary_stats['median'], 3)),
        ('Std Dev', round(summary_stats['sigma'], 3)),
        ('Cp', _rounded_or_text(summary_stats['cp'], 2)),
        ('Cpk', _rounded_or_text(summary_stats['cpk'], 2)),
        ('Samples', round(summary_stats['sample_size'], 1)),
        ('NOK nb', round(summary_stats['nok_count'], 1)),
        ('NOK %', f"{summary_stats['nok_pct'] * 100:.2f}%"),
    ]


def compute_scaled_y_limits(current_limits, scale_factor):
    """Return y-axis limits expanded by a symmetric scale factor."""
    y_min, y_max = current_limits
    data_range = y_max - y_min
    padding = scale_factor * data_range / 2
    return y_min - padding, y_max + padding


def build_summary_sheet_position_plan(base_col):
    return _build_summary_sheet_position_plan(base_col)


def build_summary_image_anchor_plan(base_col):
    return _build_summary_image_anchor_plan(base_col)


def build_histogram_annotation_specs(average, usl, lsl, y_max):
    return _build_histogram_annotation_specs(average, usl, lsl, y_max)


def build_histogram_mean_line_style():
    """Return style contract for histogram mean reference line."""
    return {
        'color': SUMMARY_PLOT_PALETTE['central_tendency'],
        'linestyle': '--',
        'linewidth': 1.6,
        'alpha': 0.55,
        'zorder': 5,
    }


def render_histogram_annotations(ax, annotation_specs, *, annotation_fontsize, annotation_box):
    """Render histogram annotations with consistent font sizing policy."""
    rendered = []
    x_min, x_max = ax.get_xlim()
    x_span = max(x_max - x_min, 1e-9)
    mean_text_offset = x_span * 0.015
    for annotation in annotation_specs:
        x_position = annotation['x'] + mean_text_offset if annotation['text'].startswith('μ=') else annotation['x']
        rendered.append(
            ax.text(
                x_position,
                annotation['y'],
                annotation['text'],
                color=annotation['color'],
                ha=annotation['ha'],
                va='top',
                fontsize=annotation_fontsize,
                bbox=annotation_box,
            )
        )
    return rendered


def build_summary_panel_subtitle_text(summary_stats):
    return build_summary_panel_subtitle(summary_stats)


def compute_histogram_font_sizes(
    figure_size=(6, 4),
    *,
    has_table=True,
    readability_scale=None,
):
    """Compute histogram annotation/table font sizes for summary-sheet embedding."""
    fig_width = figure_size[0] if isinstance(figure_size, (tuple, list)) and figure_size else 6
    fig_width = max(float(fig_width), 1.0)
    width_scale = min(1.25, max(0.8, fig_width / 6.0))

    optional_readability = 0.0 if readability_scale is None else float(readability_scale)
    readability_bonus = optional_readability * 0.18

    annotation_fontsize = 8.2 * width_scale
    table_fontsize = 9.2 * width_scale
    if has_table:
        annotation_fontsize -= 0.2
    annotation_fontsize += readability_bonus
    table_fontsize += readability_bonus

    return {
        'annotation_fontsize': min(10.5, max(7.0, annotation_fontsize)),
        'table_fontsize': min(11.5, max(8.0, table_fontsize)),
    }


def compute_histogram_table_layout(
    figure_size=(6, 4),
    *,
    table_fontsize=8.0,
    has_table=True,
):
    """Compute table bbox width and subplot right margin for histogram layouts."""
    fig_width = figure_size[0] if isinstance(figure_size, (tuple, list)) and figure_size else 6
    fig_width = max(float(fig_width), 1.0)
    width_scale = min(1.25, max(0.8, fig_width / 6.0))
    oversized_font = max(0.0, float(table_fontsize) - 8.0)

    table_bbox_width = 0.30 + (0.015 * oversized_font) - (0.01 * (width_scale - 1.0))
    table_bbox_width = min(0.36, max(0.28, table_bbox_width))

    right_margin = 0.75 + (0.02 * (width_scale - 1.0)) - (0.015 * oversized_font)
    if has_table:
        right_margin -= 0.005
    right_margin = min(0.78, max(0.68, right_margin))

    return {
        'table_bbox_width': table_bbox_width,
        'subplot_right': right_margin,
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
        'grid.linewidth': 0.6,
        'grid.alpha': 0.55,
    })


def apply_minimal_axis_style(ax, grid_axis='y'):
    """Apply a clean, minimal visual style on a chart axis."""
    ax.set_facecolor('white')
    ax.grid(True, axis=grid_axis, linestyle='-', color=SUMMARY_PLOT_PALETTE['grid'], alpha=0.55)
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

    def _safe_ttest_p_value(group_values, reference_values):
        if group_values.size < 2 or reference_values.size < 2:
            return np.nan

        if np.isclose(np.std(group_values, ddof=1), 0.0) or np.isclose(np.std(reference_values, ddof=1), 0.0):
            return np.nan

        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            _, p_value = ttest_ind(group_values, reference_values, equal_var=False, nan_policy='omit')
        return p_value

    cleaned_groups = [np.asarray(group_values, dtype=float) for group_values in values]
    if not cleaned_groups:
        return []

    population = np.concatenate(cleaned_groups)
    reference = cleaned_groups[0] if len(cleaned_groups) > 1 else population
    reference_name = str(labels[0]) if len(cleaned_groups) > 1 else 'Population'

    rows = []
    for label, group_values in zip(labels, cleaned_groups):
        if group_values.size == 0:
            continue

        if len(cleaned_groups) > 1 and str(label) == reference_name:
            p_value_display = 'Ref'
        else:
            p_value = _safe_ttest_p_value(group_values, reference)
            p_value_display = 'N/A' if np.isnan(p_value) else f"{p_value:.4f}"

        rows.append([
            str(label),
            int(group_values.size),
            round(float(np.min(group_values)), 3),
            round(float(np.mean(group_values)), 3),
            round(float(np.max(group_values)), 3),
            round(float(np.std(group_values, ddof=1)) if group_values.size > 1 else 0.0, 3),
            p_value_display,
        ])

    return rows


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


def annotate_violin_group_stats(ax, labels, values, *, readability_scale=None, annotation_mode='auto'):
    """Annotate group summary statistics on violin plots.

    Modes:
    - full: min/mean/max + ±3σ
    - compact: mean + optional ±3σ
    - auto: chooses full/compact based on group count and x-spacing
    """

    group_count = max(len(values), len(labels))
    style = resolve_violin_annotation_style(
        group_count=group_count,
        x_limits=ax.get_xlim(),
        figure_size=ax.figure.get_size_inches(),
        mode=annotation_mode,
        readability_scale=readability_scale,
    )
    annotation_boxes = []

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

        renderer = ax.figure.canvas.get_renderer()
        selected_bbox = None
        selected_offset = candidate_offsets[0]
        for candidate_offset in candidate_offsets:
            preview = ax.annotate(
                text,
                point_xy,
                textcoords='offset points',
                xytext=candidate_offset,
                fontsize=fontsize,
                color=color,
                bbox=bbox,
                alpha=0,
            )
            ax.figure.canvas.draw()
            bbox_display = preview.get_window_extent(renderer=renderer).expanded(1.03, 1.08)
            preview.remove()

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

    ax.figure.canvas.draw()
    for idx, group_values in enumerate(values):
        arr = np.asarray(group_values, dtype=float)
        if arr.size == 0:
            continue
        xpos = idx
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
        min_val = float(np.min(arr))
        max_val = float(np.max(arr))

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

        if style['show_sigma'] and std_val > 0:
            sigma_low = mean_val - (3 * std_val)
            sigma_high = mean_val + (3 * std_val)
            ax.vlines(
                xpos,
                sigma_low,
                sigma_high,
                colors=SUMMARY_PLOT_PALETTE['sigma_band'],
                linestyles=':',
                linewidth=style['sigma_line_width'],
                alpha=0.8,
                zorder=3,
            )

    return style


def add_violin_annotation_legend(ax, style):
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
        handles.append(
            Line2D([0], [0], linestyle=':', linewidth=max(style.get('sigma_line_width', 0.7), 0.7), color=SUMMARY_PLOT_PALETTE['sigma_band'], label='±3σ span (visual)'),
        )

    ax.legend(
        handles=handles,
        loc='upper right',
        bbox_to_anchor=(1.0, 1.0),
        borderaxespad=0.0,
        frameon=True,
        fontsize=max(style.get('font_size', 6.8) - 0.2, 6.6),
    )

def render_violin(ax, values, labels, *, readability_scale=None):
    if _HAS_SEABORN:
        sns.violinplot(data=values, inner=None, cut=0, linewidth=0.9, color=SUMMARY_PLOT_PALETTE['distribution_base'], ax=ax)
        ax.set_xticks(range(len(labels)))
    else:
        ax.violinplot(values, showmeans=False, showmedians=False, showextrema=False)
        ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels)
    style = annotate_violin_group_stats(ax, labels, values, readability_scale=readability_scale)
    add_violin_annotation_legend(ax, style)


def render_scatter(ax, data=None, x=None, y=None):
    if _HAS_SEABORN:
        sns.scatterplot(data=data, x=x, y=y, ax=ax, s=18, color=SUMMARY_PLOT_PALETTE['distribution_foreground'], legend=False)
    else:
        ax.scatter(data[x], data[y], color=SUMMARY_PLOT_PALETTE['distribution_foreground'], marker='.', s=18)


def render_histogram(ax, header_group):
    if _HAS_SEABORN:
        sns.histplot(data=header_group, x='MEAS', bins='auto', stat='density', alpha=0.7, color=SUMMARY_PLOT_PALETTE['distribution_base'], edgecolor='white', ax=ax)
    else:
        ax.hist(header_group['MEAS'], bins='auto', density=True, alpha=0.7, color=SUMMARY_PLOT_PALETTE['distribution_base'], edgecolor='white')


def render_iqr_boxplot(ax, values, labels):
    """Render a standard 1.5*IQR box plot used for outlier detection."""
    if not values:
        return

    positions = list(range(1, len(values) + 1))
    boxplot_kwargs = {
        'whis': 1.5,
        'patch_artist': True,
        'boxprops': {'facecolor': SUMMARY_PLOT_PALETTE['distribution_base'], 'edgecolor': SUMMARY_PLOT_PALETTE['distribution_foreground'], 'linewidth': 0.9, 'alpha': 0.45},
        'medianprops': {'color': SUMMARY_PLOT_PALETTE['central_tendency'], 'linewidth': 1.1},
        'whiskerprops': {'color': SUMMARY_PLOT_PALETTE['distribution_foreground'], 'linewidth': 0.9},
        'capprops': {'color': SUMMARY_PLOT_PALETTE['distribution_foreground'], 'linewidth': 0.9},
        'flierprops': {'marker': 'o', 'markersize': 3, 'markerfacecolor': SUMMARY_PLOT_PALETTE['outlier'], 'markeredgecolor': SUMMARY_PLOT_PALETTE['outlier'], 'alpha': 0.9},
    }
    label_values = [str(label) for label in labels]
    try:
        ax.boxplot(values, tick_labels=label_values, **boxplot_kwargs)
    except TypeError:
        ax.boxplot(values, labels=label_values, **boxplot_kwargs)
    ax.set_xticks(positions)
    ax.set_xticklabels([str(label) for label in labels])


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


def add_iqr_boxplot_legend(ax):
    """Attach a compact, non-overlapping legend for summary-sheet sized images."""
    handles = build_iqr_legend_handles()
    ax.legend(
        handles=handles,
        loc='upper right',
        bbox_to_anchor=(1.0, 1.0),
        fontsize=7,
        framealpha=0.9,
        facecolor='white',
        edgecolor=SUMMARY_PLOT_PALETTE['distribution_foreground'],
        borderaxespad=0.0,
        handlelength=1.5,
        labelspacing=0.25,
    )


def render_density_line(ax, x, p):
    if _HAS_SEABORN:
        sns.lineplot(x=x, y=p, color=SUMMARY_PLOT_PALETTE['density_line'], linewidth=1.4, ax=ax)
    else:
        ax.plot(x, p, color=SUMMARY_PLOT_PALETTE['density_line'], linewidth=1.4)


def style_histogram_stats_table(ax_table, table_data, *, capability_badge=None, capability_row_badges=None):
    """Apply semantic emphasis colors to the histogram summary table."""
    if ax_table is None:
        return

    header_cells = [(0, 0), (0, 1)]
    for cell_key in header_cells:
        cell = ax_table.get_celld().get(cell_key)
        if cell is None:
            continue
        cell.set_facecolor(SUMMARY_PLOT_PALETTE['table_header_bg'])
        cell.get_text().set_color(SUMMARY_PLOT_PALETTE['table_header_text'])

    cp_cpk_rows = {'Cp', 'Cpk'}
    for row_index, (label, _value) in enumerate(table_data, start=1):
        if capability_row_badges and label in capability_row_badges:
            _apply_table_row_badge(ax_table, row_index, capability_row_badges[label]['palette_key'])
            continue
        if capability_badge and label in cp_cpk_rows:
            _apply_table_row_badge(ax_table, row_index, capability_badge['palette_key'])
            continue

        if label not in EMPHASIS_TABLE_ROWS:
            continue
        for col_index in (0, 1):
            cell = ax_table.get_celld().get((row_index, col_index))
            if cell is None:
                continue
            cell.set_facecolor(SUMMARY_PLOT_PALETTE['table_emphasis_bg'])
            cell.get_text().set_color(SUMMARY_PLOT_PALETTE['table_emphasis_text'])

def classify_capability_status(cp, cpk):
    """Classify capability readiness into scan-friendly quality tiers."""

    def _as_float(value):
        if isinstance(value, str):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    cp_value = _as_float(cp)
    cpk_value = _as_float(cpk)
    if cp_value is None or cpk_value is None:
        return {
            'label': 'Cp/Cpk N/A',
            'palette_key': 'quality_unknown',
        }

    if cpk_value >= 1.67 and cp_value >= 1.67:
        return {
            'label': 'Cp/Cpk capable',
            'palette_key': 'quality_capable',
        }

    if cpk_value > 1.33 and cp_value > 1.33:
        return {
            'label': 'Cp/Cpk good',
            'palette_key': 'quality_good',
        }

    if cpk_value >= 1.0 and cp_value >= 1.0:
        return {
            'label': 'Cp/Cpk marginal',
            'palette_key': 'quality_marginal',
        }

    return {
        'label': 'Cp/Cpk risk',
        'palette_key': 'quality_risk',
    }


def classify_capability_value(value, *, label_prefix='Capability'):
    """Classify a single Cp/Cpk value for independent row highlighting."""

    def _as_float(raw):
        if isinstance(raw, str):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    numeric = _as_float(value)
    if numeric is None:
        return {'label': f'{label_prefix} N/A', 'palette_key': 'quality_unknown'}
    if numeric >= 1.67:
        return {'label': f'{label_prefix} capable', 'palette_key': 'quality_capable'}
    if numeric > 1.33:
        return {'label': f'{label_prefix} good', 'palette_key': 'quality_good'}
    if numeric >= 1.0:
        return {'label': f'{label_prefix} marginal', 'palette_key': 'quality_marginal'}
    return {'label': f'{label_prefix} risk', 'palette_key': 'quality_risk'}


def classify_nok_severity(nok_pct):
    """Classify NOK ratio severity for chart title cueing."""
    ratio = 0.0
    try:
        ratio = float(nok_pct)
    except (TypeError, ValueError):
        ratio = 0.0

    if ratio <= 0.003:
        return {
            'label': 'NOK 0%',
            'palette_key': 'quality_capable',
        }

    if ratio <= 0.05:
        return {
            'label': f'NOK {ratio * 100:.1f}% watch',
            'palette_key': 'quality_marginal',
        }

    return {
        'label': f'NOK {ratio * 100:.1f}% high',
        'palette_key': 'quality_risk',
    }


def build_summary_panel_subtitle(summary_stats):
    """Return compact panel subtitle text showing sample size and NOK share."""
    return f"n={int(summary_stats['sample_size'])} • NOK={summary_stats['nok_pct'] * 100:.1f}%"


def _apply_table_row_badge(ax_table, row_index, palette_key):
    for col_index in (0, 1):
        cell = ax_table.get_celld().get((row_index, col_index))
        if cell is None:
            continue
        cell.set_facecolor(SUMMARY_PLOT_PALETTE[f'{palette_key}_bg'])
        text = cell.get_text()
        text.set_color(SUMMARY_PLOT_PALETTE[f'{palette_key}_text'])
        text.set_weight('bold')


def add_quality_title_badge(ax, label, palette_key, *, x=0.01, y=1.02):
    """Render a subtle colored quality badge near the chart title area."""
    ax.text(
        x,
        y,
        label,
        transform=ax.transAxes,
        ha='left',
        va='bottom',
        fontsize=7.4,
        color=SUMMARY_PLOT_PALETTE[f'{palette_key}_text'],
        bbox={
            'boxstyle': 'round,pad=0.16',
            'fc': SUMMARY_PLOT_PALETTE[f'{palette_key}_bg'],
            'ec': SUMMARY_PLOT_PALETTE[f'{palette_key}_bg'],
            'alpha': 0.95,
        },
        zorder=6,
    )


class ExportDataThread(QThread):
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
        self.export_canceled = False
        self._cancel_signal_emitted = False
        self._prepared_grouping_df = None
        self.completion_metadata = {"local_xlsx_path": self.excel_file}
        self._exported_sheet_names = []
        self._exported_sheet_name_set = set()
        self._last_emitted_progress = -1
        self._stage_timings = {
            'transform_grouping': 0.0,
            'chart_rendering': 0.0,
            'worksheet_writes': 0.0,
        }
        self._optimization_toggles = {
            'chart_density_mode': 'full',
            'defer_non_essential_charts': False,
            'summary_sheet_minimum_charts': {'distribution', 'iqr', 'histogram', 'trend'},
            'enable_chart_multiprocessing': os.getenv('METROLIZA_EXPORT_CHART_MP', '').lower() in {'1', 'true', 'yes', 'on'} and os.name != 'nt',
        }
        self._chart_executor = None
        self._reset_export_df_cache()

    def _ensure_chart_executor(self):
        if not self._optimization_toggles.get('enable_chart_multiprocessing'):
            return None
        if self._chart_executor is None:
            self._chart_executor = ProcessPoolExecutor(max_workers=2)
        return self._chart_executor

    def _shutdown_chart_executor(self):
        if self._chart_executor is None:
            return
        try:
            self._chart_executor.shutdown(wait=True)
        finally:
            self._chart_executor = None

    def _reset_export_df_cache(self):
        self._export_df_cache = None
        self._export_df_column_order = None

    def _ensure_export_df_cache(self):
        if self._export_df_cache is None:
            export_df = read_sql_dataframe(self.db_file, self.filter_query)
            self._export_df_cache = export_df
            self._export_df_column_order = tuple(export_df.columns)
        return self._export_df_cache

    def _build_export_filtered_dataframe(self):
        export_df = self._ensure_export_df_cache()
        if not self._export_df_column_order:
            return export_df.copy()
        return export_df.loc[:, list(self._export_df_column_order)].copy()

    def _record_stage_timing(self, stage_name, elapsed):
        if stage_name in self._stage_timings:
            self._stage_timings[stage_name] += max(0.0, float(elapsed))

    def _apply_bottleneck_optimizations(self):
        total = sum(self._stage_timings.values())
        if total <= 0.0:
            return

        chart_share = self._stage_timings['chart_rendering'] / total
        if chart_share >= 0.65:
            self._optimization_toggles['chart_density_mode'] = 'reduced'
            self._optimization_toggles['defer_non_essential_charts'] = True
        elif chart_share >= 0.45:
            self._optimization_toggles['chart_density_mode'] = 'reduced'

    def _chart_sample_limit(self):
        return 900 if self._optimization_toggles['chart_density_mode'] == 'reduced' else 3000

    def _summary_chart_required(self, chart_name):
        required_charts = self._optimization_toggles.get('summary_sheet_minimum_charts', set())
        return chart_name in required_charts

    def _build_iqr_plot_payload(self, labels, values, sampled_group):
        boxplot_labels = labels if labels else ['All']
        boxplot_values = values if values else [list(sampled_group['MEAS'])]

        if self._optimization_toggles['chart_density_mode'] != 'reduced':
            return boxplot_labels, boxplot_values

        max_groups = 24
        if len(boxplot_labels) <= max_groups:
            return boxplot_labels, boxplot_values

        stride = max(1, int(np.ceil(len(boxplot_labels) / max_groups)))
        return boxplot_labels[::stride], boxplot_values[::stride]

    @staticmethod
    def _downsample_frame(df, sample_limit):
        if len(df) <= sample_limit:
            return df
        stride = max(1, int(np.ceil(len(df) / sample_limit)))
        return df.iloc[::stride].copy()

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
        grouped_meas = (
            header_group.dropna(subset=['MEAS'])
            .groupby(group_column, sort=False)['MEAS']
            .agg(list)
        )

        if grouped_meas.empty:
            return [], [], False

        labels = list(grouped_meas.index)
        values = list(grouped_meas.values)
        can_render_violin = all(len(group_values) >= min_samplesize for group_values in values)
        return labels, values, can_render_violin

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

    def _apply_group_assignments(self, header_group, grouping_df):
        merged_group, grouping_applied, merge_keys, duplicate_count = _apply_group_assignments(header_group, grouping_df)
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
        self._reset_export_df_cache()
        self._ensure_export_df_cache()
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
            ],
            should_cancel=self._check_canceled,
        )

    def get_export_backend(self):
        target_to_backend = {
            'excel_xlsx': ExcelExportBackend(),
            'google_sheets_drive_convert': ExcelExportBackend(),
        }
        return target_to_backend[self.export_target]

    def _emit_google_stage(self, stage, detail=""):
        stage_labels = {
            "generating": "Google export stage: generating workbook",
            "uploading": "Google export stage: uploading",
            "converting": "Google export stage: converting",
            "validating": "Google export stage: validating",
            "completed": "Google export stage: completed",
            "fallback": "Google export stage: fallback",
        }
        base = stage_labels.get(stage)
        if not base:
            return
        if detail:
            self.update_label.emit(build_three_line_status(f"{base} ({detail})", "Exporting data...", "ETA --"))
            return
        self.update_label.emit(build_three_line_status(base, "Exporting data...", "ETA --"))

    def _build_export_context(self, *, stage, fallback_reason=""):
        return build_export_log_extra(
            export_target=self.export_target,
            output_path=self.excel_file,
            stage=stage,
            fallback_reason=fallback_reason,
        )

    def _log_export_stage(self, message, *, stage, level="info", fallback_reason="", **extra):
        log_method = getattr(logger, level)
        log_method(
            message,
            extra=self._build_export_context(stage=stage, fallback_reason=fallback_reason) | extra,
        )

    def _log_google_issue(self, context, *, fallback_message="", warnings=None, error=None):
        warning_list = [str(item) for item in (warnings or []) if str(item).strip()]
        details = []
        if fallback_message:
            details.append(f"fallback={fallback_message}")
        if warning_list:
            details.append("warnings=" + " | ".join(warning_list))
        if error is not None:
            details.append(f"error={error}")

        suffix = f" ({'; '.join(details)})" if details else ""
        log_method = logger.error if error is not None else logger.warning
        google_extra = build_google_conversion_log_extra(
            file_ref=self.excel_file,
            error_class=type(error).__name__ if error is not None else "",
            outcome="fallback" if fallback_message else "warning",
        )
        log_method(
            "Google export issue: %s%s",
            context,
            suffix,
            extra=self._build_export_context(stage="google_issue", fallback_reason=fallback_message) | google_extra,
        )

    def run(self):
        try:
            if self._check_canceled():
                return

            self._reset_export_df_cache()
            self._ensure_chart_executor()

            self._emit_stage_progress('preparing_query', 0.0)
            self.update_label.emit(build_three_line_status("Preparing export...", "Loading data and configuring stages", "ETA --"))
            self._log_export_stage("Export started", stage="started")
            if self.export_target == "google_sheets_drive_convert":
                self._emit_google_stage("generating")

            backend = self.get_export_backend()
            self._active_backend = backend
            completed = backend.run(self)
            if not completed:
                return

            if self.export_target == "google_sheets_drive_convert":
                def _stage_callback(stage_message):
                    if stage_message == "uploading":
                        self._emit_google_stage("uploading")
                        self._log_export_stage("Google conversion stage", stage="uploading")
                        return
                    if stage_message == "converting":
                        self._emit_google_stage("converting")
                        self._log_export_stage("Google conversion stage", stage="converting")
                        return
                    if stage_message == "validating":
                        self._emit_google_stage("validating")
                        self._log_export_stage("Google conversion stage", stage="validating")
                        return
                    if stage_message.startswith("uploading retry"):
                        self._emit_google_stage("uploading", detail=stage_message)
                        self._log_export_stage("Google conversion upload retry", stage="uploading_retry", level="warning")

                conversion = upload_and_convert_workbook(
                    self.excel_file,
                    expected_sheet_names=self._build_expected_sheet_names(),
                    status_callback=_stage_callback,
                )
                self.completion_metadata.update(
                    {
                        "converted_file_id": conversion.file_id,
                        "converted_url": conversion.web_url,
                        "local_xlsx_path": conversion.local_xlsx_path,
                        "fallback_message": conversion.fallback_message,
                        "conversion_warnings": list(conversion.warnings),
                        "converted_tab_titles": list(conversion.converted_tab_titles),
                    }
                )
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
            self.update_label.emit(build_three_line_status("Export completed successfully.", "Workbook and metadata finalized", "ETA 0:00"))
            self._log_export_stage("Export completed successfully", stage="completed")
            self.finished.emit()
            QCoreApplication.processEvents()
        except GoogleDriveExportError as e:
            if self.export_target == "google_sheets_drive_convert":
                self.completion_metadata.update(
                    {
                        "fallback_message": f"Google export failed; using local .xlsx fallback: {self.excel_file}",
                        "conversion_warnings": [str(e)],
                    }
                )
                self._emit_google_stage("fallback", detail=self.completion_metadata["fallback_message"])
                self.update_label.emit(build_three_line_status(f"Warning: {e}", "Exporting data...", "ETA --"))
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
                self.log_and_exit(e)
                return
            self.log_and_exit(e)
        except Exception as e:
            self.log_and_exit(e)
        finally:
            self._shutdown_chart_executor()
            self._reset_export_df_cache()

    def add_measurements_horizontal_sheet(self, excel_writer):
        try:
            df = build_measurement_export_dataframe(self._ensure_export_df_cache())

            reference_groups = df.groupby('REFERENCE', sort=False)
            total_references = reference_groups.ngroups
            total_header_units = int(reference_groups['HEADER - AX'].nunique(dropna=False).sum())
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
            max_col = len(df['HEADER - AX'].unique()) * 3

            for ref_index, (ref, ref_group) in enumerate(reference_groups, start=1):
                if self._check_canceled():
                    return

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
                for (header, header_group) in header_groups:
                    if self._check_canceled():
                        return

                    transform_start = time.perf_counter()
                    header_group = self._sort_header_group(header_group)
                    base_col = col
                    if timing_enabled:
                        build_bundle_start = time.perf_counter()
                    write_bundle = _build_measurement_write_bundle_cached(header, header_group, base_col, cache=optimization_cache)
                    self._record_stage_timing('transform_grouping', time.perf_counter() - transform_start)
                    if timing_enabled:
                        build_bundle_elapsed += time.perf_counter() - build_bundle_start
                    header_plan = write_bundle['header_plan']
                    write_start = time.perf_counter()
                    measurement_plan = write_measurement_block(worksheet, write_bundle, formats, base_col=base_col)

                    col += 3
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
                        chart_anchor_col=col - 3,
                        cache=optimization_cache,
                    )

                    chart_insert_time = time.perf_counter() - chart_insert_start
                    if timing_enabled:
                        chart_insert_elapsed += chart_insert_time
                    self._record_stage_timing('chart_rendering', chart_insert_time)

                    if self._check_canceled():
                        return

                    if self.generate_summary_sheet:
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
                    logger.debug(
                        "Export stage totals [ref=%s]: transform=%.3fs chart=%.3fs worksheet=%.3fs toggles=%s",
                        ref,
                        self._stage_timings['transform_grouping'],
                        self._stage_timings['chart_rendering'],
                        self._stage_timings['worksheet_writes'],
                        self._optimization_toggles,
                    )
                    if self._stage_timings['chart_rendering'] > (self._stage_timings['transform_grouping'] * 2) and self._stage_timings['chart_rendering'] > self._stage_timings['worksheet_writes']:
                        logger.info(
                            "Export bottleneck analysis [ref=%s]: chart rendering dominates; remaining pure-math kernels are not currently dominant, so native code is not recommended yet.",
                            ref,
                        )

                worksheet.freeze_panes(12, 0)

            if total_references == 0 or total_header_units == 0:
                self._emit_stage_progress('measurement_sheets_charts', 1.0)
        except Exception as e:
            self.log_and_exit(e)

    def export_filtered_data(self, excel_writer):
        try:
            if self._check_canceled():
                return
            export_df = self._build_export_filtered_dataframe()
            self.write_data_to_excel(export_df, "MEASUREMENTS", excel_writer)
        except Exception as e:
            self.log_and_exit(e)

    def write_data_to_excel(self, df, table_name, excel_writer):
        try:
            if self._check_canceled():
                return
            # Write the DataFrame to the Excel file
            backend = self._active_backend or self.get_export_backend()
            safe_table_name = unique_sheet_name(table_name, backend.list_sheet_names(excel_writer))
            backend.write_dataframe(excel_writer, df, safe_table_name)
            self._record_exported_sheet_name(safe_table_name)
            worksheet = backend.get_worksheet(excel_writer, safe_table_name)

            # Apply autofilter to enable filtering
            worksheet.autofilter(0, 0, df.shape[0], df.shape[1] - 1)

            # Freeze first row
            worksheet.freeze_panes(1, 0)

            # Adjust the column widths based on the data
            for i, column in enumerate(df.columns):
                if self._check_canceled():
                    return
                column_width = self.calculate_column_width(df[column])
                worksheet.set_column(i, i, column_width)
        except Exception as e:
            self.log_and_exit(e)

    def calculate_column_width(self, data):
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
        try:
            if self._check_canceled():
                return
            transform_start = time.perf_counter()
            header_group = self._ensure_sample_number_column(header_group)
            imgplot = BytesIO()
            limits = resolve_nominal_and_limits(header_group)
            nom = limits['nom']
            USL = limits['usl']
            LSL = limits['lsl']

            summary_stats = compute_measurement_summary(header_group, usl=USL, lsl=LSL, nom=nom)
            average = summary_stats['average']
            capability_badge = classify_capability_status(summary_stats['cp'], summary_stats['cpk'])
            capability_row_badges = {
                'Cp': classify_capability_value(summary_stats['cp'], label_prefix='Cp'),
                'Cpk': classify_capability_value(summary_stats['cpk'], label_prefix='Cpk'),
            }
            panel_subtitle = build_summary_panel_subtitle(summary_stats)
            
            apply_summary_plot_theme()
            fig, ax = plt.subplots(figsize=(6, 4))
            
            grouping_df = self.prepared_grouping_df
            header_group, grouping_applied = self._apply_group_assignments(header_group, grouping_df)
            sampled_group = self._downsample_frame(header_group, self._chart_sample_limit())
            self._record_stage_timing('transform_grouping', time.perf_counter() - transform_start)

            chart_mp_enabled = self._chart_executor is not None and len(sampled_group) >= 2500
            precomputed_density_curve = None
            precomputed_trend_payload = None
            if chart_mp_enabled:
                try:
                    density_future = self._chart_executor.submit(build_histogram_density_curve_payload, sampled_group['MEAS'])
                    trend_future = self._chart_executor.submit(build_trend_plot_payload, sampled_group)
                    precomputed_density_curve = density_future.result()
                    precomputed_trend_payload = trend_future.result()
                except Exception:
                    precomputed_density_curve = None
                    precomputed_trend_payload = None

            chart_start = time.perf_counter()
            if grouping_applied:
                labels, values, can_render_violin = self._build_violin_payload(
                    sampled_group,
                    'GROUP',
                    self.violin_plot_min_samplesize,
                )
                if can_render_violin:
                    render_violin(ax, values, labels, readability_scale=self.summary_plot_scale)
                else:
                    render_scatter(ax, data=sampled_group, x='GROUP', y='MEAS')
            else:
                labels, values, can_render_violin = self._build_violin_payload(
                    sampled_group,
                    'SAMPLE_NUMBER',
                    self.violin_plot_min_samplesize,
                )
                if can_render_violin:
                    render_violin(ax, values, labels, readability_scale=self.summary_plot_scale)
                else:
                    render_scatter(ax, data=sampled_group, x='SAMPLE_NUMBER', y='MEAS')

            apply_minimal_axis_style(ax, grid_axis='y')
            apply_shared_x_axis_label_strategy(ax, labels)
            for line_spec in build_horizontal_limit_line_specs(USL, LSL):
                ax.axhline(**line_spec)

            current_y_limits = ax.get_ylim()
            y_min, y_max = compute_scaled_y_limits(current_y_limits, self.summary_plot_scale)

            # Set y-axis limits using the Axes object
            ax.set_ylim(y_min, y_max)

            ax.set_xlabel('Sample #')
            ax.set_ylabel('Measurement')
            ax.set_title(f'{header}')
            fig.savefig(imgplot, format="png")
            self._record_stage_timing('chart_rendering', time.perf_counter() - chart_start)
            
            imgplot.seek(0)
            
            summary_anchors = build_summary_image_anchor_plan(col)
            panel_plan = build_summary_panel_write_plan(summary_anchors, header)
            header_cell = panel_plan['header_cell']
            write_start = time.perf_counter()
            summary_worksheet.write(header_cell['row'], header_cell['col'], header_cell['value'])
            summary_worksheet.write(header_cell['row'], header_cell['col'] + 1, panel_subtitle)
            distribution_slot = panel_plan['image_slots']['distribution']
            summary_worksheet.insert_image(
                distribution_slot['row'],
                distribution_slot['col'],
                "",
                {'image_data': imgplot},
            )
            self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)

            if self._check_canceled():
                plt.close(fig)
                return

            plt.close(fig)

            if self._check_canceled():
                return

            if self._summary_chart_required('iqr'):
                imgplot = BytesIO()
                chart_start = time.perf_counter()
                fig, ax = plt.subplots(figsize=(6, 4))
                boxplot_labels, boxplot_values = self._build_iqr_plot_payload(labels, values, sampled_group)
                render_iqr_boxplot(ax, boxplot_values, boxplot_labels)
                add_iqr_boxplot_legend(ax)
                apply_minimal_axis_style(ax, grid_axis='y')
                apply_shared_x_axis_label_strategy(ax, boxplot_labels, positions=list(range(1, len(boxplot_labels) + 1)))
                for line_spec in build_horizontal_limit_line_specs(USL, LSL):
                    ax.axhline(**line_spec)
                ax.set_xlabel('Group')
                ax.set_ylabel('Measurement')
                ax.set_title(f'{header} - IQR Outlier Detection')

                current_y_limits = ax.get_ylim()
                y_min, y_max = compute_scaled_y_limits(current_y_limits, self.summary_plot_scale)
                ax.set_ylim(y_min, y_max)

                fig.savefig(imgplot, format="png", bbox_inches='tight')
                self._record_stage_timing('chart_rendering', time.perf_counter() - chart_start)
                imgplot.seek(0)
                iqr_slot = panel_plan['image_slots']['iqr']
                write_start = time.perf_counter()
                summary_worksheet.insert_image(iqr_slot['row'], iqr_slot['col'], "", {'image_data': imgplot})
                self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)

                if self._check_canceled():
                    plt.close(fig)
                    return

                plt.close(fig)
            
            imgplot = BytesIO()
            # Plot the histogram with auto-defined bins
            histogram_figsize = (6, 4)
            chart_start = time.perf_counter()
            fig, ax = plt.subplots(figsize=histogram_figsize)
            render_histogram(ax, sampled_group)

            histogram_font_sizes = compute_histogram_font_sizes(
                histogram_figsize,
                has_table=True,
                readability_scale=self.summary_plot_scale,
            )
            histogram_table_layout = compute_histogram_table_layout(
                histogram_figsize,
                table_fontsize=histogram_font_sizes['table_fontsize'],
                has_table=True,
            )
            
            # Add a table with statistics
            table_data = build_histogram_table_data(summary_stats)

            ax_table = plt.table(
                cellText=table_data,
                colLabels=['Statistic', 'Value'],
                cellLoc='center',
                loc='right',
                bbox=[1, 0, histogram_table_layout['table_bbox_width'], 1],
            )

            # Format the table
            ax_table.auto_set_font_size(False)
            ax_table.set_fontsize(histogram_font_sizes['table_fontsize'])
            style_histogram_stats_table(
                ax_table,
                table_data,
                capability_badge=capability_badge,
                capability_row_badges=capability_row_badges,
            )

            density_curve = precomputed_density_curve
            if density_curve is None:
                density_curve = build_histogram_density_curve_payload(sampled_group['MEAS'], point_count=40 if self._optimization_toggles['chart_density_mode'] == 'reduced' else 100)
            if density_curve is not None:
                render_density_line(ax, density_curve['x'], density_curve['y'])
            
            # Add vertical lines for mean, LSL and USL
            mean_line_style = build_histogram_mean_line_style()
            ax.axvline(average, **mean_line_style)
            ax.axvline(USL, color=SUMMARY_PLOT_PALETTE['spec_limit'], linestyle='dashed', linewidth=1.0)
            ax.axvline(LSL, color=SUMMARY_PLOT_PALETTE['spec_limit'], linestyle='dashed', linewidth=1.0)

            # Set labels and title
            ax.set_xlabel('Measurement')
            ax.set_ylabel('Density')
            ax.set_title(f'{header}')
            apply_minimal_axis_style(ax, grid_axis='y')

            _, y_max = ax.get_ylim()
            annotation_box = {'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': SUMMARY_PLOT_PALETTE['annotation_box_edge'], 'alpha': 0.94}
            annotation_specs = build_histogram_annotation_specs(average, USL, LSL, y_max)
            annotation_fontsize = histogram_font_sizes['annotation_fontsize']
            render_histogram_annotations(
                ax,
                annotation_specs,
                annotation_fontsize=annotation_fontsize,
                annotation_box=annotation_box,
            )

            plt.subplots_adjust(right=histogram_table_layout['subplot_right'])
            
            fig.savefig(imgplot, format="png")
            self._record_stage_timing('chart_rendering', time.perf_counter() - chart_start)
            imgplot.seek(0)
            histogram_slot = panel_plan['image_slots']['histogram']
            write_start = time.perf_counter()
            summary_worksheet.insert_image(histogram_slot['row'], histogram_slot['col'], "", {'image_data': imgplot})
            self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)

            if self._check_canceled():
                plt.close(fig)
                return

            plt.close(fig)
            
            imgplot = BytesIO()
            apply_summary_plot_theme()
            
            chart_start = time.perf_counter()
            trend_payload = precomputed_trend_payload or build_trend_plot_payload(sampled_group)
            data_x = trend_payload['x']
            data_y = trend_payload['y']
            unique_labels = trend_payload['labels']

            fig, ax = plt.subplots(figsize=(6, 4))

            # Trend scatter plot
            if _HAS_SEABORN:
                sns.scatterplot(x=data_x, y=data_y, ax=ax, s=20, legend=False)
            else:
                ax.scatter(data_x, data_y, color=SUMMARY_PLOT_PALETTE['distribution_foreground'], marker='.')

            for line_spec in build_horizontal_limit_line_specs(USL, LSL):
                ax.axhline(**line_spec)
            ax.set_xlabel('Sample #')
            ax.set_ylabel('Measurement')
            ax.set_title(f'{header}')
            apply_minimal_axis_style(ax, grid_axis='y')

            apply_shared_x_axis_label_strategy(ax, unique_labels, positions=data_x)
            
            current_y_limits = ax.get_ylim()
            y_min, y_max = compute_scaled_y_limits(current_y_limits, self.summary_plot_scale)

            # Set y-axis limits using the Axes object
            ax.set_ylim(y_min, y_max)

            # Saving the plot to BytesIO
            imgplot = BytesIO()
            fig.savefig(imgplot, format="png", bbox_inches='tight')
            self._record_stage_timing('chart_rendering', time.perf_counter() - chart_start)
            imgplot.seek(0)
            trend_slot = panel_plan['image_slots']['trend']
            write_start = time.perf_counter()
            summary_worksheet.insert_image(trend_slot['row'], trend_slot['col'], "", {'image_data': imgplot})
            self._record_stage_timing('worksheet_writes', time.perf_counter() - write_start)
            plt.close(fig)
            
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
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
            custom_logger.CustomLogger(exception, reraise=False)
        self.error_occurred.emit(f"{context}: {exception}")

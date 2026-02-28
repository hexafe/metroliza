import logging
import warnings
import inspect
import os
import time
import matplotlib
import pandas as pd
import numpy as np

matplotlib.use('Agg')

import importlib.util
from io import BytesIO

import matplotlib.pyplot as plt
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal
from scipy.stats import ttest_ind

from modules.contracts import ExportRequest, validate_export_request
import modules.CustomLogger as custom_logger
from modules.db import execute_select_with_columns, read_sql_dataframe
from modules.excel_sheet_utils import unique_sheet_name
from modules.export_backends import ExcelExportBackend
from modules.google_drive_export import GoogleDriveAuthError, GoogleDriveExportError, upload_and_convert_workbook
from modules.log_context import (
    build_export_log_extra,
    build_google_conversion_log_extra,
    get_operation_logger,
)
from modules.export_summary_utils import (
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
        ('NOK %', round(summary_stats['nok_pct'], 2)),
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


def apply_summary_plot_theme():
    """Apply a consistent summary plotting theme."""
    if _HAS_SEABORN:
        sns.set_theme(style='white', context='paper')
    plt.rcParams.update({
        'font.size': 8,
        'axes.labelsize': 8,
        'axes.titlesize': 10,
        'axes.edgecolor': '#9aa0a6',
        'axes.linewidth': 0.8,
        'grid.color': '#d5d7db',
        'grid.linewidth': 0.6,
        'grid.alpha': 0.35,
    })


def apply_minimal_axis_style(ax, grid_axis='y'):
    """Apply a clean, minimal visual style on a chart axis."""
    ax.set_facecolor('white')
    ax.grid(True, axis=grid_axis, linestyle='-', alpha=0.25)
    if grid_axis == 'y':
        ax.grid(False, axis='x')
    elif grid_axis == 'x':
        ax.grid(False, axis='y')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#c2c6cc')
    ax.spines['bottom'].set_color('#c2c6cc')


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


def annotate_violin_group_stats(ax, labels, values):
    """Annotate min/mean/max and ±3σ markers for each violin group."""

    def _resolve_violin_annotation_style(group_count):
        safe_group_count = max(0, int(group_count))
        if safe_group_count <= 2:
            return {
                'font_size': 8,
                'minmax_marker_size': 24,
                'mean_marker_size': 30,
                'offsets': {
                    'min': (6, -12),
                    'mean': (6, 4),
                    'max': (6, 4),
                    'sigma_low': (6, -12),
                    'sigma_high': (6, 4),
                },
                'show_minmax': True,
                'sigma_line_width': 1.0,
            }

        if safe_group_count <= 6:
            return {
                'font_size': 6,
                'minmax_marker_size': 12,
                'mean_marker_size': 18,
                'offsets': {
                    'min': (4, -10),
                    'mean': (4, 2),
                    'max': (4, 2),
                    'sigma_low': (4, -10),
                    'sigma_high': (4, 2),
                },
                'show_minmax': True,
                'sigma_line_width': 0.9,
            }

        return {
            'font_size': 5,
            'minmax_marker_size': 8,
            'mean_marker_size': 12,
            'offsets': {
                'min': (2, -8),
                'mean': (2, 1),
                'max': (2, 1),
                'sigma_low': (2, -8),
                'sigma_high': (2, 1),
            },
            'show_minmax': False,
            'sigma_line_width': 0.7,
        }

    group_count = max(len(values), len(labels))
    style = _resolve_violin_annotation_style(group_count)
    for idx, group_values in enumerate(values):
        arr = np.asarray(group_values, dtype=float)
        if arr.size == 0:
            continue
        xpos = idx
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
        min_val = float(np.min(arr))
        max_val = float(np.max(arr))

        text_box = {'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': '#d0d0d0', 'alpha': 0.9}

        if style['show_minmax']:
            ax.scatter([xpos], [min_val], color='#4f4f4f', s=style['minmax_marker_size'], marker='v', zorder=4)
            ax.annotate(
                f"min={min_val:.3f}",
                (xpos, min_val),
                textcoords='offset points',
                xytext=style['offsets']['min'],
                fontsize=style['font_size'],
                bbox=text_box,
            )

        ax.scatter([xpos], [mean_val], color='#111111', s=style['mean_marker_size'], marker='o', zorder=4)
        ax.annotate(
            f"μ={mean_val:.3f}",
            (xpos, mean_val),
            textcoords='offset points',
            xytext=style['offsets']['mean'],
            fontsize=style['font_size'],
            bbox=text_box,
        )

        if style['show_minmax']:
            ax.scatter([xpos], [max_val], color='#4f4f4f', s=style['minmax_marker_size'], marker='^', zorder=4)
            ax.annotate(
                f"max={max_val:.3f}",
                (xpos, max_val),
                textcoords='offset points',
                xytext=style['offsets']['max'],
                fontsize=style['font_size'],
                bbox=text_box,
            )

        if std_val > 0:
            sigma_low = mean_val - (3 * std_val)
            sigma_high = mean_val + (3 * std_val)
            ax.vlines(
                xpos,
                sigma_low,
                sigma_high,
                colors='#7a7a7a',
                linestyles=':',
                linewidth=style['sigma_line_width'],
                alpha=0.8,
                zorder=3,
            )
            ax.annotate(
                f"-3σ={sigma_low:.3f}",
                (xpos, sigma_low),
                textcoords='offset points',
                xytext=style['offsets']['sigma_low'],
                fontsize=style['font_size'],
                color='#5a5a5a',
                bbox=text_box,
            )
            ax.annotate(
                f"+3σ={sigma_high:.3f}",
                (xpos, sigma_high),
                textcoords='offset points',
                xytext=style['offsets']['sigma_high'],
                fontsize=style['font_size'],
                color='#5a5a5a',
                bbox=text_box,
            )


def render_violin(ax, values, labels):
    if _HAS_SEABORN:
        sns.violinplot(data=values, inner=None, cut=0, linewidth=0.9, color='#b9d7ea', ax=ax)
        ax.set_xticks(range(len(labels)))
    else:
        ax.violinplot(values, showmeans=False, showmedians=False, showextrema=False)
        ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels)
    annotate_violin_group_stats(ax, labels, values)


def render_scatter(ax, data=None, x=None, y=None):
    if _HAS_SEABORN:
        sns.scatterplot(data=data, x=x, y=y, ax=ax, s=18, color='#2f6f9f', legend=False)
    else:
        ax.scatter(data[x], data[y], color='#2f6f9f', marker='.', s=18)


def render_histogram(ax, header_group):
    if _HAS_SEABORN:
        sns.histplot(data=header_group, x='MEAS', bins='auto', stat='density', alpha=0.7, color='#90b7d4', edgecolor='white', ax=ax)
    else:
        ax.hist(header_group['MEAS'], bins='auto', density=True, alpha=0.7, color='#90b7d4', edgecolor='white')


def render_iqr_boxplot(ax, values, labels):
    """Render a standard 1.5*IQR box plot used for outlier detection."""
    if not values:
        return

    positions = list(range(1, len(values) + 1))
    boxplot_kwargs = {
        'whis': 1.5,
        'patch_artist': True,
        'boxprops': {'facecolor': '#d9e9f5', 'edgecolor': '#4f6f8f', 'linewidth': 0.9},
        'medianprops': {'color': '#1f1f1f', 'linewidth': 1.0},
        'whiskerprops': {'color': '#4f6f8f', 'linewidth': 0.9},
        'capprops': {'color': '#4f6f8f', 'linewidth': 0.9},
        'flierprops': {'marker': 'o', 'markersize': 3, 'markerfacecolor': '#b23a48', 'markeredgecolor': '#b23a48', 'alpha': 0.8},
    }
    label_values = [str(label) for label in labels]
    try:
        ax.boxplot(values, tick_labels=label_values, **boxplot_kwargs)
    except TypeError:
        ax.boxplot(values, labels=label_values, **boxplot_kwargs)
    ax.set_xticks(positions)
    ax.set_xticklabels([str(label) for label in labels], rotation=45, ha='right')


def render_density_line(ax, x, p):
    if _HAS_SEABORN:
        sns.lineplot(x=x, y=p, color='#1f1f1f', linewidth=1.4, ax=ax)
    else:
        ax.plot(x, p, color='#1f1f1f', linewidth=1.4)


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
        self._prepared_grouping_df = None
        self.completion_metadata = {"local_xlsx_path": self.excel_file}
        self._exported_sheet_names = set()
        self._last_emitted_progress = -1

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
            self._exported_sheet_names.add(sheet_name)

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
            return f"{stage_line}\n{detail_line}\nETA --"

        remaining_headers = max(0, total_header_units - completed_header_units)
        detail_line = (
            f"Ref {ref_index}/{total_references}, "
            f"Headers remaining {remaining_headers}/{total_header_units}"
        )

        elapsed_seconds = max(0.0, time.perf_counter() - start_time)
        if completed_header_units < 5 or elapsed_seconds < 2.0:
            return f"{stage_line}\n{detail_line}\nETA --"

        headers_per_second = completed_header_units / elapsed_seconds if elapsed_seconds > 0 else 0.0
        if headers_per_second <= 0:
            return f"{stage_line}\n{detail_line}\nETA --"

        eta_seconds = remaining_headers / headers_per_second
        elapsed_display = self._format_elapsed_or_eta(elapsed_seconds)
        eta_display = self._format_elapsed_or_eta(eta_seconds)
        eta_line = f"{elapsed_display} elapsed, ETA {eta_display}"
        return f"{stage_line}\n{detail_line}\n{eta_line}"

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
        self.update_label.emit("Grouping data contains duplicate keys; using latest assignment.")

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
            self.update_label.emit("Export canceled.")
            self._log_export_stage("Export cancellation observed", stage="canceled", cancel_flag=True)
            self.canceled.emit()
            return True
        return False

    def run_export_pipeline(self, excel_writer):
        return run_export_steps(
            [
                lambda: (
                    self.update_label.emit("Exporting filtered data..."),
                    self._emit_stage_progress('preparing_query', 1.0),
                    self._emit_stage_progress('filtered_sheet_write', 0.0),
                    self.export_filtered_data(excel_writer),
                    self._emit_stage_progress('filtered_sheet_write', 1.0),
                ),
                lambda: (
                    self.update_label.emit("Building measurement sheets..."),
                    self._emit_stage_progress('measurement_sheets_charts', 0.0),
                    self.add_measurements_horizontal_sheet(excel_writer),
                    self._emit_stage_progress('measurement_sheets_charts', 1.0),
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
            self.update_label.emit(f"{base} ({detail})")
            return
        self.update_label.emit(base)

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

            self._emit_stage_progress('preparing_query', 0.0)
            self.update_label.emit("Preparing export...")
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
                    expected_sheet_names=sorted(self._exported_sheet_names),
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
                    self.update_label.emit(f"Warning: {warning}")

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
            self.update_label.emit("Export completed successfully.")
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
                self.update_label.emit(f"Warning: {e}")
                self.update_label.emit("Export completed successfully.")
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

    def add_measurements_horizontal_sheet(self, excel_writer):
        try:
            df = build_measurement_export_dataframe(read_sql_dataframe(self.db_file, self.filter_query))

            reference_groups = list(df.groupby('REFERENCE', as_index=False))
            total_references = len(reference_groups)
            total_header_units = sum(ref_group['HEADER - AX'].nunique(dropna=False) for _, ref_group in reference_groups)
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

                    header_group = self._sort_header_group(header_group)
                    base_col = col
                    if timing_enabled:
                        build_bundle_start = time.perf_counter()
                    write_bundle = _build_measurement_write_bundle_cached(header, header_group, base_col, cache=optimization_cache)
                    if timing_enabled:
                        build_bundle_elapsed += time.perf_counter() - build_bundle_start
                    header_plan = write_bundle['header_plan']
                    measurement_plan = write_measurement_block(worksheet, write_bundle, formats, base_col=base_col)

                    col += 3
                    header_col_end = col - 1
                    worksheet.set_column(header_col_end, header_col_end, None, cell_format=formats['border'])

                    if timing_enabled:
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

                    if timing_enabled:
                        chart_insert_elapsed += time.perf_counter() - chart_insert_start

                    if self._check_canceled():
                        return

                    if self.generate_summary_sheet:
                        self.summary_sheet_fill(summary_worksheet, header, header_group, col)
                        if self._check_canceled():
                            return

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

                worksheet.freeze_panes(12, 0)

            if total_references == 0 or total_header_units == 0:
                self._emit_stage_progress('measurement_sheets_charts', 1.0)
        except Exception as e:
            self.log_and_exit(e)

    def export_filtered_data(self, excel_writer):
        try:
            if self._check_canceled():
                return
            data, column_names = execute_export_query(self.db_file, self.filter_query)
            export_df = build_export_dataframe(data, column_names)
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
            header_group = self._ensure_sample_number_column(header_group)
            imgplot = BytesIO()
            limits = resolve_nominal_and_limits(header_group)
            nom = limits['nom']
            USL = limits['usl']
            LSL = limits['lsl']

            summary_stats = compute_measurement_summary(header_group, usl=USL, lsl=LSL, nom=nom)
            average = summary_stats['average']
            
            apply_summary_plot_theme()
            fig, ax = plt.subplots(figsize=(6, 4))
            
            grouping_df = self.prepared_grouping_df
            header_group, grouping_applied = self._apply_group_assignments(header_group, grouping_df)
            if grouping_applied:
                labels, values, can_render_violin = self._build_violin_payload(
                    header_group,
                    'GROUP',
                    self.violin_plot_min_samplesize,
                )
                if can_render_violin:
                    render_violin(ax, values, labels)
                else:
                    render_scatter(ax, data=header_group, x='GROUP', y='MEAS')
            else:
                labels, values, can_render_violin = self._build_violin_payload(
                    header_group,
                    'SAMPLE_NUMBER',
                    self.violin_plot_min_samplesize,
                )
                if can_render_violin:
                    render_violin(ax, values, labels)
                else:
                    render_scatter(ax, data=header_group, x='SAMPLE_NUMBER', y='MEAS')

            apply_minimal_axis_style(ax, grid_axis='y')
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
            
            imgplot.seek(0)
            
            summary_anchors = build_summary_image_anchor_plan(col)
            panel_plan = build_summary_panel_write_plan(summary_anchors, header)
            header_cell = panel_plan['header_cell']
            summary_worksheet.write(header_cell['row'], header_cell['col'], header_cell['value'])
            distribution_slot = panel_plan['image_slots']['distribution']
            summary_worksheet.insert_image(
                distribution_slot['row'],
                distribution_slot['col'],
                "",
                {'image_data': imgplot},
            )

            if self._check_canceled():
                plt.close(fig)
                return

            plt.close(fig)

            if self._check_canceled():
                return

            imgplot = BytesIO()
            fig, ax = plt.subplots(figsize=(6, 4))
            boxplot_labels = labels if labels else ['All']
            boxplot_values = values if values else [list(header_group['MEAS'])]
            render_iqr_boxplot(ax, boxplot_values, boxplot_labels)
            apply_minimal_axis_style(ax, grid_axis='y')
            for line_spec in build_horizontal_limit_line_specs(USL, LSL):
                ax.axhline(**line_spec)
            ax.set_xlabel('Group')
            ax.set_ylabel('Measurement')
            ax.set_title(f'{header} - IQR Outlier Detection')

            current_y_limits = ax.get_ylim()
            y_min, y_max = compute_scaled_y_limits(current_y_limits, self.summary_plot_scale)
            ax.set_ylim(y_min, y_max)

            fig.savefig(imgplot, format="png", bbox_inches='tight')
            imgplot.seek(0)
            iqr_slot = panel_plan['image_slots']['iqr']
            summary_worksheet.insert_image(iqr_slot['row'], iqr_slot['col'], "", {'image_data': imgplot})

            if self._check_canceled():
                plt.close(fig)
                return

            plt.close(fig)
            
            imgplot = BytesIO()
            # Plot the histogram with auto-defined bins
            fig, ax = plt.subplots(figsize=(6, 4))
            render_histogram(ax, header_group)
            
            # Add a table with statistics
            table_data = build_histogram_table_data(summary_stats)

            ax_table = plt.table(cellText=table_data,
                            colLabels=['Statistic', 'Value'],
                            cellLoc='center',
                            loc='right',
                            bbox=[1, 0, 0.3, 1])

            # Format the table
            ax_table.auto_set_font_size(False)
            ax_table.set_fontsize(8)

            density_curve = build_histogram_density_curve_payload(header_group['MEAS'])
            if density_curve is not None:
                render_density_line(ax, density_curve['x'], density_curve['y'])
            
            # Add vertical lines for mean, LSL and USL
            ax.axvline(average, color='#9b1c1c', linestyle='dashed', linewidth=1.0)
            ax.axvline(USL, color='#1f7a4d', linestyle='dashed', linewidth=1.0)
            ax.axvline(LSL, color='#1f7a4d', linestyle='dashed', linewidth=1.0)

            # Set labels and title
            ax.set_xlabel('Measurement')
            ax.set_ylabel('Density')
            ax.set_title(f'{header}')
            apply_minimal_axis_style(ax, grid_axis='y')

            _, y_max = ax.get_ylim()
            annotation_box = {'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': '#d0d0d0', 'alpha': 0.9}
            for annotation in build_histogram_annotation_specs(average, USL, LSL, y_max):
                ax.text(
                    annotation['x'],
                    annotation['y'],
                    annotation['text'],
                    color=annotation['color'],
                    ha=annotation['ha'],
                    va='top',
                    fontsize=7,
                    bbox=annotation_box,
                )

            plt.subplots_adjust(right=0.75)
            
            fig.savefig(imgplot, format="png")
            imgplot.seek(0)
            histogram_slot = panel_plan['image_slots']['histogram']
            summary_worksheet.insert_image(histogram_slot['row'], histogram_slot['col'], "", {'image_data': imgplot})

            if self._check_canceled():
                plt.close(fig)
                return

            plt.close(fig)
            
            imgplot = BytesIO()
            apply_summary_plot_theme()
            
            trend_payload = build_trend_plot_payload(header_group)
            data_x = trend_payload['x']
            data_y = trend_payload['y']
            unique_labels = trend_payload['labels']

            fig, ax = plt.subplots(figsize=(6, 4))

            # Trend scatter plot
            if _HAS_SEABORN:
                sns.scatterplot(x=data_x, y=data_y, ax=ax, s=20, legend=False)
            else:
                ax.scatter(data_x, data_y, color='blue', marker='.')

            for line_spec in build_horizontal_limit_line_specs(USL, LSL):
                ax.axhline(**line_spec)
            ax.set_xlabel('Sample #')
            ax.set_ylabel('Measurement')
            ax.set_title(f'{header}')
            apply_minimal_axis_style(ax, grid_axis='y')

            # Set ticks and labels
            ax.set_xticks(data_x)
            ax.set_xticklabels(unique_labels)

            # Rotate the tick labels for better visibility
            plt.xticks(rotation=90)
            
            current_y_limits = ax.get_ylim()
            y_min, y_max = compute_scaled_y_limits(current_y_limits, self.summary_plot_scale)

            # Set y-axis limits using the Axes object
            ax.set_ylim(y_min, y_max)

            # Saving the plot to BytesIO
            imgplot = BytesIO()
            fig.savefig(imgplot, format="png", bbox_inches='tight')
            imgplot.seek(0)
            trend_slot = panel_plan['image_slots']['trend']
            summary_worksheet.insert_image(trend_slot['row'], trend_slot['col'], "", {'image_data': imgplot})
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

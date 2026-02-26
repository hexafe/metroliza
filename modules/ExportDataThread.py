import hashlib
import logging
import warnings
import matplotlib
import pandas as pd
import numpy as np

matplotlib.use('Agg')

import importlib.util
from io import BytesIO

import matplotlib.pyplot as plt
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal
from scipy.stats import norm, ttest_ind

from modules.contracts import ExportRequest, validate_export_request
from modules.CustomLogger import CustomLogger
from modules.db import execute_select_with_columns, read_sql_dataframe
from modules.excel_sheet_utils import unique_sheet_name
from modules.export_backends import ExcelExportBackend
from modules.google_drive_export import GoogleDriveExportError, upload_and_convert_workbook
from modules.export_summary_utils import compute_measurement_summary, resolve_nominal_and_limits
from modules.export_chart_writer import (
    build_measurement_chart_format_policy as _build_measurement_chart_format_policy,
    build_measurement_chart_range_specs as _build_measurement_chart_range_specs,
    build_measurement_chart_series_specs as _build_measurement_chart_series_specs,
    build_sheet_series_range as _build_sheet_series_range,
    insert_measurement_chart,
)
from modules.export_query_service import (
    build_export_dataframe as _build_export_dataframe,
    build_measurement_export_dataframe,
    execute_export_query as _execute_export_query,
)
from modules.export_sheet_writer import (
    build_measurement_block_plan as _build_measurement_block_plan,
    build_measurement_header_block_plan as _build_measurement_header_block_plan,
    build_measurement_stat_formulas as _build_measurement_stat_formulas,
    build_measurement_stat_row_specs as _build_measurement_stat_row_specs,
    build_measurement_write_bundle as _build_measurement_write_bundle,
    build_spec_limit_anchor_rows as _build_spec_limit_anchor_rows,
    create_measurement_formats,
    write_measurement_block,
)

_HAS_SEABORN = importlib.util.find_spec('seaborn') is not None
if _HAS_SEABORN:
    import seaborn as sns


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


def build_measurement_write_bundle(header, header_group, base_col):
    return _build_measurement_write_bundle(header, header_group, base_col)


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
    """Return labels with repeated values blanked for clearer x-axis display."""
    seen = set()
    sparse_labels = []
    for label in labels:
        if label in seen:
            sparse_labels.append('')
            continue
        seen.add(label)
        sparse_labels.append(label)
    return sparse_labels


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


def build_trend_plot_payload(header_group):
    """Return x/y points and sparse labels for the summary trend plot."""
    measurements = list(header_group['MEAS'])
    sample_labels = list(header_group['SAMPLE_NUMBER'])
    return {
        'x': list(range(len(measurements))),
        'y': measurements,
        'labels': build_sparse_unique_labels(sample_labels),
    }


def build_histogram_density_curve_payload(measurements, point_count=100):
    """Return x/y density curve data for histogram overlays, if available."""
    mu, std = norm.fit(measurements)
    if std <= 0:
        return None

    x_min = float(np.min(measurements))
    x_max = float(np.max(measurements))
    x_values = np.linspace(x_min, x_max, point_count)
    y_values = norm.pdf(x_values, mu, std)
    return {
        'x': x_values,
        'y': y_values,
    }


def compute_scaled_y_limits(current_limits, scale_factor):
    """Return y-axis limits expanded by a symmetric scale factor."""
    y_min, y_max = current_limits
    data_range = y_max - y_min
    padding = scale_factor * data_range / 2
    return y_min - padding, y_max + padding


def build_summary_sheet_position_plan(base_col):
    """Return summary sheet anchors aligned with the 3-column measurement block layout."""
    block_index = max((base_col - 3) // 3, 0)
    row = block_index * 20
    return {
        'row': row,
        'column': 0,
        'header_row': row,
        'image_row': row + 1,
    }


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

        ax.scatter([xpos], [min_val], color='#4f4f4f', s=12, marker='v', zorder=4)
        ax.annotate(f"min={min_val:.3f}", (xpos, min_val), textcoords='offset points', xytext=(4, -10), fontsize=6, bbox=text_box)

        ax.scatter([xpos], [mean_val], color='#111111', s=18, marker='o', zorder=4)
        ax.annotate(f"μ={mean_val:.3f}", (xpos, mean_val), textcoords='offset points', xytext=(4, 2), fontsize=6, bbox=text_box)

        ax.scatter([xpos], [max_val], color='#4f4f4f', s=12, marker='^', zorder=4)
        ax.annotate(f"max={max_val:.3f}", (xpos, max_val), textcoords='offset points', xytext=(4, 2), fontsize=6, bbox=text_box)

        if std_val > 0:
            sigma_low = mean_val - (3 * std_val)
            sigma_high = mean_val + (3 * std_val)
            ax.vlines(
                xpos,
                sigma_low,
                sigma_high,
                colors='#7a7a7a',
                linestyles=':',
                linewidth=0.9,
                alpha=0.8,
                zorder=3,
            )
            ax.annotate(f"-3σ={sigma_low:.3f}", (xpos, sigma_low), textcoords='offset points', xytext=(4, -10), fontsize=6, color='#5a5a5a', bbox=text_box)
            ax.annotate(f"+3σ={sigma_high:.3f}", (xpos, sigma_high), textcoords='offset points', xytext=(4, 2), fontsize=6, color='#5a5a5a', bbox=text_box)


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
    update_label = pyqtSignal(str)
    update_progress = pyqtSignal(int)
    finished = pyqtSignal()
    canceled = pyqtSignal()

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

    @staticmethod
    def _add_group_key(df):
        composite_key = ['REFERENCE', 'FILELOC', 'FILENAME', 'DATE', 'SAMPLE_NUMBER']
        if not all(column in df.columns for column in composite_key):
            return df

        keyed_df = df.copy()
        raw_key = keyed_df[composite_key].fillna('').astype(str).agg('|'.join, axis=1)
        keyed_df['GROUP_KEY'] = raw_key.apply(lambda value: hashlib.sha1(value.encode('utf-8')).hexdigest())
        return keyed_df

    def _prepare_grouping_df(self):
        if not isinstance(self.df_for_grouping, pd.DataFrame) or self.df_for_grouping.empty:
            return None

        if 'GROUP' not in self.df_for_grouping.columns:
            return None

        optional_cols = ['REPORT_ID', 'REFERENCE', 'FILELOC', 'FILENAME', 'DATE', 'SAMPLE_NUMBER']
        available_cols = [column for column in optional_cols if column in self.df_for_grouping.columns]

        grouping_df = self.df_for_grouping[available_cols + ['GROUP']].copy()
        grouping_df = self._add_group_key(grouping_df)
        return grouping_df

    def _warn_duplicate_group_assignments(self, grouping_df, merge_keys):
        duplicated_mask = grouping_df.duplicated(subset=merge_keys, keep=False)
        duplicate_count = int(duplicated_mask.sum())
        if duplicate_count == 0:
            return

        message = (
            f"Detected {duplicate_count} grouping assignment rows with duplicate merge key(s) "
            f"{merge_keys}. Keeping the latest assignment per key."
        )
        logging.warning(message)
        self.update_label.emit("Grouping data contains duplicate keys; using latest assignment.")

    def _apply_group_assignments(self, header_group, grouping_df):
        if grouping_df is None:
            return header_group, False

        keyed_header = self._add_group_key(header_group)
        merge_keys = self._resolve_group_merge_keys(keyed_header, grouping_df)
        if merge_keys is None:
            return keyed_header, False

        self._warn_duplicate_group_assignments(grouping_df, merge_keys)
        deduped_grouping_df = grouping_df.drop_duplicates(subset=merge_keys, keep='last')
        merge_projection = deduped_grouping_df[merge_keys + ['GROUP']]
        merged_group = pd.merge(keyed_header, merge_projection, on=merge_keys, how='left')
        merged_group['GROUP'] = merged_group['GROUP'].fillna('UNGROUPED')
        return merged_group, True

    @staticmethod
    def _keys_have_usable_values(df, keys):
        if df.empty:
            return False

        required = [key for key in keys if key in df.columns]
        if len(required) != len(keys):
            return False

        normalized = df[required].copy()
        for key in required:
            normalized[key] = normalized[key].apply(
                lambda value: str(value).strip() if pd.notna(value) else ''
            )

        return (normalized != '').all(axis=1).any()

    @staticmethod
    def _resolve_group_merge_keys(header_group, grouping_df):
        if (
            ExportDataThread._keys_have_usable_values(header_group, ['GROUP_KEY'])
            and ExportDataThread._keys_have_usable_values(grouping_df, ['GROUP_KEY'])
        ):
            return ['GROUP_KEY']

        if (
            ExportDataThread._keys_have_usable_values(header_group, ['REPORT_ID'])
            and ExportDataThread._keys_have_usable_values(grouping_df, ['REPORT_ID'])
        ):
            return ['REPORT_ID']

        composite_key = ['REFERENCE', 'FILELOC', 'FILENAME', 'DATE', 'SAMPLE_NUMBER']
        if (
            ExportDataThread._keys_have_usable_values(header_group, composite_key)
            and ExportDataThread._keys_have_usable_values(grouping_df, composite_key)
        ):
            return composite_key

        fallback_key = ['REFERENCE', 'SAMPLE_NUMBER']
        if (
            ExportDataThread._keys_have_usable_values(header_group, fallback_key)
            and ExportDataThread._keys_have_usable_values(grouping_df, fallback_key)
        ):
            return fallback_key

        return None
        

    def stop_exporting(self):
        self.export_canceled = True

    def _check_canceled(self):
        if self.export_canceled:
            self.update_label.emit("Export canceled.")
            self.canceled.emit()
            return True
        return False

    def run_export_pipeline(self, excel_writer):
        return run_export_steps(
            [
                lambda: (
                    self.update_label.emit("Exporting filtered data..."),
                    self.export_filtered_data(excel_writer),
                    self.update_progress.emit(50),
                ),
                lambda: (
                    self.update_label.emit("Building measurement sheets..."),
                    self.add_measurements_horizontal_sheet(excel_writer),
                    self.update_progress.emit(100),
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

    def run(self):
        try:
            if self._check_canceled():
                return

            self.update_progress.emit(0)
            self.update_label.emit("Preparing export...")

            backend = self.get_export_backend()
            self._active_backend = backend
            completed = backend.run(self)
            if not completed:
                return

            if self.export_target == "google_sheets_drive_convert":
                self.update_label.emit("Uploading workbook to Google Drive for Sheets conversion...")
                conversion = upload_and_convert_workbook(self.excel_file)
                self.completion_metadata.update(
                    {
                        "converted_file_id": conversion.file_id,
                        "converted_url": conversion.web_url,
                    }
                )
                self.update_label.emit(
                    f"Google Sheets conversion ready: {conversion.web_url} (local fallback: {self.excel_file})"
                )

            self.update_label.emit("Export completed successfully.")
            self.finished.emit()
            QCoreApplication.processEvents()
        except GoogleDriveExportError as e:
            self.log_and_exit(e)
        except Exception as e:
            self.log_and_exit(e)

    def add_measurements_horizontal_sheet(self, excel_writer):
        try:
            df = build_measurement_export_dataframe(read_sql_dataframe(self.db_file, self.filter_query))

            reference_groups = df.groupby('REFERENCE', as_index=False)
            backend = self._active_backend or self.get_export_backend()
            workbook = backend.get_workbook(excel_writer)
            used_sheet_names = backend.list_sheet_names(excel_writer)

            formats = create_measurement_formats(workbook)
            column_width = 12
            max_col = len(df['HEADER - AX'].unique()) * 3

            for (ref, ref_group) in reference_groups:
                if self._check_canceled():
                    return

                col = 0
                safe_ref_sheet_name = unique_sheet_name(ref, used_sheet_names)
                worksheet = workbook.add_worksheet(safe_ref_sheet_name)
                summary_worksheet = None
                if self.generate_summary_sheet:
                    summary_sheet_name = unique_sheet_name(f"{safe_ref_sheet_name}_summary", used_sheet_names)
                    summary_worksheet = workbook.add_worksheet(summary_sheet_name)

                worksheet.set_column(0, max_col, column_width, cell_format=formats['default'])

                header_groups = ref_group.groupby('HEADER - AX', as_index=False)
                for (header, header_group) in header_groups:
                    if self._check_canceled():
                        return

                    header_group = self._sort_header_group(header_group)
                    base_col = col
                    write_bundle = _build_measurement_write_bundle(header, header_group, base_col)
                    header_plan = write_bundle['header_plan']
                    measurement_plan = write_measurement_block(worksheet, write_bundle, formats, base_col=base_col)

                    col += 3
                    header_col_end = col - 1
                    worksheet.set_column(header_col_end, header_col_end, None, cell_format=formats['border'])

                    insert_measurement_chart(
                        workbook,
                        worksheet,
                        chart_type=self.selected_export_type,
                        header=header,
                        sheet_name=safe_ref_sheet_name,
                        measurement_plan=measurement_plan,
                        chart_anchor_col=col - 3,
                    )

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

                worksheet.freeze_panes(12, 0)
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
            ax.axhline(y=USL, color='#9b1c1c', linestyle='--', linewidth=1.0)
            ax.axhline(y=LSL, color='#9b1c1c', linestyle='--', linewidth=1.0)

            current_y_limits = ax.get_ylim()
            y_min, y_max = compute_scaled_y_limits(current_y_limits, self.summary_plot_scale)

            # Set y-axis limits using the Axes object
            ax.set_ylim(y_min, y_max)

            ax.set_xlabel('Sample #')
            ax.set_ylabel('Measurement')
            ax.set_title(f'{header}')
            fig.savefig(imgplot, format="png")
            
            imgplot.seek(0)
            
            summary_position = build_summary_sheet_position_plan(col)
            summary_worksheet.write(summary_position['header_row'], summary_position['column'], header)
            summary_worksheet.insert_image(summary_position['image_row'], summary_position['column'], "", {'image_data': imgplot})

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
            ax.axhline(y=USL, color='#9b1c1c', linestyle='--', linewidth=1.0)
            ax.axhline(y=LSL, color='#9b1c1c', linestyle='--', linewidth=1.0)
            ax.set_xlabel('Group')
            ax.set_ylabel('Measurement')
            ax.set_title(f'{header} - IQR Outlier Detection')

            current_y_limits = ax.get_ylim()
            y_min, y_max = compute_scaled_y_limits(current_y_limits, self.summary_plot_scale)
            ax.set_ylim(y_min, y_max)

            fig.savefig(imgplot, format="png", bbox_inches='tight')
            imgplot.seek(0)
            summary_worksheet.insert_image(summary_position['image_row'], 9, "", {'image_data': imgplot})

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

            y_min, y_max = ax.get_ylim()
            annotation_box = {'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': '#d0d0d0', 'alpha': 0.9}
            ax.text(average, y_max*0.95, f'μ={average:.3f}', color='#9b1c1c', ha='left', va='top', fontsize=7, bbox=annotation_box)
            ax.text(USL, y_max*0.9, f'USL={USL:.3f}', color='#1f7a4d', ha='right', va='top', fontsize=7, bbox=annotation_box)
            ax.text(LSL, y_max*0.85, f'LSL={LSL:.3f}', color='#1f7a4d', ha='left', va='top', fontsize=7, bbox=annotation_box)

            plt.subplots_adjust(right=0.75)
            
            fig.savefig(imgplot, format="png")
            imgplot.seek(0)
            summary_worksheet.insert_image(summary_position['image_row'], 19, "", {'image_data': imgplot})

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

            ax.axhline(y=USL, color='#9b1c1c', linestyle='--', linewidth=1.0)
            ax.axhline(y=LSL, color='#9b1c1c', linestyle='--', linewidth=1.0)
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
            summary_worksheet.insert_image(summary_position['image_row'], 29, "", {'image_data': imgplot})
            plt.close(fig)
            
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)

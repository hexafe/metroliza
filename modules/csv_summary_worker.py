"""Worker-side CSV summary export logic separated from dialog UI concerns."""

from concurrent.futures import ProcessPoolExecutor
import logging
from pathlib import Path
import re
import time

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell

from modules.csv_summary_utils import (
    compute_column_summary_stats,
    estimate_enabled_chart_count,
    normalize_plot_toggles,
)
from modules.csv_summary_worker_helpers import (
    compute_boxplot_summary as _compute_boxplot_summary,
    compute_histogram_payload as _compute_histogram_payload,
)
from modules.excel_sheet_utils import unique_sheet_name
from modules.progress_status import build_three_line_status
from modules.stats_utils import is_one_sided_geometric_tolerance


logger = logging.getLogger(__name__)

class DataProcessingThread(QThread):
    """Background worker that transforms CSV data into an Excel summary file.

    Key state includes selected columns, cancellation status, plot toggles, and
    stage timings used to tune chart-generation behavior across long runs.
    """

    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str)

    def __init__(self, selected_indexes, selected_data_columns, input_file, output_file, data_frame, csv_config=None, column_spec_limits=None, plot_toggles=None, summary_only=False):
        super().__init__()
        self.selected_indexes = selected_indexes
        self.selected_data_columns = selected_data_columns
        self.input_file = input_file
        self.output_file = output_file
        self.data_frame = data_frame
        self.canceled = False
        self.csv_config = csv_config or {}
        self.column_spec_limits = column_spec_limits or {}
        self.plot_toggles = normalize_plot_toggles(selected_data_columns, plot_toggles)
        self.summary_only = bool(summary_only)
        self.stage_timings = {
            'transform_grouping': 0.0,
            'chart_rendering': 0.0,
            'worksheet_writes': 0.0,
        }
        self.optimization_toggles = {
            'chart_density_mode': 'full',
            'defer_non_essential_charts': False,
            'enable_chart_multiprocessing': self.csv_config.get('enable_chart_multiprocessing', False),
        }
        self._chart_executor = None

    def _ensure_chart_executor(self):
        """Create or return the chart process executor when enabled."""
        if not self.optimization_toggles.get('enable_chart_multiprocessing', False):
            return None
        if self._chart_executor is None:
            self._chart_executor = ProcessPoolExecutor(max_workers=1)
        return self._chart_executor

    def _shutdown_chart_executor(self):
        """Shut down the chart executor to avoid orphaned worker processes."""
        if self._chart_executor is not None:
            try:
                self._chart_executor.shutdown(wait=True, cancel_futures=True)
            except Exception:
                logger.debug("Failed to cleanly shutdown chart executor.", exc_info=True)
            finally:
                self._chart_executor = None

    def _record_stage_timing(self, stage_name, elapsed):
        if stage_name in self.stage_timings:
            self.stage_timings[stage_name] += max(0.0, float(elapsed))

    def _apply_bottleneck_optimizations(self):
        total = sum(self.stage_timings.values())
        if total <= 0.0:
            return
        chart_share = self.stage_timings['chart_rendering'] / total
        if chart_share >= 0.65:
            self.optimization_toggles['chart_density_mode'] = 'reduced'
            self.optimization_toggles['defer_non_essential_charts'] = True
        elif chart_share >= 0.45:
            self.optimization_toggles['chart_density_mode'] = 'reduced'

    def _downsample_for_chart(self, selected_data, data_column):
        sample_limit = 1200 if self.optimization_toggles['chart_density_mode'] == 'reduced' else 4000
        row_count = len(selected_data)
        if row_count <= sample_limit:
            return selected_data
        stride = max(1, int(row_count / sample_limit))
        return selected_data.iloc[::stride].copy()

    @staticmethod
    def _format_eta(eta_seconds):
        if eta_seconds is None:
            return "ETA --"
        rounded_seconds = max(0, int(round(float(eta_seconds))))
        minutes, seconds = divmod(rounded_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"ETA {hours}:{minutes:02d}:{seconds:02d}"
        return f"ETA {minutes}:{seconds:02d}"

    def _estimate_eta_seconds(self, start_time, processed_columns, total_columns):
        if processed_columns <= 0 or total_columns <= 0:
            return None
        elapsed = max(0.0, time.perf_counter() - start_time)
        average_per_column = elapsed / processed_columns
        remaining_columns = max(0, total_columns - processed_columns)
        return average_per_column * remaining_columns

    def write_summary_data(self, worksheet, data_column, selected_data, spec_limits):
        """Write formulas and statistics rows for one data-column summary block."""
        col = selected_data.shape[1]
        nom = spec_limits.get('nom', 0.0)
        usl_offset = spec_limits.get('usl', 0.0)
        lsl_offset = spec_limits.get('lsl', 0.0)

        worksheet.write(0, col + 2, 'NOM')
        worksheet.write(0, col + 3, nom)

        worksheet.write(1, col + 2, 'USL')
        worksheet.write(1, col + 3, usl_offset)
        USL_cell = xl_rowcol_to_cell(1, col + 3, row_abs=True, col_abs=True)

        worksheet.write(2, col + 2, 'LSL')
        worksheet.write(2, col + 3, lsl_offset)
        LSL_cell = xl_rowcol_to_cell(2, col + 3, row_abs=True, col_abs=True)

        worksheet.write(3, col + 2, 'MIN')
        min_formula = f"=ROUND(MIN({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1}), 3)"
        worksheet.write_formula(3, col + 3, min_formula)

        worksheet.write(4, col + 2, 'AVG')
        avg_formula = f"=ROUND(AVERAGE({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1}), 3)"
        worksheet.write_formula(4, col + 3, avg_formula)

        worksheet.write(5, col + 2, 'MAX')
        max_formula = f"=ROUND(MAX({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1}), 3)"
        worksheet.write_formula(5, col + 3, max_formula)

        worksheet.write(6, col + 2, 'STD')
        std_formula = f"=ROUND(STDEV({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1}), 3)"
        worksheet.write_formula(6, col + 3, std_formula)

        worksheet.write(7, col + 2, 'Cp')
        summary_col = xl_col_to_name(col + 3)
        USL_formula = f"({summary_col}1 + {summary_col}2)"
        LSL_formula = f"({summary_col}1 + {summary_col}3)"
        sigma_formula = f"({summary_col}7)"
        if is_one_sided_geometric_tolerance(nom, lsl_offset):
            cp_formula = '="N/A"'
        else:
            cp_formula = f"=ROUND(({USL_formula} - {LSL_formula})/(6 * {sigma_formula}), 3)"
        worksheet.write_formula(7, col + 3, cp_formula)

        worksheet.write(8, col + 2, 'Cpk')
        average_formula = f"({summary_col}5)"
        if is_one_sided_geometric_tolerance(nom, lsl_offset):
            cpk_formula = f"=ROUND(({USL_formula} - {average_formula})/(3 * {sigma_formula}), 3)"
        else:
            cpk_formula = f"=ROUND(MIN( ({USL_formula} - {average_formula})/(3 * {sigma_formula}), ({average_formula} - {LSL_formula})/(3 * {sigma_formula}) ), 3)"
        worksheet.write_formula(8, col + 3, cpk_formula)

        worksheet.write(9, col + 2, "Sample size")
        count_formula = f"=COUNT({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1})"
        worksheet.write_formula(9, col + 3, count_formula)

        return col, USL_cell, LSL_cell

    def apply_conditional_formatting(self, worksheet, selected_data, data_column, col, USL_cell, LSL_cell, writer):
        """Apply tolerance-driven highlighting for out-of-spec measurement cells."""
        # Define the format for conditional formatting (highlight cells in red)
        red_format = writer.book.add_format({'bg_color': 'red', 'font_color': 'white', 'align': 'center', 'valign': 'vcenter', 'right': 1, 'num_format': '#,##0.000'})

        # Apply conditional formatting to highlight cells greater than USL in red
        worksheet.conditional_format(1, col - 1, len(selected_data[data_column]), col - 1,
                                    {'type': 'cell', 'criteria': '>', 'value': USL_cell, 'format': red_format})

        # Apply conditional formatting to highlight cells lower than LSL in red
        worksheet.conditional_format(1, col - 1, len(selected_data[data_column]), col - 1,
                                    {'type': 'cell', 'criteria': '<', 'value': LSL_cell, 'format': red_format})

    def add_xy_chart(self, worksheet, data_column, col, selected_data, writer, sheet_name):
        """Insert a scatter chart for one measurement column."""
        # Create an XY chart object
        chart = writer.book.add_chart({'type': 'scatter'})

        # Add data to the chart with the specified x and y ranges
        num_rows = len(selected_data[data_column])
        x_range = f"={sheet_name}!${xl_col_to_name(0)}$2:${xl_col_to_name(0)}${num_rows + 1}"
        y_range = f"={sheet_name}!${xl_col_to_name(col - 1)}$2:${xl_col_to_name(col - 1)}${num_rows + 1}"

        # Add the series to the chart
        chart.add_series({
            'name': data_column,
            'categories': x_range,
            'values': y_range,
        })

        # Configure the chart properties
        chart.set_title({'name': f'{sheet_name}'})
        chart.set_x_axis({
            # 'name': 'Date',
            # 'date_axis': True,
            'min': 0,
            'max': num_rows + 1,
        })
        chart.set_y_axis({
            'name': f'{sheet_name}',
            'major_gridlines': {
                'visible': False,
            }
        })

        chart.set_legend({'position': 'none'})

        # Insert the chart into the worksheet.
        worksheet.insert_chart(12, col + 5, chart)



    def add_histogram_chart(self, worksheet, data_column, col, selected_data, writer, sheet_name):
        """Generate histogram data and insert a chart for one data column."""
        numeric_series = pd.to_numeric(selected_data[data_column], errors='coerce').dropna()
        if numeric_series.empty:
            return

        histogram_col_start = col + 6
        worksheet.write(0, histogram_col_start, 'Histogram Bin')
        worksheet.write(0, histogram_col_start + 1, 'Count')

        max_bins = 8 if self.optimization_toggles['chart_density_mode'] == 'reduced' else 12
        bin_count = min(max_bins, max(5, int(len(numeric_series) ** 0.5)))

        histogram_rows = None
        mp_enabled = self.optimization_toggles['enable_chart_multiprocessing'] and len(numeric_series) >= 2500
        if mp_enabled:
            try:
                pool = self._ensure_chart_executor()
                if pool is not None:
                    histogram_rows = pool.submit(_compute_histogram_payload, numeric_series.tolist(), bin_count).result()
            except Exception:
                histogram_rows = None

        if histogram_rows is None:
            histogram_rows = _compute_histogram_payload(numeric_series.tolist(), bin_count)

        for row_index, (bin_interval, count) in enumerate(histogram_rows, start=1):
            worksheet.write(row_index, histogram_col_start, bin_interval)
            worksheet.write(row_index, histogram_col_start + 1, count)

        chart = writer.book.add_chart({'type': 'column'})
        chart.add_series({
            'name': f'{data_column} histogram',
            'categories': [sheet_name, 1, histogram_col_start, len(histogram_rows), histogram_col_start],
            'values': [sheet_name, 1, histogram_col_start + 1, len(histogram_rows), histogram_col_start + 1],
            'gap': 2,
        })
        chart.set_title({'name': f'{sheet_name} histogram'})
        chart.set_x_axis({'name': 'Bins'})
        chart.set_y_axis({'name': 'Count'})
        chart.set_legend({'position': 'none'})
        worksheet.insert_chart(30, col + 5, chart)

    def add_boxplot_chart(self, worksheet, data_column, col, selected_data, writer, sheet_name):
        """Create a boxplot-style visualization from summary statistics."""
        numeric_series = pd.to_numeric(selected_data[data_column], errors='coerce').dropna()
        if numeric_series.empty:
            return

        stats_col_start = col + 9
        worksheet.write(0, stats_col_start, 'Boxplot metric')
        worksheet.write(0, stats_col_start + 1, 'Value')
        worksheet.write(0, stats_col_start + 2, 'Category')
        worksheet.write(0, stats_col_start + 3, 'Q1 anchor')
        worksheet.write(0, stats_col_start + 4, 'IQR')
        worksheet.write(0, stats_col_start + 5, 'Median')
        worksheet.write(0, stats_col_start + 6, 'Whisker +')
        worksheet.write(0, stats_col_start + 7, 'Whisker -')

        summary_rows = None
        mp_enabled = self.optimization_toggles['enable_chart_multiprocessing'] and len(numeric_series) >= 2500
        if mp_enabled:
            try:
                pool = self._ensure_chart_executor()
                if pool is not None:
                    summary_rows = pool.submit(_compute_boxplot_summary, numeric_series.tolist()).result()
            except Exception:
                summary_rows = None

        if summary_rows is None:
            summary_rows = _compute_boxplot_summary(numeric_series.tolist())

        summary_map = {label: float(value) for label, value in summary_rows}
        min_value = summary_map['Min']
        q1_value = summary_map['Q1']
        median_value = summary_map['Median']
        q3_value = summary_map['Q3']
        max_value = summary_map['Max']
        iqr_value = q3_value - q1_value
        whisker_plus = max_value - median_value
        whisker_minus = median_value - min_value

        for row_index, (label, value) in enumerate(summary_rows, start=1):
            worksheet.write(row_index, stats_col_start, label)
            worksheet.write(row_index, stats_col_start + 1, round(value, 3))

        boxplot_row = len(summary_rows) + 2
        worksheet.write(boxplot_row, stats_col_start + 2, data_column)
        worksheet.write(boxplot_row, stats_col_start + 3, round(q1_value, 3))
        worksheet.write(boxplot_row, stats_col_start + 4, round(iqr_value, 3))
        worksheet.write(boxplot_row, stats_col_start + 5, round(median_value, 3))
        worksheet.write(boxplot_row, stats_col_start + 6, round(whisker_plus, 3))
        worksheet.write(boxplot_row, stats_col_start + 7, round(whisker_minus, 3))

        chart = writer.book.add_chart({'type': 'column', 'subtype': 'stacked'})
        chart.add_series({
            'name': f'{data_column} lower quartile anchor',
            'categories': [sheet_name, boxplot_row, stats_col_start + 2, boxplot_row, stats_col_start + 2],
            'values': [sheet_name, boxplot_row, stats_col_start + 3, boxplot_row, stats_col_start + 3],
            'fill': {'none': True},
            'border': {'none': True},
        })
        chart.add_series({
            'name': f'{data_column} interquartile range',
            'categories': [sheet_name, boxplot_row, stats_col_start + 2, boxplot_row, stats_col_start + 2],
            'values': [sheet_name, boxplot_row, stats_col_start + 4, boxplot_row, stats_col_start + 4],
            'fill': {'color': '#4F81BD'},
            'border': {'color': '#1F497D'},
        })

        whisker_chart = writer.book.add_chart({'type': 'line'})
        whisker_chart.add_series({
            'name': f'{data_column} median',
            'categories': [sheet_name, boxplot_row, stats_col_start + 2, boxplot_row, stats_col_start + 2],
            'values': [sheet_name, boxplot_row, stats_col_start + 5, boxplot_row, stats_col_start + 5],
            'line': {'none': True},
            'marker': {
                'type': 'dash',
                'size': 9 if self.optimization_toggles['chart_density_mode'] == 'reduced' else 11,
                'border': {'color': '#C0504D'},
                'fill': {'color': '#C0504D'},
            },
            'y_error_bars': {
                'type': 'custom',
                'plus_values': [sheet_name, boxplot_row, stats_col_start + 6, boxplot_row, stats_col_start + 6],
                'minus_values': [sheet_name, boxplot_row, stats_col_start + 7, boxplot_row, stats_col_start + 7],
                'end_style': 1,
                'line': {'color': '#404040', 'width': 1.25},
            },
        })

        chart.combine(whisker_chart)
        chart.set_title({'name': f'{sheet_name} boxplot'})
        chart.set_x_axis({'name': 'Measurement'})
        chart.set_y_axis({'name': 'Value'})
        chart.set_legend({'position': 'none'})
        worksheet.insert_chart(48, col + 5, chart)

    def write_overview_sheet(self, writer, overview_rows):
        """Write aggregate column statistics to the final summary worksheet."""
        overview_df = pd.DataFrame(overview_rows)
        if overview_df.empty:
            return
        overview_df.to_excel(writer, sheet_name='CSV_SUMMARY', index=False)

    def run(self):
        """Run workbook generation and emit status updates from the worker thread."""
        # Perform the data processing and save to the Excel file here

        if self.selected_indexes and self.selected_data_columns:
            try:
                logger.info(
                    "CSV summary processing started: input='%s', output='%s', columns=%d, summary_only=%s",
                    self.input_file,
                    self.output_file,
                    len(self.selected_data_columns),
                    self.summary_only,
                )
                # Create an Excel writer with the selected output file
                writer = pd.ExcelWriter(self.output_file, engine='xlsxwriter')

                # Calculate the total number of filtered data columns
                total_filtered_columns = len(self.selected_data_columns)
                used_sheet_names = set()

                num_format = writer.book.add_format({'align': 'center', 'valign': 'vcenter', 'num_format': '#,##0.000'})

                overview_rows = []
                total_write_seconds = 0.0
                total_chart_seconds = 0.0
                processing_started_at = time.perf_counter()

                # Update the progress bar for each selected data column
                for i, data_column in enumerate(self.selected_data_columns):
                    # Check if the processing has been canceled
                    if self.canceled:
                        break

                    # Create a new DataFrame with the selected data column and indexes
                    transform_start = time.perf_counter()
                    selected_data = self.data_frame[self.selected_indexes + [data_column]].copy()

                    selected_data = selected_data.assign(
                        **{data_column: pd.to_numeric(selected_data[data_column], errors='coerce')}
                    )
                    selected_data = selected_data.dropna(subset=[data_column])
                    self._record_stage_timing('transform_grouping', time.perf_counter() - transform_start)
                    if selected_data.empty:
                        progress_percentage = int((i + 1) * 100 / total_filtered_columns)
                        eta_label = self._format_eta(
                            self._estimate_eta_seconds(
                                processing_started_at,
                                i + 1,
                                total_filtered_columns,
                            )
                        )
                        self.progress_signal.emit(progress_percentage)
                        self.status_signal.emit(
                            build_three_line_status(
                                "Processing data...",
                                f"Column {i + 1}/{total_filtered_columns}: {data_column}",
                                eta_label,
                            )
                        )
                        continue

                    spec_limits = self.column_spec_limits.get(data_column, {'nom': 0.0, 'usl': 0.0, 'lsl': 0.0})

                    if not self.summary_only:
                        write_start = time.perf_counter()
                        # Write the data to a new sheet with a safe unique name
                        sheet_name = unique_sheet_name(data_column, used_sheet_names)
                        selected_data.to_excel(writer, sheet_name=sheet_name, index=False)

                        worksheet = writer.sheets[sheet_name]

                        col, USL_cell, LSL_cell = self.write_summary_data(worksheet, data_column, selected_data, spec_limits)

                        # Set the number format for the data column
                        worksheet.set_column(col, col, None, num_format)

                        self.apply_conditional_formatting(worksheet, selected_data, data_column, col, USL_cell, LSL_cell, writer)

                        write_elapsed = time.perf_counter() - write_start
                        total_write_seconds += write_elapsed
                        self._record_stage_timing('worksheet_writes', write_elapsed)

                        chart_start = time.perf_counter()
                        chart_data = self._downsample_for_chart(selected_data, data_column)
                        self.add_xy_chart(worksheet, data_column, col, chart_data, writer, sheet_name)

                        plot_options = self.plot_toggles.get(data_column, {'histogram': True, 'boxplot': True})
                        if plot_options.get('histogram', True):
                            self.add_histogram_chart(worksheet, data_column, col, chart_data, writer, sheet_name)
                        if plot_options.get('boxplot', True) and not self.optimization_toggles['defer_non_essential_charts']:
                            self.add_boxplot_chart(worksheet, data_column, col, chart_data, writer, sheet_name)

                        chart_elapsed = time.perf_counter() - chart_start
                        total_chart_seconds += chart_elapsed
                        self._record_stage_timing('chart_rendering', chart_elapsed)
                        self._apply_bottleneck_optimizations()
                        logger.debug(
                            "CSV Summary column '%s' timings: write=%.3fs, chart=%.3fs, rows=%d, toggles=%s",
                            data_column,
                            write_elapsed,
                            chart_elapsed,
                            len(selected_data),
                            self.optimization_toggles,
                        )
                    else:
                        sheet_name = ''

                    stats = compute_column_summary_stats(
                        selected_data[data_column],
                        usl=spec_limits.get('usl', 0.0),
                        lsl=spec_limits.get('lsl', 0.0),
                        nom=spec_limits.get('nom', 0.0),
                    )
                    overview_rows.append({
                        'column': data_column,
                        'sheet_name': sheet_name,
                        'sample_size': stats['sample_size'],
                        'min': stats['min'],
                        'avg': stats['avg'],
                        'max': stats['max'],
                        'std': stats['std'],
                        'cp': stats['cp'],
                        'cpk': stats['cpk'],
                        'nom': stats['nom'],
                        'usl': stats['usl'],
                        'lsl': stats['lsl'],
                        'spec_limits_valid': stats['spec_limits_valid'],
                        'spec_limits_note': stats['spec_limits_note'],
                    })

                    # Calculate the progress percentage and emit the progress signal
                    progress_percentage = int((i + 1) * 100 / total_filtered_columns)
                    eta_label = self._format_eta(
                        self._estimate_eta_seconds(
                            processing_started_at,
                            i + 1,
                            total_filtered_columns,
                        )
                    )
                    self.progress_signal.emit(progress_percentage)
                    self.status_signal.emit(
                        build_three_line_status(
                            "Processing data...",
                            f"Column {i + 1}/{total_filtered_columns}: {data_column}",
                            eta_label,
                        )
                    )

                if self.canceled:
                    writer.close()
                    try:
                        Path(self.output_file).unlink(missing_ok=True)
                    except Exception:
                        logger.warning("Failed to remove canceled CSV summary output '%s'.", self.output_file)
                    logger.info("CSV summary processing canceled for output '%s'.", self.output_file)
                    self.status_signal.emit(build_three_line_status("Processing canceled", "No further work will be processed.", "ETA --"))
                    return

                self.write_overview_sheet(writer, overview_rows)

                # Save the Excel file
                writer.close()

                if not self.summary_only and total_filtered_columns > 0:
                    logger.debug(
                        "CSV Summary timing totals: write=%.3fs, chart=%.3fs, columns=%d, stage_timings=%s, toggles=%s",
                        total_write_seconds,
                        total_chart_seconds,
                        total_filtered_columns,
                        self.stage_timings,
                        self.optimization_toggles,
                    )
                    if self.stage_timings['chart_rendering'] > self.stage_timings['transform_grouping'] * 2 and self.stage_timings['chart_rendering'] > self.stage_timings['worksheet_writes']:
                        logger.info(
                            "CSV Summary bottleneck analysis: chart rendering dominates; remaining workloads are IO/chart-bound so native code for pure-math kernels is not currently justified."
                        )
                logger.info("CSV summary processing completed successfully: output='%s'.", self.output_file)
                self.status_signal.emit(build_three_line_status("Processing complete", "Workbook generated successfully", "ETA 0:00"))

            except Exception:
                logger.exception(
                    "CSV summary data processing failed for input '%s' and output '%s'.",
                    self.input_file,
                    self.output_file,
                )
                self.canceled = True
                self.status_signal.emit(build_three_line_status("Processing failed", "An unexpected error occurred", "ETA --"))
            finally:
                self._shutdown_chart_executor()

        else:
            logger.warning("CSV summary processing skipped because no data columns were selected.")
            self.status_signal.emit(build_three_line_status("Processing skipped", "No data columns were selected", "ETA --"))
            self._shutdown_chart_executor()

    def cancel(self):
        """Request cooperative cancellation and stop background chart workers."""
        self.canceled = True
        self._shutdown_chart_executor()

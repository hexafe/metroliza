from PyQt6.QtCore import Qt, pyqtSlot, QThread, pyqtSignal, QTemporaryFile, QSize
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QPushButton,
    QFileDialog,
    QListWidget,
    QMessageBox,
    QHBoxLayout,
    QProgressBar,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QCheckBox,
)
from pathlib import Path
import logging
import re
import time
import pandas as pd
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell
from modules.excel_sheet_utils import unique_sheet_name
from modules.csv_summary_utils import (
    build_default_plot_toggles,
    compute_column_summary_stats,
    load_csv_with_fallbacks,
    normalize_plot_toggles,
    normalize_column_spec_limits,
    resolve_default_data_columns,
    build_csv_summary_preset_key,
    estimate_enabled_chart_count,
    recommend_extended_plots_default,
    load_csv_summary_presets,
    migrate_csv_summary_presets,
    save_csv_summary_presets,
)
import base64
from modules import Base64EncodedFiles


logger = logging.getLogger(__name__)


class FilterDialog(QDialog):
    def __init__(self, parent, column_names):
        super().__init__(parent)

        self.setWindowTitle("Filter Columns")
        self.setGeometry(200, 200, 500, 150)

        self.column_names = column_names
        self.selected_indexes = column_names[:1]
        self.selected_data_columns = column_names[1:]

        # Initialize the layout
        main_layout = QVBoxLayout()

        # Create horizontal layout for the list widgets
        horizontal_layout = QHBoxLayout()

        # Add the list widgets for indexes and data columns
        self.index_list_widget = QListWidget()
        self.data_list_widget = QListWidget()

        # Set the selection mode to multi-selection
        self.index_list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.data_list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)

        # Add the list widgets to the horizontal layout
        horizontal_layout.addWidget(self.index_list_widget)
        horizontal_layout.addWidget(self.data_list_widget)

        # Populate the list widgets with column names
        self.index_list_widget.addItem("SELECT DEFAULT (FIRST COLUMN)")
        self.index_list_widget.addItems(column_names)
        self.data_list_widget.addItem("SELECT ALL")
        self.data_list_widget.addItems(column_names)

        # Add the horizontal layout to the main layout
        main_layout.addLayout(horizontal_layout)

        # Add OK button
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)

        # Add the OK button to the layout
        main_layout.addWidget(ok_button)

        # Set the layout for the dialog
        self.setLayout(main_layout)

        # Select the default filter initially
        self.select_default_filter()

    def select_default_filter(self):
        # Select the first item in INDEX list as default
        self.index_list_widget.setCurrentRow(0)

        # Select the first item in DATA list as default
        self.data_list_widget.setCurrentRow(0)

    def get_selected_columns(self):
        # Get the selected indexes and data columns
        self.selected_indexes = [item.text() for item in self.index_list_widget.selectedItems()]
        self.selected_data_columns = [item.text() for item in self.data_list_widget.selectedItems()]

        # Return the first column if "SELECT DEFAULT (FIRST COLUMN)" is selected
        if "SELECT DEFAULT (FIRST COLUMN)" in self.selected_indexes:
            self.selected_indexes = self.column_names[:1]

        # Return all columns except the ones selected in INDEX if "SELECT ALL" is selected
        if "SELECT ALL" in self.selected_data_columns:
            self.selected_data_columns = [column for column in self.column_names if column not in self.selected_indexes]
            if "SELECT ALL" in self.selected_data_columns:
                self.selected_data_columns.remove("SELECT ALL")

        # Return the selected columns
        return self.selected_indexes, self.selected_data_columns


class SpecLimitsDialog(QDialog):
    def __init__(self, parent, data_columns, existing_limits):
        super().__init__(parent)
        self.setWindowTitle("Column spec limits")
        self.setGeometry(220, 220, 700, 380)
        self.data_columns = data_columns

        layout = QVBoxLayout()
        self.table = QTableWidget(len(data_columns), 4, self)
        self.table.setHorizontalHeaderLabels(["Column", "NOM", "USL", "LSL"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)

        for row, column_name in enumerate(data_columns):
            self.table.setItem(row, 0, QTableWidgetItem(column_name))
            defaults = existing_limits.get(column_name, {'nom': 0.0, 'usl': 0.0, 'lsl': 0.0})
            self.table.setItem(row, 1, QTableWidgetItem(str(defaults.get('nom', 0.0))))
            self.table.setItem(row, 2, QTableWidgetItem(str(defaults.get('usl', 0.0))))
            self.table.setItem(row, 3, QTableWidgetItem(str(defaults.get('lsl', 0.0))))

        layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _cell_to_float(self, row, col):
        item = self.table.item(row, col)
        if item is None:
            return 0.0
        value = (item.text() or "").strip()
        if value == "":
            return 0.0
        try:
            return float(value.replace(',', '.'))
        except ValueError:
            return 0.0

    def get_limits(self):
        limits = {}
        for row, column_name in enumerate(self.data_columns):
            limits[column_name] = {
                'nom': self._cell_to_float(row, 1),
                'usl': self._cell_to_float(row, 2),
                'lsl': self._cell_to_float(row, 3),
            }
        return limits


class DataProcessingThread(QThread):
    progress_signal = pyqtSignal(int)

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

    def write_summary_data(self, worksheet, data_column, selected_data, spec_limits):
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
        cp_formula = f"ROUND(({USL_formula} - {LSL_formula})/(6 * {sigma_formula}), 3)"
        worksheet.write_formula(7, col + 3, cp_formula)

        worksheet.write(8, col + 2, 'Cpk')
        average_formula = f"({summary_col}5)"
        cpk_formula = f"ROUND(MIN( ({USL_formula} - {average_formula})/(3 * {sigma_formula}), ({average_formula} - {LSL_formula})/(3 * {sigma_formula}) ), 3)"
        worksheet.write_formula(8, col + 3, cpk_formula)

        worksheet.write(9, col + 2, "Sample size")
        count_formula = f"=COUNT({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1})"
        worksheet.write_formula(9, col + 3, count_formula)

        return col, USL_cell, LSL_cell

    def apply_conditional_formatting(self, worksheet, selected_data, data_column, col, USL_cell, LSL_cell, writer):
        # Define the format for conditional formatting (highlight cells in red)
        red_format = writer.book.add_format({'bg_color': 'red', 'font_color': 'white', 'align': 'center', 'valign': 'vcenter', 'right': 1, 'num_format': '#,##0.000'})

        # Apply conditional formatting to highlight cells greater than USL in red
        worksheet.conditional_format(1, col - 1, len(selected_data[data_column]), col - 1,
                                    {'type': 'cell', 'criteria': '>', 'value': USL_cell, 'format': red_format})

        # Apply conditional formatting to highlight cells lower than LSL in red
        worksheet.conditional_format(1, col - 1, len(selected_data[data_column]), col - 1,
                                    {'type': 'cell', 'criteria': '<', 'value': LSL_cell, 'format': red_format})

    def add_xy_chart(self, worksheet, data_column, col, selected_data, writer, sheet_name):
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
        numeric_series = pd.to_numeric(selected_data[data_column], errors='coerce').dropna()
        if numeric_series.empty:
            return

        histogram_col_start = col + 6
        worksheet.write(0, histogram_col_start, 'Histogram Bin')
        worksheet.write(0, histogram_col_start + 1, 'Count')

        bin_count = min(12, max(5, int(len(numeric_series) ** 0.5)))
        bins = pd.cut(numeric_series, bins=bin_count)
        counts = bins.value_counts().sort_index()

        for row_index, (bin_interval, count) in enumerate(counts.items(), start=1):
            worksheet.write(row_index, histogram_col_start, str(bin_interval))
            worksheet.write(row_index, histogram_col_start + 1, int(count))

        chart = writer.book.add_chart({'type': 'column'})
        chart.add_series({
            'name': f'{data_column} histogram',
            'categories': [sheet_name, 1, histogram_col_start, len(counts), histogram_col_start],
            'values': [sheet_name, 1, histogram_col_start + 1, len(counts), histogram_col_start + 1],
            'gap': 2,
        })
        chart.set_title({'name': f'{sheet_name} histogram'})
        chart.set_x_axis({'name': 'Bins'})
        chart.set_y_axis({'name': 'Count'})
        chart.set_legend({'position': 'none'})
        worksheet.insert_chart(30, col + 5, chart)

    def add_boxplot_chart(self, worksheet, data_column, col, selected_data, writer, sheet_name):
        numeric_series = pd.to_numeric(selected_data[data_column], errors='coerce').dropna()
        if numeric_series.empty:
            return

        stats_col_start = col + 9
        worksheet.write(0, stats_col_start, 'Five-number summary')
        worksheet.write(0, stats_col_start + 1, data_column)

        summary_rows = [
            ('Min', float(numeric_series.min())),
            ('Q1', float(numeric_series.quantile(0.25))),
            ('Median', float(numeric_series.median())),
            ('Q3', float(numeric_series.quantile(0.75))),
            ('Max', float(numeric_series.max())),
        ]
        for row_index, (label, value) in enumerate(summary_rows, start=1):
            worksheet.write(row_index, stats_col_start, label)
            worksheet.write(row_index, stats_col_start + 1, round(value, 3))

        chart = writer.book.add_chart({'type': 'line'})
        chart.add_series({
            'name': f'{data_column} boxplot profile',
            'categories': [sheet_name, 1, stats_col_start, len(summary_rows), stats_col_start],
            'values': [sheet_name, 1, stats_col_start + 1, len(summary_rows), stats_col_start + 1],
            'marker': {'type': 'circle', 'size': 6},
        })
        chart.set_title({'name': f'{sheet_name} boxplot profile'})
        chart.set_x_axis({'name': 'Summary point'})
        chart.set_y_axis({'name': 'Value'})
        chart.set_legend({'position': 'none'})
        worksheet.insert_chart(48, col + 5, chart)

    def write_overview_sheet(self, writer, overview_rows):
        overview_df = pd.DataFrame(overview_rows)
        if overview_df.empty:
            return
        overview_df.to_excel(writer, sheet_name='CSV_SUMMARY', index=False)

    def run(self):
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

                # Update the progress bar for each selected data column
                for i, data_column in enumerate(self.selected_data_columns):
                    # Check if the processing has been canceled
                    if self.canceled:
                        break

                    # Create a new DataFrame with the selected data column and indexes
                    selected_data = self.data_frame[self.selected_indexes + [data_column]].copy()

                    selected_data.loc[:, data_column] = pd.to_numeric(selected_data[data_column], errors='coerce')
                    selected_data = selected_data.dropna(subset=[data_column])
                    if selected_data.empty:
                        progress_percentage = int((i + 1) * 100 / total_filtered_columns)
                        self.progress_signal.emit(progress_percentage)
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

                        chart_start = time.perf_counter()
                        self.add_xy_chart(worksheet, data_column, col, selected_data, writer, sheet_name)

                        plot_options = self.plot_toggles.get(data_column, {'histogram': True, 'boxplot': True})
                        if plot_options.get('histogram', True):
                            self.add_histogram_chart(worksheet, data_column, col, selected_data, writer, sheet_name)
                        if plot_options.get('boxplot', True):
                            self.add_boxplot_chart(worksheet, data_column, col, selected_data, writer, sheet_name)

                        chart_elapsed = time.perf_counter() - chart_start
                        total_chart_seconds += chart_elapsed
                        logger.debug(
                            "CSV Summary column '%s' timings: write=%.3fs, chart=%.3fs, rows=%d",
                            data_column,
                            write_elapsed,
                            chart_elapsed,
                            len(selected_data),
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
                    self.progress_signal.emit(progress_percentage)

                if self.canceled:
                    writer.close()
                    try:
                        Path(self.output_file).unlink(missing_ok=True)
                    except Exception:
                        logger.warning("Failed to remove canceled CSV summary output '%s'.", self.output_file)
                    logger.info("CSV summary processing canceled for output '%s'.", self.output_file)
                    return

                self.write_overview_sheet(writer, overview_rows)

                # Save the Excel file
                writer.close()

                if not self.summary_only and total_filtered_columns > 0:
                    logger.debug(
                        "CSV Summary timing totals: write=%.3fs, chart=%.3fs, columns=%d",
                        total_write_seconds,
                        total_chart_seconds,
                        total_filtered_columns,
                    )
                logger.info("CSV summary processing completed successfully: output='%s'.", self.output_file)

            except Exception:
                logger.exception(
                    "CSV summary data processing failed for input '%s' and output '%s'.",
                    self.input_file,
                    self.output_file,
                )
                self.canceled = True

        else:
            logger.warning("CSV summary processing skipped because no data columns were selected.")

    def cancel(self):
        self.canceled = True


class CSVSummaryDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)

        self.setWindowTitle("CSV Summary")
        self.setGeometry(200, 200, 300, 150)

        self.input_file = ""
        self.output_file = ""
        self.data_frame = None  # Store the loaded DataFrame
        self.column_names = []
        self.selected_indexes = []
        self.selected_data_columns = []
        self.csv_config = {}
        self.column_spec_limits = {}
        self.plot_toggles = {}
        self.summary_only = False

        # Initialize the layout
        layout = QVBoxLayout()

        # Add the buttons to the layout
        self.input_button = QPushButton("Select input file (CSV)")
        self.filter_button = QPushButton("Filter columns (optional)")
        self.spec_limits_button = QPushButton("Set spec limits (optional)")
        self.clear_presets_button = QPushButton("Clear saved presets (optional)")
        self.include_extended_plots = QCheckBox("Include histogram and boxplot charts")
        self.summary_only_checkbox = QCheckBox("Summary-only mode (skip per-column sheets/charts)")
        self.output_button = QPushButton("Select output file (xlsx)")
        self.start_button = QPushButton("START")  # Add the START button
        layout.addWidget(self.input_button)
        layout.addWidget(self.filter_button)
        layout.addWidget(self.spec_limits_button)
        layout.addWidget(self.clear_presets_button)
        layout.addWidget(self.include_extended_plots)
        layout.addWidget(self.summary_only_checkbox)
        layout.addWidget(self.output_button)
        layout.addWidget(self.start_button)  # Add the START button to the layout

        # Connect the buttons to their respective functions
        self.input_button.clicked.connect(self.handle_input_button)
        self.filter_button.clicked.connect(self.handle_filter_button)
        self.spec_limits_button.clicked.connect(self.handle_spec_limits_button)
        self.clear_presets_button.clicked.connect(self.handle_clear_presets_button)
        self.output_button.clicked.connect(self.handle_output_button)
        self.start_button.clicked.connect(self.handle_start_button)  # Connect the START button

        self.include_extended_plots.setChecked(True)
        self.summary_only_checkbox.setChecked(False)

        # Initially, disable the FILTER, OUTPUT, and START buttons
        self.filter_button.setEnabled(False)
        self.spec_limits_button.setEnabled(False)
        self.output_button.setEnabled(False)
        self.start_button.setEnabled(False)

        # Set the layout for the dialog
        self.setLayout(layout)

        self.preset_path = Path.home() / '.metroliza' / '.csv_summary_presets.json'

    def _load_presets(self):
        presets = load_csv_summary_presets(self.preset_path)
        migrated, changed = migrate_csv_summary_presets(presets)
        if changed:
            save_csv_summary_presets(self.preset_path, migrated)
        return migrated

    def _save_presets(self, preset_key, selected_indexes, selected_data_columns, csv_config, column_spec_limits, include_extended_plots, summary_only, plot_toggles):
        if not preset_key:
            return
        presets = self._load_presets()
        presets[preset_key] = {
            "selected_indexes": list(selected_indexes or []),
            "selected_data_columns": list(selected_data_columns or []),
            "csv_config": csv_config or {},
            "column_spec_limits": normalize_column_spec_limits(selected_data_columns, column_spec_limits),
            "include_extended_plots": bool(include_extended_plots),
            "summary_only": bool(summary_only),
            "plot_toggles": normalize_plot_toggles(selected_data_columns, plot_toggles, full_report=include_extended_plots),
        }
        save_csv_summary_presets(self.preset_path, presets)

    @staticmethod
    def _preset_key_candidates(file_path):
        path = Path(file_path)
        normalized_stem = re.sub(r"\d+", "", path.stem).strip("_- ").lower()
        candidates = [build_csv_summary_preset_key(path)]
        if normalized_stem:
            candidates.append(f"{normalized_stem}.csv")
        return candidates

    def _resolve_preset_for_file(self, file_path):
        presets = self._load_presets()
        for key in self._preset_key_candidates(file_path):
            preset = presets.get(key)
            if isinstance(preset, dict):
                return preset
        return {}

    # Define functions for button clicks
    def handle_input_button(self):
        options = QFileDialog.Option.ReadOnly
        filename, _ = QFileDialog.getOpenFileName(self, "Select input file (CSV)", "", "CSV Files (*.csv);;All Files (*)", options=options)
        if filename:
            if not filename.endswith(".csv"):
                filename += ".csv"
            logger.info("Selected input CSV file: %s", filename)
            self.input_file = filename
            # Enable the FILTER and OUTPUT buttons after the input file is selected
            self.filter_button.setEnabled(True)
            self.spec_limits_button.setEnabled(True)
            self.output_button.setEnabled(True)

            preset = self._resolve_preset_for_file(filename)
            preset_csv_config = preset.get('csv_config', {}) if isinstance(preset, dict) else {}

            # Load CSV with delimiter/decimal fallbacks.
            try:
                self.data_frame, self.csv_config = load_csv_with_fallbacks(filename, preferred_config=preset_csv_config)
            except Exception as exc:
                logger.exception("CSV summary failed to load input file '%s'.", filename)
                QMessageBox.critical(self, 'CSV load failed', f'Could not load CSV file.\n\n{exc}')
                self.filter_button.setEnabled(False)
                self.spec_limits_button.setEnabled(False)
                self.output_button.setEnabled(False)
                self.start_button.setEnabled(False)
                return

            self.column_names = self.data_frame.columns.tolist()
            preset_indexes = preset.get('selected_indexes', []) if isinstance(preset, dict) else []
            preset_data_columns = preset.get('selected_data_columns', []) if isinstance(preset, dict) else []

            self.selected_indexes = [col for col in preset_indexes if col in self.column_names] or self.column_names[:1]
            default_data_columns = resolve_default_data_columns(self.data_frame, self.selected_indexes)
            self.selected_data_columns = [col for col in preset_data_columns if col in default_data_columns] or default_data_columns

            if isinstance(preset, dict):
                preset_include_extended_plots = bool(preset.get('include_extended_plots', True))
            else:
                preset_include_extended_plots = recommend_extended_plots_default(self.selected_data_columns)
            self.include_extended_plots.setChecked(preset_include_extended_plots)
            self.summary_only = bool(preset.get('summary_only', False)) if isinstance(preset, dict) else False
            self.summary_only_checkbox.setChecked(self.summary_only)

            preset_spec_limits = preset.get('column_spec_limits', {}) if isinstance(preset, dict) else {}
            self.column_spec_limits = normalize_column_spec_limits(self.selected_data_columns, preset_spec_limits)

            preset_plot_toggles = preset.get('plot_toggles', {}) if isinstance(preset, dict) else {}
            self.plot_toggles = normalize_plot_toggles(
                self.selected_data_columns,
                preset_plot_toggles,
                full_report=self.include_extended_plots.isChecked(),
            )

    def handle_filter_button(self):
        logger.debug("FILTER button clicked.")

        # Open the FilterDialog and pass the column names to it
        if self.data_frame is not None:
            filter_dialog = FilterDialog(self, self.column_names)

            if filter_dialog.exec() == QDialog.DialogCode.Accepted:
                self.selected_indexes, self.selected_data_columns = filter_dialog.get_selected_columns()

                # Use the selected_indexes and selected_data_columns for further processing
                if self.selected_indexes:
                    logger.info("Selected index columns: %s", self.selected_indexes)
                if self.selected_data_columns:
                    logger.info("Selected data columns: %s", self.selected_data_columns)
                    self.column_spec_limits = {
                        column: self.column_spec_limits.get(column, {'nom': 0.0, 'usl': 0.0, 'lsl': 0.0})
                        for column in self.selected_data_columns
                    }
                    self.plot_toggles = normalize_plot_toggles(
                        self.selected_data_columns,
                        self.plot_toggles,
                        full_report=self.include_extended_plots.isChecked(),
                    )
        else:
            QMessageBox.warning(self, "Warning", "No data loaded. Please select an input file first.")

    def handle_spec_limits_button(self):
        if not self.selected_data_columns:
            QMessageBox.information(self, "No data columns", "Select input/filter columns before setting spec limits.")
            return

        spec_dialog = SpecLimitsDialog(self, self.selected_data_columns, self.column_spec_limits)
        if spec_dialog.exec() == QDialog.DialogCode.Accepted:
            self.column_spec_limits = spec_dialog.get_limits()

    def handle_clear_presets_button(self):
        if not self.preset_path.exists():
            QMessageBox.information(self, "No presets", "No saved CSV presets were found.")
            return

        self.preset_path.unlink(missing_ok=True)
        QMessageBox.information(self, "Presets cleared", "Saved CSV presets were removed.")

    def handle_output_button(self):
        # options = QFileDialog.Option.DontUseNativeDialog
        default_name = self.input_file[:-4]
        if not default_name.endswith(".xlsx"):
            default_name += ".xlsx"

        file_path = Path(default_name)
        base_name = file_path.stem
        suffix = file_path.suffix
        directory = file_path.parent

        counter = 1
        while file_path.exists():
            file_path = directory / f"{base_name}_{counter}{suffix}"
            counter += 1

        filename, _ = QFileDialog.getSaveFileName(self, "Select output file (xlsx)", str(file_path),
                                                "Excel Files (*.xlsx);;All Files (*)")#, options=options)

        if filename:
            logger.info("Selected output Excel file: %s", filename)
            self.output_file = filename
            # Enable the START button after the output file is selected
            self.start_button.setEnabled(True)

    @pyqtSlot()
    def show_loading_screen(self):
        # Create a custom QDialog for the loading screen
        self.loading_dialog = QDialog(self, Qt.WindowType.WindowTitleHint)
        self.loading_dialog.setWindowTitle("Processing...")
        self.loading_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.loading_dialog.setFixedSize(400, 300)

        # Create a QLabel to display the loading GIF
        loading_gif_label = QLabel(self.loading_dialog)
        loading_gif_label.setFixedSize(200, 200)
        loading_gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Load the loading.gif from a file, create a QMovie from it, and set it to the label
        loading_gif_decoded = base64.b64decode(Base64EncodedFiles.encoded_loading_gif)

        # Create temporary file and save encoded loading gif to it
        temp_file = QTemporaryFile()
        temp_file.setAutoRemove(False)
        temp_file_name = ""
        if temp_file.open():
            temp_file.write(loading_gif_decoded)
            temp_file.close()
            temp_file_name = temp_file.fileName()

        # Create the QMovie using the temporary file name
        loading_gif = QMovie(temp_file_name)
        loading_gif.setScaledSize(QSize(200, 200))
        loading_gif_label.setMovie(loading_gif)
        loading_gif.start()

        # Create the loading label and progress bar as instance variables
        self.loading_label = QLabel("Processing data...", self.loading_dialog)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.loading_bar = QProgressBar(self.loading_dialog)
        self.loading_bar.setValue(0)
        self.loading_bar.setFixedSize(380, 20)
        self.loading_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Create a layout for the dialog and add the loading GIF, loading label, and progress bar to it
        layout = QVBoxLayout(self.loading_dialog)
        layout.addWidget(loading_gif_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.loading_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.loading_bar, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Create and add the Cancel button to the layout
        cancel_button = QPushButton("Cancel", self.loading_dialog)
        cancel_button.clicked.connect(self.stop_data_processing_and_close_loading)
        layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Start the data processing in a separate thread
        self.worker_thread = DataProcessingThread(
            self.selected_indexes,
            self.selected_data_columns,
            self.input_file,
            self.output_file,
            self.data_frame,
            self.csv_config,
            self.column_spec_limits,
            self.plot_toggles if self.include_extended_plots.isChecked() else build_default_plot_toggles(self.selected_data_columns, full_report=False),
            summary_only=self.summary_only_checkbox.isChecked(),
        )
        # Connect the progress signal to the update_progress_bar slot
        self.worker_thread.progress_signal.connect(self.update_progress_bar)
        self.worker_thread.finished.connect(self.on_data_processing_finished)
        self.worker_thread.start()

        # Show the loading dialog
        self.loading_dialog.show()

    def update_progress_bar(self, value):
        # Update the progress bar value
        self.loading_bar.setValue(value)

    def stop_data_processing_and_close_loading(self):
        if self.worker_thread:
            # Stop the data processing thread if it exists
            self.worker_thread.cancel()

    @pyqtSlot()
    def on_data_processing_finished(self):
        # Data processing is complete or canceled

        if self.worker_thread.canceled:
            # Show a message box to inform the user that processing has been canceled
            QMessageBox.information(self, "Processing canceled", "Processing has been canceled")
        else:
            # Show a message box to inform the user that processing is complete
            QMessageBox.information(self, "Processing complete", f"Data saved to {self.output_file}!")

        # Close the loading dialog
        self.loading_dialog.close()

        # Reset the worker thread
        self.worker_thread = None


    def _show_chart_generation_advisory(self):
        chart_count = estimate_enabled_chart_count(
            self.selected_data_columns,
            self.plot_toggles,
            full_report=self.include_extended_plots.isChecked(),
            summary_only=self.summary_only_checkbox.isChecked(),
        )
        if chart_count <= 40:
            return

        reply = QMessageBox.question(
            self,
            "Large chart workload detected",
            (
                f"This export is configured to generate about {chart_count} charts.\n\n"
                "This may be slow for large datasets.\n"
                "Would you like to switch to Quick-look mode (disable charts)?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.include_extended_plots.setChecked(False)

    def handle_start_button(self):
        # Perform the desired action when the START button is clicked
        # You can access the input_file, output_file, and data_frame variables here for further processing

        if self.data_frame is not None:
            self._show_chart_generation_advisory()

            self._save_presets(
                build_csv_summary_preset_key(self.input_file),
                self.selected_indexes,
                self.selected_data_columns,
                self.csv_config,
                self.column_spec_limits,
                self.include_extended_plots.isChecked(),
                self.summary_only_checkbox.isChecked(),
                self.plot_toggles,
            )
            # Show the loading screen and progress bar
            self.show_loading_screen()
        else:
            logger.warning("Start requested without loaded data frame.")

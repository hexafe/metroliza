import hashlib
import logging
import matplotlib
import pandas as pd
import numpy as np

matplotlib.use('Agg')

import matplotlib.pyplot as plt
from scipy.stats import norm
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal
from io import BytesIO
from modules.CustomLogger import CustomLogger
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell, xl_range
from modules.excel_sheet_utils import unique_sheet_name
from modules.export_summary_utils import compute_measurement_summary, resolve_nominal_and_limits
from modules.contracts import ExportRequest, validate_export_request
from modules.db import execute_select_with_columns, read_sql_dataframe


def build_export_dataframe(data, column_names):
    return pd.DataFrame(data, columns=column_names)


def execute_export_query(db_file, export_query, select_reader=execute_select_with_columns):
    return select_reader(db_file, export_query)


def run_export_steps(steps, should_cancel):
    for step in steps:
        if should_cancel():
            return False
        step()
    return not should_cancel()


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
        self.selected_sorting_parameter = validated_request.options.sorting_parameter
        self.violin_plot_min_samplesize = validated_request.options.violin_plot_min_samplesize
        self.summary_plot_scale = validated_request.options.summary_plot_scale
        self.hide_ok_results = validated_request.options.hide_ok_results
        self.generate_summary_sheet = validated_request.options.generate_summary_sheet
        self.export_canceled = False
        self._prepared_grouping_df = None

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

    def run(self):
        try:
            if self._check_canceled():
                return

            self.update_progress.emit(0)
            self.update_label.emit("Preparing export...")

            excel_writer = pd.ExcelWriter(self.excel_file, engine='xlsxwriter')
            try:
                completed = run_export_steps(
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
                if not completed:
                    return
            finally:
                excel_writer.close()

            self.update_label.emit("Export completed successfully.")
            self.finished.emit()
            QCoreApplication.processEvents()
        except Exception as e:
            self.log_and_exit(e)

    def add_measurements_horizontal_sheet(self, excel_writer):
        try:
            df = read_sql_dataframe(self.db_file, self.filter_query)
            df = self._ensure_sample_number_column(df)
            df['HEADER - AX'] = df['HEADER'] + ' - ' + df['AX']

            # Group the data by reference
            reference_groups = df.groupby('REFERENCE', as_index=False)

            # Create the summary worksheet
            workbook = excel_writer.book
            used_sheet_names = set(excel_writer.sheets.keys())

            # Initialize variables for column and summary column tracking
            col = 0

            # Define cell formats
            default_format = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
            border_format = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'right': 1})
            wrap_format = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'text_wrap': True})
            percent_format = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'num_format': '0.00%'})

            column_width = 12

            # Set the default cell format for the summary worksheet
            max_col = len(df['HEADER - AX'].unique()) * 3

            for (ref, ref_group) in reference_groups:
                if self._check_canceled():
                    return
                # Reset the column tracking for new sheet
                col = 0
                
                safe_ref_sheet_name = unique_sheet_name(ref, used_sheet_names)

                # Create a worksheet for each reference
                worksheet = workbook.add_worksheet(safe_ref_sheet_name)
                if self.generate_summary_sheet:
                    summary_sheet_name = unique_sheet_name(f"{safe_ref_sheet_name}_summary", used_sheet_names)
                    summary_worksheet = workbook.add_worksheet(summary_sheet_name)

                # Set the default cell format for the worksheet
                worksheet.set_column(0, max_col, column_width, cell_format=default_format)

                # Group the data by header within the reference
                header_groups = ref_group.groupby('HEADER - AX', as_index=False)

                for (header, header_group) in header_groups:
                    if self._check_canceled():
                        return
                    header_group = self._sort_header_group(header_group)
                    
                    worksheet.write(0, col, 'NOM')
                    nom = round(header_group['NOM'].iloc[0], 3)
                    worksheet.write(0, col + 1, nom)
                    NOM_cell = xl_rowcol_to_cell(0, col + 1, row_abs=True, col_abs=True)
                    
                    worksheet.write(1, col, '+TOL')
                    USL = round(header_group['+TOL'].iloc[0], 3)
                    worksheet.write(1, col + 1, USL)
                    USL = nom + USL
                    USL_cell = xl_rowcol_to_cell(1, col + 1, row_abs=True, col_abs=True)
                    
                    worksheet.write(2, col, '-TOL')
                    if header_group['-TOL'].iloc[0]:
                        LSL = round(header_group['-TOL'].iloc[0], 3)
                    else:
                        LSL = 0
                    worksheet.write(2, col + 1, LSL)
                    LSL = nom + LSL
                    LSL_cell = xl_rowcol_to_cell(2, col + 1, row_abs=True, col_abs=True)
                    
                    data_range_y = f'{xl_col_to_name(col + 2)}22:{xl_col_to_name(col + 2)}{len(header_group) + 21}'
                    data_range_x = f'{xl_col_to_name(col + 1)}22:{xl_col_to_name(col + 1)}{len(header_group) + 21}'
                    
                    worksheet.write(3, col, 'MIN')
                    min_formula = f"=ROUND(MIN({data_range_y}), 3)"
                    worksheet.write_formula(3, col + 1, min_formula)
                    
                    worksheet.write(4, col, 'AVG')
                    avg_formula = f"=ROUND(AVERAGE({data_range_y}), 3)"
                    worksheet.write_formula(4, col + 1, avg_formula)
                    
                    worksheet.write(5, col, 'MAX')
                    max_formula = f"=ROUND(MAX({data_range_y}), 3)"
                    worksheet.write_formula(5, col + 1, max_formula)
                    
                    worksheet.write(6, col, 'STD')
                    std_formula = f"=ROUND(STDEV({data_range_y}), 3)"
                    worksheet.write_formula(6, col + 1, std_formula)
                    
                    worksheet.write(7, col, 'Cp')
                    summary_col = xl_col_to_name(col + 1)
                    USL_formula = f"({summary_col}1 + {summary_col}2)"
                    LSL_formula = f"({summary_col}1 + {summary_col}3)"
                    sigma_formula = f"({summary_col}7)"
                    cp_formula = f"=ROUND(({USL_formula} - {LSL_formula})/(6 * {sigma_formula}), 3)"
                    worksheet.write_formula(7, col + 1, cp_formula)
                    
                    worksheet.write(8, col, 'Cpk')
                    average_formula = f"({summary_col}5)"
                    # Check if NOM and LSL are both equal to 0
                    if nom == 0 and LSL == 0:
                        cpk_formula = f"=ROUND(({USL_formula} - {average_formula})/(3 * {sigma_formula}), 3)"
                    else:
                        cpk_formula = f"=ROUND(MIN( ({USL_formula} - {average_formula})/(3 * {sigma_formula}), ({average_formula} - {LSL_formula})/(3 * {sigma_formula}) ), 3)"
                    worksheet.write_formula(8, col + 1, cpk_formula)
                    
                    worksheet.write(9, col, "NOK number")
                    NOK_HIGH = f'COUNTIF({data_range_y}, ">"&({NOM_cell}+{USL_cell}))'
                    NOK_LOW = f'COUNTIF({data_range_y}, "<"&({NOM_cell}+{LSL_cell}))'
                    NOK_TOTAL = f'={NOK_HIGH}+{NOK_LOW}'
                    worksheet.write_formula(9, col + 1, NOK_TOTAL)
                    
                    worksheet.write(10, col, "NOK %")
                    NOK_cell = xl_rowcol_to_cell(9, col + 1, row_abs=True, col_abs=True)
                    SAMPLESIZE_cell = xl_rowcol_to_cell(11, col + 1, row_abs=True, col_abs=True)
                    NOK_perc_formula = f"=ROUND(({NOK_cell}/{SAMPLESIZE_cell})*100%, 3)"
                    worksheet.write_formula(10, col + 1, NOK_perc_formula, percent_format)
                    
                    worksheet.write(11, col, "Sample size")
                    count_formula = f"=COUNT({data_range_y})"
                    worksheet.write_formula(11, col + 1, count_formula)
                    
                    worksheet.write(20, col, 'Date')
                    worksheet.write_column(21, col, header_group['DATE'])
                    
                    worksheet.write(20, col + 1, 'Sample #')
                    worksheet.write_column(21, col + 1, header_group['SAMPLE_NUMBER'])
                    
                    worksheet.write(20, col + 2, header, wrap_format)
                    worksheet.write_column(21, col + 2, round(header_group['MEAS'], 3))
                    
                    
                    # Define the format for conditional formatting (highlight cells in red)
                    red_format = workbook.add_format({'bg_color': 'red', 'font_color': 'white', 'align': 'center', 'valign': 'vcenter', 'right': 1})

                    # Apply conditional formatting to highlight cells greater than USL in red
                    worksheet.conditional_format(21, col + 2, len(header_group) + 20, col + 2,
                                                {'type': 'cell', 'criteria': '>', 'value': f'({NOM_cell}+{USL_cell})', 'format': red_format})

                    # Apply conditional formatting to highlight cells lower than LSL in red
                    worksheet.conditional_format(21, col + 2, len(header_group) + 20, col + 2,
                                                {'type': 'cell', 'criteria': '<', 'value': f'({NOM_cell}+{LSL_cell})', 'format': red_format})
                    
                    # Apply conditional formatting to highlight if NOK% > 0
                    worksheet.conditional_format(10, col + 1, 10, col + 1,
                                                {'type': 'cell', 'criteria': '>', 'value': f'0', 'format': red_format})                
                    
                    col += 3

                    # Merge cells for the header
                    header_col_end = col - 1

                    # Set border format for last column of header for worksheet
                    worksheet.set_column(header_col_end, header_col_end, None, cell_format=border_format)
                    
                    # Create an XY chart object
                    chart = workbook.add_chart({'type': self.selected_export_type})

                    # Add data to the chart with the specified x and y ranges
                    num_rows = len(header_group) + 20
                    x_range = f"={safe_ref_sheet_name}!${data_range_x}"
                    y_range = f"={safe_ref_sheet_name}!${data_range_y}"

                    # Add the series to the chart
                    chart.add_series({
                        'name': header,
                        'categories': x_range,
                        'values': y_range,
                    })

                    # Configure the chart properties
                    chart.set_title({'name': f'{header}', 'name_font': {'size': 10}})
                    
                    chart.set_y_axis({
                        'major_gridlines': {
                            'visible': False,
                        }
                    })

                    chart.set_legend({'position': 'none'})
                    
                    USL_y_values_list = [USL] * len(header_group)
                    LSL_y_values_list = [LSL] * len(header_group)
                    USL_limits_y_values = '={' + ','.join(str(item) for item in USL_y_values_list) + '}'
                    LSL_limits_y_values = '={' + ','.join(str(item) for item in LSL_y_values_list) + '}'
                    chart.add_series({
                        'name': 'USL',
                        'categories': x_range,
                        'values': USL_limits_y_values,
                        'line': {'color': 'red', 'width': 1},
                        'marker': {'type': 'none'},
                        'data_labels': {'value': False},
                        'show_legend_key': False,
                    })
                    chart.add_series({
                        'name': 'LSL',
                        'categories': x_range,
                        'values': LSL_limits_y_values,
                        'line': {'color': 'red', 'width': 1},
                        'marker': {'type': 'none'},
                        'data_labels': {'value': False},
                        'show_legend_key': False,
                    })
                    
                    chart.set_size({'width': 240, 'height': 160})

                    # Insert the chart into the worksheet.
                    worksheet.insert_chart(12, col - 3, chart)

                    if self._check_canceled():
                        return
                    
                    if self.generate_summary_sheet:
                        self.summary_sheet_fill(summary_worksheet, header, header_group, col)
                        if self._check_canceled():
                            return
                    
                    if self.hide_ok_results:
                        # Use a list comprehension to check if all meas_value elements are within tolerance
                        hide_columns = all(LSL <= meas_value <= USL for meas_value in header_group['MEAS'])
                        if hide_columns:
                            worksheet.set_column(col - 3, col - 1, 0)
                    

                # Freeze panes in the reference worksheet
                worksheet.freeze_panes(12, 0)
        except Exception as e:
            self.log_and_exit(e)
        
    def export_filtered_data(self, excel_writer):
        try:
            if self._check_canceled():
                return
            data, column_names = execute_export_query(self.db_file, self.filter_query)
            self.write_data_to_excel(data, column_names, "MEASUREMENTS", excel_writer)
        except Exception as e:
            self.log_and_exit(e)

    def write_data_to_excel(self, data, column_names, table_name, excel_writer):
        try:
            if self._check_canceled():
                return
            # Convert the data to a DataFrame
            df = build_export_dataframe(data, column_names)

            # Write the DataFrame to the Excel file
            safe_table_name = unique_sheet_name(table_name, set(excel_writer.sheets.keys()))
            df.to_excel(excel_writer, sheet_name=safe_table_name, index=False)
            worksheet = excel_writer.sheets[safe_table_name]

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
            minimum = summary_stats['minimum']
            maximum = summary_stats['maximum']
            sigma = summary_stats['sigma']
            average = summary_stats['average']
            median = summary_stats['median']
            Cp = summary_stats['cp']
            Cpk = summary_stats['cpk']
            samplesize = summary_stats['sample_size']
            NOK_nb = summary_stats['nok_count']
            NOK_pct = summary_stats['nok_pct']
            
            # Create a Matplotlib figure and plot the scatter chart with lines
            # Set global font size
            plt.rcParams.update({'font.size': 8, 'axes.labelsize': 8, 'axes.titlesize': 10})
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
                    plt.violinplot(values,
                                   showmeans=True,
                                   showmedians=False,
                                   showextrema=True)
                    plt.xticks(range(1, len(labels) + 1), labels)
                else:
                    ax.scatter(header_group['GROUP'], header_group['MEAS'], label=header, color='blue', marker='.')
            else:
                labels, values, can_render_violin = self._build_violin_payload(
                    header_group,
                    'SAMPLE_NUMBER',
                    self.violin_plot_min_samplesize,
                )
                if can_render_violin:
                    plt.violinplot(values,
                                   showmeans=True,
                                   showmedians=False,
                                   showextrema=True)
                    plt.xticks(range(1, len(labels) + 1), labels)
                else:
                    ax.scatter(header_group['SAMPLE_NUMBER'], header_group['MEAS'], label=header, color='blue', marker='.')
            
            ax.axhline(y=USL, color='red', linestyle='--', label='Upper Limit (USL)')
            ax.axhline(y=LSL, color='red', linestyle='--', label='Lower Limit (LSL)')
            
            # Get the current y-axis limits
            current_y_limits = ax.get_ylim()

            # Calculate data range
            data_range = current_y_limits[1] - current_y_limits[0]

            # Calculate new y-axis limits based on the data range and scale factor
            y_min = current_y_limits[0] - self.summary_plot_scale * data_range / 2
            y_max = current_y_limits[1] + self.summary_plot_scale * data_range / 2

            # Set y-axis limits using the Axes object
            ax.set_ylim(y_min, y_max)
            
            ax.set_xlabel('Sample #')
            ax.set_ylabel('Measurement')
            ax.set_title(f'{header}')
            fig.savefig(imgplot, format="png")
            
            imgplot.seek(0)
            
            row = 0
            if col > 3:
                row = int(((col/3)-1)*20)
            summary_worksheet.write(row, 0, header)
            summary_worksheet.insert_image(row + 1, 0, "", {'image_data': imgplot})

            if self._check_canceled():
                plt.close(fig)
                return

            plt.close(fig)
            
            imgplot = BytesIO()
            # Plot the histogram with auto-defined bins
            fig, ax = plt.subplots(figsize=(6, 4))
            n, bins, patches = plt.hist(header_group['MEAS'], bins='auto', density=True, alpha=0.7, color='blue', edgecolor='black')
            
            # Add a table with statistics
            table_data = [
                ('Min', round(minimum, 3)),
                ('Max', round(maximum, 3)),
                ('Mean', round(average, 3)),
                ('Median', round(median, 3)),
                ('Std Dev', round(sigma, 3)),
                ('Cp', Cp if isinstance(Cp, str) else round(Cp, 2)),
                ('Cpk', Cpk if isinstance(Cpk, str) else round(Cpk, 2)),
                ('Samples', round(samplesize, 1)),
                ('NOK nb', round(NOK_nb, 1)),
                ('NOK %', round(NOK_pct, 2)),
            ]

            ax_table = plt.table(cellText=table_data,
                            colLabels=['Statistic', 'Value'],
                            cellLoc='center',
                            loc='right',
                            bbox=[1, 0, 0.3, 1])

            # Format the table
            ax_table.auto_set_font_size(False)
            ax_table.set_fontsize(8)

            # Fit a normal distribution to the data. If the measured values are
            # constant, std can be 0 and scipy emits divide-by-zero warnings.
            mu, std = norm.fit(header_group['MEAS'])
            if std > 0:
                # Plot the Gaussian curve
                xmin, xmax = plt.xlim()
                x = np.linspace(xmin, xmax, 100)
                p = norm.pdf(x, mu, std)
                plt.plot(x, p, 'k', linewidth=2)
            
            # Add vertical lines for mean, LSL and USL
            plt.axvline(average, color='red', linestyle='dashed', linewidth=2, label=f'Mean = {average:.3f}')
            plt.axvline(USL, color='green', linestyle='dashed', linewidth=2, label=f'USL = {USL:.3f}')
            plt.axvline(LSL, color='green', linestyle='dashed', linewidth=2, label=f'LSL = {LSL:.3f}')
            
            # Get current y-axis limits
            y_min, y_max = plt.ylim()

            # Add text annotations for mean, LSL and USL
            plt.text(average, y_max*0.95, f'Mean = {average:.3f}', color='red', ha='left', va='top', bbox = dict(facecolor = 'white'))
            plt.text(USL, y_max*0.9, f'USL = {USL:.3f}', color='green', ha='right', va='top', bbox = dict(facecolor = 'white'))
            plt.text(LSL, y_max*0.85, f'LSL = {LSL:.3f}', color='green', ha='left', va='top', bbox = dict(facecolor = 'white'))

            # Set labels and title
            plt.xlabel('Measurement')
            plt.ylabel('Frequency')
            plt.title(f'{header}')
            
            plt.subplots_adjust(right=0.75)
            
            fig.savefig(imgplot, format="png")
            imgplot.seek(0)
            summary_worksheet.insert_image(row + 1, 9, "", {'image_data': imgplot})

            if self._check_canceled():
                plt.close(fig)
                return

            plt.close(fig)
            
            imgplot = BytesIO()
            plt.rcParams.update({'font.size': 8, 'axes.labelsize': 8, 'axes.titlesize': 10})
            
            data_x = list(range(0, header_group['MEAS'].count()))
            data_y = header_group['MEAS']

            unique_labels = []
            for label in header_group['SAMPLE_NUMBER']:
                if label not in unique_labels:
                    unique_labels.append(label)
                else:
                    unique_labels.append('')

            fig, ax = plt.subplots(figsize=(6, 4))

            # Scatter plot
            ax.scatter(data_x, data_y, label=header, color='blue', marker='.')

            ax.axhline(y=USL, color='red', linestyle='--', label='Upper Limit (USL)')
            ax.axhline(y=LSL, color='red', linestyle='--', label='Lower Limit (LSL)')
            ax.set_xlabel('Sample #')
            ax.set_ylabel('Measurement')
            ax.set_title(f'{header}')

            # Set ticks and labels
            ax.set_xticks(data_x)
            ax.set_xticklabels(unique_labels)

            # Rotate the tick labels for better visibility
            plt.xticks(rotation=90)
            
            # Get the current y-axis limits
            current_y_limits = ax.get_ylim()

            # Calculate data range
            data_range = current_y_limits[1] - current_y_limits[0]

            # Calculate new y-axis limits based on the data range and scale factor
            y_min = current_y_limits[0] - self.summary_plot_scale * data_range / 2
            y_max = current_y_limits[1] + self.summary_plot_scale * data_range / 2

            # Set y-axis limits using the Axes object
            ax.set_ylim(y_min, y_max)

            # Saving the plot to BytesIO
            imgplot = BytesIO()
            fig.savefig(imgplot, format="png", bbox_inches='tight')
            imgplot.seek(0)
            summary_worksheet.insert_image(row + 1, 19, "", {'image_data': imgplot})
            plt.close(fig)
            
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)

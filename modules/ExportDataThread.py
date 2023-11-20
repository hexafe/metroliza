import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm
from PyQt5.QtCore import QCoreApplication, QThread, pyqtSignal
from io import BytesIO
import re
import sqlite3
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell, xl_range


class ExportDataThread(QThread):
    update_label = pyqtSignal(str)
    update_progress = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(
        self,
        db_file,
        excel_file,
        filter_query=None,
        selected_export_type="scatter",
        selected_sorting_parameter="date",
        violin_plot_min_samplesize=6,
        hide_ok_results=False,
        generate_summary_sheet=False,
        ):
        
        super().__init__()
        self.db_file = db_file
        self.excel_file = excel_file
        if not filter_query:
            filter_query = """
            SELECT MEASUREMENTS.AX, MEASUREMENTS.NOM, MEASUREMENTS."+TOL", 
                MEASUREMENTS."-TOL", MEASUREMENTS.BONUS, MEASUREMENTS.MEAS, 
                MEASUREMENTS.DEV, MEASUREMENTS.OUTTOL, MEASUREMENTS.HEADER, REPORTS.REFERENCE, 
                REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE, REPORTS.SAMPLE_NUMBER 
            FROM MEASUREMENTS
            JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
            WHERE 1=1
            """
        self.filter_query = filter_query
        self.selected_export_type = selected_export_type.lower()
        self.selected_sorting_parameter = selected_sorting_parameter.lower()
        self.violin_plot_min_samplesize = violin_plot_min_samplesize
        self.hide_ok_results = hide_ok_results
        self.generate_summary_sheet = generate_summary_sheet

    def run(self):
        # Connect to the SQLite database
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()

            # Retrieve the table names from the database
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")

            # Create an Excel writer using xlsxwriter engine
            excel_writer = pd.ExcelWriter(self.excel_file, engine='xlsxwriter')

            self.export_filtered_data(cursor, excel_writer)

            self.add_measurements_horizontal_sheet(cursor, excel_writer)

            excel_writer.close()

            self.update_label.emit("Export completed successfully.")
            self.finished.emit()
            QCoreApplication.processEvents()

    def add_measurements_horizontal_sheet(self, cursor, excel_writer):
        # Fetch data from the cursor
        df = pd.read_sql_query(self.filter_query, cursor.connection)
        df['HEADER - AX'] = df['HEADER'] + ' - ' + df['AX']

        # Group the data by reference
        reference_groups = df.groupby('REFERENCE', as_index=False)

        # Create the summary worksheet
        workbook = excel_writer.book

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
            # Reset the column tracking for new sheet
            col = 0
            
            # Check if ref has invalid Excel characters for sheet
            invalid_chars = r'[\[\]:\*\?/\\]'
            ref = re.sub(invalid_chars, '', ref)

            # Create a worksheet for each reference
            worksheet = workbook.add_worksheet(ref)
            if self.generate_summary_sheet:
                summary_worksheet = workbook.add_worksheet(f"{ref}_summary")

            # Set the default cell format for the worksheet
            worksheet.set_column(0, max_col, column_width, cell_format=default_format)

            # # Set border format for the first column of the worksheet
            # worksheet.set_column(0, 0, column_width, cell_format=border_format)

            # Group the data by header within the reference
            header_groups = ref_group.groupby('HEADER - AX', as_index=False)

            for (header, header_group) in header_groups:
                if self.selected_sorting_parameter == "sample #":
                    header_group.sort_values(by='SAMPLE_NUMBER', inplace=True)
                else:
                    header_group.sort_values(by='DATE', inplace=True)
                
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
                x_range = f"={ref}!${data_range_x}"
                y_range = f"={ref}!${data_range_y}"

                # Add the series to the chart
                chart.add_series({
                    'name': header,
                    'categories': x_range,
                    'values': y_range,
                })

                # Configure the chart properties
                chart.set_title({'name': f'{header}', 'name_font': {'size': 10}})
                # chart.set_x_axis({
                #     'min': 0,
                #     'max': num_rows + 1,
                # })
                chart.set_y_axis({
                    # 'name': f'{header}',
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
                
                if self.generate_summary_sheet:
                    self.summary_sheet_fill(summary_worksheet, header, header_group, col)
                
                if self.hide_ok_results:
                    # Use a list comprehension to check if all meas_value elements are within tolerance
                    hide_columns = all(LSL <= meas_value <= USL for meas_value in header_group['MEAS'])
                    if hide_columns:
                        worksheet.set_column(col - 3, col - 1, 0)
                

            # Freeze panes in the reference worksheet
            worksheet.freeze_panes(12, 0)
        
    def export_filtered_data(self, cursor, excel_writer):
        export_query = self.filter_query
        cursor.execute(export_query)
        data = cursor.fetchall()
        column_names = [desc[0] for desc in cursor.description]

        # Write the data to the Excel file
        self.write_data_to_excel(data, column_names, "MEASUREMENTS", excel_writer)

    def write_data_to_excel(self, data, column_names, table_name, excel_writer):
        # Convert the data to a DataFrame
        df = pd.DataFrame(data, columns=column_names)

        # Write the DataFrame to the Excel file
        df.to_excel(excel_writer, sheet_name=table_name, index=False)
        worksheet = excel_writer.sheets[table_name]

        # Apply autofilter to enable filtering
        worksheet.autofilter(0, 0, df.shape[0], df.shape[1] - 1)

        # Freeze first row
        worksheet.freeze_panes(1, 0)

        # Adjust the column widths based on the data
        for i, column in enumerate(df.columns):
            column_width = self.calculate_column_width(df[column])
            worksheet.set_column(i, i, column_width)

    def calculate_column_width(self, data):
        if data.empty:
            return 12  # Return a default width 12 if the data is empty

        # Convert series to a list and calculate the column width based on the maximum length of the data in the column
        column_width = data.astype(str).apply(len).max()
        column_width = min(column_width, 40)
        column_width = max(column_width, 12)
        return column_width
    
    def summary_sheet_fill(self, summary_worksheet, header, header_group, col):
        imgplot = BytesIO()
        nom = round(header_group['NOM'].iloc[0], 3)
        USL = round(header_group['+TOL'].iloc[0], 3)
        USL = nom + USL
        if header_group['-TOL'].iloc[0]:
            LSL = round(header_group['-TOL'].iloc[0], 3)
        else:
            LSL = 0
        LSL = nom + LSL
        minimum = header_group['MEAS'].min()
        maximum = header_group['MEAS'].max()
        sigma = header_group['MEAS'].std()
        average = header_group['MEAS'].mean()
        median = header_group['MEAS'].median()
        Cp = (USL - LSL)/(6 * sigma)
        if nom == 0 and LSL == 0:
            Cpk = (USL - average)/(3 * sigma)
        else:
            Cpk = min((USL - average)/(3 * sigma), (average - LSL)/(3 * sigma))
        samplesize = header_group['MEAS'].count()
        NOK_nb = header_group[header_group['MEAS'] > USL]['MEAS'].count() + header_group[header_group['MEAS'] < LSL]['MEAS'].count()
        NOK_pct = NOK_nb/samplesize
        
        # Create a Matplotlib figure and plot the scatter chart with lines
        # Set global font size
        plt.rcParams.update({'font.size': 8, 'axes.labelsize': 8, 'axes.titlesize': 10})
        fig, ax = plt.subplots(figsize=(6, 4))
        
        if (header_group.groupby('SAMPLE_NUMBER')['MEAS'].nunique() >= self.violin_plot_min_samplesize).all():
           plt.violinplot(header_group.groupby('SAMPLE_NUMBER')['MEAS'].apply(list),
                          showmeans=True,
                          showmedians=False,
                          showextrema=True)
           xtick_labels = header_group['SAMPLE_NUMBER'].unique()
           plt.xticks(range(1, len(xtick_labels) + 1), xtick_labels)
        else:
            ax.scatter(header_group['SAMPLE_NUMBER'], header_group['MEAS'], label=header, color='blue', marker='.')
        
        ax.axhline(y=USL, color='red', linestyle='--', label='Upper Limit (USL)')
        ax.axhline(y=LSL, color='red', linestyle='--', label='Lower Limit (LSL)')
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
            ('Cp', round(Cp, 2)),
            ('Cpk', round(Cpk, 2)),
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

        # Fit a normal distribution to the data
        mu, std = norm.fit(header_group['MEAS'])

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
        
        plt.close(fig)
        
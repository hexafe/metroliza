import pandas as pd
import numpy as np
from PyQt5.QtCore import QCoreApplication, QThread, pyqtSignal
import math
import re
import sqlite3
import xlsxwriter


class ExportDataThread(QThread):
    update_label = pyqtSignal(str)
    update_progress = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, db_file, excel_file, filter_query=None):
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

            # Set the default cell format for the worksheet
            worksheet.set_column(0, max_col, column_width, cell_format=default_format)

            # # Set border format for the first column of the worksheet
            # worksheet.set_column(0, 0, column_width, cell_format=border_format)

            # Group the data by header within the reference
            header_groups = ref_group.groupby('HEADER - AX', as_index=False)

            for (header, header_group) in header_groups:
                worksheet.write(0, col, 'NOM')
                nom = round(header_group['NOM'].iloc[0], 3)
                worksheet.write(0, col + 1, nom)
                
                worksheet.write(1, col, '+TOL')
                USL = round(header_group['+TOL'].iloc[0], 3)
                worksheet.write(1, col + 1, USL)
                USL = nom + USL
                
                worksheet.write(2, col, '-TOL')
                if header_group['-TOL'].iloc[0]:
                    LSL = round(header_group['-TOL'].iloc[0], 3)
                else:
                    LSL = 0
                worksheet.write(2, col + 1, LSL)
                LSL = nom + LSL
                
                worksheet.write(3, col, 'MIN')
                min_meas = round(header_group['MEAS'].min(), 3)
                worksheet.write(3, col + 1, min_meas)
                
                worksheet.write(4, col, 'AVG')
                avg_meas = round(header_group['MEAS'].mean(), 3)
                worksheet.write(4, col + 1, avg_meas)
                
                worksheet.write(5, col, 'MAX')
                max_meas = round(header_group['MEAS'].max(), 3)
                worksheet.write(5, col + 1, max_meas)
                
                worksheet.write(6, col, 'STD')
                if np.isnan(header_group['MEAS'].std()) or np.isinf(header_group['MEAS'].std()):
                    sigma = round(0, 3)
                else:
                    sigma = round(header_group['MEAS'].std(), 3)
                worksheet.write(6, col + 1, sigma)
                
                worksheet.write(7, col, 'Cp')
                if sigma:
                    Cp = round((USL - LSL)/(6 * sigma), 3)
                else:
                    Cp = 0
                if np.isnan(Cp) or np.isinf(Cp):
                    Cp = 0
                worksheet.write(7, col + 1, Cp)
                
                worksheet.write(8, col, 'Cpk')
                if sigma:
                    Cpk = round(min((USL - avg_meas)/(3 * sigma), (avg_meas - LSL)/(3 * sigma)), 3)
                else:
                    Cpk = 0
                if np.isnan(Cpk) or np.isinf(Cpk):
                    Cpk = 0
                worksheet.write(8, col + 1, Cpk)
                
                worksheet.write(10, col, 'Date')
                worksheet.write_column(11, col, header_group['DATE'])
                
                worksheet.write(10, col + 1, 'Sample #')
                worksheet.write_column(11, col + 1, header_group['SAMPLE_NUMBER'])
                
                worksheet.write(10, col + 2, header)
                worksheet.write_column(11, col + 2, round(header_group['MEAS'], 3))
                
                # Define the format for conditional formatting (highlight cells in red)
                red_format = workbook.add_format({'bg_color': 'red', 'font_color': 'white', 'align': 'center', 'valign': 'vcenter', 'right': 1})

                # Apply conditional formatting to highlight cells greater than USL in red
                worksheet.conditional_format(11, col + 2, len(header_group) + 10, col + 2,
                                            {'type': 'cell', 'criteria': '>', 'value': USL, 'format': red_format})

                # Apply conditional formatting to highlight cells lower than LSL in red
                worksheet.conditional_format(11, col + 2, len(header_group) + 10, col + 2,
                                            {'type': 'cell', 'criteria': '<', 'value': LSL, 'format': red_format})
                
                col += 3

                # Merge cells for the header
                header_col_end = col - 1

                # Set border format for last column of header for worksheet
                worksheet.set_column(header_col_end, header_col_end, None, cell_format=border_format)

            # Freeze panes in the reference worksheet
            worksheet.freeze_panes(11, 0)
        
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
            return 12  # Return a default width if the data is empty

        # Convert series to a list and calculate the column width based on the maximum length of the data in the column
        column_width = data.astype(str).apply(len).max()
        column_width = min(column_width, 40)
        column_width = max(column_width, 12)
        return column_width
    
import pandas as pd
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
                REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE 
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
        cursor.execute(self.filter_query)
        data = cursor.fetchall()
        column_names = [desc[0] for desc in cursor.description]

        # Create a DataFrame from the fetched data
        df = pd.DataFrame(data, columns=column_names)
        df['HEADER - AX'] = df['HEADER'] + ' - ' + df['AX']

        # Group the data by reference
        reference_groups = df.groupby('REFERENCE')

        # Create the summary worksheet
        workbook = excel_writer.book
        summary_worksheet = workbook.add_worksheet('SUMMARY')
        summary_row_names = ['REFERENCE', 'HEADER', 'AX', 'NOM', 'MIN', 'MAX', 'AVG', 'STD', 'Cp', 'Cpk', 'SAMPLES']

        # Write summary row names to the summary worksheet
        for index, name in enumerate(summary_row_names):
            summary_worksheet.write(index, 0, name)

        # Initialize variables for column and summary column tracking
        col = 1
        summary_col = 1
        summary_ref_col_added = 1

        # Define cell formats
        default_format = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
        border_format = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'right': 1})

        # Set the default cell format for the summary worksheet
        max_col = len(df['HEADER - AX'].unique())
        summary_worksheet.set_column(0, max_col, None, cell_format=default_format)

        # Set border format for the first column of the summary worksheet
        summary_worksheet.set_column(0, 0, None, cell_format=border_format)

        for (ref, ref_group) in reference_groups:
            # Check if ref has invalid Excel characters for sheet
            invalid_chars = r'[\[\]:\*\?/\\]'
            ref = re.sub(invalid_chars, '', ref)

            # Create a worksheet for each reference
            worksheet = workbook.add_worksheet(ref)

            # Set the default cell format for the worksheet
            worksheet.set_column(0, max_col, None, cell_format=default_format)

            # Set border format for the first column of the worksheet
            worksheet.set_column(0, 0, None, cell_format=border_format)

            worksheet.write(0, 0, 'HEADER')
            worksheet.write(1, 0, 'AX')

            # Reset the column tracking for new sheet
            col = 1
            summary_ref_col_added = summary_col

            # Write the reference value to the summary worksheet
            summary_worksheet.write(0, summary_col, ref)

            # Group the data by header within the reference
            header_groups = ref_group.groupby('HEADER')

            for (header, header_group) in header_groups:
                # Reset header col tracking
                header_col_added = col
                summary_header_col_added = summary_col

                # Write the header value to the worksheet and summary worksheet
                worksheet.write(0, col, header)
                summary_worksheet.write(1, summary_col, header)

                # Group the data by AX within the header
                ax_groups = header_group.groupby('AX')

                for (ax, ax_group) in ax_groups:
                    # Write the AX value to the worksheet and summary worksheet
                    worksheet.write(1, col, ax)
                    summary_worksheet.write(2, summary_col, ax)

                    # Write the measurement values to the worksheet
                    ax_values = ax_group['MEAS']
                    worksheet.write_column(2, col, ax_values)

                    # Write summary statistics to the summary worksheet
                    summary_worksheet.write(3, summary_col, ax_group['NOM'].iloc[0])
                    summary_worksheet.write(4, summary_col, ax_values.min())
                    summary_worksheet.write(5, summary_col, ax_values.max())
                    summary_worksheet.write(6, summary_col, ax_values.mean())
                    if math.isnan(ax_values.std()) or math.isinf(ax_values.std()):
                        summary_worksheet.write(7, summary_col, 0)
                    else:
                        summary_worksheet.write(7, summary_col, ax_values.std())

                    # Write the count of samples to the summary worksheet
                    summary_worksheet.write(10, summary_col, ax_values.count())

                    col += 1
                    summary_col += 1

                # Merge cells for the header
                header_col_end = col - 1
                summary_header_col_end = summary_col - 1
                if header_col_added != header_col_end:
                    worksheet.merge_range(0, header_col_added, 0, header_col_end, header)
                if summary_header_col_added != summary_header_col_end:
                    summary_worksheet.merge_range(1, summary_header_col_added, 1, summary_header_col_end, header)

                # Set border format for last column of header for worksheet
                worksheet.set_column(header_col_end, header_col_end, None, cell_format=border_format)

            # Merge cells for the reference in the summary worksheet
            summary_ref_col_end = summary_col - 1
            if summary_ref_col_added != summary_ref_col_end:
                summary_worksheet.merge_range(0, summary_ref_col_added, 0, summary_ref_col_end, ref)

            # Set border format for last column of reference for summary worksheet
            summary_worksheet.set_column(summary_ref_col_end, summary_ref_col_end, None, cell_format=border_format)

            # Freeze panes in the reference worksheet
            worksheet.freeze_panes(2, 1)

        # Freeze panes in the summary worksheet
        summary_worksheet.freeze_panes(3, 1)

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
            return 10  # Return a default width if the data is empty

        # Convert series to a list and calculate the column width based on the maximum length of the data in the column
        column_width = data.astype(str).apply(len).max()
        column_width = min(column_width, 40)
        column_width = max(column_width, 10)
        return column_width
    
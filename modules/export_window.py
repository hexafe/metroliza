from PyQt5.QtGui import QMovie
from PyQt5.QtCore import (
    QThread,
    pyqtSignal,
    Qt,
    QDate,
    QTemporaryFile,
    QSize,
    QCoreApplication,
)
from PyQt5.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QGridLayout,
    QFileDialog,
    QProgressBar,
    QVBoxLayout,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QLineEdit,
    QDateEdit,
)
import sqlite3
import pandas as pd
import xlsxwriter
import base64
from modules import base64_encoded_files
from pathlib import Path
import math


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
        cursor.execute(self.filter_query)
        data = cursor.fetchall()
        column_names = [desc[0] for desc in cursor.description]

        # Create a DataFrame from the fetched data
        df = pd.DataFrame(data, columns=column_names)
        df['HEADER - AX'] = df['HEADER'] + ' - ' + df['AX']

        # Group the data by reference
        reference_groups = df.groupby('REFERENCE')

        # Create the sheet for horizontal measurements
        sheet_name = 'MEASUREMENTS_HORIZONTAL'
        ref_row = 0
        header_row = 1
        ax_row = 2
        meas_row = 3

        workbook = excel_writer.book
        worksheet = workbook.add_worksheet(sheet_name)
        default_format = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
        border_format = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'right': 2})

        summary_worksheet = workbook.add_worksheet('SUMMARY')
        summary_row_names = ['REFERENCE', 'HEADER', 'AX', 'NOM', 'MIN', 'MAX', 'AVG', 'STD', 'Cp', 'Cpk', 'SAMPLES',]

        # Write summary row names to the summary worksheet
        for index, name in enumerate(summary_row_names):
            summary_worksheet.write(index, 0, name)

        ref_col_added = 0
        header_col_added = 0
        col = 0

        for (ref, ref_group) in reference_groups:
            ref_col_added = col

            # Write the reference value
            worksheet.write(ref_row, col, ref)
            summary_worksheet.write(0, col + 1, ref)

            # Get the headers for the current reference
            header_groups = ref_group.groupby('HEADER')

            for (header, header_group) in header_groups:
                header_col_added = col

                # Write the header value
                worksheet.write(header_row, col, header)
                summary_worksheet.write(1, col + 1, header)

                # Get the headers for the current reference
                ax_groups = header_group.groupby('AX')

                for (ax, ax_group) in ax_groups:
                    ax_values = ax_group['MEAS']

                    # Write the AX value
                    worksheet.write(ax_row, col, ax)
                    summary_worksheet.write(2, col + 1, ax)

                    # Write the measurement values
                    ax_values = ax_group['MEAS']
                    for i, meas_value in enumerate(ax_values):
                        worksheet.write(meas_row + i, col, meas_value)
                        
                    summary_worksheet.write(10, col + 1, ax_values.count())

                    # Write summary statistics to the summary worksheet
                    summary_worksheet.write(3, col + 1, ax_group['NOM'].iloc[0])
                    summary_worksheet.write(4, col + 1, ax_values.min())
                    summary_worksheet.write(5, col + 1, ax_values.max())
                    summary_worksheet.write(6, col + 1, ax_values.mean())
                    if math.isnan(ax_values.std()) or math.isinf(ax_values.std()):
                        summary_worksheet.write(7, col + 1, 0)
                    else:
                        summary_worksheet.write(7, col + 1, ax_values.std())

                    col += 1

                # Merge cells for the header
                header_col_end = col - 1
                if header_col_added != header_col_end:
                    worksheet.merge_range(header_row, header_col_added, header_row, header_col_end, header)
                    summary_worksheet.merge_range(1, header_col_added + 1, 1, header_col_end + 1, header)

            # Merge cells for the reference
            ref_col_end = col - 1
            if ref_col_added != ref_col_end:
                worksheet.merge_range(ref_row, ref_col_added, ref_row, ref_col_end, ref)
                summary_worksheet.merge_range(0, ref_col_added + 1, 0, ref_col_end + 1, ref)

        # Set the default cell format for the worksheet (middle-aligned and centered)
        worksheet.set_column(0, col, None, cell_format=default_format)
        summary_worksheet.set_column(0, col + 1, None, cell_format=default_format)

        # Set border format for the first column of the summary worksheet
        summary_worksheet.set_column(0, 0, None, border_format)

        prev_last_ref_col = 0
        for (ref, ref_group) in reference_groups:
            last_ref_col = len(ref_group['HEADER - AX'].unique().tolist()) - 1
            prev_last_ref_col += last_ref_col

            # Set border format for the last column of each reference in the worksheet
            worksheet.set_column(prev_last_ref_col, prev_last_ref_col, None, border_format)

            # Set border format for the last column of each reference in the summary worksheet
            summary_worksheet.set_column(prev_last_ref_col + 1, prev_last_ref_col + 1, None, border_format)
            prev_last_ref_col += 1

        # Freeze panes in the worksheets
        worksheet.freeze_panes(3, 0)
        summary_worksheet.freeze_panes(0, 1)

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
        column_width = max(len(str(value)) for value in data.tolist()) + 2
        column_width = min(column_width, 40)
        column_width = max(column_width, 10)
        return column_width


class ExportDialog(QDialog):
    def __init__(self, parent=None, db_file=""):
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.setWindowIcon(parent.windowIcon())
        self.setGeometry(100, 100, 300, 150)

        self.db_file = db_file
        self.excel_file = ""
        self.filter_query = None

        self.init_widgets()
        self.init_layout()

    def init_widgets(self):
        """Initialize the widgets"""
        self.select_db_label = QLabel("Select a database file:")
        self.select_db_button = QPushButton("Browse")
        self.select_db_button.clicked.connect(self.select_db_file)
        
        self.filter_button = QPushButton("Filter")
        self.filter_button.clicked.connect(self.open_filter_window)
        
        self.select_excel_label = QLabel("Select an excel file:")
        self.select_excel_button = QPushButton("Browse")
        self.select_excel_button.clicked.connect(self.select_excel_file)
        
        self.export_button = QPushButton("Export")
        self.export_button.setDisabled(True)
        self.export_button.clicked.connect(self.show_loading_screen)
        
        self.select_filter_label = QLabel("Select filters (optional): not applied")
        
        self.spacer = QLabel(" ")
        
        if self.db_file:
            self.database_text_label = QLabel(self.db_file)
            self.select_excel_button.setEnabled(True)
            self.filter_button.setEnabled(True)
        else:
            self.database_text_label = QLabel("None selected")
            self.filter_button.setDisabled(True)
            self.select_excel_button.setDisabled(True)
            
        if self.excel_file:
            self.excel_file_text_label = QLabel(self.excel_file)
            self.export_button.setEnabled(True)
        else:
            self.excel_file_text_label = QLabel("None selected")
            self.export_button.setEnabled(False)

    def init_layout(self):
        """Initialize the layout"""
        self.layout = QGridLayout()
        
        self.layout.addWidget(self.select_db_label, 0, 0)
        self.layout.addWidget(self.database_text_label, 1, 0)
        self.layout.addWidget(self.select_db_button, 2, 0, 1, 2)
        self.layout.addWidget(self.spacer, 3, 0)
        
        self.layout.addWidget(self.select_excel_label, 4, 0)
        self.layout.addWidget(self.excel_file_text_label, 5, 0)
        self.layout.addWidget(self.select_excel_button, 6, 0, 1, 2)
        self.layout.addWidget(self.spacer, 7, 0)
        
        self.layout.addWidget(self.select_filter_label, 8, 0)
        self.layout.addWidget(self.filter_button, 9, 0, 1, 2)
        self.layout.addWidget(self.spacer, 10, 0)
        
        self.layout.addWidget(self.export_button, 11, 0, 1, 2)
        
        self.setLayout(self.layout)

    def select_db_file(self):
        """Open a file dialog to select a database file"""
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        filename, _ = QFileDialog.getOpenFileName(self, "Select a database file", "",
                                                  "SQLite database (*.db);;All files (*)", options=options)
        if filename:
            if not filename.endswith(".db"):
                filename += ".db"
            print(f"{filename=}")
            self.db_file = filename
            self.database_text_label.setText(filename)
            self.select_excel_button.setEnabled(True)
            self.filter_button.setEnabled(True)
            self.parent().set_db_file(filename)

    def open_filter_window(self):
        """Open window used for filtering references, headers and dates of measurements"""
        # Create the filter window as a QDialog
        self.filter_window = QDialog(self)
        self.filter_window.setWindowTitle("Data filtering")
        self.filter_window.setModal(True)

        # Create labels and list widgets for each column to be filtered
        ax_label = QLabel("AX:")
        self.ax_list = QListWidget()
        self.ax_list.setSelectionMode(QAbstractItemView.MultiSelection)

        reference_label = QLabel("REFERENCE:")
        self.reference_list = QListWidget()
        self.reference_list.setSelectionMode(QAbstractItemView.MultiSelection)

        header_label = QLabel("HEADER:")
        self.header_list = QListWidget()
        self.header_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.all_headers_list = QListWidget()
        self.all_headers_list.setSelectionMode(QAbstractItemView.MultiSelection)

        date_from_label = QLabel("MEASUREMENT DATE FROM:")
        self.date_from_calendar = QDateEdit(calendarPopup=True)
        self.date_from_calendar.setCalendarPopup(True)
        self.date_from_calendar.setDate(QDate(1970, 1, 1))
        self.date_from_calendar.setMinimumWidth(100)

        date_to_label = QLabel("MEASUREMENT DATE TO:")
        self.date_to_calendar = QDateEdit(calendarPopup=True)
        self.date_to_calendar.setCalendarPopup(True)
        self.date_to_calendar.setDate(QDate.currentDate())
        self.date_to_calendar.setMinimumWidth(100)

        # Set the default selection for list widgets as "SELECT ALL"
        self.ax_list.addItem("SELECT ALL")
        self.reference_list.addItem("SELECT ALL")
        self.header_list.addItem("SELECT ALL")
        self.all_headers_list.addItem("SELECT ALL")

        # Create separate QLineEdit widgets for searching in each list widget
        self.ax_search_input = QLineEdit()
        self.ax_search_input.setPlaceholderText("Search AX...")
        self.reference_search_input = QLineEdit()
        self.reference_search_input.setPlaceholderText("Search REFERENCE...")
        self.header_search_input = QLineEdit()
        self.header_search_input.setPlaceholderText("Search HEADER...")

        # Create a button to apply the filters
        apply_button = QPushButton("Apply filters")
        apply_button.clicked.connect(self.apply_filters)

        # Create a button to select today's date as "date TO"
        select_today_button = QPushButton("Select today")
        select_today_button.clicked.connect(self.select_today_as_date_to)

        # Create a button to select the beginning of time
        select_beginning_button = QPushButton("Select beginning of time")
        select_beginning_button.clicked.connect(self.select_beginning_of_time)

        # Create a grid layout for the filter window
        layout = QGridLayout(self.filter_window)

        # Add labels and widgets to the grid layout
        layout.addWidget(ax_label, 0, 0)
        layout.addWidget(self.ax_search_input, 1, 0)
        layout.addWidget(self.ax_list, 2, 0)

        layout.addWidget(reference_label, 0, 1)
        layout.addWidget(self.reference_search_input, 1, 1)
        layout.addWidget(self.reference_list, 2, 1)

        layout.addWidget(header_label, 0, 2)
        layout.addWidget(self.header_search_input, 1, 2)
        layout.addWidget(self.header_list, 2, 2)

        layout.addWidget(date_from_label, 3, 0)
        layout.addWidget(self.date_from_calendar, 3, 1)

        layout.addWidget(date_to_label, 4, 0)
        layout.addWidget(self.date_to_calendar, 4, 1)
        
        # Set the fixed widths for elements in column 0 and column 1
        for row in range(layout.rowCount()):
            for column in range(layout.columnCount()):
                item = layout.itemAtPosition(row, column)
                if item is not None:
                    widget = item.widget()
                    if widget is not None:
                        if column == 0:
                            widget.setFixedWidth(150)
                        elif column == 1:
                            widget.setFixedWidth(150)

        # Add buttons to the layout
        layout.addWidget(select_beginning_button, 3, 2)
        layout.addWidget(select_today_button, 4, 2)
        layout.addWidget(apply_button, 6, 0, 1, 3)
        
        # Populate the list widgets with unique values from the columns in the database
        self.populate_list_widgets()

        # Connect the search input signals
        self.ax_search_input.textChanged.connect(lambda: self.search_list_widgets(self.ax_list, self.ax_search_input.text()))
        self.header_search_input.textChanged.connect(lambda: self.search_list_widgets(self.header_list, self.header_search_input.text()))
        self.reference_search_input.textChanged.connect(lambda: self.search_list_widgets(self.reference_list, self.reference_search_input.text()))

        # Show the filter window
        self.filter_window.show()

    def search_list_widgets(self, list_widget, search_text):
        selected_items = list_widget.selectedItems()

        list_widget.clearSelection()

        if not search_text:
            # Show all items if search text is empty
            for row in range(list_widget.count()):
                item = list_widget.item(row)
                item.setHidden(False)

            # Restore the previously selected items
            for item in selected_items:
                item.setSelected(True)

            return

        # Perform case-insensitive search
        search_text = search_text.lower()

        # Iterate over items and hide those that don't match the search text
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            item_text = item.text().lower()
            if search_text in item_text:
                item.setHidden(False)
            else:
                item.setHidden(True)

        # Restore the previously selected items
        for item in selected_items:
            item.setSelected(True)

    def populate_list_widgets(self):
        try:
            # Connect to the SQLite database
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()

                # Get unique values from AX column
                cursor.execute("SELECT DISTINCT AX FROM MEASUREMENTS;")
                ax_values = cursor.fetchall()
                for value in ax_values:
                    item = QListWidgetItem(value[0])
                    self.ax_list.addItem(item)

                # Get unique values from HEADER column
                cursor.execute("SELECT DISTINCT HEADER FROM MEASUREMENTS;")
                header_values = cursor.fetchall()
                for value in header_values:
                    header_item = QListWidgetItem(value[0])
                    all_headers_item = QListWidgetItem(value[0])
                    self.header_list.addItem(header_item)
                    self.all_headers_list.addItem(all_headers_item)

                # Get unique values from REFERENCE column
                cursor.execute("SELECT DISTINCT REFERENCE FROM REPORTS;")
                reference_values = cursor.fetchall()
                for value in reference_values:
                    item = QListWidgetItem(value[0])
                    self.reference_list.addItem(item)

        except sqlite3.Error as e:
            print(f"Error accessing the database: {e}")
            return

        cursor.close()

        # Connect the itemSelectionChanged signal of the reference_list to the on_reference_selection_changed method
        self.reference_list.itemSelectionChanged.connect(self.on_reference_selection_changed)

    def on_reference_selection_changed(self):
        selected_references = [item.text() for item in self.reference_list.selectedItems()]

        # Clear the current items in the HEADER list widget
        self.header_list.clear()

        if selected_references and "SELECT ALL" not in selected_references:
            try:
                # Connect to the SQLite database
                with sqlite3.connect(self.db_file) as conn:
                    cursor = conn.cursor()

                    # Get unique values from HEADER column based on the selected references
                    reference_values = "','".join(selected_references)
                    query = f"""
                        SELECT DISTINCT HEADER FROM MEASUREMENTS 
                        JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID 
                        WHERE REFERENCE IN (SELECT REFERENCE FROM REPORTS WHERE REFERENCE IN ('{reference_values}'));
                        """
                    cursor.execute(query)
                    header_values = cursor.fetchall()
                    for value in header_values:
                        item = QListWidgetItem(value[0])
                        self.header_list.addItem(item)

            except sqlite3.Error as e:
                print(f"Error accessing the database: {e}")
                return

            cursor.close()
        else:
            # Add all headers from all_headers_list when no references are selected
            for row in range(self.all_headers_list.count()):
                item = self.all_headers_list.item(row)
                self.header_list.addItem(item.text())

    def select_beginning_of_time(self):
        beginning_of_time = QDate(1970, 1, 1)
        self.date_from_calendar.setDate(beginning_of_time)

    def select_today_as_date_to(self):
        today = QDate.currentDate()
        self.date_to_calendar.setDate(today)

    def apply_filters(self):
        # Get the selected values from the list widgets and calendars
        ax_selected_items = [item.text() for item in self.ax_list.selectedItems()]
        header_selected_items = [item.text() for item in self.header_list.selectedItems()]
        reference_selected_items = [item.text() for item in self.reference_list.selectedItems()]
        date_from = self.date_from_calendar.date().toString("yyyy-MM-dd")
        date_to = self.date_to_calendar.date().toString("yyyy-MM-dd")

        # Construct the filter query based on the selected values
        query = """
            SELECT MEASUREMENTS.AX, MEASUREMENTS.NOM, MEASUREMENTS."+TOL", 
                MEASUREMENTS."-TOL", MEASUREMENTS.BONUS, MEASUREMENTS.MEAS, 
                MEASUREMENTS.DEV, MEASUREMENTS.OUTTOL, MEASUREMENTS.HEADER, REPORTS.REFERENCE, 
                REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE 
            FROM MEASUREMENTS
            JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
            WHERE 1=1
            """

        if ax_selected_items and "SELECT ALL" not in ax_selected_items:
            ax_values = "','".join(ax_selected_items)
            query += f" AND MEASUREMENTS.AX IN ('{ax_values}')"

        if header_selected_items and "SELECT ALL" not in header_selected_items:
            header_values = "','".join(header_selected_items)
            query += f" AND MEASUREMENTS.HEADER IN ('{header_values}')"

        if reference_selected_items and "SELECT ALL" not in reference_selected_items:
            reference_values = "','".join(reference_selected_items)
            query += f" AND REPORTS.REFERENCE IN ('{reference_values}')"

        if date_from:
            query += f" AND REPORTS.DATE >= '{date_from}'"

        if date_to:
            query += f" AND REPORTS.DATE <= '{date_to}'"

        self.filter_query = query
        
        # Update filter label in export window
        self.select_filter_label.setText("Select filters (optional): applied")

        # Close the filter window
        self.filter_window.close()

        # Enable the select excel button
        self.select_excel_button.setEnabled(True)

    def select_excel_file(self):
        """Open a file dialog to select an excel file"""
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        default_name = self.db_file[:-3]
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

        filename, _ = QFileDialog.getSaveFileName(self, "Select an Excel file", str(file_path),
                                                "Excel workbook (*.xlsx);;All files (*)", options=options)

        if filename:
            file_path = Path(filename)
            print(f"{file_path=}")
            self.excel_file = file_path
            self.excel_file_text_label.setText(str(file_path))
            self.export_button.setEnabled(True)

    def show_loading_screen(self):
        # Create the progress dialog
        self.loading_dialog = QDialog(self, Qt.WindowTitleHint)
        self.loading_dialog.setWindowTitle("Exporting data...")
        self.loading_dialog.setWindowModality(Qt.ApplicationModal)
        self.loading_dialog.setFixedSize(400, 300)

        # Create a QLabel to display the loading GIF
        loading_gif_label = QLabel(self.loading_dialog)
        loading_gif_label.setFixedSize(200, 200)
        loading_gif_label.setAlignment(Qt.AlignCenter)

        # Load the loading.gif from a file, create a QMovie from it, and set it to the label
        loading_gif_decoded = base64.b64decode(base64_encoded_files.encoded_loading_gif)

        # Create temporary file and save encoded loading gif to it
        temp_file = QTemporaryFile()
        temp_file.setAutoRemove(False)
        temp_file_name = ""
        if temp_file.open():
            temp_file.write(loading_gif_decoded)
            temp_file.close()
            temp_file_name = temp_file.fileName()

        # Create the QMovie using the temporary file name
        self.loading_gif = QMovie(temp_file_name)
        self.loading_gif.setScaledSize(QSize(200, 200))
        loading_gif_label.setMovie(self.loading_gif)
        self.loading_gif.start()

        # Create the loading label and progress bar
        self.loading_label = QLabel("Exporting data...", self.loading_dialog)
        self.loading_label.setAlignment(Qt.AlignCenter)

        self.loading_bar = QProgressBar(self.loading_dialog)
        self.loading_bar.setValue(0)
        self.loading_bar.setFixedSize(380, 20)
        self.loading_bar.setAlignment(Qt.AlignCenter)

        # Create a layout for the progress dialog and add the loading GIF, loading label, and progress bar to it
        layout = QVBoxLayout(self.loading_dialog)
        layout.addWidget(loading_gif_label, alignment=Qt.AlignHCenter)
        layout.addWidget(self.loading_label, alignment=Qt.AlignHCenter)
        layout.addWidget(self.loading_bar, alignment=Qt.AlignHCenter)

        # Create and add the Cancel button to the layout
        cancel_button = QPushButton("Cancel", self.loading_dialog)
        cancel_button.clicked.connect(self.stop_exporting)
        layout.addWidget(cancel_button, alignment=Qt.AlignHCenter)

        # Disable the export button and show the progress dialog
        self.export_button.setDisabled(True)
        self.loading_dialog.show()

        # Start the exporting thread
        self.export_thread = ExportDataThread(self.db_file, self.excel_file, self.filter_query)
        self.export_thread.update_label.connect(self.loading_label.setText)
        self.export_thread.update_progress.connect(self.loading_bar.setValue)
        self.export_thread.finished.connect(self.on_export_finished)
        self.export_thread.start()

    def stop_exporting(self):
        # Stop the exporting thread
        self.export_thread.quit()

        # Check if the thread is still running and wait for it to finish
        if self.export_thread.isRunning():
            print("Export thread still running, waiting...")
            # TODO: remove terminate after changing way of export to line by line or something that can be stopped
            self.export_thread.terminate()
            self.export_thread.wait()
            print("Export thread closed successfully!")

        # Show a message box to inform the user that exporting has been cancelled
        QMessageBox.information(self, "Export canceled", f"Data exporting has been canceled")

        self.loading_dialog.reject()
        self.close()

    def on_export_finished(self):
        # Show a message box to inform the user that exporting is complete
        QMessageBox.information(self, "Export successful", f"Data exported successfully to {self.excel_file}!")

        # Close the loading dialog
        self.loading_dialog.accept()

        # Re-enable the export button
        self.export_button.setEnabled(True)

        # Close the exporting dialog
        self.accept()


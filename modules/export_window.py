from PyQt5.QtCore import QThread, pyqtSignal, Qt, QDate
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
from PyQt5.QtGui import QMovie
from PyQt5.QtCore import QTemporaryFile, QSize
from modules import base64_encoded_files


class ExportDataThread(QThread):
    update_label = pyqtSignal(str)
    update_progress = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, db_file, excel_file, filter_query=None):
        super().__init__()
        self.db_file = db_file
        self.excel_file = excel_file
        self.filter_query = filter_query

    def run(self):
        # Connect to the SQLite database
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()

            # Retrieve the table names from the database
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()

            # Calculate the total number of tables for progress tracking
            total_tables = len(tables)
            current_table = 0

            # Create an Excel writer using xlsxwriter engine
            excel_writer = pd.ExcelWriter(self.excel_file, engine='xlsxwriter')

            if self.filter_query:
                self.export_filtered_data(cursor, excel_writer)
            else:
                self.export_all_tables(cursor, tables, excel_writer, total_tables, current_table)

            excel_writer.close()
            self.update_label.emit("Export completed successfully.")

        self.finished.emit()

    def export_filtered_data(self, cursor, excel_writer):
        export_query = self.filter_query
        cursor.execute(export_query)
        data = cursor.fetchall()
        column_names = [desc[0] for desc in cursor.description]

        # Write the data to the Excel file
        self.write_data_to_excel(data, column_names, "MEASUREMENTS", excel_writer)

    def export_all_tables(self, cursor, tables, excel_writer, total_tables, current_table):
        # Export each table to the Excel file
        for table in tables:
            table_name = table[0]

            # Construct the export query
            export_query = f"SELECT * FROM {table_name}"

            # Execute the export query and fetch the data
            cursor.execute(export_query)
            data = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description]

            # Write the data to the Excel file
            self.write_data_to_excel(data, column_names, table_name, excel_writer)

            # Update the progress
            current_table += 1
            progress = int((current_table / total_tables) * 100)
            self.update_progress.emit(progress)

    def write_data_to_excel(self, data, column_names, table_name, excel_writer):
        # Convert the data to a DataFrame
        df = pd.DataFrame(data, columns=column_names)

        # Write the DataFrame to the Excel file
        df.to_excel(excel_writer, sheet_name=table_name, index=False)
        worksheet = excel_writer.sheets[table_name]

        # Adjust the column widths based on the data
        for i, column in enumerate(df.columns):
            column_width = self.calculate_column_width(df[column])
            worksheet.set_column(i, i, column_width)

    def calculate_column_width(self, data):
        if data.empty:
            return 10  # Return a default width if the data is empty

        # Convert series to a list and calculate the column width based on the maximum length of the data in the column
        column_width = max(len(str(value)) for value in data.tolist()) + 2
        return max(column_width, 10)


class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.setWindowIcon(parent.windowIcon())
        self.setGeometry(100, 100, 300, 150)

        self.db_file = ""
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
        self.filter_button.setDisabled(True)
        self.filter_button.clicked.connect(self.open_filter_window)
        self.select_excel_label = QLabel("Select an excel file:")
        self.select_excel_button = QPushButton("Browse")
        self.select_excel_button.setDisabled(True)
        self.select_excel_button.clicked.connect(self.select_excel_file)
        self.export_button = QPushButton("Export")
        self.export_button.setDisabled(True)
        self.export_button.clicked.connect(self.show_loading_screen)

    def init_layout(self):
        """Initialize the layout"""
        self.layout = QGridLayout()
        self.layout.addWidget(self.select_db_label, 0, 0)
        self.layout.addWidget(self.select_db_button, 0, 1)
        self.layout.addWidget(self.filter_button, 2, 0, 1, 2)
        self.layout.addWidget(self.select_excel_label, 1, 0)
        self.layout.addWidget(self.select_excel_button, 1, 1)
        self.layout.addWidget(self.export_button, 3, 0, 1, 2)
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
            self.select_excel_button.setEnabled(True)
            self.filter_button.setEnabled(True)

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
        self.date_from_calendar.setFixedSize(200, 30)

        date_to_label = QLabel("MEASUREMENT DATE TO:")
        self.date_to_calendar = QDateEdit(calendarPopup=True)
        self.date_to_calendar.setCalendarPopup(True)
        self.date_to_calendar.setDate(QDate.currentDate())
        self.date_to_calendar.setFixedSize(200, 30)

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
        select_beginning_button = QPushButton("Select Beginning of Time")
        select_beginning_button.clicked.connect(self.select_beginning_of_time)

        # Create a grid layout for the filter window
        layout = QGridLayout(self.filter_window)

        # Add labels, list widgets, and search inputs to the grid layout
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
        filename, _ = QFileDialog.getSaveFileName(self, "Select an Excel file", f"{default_name}",
                                                "Excel workbook (*.xlsx);;All files (*)", options=options)
        if filename:
            if not filename.endswith(".xlsx"):
                filename += ".xlsx"
            print(f"{filename=}")
            self.excel_file = filename
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


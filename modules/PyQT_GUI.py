from PyQt5.QtWidgets import  QMainWindow, QFileDialog, QVBoxLayout
from PyQt5.QtWidgets import QPushButton, QWidget, QLabel, QGridLayout
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from PyQt5.QtWidgets import QProgressBar
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtCore import QTemporaryFile, pyqtSlot
from PyQt5.QtGui import QMovie
import sqlite3
import pandas as pd
import xlsxwriter
from modules import base64_encoded_files, reports_parser
from pathlib import Path
import base64
import time

VERSION_DATE = "230513.1930"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Initialize the main window and layout
        self.setWindowTitle(f"Metroliza [{VERSION_DATE}]")
        self.setGeometry(100, 100, 300, 150)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QGridLayout()
        self.central_widget.setLayout(self.layout)
        
        self.parsing_dialog = None
        self.export_dialog = None

        # Initialize the buttons
        self.parse_button = QPushButton("Launch Parsing")
        self.export_button = QPushButton("Launch Export")

        # Add the buttons to the layout
        self.layout.addWidget(self.parse_button, 0, 0)
        self.layout.addWidget(self.export_button, 1, 0)

        # Connect the buttons to their respective dialogs
        self.parse_button.clicked.connect(self.launch_parsing_dialog)
        self.export_button.clicked.connect(self.launch_export_dialog)

    def launch_parsing_dialog(self):
        # Check if parsing dialog is already open or visible
        if not self.parsing_dialog or not self.parsing_dialog.isVisible():
            # Create a new parsing dialog if not already existing or visible
            self.parsing_dialog = ParsingDialog(self)
            self.parsing_dialog.show()

        # Raise the parsing dialog to the top and activate it
        self.parsing_dialog.raise_()
        self.parsing_dialog.activateWindow()

    def launch_export_dialog(self):
        # Check if export dialog is already open or visible
        if not self.export_dialog or not self.export_dialog.isVisible():
            # Create a new export dialog if not already existing or visible
            self.export_dialog = ExportDialog(self)
            self.export_dialog.show()

        # Raise the export dialog to the top and activate it
        self.export_dialog.raise_()
        self.export_dialog.activateWindow()


class ParseReportsThread(QThread):
    update_progress = pyqtSignal(int)
    update_label = pyqtSignal(str)
    parsing_finished = pyqtSignal()

    def __init__(self, directory, db_file):
        super().__init__()

        # Initialize the thread with the provided directory and database file
        self.directory = directory
        self.db_file = db_file
        self.parsing_canceled = False

    def get_list_of_reports(self):
        pdf_files = []
        for path in Path(self.directory).glob("**/*.[Pp][Dd][Ff]"):
            if path.is_file() and path.stat().st_size:
                pdf_files.append(path)
        return pdf_files

    def get_list_of_reports_in_database(self):
        # Create an empty list to store the reports
        list_of_reports_in_database = []

        # Connect to the SQLite database
        with sqlite3.connect(self.db_file) as conn:
            # Create a cursor object
            with conn:
                # Retry mechanism for handling database lock
                max_retry_attempts = 5
                retry_delay = 1  # seconds
                retry_attempt = 1
                while retry_attempt <= max_retry_attempts:
                    try:
                        cursor = conn.cursor()

                        # Check if 'REPORTS' table exists
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='REPORTS'")
                        result = cursor.fetchone()

                        if result:
                            # 'REPORTS' table exists, fetch the list of filenames
                            cursor.execute("SELECT FILENAME FROM REPORTS")
                            rows = cursor.fetchall()

                            for row in rows:
                                # Extract report filename
                                filename = row[0]

                                # Append the filename to the list
                                list_of_reports_in_database.append(filename)

                            # Return the list of reports in the database
                            return list_of_reports_in_database

                    except sqlite3.OperationalError as e:
                        error_message = str(e)
                        if 'database is locked' in error_message:
                            print(f"Database is locked. Retrying attempt {retry_attempt}...")
                            retry_attempt += 1
                            time.sleep(retry_delay)
                        else:
                            print(f"Error occurred: {error_message}.")  # Handle other database errors

        # Return the list of reports in the database
        return list_of_reports_in_database

    def stop_parsing(self):
        # Set the flag to indicate parsing cancellation
        self.parsing_canceled = True

    def run(self):
        # Get the list of reports from the provided directory
        list_of_reports = self.get_list_of_reports()
        list_of_parsed_reports = self.get_list_of_reports_in_database()
        total_files = len(list_of_reports)
        parsed_files = 0

        # Loop through each report and parse it
        for report in list_of_reports:
            if self.parsing_canceled:
                break

            if report.name not in list_of_parsed_reports:
                reports_parser.CMMReport(report, self.db_file)
            parsed_files += 1

            # Calculate the percentage of parsed files and emit the progress signal
            percentage = int(parsed_files / total_files * 100)
            self.update_progress.emit(percentage)

            # Update the label with the current parsing status
            self.update_label.emit(f"Parsing file {parsed_files} of {total_files}")

        # Emit the signal indicating that parsing has finished
        self.parsing_finished.emit()


class ParsingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Set the window title and geometry
        self.setWindowTitle("Parsing")
        self.setGeometry(100, 100, 300, 150)
        
        # Initialize variables
        self.directory = ""
        self.db_file = ""
        
        # Initialize the widgets
        self.directory_label = QLabel("Select a directory:")
        self.directory_button = QPushButton("Browse")
        self.directory_button.clicked.connect(self.select_directory)
        self.database_label = QLabel("Select a database file:")
        self.database_button = QPushButton("Browse")
        self.database_button.setDisabled(True)
        self.database_button.clicked.connect(self.select_database)
        self.parse_button = QPushButton("Parse reports")
        self.parse_button.setDisabled(True)
        self.parse_button.clicked.connect(self.show_loading_screen)
        
        # Initialize thread and flag
        self.parse_thread = None
        self.parsing_canceled = False

        # Initialize the layout
        self.layout = QGridLayout()
        self.layout.addWidget(self.directory_label, 0, 0)
        self.layout.addWidget(self.directory_button, 0, 1)
        self.layout.addWidget(self.database_label, 1, 0)
        self.layout.addWidget(self.database_button, 1, 1)
        self.layout.addWidget(self.parse_button, 2, 0, 1, 2)
        self.setLayout(self.layout)

    @pyqtSlot()
    def select_directory(self):
        # Open a dialog to select a directory
        directory = QFileDialog.getExistingDirectory(self, "Select directory")
        if directory:
            print(f"{directory=}")
            self.directory = directory
            self.database_button.setEnabled(True)

    @pyqtSlot()
    def select_database(self):
        # Open a dialog to select a database file
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        default_name = [part for part in self.directory.split("/") if part][-1]
        filename, _ = QFileDialog.getSaveFileName(self, "Select database", f"{default_name}",
                                                  "SQLite3 database (*.db);;All Files (*)", options=options)
        if filename:
            if not filename.endswith(".db"):
                filename += ".db"
            print(f"{filename=}")
            self.db_file = filename
            self.parse_button.setEnabled(True)

    @pyqtSlot()
    def show_loading_screen(self):
        # Create the progress dialog
        self.loading_dialog = QDialog(self, Qt.WindowTitleHint)
        self.loading_dialog.setWindowTitle("Parsing reports...")
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
        self.loading_gif = QMovie(temp_file_name)  # Save as an instance variable
        self.loading_gif.setScaledSize(QSize(200, 200))
        loading_gif_label.setMovie(self.loading_gif)
        self.loading_gif.start()

        # Create the loading label and progress bar
        self.loading_label = QLabel("Parsing files...", self.loading_dialog)
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
        cancel_button.clicked.connect(self.stop_parsing)
        layout.addWidget(cancel_button, alignment=Qt.AlignHCenter)

        # Disable the parse button and show the progress dialog
        self.parse_button.setDisabled(True)
        self.loading_dialog.show()
        
        # Start the parsing thread
        self.parse_thread = ParseReportsThread(self.directory, self.db_file)
        self.parse_thread.update_label.connect(self.loading_label.setText)
        self.parse_thread.update_progress.connect(self.loading_bar.setValue)
        self.parse_thread.finished.connect(self.on_parse_finished)
        self.parse_thread.start()

    @pyqtSlot()
    def stop_parsing(self):
        # Stop the parsing thread
        self.parsing_canceled = True
        self.parse_thread.stop_parsing()
        self.parse_thread.quit()
        
        # Check if the thread is still running and wait for it to finish
        if self.parse_thread.isRunning():
            print("Parsing thread still running, waiting...")
            self.parse_thread.wait()
            print("Parsing thread closed successfully!")
        
        # Close the loading dialog
        self.loading_dialog.reject()
        
        # Close the main dialog
        self.close()
        
    @pyqtSlot()
    def on_parse_finished(self):
        if self.parsing_canceled:
            # Show a message box to inform the user that parsing has been canceled
            QMessageBox.information(self, "Parsing canceled", "Parsing has been canceled")
        else:
            # Show a message box to inform the user that parsing is complete
            QMessageBox.information(self, "Parsing successful", f"Measurements data saved to {self.db_file}!")
        
        # Close the loading dialog
        self.loading_dialog.accept()
        
        # Re-enable the parse button
        self.parse_button.setEnabled(True)
        
        # Reset the parsing canceled flag
        self.parsing_canceled = False
        
        # Close the parsing dialog
        self.accept()


class ExportDataThread(QThread):
    update_label = pyqtSignal(str)
    update_progress = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, db_file, excel_file):
        super().__init__()
        self.db_file = db_file
        self.excel_file = excel_file

    def run(self):
        try:
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

                # Export each table in a separate sheet
                for table in tables:
                    table_name = table[0]
                    cursor.execute(f'SELECT * FROM "{table_name}";')
                    data = cursor.fetchall()
                    column_names = [desc[0] for desc in cursor.description]
                    df = pd.DataFrame(data, columns=column_names)

                    # Sanitize the table name to avoid invalid characters in the sheet name
                    table_name_sanitized = ''.join([c if c.isalnum() or c.isspace() else '' for c in table_name])
                    table_name_sanitized = table_name_sanitized[:30]  # Limit the sheet name to 30 characters
                    if not table_name_sanitized:
                        table_name_sanitized = 'Sheet'

                    # Write the DataFrame to the Excel sheet
                    df.to_excel(excel_writer, sheet_name=table_name_sanitized, index=False)
                    worksheet = excel_writer.sheets[table_name_sanitized]

                    # Adjust the column widths based on the data
                    for i, column in enumerate(df.columns):
                        column_width = self.calculate_column_width(df[column])
                        worksheet.set_column(i, i, column_width)

                    current_table += 1
                    progress = int((current_table / total_tables) * 100)
                    self.update_progress.emit(progress)
                    self.update_label.emit(f"Exporting table {current_table}/{total_tables}")

                excel_writer.close()
                cursor.close()

            self.finished.emit()

        except Exception as e:
            self.update_label.emit(f"Export error: {str(e)}")
            self.finished.emit()

    def calculate_column_width(self, data):
        # Calculate the column width based on the maximum length of the data in the column
        column_width = max(len(str(value)) for value in data) + 2
        return max(column_width, 10)


class ExportDialog(QDialog):
    def __init__(self, db_file, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export data")
        self.setGeometry(100, 100, 300, 150)

        self.db_file = db_file
        self.excel_file = ""

        self.init_widgets()
        self.init_layout()

    def init_widgets(self):
        """Initialize the widgets"""
        self.select_db_label = QLabel("Select a database file:")
        self.select_db_button = QPushButton("Browse")
        self.select_db_button.clicked.connect(self.select_db_file)
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
        self.layout.addWidget(self.select_excel_label, 1, 0)
        self.layout.addWidget(self.select_excel_button, 1, 1)
        self.layout.addWidget(self.export_button, 2, 0, 1, 2)
        self.setLayout(self.layout)

    def select_db_file(self):
        """Open a file dialog to select a database file"""
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        filename, _ = QFileDialog.getOpenFileName(self, "Select database", "",
                                                  "SQLite database (*.db);;All Files (*)", options=options)
        if filename:
            if not filename.endswith(".db"):
                filename += ".db"
            print(f"{filename=}")
            self.db_file = filename
            self.select_excel_button.setEnabled(True)

    def select_excel_file(self):
        """Open a file dialog to select an excel file"""
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        filename, _ = QFileDialog.getSaveFileName(self, "Select Excel File", f"{self.db_file[:-3]}",
                                                  "Excel workbook (*.xlsx);;All Files (*)", options=options)
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
        self.loading_gif = QMovie(temp_file_name)  # Save as an instance variable
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
        self.export_thread = ExportDataThread(self.db_file, self.excel_file)
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
            self.export_thread.wait()
            print("Export thread closed successfully!")
        
        # self.export_thread.terminate()
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
        

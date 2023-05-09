from PyQt5.QtWidgets import  QMainWindow, QFileDialog, QVBoxLayout
from PyQt5.QtWidgets import QPushButton, QWidget, QLabel, QGridLayout
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from PyQt5.QtWidgets import QProgressBar
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QMovie
import sqlite3
import pandas as pd
import xlsxwriter
from modules import reports_parser
from pathlib import Path


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Initialize the main window and layout
        self.setWindowTitle("Metroliza")
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
        if not self.parsing_dialog or not self.parsing_dialog.isVisible():
            self.parsing_dialog = ParsingDialog(self)
            self.parsing_dialog.show()
        self.parsing_dialog.raise_()
        self.parsing_dialog.activateWindow()

    def launch_export_dialog(self):
        if not self.export_dialog or not self.export_dialog.isVisible():
            self.export_dialog = ExportDialog(self)
            self.export_dialog.show()
        self.export_dialog.raise_()
        self.export_dialog.activateWindow()


class ParseReportsThread(QThread):
    update_progress = pyqtSignal(int)
    update_label = pyqtSignal(str)
    parsing_finished = pyqtSignal()

    def __init__(self, directory, db_file):
        super().__init__()
        self.directory = directory
        self.db_file = db_file

    def run(self):
        list_of_reports = get_list_of_reports(Path(self.directory))
        total_files = len(list_of_reports)
        parsed_files = 0
        for report in list_of_reports:
            reports_parser.CMMReport(report, self.db_file)
            parsed_files += 1
            percentage = int(parsed_files / total_files * 100)
            self.update_progress.emit(percentage)
            self.update_label.emit(f"Parsing file {parsed_files} of {total_files}")
        self.parsing_finished.emit()


class ParsingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Parsing")
        self.setGeometry(100, 100, 300, 150)
        
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
        self.parse_button = QPushButton("Parse Reports")
        self.parse_button.setDisabled(True)
        self.parse_button.clicked.connect(self.show_loading_screen)
        
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

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select directory")
        if directory:
            print(f"{directory=}")
            self.directory = directory
            self.database_button.setEnabled(True)

    def select_database(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        filename, _ = QFileDialog.getSaveFileName(self, "Select database", "",
                                                  "SQLite3 Database (*.db);;All Files (*)", options=options)
        if filename:
            if not filename.endswith(".db"):
                filename += ".db"
            print(f"{filename=}")
            self.db_file = filename
            self.parse_button.setEnabled(True)

    def show_loading_screen(self):
        # Create the progress dialog
        self.loading_dialog = QDialog(self, Qt.WindowTitleHint)
        self.loading_dialog.setWindowTitle("Parsing Reports...")
        self.loading_dialog.setWindowModality(Qt.ApplicationModal)
        self.loading_dialog.setFixedSize(400, 300)

        # Create a QLabel to display the loading GIF
        loading_gif_label = QLabel(self.loading_dialog)
        loading_gif_label.setFixedSize(200, 200)
        loading_gif_label.setAlignment(Qt.AlignCenter)

        # Load the loading.gif from a file, create a QMovie from it, and set it to the label
        loading_gif = QMovie("./modules/loading.gif")
        loading_gif.setScaledSize(QSize(200, 200))
        loading_gif_label.setMovie(loading_gif)
        loading_gif.start()

        # Create the loading label and progress bar
        self.loading_label = QLabel("Parsing files...", self.loading_dialog)
        self.loading_label.setAlignment(Qt.AlignCenter)  # align the loading label to center

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

    def stop_parsing(self):
        # Stop the parsing thread
        self.parsing_canceled = True
        self.parse_thread.terminate()
        self.loading_dialog.reject()
        
    def on_parse_finished(self):
        if self.parsing_canceled:
            # Show a message box to inform the user that parsing has been canceled
            QMessageBox.information(self, "Parsing Canceled", "Parsing has been canceled.")
        else:
            # Show a message box to inform the user that parsing is complete
            QMessageBox.information(self, "Parsing Successful", f"Measurements data saved to {self.db_file}!")
        
        # Close the loading dialog
        self.loading_dialog.accept()
        
        # Re-enable the parse button
        self.parse_button.setEnabled(True)
        
        # Reset the parsing canceled flag
        self.parsing_canceled = False


class ExportDialog(QDialog):
    def __init__(self, db_file, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Data")
        self.setGeometry(100, 100, 300, 150)

        self.db_file = db_file
        self.excel_file = ""

        self.select_db_btn = QPushButton("Select Database")
        self.select_db_btn.clicked.connect(self.select_db_file)

        self.select_excel_btn = QPushButton("Select Excel File")
        self.select_excel_btn.clicked.connect(self.select_excel_file)

        self.export_btn = QPushButton("Export Data")
        self.export_btn.clicked.connect(self.export_data)
        self.export_btn.setEnabled(False)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)

        vbox = QVBoxLayout()
        vbox.addWidget(self.select_db_btn)
        vbox.addWidget(self.select_excel_btn)
        vbox.addWidget(self.export_btn)
        vbox.addWidget(self.cancel_btn)

        self.setLayout(vbox)

    def select_db_file(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        filename, _ = QFileDialog.getOpenFileName(self, "Select Database", "",
                                                  "SQLite Database (*.db);;All Files (*)", options=options)
        if filename:
            if not filename.endswith(".db"):
                filename += ".db"
            print(f"{filename=}")
            self.db_file = filename

    def select_excel_file(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        filename, _ = QFileDialog.getSaveFileName(self, "Select Excel File", "",
                                                  "Excel Workbook (*.xlsx);;All Files (*)", options=options)
        if filename:
            if not filename.endswith(".xlsx"):
                filename += ".xlsx"
            print(f"{filename=}")
            self.excel_file = filename
            self.export_btn.setEnabled(True)

    def export_data(self):
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()

            excel_writer = pd.ExcelWriter(self.excel_file, engine='xlsxwriter')

            for table in tables:
                table_name = table[0]
                cursor.execute(f'SELECT * FROM "{table_name}";')
                data = cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]
                df = pd.DataFrame(data, columns=column_names)
                table_name_sanitized = ''.join([c if c.isalnum() or c.isspace() else '' for c in table_name])
                table_name_sanitized = table_name_sanitized[:30]
                if not table_name_sanitized:
                    table_name_sanitized = 'Sheet'
                df.to_excel(excel_writer, sheet_name=table_name_sanitized, index=False)
                worksheet = excel_writer.sheets[table_name_sanitized]
                worksheet.set_column(len(df.columns), len(df.columns) + len(df.columns), None)

            excel_writer.close()

            cursor.close()
            conn.close()
            
            QMessageBox.information(self, "Export Successful", "Data exported successfully to Excel!")
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"An error occurred while exporting data:\n\n{str(e)}")
            self.reject()


def get_list_of_reports(directory: Path):
    """Function to return list (str) of pdf files in given path

    Returns:
        (str) list: list of strings with pdf files paths
    """
    pdf_files = []
    for path in directory.glob("**/*.[Pp][Dd][Ff]"):
        if path.is_file() and path.stat().st_size:
            pdf_files.append(path)
    return pdf_files
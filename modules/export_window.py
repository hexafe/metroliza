from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QGridLayout,
    QFileDialog,
    QProgressBar,
    QVBoxLayout,
    QMessageBox,
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.setWindowIcon(parent.windowIcon())
        self.setGeometry(100, 100, 300, 150)

        self.db_file = ""
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
        default_name = [part for part in self.db_file.split("/") if part][-1][:-3]
        if not default_name.endswith(".xlsx"):
                default_name += ".xlsx"
        filename, _ = QFileDialog.getSaveFileName(self, "Select Excel File", f"{default_name}",
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
            #TODO: remove terminate after changing way of export to line by line or something that can be stopped
            self.export_thread.terminate()
            self.export_thread.wait()
            print("Export thread closed successfully!")
        
        # Show a message box to inform the user that exporting has been cancelled
        QMessageBox.information(self, "Export canceled", f"Data exporting has been canceled")
        
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

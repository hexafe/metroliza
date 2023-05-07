import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog
from PyQt5.QtWidgets import QPushButton, QWidget, QLabel, QGridLayout
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QLineEdit
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from PyQt5.QtCore import Qt
import sqlite3
import pandas as pd
import xlsxwriter


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
        # Create the parsing dialog
        parsing_dialog = ParsingDialog(self)
        parsing_dialog.exec_()

    def launch_export_dialog(self):
        # Create the export dialog
        export_dialog = ExportDialog(self)
        export_dialog.exec_()

class ParsingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Parsing")
        self.setGeometry(100, 100, 300, 150)

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
        self.parse_button.clicked.connect(self.parse_reports)

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
            print(f"{filename=}")
            self.filename = filename
            self.parse_button.setEnabled(True)

    def parse_reports(self):
        # TODO: Parse the reports and save the data to the selected database
        print("Parsing reports")
        self.accept()

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
            self.db_file = filename

    def select_excel_file(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        filename, _ = QFileDialog.getSaveFileName(self, "Select Excel File", "",
                                                  "Excel Workbook (*.xlsx);;All Files (*)", options=options)
        if filename:
            if not filename.endswith(".xlsx"):
                filename += ".xlsx"
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
                
            excel_writer.save()
            excel_writer.close()
            cursor.close()
            conn.close()
            QMessageBox.information(self, "Export Successful", "Data exported successfully to Excel!")
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"An error occurred while exporting data:\n\n{str(e)}")
            self.reject()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_window = MainWindow()
    
    # Create instances of ExportDialog and ParsingDialog
    export_dialog = ExportDialog(main_window)
    parsing_dialog = ParsingDialog(main_window)

    # Connect buttons in main window to corresponding dialogs
    main_window.parse_button.clicked.connect(parsing_dialog.show)
    main_window.export_button.clicked.connect(export_dialog.show)

    main_window.show()
    sys.exit(app.exec_())
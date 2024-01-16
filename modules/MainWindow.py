import base64
import logging
from modules import base64_encoded_files
from modules.ExportDialog import ExportDialog
from modules.ParsingDialog import ParsingDialog
from modules.ModifyDB import ModifyDB
from modules.AboutWindow import AboutWindow
from modules.CSVSummaryDialog import CSVSummaryDialog
from modules.ReleaseNotesDialog import ReleaseNotesDialog
from modules.CustomLogger import CustomLogger
from version_date import release_notes
from PyQt5.QtCore import QByteArray
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QGridLayout,
    QMainWindow,
    QPushButton,
    QWidget,
    QAction,
)


class MainWindow(QMainWindow):
    def __init__(self, VERSION_DATE):
        super().__init__()

        # Initialize the main window and layout
        self.setWindowTitle(f"Metroliza [{VERSION_DATE}]")
        self.setGeometry(100, 100, 300, 150)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QGridLayout()
        self.central_widget.setLayout(self.layout)

        # Set the window icon
        icon_decoded = base64.b64decode(base64_encoded_files.encoded_icon)
        byte_array = QByteArray(icon_decoded)
        pixmap = QPixmap()
        pixmap.loadFromData(byte_array)
        icon = QIcon(pixmap)
        self.setWindowIcon(icon)

        self.parsing_dialog = None
        self.modifydb_dialog = None
        self.export_dialog = None
        self.directory = None
        self.db_file = None

        # Initialize and set up buttons with tooltips
        self.parse_button = QPushButton("Launch Parsing")
        self.modifydb_button = QPushButton("Launch Modify Database")
        self.export_button = QPushButton("Launch Export")
        self.csv_summary_button = QPushButton("CSV Summary")
        self.setup_button_tooltips()

        # Set up menu items
        self.setup_menu_actions()

        # Add buttons to the layout and connect signals
        self.setup_buttons_layout()

    def setup_button_tooltips(self):
        self.parse_button.setToolTip("Use Parsing module to get data from PDF reports into database for further export to Excel")
        self.modifydb_button.setToolTip("Use Modify Database module to modify Reference, Part number or Header in database")
        self.export_button.setToolTip("Use Export module to filter, set and export data from database to Excel file")
        self.csv_summary_button.setToolTip("Use CSV module to automatically create charts from CSV data")

    def setup_menu_actions(self):
        self.about_button = QAction("About", self)
        self.about_button.triggered.connect(self.open_about_window)
        self.release_notes_action = QAction("Release notes", self)
        self.release_notes_action.triggered.connect(self.open_release_notes_dialog)
        self.menuBar().addAction(self.about_button)
        self.menuBar().addAction(self.release_notes_action)

    def setup_buttons_layout(self):
        self.layout.addWidget(self.parse_button, 0, 0)
        self.layout.addWidget(self.modifydb_button, 1, 0)
        self.layout.addWidget(self.export_button, 2, 0)
        self.layout.addWidget(self.csv_summary_button, 3, 0)
        self.parse_button.clicked.connect(self.launch_parsing_dialog)
        self.modifydb_button.clicked.connect(self.launch_modifydb_dialog)
        self.export_button.clicked.connect(self.launch_export_dialog)
        self.csv_summary_button.clicked.connect(self.launch_csv_summary_dialog)

    def launch_parsing_dialog(self):
        try:
            if self.export_dialog and self.export_dialog.isVisible():
                self.export_dialog.close()
                
            if self.modifydb_dialog and self.modifydb_dialog.isVisible():
                self.modifydb_dialog.close()

            if not self.parsing_dialog or not self.parsing_dialog.isVisible():
                self.parsing_dialog = ParsingDialog(self, self.directory, self.db_file)
                self.parsing_dialog.show()

            self.parsing_dialog.raise_()
            self.parsing_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)
            
    def launch_modifydb_dialog(self):
        try:
            if self.export_dialog and self.export_dialog.isVisible():
                self.export_dialog.close()
                
            if self.parsing_dialog and self.parsing_dialog.isVisible():
                self.parsing_dialog.close()

            if not self.modifydb_dialog or not self.modifydb_dialog.isVisible():
                self.modifydb_dialog = ModifyDB(self, self.db_file)
                self.modifydb_dialog.show()

            self.modifydb_dialog.raise_()
            self.modifydb_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)

    def launch_export_dialog(self):
        try:
            if self.parsing_dialog and self.parsing_dialog.isVisible():
                self.parsing_dialog.close()
                
            if self.modifydb_dialog and self.modifydb_dialog.isVisible():
                self.modifydb_dialog.close()

            if not self.export_dialog or not self.export_dialog.isVisible():
                self.export_dialog = ExportDialog(self, self.db_file)
                self.export_dialog.show()

            self.export_dialog.raise_()
            self.export_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)

    def open_about_window(self):
        try:
            about_window = AboutWindow(self)
            about_window.exec_()
        except Exception as e:
            self.log_and_exit(e)

    def open_release_notes_dialog(self):
        try:
            release_notes_dialog = ReleaseNotesDialog(self, release_notes)
            release_notes_dialog.exec_()
        except Exception as e:
            self.log_and_exit(e)

    def launch_csv_summary_dialog(self):
        try:
            csv_summary_window = CSVSummaryDialog(self)
            csv_summary_window.exec_()
        except Exception as e:
            self.log_and_exit(e)

    def set_db_file(self, db_file):
        try:
            self.db_file = db_file
        except Exception as e:
            self.log_and_exit(e)

    def set_directory(self, directory):
        try:
            self.directory = directory
        except Exception as e:
            self.log_and_exit(e)

    def log_and_exit(self, exception):
        CustomLogger(exception)

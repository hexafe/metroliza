from modules import base64_encoded_files
from modules.ExportDialog import ExportDialog
from modules.ParsingDialog import ParsingDialog
from modules.AboutWindow import AboutWindow
from modules.CSVSummaryDialog import CSVSummaryDialog
from modules.ReleaseNotesDialog import ReleaseNotesDialog
from version_date import release_notes
from PyQt5.QtCore import QByteArray
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QGridLayout,
    QMainWindow,
    QPushButton,
    QWidget,
    QAction,
    QMessageBox,
)
import base64
import logging


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

        # Set the icon
        icon_decoded = base64.b64decode(base64_encoded_files.encoded_icon)
        byte_array = QByteArray(icon_decoded)
        pixmap = QPixmap()
        pixmap.loadFromData(byte_array)
        icon = QIcon(pixmap)
        self.setWindowIcon(icon)

        self.parsing_dialog = None
        self.export_dialog = None

        self.directory = None
        self.db_file = None

        # Initialize the buttons
        self.parse_button = QPushButton("Launch Parsing")
        self.export_button = QPushButton("Launch Export")
        self.csv_summary_button = QPushButton("CSV Summary")

        # Add the About button in menu bar
        self.about_button = QAction("About", self)
        self.about_button.triggered.connect(self.open_about_window)
        self.menuBar().addAction(self.about_button)
        
        # Add the Release notes button in menu bar
        self.release_notes_action = QAction("Release notes", self)
        self.release_notes_action.triggered.connect(self.open_release_notes_dialog)
        self.menuBar().addAction(self.release_notes_action)

        # Add the buttons to the layout
        self.layout.addWidget(self.parse_button, 0, 0)
        self.layout.addWidget(self.export_button, 1, 0)
        self.layout.addWidget(self.csv_summary_button, 2, 0)

        # Connect the buttons to their respective dialogs
        self.parse_button.clicked.connect(self.launch_parsing_dialog)
        self.export_button.clicked.connect(self.launch_export_dialog)
        self.csv_summary_button.clicked.connect(self.launch_csv_summary_dialog)

    def launch_parsing_dialog(self):
        try:
            # Check if export dialog is already open or visible
            if self.export_dialog and self.export_dialog.isVisible():
                self.export_dialog.close()

            # Check if parsing dialog is already open or visible
            if not self.parsing_dialog or not self.parsing_dialog.isVisible():
                # Create a new parsing dialog if not already existing or visible
                self.parsing_dialog = ParsingDialog(self, self.directory, self.db_file)
                self.parsing_dialog.show()

            # Raise the parsing dialog to the top and activate it
            self.parsing_dialog.raise_()
            self.parsing_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)

    def launch_export_dialog(self):
        try:
            # Check if parsing dialog is already open or visible
            if self.parsing_dialog and self.parsing_dialog.isVisible():
                self.parsing_dialog.close()

            # Check if export dialog is already open or visible
            if not self.export_dialog or not self.export_dialog.isVisible():
                # Create a new export dialog if not already existing or visible
                self.export_dialog = ExportDialog(self, self.db_file)
                self.export_dialog.show()

            # Raise the export dialog to the top and activate it
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
            release_notes_dialog = ReleaseNotesDialog(release_notes)
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
        logging.exception("An error occured: %s", exception)
        QMessageBox.information(None, "Error", "An error occured.\nPlease check log file for more informations.\n(or just contact the author :P)")
        raise

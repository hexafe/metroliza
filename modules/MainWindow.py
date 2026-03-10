import base64
from modules import Base64EncodedFiles
from modules.export_dialog import ExportDialog
from modules.parsing_dialog import ParsingDialog
from modules.modify_db import ModifyDB
from modules.about_window import AboutWindow
from modules.release_notes_dialog import ReleaseNotesDialog
from modules.custom_logger import CustomLogger
from modules.csv_summary_dialog import CSVSummaryDialog
from modules.characteristic_mapping_dialog import CharacteristicMappingDialog
from VersionDate import release_notes
from PyQt6.QtCore import QByteArray
from PyQt6.QtGui import QIcon, QPixmap, QAction
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from modules import ui_theme_tokens


class MainWindow(QMainWindow):
    """A main window class that provides the user interface for the Metroliza application."""

    def __init__(self, version_label, days_until_expiration):
        """Initialize the main window and its components.

        Args:
            VERSION_DATE (str): The version and date of the application.
        """
        super().__init__()

        # Initialize the main window and layout
        if days_until_expiration is None:
            self.setWindowTitle(f"Metroliza [{version_label}]")
        else:
            self.setWindowTitle(f"Metroliza [{version_label}] ({days_until_expiration+1} day{'s' if days_until_expiration+1 > 1 else ''} left)")
        self.setGeometry(100, 100, 300, 150)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QGridLayout()
        self.central_widget.setLayout(self.layout)
        self.days_until_expiration = days_until_expiration

        # Set the window icon
        self.setWindowIcon(self.decode_icon(Base64EncodedFiles.encoded_icon))

        # Initialize the dialogs and attributes
        self.parsing_dialog = None
        self.modifydb_dialog = None
        self.export_dialog = None
        self.directory = None
        self.db_file = None

        # Initialize and set up buttons with tooltips
        self.parse_button = QPushButton("Ingest Reports")
        self.modifydb_button = QPushButton("Manage Database Records")
        self.export_button = QPushButton("Export to Excel")
        self.csv_summary_button = QPushButton("Build CSV Summary Charts")
        self.map_characteristics_button = QPushButton("Map Characteristic Names")

        self.heading_label = QLabel("Process reports from intake to export")
        self.subheading_label = QLabel("Start by ingesting PDF reports, then manage data and export results.")
        self.status_label = QLabel()
        self.readiness_label = QLabel()
        self.setup_button_tooltips()

        # Set up menu items
        self.setup_menu_actions()

        # Add buttons to the layout and connect signals
        self.setup_buttons_layout()

    def decode_icon(self, encoded_icon):
        """Decode the base64 encoded icon and return an QIcon object.

        Args:
            encoded_icon (str): The base64 encoded icon.

        Returns:
            QIcon: The decoded icon.
        """
        icon_decoded = base64.b64decode(encoded_icon)
        byte_array = QByteArray(icon_decoded)
        pixmap = QPixmap()
        pixmap.loadFromData(byte_array)
        icon = QIcon(pixmap)
        return icon

    def setup_button_tooltips(self):
        """Set up the tooltips for the buttons."""
        self.parse_button.setToolTip("Import PDF reports into the working database.")
        self.modifydb_button.setToolTip("Edit references, part numbers, and headers in the database.")
        self.export_button.setToolTip("Filter and export selected data from the database to Excel.")
        self.csv_summary_button.setToolTip("Generate summary charts from CSV input files.")
        self.map_characteristics_button.setToolTip("Define equivalent characteristic names used across sources.")

    def setup_menu_actions(self):
        """Set up the menu actions for the main window."""
        self.about_button = QAction("About", self)
        self.about_button.triggered.connect(self.open_about_window)
        self.release_notes_action = QAction("Release notes", self)
        self.release_notes_action.triggered.connect(self.open_release_notes_dialog)
        self.menuBar().addAction(self.about_button)
        self.menuBar().addAction(self.release_notes_action)

    def setup_buttons_layout(self):
        """Add the buttons to the layout and connect the signals."""
        main_container = QFrame()
        main_container_layout = QVBoxLayout(main_container)
        main_container_layout.setContentsMargins(12, 12, 12, 12)
        main_container_layout.setSpacing(10)

        self.heading_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.subheading_label.setWordWrap(True)
        self.subheading_label.setStyleSheet("color: #555;")
        main_container_layout.addWidget(self.heading_label)
        main_container_layout.addWidget(self.subheading_label)

        main_container_layout.addWidget(self._build_context_panel())
        main_container_layout.addWidget(self._build_action_group("Ingest", [self.parse_button], 0))
        main_container_layout.addWidget(self._build_action_group("Manage", [self.modifydb_button, self.map_characteristics_button], 1))
        main_container_layout.addWidget(self._build_action_group("Export", [self.export_button], 2))
        main_container_layout.addWidget(self._build_action_group("Tools", [self.csv_summary_button], 3))
        main_container_layout.addStretch()

        self.layout.addWidget(main_container, 0, 0)

        self.update_context_status()
        self.parse_button.clicked.connect(self.launch_parsing_dialog)
        self.modifydb_button.clicked.connect(self.launch_modifydb_dialog)
        self.export_button.clicked.connect(self.launch_export_dialog)
        self.csv_summary_button.clicked.connect(self.launch_csv_summary_dialog)
        self.map_characteristics_button.clicked.connect(self.launch_characteristic_mapping_dialog)

    def _build_context_panel(self):
        panel = QGroupBox("Context")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(4)
        self.status_label.setWordWrap(True)
        self.readiness_label.setWordWrap(True)
        self.readiness_label.setStyleSheet("color: #555;")
        panel_layout.addWidget(self.status_label)
        panel_layout.addWidget(self.readiness_label)
        return panel

    def _build_action_group(self, title, buttons, palette_index):
        color = ui_theme_tokens.BASE_GROUP_PALETTE[palette_index % len(ui_theme_tokens.BASE_GROUP_PALETTE)]
        group = QGroupBox(title)
        group.setStyleSheet(f"QGroupBox {{ background-color: {color}; border: 1px solid #D0D0D0; border-radius: 6px; margin-top: 8px; padding-top: 6px; }}")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(10, 10, 10, 10)
        group_layout.setSpacing(6)
        for button in buttons:
            group_layout.addWidget(button)
        return group

    def update_context_status(self):
        if self.db_file:
            self.status_label.setText(f"Database: {self.db_file}")
        else:
            self.status_label.setText("Database: Not selected yet")

        if self.db_file and self.directory:
            self.readiness_label.setText("Ready: ingest, manage, and export workflows are available.")
        elif self.db_file:
            self.readiness_label.setText("Hint: set a source directory before ingesting reports.")
        else:
            self.readiness_label.setText("Hint: choose or create a database in a workflow dialog to get started.")

    def launch_parsing_dialog(self):
        """Launch the parsing dialog and close the other dialogs if they are open."""
        try:
            if self.export_dialog and self.export_dialog.isVisible():
                self.export_dialog.close()
                
            if self.modifydb_dialog and self.modifydb_dialog.isVisible():
                self.modifydb_dialog.close()

            if not self.parsing_dialog or not self.parsing_dialog.isVisible():
                self.parsing_dialog = ParsingDialog(self, self.directory, self.db_file)
                self.parsing_dialog.show()
        except Exception as e:
            CustomLogger(e, reraise=False)
            
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
            about_window = AboutWindow(self, days_until_expiration=self.days_until_expiration)
            about_window.exec()
        except Exception as e:
            self.log_and_exit(e)

    def open_release_notes_dialog(self):
        try:
            release_notes_dialog = ReleaseNotesDialog(self, release_notes)
            release_notes_dialog.exec()
        except Exception as e:
            self.log_and_exit(e)

    def launch_csv_summary_dialog(self):
        try:
            csv_summary_window = CSVSummaryDialog(self)
            csv_summary_window.exec()
            pass
        except Exception as e:
            self.log_and_exit(e)

    def launch_characteristic_mapping_dialog(self):
        try:
            characteristic_mapping_dialog = CharacteristicMappingDialog(self, self.db_file)
            characteristic_mapping_dialog.exec()
        except Exception as e:
            self.log_and_exit(e)

    def set_db_file(self, db_file):
        try:
            self.db_file = db_file
            self.update_context_status()
        except Exception as e:
            self.log_and_exit(e)

    def set_directory(self, directory):
        try:
            self.directory = directory
            self.update_context_status()
        except Exception as e:
            self.log_and_exit(e)

    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)

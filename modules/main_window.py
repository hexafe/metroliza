import base64
from modules import base64_encoded_files
from modules.export_dialog import ExportDialog
from modules.parsing_dialog import ParsingDialog
from modules.metadata_enrichment_thread import MetadataEnrichmentThread
from modules.modify_db import ModifyDB
from modules.about_window import AboutWindow
from modules.release_notes_dialog import ReleaseNotesDialog
from modules.custom_logger import CustomLogger
from modules.csv_summary_dialog import CSVSummaryDialog
from modules.characteristic_mapping_dialog import CharacteristicMappingDialog
from modules.industrial_data_dialog import IndustrialDataDialog
from modules.help_menu import build_help_menu
from VersionDate import release_notes
from PyQt6.QtCore import QByteArray
from PyQt6.QtGui import QIcon, QPixmap, QAction
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from modules.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_window_size,
    section_label,
    secondary_label,
    separator,
    set_status_variant,
    status_chip,
)


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
        configure_window_size(self, minimum=(460, 360), initial=(560, 460))
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(16, 16, 16, 16)
        self.layout.setSpacing(10)
        self.central_widget.setLayout(self.layout)
        self.days_until_expiration = days_until_expiration

        # Set the window icon
        self.setWindowIcon(self.decode_icon(base64_encoded_files.encoded_icon))

        # Initialize the dialogs and attributes
        self.parsing_dialog = None
        self.modifydb_dialog = None
        self.export_dialog = None
        self.metadata_enrichment_thread = None
        self.metadata_enrichment_error_message = None
        self.industrial_data_dialog = None
        self.directory = None
        self.db_file = None

        # Initialize and set up command-center widgets
        self.workflow_label = section_label("Workflow")
        self.context_label = section_label("Current context")
        self.source_status_label = status_chip("Source: not selected", "neutral")
        self.database_status_label = status_chip("Database: not selected", "neutral")
        self.workflow_hint_label = secondary_label(
            "Parse reports, clean database values when needed, match names, then export the workbook."
        )
        self.parse_button = QPushButton("Parse Reports")
        self.modifydb_button = QPushButton("Modify Database")
        self.export_button = QPushButton("Export Workbook")
        self.map_characteristics_button = QPushButton("Match Characteristic Names")
        self.metadata_enrichment_status_label = status_chip("Metadata enrichment idle", "neutral")
        self.metadata_enrichment_progress_bar = QProgressBar()
        self.cancel_metadata_enrichment_button = QPushButton("Cancel")
        self.setup_button_tooltips()

        # Set up menu items
        self.setup_menu_actions()

        # Add buttons to the layout and connect signals
        self.setup_buttons_layout()
        self._sync_context_rows()
        apply_metroliza_theme(self)

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
        self.parse_button.setToolTip("Import measurements from PDF reports into a SQLite database.")
        self.modifydb_button.setToolTip("Clean stored references, sample numbers, headers, and record values.")
        self.export_button.setToolTip("Filter, group, and export database measurements to an Excel workbook.")
        self.map_characteristics_button.setToolTip("Map different report names to one common characteristic name.")
        self.cancel_metadata_enrichment_button.setToolTip("Request metadata enrichment cancellation after the current report")

    def setup_menu_actions(self):
        """Set up the menu actions for the main window."""
        self.about_button = QAction("About", self)
        self.about_button.triggered.connect(self.open_about_window)
        self.release_notes_action = QAction("Release notes", self)
        self.release_notes_action.triggered.connect(self.open_release_notes_dialog)
        self.csv_summary_action = QAction("CSV Summary...", self)
        self.csv_summary_action.setToolTip("Create a standalone summary workbook from CSV data.")
        self.csv_summary_action.triggered.connect(self.launch_csv_summary_dialog)
        self.enrich_metadata_action = QAction("Enrich existing database metadata...", self)
        self.enrich_metadata_action.setToolTip("Run OCR metadata enrichment on reports already saved in the selected database")
        self.enrich_metadata_action.triggered.connect(self.launch_metadata_enrichment)
        self.industrial_data_action = QAction("Industrial data...", self)
        self.industrial_data_action.setToolTip("Configure, sync, link, and export cached Oznak industrial data")
        self.industrial_data_action.triggered.connect(self.launch_industrial_data_dialog)
        self.tools_menu = self.menuBar().addMenu("Tools")
        self.tools_menu.addAction(self.csv_summary_action)
        self.tools_menu.addAction(self.enrich_metadata_action)
        self.tools_menu.addAction(self.industrial_data_action)
        _, self.help_menu = build_help_menu(self, [("Main window manual", 'main_window')], menu_bar=self.menuBar())
        if hasattr(self.help_menu, "addSeparator"):
            self.help_menu.addSeparator()
        self.help_menu.addAction(self.release_notes_action)
        self.help_menu.addAction(self.about_button)

    def setup_buttons_layout(self):
        """Add the buttons to the layout and connect the signals."""
        self.layout.addWidget(self.context_label)
        self.layout.addWidget(self.source_status_label)
        self.layout.addWidget(self.database_status_label)
        self.layout.addWidget(separator())
        self.layout.addWidget(self.workflow_label)
        self.layout.addWidget(self.workflow_hint_label)

        primary_row = QHBoxLayout()
        primary_row.setContentsMargins(0, 0, 0, 0)
        primary_row.setSpacing(8)
        primary_row.addWidget(self.parse_button)
        primary_row.addWidget(self.export_button)
        self.layout.addLayout(primary_row)

        prep_row = QHBoxLayout()
        prep_row.setContentsMargins(0, 0, 0, 0)
        prep_row.setSpacing(8)
        prep_row.addWidget(self.modifydb_button)
        prep_row.addWidget(self.map_characteristics_button)
        self.layout.addLayout(prep_row)

        self.layout.addWidget(separator())
        self.layout.addWidget(self.metadata_enrichment_status_label)
        self.layout.addWidget(self.metadata_enrichment_progress_bar)
        self.layout.addWidget(self.cancel_metadata_enrichment_button)
        self.parse_button.clicked.connect(self.launch_parsing_dialog)
        self.modifydb_button.clicked.connect(self.launch_modifydb_dialog)
        self.export_button.clicked.connect(self.launch_export_dialog)
        self.map_characteristics_button.clicked.connect(self.launch_characteristic_mapping_dialog)
        self.cancel_metadata_enrichment_button.clicked.connect(self.stop_metadata_enrichment)
        self.metadata_enrichment_status_label.setVisible(False)
        self.metadata_enrichment_progress_bar.setVisible(False)
        self.cancel_metadata_enrichment_button.setVisible(False)
        configure_accessibility(self.parse_button, name="Parse Reports")
        configure_accessibility(self.export_button, name="Export Workbook")
        configure_accessibility(self.modifydb_button, name="Modify Database")
        configure_accessibility(self.map_characteristics_button, name="Match Characteristic Names")
        configure_accessibility(self.cancel_metadata_enrichment_button, name="Cancel metadata enrichment")

    def _sync_context_rows(self):
        source_text = self.directory if self.directory else "not selected"
        database_text = self.db_file if self.db_file else "not selected"
        self.source_status_label.setText(f"Source: {source_text}")
        self.database_status_label.setText(f"Database: {database_text}")
        set_status_variant(self.source_status_label, "success" if self.directory else "neutral")
        set_status_variant(self.database_status_label, "success" if self.db_file else "neutral")

    def is_metadata_enrichment_active(self):
        return (
            self.metadata_enrichment_thread is not None
            and self.metadata_enrichment_thread.isRunning()
        )

    def launch_metadata_enrichment(self):
        """Start modeless OCR metadata enrichment for the selected database."""
        try:
            if not self.db_file:
                self.metadata_enrichment_status_label.setText("Select a database before enrichment")
                self.metadata_enrichment_status_label.setVisible(True)
                set_status_variant(self.metadata_enrichment_status_label, "warning")
                return
            if self.is_metadata_enrichment_active():
                self.metadata_enrichment_status_label.setText("Metadata enrichment already running")
                self.metadata_enrichment_status_label.setVisible(True)
                set_status_variant(self.metadata_enrichment_status_label, "info")
                return

            self.metadata_enrichment_thread = MetadataEnrichmentThread(self.db_file)
            self.metadata_enrichment_error_message = None
            self.metadata_enrichment_thread.update_label.connect(self.metadata_enrichment_status_label.setText)
            self.metadata_enrichment_thread.update_progress.connect(self.metadata_enrichment_progress_bar.setValue)
            self.metadata_enrichment_thread.error_occurred.connect(self.on_metadata_enrichment_error)
            self.metadata_enrichment_thread.enrichment_finished.connect(self.on_metadata_enrichment_finished)

            self.metadata_enrichment_status_label.setText("Metadata enrichment starting")
            self.metadata_enrichment_status_label.setVisible(True)
            set_status_variant(self.metadata_enrichment_status_label, "info")
            self.metadata_enrichment_progress_bar.setValue(0)
            self.metadata_enrichment_progress_bar.setVisible(True)
            self.cancel_metadata_enrichment_button.setEnabled(True)
            self.cancel_metadata_enrichment_button.setVisible(True)
            self.enrich_metadata_action.setEnabled(False)
            self.metadata_enrichment_thread.start()
        except Exception as e:
            self.log_and_exit(e)

    def stop_metadata_enrichment(self):
        try:
            if self.metadata_enrichment_thread is not None and self.metadata_enrichment_thread.isRunning():
                self.metadata_enrichment_thread.stop_enrichment()
                self.cancel_metadata_enrichment_button.setEnabled(False)
                self.metadata_enrichment_status_label.setText("Canceling metadata enrichment...")
                set_status_variant(self.metadata_enrichment_status_label, "warning")
        except Exception as e:
            self.log_and_exit(e)

    def on_metadata_enrichment_error(self, message):
        self.metadata_enrichment_error_message = message
        self.metadata_enrichment_status_label.setText(f"Metadata enrichment failed: {message}")
        set_status_variant(self.metadata_enrichment_status_label, "danger")

    def on_metadata_enrichment_finished(self):
        try:
            self.enrich_metadata_action.setEnabled(True)
            self.cancel_metadata_enrichment_button.setEnabled(False)
            self.cancel_metadata_enrichment_button.setVisible(False)
            if self.metadata_enrichment_error_message:
                self.metadata_enrichment_status_label.setText(
                    f"Metadata enrichment failed: {self.metadata_enrichment_error_message}"
                )
                set_status_variant(self.metadata_enrichment_status_label, "danger")
                return
            if self.metadata_enrichment_thread is None:
                return
            result = getattr(self.metadata_enrichment_thread, "result", None)
            if result is not None:
                self.metadata_enrichment_progress_bar.setValue(100)
                self.metadata_enrichment_status_label.setText(
                    f"Metadata enrichment complete: {result.enriched_files}/{result.total_files} reports updated"
                )
                set_status_variant(self.metadata_enrichment_status_label, "success")
        except Exception as e:
            self.log_and_exit(e)

    def launch_parsing_dialog(self):
        """Launch the parsing dialog and close the other dialogs if they are open."""
        try:
            if self.export_dialog and self.export_dialog.isVisible():
                self.export_dialog.close()
                
            if self.modifydb_dialog and self.modifydb_dialog.isVisible():
                self.modifydb_dialog.close()

            if not self.parsing_dialog or not self.parsing_dialog.isVisible():
                self.parsing_dialog = ParsingDialog(self, self.directory, self.db_file)
                enrichment_signal = getattr(self.parsing_dialog, "metadata_enrichment_requested", None)
                if enrichment_signal is not None:
                    enrichment_signal.connect(self.start_metadata_enrichment_from_parsing)
                self.parsing_dialog.show()
        except Exception as e:
            CustomLogger(e, reraise=False)

    def start_metadata_enrichment_from_parsing(self, db_file):
        """Receive a successful light import request and start modeless enrichment."""
        try:
            if db_file:
                self.set_db_file(db_file)
            self.launch_metadata_enrichment()
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

    def launch_industrial_data_dialog(self):
        try:
            if not self.industrial_data_dialog or not self.industrial_data_dialog.isVisible():
                self.industrial_data_dialog = IndustrialDataDialog(self, self.db_file)
                self.industrial_data_dialog.show()

            self.industrial_data_dialog.raise_()
            self.industrial_data_dialog.activateWindow()
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
            self._sync_context_rows()
            if self.industrial_data_dialog and self.industrial_data_dialog.isVisible():
                self.industrial_data_dialog.update_db_file(db_file)
        except Exception as e:
            self.log_and_exit(e)

    def set_directory(self, directory):
        try:
            self.directory = directory
            self._sync_context_rows()
        except Exception as e:
            self.log_and_exit(e)

    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)

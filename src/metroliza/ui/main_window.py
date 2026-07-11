import base64
import importlib
from pathlib import Path
import tempfile
from time import perf_counter
from typing import Callable

from metroliza.app.startup_profile import record_event
from metroliza.resources.app_assets import encoded_icon
from metroliza.shared.custom_logger import CustomLogger
from metroliza.ui.help_menu import build_help_menu
from PyQt6.QtCore import QByteArray, QTimer
from PyQt6.QtGui import QAction, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_window_size,
    section_label,
    secondary_label,
    separator,
    set_status_variant,
    status_chip,
)


FEATURE_IMPORT_WARMUP_MODULES = (
    ("Parse Reports", "metroliza.ui.parsing_dialog"),
    ("Export Workbook", "metroliza.ui.export_dialog"),
    ("CSV Summary", "metroliza.ui.industrial_analytics_dialog"),
    ("Industrial Data", "metroliza.ui.industrial_data_dialog"),
    ("Metadata Enrichment", "metroliza.parsing.metadata_enrichment_thread"),
    ("Modify Database", "metroliza.ui.modify_db"),
    ("Match Characteristic Names", "metroliza.ui.characteristic_mapping_dialog"),
    ("Parser Profiles", "metroliza.ui.parser_plugin_wizard"),
)


def warm_feature_imports(importer=importlib.import_module):
    """Preload feature modules so opening them from the main window is immediate."""
    record_event("feature_warmup_start", module_count=len(FEATURE_IMPORT_WARMUP_MODULES))
    warmup_start = perf_counter()
    loaded_modules = []
    failed_modules = []
    for label, module_name in FEATURE_IMPORT_WARMUP_MODULES:
        loaded_module, failed_module = _warm_feature_module(
            label,
            module_name,
            importer=importer,
        )
        if loaded_module is not None:
            loaded_modules.append(loaded_module)
        if failed_module is not None:
            failed_modules.append(failed_module)
    record_event(
        "feature_warmup_done",
        loaded_count=len(loaded_modules),
        failed_count=len(failed_modules),
        elapsed_ms=round((perf_counter() - warmup_start) * 1000, 3),
    )
    return loaded_modules, failed_modules


def _warm_feature_module(label, module_name, *, importer):
    module_start = perf_counter()
    record_event("feature_warmup_module_start", label=label, module=module_name)
    try:
        importer(module_name)
    except Exception as exc:  # pragma: no cover - exercised through tests with fakes
        elapsed_ms = (perf_counter() - module_start) * 1000
        record_event(
            "feature_warmup_module_done",
            label=label,
            module=module_name,
            status="failed",
            elapsed_ms=round(elapsed_ms, 3),
            error_type=type(exc).__name__,
        )
        return None, {
            "module": module_name,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }

    elapsed_ms = (perf_counter() - module_start) * 1000
    record_event(
        "feature_warmup_module_done",
        label=label,
        module=module_name,
        status="loaded",
        elapsed_ms=round(elapsed_ms, 3),
    )
    return module_name, None


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

        # Set the window icon without importing the loading GIF asset bundle.
        self.setWindowIcon(self.decode_icon(encoded_icon))

        # Initialize the dialogs and attributes
        self.parsing_dialog = None
        self.modifydb_dialog = None
        self.export_dialog = None
        self.metadata_enrichment_thread = None
        self.metadata_enrichment_error_message = None
        self.industrial_data_dialog = None
        self.realtime_monitoring_dialog = None
        self.last_realtime_dashboard_path = None
        self.last_realtime_dashboard_db_path = None
        self._realtime_session_db_path = None
        self._recovered_realtime_db_paths: set[str] = set()
        self._close_deferred_for_realtime = False
        self.parser_plugin_wizard_dialog = None
        self.directory = None
        self.db_file = None
        self._feature_import_warmup_completed = False
        self._feature_import_warmup_scheduled = False
        self._feature_import_warmup_failures = []
        self._feature_import_warmup_loaded_modules = []
        self._feature_import_warmup_queue = []
        self._feature_import_warmup_start = None
        self._feature_import_warmup_on_finished = None
        self._feature_import_warmup_status_callback = None
        self._feature_import_warmup_importer = importlib.import_module

        # Initialize and set up command-center widgets
        self.workflow_label = section_label("Workflow")
        self.context_label = section_label("Current context")
        self.source_status_label = status_chip("Source: not selected", "neutral")
        self.database_status_label = status_chip("Database: not selected", "neutral")
        self.workflow_hint_label = secondary_label(
            "Parse reports, clean database values when needed, match names, then export the workbook."
        )
        self.workflow_next_step_label = status_chip(
            "Next step: choose reports and create or select a database.",
            "warning",
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

    def schedule_feature_import_warmup(
        self,
        *,
        delay_ms: int = 100,
        on_finished: Callable[[], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Schedule feature import warmup after the first visible window paint."""
        if self._feature_import_warmup_completed:
            if on_finished is not None:
                QTimer.singleShot(0, on_finished)
            return
        if self._feature_import_warmup_completed or self._feature_import_warmup_scheduled:
            return
        self._feature_import_warmup_scheduled = True
        self._feature_import_warmup_on_finished = on_finished
        self._feature_import_warmup_status_callback = status_callback
        self._feature_import_warmup_loaded_modules = []
        self._feature_import_warmup_failures = []
        self._feature_import_warmup_queue = list(FEATURE_IMPORT_WARMUP_MODULES)
        self._feature_import_warmup_start = None
        record_event("feature_warmup_scheduled", delay_ms=max(0, int(delay_ms)))
        self.statusBar().showMessage("Loading tools...", 2000)
        if status_callback is not None:
            status_callback("Loading tools...")
        QTimer.singleShot(max(0, int(delay_ms)), self._preload_next_feature_import)

    def _preload_next_feature_import(self):
        """Load the next feature module and yield back to Qt before continuing."""
        if self._feature_import_warmup_completed:
            return

        if not self._feature_import_warmup_queue:
            self._finish_feature_import_warmup()
            return

        if len(self._feature_import_warmup_queue) == len(FEATURE_IMPORT_WARMUP_MODULES):
            self._feature_import_warmup_start = perf_counter()
            record_event("feature_warmup_start", module_count=len(FEATURE_IMPORT_WARMUP_MODULES))

        label, module_name = self._feature_import_warmup_queue.pop(0)
        self.statusBar().showMessage(f"Loading {label}...", 2000)
        if self._feature_import_warmup_status_callback is not None:
            self._feature_import_warmup_status_callback(f"Loading {label}...")

        loaded_module, failed_module = _warm_feature_module(
            label,
            module_name,
            importer=self._feature_import_warmup_importer,
        )
        if loaded_module is not None:
            self._feature_import_warmup_loaded_modules.append(loaded_module)
        if failed_module is not None:
            self._feature_import_warmup_failures.append(failed_module)

        QTimer.singleShot(0, self._preload_next_feature_import)

    def _finish_feature_import_warmup(self):
        loaded_modules = list(self._feature_import_warmup_loaded_modules)
        failed_modules = list(self._feature_import_warmup_failures)
        warmup_start = self._feature_import_warmup_start or perf_counter()
        record_event(
            "feature_warmup_done",
            loaded_count=len(loaded_modules),
            failed_count=len(failed_modules),
            elapsed_ms=round((perf_counter() - warmup_start) * 1000, 3),
        )
        self._feature_import_warmup_completed = True
        self._feature_import_warmup_scheduled = False
        self._feature_import_warmup_failures = list(failed_modules)
        self._feature_import_warmup_queue = []
        on_finished = self._feature_import_warmup_on_finished
        self._feature_import_warmup_on_finished = None
        self._feature_import_warmup_status_callback = None
        if failed_modules:
            self.statusBar().showMessage(
                "Some tools will finish loading when opened.",
                5000,
            )
            for failure in failed_modules:
                exception = RuntimeError(
                    "Feature import warm-up failed for "
                    f"{failure['module']}: {failure['error_type']}: {failure['message']}"
                )
                CustomLogger(exception, reraise=False)
            if on_finished is not None:
                on_finished()
            return

        if loaded_modules:
            self.statusBar().showMessage("Tools ready", 2000)
        if on_finished is not None:
            on_finished()

    def decode_icon(self, encoded_icon_payload):
        """Decode the base64 encoded icon and return a QIcon object."""
        icon_decoded = base64.b64decode(encoded_icon_payload)
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
        self.csv_summary_action.setToolTip("Analyze CSV or Excel data with dashboards and workbook output.")
        self.csv_summary_action.triggered.connect(self.launch_csv_summary_dialog)
        self.enrich_metadata_action = QAction("Enrich existing database metadata...", self)
        self.enrich_metadata_action.setToolTip("Run OCR metadata enrichment on reports already saved in the selected database")
        self.enrich_metadata_action.triggered.connect(self.launch_metadata_enrichment)
        self.industrial_data_action = QAction("Industrial data...", self)
        self.industrial_data_action.setToolTip("Configure, sync, link, and export cached Oznak industrial data")
        self.industrial_data_action.triggered.connect(self.launch_industrial_data_dialog)
        self.realtime_monitoring_action = QAction("Real-time Industrial Monitoring...", self)
        self.realtime_monitoring_action.setToolTip(
            "Configure and run realtime polling for industrial source databases."
        )
        self.realtime_monitoring_action.triggered.connect(self.launch_realtime_industrial_monitoring_dialog)
        self.parser_profiles_action = QAction("Parser profiles...", self)
        self.parser_profiles_action.setToolTip("Create a local handoff folder for a new supplier parser profile")
        self.parser_profiles_action.triggered.connect(self.launch_parser_plugin_wizard)
        self.tools_menu = self.menuBar().addMenu("Tools")
        self.tools_menu.addAction(self.csv_summary_action)
        self.tools_menu.addAction(self.enrich_metadata_action)
        self.tools_menu.addAction(self.industrial_data_action)
        self.tools_menu.addAction(self.realtime_monitoring_action)
        self.tools_menu.addAction(self.parser_profiles_action)
        _, self.help_menu = build_help_menu(
            self,
            [
                ("Main window manual", 'main_window'),
                ("Startup, license, and support", 'help_startup_and_license'),
            ],
            menu_bar=self.menuBar(),
        )
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
        self.layout.addWidget(self.workflow_next_step_label)

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
        configure_accessibility(self.workflow_next_step_label, name="Recommended next workflow step")
        configure_accessibility(self.cancel_metadata_enrichment_button, name="Cancel metadata enrichment")

    def _sync_context_rows(self):
        source_text = self.directory if self.directory else "not selected"
        database_text = self.db_file if self.db_file else "not selected"
        self.source_status_label.setText(f"Source: {source_text}")
        self.database_status_label.setText(f"Database: {database_text}")
        set_status_variant(self.source_status_label, "success" if self.directory else "neutral")
        set_status_variant(self.database_status_label, "success" if self.db_file else "neutral")
        self._sync_workflow_next_step()

    def _sync_workflow_next_step(self):
        if not hasattr(self, "workflow_next_step_label"):
            return
        has_source = bool(self.directory)
        has_database = bool(self.db_file)
        if has_source and has_database:
            text = "Next step: parse reports, then export or clean the database if needed."
            variant = "success"
        elif has_database:
            text = "Next step: export this database, or choose reports to add more data."
            variant = "info"
        elif has_source:
            text = "Next step: select or create a database file for these reports."
            variant = "warning"
        else:
            text = "Next step: choose reports and create or select a database."
            variant = "warning"
        self.workflow_next_step_label.setText(text)
        set_status_variant(self.workflow_next_step_label, variant)

    def is_metadata_enrichment_active(self):
        return (
            self.metadata_enrichment_thread is not None
            and self.metadata_enrichment_thread.isRunning()
        )

    def launch_metadata_enrichment(self):
        """Start modeless OCR metadata enrichment for the selected database."""
        try:
            from metroliza.parsing.metadata_enrichment_thread import MetadataEnrichmentThread

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
            self.metadata_enrichment_thread.finished.connect(self._clear_metadata_enrichment_thread)

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

    def _clear_metadata_enrichment_thread(self):
        self.metadata_enrichment_thread = None

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

    def closeEvent(self, event):
        if self.is_metadata_enrichment_active():
            self.stop_metadata_enrichment()
            event.ignore()
            return
        if self.realtime_monitoring_dialog is not None:
            if not self.realtime_monitoring_dialog.request_shutdown():
                self._close_deferred_for_realtime = True
                event.ignore()
                return
            self.realtime_monitoring_dialog.close()
        self._close_deferred_for_realtime = False
        self._cleanup_realtime_session_db()
        super().closeEvent(event)

    def launch_parsing_dialog(self):
        """Launch the parsing dialog and close the other dialogs if they are open."""
        try:
            from metroliza.ui.parsing_dialog import ParsingDialog

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
            self.log_and_exit(e)

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
            from metroliza.ui.modify_db import ModifyDB

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
            from metroliza.ui.export_dialog import ExportDialog

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
            from metroliza.ui.about_window import AboutWindow

            about_window = AboutWindow(self, days_until_expiration=self.days_until_expiration)
            about_window.exec()
        except Exception as e:
            self.log_and_exit(e)

    def open_release_notes_dialog(self):
        try:
            from metroliza.app.version import release_notes
            from metroliza.ui.release_notes_dialog import ReleaseNotesDialog

            release_notes_dialog = ReleaseNotesDialog(self, release_notes)
            release_notes_dialog.exec()
        except Exception as e:
            self.log_and_exit(e)

    def launch_csv_summary_dialog(self):
        try:
            from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog, SOURCE_TABULAR_FILE

            csv_summary_window = IndustrialAnalyticsDialog(
                self,
                source_kind=SOURCE_TABULAR_FILE,
            )
            csv_summary_window.exec()
        except Exception as e:
            self.log_and_exit(e)

    def launch_industrial_data_dialog(self):
        try:
            from metroliza.ui.industrial_data_dialog import IndustrialDataDialog

            if not self.industrial_data_dialog or not self.industrial_data_dialog.isVisible():
                self.industrial_data_dialog = IndustrialDataDialog(self, self.db_file)
                self.industrial_data_dialog.show()

            self.industrial_data_dialog.raise_()
            self.industrial_data_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)

    def launch_realtime_industrial_monitoring_dialog(self):
        try:
            dashboard_db_path, using_session_db = self._realtime_dashboard_db_file()
            from metroliza.ui.realtime_industrial_monitoring_dialog import (
                RealtimeIndustrialMonitoringDialog,
            )

            if (
                self.realtime_monitoring_dialog is not None
                and self.realtime_monitoring_dialog.isVisible()
                and self.realtime_monitoring_dialog.db_file != dashboard_db_path
            ):
                if not self.realtime_monitoring_dialog.request_shutdown():
                    self.statusBar().showMessage(
                        "Waiting for realtime monitoring to stop before changing databases.",
                        5000,
                    )
                    return
                self.realtime_monitoring_dialog.close()
                self.realtime_monitoring_dialog = None
            if self.realtime_monitoring_dialog is None or not self.realtime_monitoring_dialog.isVisible():
                self.realtime_monitoring_dialog = RealtimeIndustrialMonitoringDialog(
                    self,
                    dashboard_db_path,
                )
                self.realtime_monitoring_dialog.shutdown_complete.connect(
                    self._on_realtime_monitoring_shutdown_complete
                )
                self.realtime_monitoring_dialog.show()
            else:
                self.realtime_monitoring_dialog.reload_from_database()
            self.last_realtime_dashboard_db_path = dashboard_db_path
            self.realtime_monitoring_dialog.raise_()
            self.realtime_monitoring_dialog.activateWindow()
            if using_session_db:
                self.statusBar().showMessage(
                    "Real-time industrial monitoring opened with temporary session DB.",
                    5000,
                )
            else:
                self.statusBar().showMessage("Real-time industrial monitoring opened.", 5000)
        except Exception as e:
            self.log_and_exit(e)

    def _on_realtime_monitoring_shutdown_complete(self) -> None:
        dialog = self.realtime_monitoring_dialog
        if dialog is not None:
            dialog.close()
        if self._close_deferred_for_realtime:
            QTimer.singleShot(0, self.close)

    def launch_realtime_industrial_monitoring_dashboard(self):
        self.launch_realtime_industrial_monitoring_dialog()

    def _realtime_dashboard_db_file(self):
        if self.db_file:
            return self.db_file, False
        if self._realtime_session_db_path is None or not self._realtime_session_db_path.exists():
            session_dir = Path(tempfile.gettempdir()) / "metroliza" / "realtime_sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            session_file = tempfile.NamedTemporaryFile(
                prefix="metroliza_realtime_session_",
                suffix=".sqlite",
                dir=session_dir,
                delete=False,
            )
            session_file.close()
            self._realtime_session_db_path = Path(session_file.name)
        return str(self._realtime_session_db_path), True

    def _cleanup_realtime_session_db(self):
        session_db_path = self._realtime_session_db_path
        self._realtime_session_db_path = None
        if session_db_path is None:
            return
        for path in (
            session_db_path,
            Path(f"{session_db_path}-wal"),
            Path(f"{session_db_path}-shm"),
        ):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            session_db_path.parent.rmdir()
        except OSError:
            pass

    def launch_parser_plugin_wizard(self):
        try:
            from metroliza.ui.parser_plugin_wizard import ParserPluginWizardDialog

            if not self.parser_plugin_wizard_dialog or not self.parser_plugin_wizard_dialog.isVisible():
                self.parser_plugin_wizard_dialog = ParserPluginWizardDialog(self)
                self.parser_plugin_wizard_dialog.show()

            self.parser_plugin_wizard_dialog.raise_()
            self.parser_plugin_wizard_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)

    def launch_characteristic_mapping_dialog(self):
        try:
            from metroliza.ui.characteristic_mapping_dialog import CharacteristicMappingDialog

            characteristic_mapping_dialog = CharacteristicMappingDialog(self, self.db_file)
            characteristic_mapping_dialog.exec()
        except Exception as e:
            self.log_and_exit(e)

    def set_db_file(self, db_file):
        try:
            recovery_result = self._recover_abandoned_realtime_staging(db_file)
            self.db_file = db_file
            self._sync_context_rows()
            if self.industrial_data_dialog and self.industrial_data_dialog.isVisible():
                self.industrial_data_dialog.update_db_file(db_file)
            if recovery_result and recovery_result.get("runs_failed", 0):
                self.statusBar().showMessage(
                    "Recovered abandoned industrial sync staging: "
                    f"{recovery_result['runs_failed']} run(s), "
                    f"{recovery_result.get('rows_discarded', 0)} row(s) discarded.",
                    8000,
                )
        except Exception as e:
            self.log_and_exit(e)

    def _recover_abandoned_realtime_staging(self, db_file):
        if not db_file or str(db_file) == ":memory:":
            return None
        db_path = Path(db_file).expanduser().resolve()
        db_key = str(db_path)
        if db_key in self._recovered_realtime_db_paths or not db_path.exists():
            return None
        from metroliza.industrial.industrial_data_repository import IndustrialDataRepository

        result = IndustrialDataRepository(db_key).recover_abandoned_sync_staging_at_startup()
        self._recovered_realtime_db_paths.add(db_key)
        return result

    def set_directory(self, directory):
        try:
            self.directory = directory
            self._sync_context_rows()
        except Exception as e:
            self.log_and_exit(e)

    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)

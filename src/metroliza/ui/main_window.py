import base64
import importlib
import importlib.util
from pathlib import Path
import tempfile
from time import perf_counter
from typing import Callable

from metroliza.app.startup_profile import record_event
from metroliza.resources.app_assets import encoded_icon
from metroliza.shared.custom_logger import CustomLogger
from metroliza.ui.help_menu import build_help_menu
from PyQt6.QtCore import QByteArray, QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from metroliza.ui.workspace_context import WorkspaceContext
from metroliza.ui.ui_preferences import UiPreferences
from metroliza.ui.window_coordinator import (
    WindowContextPolicy,
    WindowCoordinator,
)
from metroliza.ui.workspace_context import WorkspaceField
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    apply_metroliza_application_theme,
    configure_accessibility,
    configure_window_size,
    section_label,
    secondary_label,
    set_button_role,
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

    def __init__(self, version_label, days_until_expiration, *, ui_preferences=None):
        """Initialize the main window and its components.

        Args:
            VERSION_DATE (str): The version and date of the application.
        """
        super().__init__()
        self.ui_preferences = ui_preferences or UiPreferences(QSettings("Hexafe", "Metroliza"))

        # Initialize the main window and layout
        if days_until_expiration is None:
            self.setWindowTitle(f"Metroliza [{version_label}]")
        else:
            self.setWindowTitle(f"Metroliza [{version_label}] ({days_until_expiration+1} day{'s' if days_until_expiration+1 > 1 else ''} left)")
        configure_window_size(self, minimum=(720, 480), initial=(1100, 740), screen_margin=32)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(4)
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
        self._pending_realtime_database = None
        self._recovered_realtime_db_paths: set[str] = set()
        self._close_deferred_for_realtime = False
        self._close_deferred_for_children = False
        self._close_deferred_for_reports = False
        self._reports_workspace = None
        self._reports_first_paint = False
        self._database_workflow_buttons = []
        self._deferred_close_blockers: set[str] = set()
        self._deferred_child_close_retry_scheduled = False
        self.parser_plugin_wizard_dialog = None
        self.directory = None
        self.db_file = None
        self.workspace_context = WorkspaceContext()
        self.workspace_context.snapshot_changed.connect(self._on_workspace_snapshot_changed)
        self.window_coordinator = WindowCoordinator(self.workspace_context, parent=self)
        self.window_coordinator.window_closed.connect(self._on_coordinated_window_closed)
        self.window_coordinator.window_close_deferral_cancelled.connect(
            self._on_coordinated_close_deferral_cancelled
        )
        self._coordinated_window_attributes = {
            "modify_database": "modifydb_dialog",
            "export": "export_dialog",
            "industrial_data": "industrial_data_dialog",
            "realtime_monitor": "realtime_monitoring_dialog",
            "parser_profiles": "parser_plugin_wizard_dialog",
        }
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
        self.workflow_hint_label = secondary_label("Review and import reports in Reports, then prepare or export the database.")
        self.workflow_next_step_label = status_chip(
            "Next step: choose reports and create or select a database.",
            "warning",
        )
        self.workspace_notice_label = status_chip("Workspace ready", "neutral")
        self.workspace_notice_label.setVisible(False)
        self.parse_button = QPushButton("Parse Reports")
        self.home_next_action = self.parse_button
        self.home_report_result = secondary_label("")
        self.home_report_progress = secondary_label("")
        self.home_cancel_report = QPushButton("Cancel report operation")
        self.modifydb_button = QPushButton("Modify Database")
        self.export_button = QPushButton("Export Workbook")
        self.map_characteristics_button = QPushButton("Match Characteristic Names")
        self.metadata_enrichment_status_label = status_chip("Metadata enrichment idle", "neutral")
        self.metadata_enrichment_progress_bar = QProgressBar()
        self.cancel_metadata_enrichment_button = QPushButton("Cancel")
        set_button_role(self.parse_button, "primary")
        set_button_role(self.export_button, "secondary")
        set_button_role(self.modifydb_button, "secondary")
        set_button_role(self.map_characteristics_button, "secondary")
        set_button_role(self.cancel_metadata_enrichment_button, "danger")
        self.setup_button_tooltips()

        # Set up menu items
        self.setup_menu_actions()

        # Add buttons to the layout and connect signals
        self.setup_buttons_layout()
        self._sync_context_rows()
        self._restore_ui_preferences()
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
        self.parse_button.setToolTip("Open Reports and focus the next available report action.")
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
        self.csv_summary_action.triggered.connect(lambda: self._show_workspace_page("csv_analytics"))
        self.enrich_metadata_action = QAction("Enrich existing database metadata...", self)
        self.enrich_metadata_action.setToolTip("Run OCR metadata enrichment on reports already saved in the selected database")
        self.enrich_metadata_action.triggered.connect(self.launch_metadata_enrichment)
        self.industrial_data_action = QAction("Industrial data...", self)
        self.industrial_data_action.setToolTip("Configure, sync, link, and export cached Oznak industrial data")
        self.industrial_data_action.triggered.connect(lambda: self._show_workspace_page("industrial_data"))
        self.realtime_monitoring_action = QAction("Real-time Industrial Monitoring...", self)
        self.realtime_monitoring_action.setToolTip(
            "Configure and run realtime polling for industrial source databases."
        )
        self.realtime_monitoring_action.triggered.connect(lambda: self._show_workspace_page("realtime_monitor"))
        self.parser_profiles_action = QAction("Parser profiles...", self)
        self.parser_profiles_action.setToolTip("Create a local handoff folder for a new supplier parser profile")
        self.parser_profiles_action.triggered.connect(lambda: self._show_workspace_page("parser_profiles"))
        self.tools_menu = self.menuBar().addMenu("Tools")
        self.tools_menu.addAction(self.csv_summary_action)
        self.tools_menu.addAction(self.enrich_metadata_action)
        self.tools_menu.addAction(self.industrial_data_action)
        self.tools_menu.addAction(self.realtime_monitoring_action)
        self.tools_menu.addAction(self.parser_profiles_action)
        self.view_menu = self.menuBar().addMenu("View")
        self.theme_menu = self.view_menu.addMenu("Theme")
        self.theme_action_group = QActionGroup(self)
        self.theme_action_group.setExclusive(True)
        self.theme_actions = {}
        for mode, label in (
            ("system", "System"),
            ("light", "Light"),
            ("dark", "Dark"),
            ("high_contrast", "System high contrast"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, selected_mode=mode: (
                    self._set_theme_mode(selected_mode) if checked else None
                )
            )
            self.theme_action_group.addAction(action)
            self.theme_menu.addAction(action)
            self.theme_actions[mode] = action
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
        self.diagnostic_incidents_action = QAction("Diagnostic incidents…", self)
        self.diagnostic_incidents_action.triggered.connect(self.open_diagnostic_incidents)
        self.help_menu.addAction(self.diagnostic_incidents_action)
        self.help_menu.aboutToShow.connect(self._refresh_incident_action)
        self._refresh_incident_action()
        self.help_menu.addAction(self.about_button)

    def _refresh_incident_action(self):
        available = importlib.util.find_spec("metroliza.ui.incident_dialog") is not None
        self.diagnostic_incidents_action.setEnabled(available)
        explanation = (
            "Inspect and export selected local diagnostic incidents."
            if available else "Diagnostic incidents are unavailable in this build."
        )
        self.diagnostic_incidents_action.setToolTip(explanation)
        self.diagnostic_incidents_action.setStatusTip(explanation)

    def open_diagnostic_incidents(self):
        """Use the normal lazy viewer entry; report absent and broken features separately."""
        try:
            module = importlib.import_module("metroliza.ui.incident_dialog")
        except ModuleNotFoundError as exc:
            if exc.name == "metroliza.ui.incident_dialog":
                self.diagnostic_incidents_action.setEnabled(False)
                message = "Diagnostic incidents are unavailable in this build."
            else:
                message = "Diagnostic incidents could not load because an installed dependency is unavailable."
            QMessageBox.warning(self, "Diagnostic incidents", message)
            return False
        except Exception:
            QMessageBox.warning(self, "Diagnostic incidents", "The installed diagnostic feature could not be loaded.")
            return False
        try:
            module.open_incident_viewer(self)
        except Exception:
            QMessageBox.warning(self, "Diagnostic incidents", "The diagnostic viewer could not be opened.")
            return False
        return True

    def setup_buttons_layout(self):
        """Compose primary workspaces around one persistent report owner."""
        self.layout.addWidget(self.workspace_notice_label)
        self.navigation_combo = QComboBox()
        self.navigation_combo.setAccessibleName("Metroliza workspace navigation")
        self.layout.addWidget(self.navigation_combo)
        shell_row = QHBoxLayout()
        shell_row.setContentsMargins(0, 0, 0, 0)
        shell_row.setSpacing(8)
        self.navigation_list = QListWidget()
        self.navigation_list.setObjectName("workspaceNavigation")
        self.navigation_list.setFixedWidth(168)
        self.workspace_stack = QStackedWidget()
        self.workspace_stack.setObjectName("workspacePages")
        # A hidden page's size hint must not force the current page wider/taller.
        self.workspace_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        shell_row.addWidget(self.navigation_list)
        shell_row.addWidget(self.workspace_stack, 1)
        self.layout.addLayout(shell_row, 1)

        self.home_page = QWidget()
        home_layout = QVBoxLayout(self.home_page)
        home_layout.setContentsMargins(4, 4, 4, 4)
        home_layout.setSpacing(8)
        for widget in (
            section_label("Home"), self.context_label, self.source_status_label,
            self.database_status_label, self.workflow_hint_label,
            self.workflow_next_step_label, self.home_report_progress,
            self.home_report_result, self.home_next_action, self.home_cancel_report,
        ):
            home_layout.addWidget(widget)
        home_layout.addStretch(1)
        self._add_workspace_page("Home", self.home_page)

        self.reports_page = QWidget()
        reports_layout = QVBoxLayout(self.reports_page)
        self._reports_layout = reports_layout
        reports_layout.setContentsMargins(0, 0, 0, 0)
        reports_layout.setSpacing(2)
        downstream_row = QHBoxLayout()
        downstream_row.setSpacing(4)
        for button in (self.modifydb_button, self.map_characteristics_button, self.export_button):
            downstream_row.addWidget(button)
        reports_layout.addLayout(downstream_row)
        self._add_workspace_page("Reports", self.reports_page)
        for title, description, action, callback in (
            ("CSV Analytics", "Analyze CSV or Excel data and prepare dashboards or workbooks.",
             "Open CSV Summary", self.launch_csv_summary_dialog),
            ("Industrial Data", "Configure read-only sources and work with their bounded local cache.",
             "Open Industrial Data", self.launch_industrial_data_dialog),
            ("Realtime Monitor", "Monitor reviewed source configurations and inspect source lag and events.",
             "Open Realtime Monitor", self.launch_realtime_industrial_monitoring_dialog),
            ("Parser Profiles", "Inspect unsupported formats and prepare a local parser-profile handoff.",
             "Manage Parser Profiles", self.launch_parser_plugin_wizard),
            ("Tools", "Maintenance utilities for the current database. Domain shortcuts in the Tools menu open their primary workspace.",
             "Enrich existing database metadata", self.launch_metadata_enrichment),
        ):
            self._add_workspace_page(title, self._build_workspace_landing_page(
                title, description, ((action, callback),),
            ))
        self.navigation_list.currentRowChanged.connect(self._on_navigation_changed)
        self.navigation_combo.currentIndexChanged.connect(self.navigation_list.setCurrentRow)
        self.navigation_list.setCurrentRow(0)
        self.navigation_list.currentRowChanged.connect(self._persist_navigation_index)

        task_row = QHBoxLayout()
        task_row.setSpacing(4)
        task_row.addWidget(self.metadata_enrichment_status_label, 1)
        task_row.addWidget(self.metadata_enrichment_progress_bar)
        task_row.addWidget(self.cancel_metadata_enrichment_button)
        self.layout.addLayout(task_row)
        self.home_next_action.clicked.connect(self.launch_parsing_dialog)
        self.home_cancel_report.clicked.connect(self._cancel_report_operation)
        self.modifydb_button.clicked.connect(self.launch_modifydb_dialog)
        self.export_button.clicked.connect(self.launch_export_dialog)
        self.map_characteristics_button.clicked.connect(self.launch_characteristic_mapping_dialog)
        self.cancel_metadata_enrichment_button.clicked.connect(self.stop_metadata_enrichment)
        self.metadata_enrichment_status_label.hide()
        self.metadata_enrichment_progress_bar.hide()
        self.cancel_metadata_enrichment_button.hide()
        configure_accessibility(self.export_button, name="Export Workbook")
        configure_accessibility(self.modifydb_button, name="Modify Database")
        configure_accessibility(self.map_characteristics_button, name="Match Characteristic Names")
        configure_accessibility(self.workflow_next_step_label, name="Recommended next workflow step")
        configure_accessibility(self.cancel_metadata_enrichment_button, name="Cancel metadata enrichment")
        configure_accessibility(self.navigation_list, name="Metroliza workspace navigation",
                                description="Choose a workflow without closing other work.")
        self._update_navigation_layout()

    def _add_workspace_page(self, label: str, page: QWidget) -> None:
        page_id = label.lower().replace(" ", "_")
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, page_id)
        self.navigation_list.addItem(item)
        self.navigation_combo.addItem(label, page_id)
        self.workspace_stack.addWidget(page)

    def _show_workspace_page(self, page_id):
        index = self.navigation_combo.findData(page_id)
        if index >= 0:
            self.navigation_list.setCurrentRow(index)

    def _on_navigation_changed(self, index):
        if self._reports_first_paint and self.navigation_combo.itemData(index) == "reports":
            self._ensure_reports_workspace()
        self.workspace_stack.setCurrentIndex(index)
        self.navigation_combo.blockSignals(True)
        self.navigation_combo.setCurrentIndex(index)
        self.navigation_combo.blockSignals(False)

    def _update_navigation_layout(self):
        compact = self.width() < 1000
        self.navigation_list.setVisible(not compact)
        self.navigation_combo.setVisible(compact)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "navigation_list"):
            self._update_navigation_layout()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._reports_first_paint:
            self._reports_first_paint = True
            if self.navigation_combo.currentData() == "reports":
                QTimer.singleShot(0, self._ensure_reports_workspace)

    @property
    def reports_workspace(self):
        return self._ensure_reports_workspace()

    def _ensure_reports_workspace(self):
        """Create the sole owner on entry, preserving startup's first-paint boundary."""
        if self._reports_workspace is None:
            from metroliza.ui.parsing_dialog import ReportsWorkspace
            from metroliza.ui.report_planner import PLANNER_ACTION_STYLE

            host = ReportsWorkspace(self.reports_page)
            host.operation_start_allowed = self._report_start_allowed
            self._reports_workspace = host
            self.parsing_dialog = host
            host.source_change_requested.connect(self.set_directory)
            host.database_change_requested.connect(self.set_db_file)
            host.metadata_enrichment_requested.connect(self.start_metadata_enrichment_from_parsing)
            host.state_changed.connect(self._sync_workflow_next_step)
            host.shutdown_ready.connect(self._on_reports_shutdown_ready)
            self._reports_layout.insertWidget(0, host, 1)
            for button in (self.modifydb_button, self.map_characteristics_button, self.export_button):
                button.setStyleSheet(PLANNER_ACTION_STYLE)
            host.apply_workspace_snapshot(self.workspace_context.snapshot)
            self._sync_workflow_next_step()
        return self._reports_workspace

    def _cancel_report_operation(self):
        if self._reports_workspace is not None:
            self._reports_workspace._request_active_worker_cancellation()

    def _build_workspace_landing_page(
        self,
        title: str,
        description: str,
        actions: tuple[tuple[str, Callable[[], None]], ...],
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        layout.addWidget(section_label(title))
        description_label = secondary_label(description)
        layout.addWidget(description_label)
        for index, (label, callback) in enumerate(actions):
            button = QPushButton(label)
            set_button_role(button, "primary" if index == 0 else "secondary")
            button.clicked.connect(callback)
            if title in ("Industrial Data", "Realtime Monitor", "Tools"):
                self._database_workflow_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)
        return page

    def _on_workspace_snapshot_changed(self, current, _previous) -> None:
        self.directory = current.source_directory
        self.db_file = current.database_file
        if self._reports_workspace is not None:
            self._reports_workspace.apply_workspace_snapshot(current)
        self._sync_context_rows()

    def _restore_ui_preferences(self) -> None:
        theme_mode = self.ui_preferences.get(
            "theme/mode",
            "system",
            expected_type=str,
        )
        if theme_mode not in self.theme_actions:
            theme_mode = "system"
        self._set_theme_mode(theme_mode, persist=False)

        page_id = self.ui_preferences.get("presentation/navigation/page", "", expected_type=str)
        if page_id:
            self._show_workspace_page(page_id)
        else:
            # Existing six-page integer preferences retain their original meaning.
            navigation_index = self.ui_preferences.get("presentation/navigation/current", 0, expected_type=int)
            if 0 <= navigation_index < 6:
                self.navigation_list.setCurrentRow(navigation_index)

        geometry = self.ui_preferences.get(
            "windows/main/geometry",
            QByteArray(),
            expected_type=QByteArray,
        )
        if not geometry.isEmpty():
            self.restoreGeometry(geometry)

    def _set_theme_mode(self, mode: str, *, persist: bool = True) -> None:
        if mode not in self.theme_actions:
            mode = "system"
        apply_metroliza_application_theme(QApplication.instance(), mode=mode)
        self.theme_actions[mode].setChecked(True)
        if persist:
            self.ui_preferences.set("theme/mode", mode)

    def _persist_navigation_index(self, index: int) -> None:
        if index >= 0 and hasattr(self, "ui_preferences"):
            self.ui_preferences.set("presentation/navigation/current", int(index))
            self.ui_preferences.set("presentation/navigation/page", self.navigation_combo.itemData(index))

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
        reports = self._reports_workspace
        busy = reports is not None and not reports.can_change_workspace()
        if busy:
            caption = "View active report operation"
        elif not self.directory:
            caption = "Choose reports in Reports"
        elif not self.db_file:
            caption = "Choose database in Reports"
        elif reports is not None and reports.parse_button.isEnabled():
            caption = "Continue selected import in Reports"
        else:
            caption = "Review reports in Reports"
        self.home_next_action.setText(caption)
        self.home_next_action.setAccessibleName(caption)
        if reports is not None:
            guidance = reports.readiness_label.text()
            variant = reports.readiness_label.property("statusVariant")
        else:
            guidance = (
                "Select a source and database to review reports." if not self.directory
                else "Select or create a database before reviewing reports." if not self.db_file
                else "Ready to review. No database changes are made until you import."
            )
            variant = "warning"
        self.workflow_next_step_label.setText(guidance)
        set_status_variant(self.workflow_next_step_label, variant)
        self.home_cancel_report.setVisible(busy)
        self.home_report_progress.setVisible(busy)
        phase = "Reviewing reports" if busy and reports.preflight_thread is not None else "Processing selected reports"
        self.home_report_progress.setText(f"{phase}: {reports._operation_progress}%" if busy else "")
        outcome = reports.report_planner.outcome.toPlainText() if reports is not None else ""
        summary = " · ".join(line for line in outcome.splitlines() if line)[:300]
        self.home_report_result.setText(summary)
        self.home_report_result.setVisible(bool(summary))
        for button in (self.modifydb_button, self.map_characteristics_button, self.export_button):
            button.setEnabled(bool(self.db_file) and not busy)
        for button in self._database_workflow_buttons:
            button.setEnabled(not busy)
        self.enrich_metadata_action.setEnabled(not busy and not self.is_metadata_enrichment_active())

    def is_metadata_enrichment_active(self):
        return (
            self.metadata_enrichment_thread is not None
            and self.metadata_enrichment_thread.isRunning()
        )

    def launch_metadata_enrichment(self):
        """Start modeless OCR metadata enrichment for the selected database."""
        if not self._report_database_action_allowed():
            return
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
        self._sync_workflow_next_step()

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
            self.enrich_metadata_action.setEnabled(
                self._reports_workspace is None or self._reports_workspace.can_change_workspace()
            )
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
        if self._reports_workspace is not None and not self._reports_workspace.request_shutdown():
            self._close_deferred_for_reports = True
            self.workspace_notice_label.setText("Waiting for the report operation to stop before closing Metroliza.")
            self.workspace_notice_label.show()
            event.ignore()
            return
        self._close_deferred_for_reports = False
        if self.is_metadata_enrichment_active():
            self.stop_metadata_enrichment()
            event.ignore()
            return
        realtime_dialog = self.realtime_monitoring_dialog
        if realtime_dialog is not None:
            if not realtime_dialog.request_shutdown():
                deferred_check = getattr(realtime_dialog, "is_close_deferred", None)
                self._close_deferred_for_realtime = bool(
                    callable(deferred_check) and deferred_check()
                )
                if not self._close_deferred_for_realtime:
                    cleanup_check = getattr(realtime_dialog, "dashboard_cleanup_retry_required", None)
                    if callable(cleanup_check) and cleanup_check():
                        self.workspace_notice_label.setText(
                            "Private dashboard storage could not be removed. Close again to retry."
                        )
                    else:
                        self.workspace_notice_label.setText(
                            "Metroliza close was cancelled because Realtime Monitor kept "
                            "unsaved source changes. Resolve them and try again."
                        )
                    set_status_variant(self.workspace_notice_label, "warning")
                    self.workspace_notice_label.setVisible(True)
                event.ignore()
                return
            managed_realtime = self.window_coordinator.get("realtime_monitor")
            if realtime_dialog is not managed_realtime and realtime_dialog.close() is False:
                self._show_close_blocked_notice(("realtime_monitor",))
                event.ignore()
                return
        blocked_windows = self.window_coordinator.close_all()
        if blocked_windows:
            deferred_windows = tuple(
                window_id
                for window_id in blocked_windows
                if self.window_coordinator.is_close_deferred(window_id)
            )
            closes_automatically = len(deferred_windows) == len(blocked_windows)
            self._close_deferred_for_children = closes_automatically
            self._deferred_close_blockers = (
                set(deferred_windows) if closes_automatically else set()
            )
            self._deferred_child_close_retry_scheduled = False
            self._show_close_blocked_notice(
                blocked_windows,
                closes_automatically=closes_automatically,
            )
            event.ignore()
            return
        self._close_deferred_for_children = False
        self._deferred_close_blockers.clear()
        self._deferred_child_close_retry_scheduled = False
        forbidden_realtime_archive = (
            self.db_file
            if self.db_file and not self._is_realtime_session_database(self.db_file)
            else None
        )
        realtime_retained, _saved_path = self._resolve_realtime_session_before_discard(
            forbidden_destination=forbidden_realtime_archive
        )
        if not realtime_retained:
            self._close_deferred_for_realtime = False
            self._close_deferred_for_children = False
            self._deferred_close_blockers.clear()
            self._deferred_child_close_retry_scheduled = False
            self.workspace_notice_label.setText(
                "Temporary realtime data was kept. Save or discard it before closing Metroliza."
            )
            set_status_variant(self.workspace_notice_label, "warning")
            self.workspace_notice_label.setVisible(True)
            event.ignore()
            return
        self._close_deferred_for_realtime = False
        self._cleanup_realtime_session_db()
        self.ui_preferences.set("windows/main/geometry", self.saveGeometry())
        self._persist_navigation_index(self.navigation_list.currentRow())
        super().closeEvent(event)

    def _on_reports_shutdown_ready(self):
        if self._close_deferred_for_reports:
            self._close_deferred_for_reports = False
            QTimer.singleShot(0, self.close)

    def _show_close_blocked_notice(
        self,
        window_ids: tuple[str, ...],
        *,
        closes_automatically: bool = False,
    ) -> None:
        labels: list[str] = []
        for window_id in window_ids:
            widget = self.window_coordinator.get(window_id)
            title = widget.windowTitle().strip() if widget is not None else ""
            labels.append(title or window_id.replace("_", " ").title())
        joined_labels = ", ".join(labels)
        if closes_automatically:
            message = (
                f"Waiting for {joined_labels} to stop safely. "
                "Metroliza will close when active work finishes."
            )
        else:
            message = f"Close blocked by: {joined_labels}. Resolve unsaved work and try again."
        self.workspace_notice_label.setText(message)
        set_status_variant(self.workspace_notice_label, "warning")
        self.workspace_notice_label.setVisible(True)

    def _open_coordinated_window(
        self,
        window_id: str,
        factory,
        *,
        context_policy=WindowContextPolicy.KEEP,
        context_fields=frozenset(
            {WorkspaceField.SOURCE_DIRECTORY, WorkspaceField.DATABASE_FILE}
        ),
        context_updater=None,
    ):
        if window_id not in self.window_coordinator.registered_window_ids:
            self.window_coordinator.register_modeless(
                window_id,
                factory,
                context_policy=context_policy,
                context_fields=context_fields,
                context_updater=context_updater,
            )
        widget = self.window_coordinator.open_modeless(window_id)
        attribute = self._coordinated_window_attributes.get(window_id)
        if attribute:
            setattr(self, attribute, widget)
        return widget

    def _on_coordinated_window_closed(self, window_id: str) -> None:
        if window_id == "realtime_monitor":
            self._pending_realtime_database = None
        attribute = self._coordinated_window_attributes.get(window_id)
        if attribute:
            setattr(self, attribute, None)
        if window_id in self._deferred_close_blockers:
            self._deferred_close_blockers.discard(window_id)
            if (
                self._close_deferred_for_children
                and not self._deferred_close_blockers
                and not self._deferred_child_close_retry_scheduled
            ):
                self._deferred_child_close_retry_scheduled = True
                QTimer.singleShot(0, self._retry_deferred_child_close)

    def _retry_deferred_child_close(self) -> None:
        self._deferred_child_close_retry_scheduled = False
        if self._close_deferred_for_children and not self._deferred_close_blockers:
            self.close()

    def _on_coordinated_close_deferral_cancelled(self, window_id: str) -> None:
        if window_id not in self._deferred_close_blockers:
            return
        self._close_deferred_for_children = False
        self._deferred_close_blockers.clear()
        self._deferred_child_close_retry_scheduled = False
        self.workspace_notice_label.setText(
            "Metroliza close was cancelled because a child editor kept unsaved work."
        )
        set_status_variant(self.workspace_notice_label, "warning")
        self.workspace_notice_label.setVisible(True)

    def _update_realtime_window_context(self, widget, snapshot) -> None:
        database = snapshot.database_file
        if not database:
            return
        if not self._rebind_realtime_dialog(widget, database):
            self.workspace_notice_label.setText(
                "Realtime Monitor is still using its previous database. Stop it before "
                "switching monitor context, or resolve its temporary session data."
            )
            set_status_variant(self.workspace_notice_label, "danger")
        self.workspace_notice_label.setVisible(True)

    def launch_parsing_dialog(self):
        """Compatibility action: focus the one persistent Reports owner."""
        self._show_workspace_page("reports")
        self.reports_workspace.focus_primary_action()
        return self.reports_workspace

    def start_metadata_enrichment_from_parsing(self, db_file):
        if db_file != self.workspace_context.snapshot.database_file:
            self.workspace_notice_label.setText("Report completion belongs to a different database.")
            self.workspace_notice_label.show()
            return
        self.launch_metadata_enrichment()

    def launch_modifydb_dialog(self):
        if not self._report_database_action_allowed():
            return
        try:
            from metroliza.ui.modify_db import ModifyDB

            if self._is_qwidget_type(ModifyDB):
                self.modifydb_dialog = self._open_coordinated_window(
                    "modify_database",
                    lambda snapshot: ModifyDB(self, snapshot.database_file, modal=False),
                    context_policy=WindowContextPolicy.CLOSE,
                    context_fields=frozenset({WorkspaceField.DATABASE_FILE}),
                )
            elif not self.modifydb_dialog or not self.modifydb_dialog.isVisible():
                self.modifydb_dialog = ModifyDB(self, self.db_file)
                self._track_modeless_dialog("modifydb_dialog", self.modifydb_dialog)
                self.modifydb_dialog.show()

            self.modifydb_dialog.database_change_allowed = self._report_context_change_allowed
            self.modifydb_dialog.raise_()
            self.modifydb_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)

    def launch_export_dialog(self):
        if not self._report_database_action_allowed():
            return
        try:
            from metroliza.ui.export_dialog import ExportDialog

            if self._is_qwidget_type(ExportDialog):
                self.export_dialog = self._open_coordinated_window(
                    "export",
                    lambda snapshot: ExportDialog(self, snapshot.database_file),
                    context_policy=WindowContextPolicy.KEEP,
                    context_fields=frozenset({WorkspaceField.DATABASE_FILE}),
                )
            elif not self.export_dialog or not self.export_dialog.isVisible():
                self.export_dialog = ExportDialog(self, self.db_file)
                self._track_modeless_dialog("export_dialog", self.export_dialog)
                self.export_dialog.show()

            self.export_dialog.database_change_allowed = self._report_context_change_allowed
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
        if not self._report_database_action_allowed():
            return
        try:
            from metroliza.ui.industrial_data_dialog import IndustrialDataDialog

            if self._is_qwidget_type(IndustrialDataDialog):
                self.industrial_data_dialog = self._open_coordinated_window(
                    "industrial_data",
                    lambda snapshot: IndustrialDataDialog(self, snapshot.database_file),
                    context_policy=WindowContextPolicy.UPDATE,
                    context_fields=frozenset({WorkspaceField.DATABASE_FILE}),
                    context_updater=lambda dialog, snapshot: dialog.update_db_file(
                        snapshot.database_file
                    ),
                )
            elif not self.industrial_data_dialog or not self.industrial_data_dialog.isVisible():
                self.industrial_data_dialog = IndustrialDataDialog(self, self.db_file)
                self._track_modeless_dialog("industrial_data_dialog", self.industrial_data_dialog)
                self.industrial_data_dialog.show()

            self.industrial_data_dialog.database_change_allowed = self._report_context_change_allowed
            self.industrial_data_dialog.raise_()
            self.industrial_data_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)

    def launch_realtime_industrial_monitoring_dialog(self):
        if not self._report_database_action_allowed():
            return
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
                if not self._rebind_realtime_dialog(
                    self.realtime_monitoring_dialog,
                    dashboard_db_path,
                ):
                    self.statusBar().showMessage(
                        "Realtime Monitor kept its previous database. Stop active work or "
                        "resolve unsaved source changes before switching.",
                        5000,
                    )
                    return
            if self._is_qwidget_type(RealtimeIndustrialMonitoringDialog):
                def create_realtime(snapshot):
                    resolved_db = snapshot.database_file
                    if not resolved_db:
                        resolved_db, _temporary = self._realtime_dashboard_db_file()
                    dialog = RealtimeIndustrialMonitoringDialog(
                        self,
                        resolved_db,
                        temporary_session=self._is_realtime_session_database(resolved_db),
                    )
                    dialog.shutdown_complete.connect(
                        self._on_realtime_monitoring_shutdown_complete
                    )
                    self._connect_realtime_shutdown_cleanup_failure(dialog)
                    dialog.database_work_idle.connect(self._retry_pending_realtime_rebind)
                    return dialog

                self.realtime_monitoring_dialog = self._open_coordinated_window(
                    "realtime_monitor",
                    create_realtime,
                    context_policy=WindowContextPolicy.UPDATE,
                    context_fields=frozenset({WorkspaceField.DATABASE_FILE}),
                    context_updater=self._update_realtime_window_context,
                )
            elif self.realtime_monitoring_dialog is None or not self.realtime_monitoring_dialog.isVisible():
                self.realtime_monitoring_dialog = RealtimeIndustrialMonitoringDialog(
                    self,
                    dashboard_db_path,
                    temporary_session=using_session_db,
                )
                self._track_modeless_dialog("realtime_monitoring_dialog", self.realtime_monitoring_dialog)
                self.realtime_monitoring_dialog.shutdown_complete.connect(
                    self._on_realtime_monitoring_shutdown_complete
                )
                self._connect_realtime_shutdown_cleanup_failure(self.realtime_monitoring_dialog)
                self.realtime_monitoring_dialog.database_work_idle.connect(
                    self._retry_pending_realtime_rebind
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

    def _connect_realtime_shutdown_cleanup_failure(self, dialog) -> None:
        cleanup_failed = getattr(dialog, "shutdown_cleanup_failed", None)
        if cleanup_failed is not None:
            cleanup_failed.connect(self._on_realtime_shutdown_cleanup_failed)

    def _on_realtime_shutdown_cleanup_failed(self) -> None:
        if self.sender() is not self.realtime_monitoring_dialog:
            return
        retry_root_close = self._close_deferred_for_realtime
        self._close_deferred_for_realtime = False
        if not retry_root_close:
            return
        self._close_deferred_for_children = False
        self._deferred_close_blockers.clear()
        self._deferred_child_close_retry_scheduled = False
        self.workspace_notice_label.setText(
            "Private dashboard storage could not be removed. Close again to retry."
        )
        set_status_variant(self.workspace_notice_label, "warning")
        self.workspace_notice_label.setVisible(True)

    def _on_realtime_monitoring_shutdown_complete(self) -> None:
        retry_root_close = self._close_deferred_for_realtime
        self._close_deferred_for_realtime = False
        dialog = self.realtime_monitoring_dialog
        if dialog is not None:
            dialog.close()
        if retry_root_close:
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

    def _is_realtime_session_database(self, database: str | Path | None) -> bool:
        session_path = self._realtime_session_db_path
        if session_path is None or not database:
            return False
        try:
            return Path(database).expanduser().resolve() == session_path.expanduser().resolve()
        except OSError:
            return str(database) == str(session_path)

    def _realtime_session_disposable_counts(self) -> dict[str, int]:
        session_path = self._realtime_session_db_path
        if session_path is None or not session_path.is_file():
            return {}
        from metroliza.industrial.industrial_cache_target import disposable_cache_counts

        try:
            counts = disposable_cache_counts(session_path)
        except Exception:
            # An unreadable session may still contain recoverable operator data.
            # Require an explicit save/discard choice instead of deleting it.
            return {"unreadable_realtime_session": 1}
        if not counts.get("industrial_source_profiles"):
            return counts
        dialog = self.realtime_monitoring_dialog
        config_path = getattr(dialog, "config_path", None)
        if not config_path:
            return counts
        try:
            from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
            from metroliza.industrial.industrial_source_config import (
                load_source_profiles_from_config,
                source_profile_configuration_signature,
            )

            configured_signatures = {
                source_profile_configuration_signature(profile)
                for profile in load_source_profiles_from_config(config_path)
            }
            stored_profiles = IndustrialDataRepository(
                str(session_path)
            ).list_source_profiles(include_disabled=True)
        except Exception:
            return counts
        derived_profiles = sum(
            source_profile_configuration_signature(profile) in configured_signatures
            for profile in stored_profiles
        )
        counts["industrial_source_profiles"] = max(
            0,
            counts["industrial_source_profiles"] - derived_profiles,
        )
        return counts

    def _resolve_realtime_session_before_discard(
        self,
        *,
        forbidden_destination: str | Path | None = None,
    ) -> tuple[bool, Path | None]:
        counts = self._realtime_session_disposable_counts()
        persisted_rows = sum(counts.values())
        if persisted_rows < 1:
            return True, None
        choice = QMessageBox.question(
            self,
            "Temporary realtime data",
            f"The temporary realtime session contains {persisted_rows:,} persisted data row(s). "
            "Save a separate durable archive before removing the session?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False, None
        if choice == QMessageBox.StandardButton.Discard:
            return True, None

        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Save separate realtime session archive",
            "realtime_session.sqlite",
            "SQLite database (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if not selected:
            return False, None
        if not selected.lower().endswith((".db", ".sqlite", ".sqlite3")):
            selected = f"{selected}.sqlite"
        destination = Path(selected).expanduser().resolve()
        if forbidden_destination is not None:
            reserved_path = Path(forbidden_destination).expanduser().resolve()
            if destination == reserved_path:
                QMessageBox.warning(
                    self,
                    "Temporary realtime data",
                    "Choose a separate archive file. The active Metroliza database will not be "
                    "replaced or merged automatically.",
                )
                return False, None
        try:
            from metroliza.industrial.industrial_cache_target import (
                IndustrialCacheTarget,
                persist_temporary_industrial_cache,
            )

            persist_temporary_industrial_cache(
                IndustrialCacheTarget(
                    mode="temporary",
                    cache_db_file=str(self._realtime_session_db_path),
                    is_temporary=True,
                ),
                destination,
            )
        except Exception as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.warning(
                self,
                "Temporary realtime data",
                "The realtime session could not be saved. Its temporary data was kept.",
            )
            return False, None
        return True, destination

    def _rebind_realtime_dialog(self, dialog, database: str) -> bool:
        active_check = getattr(dialog, "is_monitoring_active", None)
        if callable(active_check) and active_check():
            self._pending_realtime_database = database
            dialog.rebind_database(database)
            return False
        moving_from_session = self._is_realtime_session_database(
            getattr(dialog, "db_file", None)
        )
        saved_path: Path | None = None
        if moving_from_session:
            approved, saved_path = self._resolve_realtime_session_before_discard(
                forbidden_destination=database
            )
            if not approved:
                return False
        if not dialog.rebind_database(database):
            return False
        self._pending_realtime_database = None
        if moving_from_session:
            self._cleanup_realtime_session_db()
            set_storage_mode = getattr(dialog, "set_temporary_session_storage", None)
            if callable(set_storage_mode):
                set_storage_mode(False)
        if saved_path is None:
            message = "Realtime Monitor moved to the active database."
        else:
            message = f"Realtime session saved to {saved_path}; monitor moved to the active database."
        self.workspace_notice_label.setText(message)
        set_status_variant(self.workspace_notice_label, "success")
        return True

    def _retry_pending_realtime_rebind(self) -> None:
        database = self._pending_realtime_database
        dialog = self.realtime_monitoring_dialog
        self._pending_realtime_database = None
        if not database or dialog is None:
            return
        if getattr(dialog, "db_file", None) == database:
            return
        if not self._rebind_realtime_dialog(dialog, database):
            self.workspace_notice_label.setText(
                "Realtime Monitor is still using its previous database. Resolve its temporary "
                "session data before switching monitor context."
            )
            set_status_variant(self.workspace_notice_label, "warning")
            self.workspace_notice_label.setVisible(True)

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

            if self._is_qwidget_type(ParserPluginWizardDialog):
                self.parser_plugin_wizard_dialog = self._open_coordinated_window(
                    "parser_profiles",
                    lambda _snapshot: ParserPluginWizardDialog(self),
                )
            elif not self.parser_plugin_wizard_dialog or not self.parser_plugin_wizard_dialog.isVisible():
                self.parser_plugin_wizard_dialog = ParserPluginWizardDialog(self)
                self._track_modeless_dialog(
                    "parser_plugin_wizard_dialog",
                    self.parser_plugin_wizard_dialog,
                )
                self.parser_plugin_wizard_dialog.show()

            self.parser_plugin_wizard_dialog.raise_()
            self.parser_plugin_wizard_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)

    def launch_characteristic_mapping_dialog(self):
        if not self._report_database_action_allowed():
            return
        try:
            from metroliza.ui.characteristic_mapping_dialog import CharacteristicMappingDialog

            characteristic_mapping_dialog = CharacteristicMappingDialog(self, self.db_file)
            characteristic_mapping_dialog.exec()
        except Exception as e:
            self.log_and_exit(e)

    def set_db_file(self, db_file):
        try:
            if not self._report_context_change_allowed():
                return False
            if self.industrial_data_dialog and self.industrial_data_dialog.isVisible():
                updated = self.industrial_data_dialog.update_db_file(db_file)
                if updated is False:
                    self.workspace_notice_label.setText(
                        "Database change cancelled because temporary industrial data was not resolved."
                    )
                    set_status_variant(self.workspace_notice_label, "warning")
                    self.workspace_notice_label.setVisible(True)
                    return False
            self.workspace_notice_label.setVisible(False)
            recovery_result = self._recover_abandoned_realtime_staging(db_file)
            self.workspace_context.set_database_file(db_file)
            realtime = self.realtime_monitoring_dialog
            if (
                realtime is not None
                and realtime is not self.window_coordinator.get("realtime_monitor")
                and realtime.isVisible()
                and getattr(realtime, "db_file", None) != db_file
            ):
                rebound = bool(
                    hasattr(realtime, "rebind_database")
                    and self._rebind_realtime_dialog(realtime, str(db_file or ""))
                )
                if not rebound:
                    self.workspace_notice_label.setText(
                        "Realtime Monitor is still using its previous database. Stop it before "
                        "switching monitor context, or resolve its temporary session data."
                    )
                    set_status_variant(self.workspace_notice_label, "danger")
                self.workspace_notice_label.setVisible(True)
            stale_workflows = self._workflows_using_previous_database(db_file)
            if stale_workflows:
                self.workspace_notice_label.setText(
                    f"{', '.join(stale_workflows)} remain on their previously selected database. "
                    "Finish or close them before starting work in the new context."
                )
                set_status_variant(self.workspace_notice_label, "warning")
                self.workspace_notice_label.setVisible(True)
            if recovery_result and recovery_result.get("runs_failed", 0):
                self.statusBar().showMessage(
                    "Recovered abandoned industrial sync staging: "
                    f"{recovery_result['runs_failed']} run(s), "
                    f"{recovery_result.get('rows_discarded', 0)} row(s) discarded.",
                    8000,
                )
            return True
        except Exception as e:
            self.log_and_exit(e)

    def _workflows_using_previous_database(self, database_file) -> tuple[str, ...]:
        labels = []
        for label, dialog in (
            ("Export", self.export_dialog),
            ("Database editor", self.modifydb_dialog),
        ):
            if dialog is None:
                continue
            try:
                visible = bool(dialog.isVisible())
            except (AttributeError, RuntimeError):
                visible = False
            dialog_database = getattr(dialog, "db_file", None)
            if visible and dialog_database and dialog_database != database_file:
                labels.append(label)
        return tuple(labels)

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
            if directory != self.directory and not self._report_context_change_allowed():
                return False
            self.workspace_context.set_source_directory(directory)
            return True
        except Exception as e:
            self.log_and_exit(e)

    def _report_context_change_allowed(self):
        if self._reports_workspace is None or self._reports_workspace.can_change_workspace():
            return True
        self.workspace_notice_label.setText("Finish or cancel the report operation before changing its source or database.")
        set_status_variant(self.workspace_notice_label, "warning")
        self.workspace_notice_label.show()
        return False

    def _report_database_action_allowed(self):
        if self._reports_workspace is None or self._reports_workspace.can_change_workspace():
            return True
        self.workspace_notice_label.setText("Finish or cancel the report operation before starting another database workflow.")
        set_status_variant(self.workspace_notice_label, "warning")
        self.workspace_notice_label.show()
        return False

    def _report_start_allowed(self):
        """Keep existing same-database windows safe without closing their work."""
        if getattr(self.export_dialog, "database_context_transition_active", False):
            self.statusBar().showMessage(
                "Report start was blocked during Export database selection.", 5000
            )
            return False
        if not self.db_file:
            return True
        blockers = []
        if self.is_metadata_enrichment_active():
            enrichment_database = getattr(self.metadata_enrichment_thread, "db_file", None)
            if not enrichment_database or Path(enrichment_database).resolve() == Path(self.db_file).resolve():
                blockers.append("metadata enrichment")
        blockers.extend(self._same_database_workflow_labels())
        if not blockers:
            return True
        self.workspace_notice_label.setText(
            f"Finish or close {', '.join(blockers)} before reviewing or importing reports in this database."
        )
        set_status_variant(self.workspace_notice_label, "warning")
        self.workspace_notice_label.show()
        return False

    def _same_database_workflow_labels(self):
        """Collect visible workflow owners of this report database or an unknown one."""
        blockers = []
        for label, dialog in (
            ("Export", self.export_dialog), ("Database editor", self.modifydb_dialog),
            ("Industrial Data", self.industrial_data_dialog),
            ("Realtime Monitor", self.realtime_monitoring_dialog),
        ):
            if dialog is None:
                continue
            try:
                if not dialog.isVisible():
                    continue
            except RuntimeError:
                continue
            databases = tuple(path for path in (
                getattr(dialog, "db_file", None), getattr(dialog, "report_db_file", None),
            ) if path)
            if not databases or any(Path(path).resolve() == Path(self.db_file).resolve() for path in databases):
                blockers.append(label)
        return blockers

    def _track_modeless_dialog(self, attribute: str, dialog) -> None:
        if hasattr(dialog, "setAttribute"):
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        destroyed = getattr(dialog, "destroyed", None)
        if destroyed is not None and hasattr(destroyed, "connect"):
            destroyed.connect(
                lambda _object=None, name=attribute, instance=dialog: self._clear_tracked_dialog(
                    name,
                    instance,
                )
            )

    @staticmethod
    def _is_qwidget_type(candidate) -> bool:
        try:
            return issubclass(candidate, QWidget)
        except TypeError:
            return False

    def _clear_tracked_dialog(self, attribute: str, dialog) -> None:
        if getattr(self, attribute, None) is dialog:
            setattr(self, attribute, None)

    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)

"""Modeless realtime industrial monitoring dialog."""

from __future__ import annotations

from pathlib import Path
import tempfile
from time import monotonic
from typing import Any

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from metroliza.industrial.anomaly.event_repository import AnomalyEventStatusConflictError
from metroliza.industrial.industrial_data_repository import (
    IndustrialDataRepository,
    IndustrialSourceProfile,
    looks_sensitive_key,
    redact_sensitive_text,
)
from metroliza.industrial.industrial_source_config import (
    default_industrial_source_config_path,
    import_source_profiles_to_repository,
)
from metroliza.industrial.realtime.monitor_config import (
    DEFAULT_AGGREGATION_METHODS,
    RealtimeMonitorConfig,
    RealtimeMonitorConfigRepository,
)
from metroliza.industrial.realtime.realtime_dashboard_html import write_realtime_dashboard_html
from metroliza.industrial.realtime.realtime_dashboard_service import RealtimeDashboardService
from metroliza.industrial.realtime.stream_config import (
    DEFAULT_CONTEXT_FIELDS,
    DEFAULT_SEGMENT_FIELDS,
    RealtimeStreamConfigError,
)
from metroliza.industrial.industrial_workers import (
    RealtimeDashboardWriterThread,
    RealtimeMonitorPollThread,
)
from metroliza.ui.industrial_source_profiles_dialog import IndustrialSourceProfilesDialog
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_dialog_button_roles,
    configure_table,
    configure_window_size,
    path_field,
    section_label,
    separator,
    set_button_role,
    set_status_variant,
    status_chip,
    update_path_field,
)


class RealtimeIndustrialMonitoringDialog(QDialog):
    """Configure and run live polling for one or more industrial source profiles."""

    shutdown_complete = pyqtSignal()
    monitor_stopped = pyqtSignal()
    database_work_idle = pyqtSignal()

    def __init__(
        self,
        parent=None,
        db_file: str | None = None,
        config_path: str | Path | None = None,
        temporary_session: bool = False,
    ):
        super().__init__(parent)
        self.db_file = str(db_file or "")
        self.temporary_session = bool(temporary_session)
        self.config_path = Path(config_path or default_industrial_source_config_path()).expanduser()
        self.repository = RealtimeMonitorConfigRepository(self.db_file)
        self.source_repository = IndustrialDataRepository(self.db_file)
        self.source_window: IndustrialSourceProfilesDialog | None = None
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_once)
        self.poll_thread: RealtimeMonitorPollThread | None = None
        self.dashboard_write_debounce_timer = QTimer(self)
        self.dashboard_write_debounce_timer.setSingleShot(True)
        self.dashboard_write_debounce_timer.setInterval(250)
        self.dashboard_write_debounce_timer.timeout.connect(self._start_dashboard_write)
        self.dashboard_thread: RealtimeDashboardWriterThread | None = None
        self._dashboard_write_pending = False
        self._dashboard_open_pending = False
        self._dashboard_open_after_current = False
        self._stop_requested = False
        self._closing = False
        self._shutdown_waiting = False
        self._shutdown_completion_emitted = False
        self._dashboard_temp_dir = tempfile.TemporaryDirectory(
            prefix="metroliza-realtime-dashboard-"
        )
        self.profiles: list[IndustrialSourceProfile] = []
        self.configs_by_profile_id: dict[int, RealtimeMonitorConfig] = {}
        self.active_configs: tuple[RealtimeMonitorConfig, ...] = ()
        self._next_poll_due_by_profile_id: dict[int, float] = {}
        self.last_poll_results: tuple[Any, ...] = ()
        self.last_dashboard_path: Path | None = None

        self.setWindowTitle("Real-time Industrial Monitoring")
        apply_metroliza_theme(self)
        configure_window_size(self, minimum=(900, 620), initial=(1120, 760))
        self._build_ui()
        self.reload_from_database()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.addWidget(section_label("Real-time industrial monitoring"), 1)
        self.monitor_state_label = status_chip("Monitor: stopped", "neutral")
        header_row.addWidget(self.monitor_state_label)
        layout.addLayout(header_row)

        self.status_label = status_chip("Ready", "neutral")
        layout.addWidget(self.status_label)
        self.storage_lifecycle_label = status_chip("", "neutral")
        layout.addWidget(self.storage_lifecycle_label)
        self.set_temporary_session_storage(self.temporary_session)
        subsystem_row = QHBoxLayout()
        self.config_readiness_label = status_chip("Setup: not checked", "neutral")
        self.poll_status_label = status_chip("Poll: not run", "neutral")
        self.dashboard_status_label = status_chip("Dashboard: not generated", "neutral")
        subsystem_row.addWidget(self.config_readiness_label, 1)
        subsystem_row.addWidget(self.poll_status_label, 1)
        subsystem_row.addWidget(self.dashboard_status_label, 1)
        layout.addLayout(subsystem_row)

        self.workflow_tabs = QTabWidget()
        self.workflow_tabs.setObjectName("realtimeWorkflowTabs")
        self.workflow_tabs.addTab(self._build_monitor_page(), "Monitor")
        self.workflow_tabs.addTab(self._build_setup_page(), "Setup")
        self.workflow_tabs.addTab(self._build_event_review_page(), "Event Review")
        self.workflow_tabs.currentChanged.connect(self._sync_default_action_for_tab)
        layout.addWidget(self.workflow_tabs, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        configure_dialog_button_roles(
            secondary=(
                self.start_button,
                self.poll_once_button,
                self.open_dashboard_button,
                self.save_button,
                self.apply_checked_button,
                self.refresh_events_button,
                self.acknowledge_event_button,
                self.resolve_event_button,
                self.false_positive_event_button,
            ),
            quiet=(self.close_button,),
            danger=(self.stop_button,),
        )
        close_row.addWidget(self.close_button)
        layout.addLayout(close_row)
        self._sync_running_state(False)
        self._sync_default_action_for_tab(0)

    def set_temporary_session_storage(self, temporary: bool) -> None:
        self.temporary_session = bool(temporary)
        if self.temporary_session:
            self.storage_lifecycle_label.setText(
                "Temporary session storage · samples, events, and monitor setup must be saved "
                "or explicitly discarded before this session is removed."
            )
            set_status_variant(self.storage_lifecycle_label, "warning")
        else:
            self.storage_lifecycle_label.setText(
                "Durable storage · realtime samples, events, and monitor setup are retained."
            )
            set_status_variant(self.storage_lifecycle_label, "success")

    def _sync_default_action_for_tab(self, index: int) -> None:
        candidates = (
            self.start_button,
            self.save_button,
            self.refresh_events_button,
        )
        selected = candidates[index] if 0 <= index < len(candidates) else None
        for button in candidates:
            set_button_role(button, "primary", default=button is selected)

    def _build_monitor_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addLayout(self._build_monitor_action_row())
        layout.addWidget(self._build_status_panel(), 2)
        layout.addWidget(self._build_diagnostics_panel(), 1)
        return page

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_source_panel())
        splitter.addWidget(self._build_config_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes((340, 680))
        content_layout.addWidget(splitter, 1)
        content_layout.addWidget(separator())
        content_layout.addLayout(self._build_setup_action_row())
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page

    def _build_source_panel(self) -> QWidget:
        panel = QGroupBox("Sources")
        layout = QVBoxLayout(panel)
        config_row = QHBoxLayout()
        self.source_config_path_field = path_field(str(self.config_path))
        self.browse_config_button = QPushButton("Browse")
        self.reload_config_button = QPushButton("Reload Config")
        self.edit_sources_button = QPushButton("Production Sources...")
        self.browse_config_button.clicked.connect(self.choose_source_config_path)
        self.reload_config_button.clicked.connect(self.reload_from_database)
        self.edit_sources_button.clicked.connect(self.open_source_profiles_dialog)
        config_row.addWidget(self.source_config_path_field, 1)
        config_row.addWidget(self.browse_config_button)
        config_row.addWidget(self.reload_config_button)
        layout.addWidget(QLabel("Production source config file"))
        layout.addLayout(config_row)
        layout.addWidget(self.edit_sources_button)
        self.source_list = QListWidget()
        self.source_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.source_list.currentItemChanged.connect(self._on_current_source_changed)
        self.source_list.itemChanged.connect(self._on_source_check_changed)
        layout.addWidget(self.source_list)
        self.source_summary_label = QLabel("No production sources in this database.")
        self.source_summary_label.setWordWrap(True)
        layout.addWidget(self.source_summary_label)
        source_actions = QHBoxLayout()
        self.select_all_sources_button = QPushButton("Select All")
        self.clear_sources_button = QPushButton("Clear")
        self.select_all_sources_button.clicked.connect(self.select_all_sources)
        self.clear_sources_button.clicked.connect(self.clear_selected_sources)
        source_actions.addWidget(self.select_all_sources_button)
        source_actions.addWidget(self.clear_sources_button)
        layout.addLayout(source_actions)
        self.reload_button = QPushButton("Reload")
        self.reload_button.clicked.connect(self.reload_from_database)
        layout.addWidget(self.reload_button)
        return panel

    def _build_config_panel(self) -> QWidget:
        panel = QGroupBox("Configuration")
        layout = QVBoxLayout(panel)
        form = QFormLayout()

        self.stream_key_edit = QLineEdit()
        self.cursor_column_edit = QLineEdit()
        self.event_time_column_edit = QLineEdit()
        self.record_key_column_edit = QLineEdit()
        self.signal_columns_edit = QPlainTextEdit()
        self.signal_columns_edit.setPlaceholderText("cycle_time=cycle_time_s\npressure=pressure_bar")
        self.signal_columns_edit.setMinimumHeight(96)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 86_400)
        self.interval_spin.setValue(60)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 86_400)
        self.timeout_spin.setValue(30)
        self.chunk_spin = QSpinBox()
        self.chunk_spin.setRange(1, 100_000)
        self.chunk_spin.setValue(500)
        self.max_catchup_spin = QSpinBox()
        self.max_catchup_spin.setRange(1, 500_000)
        self.max_catchup_spin.setValue(5_000)

        self.display_mode_combo = QComboBox()
        self.display_mode_combo.addItems(("raw", "aggregated"))
        self.aggregation_bucket_combo = QComboBox()
        self.aggregation_bucket_combo.addItems(("none", "hour", "day", "week", "month", "year"))
        self.aggregation_methods_edit = QLineEdit(", ".join(DEFAULT_AGGREGATION_METHODS))
        self.aggregation_groups_edit = QLineEdit()
        self.context_fields_edit = QLineEdit(", ".join(DEFAULT_CONTEXT_FIELDS))
        self.segment_fields_edit = QLineEdit(", ".join(DEFAULT_SEGMENT_FIELDS))
        self.detectors_edit = QLineEdit("spec_limits")

        form.addRow("Stream key", self.stream_key_edit)
        form.addRow("Cursor column", self.cursor_column_edit)
        form.addRow("Event time column", self.event_time_column_edit)
        form.addRow("Record key column", self.record_key_column_edit)
        form.addRow("Signal columns", self.signal_columns_edit)
        layout.addLayout(form)

        advanced_group = QGroupBox("Advanced polling, aggregation, and detectors")
        advanced_group.setCheckable(True)
        advanced_group.setChecked(False)
        advanced_form = QFormLayout(advanced_group)
        advanced_form.addRow("Polling interval seconds", self.interval_spin)
        advanced_form.addRow("Query timeout seconds", self.timeout_spin)
        advanced_form.addRow("Rows per fetch", self.chunk_spin)
        advanced_form.addRow("Max catchup rows", self.max_catchup_spin)
        advanced_form.addRow("Dashboard mode", self.display_mode_combo)
        advanced_form.addRow("Aggregation bucket", self.aggregation_bucket_combo)
        advanced_form.addRow("Aggregation methods", self.aggregation_methods_edit)
        advanced_form.addRow("Aggregation groups", self.aggregation_groups_edit)
        advanced_form.addRow("Context fields", self.context_fields_edit)
        advanced_form.addRow("Segment fields", self.segment_fields_edit)
        advanced_form.addRow("Detectors", self.detectors_edit)
        layout.addWidget(advanced_group)

        path_row = QHBoxLayout()
        self.dashboard_path_field = path_field("", empty_text="Default temp dashboard")
        self.choose_dashboard_button = QPushButton("Choose")
        self.choose_dashboard_button.clicked.connect(self.choose_dashboard_path)
        path_row.addWidget(QLabel("Dashboard file"))
        path_row.addWidget(self.dashboard_path_field, 1)
        path_row.addWidget(self.choose_dashboard_button)
        layout.addLayout(path_row)
        return panel

    def _build_setup_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.save_button = QPushButton("Save Current Source")
        self.apply_checked_button = QPushButton("Apply Current to Checked")
        self.save_button.clicked.connect(self.save_current_source_config)
        self.apply_checked_button.clicked.connect(self.apply_current_to_checked_configs)
        row.addWidget(self.save_button)
        row.addWidget(self.apply_checked_button)
        row.addStretch(1)
        return row

    def _build_monitor_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.start_button = QPushButton("Start Checked")
        self.poll_once_button = QPushButton("Poll Once")
        self.stop_button = QPushButton("Stop")
        self.open_dashboard_button = QPushButton("Open Dashboard")

        self.start_button.clicked.connect(self.start_monitoring)
        self.poll_once_button.clicked.connect(self.poll_once)
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.open_dashboard_button.clicked.connect(self.open_dashboard)

        for button in (
            self.start_button,
            self.poll_once_button,
            self.stop_button,
            self.open_dashboard_button,
        ):
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _build_status_panel(self) -> QWidget:
        panel = QGroupBox("Status")
        layout = QVBoxLayout(panel)
        self.status_table = QTableWidget(0, 11)
        self.status_table.setHorizontalHeaderLabels(
            (
                "Source",
                "Stream",
                "Status",
                "Stage",
                "Rows",
                "Samples",
                "Events",
                "Cursor",
                "Query",
                "Lag",
                "Error",
            )
        )
        configure_table(self.status_table, stretch_column=0, min_height=170)
        layout.addWidget(self.status_table)
        return panel

    def _build_diagnostics_panel(self) -> QWidget:
        panel = QGroupBox("Diagnostics")
        layout = QVBoxLayout(panel)
        self.diagnostics_text = QPlainTextEdit()
        self.diagnostics_text.setReadOnly(True)
        self.diagnostics_text.setMaximumBlockCount(400)
        layout.addWidget(self.diagnostics_text)
        return panel

    def _build_event_review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        intro = QLabel(
            "Review persisted anomaly events. Every operator action requires an operator name "
            "and a comment; Metroliza never automates hold, release, or scrap decisions."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.event_review_table = QTableWidget(0, 8)
        self.event_review_table.setHorizontalHeaderLabels(
            (
                "Time",
                "Source",
                "Signal",
                "Severity",
                "Value",
                "Detector",
                "Explanation",
                "Event ID",
            )
        )
        self.event_review_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.event_review_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.event_review_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.event_review_table.itemSelectionChanged.connect(self._sync_event_action_buttons)
        configure_table(self.event_review_table, stretch_column=6, min_height=220)
        layout.addWidget(self.event_review_table, 1)

        operator_row = QHBoxLayout()
        self.event_operator_edit = QLineEdit()
        self.event_operator_edit.setPlaceholderText("Operator name")
        self.event_comment_edit = QLineEdit()
        self.event_comment_edit.setPlaceholderText("Required review comment")
        operator_row.addWidget(QLabel("Operator"))
        operator_row.addWidget(self.event_operator_edit, 1)
        operator_row.addWidget(QLabel("Comment"))
        operator_row.addWidget(self.event_comment_edit, 2)
        layout.addLayout(operator_row)

        action_row = QHBoxLayout()
        self.refresh_events_button = QPushButton("Refresh events")
        self.acknowledge_event_button = QPushButton("Acknowledge")
        self.resolve_event_button = QPushButton("Resolve")
        self.false_positive_event_button = QPushButton("Mark false positive")
        self.refresh_events_button.clicked.connect(self.refresh_event_review)
        self.acknowledge_event_button.clicked.connect(
            lambda: self._apply_selected_event_action("acknowledge")
        )
        self.resolve_event_button.clicked.connect(
            lambda: self._apply_selected_event_action("resolve")
        )
        self.false_positive_event_button.clicked.connect(
            lambda: self._apply_selected_event_action("false_positive")
        )
        action_row.addWidget(self.refresh_events_button)
        action_row.addStretch(1)
        action_row.addWidget(self.acknowledge_event_button)
        action_row.addWidget(self.resolve_event_button)
        action_row.addWidget(self.false_positive_event_button)
        layout.addLayout(action_row)
        self.event_review_status_label = status_chip("Open events: not loaded", "neutral")
        layout.addWidget(self.event_review_status_label)
        self._sync_event_action_buttons()
        return page

    def refresh_event_review(self) -> None:
        try:
            events = RealtimeDashboardService(self.db_file).list_open_anomaly_events(limit=100)
        except Exception as exc:
            message = redact_sensitive_text(exc)
            self.event_review_status_label.setText(f"Could not load open events: {message}")
            set_status_variant(self.event_review_status_label, "danger")
            return

        self.event_review_table.setRowCount(len(events))
        for row, event in enumerate(events):
            values = (
                event.event_time,
                event.profile_name,
                event.signal_key,
                event.severity,
                f"{event.observed_value:g}",
                event.detector_key,
                event.explanation,
                str(event.id),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 7:
                    item.setData(Qt.ItemDataRole.UserRole, int(event.id))
                self.event_review_table.setItem(row, column, item)
        self.event_review_status_label.setText(f"Open events: {len(events)}")
        set_status_variant(
            self.event_review_status_label,
            "warning" if events else "success",
        )
        self._sync_event_action_buttons()

    def _selected_event_id(self) -> int | None:
        row = self.event_review_table.currentRow()
        if row < 0:
            return None
        item = self.event_review_table.item(row, 7)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _sync_event_action_buttons(self) -> None:
        selected = self._selected_event_id() is not None
        for button_name in (
            "acknowledge_event_button",
            "resolve_event_button",
            "false_positive_event_button",
        ):
            button = getattr(self, button_name, None)
            if button is not None:
                button.setEnabled(selected)

    def _apply_selected_event_action(self, action: str) -> None:
        event_id = self._selected_event_id()
        operator = self.event_operator_edit.text().strip()
        comment = self.event_comment_edit.text().strip()
        if event_id is None:
            self.event_review_status_label.setText("Select one event to review.")
            set_status_variant(self.event_review_status_label, "warning")
            return
        if not operator or not comment:
            self.event_review_status_label.setText(
                "Operator name and review comment are required."
            )
            set_status_variant(self.event_review_status_label, "warning")
            return
        service = RealtimeDashboardService(self.db_file)
        try:
            if action == "acknowledge":
                service.acknowledge_event(
                    event_id=event_id,
                    ack_by=operator,
                    comment=comment,
                    expected_status="open",
                )
                verb = "acknowledged"
            elif action == "resolve":
                service.resolve_event(
                    event_id=event_id,
                    resolved_by=operator,
                    comment=comment,
                    expected_status="open",
                )
                verb = "resolved"
            elif action == "false_positive":
                service.mark_event_false_positive(
                    event_id=event_id,
                    marked_by=operator,
                    comment=comment,
                    expected_status="open",
                )
                verb = "marked false positive"
            else:
                raise ValueError(f"Unsupported event action: {action}")
        except AnomalyEventStatusConflictError:
            self.refresh_event_review()
            self.event_review_status_label.setText(
                "This event was already reviewed elsewhere. The open-event list was refreshed."
            )
            set_status_variant(self.event_review_status_label, "warning")
            return
        except Exception as exc:
            message = redact_sensitive_text(exc)
            self.event_review_status_label.setText(f"Event review failed: {message}")
            set_status_variant(self.event_review_status_label, "danger")
            return

        self.event_comment_edit.clear()
        self.refresh_event_review()
        self.event_review_status_label.setText(f"Event {event_id} {verb} by {operator}.")
        set_status_variant(self.event_review_status_label, "success")

    def _load_database_state(self, source_repository, config_repository):
        source_repository.ensure_schema()
        config_repository.ensure_schema()
        config_path = Path(
            self.source_config_path_field.text() or self.config_path
        ).expanduser()
        imported = import_source_profiles_to_repository(config_path, source_repository)
        profiles = source_repository.list_source_profiles(include_disabled=True)
        configs = config_repository.list_configs()
        return config_path, imported, profiles, configs

    def _apply_loaded_database_state(self, state) -> None:
        config_path, imported, profiles, configs = state
        self.config_path = config_path
        self.profiles = profiles
        self.configs_by_profile_id = {config.source_profile_id: config for config in configs}
        self._populate_sources()
        if profiles:
            source_text = (
                f"Ready; imported {len(imported)} source(s) from YAML"
                if imported
                else "Ready"
            )
        else:
            source_text = "No industrial sources configured"
        self._set_config_status(source_text, "info")
        self.refresh_event_review()

    def _report_database_load_failure(self, exc: Exception) -> None:
        self._append_diagnostic(f"Database load failed; error_type={type(exc).__name__}")
        self._set_config_status(
            "Database load failed. The previous realtime context is still active.",
            "danger",
        )

    def reload_from_database(self) -> bool:
        try:
            state = self._load_database_state(self.source_repository, self.repository)
        except Exception as exc:
            self._report_database_load_failure(exc)
            return False
        self._apply_loaded_database_state(state)
        return True

    def rebind_database(self, db_file: str) -> bool:
        """Move an idle monitor to the active workspace database without stale context."""

        target = str(db_file or "").strip()
        if not target:
            return False
        if self.is_monitoring_active():
            self._set_monitor_status(
                "Monitor: stop active work before changing the workspace database",
                "warning",
            )
            return False
        if target == self.db_file:
            return True
        if not self._close_source_profiles_for_context_change(
            "changing the workspace database"
        ):
            return False

        candidate_repository = RealtimeMonitorConfigRepository(target)
        candidate_source_repository = IndustrialDataRepository(target)
        try:
            state = self._load_database_state(
                candidate_source_repository,
                candidate_repository,
            )
        except Exception as exc:
            self._report_database_load_failure(exc)
            return False

        self.db_file = target
        self.repository = candidate_repository
        self.source_repository = candidate_source_repository
        self.active_configs = ()
        self._next_poll_due_by_profile_id = {}
        self.last_poll_results = ()
        self.status_table.setRowCount(0)
        self._apply_loaded_database_state(state)
        self._set_monitor_status("Monitor: stopped", "neutral")
        self._set_status("Realtime monitor moved to the active workspace database.", "success")
        return True

    def choose_source_config_path(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Production source config",
            str(self.config_path),
            "YAML files (*.yaml *.yml);;All files (*)",
        )
        if not selected:
            return
        self.config_path = Path(selected).expanduser()
        update_path_field(self.source_config_path_field, str(self.config_path))
        self.reload_from_database()

    def open_source_profiles_dialog(self) -> None:
        if self.source_window is not None:
            try:
                if self.source_window.isVisible():
                    self.source_window.raise_()
                    self.source_window.activateWindow()
                    return
            except RuntimeError:
                self.source_window = None
        self.source_window = IndustrialSourceProfilesDialog(
            self,
            db_file=self.db_file,
            config_path=self.config_path,
        )
        self.source_window.finished.connect(self._handle_source_dialog_closed)
        self.source_window.show()
        self.source_window.raise_()
        self.source_window.activateWindow()

    def _close_source_profiles_for_context_change(self, action: str) -> bool:
        source_window = self.source_window
        if source_window is None:
            return True
        try:
            closed = source_window.close()
            still_visible = source_window.isVisible()
        except RuntimeError:
            self.source_window = None
            return True
        if not closed or still_visible:
            self._set_config_status(
                f"Save or discard Production line source changes before {action}.",
                "warning",
            )
            return False
        if self.source_window is source_window:
            self.config_path = source_window.config_path
            update_path_field(self.source_config_path_field, str(self.config_path))
            self.source_window = None
        return True

    def _handle_source_dialog_closed(self, _result: int) -> None:
        if self.source_window is not None:
            self.config_path = self.source_window.config_path
            update_path_field(self.source_config_path_field, str(self.config_path))
        self.source_window = None
        self.reload_from_database()

    def _populate_sources(self) -> None:
        self.source_list.blockSignals(True)
        self.source_list.clear()
        first_enabled_item: QListWidgetItem | None = None
        first_item: QListWidgetItem | None = None
        for profile in self.profiles:
            item = QListWidgetItem(_profile_label(profile))
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            if profile.is_enabled:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            else:
                item.setFlags(
                    (item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    & ~Qt.ItemFlag.ItemIsEnabled
                )
            saved = self.configs_by_profile_id.get(profile.id)
            checked = profile.is_enabled and (
                bool(saved and saved.enabled) or (len(self.profiles) == 1 and saved is None)
            )
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.source_list.addItem(item)
            first_item = first_item or item
            if profile.is_enabled and first_enabled_item is None:
                first_enabled_item = item
        if first_enabled_item is not None:
            self.source_list.setCurrentItem(first_enabled_item)
        elif first_item is not None:
            self.source_list.setCurrentItem(first_item)
        self.source_list.blockSignals(False)
        self._load_current_source_config()
        self._update_source_summary()

    def select_all_sources(self) -> None:
        for index in range(self.source_list.count()):
            item = self.source_list.item(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Checked)
        self._on_source_check_changed(None)

    def clear_selected_sources(self) -> None:
        for index in range(self.source_list.count()):
            item = self.source_list.item(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._on_source_check_changed(None)

    def _on_current_source_changed(self, _current, _previous) -> None:
        self._load_current_source_config()

    def _on_source_check_changed(self, _item) -> None:
        if not self.poll_timer.isActive():
            self.active_configs = ()
        self._update_source_summary()
        self._sync_buttons()

    def _load_current_source_config(self) -> None:
        profile = self.current_profile()
        if profile is None or not profile.is_enabled:
            self._apply_config_to_form(None)
            self._set_config_status("Setup: select an enabled source", "warning")
            self._sync_buttons()
            return
        saved_config = self.configs_by_profile_id.get(profile.id)
        self._apply_config_to_form(saved_config or _default_config(profile))
        if saved_config is None:
            self._set_config_status(
                f"Setup: {profile.profile_name} is using unsaved suggested values",
                "warning",
            )
        else:
            self._set_config_status(f"Setup: {profile.profile_name} saved", "success")
        self._sync_buttons()

    def current_profile(self) -> IndustrialSourceProfile | None:
        item = self.source_list.currentItem()
        if item is None:
            return None
        profile_id = item.data(Qt.ItemDataRole.UserRole)
        return next((profile for profile in self.profiles if profile.id == profile_id), None)

    def selected_profiles(self) -> tuple[IndustrialSourceProfile, ...]:
        selected_ids: set[int] = set()
        for index in range(self.source_list.count()):
            item = self.source_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                selected_ids.add(int(item.data(Qt.ItemDataRole.UserRole)))
        return tuple(
            profile for profile in self.profiles if profile.id in selected_ids and profile.is_enabled
        )

    def _update_source_summary(self) -> None:
        enabled_count = sum(1 for profile in self.profiles if profile.is_enabled)
        disabled_count = len(self.profiles) - enabled_count
        selected_count = len(self.selected_profiles())
        if not self.profiles:
            text = "No production sources in this database."
        elif enabled_count == 0:
            text = f"{disabled_count} disabled source(s)."
        elif disabled_count:
            text = f"{selected_count} of {enabled_count} enabled source(s) selected; {disabled_count} disabled."
        else:
            text = f"{selected_count} of {enabled_count} source(s) selected."
        self.source_summary_label.setText(text)

    def _apply_config_to_form(self, config: RealtimeMonitorConfig | None) -> None:
        if config is None:
            for edit in (
                self.stream_key_edit,
                self.cursor_column_edit,
                self.event_time_column_edit,
                self.record_key_column_edit,
            ):
                edit.clear()
            self.signal_columns_edit.clear()
            update_path_field(self.dashboard_path_field, "", empty_text="Default temp dashboard")
            return

        self.stream_key_edit.setText(config.stream_key)
        self.cursor_column_edit.setText(config.cursor_column)
        self.event_time_column_edit.setText(config.event_time_column)
        self.record_key_column_edit.setText(config.record_key_column)
        self.signal_columns_edit.setPlainText(_format_signal_columns(config.signal_columns))
        self.interval_spin.setValue(int(config.polling_interval_seconds))
        self.timeout_spin.setValue(int(config.timeout_seconds))
        self.chunk_spin.setValue(int(config.chunk_size))
        self.max_catchup_spin.setValue(int(config.max_catchup_rows_per_cycle))
        self.display_mode_combo.setCurrentText(config.display_mode)
        self.aggregation_bucket_combo.setCurrentText(config.aggregation_time_bucket)
        self.aggregation_methods_edit.setText(", ".join(config.aggregation_methods))
        self.aggregation_groups_edit.setText(", ".join(config.aggregation_group_fields))
        self.context_fields_edit.setText(", ".join(config.context_fields))
        self.segment_fields_edit.setText(", ".join(config.segment_fields))
        self.detectors_edit.setText(", ".join(config.detectors))
        update_path_field(
            self.dashboard_path_field,
            config.dashboard_output_path or "",
            empty_text="Default temp dashboard",
        )

    def _config_from_form(self, profile: IndustrialSourceProfile) -> RealtimeMonitorConfig:
        current_profile = self.current_profile()
        stream_key = self.stream_key_edit.text().strip()
        if not stream_key or (
            current_profile is not None
            and len(self.selected_profiles()) > 1
            and stream_key == current_profile.profile_key
        ):
            stream_key = profile.profile_key
        signal_columns = _parse_signal_columns(self.signal_columns_edit.toPlainText())
        return RealtimeMonitorConfig(
            source_profile_id=profile.id,
            stream_key=stream_key,
            enabled=True,
            cursor_column=self.cursor_column_edit.text().strip(),
            event_time_column=self.event_time_column_edit.text().strip(),
            record_key_column=self.record_key_column_edit.text().strip(),
            signal_keys=tuple(signal_columns.keys()),
            signal_columns=signal_columns,
            polling_interval_seconds=float(self.interval_spin.value()),
            timeout_seconds=float(self.timeout_spin.value()),
            chunk_size=int(self.chunk_spin.value()),
            max_catchup_rows_per_cycle=int(self.max_catchup_spin.value()),
            display_mode=self.display_mode_combo.currentText(),
            aggregation_time_bucket=self.aggregation_bucket_combo.currentText(),
            aggregation_methods=_parse_csv_text(self.aggregation_methods_edit.text()),
            aggregation_group_fields=_parse_csv_text(self.aggregation_groups_edit.text()),
            context_fields=_parse_csv_text(self.context_fields_edit.text()),
            segment_fields=_parse_csv_text(self.segment_fields_edit.text()),
            detectors=_parse_csv_text(self.detectors_edit.text()) or ("spec_limits",),
            dashboard_output_path=_field_path(self.dashboard_path_field.text()),
        ).validated()

    def save_current_source_config(self) -> tuple[RealtimeMonitorConfig, ...]:
        profile = self.current_profile()
        if profile is None or not profile.is_enabled:
            self._set_config_status("Select an enabled source to save.", "warning")
            return ()
        try:
            config = self.repository.upsert_config(self._config_from_form(profile))
            self.configs_by_profile_id[profile.id] = config
            self.active_configs = ()
            self._set_config_status(
                f"Saved realtime monitor config for {profile.profile_name}.",
                "success",
            )
            self._sync_buttons()
            return (config,)
        except Exception as exc:
            message = redact_sensitive_text(exc)
            self._set_config_status(f"Config save failed: {message}", "danger")
            QMessageBox.warning(self, "Realtime monitor config", message)
            return ()

    def apply_current_to_checked_configs(self) -> tuple[RealtimeMonitorConfig, ...]:
        profiles = self.selected_profiles()
        if not profiles:
            self._set_config_status("Select at least one source to monitor.", "warning")
            return ()
        saved: list[RealtimeMonitorConfig] = []
        try:
            for profile in profiles:
                config = self.repository.upsert_config(self._config_from_form(profile))
                self.configs_by_profile_id[profile.id] = config
                saved.append(config)
            self.active_configs = ()
            self._set_config_status(
                f"Applied current settings to {len(saved)} checked source(s).",
                "success",
            )
            self._sync_buttons()
            return tuple(saved)
        except Exception as exc:
            message = redact_sensitive_text(exc)
            self._set_config_status(f"Config save failed: {message}", "danger")
            QMessageBox.warning(self, "Realtime monitor config", message)
            return ()

    def save_selected_configs(self) -> tuple[RealtimeMonitorConfig, ...]:
        """Compatibility wrapper for older callers that saved all checked sources."""

        return self.apply_current_to_checked_configs()

    def _configs_for_checked_sources(self, *, save_current: bool) -> tuple[RealtimeMonitorConfig, ...]:
        profiles = self.selected_profiles()
        if not profiles:
            self._set_config_status("Select at least one source to monitor.", "warning")
            return ()
        current_profile = self.current_profile()
        missing_profiles = [
            profile
            for profile in profiles
            if profile.id not in self.configs_by_profile_id
            and not (
                save_current
                and current_profile is not None
                and profile.id == current_profile.id
            )
        ]
        if missing_profiles:
            names = ", ".join(profile.profile_name for profile in missing_profiles)
            message = f"Save realtime setup before monitoring: {names}."
            self._set_config_status(message, "warning")
            QMessageBox.warning(self, "Realtime setup required", message)
            self.workflow_tabs.setCurrentIndex(1)
            return ()
        configs: list[RealtimeMonitorConfig] = []
        try:
            for profile in profiles:
                config = self.configs_by_profile_id.get(profile.id)
                if save_current and current_profile is not None and profile.id == current_profile.id:
                    config = self.repository.upsert_config(self._config_from_form(profile))
                    self.configs_by_profile_id[profile.id] = config
                elif config is None:
                    # Missing configs are rejected by preflight above. Never persist
                    # suggested defaults as an implicit live-monitoring decision.
                    continue
                configs.append(config)
        except Exception as exc:
            message = redact_sensitive_text(exc)
            self._set_config_status(f"Config save failed: {message}", "danger")
            QMessageBox.warning(self, "Realtime monitor config", message)
            return ()
        return tuple(configs)

    def start_monitoring(self) -> None:
        configs = self._configs_for_checked_sources(save_current=True)
        if not configs:
            return
        self.active_configs = configs
        self._stop_requested = False
        now = monotonic()
        self._next_poll_due_by_profile_id = {
            config.source_profile_id: now for config in configs
        }
        interval_ms = max(1_000, int(min(config.polling_interval_seconds for config in configs) * 1_000))
        self.poll_timer.start(interval_ms)
        self._sync_running_state(True)
        self._set_monitor_status(
            f"Monitor: running {len(configs)} checked source(s)",
            "success",
        )
        self.workflow_tabs.setCurrentIndex(0)
        self.poll_once()

    def stop_monitoring(self, _checked: bool = False, *, wait_for_thread: bool = False) -> None:
        self.poll_timer.stop()
        poll_owned = self.poll_thread is not None
        poll_running = poll_owned and self.poll_thread.isRunning()
        if poll_owned:
            self._stop_requested = True
        if poll_running:
            self.poll_thread.cancel()
            if wait_for_thread:
                self.poll_thread.wait(3_000)
        self.active_configs = ()
        self._next_poll_due_by_profile_id = {}
        if self.poll_thread is not None:
            self._sync_running_state(True)
            self.stop_button.setEnabled(False)
            self._set_monitor_status("Monitor: stopping after the active poll", "warning")
            self._set_status("Stopping realtime monitoring...", "warning")
            return
        self._stop_requested = False
        self._sync_running_state(False)
        self._set_monitor_status("Monitor: stopped", "neutral")
        self._set_status("Stopped", "neutral")
        self.monitor_stopped.emit()
        self._emit_database_work_idle_if_ready()

    def poll_once(self) -> None:
        timer_active = self.poll_timer.isActive()
        configs = self._due_active_configs() if timer_active else ()
        if timer_active and not configs:
            return
        if not configs:
            configs = self._configs_for_checked_sources(save_current=True)
            if not configs:
                return
        if self.poll_thread is not None:
            self._append_diagnostic("Poll skipped because a previous cycle is still finishing.")
            return
        if timer_active:
            self._advance_poll_due_times(configs)
        poll_thread = RealtimeMonitorPollThread(db_file=self.db_file, configs=configs)
        self.poll_thread = poll_thread
        poll_thread.update_label.connect(lambda text: self._set_poll_status(text, "info"))
        poll_thread.result_ready.connect(self._on_poll_results)
        poll_thread.error_occurred.connect(self._on_poll_error)
        poll_thread.cancelled.connect(lambda text: self._set_poll_status(text, "warning"))
        poll_thread.finished.connect(lambda: self._clear_poll_thread(poll_thread))
        self._set_poll_status("Polling realtime industrial sources...", "info")
        poll_thread.start()

    def _due_active_configs(self) -> tuple[RealtimeMonitorConfig, ...]:
        now = monotonic()
        return tuple(
            config
            for config in self.active_configs
            if self._next_poll_due_by_profile_id.get(config.source_profile_id, now) <= now
        )

    def _advance_poll_due_times(self, configs: tuple[RealtimeMonitorConfig, ...]) -> None:
        now = monotonic()
        for config in configs:
            interval = max(1.0, float(config.polling_interval_seconds or 1.0))
            self._next_poll_due_by_profile_id[config.source_profile_id] = now + interval

    def _on_poll_results(self, results: tuple[Any, ...]) -> None:
        if self._closing:
            return
        self.last_poll_results = tuple(results or ())
        self._populate_result_table(self.last_poll_results)
        failed = [result for result in self.last_poll_results if _result_has_actionable_failure(result)]
        inserted = sum(int(getattr(result, "samples_inserted", 0) or 0) for result in self.last_poll_results)
        event_count = sum(
            int(getattr(result, "detector_events_created", 0) or 0) for result in self.last_poll_results
        )
        self._append_diagnostic(_format_results_for_diagnostics(self.last_poll_results))
        self._schedule_dashboard_write(open_after=False)
        self.refresh_event_review()
        if failed:
            self._set_poll_status(_format_failed_status(failed), "warning")
        else:
            self._set_poll_status(
                f"Polling completed: {inserted} sample(s), {event_count} event(s).",
                "success",
            )

    def _on_poll_error(self, message: str) -> None:
        if self._closing:
            return
        self._set_poll_status(f"Polling failed: {message}", "danger")
        self._append_diagnostic(message)

    def _clear_poll_thread(self, finished_thread=None) -> None:
        if finished_thread is not None and finished_thread is not self.poll_thread:
            return
        self.poll_thread = None
        delete_later = getattr(finished_thread, "deleteLater", None)
        if callable(delete_later):
            delete_later()
        if self._closing:
            self._complete_deferred_shutdown()
            return
        if self._stop_requested:
            self._stop_requested = False
            self._sync_running_state(False)
            self._set_monitor_status("Monitor: stopped", "neutral")
            self._set_status("Stopped", "neutral")
            self.monitor_stopped.emit()
            self._emit_database_work_idle_if_ready()
            return
        self._sync_buttons()
        self._emit_database_work_idle_if_ready()

    def _populate_result_table(self, results: tuple[Any, ...]) -> None:
        self.status_table.setRowCount(len(results))
        profile_names = {profile.id: profile.profile_name for profile in self.profiles}
        for row, result in enumerate(results):
            values = (
                profile_names.get(getattr(result, "source_profile_id", None), "Unknown source"),
                getattr(result, "stream_key", ""),
                _result_status(result),
                _result_stage(result),
                str(getattr(result, "rows_fetched", 0)),
                str(getattr(result, "samples_inserted", 0)),
                str(getattr(result, "detector_events_created", 0)),
                _result_cursor(result),
                _result_query_reference(result),
                _format_lag(getattr(result, "lag_seconds", None)),
                _result_error(result),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column not in {0, 10}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.status_table.setItem(row, column, item)

    def choose_dashboard_path(self) -> None:
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Realtime monitoring dashboard",
            str(self._default_dashboard_path()),
            "HTML files (*.html);;All files (*)",
        )
        if selected:
            update_path_field(self.dashboard_path_field, selected, empty_text="Default temp dashboard")

    def open_dashboard(self) -> None:
        self._schedule_dashboard_write(open_after=True)

    def _schedule_dashboard_write(self, *, open_after: bool) -> None:
        if self._closing:
            return
        self._dashboard_write_pending = True
        self._dashboard_open_pending = self._dashboard_open_pending or open_after
        if self.dashboard_thread is not None:
            if open_after:
                self._set_dashboard_status(
                    "Dashboard refresh queued; current write is finishing.",
                    "info",
                )
            return
        if open_after:
            self._start_dashboard_write()
        else:
            self.dashboard_write_debounce_timer.start()

    def _start_dashboard_write(self) -> None:
        if self._closing or not self._dashboard_write_pending:
            return
        if self.dashboard_thread is not None:
            return
        self.dashboard_write_debounce_timer.stop()
        output_path = Path(_field_path(self.dashboard_path_field.text()) or self._default_dashboard_path())
        self._dashboard_write_pending = False
        self._dashboard_open_after_current = self._dashboard_open_pending
        self._dashboard_open_pending = False
        dashboard_thread = RealtimeDashboardWriterThread(
            db_file=self.db_file,
            output_file=str(output_path),
        )
        self.dashboard_thread = dashboard_thread
        dashboard_thread.result_ready.connect(self._on_dashboard_written)
        dashboard_thread.error_occurred.connect(self._on_dashboard_write_error)
        dashboard_thread.finished.connect(
            lambda: self._on_dashboard_writer_finished(dashboard_thread)
        )
        if self._dashboard_open_after_current:
            self._set_dashboard_status("Preparing realtime dashboard...", "info")
        dashboard_thread.start()

    def _on_dashboard_written(self, path: object) -> None:
        if self._closing:
            return
        self.last_dashboard_path = Path(path)
        if self._dashboard_open_after_current:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_dashboard_path)))
            self._set_dashboard_status(
                f"Dashboard opened: {self.last_dashboard_path}",
                "success",
            )
        else:
            self._set_dashboard_status(
                f"Dashboard refreshed: {self.last_dashboard_path}",
                "success",
            )

    def _on_dashboard_write_error(self, message: str) -> None:
        if self._closing:
            return
        self._append_diagnostic(f"Dashboard write failed: {message}")
        self._set_dashboard_status(f"Dashboard write failed: {message}", "warning")

    def _on_dashboard_writer_finished(self, finished_thread=None) -> None:
        if finished_thread is not None and finished_thread is not self.dashboard_thread:
            return
        self.dashboard_thread = None
        delete_later = getattr(finished_thread, "deleteLater", None)
        if callable(delete_later):
            delete_later()
        self._dashboard_open_after_current = False
        if self._closing:
            self._complete_deferred_shutdown()
            return
        if self._dashboard_write_pending:
            if self._dashboard_open_pending:
                self._start_dashboard_write()
            else:
                self.dashboard_write_debounce_timer.start()
        self._emit_database_work_idle_if_ready()

    def write_dashboard(self, *, open_after: bool = False) -> Path | None:
        try:
            output_path = Path(_field_path(self.dashboard_path_field.text()) or self._default_dashboard_path())
            output_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot = RealtimeDashboardService(self.db_file).dashboard_snapshot()
            self.last_dashboard_path = write_realtime_dashboard_html(snapshot, output_path)
            if open_after:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_dashboard_path)))
            return self.last_dashboard_path
        except Exception as exc:
            self._append_diagnostic(f"Dashboard write failed: {exc}")
            self._set_dashboard_status(f"Dashboard write failed: {exc}", "warning")
            return None

    def _default_dashboard_path(self) -> Path:
        if self._dashboard_temp_dir is None:
            raise RuntimeError("Realtime dashboard session has already been closed")
        output_dir = Path(self._dashboard_temp_dir.name)
        return output_dir / "realtime_industrial_monitoring.html"

    def _sync_running_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.poll_once_button.setEnabled(not running)
        self.reload_button.setEnabled(not running)
        self.reload_config_button.setEnabled(not running)
        self.browse_config_button.setEnabled(not running)
        self.edit_sources_button.setEnabled(not running)
        self.source_list.setEnabled(not running)
        self.monitor_state_label.setText("Monitor: running" if running else "Monitor: stopped")
        set_status_variant(self.monitor_state_label, "success" if running else "neutral")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has_sources = bool(self.selected_profiles())
        current = self.current_profile()
        current_is_enabled = bool(current and current.is_enabled)
        poll_thread_owned = self.poll_thread is not None
        running = self.poll_timer.isActive() or poll_thread_owned or self._stop_requested
        has_enabled_sources = any(profile.is_enabled for profile in self.profiles)
        selected_profiles = self.selected_profiles()
        selected_are_configured = bool(selected_profiles) and all(
            profile.id in self.configs_by_profile_id for profile in selected_profiles
        )
        self.save_button.setEnabled(current_is_enabled and not running)
        self.apply_checked_button.setEnabled(has_sources and current_is_enabled and not running)
        self.start_button.setEnabled(selected_are_configured and not running)
        self.poll_once_button.setEnabled(selected_are_configured and not running)
        self.stop_button.setEnabled(running and not self._stop_requested)
        self.select_all_sources_button.setEnabled(has_enabled_sources and not running)
        self.clear_sources_button.setEnabled(has_sources and not running)
        has_dashboard_context = bool(self.last_poll_results or self.configs_by_profile_id or has_sources)
        self.open_dashboard_button.setEnabled(has_dashboard_context)

    def _set_status(self, text: str, variant: str) -> None:
        self.status_label.setText(text)
        set_status_variant(self.status_label, variant)

    def _set_config_status(self, text: str, variant: str) -> None:
        self.config_readiness_label.setText(text)
        set_status_variant(self.config_readiness_label, variant)
        self._set_status(text, variant)

    def _set_monitor_status(self, text: str, variant: str) -> None:
        self.monitor_state_label.setText(text)
        set_status_variant(self.monitor_state_label, variant)

    def _set_poll_status(self, text: str, variant: str) -> None:
        self.poll_status_label.setText(text)
        set_status_variant(self.poll_status_label, variant)
        self._set_status(text, variant)

    def _set_dashboard_status(self, text: str, variant: str) -> None:
        self.dashboard_status_label.setText(text)
        set_status_variant(self.dashboard_status_label, variant)
        self._set_status(text, variant)

    def _append_diagnostic(self, text: str) -> None:
        if not str(text or "").strip():
            return
        if not self.diagnostics_text.document().isEmpty():
            self.diagnostics_text.appendPlainText("")
        self.diagnostics_text.appendPlainText(str(text))
        cursor = self.diagnostics_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.diagnostics_text.setTextCursor(cursor)
        self.diagnostics_text.ensureCursorVisible()

    def request_shutdown(self) -> bool:
        """Request worker cancellation and report whether database use has stopped."""

        if not self._close_source_profiles_for_context_change("closing realtime monitoring"):
            return False
        self._closing = True
        self.dashboard_write_debounce_timer.stop()
        self._dashboard_write_pending = False
        self._dashboard_open_pending = False
        self.poll_timer.stop()
        self.active_configs = ()
        self._next_poll_due_by_profile_id = {}
        if self.poll_thread is not None and self.poll_thread.isRunning():
            self.poll_thread.cancel()
        if self._workers_own_context():
            self._shutdown_waiting = True
            self._set_monitor_status("Monitor: stopping", "warning")
            self._set_status("Stopping realtime monitoring...", "warning")
            return False
        self._cleanup_dashboard_session()
        return True

    def is_close_deferred(self) -> bool:
        """Return whether shutdown was accepted and is waiting only on owned workers."""

        return bool(self._closing and self._shutdown_waiting)

    def is_monitoring_active(self) -> bool:
        """Return whether queued or active work prevents a safe database rebind."""

        return (
            self.poll_timer.isActive()
            or self._stop_requested
            or self._workers_own_context()
            or self.dashboard_write_debounce_timer.isActive()
            or self._dashboard_write_pending
        )

    def _emit_database_work_idle_if_ready(self) -> None:
        if not self._closing and not self.is_monitoring_active():
            self.database_work_idle.emit()

    def _workers_own_context(self) -> bool:
        """Return whether queued terminal callbacks still own the bound database."""

        return self.poll_thread is not None or self.dashboard_thread is not None

    def _complete_deferred_shutdown(self) -> None:
        if not self._closing or self._workers_own_context():
            return
        self._cleanup_dashboard_session()
        if self._shutdown_waiting and not self._shutdown_completion_emitted:
            self._shutdown_completion_emitted = True
            self.shutdown_complete.emit()
            QTimer.singleShot(0, self.close)

    def _cleanup_dashboard_session(self) -> None:
        temp_dir = self._dashboard_temp_dir
        self._dashboard_temp_dir = None
        if temp_dir is not None:
            temp_dir.cleanup()

    def closeEvent(self, event) -> None:
        if not self.request_shutdown():
            event.ignore()
            return
        super().closeEvent(event)


def _profile_label(profile: IndustrialSourceProfile) -> str:
    disabled = "" if profile.is_enabled else " (disabled)"
    return f"{profile.profile_name} [{profile.source_db_alias}]{disabled}"


def _default_config(profile: IndustrialSourceProfile) -> RealtimeMonitorConfig:
    cursor = profile.default_pagination_column or "id"
    event_time = profile.timestamp_column or cursor
    metric_columns = _default_metric_columns(profile, cursor=cursor, event_time=event_time)
    return RealtimeMonitorConfig(
        source_profile_id=profile.id,
        stream_key=profile.profile_key,
        cursor_column=cursor,
        event_time_column=event_time,
        record_key_column=cursor,
        signal_keys=tuple(metric_columns.keys()),
        signal_columns=metric_columns,
    )


def _default_metric_columns(
    profile: IndustrialSourceProfile,
    *,
    cursor: str,
    event_time: str,
) -> dict[str, str]:
    ignored = {
        cursor,
        event_time,
        "id",
        "event_id",
        "record_id",
        "source_record_key",
        "source_primary_key",
        "reference",
        "part_number",
        "revision",
        "station",
        "line",
        "work_order",
        "batch_lot",
        "operator_name",
        "process_status",
    }
    columns = [column for column in profile.allowed_columns if column and column not in ignored]
    if not columns:
        columns = ["value"]
    return {column: column for column in columns[:3]}


def _format_signal_columns(signal_columns: dict[str, str] | Any) -> str:
    return "\n".join(f"{signal_key}={column}" for signal_key, column in dict(signal_columns).items())


def _parse_signal_columns(value: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    tokens = [token.strip() for line in str(value or "").splitlines() for token in line.split(",")]
    for token in tokens:
        if not token:
            continue
        if "=" in token:
            key, column = token.split("=", 1)
        else:
            key = column = token
        key = key.strip()
        column = column.strip()
        if key and column:
            mapping[key] = column
    if not mapping:
        raise RealtimeStreamConfigError("Configure at least one realtime signal column.")
    return mapping


def _parse_csv_text(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(token.strip() for token in str(value or "").split(",") if token.strip()))


def _field_path(value: str) -> str | None:
    text = str(value or "").strip()
    if not text or text == "Default temp dashboard":
        return None
    return text


def _format_lag(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return str(value)


def _result_stage(result: Any) -> str:
    diagnostics = _safe_result_diagnostics(result)
    stage = diagnostics.get("stage") or diagnostics.get("failure_stage")
    if not stage and _detector_consumer_failed(result):
        stage = "detector_consumer"
    return redact_sensitive_text(stage, max_len=80) if stage else ""


def _result_status(result: Any) -> str:
    status = getattr(result, "status", "") or ""
    if status != "failed" and _detector_consumer_failed(result):
        return "completed_with_warnings"
    return str(status)


def _detector_consumer_failed(result: Any) -> bool:
    return str(getattr(result, "detector_consumer_status", "") or "").lower() == "failed"


def _result_has_actionable_failure(result: Any) -> bool:
    return str(getattr(result, "status", "") or "").lower() == "failed" or _detector_consumer_failed(result)


def _result_cursor(result: Any) -> str:
    diagnostics = _safe_result_diagnostics(result)
    cursor = getattr(result, "cursor_value", None) or diagnostics.get("cursor_value")
    return redact_sensitive_text(cursor, max_len=120) if cursor not in (None, "") else ""


def _result_query_reference(result: Any) -> str:
    diagnostics = _safe_result_diagnostics(result)
    query_summary = diagnostics.get("query_summary")
    if query_summary:
        return redact_sensitive_text(query_summary, max_len=120)
    sql_hash = diagnostics.get("sql_hash")
    if sql_hash:
        return f"hash={str(sql_hash)[:12]}"
    summary = diagnostics.get("summary")
    if isinstance(summary, dict):
        nested_hash = summary.get("sql_hash")
        if nested_hash:
            return f"hash={str(nested_hash)[:12]}"
        stream_key = summary.get("stream_key")
        limit = summary.get("limit")
        if stream_key and limit is not None:
            return redact_sensitive_text(f"stream={stream_key}, limit={limit}", max_len=120)
    return ""


def _result_error(result: Any) -> str:
    diagnostics = _safe_result_diagnostics(result)
    error = (
        getattr(result, "error", None)
        or diagnostics.get("error")
        or getattr(result, "detector_consumer_error", None)
    )
    return redact_sensitive_text(error, max_len=180) if error else ""


def _format_failed_status(failed: list[Any]) -> str:
    first = failed[0]
    stream = redact_sensitive_text(getattr(first, "stream_key", "") or "stream", max_len=60)
    stage = _result_stage(first) or "failed"
    error = _result_error(first)
    prefix = f"Polling completed with {len(failed)} failed stream(s): {stream} {stage}"
    if error:
        return f"{prefix} - {error}"
    rows = getattr(first, "rows_fetched", None)
    cursor = _result_cursor(first)
    detail_parts = []
    if rows is not None:
        detail_parts.append(f"rows={rows}")
    if cursor:
        detail_parts.append(f"cursor={cursor}")
    if detail_parts:
        return f"{prefix} ({', '.join(detail_parts)})"
    return prefix


def _safe_result_diagnostics(result: Any) -> dict[str, Any]:
    return _safe_diagnostics_mapping(getattr(result, "diagnostics", {}) or {})


def _safe_diagnostics_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        try:
            value = dict(value or {})
        except (TypeError, ValueError):
            return {}
    safe: dict[str, Any] = {}
    for key, nested in value.items():
        key_text = str(key)
        safe_value = _safe_diagnostic_value(key_text, nested)
        if safe_value is _SKIP_DIAGNOSTIC:
            continue
        safe[key_text] = safe_value
    return safe


_SKIP_DIAGNOSTIC = object()


def _safe_diagnostic_value(key: str, value: Any) -> Any:
    key_text = str(key)
    if _is_raw_sql_diagnostic_key(key_text):
        return _SKIP_DIAGNOSTIC
    if looks_sensitive_key(key_text) and key_text not in {"credentials_source"}:
        return "<redacted>"
    if isinstance(value, dict):
        return _safe_diagnostics_mapping(value)
    if isinstance(value, list):
        return tuple(_safe_diagnostic_value("", item) for item in value)
    if isinstance(value, tuple):
        return tuple(_safe_diagnostic_value("", item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value, max_len=None)
    return value


def _is_raw_sql_diagnostic_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return normalized in {"sql", "sql_text", "raw_sql", "query", "query_sql", "sql_query", "parameters"}


def _format_results_for_diagnostics(results: tuple[Any, ...]) -> str:
    lines: list[str] = []
    for result in results:
        safe_diagnostics = _safe_result_diagnostics(result)
        lines.append(
            " | ".join(
                (
                    f"stream={getattr(result, 'stream_key', '')}",
                    f"status={_result_status(result)}",
                    f"stage={_result_stage(result)}",
                    f"rows={getattr(result, 'rows_fetched', 0)}",
                    f"cursor={_result_cursor(result)}",
                    f"query={_result_query_reference(result)}",
                    f"error={_result_error(result)}",
                    f"samples={getattr(result, 'samples_inserted', 0)}",
                    f"events={getattr(result, 'detector_events_created', 0)}",
                    f"diagnostics={safe_diagnostics}",
                )
            )
        )
    return "\n".join(lines)

"""Oznak production-line access check and reference-scoped sync dialog."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from metroliza.industrial.industrial_data_repository import (
    IndustrialDataRepository,
    IndustrialSourceProfile,
    redact_sensitive_text,
)
from metroliza.industrial.industrial_credentials import (
    default_industrial_credential_path,
    forget_industrial_credentials,
    load_industrial_credentials,
    save_industrial_credentials,
)
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.industrial_filter_dialog import IndustrialFilterDialog
from metroliza.industrial.industrial_source_config import (
    IndustrialSourceConfigError,
    default_industrial_source_config_path,
    load_source_profiles_from_config,
)
from metroliza.industrial.industrial_workflow_state import (
    INDUSTRIAL_FILTER_FIELDS,
    INDUSTRIAL_QUERY_FILTER_OPERATOR_CHOICES,
    IndustrialFetchState,
    IndustrialFilterState,
    IndustrialQueryFilter,
    format_industrial_query_filters,
    parse_industrial_query_filter_lines,
    parse_reference_values,
    require_identifier,
)
from metroliza.industrial.industrial_workers import (
    IndustrialLinkRefreshThread,
    IndustrialOznakAccessCheckThread,
    IndustrialOznakSyncThread,
)
from metroliza.reports.db import sqlite_connection_scope
from metroliza.reports.report_schema import ensure_report_schema
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_window_size,
    section_label,
    set_status_variant,
    status_chip,
)


_REPORT_DB_FILE_UNSET = object()
DEFAULT_SQL_RECIPE_DIR = Path.home() / ".metroliza" / "industrial_sql_recipes"


@dataclass(frozen=True)
class _OznakOperation:
    profile: IndustrialSourceProfile
    username: str
    password: str
    fetch_state: IndustrialFetchState | None
    test_only: bool
    access_only: bool
    pending_credential_save: tuple[str, str, str] | None


class IndustrialSqlQueryDialog(QDialog):
    """Large SQL editor and preview surface for production data fetches."""

    def __init__(self, parent: "IndustrialSyncDialog"):
        super().__init__(parent)
        self.parent_dialog = parent
        self._syncing = False
        self.setWindowTitle("Industrial SQL query")
        configure_window_size(self, minimum=(760, 560), initial=(960, 720))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        layout.addWidget(section_label("SQL editor"))
        self.query_edit = QPlainTextEdit()
        self.query_edit.setMinimumHeight(220)
        self.query_edit.setPlaceholderText(parent.sql_query_edit.placeholderText())
        layout.addWidget(self.query_edit, 2)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.open_button = QPushButton("Open recipe...")
        self.save_button = QPushButton("Save recipe...")
        self.preview_limit_spin = QSpinBox()
        self.preview_limit_spin.setRange(1, 500)
        self.preview_button = QPushButton("Preview SQL")
        self.close_button = QPushButton("Close")
        actions.addWidget(self.open_button)
        actions.addWidget(self.save_button)
        actions.addStretch(1)
        actions.addWidget(section_label("Preview rows"))
        actions.addWidget(self.preview_limit_spin)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

        self.status_label = status_chip("SQL preview: not checked", "neutral")
        layout.addWidget(self.status_label)
        self.preview_table = QTableWidget(0, 0)
        layout.addWidget(self.preview_table, 3)

        self.query_edit.textChanged.connect(self._push_query_to_parent)
        self.preview_limit_spin.valueChanged.connect(self._push_limit_to_parent)
        self.open_button.clicked.connect(parent.open_sql_recipe)
        self.save_button.clicked.connect(parent.save_sql_recipe)
        self.preview_button.clicked.connect(self._preview_sql)
        self.close_button.clicked.connect(self.close)

        self.sync_from_parent()
        apply_metroliza_theme(self)

    def sync_from_parent(self) -> None:
        self._syncing = True
        try:
            text = self.parent_dialog.sql_query_edit.toPlainText()
            if self.query_edit.toPlainText() != text:
                self.query_edit.setPlainText(text)
            self.preview_limit_spin.setValue(self.parent_dialog.sql_preview_limit_spin.value())
            self.status_label.setText(self.parent_dialog.sql_status_label.text())
        finally:
            self._syncing = False

    def sync_status_from_parent(self) -> None:
        self.status_label.setText(self.parent_dialog.sql_status_label.text())

    def set_preview_records(self, records: Any) -> None:
        _populate_preview_table(self.preview_table, records)

    def _push_query_to_parent(self) -> None:
        if self._syncing:
            return
        text = self.query_edit.toPlainText()
        if self.parent_dialog.sql_query_edit.toPlainText() != text:
            self.parent_dialog.sql_query_edit.setPlainText(text)

    def _push_limit_to_parent(self, value: int) -> None:
        if self._syncing:
            return
        self.parent_dialog.sql_preview_limit_spin.setValue(value)

    def _preview_sql(self) -> None:
        self._push_query_to_parent()
        self._push_limit_to_parent(self.preview_limit_spin.value())
        self.parent_dialog.preview_sql()


def _populate_preview_table(table: QTableWidget, records: Any) -> None:
    preview_rows: list[dict[str, Any]] = []
    for record in tuple(records or ()):
        if isinstance(record, dict) and isinstance(record.get("raw_record"), dict):
            preview_rows.append({str(key): value for key, value in record["raw_record"].items()})
        elif isinstance(record, dict):
            preview_rows.append({str(key): value for key, value in record.items()})
    columns: list[str] = []
    for row in preview_rows:
        for column in row:
            if column not in columns:
                columns.append(column)
    columns = columns[:50]
    table.clear()
    table.setRowCount(len(preview_rows))
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    for row_index, row in enumerate(preview_rows):
        for column_index, column in enumerate(columns):
            value = row.get(column)
            table.setItem(
                row_index,
                column_index,
                QTableWidgetItem("" if value is None else str(value)),
            )
    table.resizeColumnsToContents()


class IndustrialSyncDialog(QDialog):
    """Run production-line access checks and reference-scoped industrial syncs."""

    def __init__(
        self,
        parent=None,
        *,
        db_file: str | None = None,
        report_db_file: str | None | object = _REPORT_DB_FILE_UNSET,
        config_path: str | Path | None = None,
        access_only: bool | None = None,
        filter_state: IndustrialFilterState | None = None,
    ):
        super().__init__(parent)
        self.db_file = db_file
        self.report_db_file = db_file if report_db_file is _REPORT_DB_FILE_UNSET else report_db_file
        self.config_path = Path(config_path or default_industrial_source_config_path()).expanduser()
        self.access_only = bool(access_only) if access_only is not None else not bool(db_file)
        self.filter_state = filter_state or IndustrialFilterState()
        self.filter_window = None
        self.oznak_sync_thread = None
        self._pending_credential_save: tuple[str, str, str] | None = None
        self._can_forget_credentials = False
        self._loading_profiles = False
        self._sql_recipe_path: Path | None = None
        self._pending_sql_preview = False
        self._open_csv_summary_after_fetch = False
        self._batch_operations: list[_OznakOperation] = []
        self._batch_results: list[dict[str, Any]] = []
        self._active_operation: _OznakOperation | None = None
        self._active_batch_total = 0
        self.link_refresh_thread: IndustrialLinkRefreshThread | None = None
        self.sql_editor_window: IndustrialSqlQueryDialog | None = None
        self.setWindowTitle("Fetch industrial data")
        configure_window_size(self, minimum=(860, 520), initial=(940, 840))

        self.status_label = status_chip(
            "Select a production source and enter production database credentials.",
            "neutral",
        )
        self.profile_combo = QComboBox()
        self.source_check_list = QListWidget()
        self.source_check_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.source_check_list.setFixedHeight(52)
        self.source_check_list.itemChanged.connect(lambda _item: self._sync_action_buttons())
        self.select_all_sources_button = QPushButton("Select all")
        self.current_source_only_button = QPushButton("Current only")
        self.select_all_sources_button.clicked.connect(self.select_all_sources)
        self.current_source_only_button.clicked.connect(self.select_current_source_only)
        self.batch_use_current_credentials_checkbox = QCheckBox(
            "Use entered credentials for all checked sources"
        )
        self.batch_use_current_credentials_checkbox.setChecked(True)
        self.filter_status_label = status_chip(self.filter_state.summary(), "neutral")

        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.remember_credentials_checkbox = QCheckBox("Remember on this computer")
        self.credentials_location_label = status_chip(
            f"No saved credentials for this source. File store: {default_industrial_credential_path()}",
            "neutral",
        )
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 1_000_000)
        self.limit_spin.setValue(5000)
        self.fetch_all_checkbox = QCheckBox("Fetch all rows")
        self.fetch_all_checkbox.setToolTip(
            "Fetch every row visible to the configured source and filters after a warning confirmation."
        )
        self.fetch_all_checkbox.stateChanged.connect(lambda _state: self._sync_limit_controls())
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 3600)
        self.timeout_spin.setValue(30)

        self.username_edit.setPlaceholderText("production database username")
        self.password_edit.setPlaceholderText("local credential store or session password")

        self.mode_tabs = QTabWidget()
        self.mode_tabs.setFixedHeight(190)
        self.edit_filter_button = QPushButton("Edit filters...")
        self.reference_column_edit = QLineEdit(self.filter_state.reference_column or "reference")
        self.reference_column_edit.setPlaceholderText("reference")
        self.reference_values_edit = QPlainTextEdit()
        self.reference_values_edit.setFixedHeight(34)
        self.reference_values_edit.setPlaceholderText("Optional: REF1, REF2, REF3")
        self.additional_filters_edit = QPlainTextEdit()
        self.additional_filters_edit.setFixedHeight(40)
        self.additional_filters_edit.setPlaceholderText(
            "Optional: station = S1\nprocess_status IN OK, NOK"
        )
        self.filter_column_combo = QComboBox()
        for column, label in INDUSTRIAL_FILTER_FIELDS:
            self.filter_column_combo.addItem(f"{label} ({column})", column)
        self.filter_operator_combo = QComboBox()
        for operator in INDUSTRIAL_QUERY_FILTER_OPERATOR_CHOICES:
            self.filter_operator_combo.addItem(operator, operator)
        self.filter_value_edit = QLineEdit()
        self.filter_value_edit.setPlaceholderText("Value, or comma-separated values for IN")
        self.add_filter_button = QPushButton("Add filter")
        self.load_filter_references_button = QPushButton("Use report DB values")
        self.clear_inline_filters_button = QPushButton("Clear filters")
        self.apply_inline_filters_button = QPushButton("Apply filters")
        self.sql_query_edit = QPlainTextEdit()
        self.sql_query_edit.setFixedHeight(64)
        self.sql_query_edit.setPlaceholderText(
            "SELECT reference, station, line, status, process_timestamp\n"
            "FROM production_view\n"
            "WHERE station = 'S1'"
        )
        self.sql_preview_limit_spin = QSpinBox()
        self.sql_preview_limit_spin.setRange(1, 500)
        self.sql_preview_limit_spin.setValue(5)
        self.sql_status_label = status_chip("SQL preview: not checked", "neutral")
        self.sql_preview_table = QTableWidget(0, 0)
        self.sql_preview_table.setFixedHeight(64)
        self.open_sql_button = QPushButton("Open recipe...")
        self.save_sql_button = QPushButton("Save recipe...")
        self.preview_sql_button = QPushButton("Preview SQL")
        self.open_sql_editor_button = QPushButton("Open SQL editor...")
        self.test_connection_button = QPushButton("Check access")
        self.sync_now_button = QPushButton("Fetch to cache")
        self.fetch_csv_summary_button = QPushButton("Fetch to CSV Summary")
        self.cancel_sync_button = QPushButton("Cancel")
        self.forget_credentials_button = QPushButton("Forget saved credentials")
        self.close_button = QPushButton("Close")
        self.test_connection_button.setToolTip(
            "Reads up to one production row to verify credentials, table, columns, and query access. Nothing is saved."
        )
        self.sync_now_button.setToolTip(
            "Fetches rows matching the selected filters or LIMIT and saves them in the local industrial cache."
        )
        self.edit_filter_button.setToolTip(
            "Open the larger filter dialog. The visible guided fields are used for fetches."
        )
        self.reference_column_edit.setToolTip(
            "Production DB column used only when the Reference/ID values field is not empty."
        )
        self.reference_values_edit.setToolTip(
            "Optional restriction: only rows whose Reference/ID column matches these pasted values are fetched."
        )
        self.additional_filters_edit.setToolTip(
            "Optional simple server-side filters, one per line, combined with the Reference/ID restriction."
        )
        self.filter_column_combo.setToolTip("Select a production column for an additional filter.")
        self.filter_operator_combo.setToolTip("Select how the column should match the value.")
        self.filter_value_edit.setToolTip("Enter one value, or comma-separated values for IN filters.")
        self.add_filter_button.setToolTip("Append the selected filter to Additional server-side filters.")
        self.preview_sql_button.setToolTip(
            "Run the SQL query with the preview row limit. Preview never writes to the local cache."
        )
        self.open_sql_editor_button.setToolTip(
            "Open a larger SQL editor and preview table in a separate dialog."
        )
        self.fetch_csv_summary_button.setToolTip(
            "Fetch rows into the local cache, then open them in CSV Summary."
        )
        self.load_filter_references_button.setToolTip(
            "Paste distinct reference values from the open Metroliza report database."
        )
        self.clear_inline_filters_button.setToolTip("Clear guided fetch restrictions.")
        self.apply_inline_filters_button.setToolTip("Validate and apply the visible guided filters.")

        self.edit_filter_button.clicked.connect(self.open_filter_dialog)
        self.load_filter_references_button.clicked.connect(self.load_inline_database_references)
        self.clear_inline_filters_button.clicked.connect(self.clear_inline_filters)
        self.apply_inline_filters_button.clicked.connect(lambda: self._apply_inline_filter_state(show_errors=True))
        self.add_filter_button.clicked.connect(self.add_inline_filter_from_builder)
        self.filter_operator_combo.currentIndexChanged.connect(
            lambda _index: self._sync_filter_builder_value_state()
        )
        self.open_sql_button.clicked.connect(self.open_sql_recipe)
        self.save_sql_button.clicked.connect(self.save_sql_recipe)
        self.preview_sql_button.clicked.connect(self.preview_sql)
        self.open_sql_editor_button.clicked.connect(self.open_sql_editor)
        self.test_connection_button.clicked.connect(self.test_connection)
        self.sync_now_button.clicked.connect(self.sync_now)
        self.fetch_csv_summary_button.clicked.connect(self.fetch_to_csv_summary)
        self.cancel_sync_button.clicked.connect(self.cancel_sync)
        self.forget_credentials_button.clicked.connect(self.forget_saved_credentials)
        self.close_button.clicked.connect(self.reject)
        self.profile_combo.currentIndexChanged.connect(self._handle_profile_changed)
        self.mode_tabs.currentChanged.connect(lambda _index: self._sync_filter_status())
        self.cancel_sync_button.setEnabled(False)
        self.forget_credentials_button.setEnabled(False)

        self._build_layout()
        self._sync_access_only_visibility()
        self.reload_profiles()
        self._sync_filter_fields_from_state()
        self._sync_filter_status()
        if self.access_only:
            self.sync_now_button.setToolTip(
                "Fetching to cache requires an active local industrial cache."
            )
        apply_metroliza_theme(self)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("Industrial Data manual", "industrial_data")])
        layout.addWidget(section_label("Production database access and cache fetch"))
        layout.addWidget(self.status_label)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setSpacing(8)
        form.addRow("Current source / credentials", self.profile_combo)
        source_pick_row = QHBoxLayout()
        source_pick_row.setContentsMargins(0, 0, 0, 0)
        source_pick_row.setSpacing(8)
        source_pick_row.addWidget(self.source_check_list, 1)
        source_pick_actions = QVBoxLayout()
        source_pick_actions.setContentsMargins(0, 0, 0, 0)
        source_pick_actions.setSpacing(6)
        source_pick_actions.addWidget(self.select_all_sources_button)
        source_pick_actions.addWidget(self.current_source_only_button)
        source_pick_actions.addStretch(1)
        source_pick_row.addLayout(source_pick_actions)
        form.addRow("Production sources to fetch", source_pick_row)
        self.source_check_row_label = form.labelForField(source_pick_row)
        form.addRow("", self.batch_use_current_credentials_checkbox)
        self.batch_credentials_row_label = form.labelForField(
            self.batch_use_current_credentials_checkbox
        )
        form.addRow("Production DB username", self.username_edit)
        form.addRow("Production DB password", self.password_edit)
        form.addRow("", self.remember_credentials_checkbox)
        credentials_row = QHBoxLayout()
        credentials_row.setContentsMargins(0, 0, 0, 0)
        credentials_row.setSpacing(8)
        credentials_row.addWidget(self.credentials_location_label, 1)
        credentials_row.addWidget(self.forget_credentials_button)
        form.addRow("Saved credentials", credentials_row)
        form.addRow("Fetch row limit", self.limit_spin)
        self.limit_row_label = form.labelForField(self.limit_spin)
        form.addRow("", self.fetch_all_checkbox)
        self.fetch_all_row_label = form.labelForField(self.fetch_all_checkbox)
        form.addRow("Query timeout seconds", self.timeout_spin)
        layout.addLayout(form)

        guided_tab = QVBoxLayout()
        guided_tab.setContentsMargins(8, 8, 8, 8)
        guided_tab.setSpacing(8)
        guided_form = QFormLayout()
        guided_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        guided_form.setSpacing(8)
        guided_form.addRow("Reference/ID column", self.reference_column_edit)
        guided_form.addRow("Only fetch these Reference/ID values", self.reference_values_edit)
        filter_builder_row = QHBoxLayout()
        filter_builder_row.setContentsMargins(0, 0, 0, 0)
        filter_builder_row.setSpacing(8)
        filter_builder_row.addWidget(self.filter_column_combo, 2)
        filter_builder_row.addWidget(self.filter_operator_combo, 1)
        filter_builder_row.addWidget(self.filter_value_edit, 2)
        filter_builder_row.addWidget(self.add_filter_button)
        guided_form.addRow("Build filter", filter_builder_row)
        guided_form.addRow("Additional server-side filters", self.additional_filters_edit)
        guided_tab.addLayout(guided_form)
        filter_row = QGridLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setHorizontalSpacing(8)
        filter_row.addWidget(self.filter_status_label, 0, 0)
        filter_row.addWidget(self.load_filter_references_button, 0, 1)
        filter_row.addWidget(self.clear_inline_filters_button, 0, 2)
        filter_row.addWidget(self.apply_inline_filters_button, 0, 3)
        filter_row.addWidget(self.edit_filter_button, 0, 4)
        filter_row.setColumnStretch(0, 1)
        guided_tab.addLayout(filter_row)
        guided_holder = QWidget(self)
        guided_holder.setLayout(guided_tab)
        self.mode_tabs.addTab(guided_holder, "Guided filters")
        self._sync_filter_builder_value_state()

        sql_holder = QWidget(self)
        sql_tab = QVBoxLayout(sql_holder)
        sql_tab.setContentsMargins(8, 8, 8, 8)
        sql_tab.setSpacing(8)
        sql_tab.addWidget(self.sql_query_edit, 1)
        sql_actions = QHBoxLayout()
        sql_actions.setContentsMargins(0, 0, 0, 0)
        sql_actions.setSpacing(8)
        sql_actions.addWidget(self.open_sql_button)
        sql_actions.addWidget(self.save_sql_button)
        sql_actions.addWidget(self.open_sql_editor_button)
        sql_actions.addStretch(1)
        sql_actions.addWidget(section_label("Preview rows"))
        sql_actions.addWidget(self.sql_preview_limit_spin)
        sql_actions.addWidget(self.preview_sql_button)
        sql_tab.addLayout(sql_actions)
        sql_tab.addWidget(self.sql_status_label)
        sql_tab.addWidget(self.sql_preview_table, 1)
        self.mode_tabs.addTab(sql_holder, "SQL query")
        layout.addWidget(self.mode_tabs, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        actions.addWidget(self.test_connection_button)
        actions.addWidget(self.sync_now_button)
        actions.addWidget(self.fetch_csv_summary_button)
        actions.addWidget(self.cancel_sync_button)
        layout.addLayout(actions)

    def _sync_access_only_visibility(self) -> None:
        show_cache_write_controls = not self.access_only
        for widget in (
            self.source_check_list,
            self.select_all_sources_button,
            self.current_source_only_button,
            self.batch_use_current_credentials_checkbox,
            self.limit_spin,
            self.fetch_all_checkbox,
            self.filter_status_label,
            self.edit_filter_button,
            self.mode_tabs,
            self.sync_now_button,
            self.fetch_csv_summary_button,
        ):
            widget.setVisible(show_cache_write_controls)
        for label in (
            getattr(self, "limit_row_label", None),
            getattr(self, "fetch_all_row_label", None),
            getattr(self, "source_check_row_label", None),
            getattr(self, "batch_credentials_row_label", None),
        ):
            if label is not None:
                label.setVisible(show_cache_write_controls)
        if self.access_only:
            self.fetch_all_checkbox.setChecked(False)

    def reload_profiles(self) -> None:
        if self._loading_profiles:
            return
        self._loading_profiles = True
        self.profile_combo.clear()
        profiles: list[IndustrialSourceProfile]
        if self.access_only:
            try:
                profiles = load_source_profiles_from_config(self.config_path)
            except (IndustrialSourceConfigError, OSError) as exc:
                profiles = []
                self.status_label.setText(f"Could not load sources from config: {exc}")
                set_status_variant(self.status_label, "warning")
        elif not self.db_file:
            profiles = []
            self._set_ready_state(
                False,
                "Select or create a local industrial cache before fetching production rows.",
            )
        else:
            try:
                profiles = IndustrialDataRepository(self.db_file).list_source_profiles()
            except Exception as exc:
                profiles = []
                self.status_label.setText(f"Could not load sources: {exc}")
                set_status_variant(self.status_label, "warning")
        for profile in profiles:
            self.profile_combo.addItem(profile.profile_name, profile)
        self._populate_source_check_list(profiles)
        self._loading_profiles = False
        if profiles:
            if self.access_only:
                self._set_ready_state(
                    True,
                    "Access-only mode: Check access reads up to one row and never saves data. Select or create a local industrial cache to fetch rows.",
                )
            else:
                self._set_ready_state(
                    True,
                    "Production source selected. Check access with a one-row read or fetch selected rows into the cache.",
                )
            self._load_stored_credentials_for_current_profile()
        else:
            if self.access_only:
                self._set_ready_state(
                    False,
                    "Access-only mode: configure at least one production source before checking access.",
                )
            else:
                self._set_ready_state(False, "Create a production source before fetching rows.")
            self._update_credentials_location_label(None)

    def _populate_source_check_list(self, profiles: list[IndustrialSourceProfile]) -> None:
        self.source_check_list.blockSignals(True)
        self.source_check_list.clear()
        for index, profile in enumerate(profiles):
            item = QListWidgetItem(f"{profile.profile_name} [{profile.source_db_alias}]")
            item.setData(Qt.ItemDataRole.UserRole, profile.profile_key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if index == 0 else Qt.CheckState.Unchecked)
            self.source_check_list.addItem(item)
        self.source_check_list.blockSignals(False)

    def _set_ready_state(self, enabled: bool, message: str) -> None:
        self.status_label.setText(message)
        set_status_variant(self.status_label, "neutral" if enabled else "warning")
        self._sync_action_buttons()

    def current_profile(self) -> IndustrialSourceProfile | None:
        profile = self.profile_combo.currentData()
        return profile if isinstance(profile, IndustrialSourceProfile) else None

    def _handle_profile_changed(self, _index: int) -> None:
        self._load_stored_credentials_for_current_profile()
        self._ensure_checked_source_selection()
        self._sync_action_buttons()

    def select_all_sources(self) -> None:
        self.source_check_list.blockSignals(True)
        try:
            for index in range(self.source_check_list.count()):
                self.source_check_list.item(index).setCheckState(Qt.CheckState.Checked)
        finally:
            self.source_check_list.blockSignals(False)
        self._sync_action_buttons()

    def select_current_source_only(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        self.source_check_list.blockSignals(True)
        try:
            for index in range(self.source_check_list.count()):
                item = self.source_check_list.item(index)
                checked = item.data(Qt.ItemDataRole.UserRole) == profile.profile_key
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self.source_check_list.blockSignals(False)
        self._sync_action_buttons()

    def checked_profiles(self) -> tuple[IndustrialSourceProfile, ...]:
        profiles_by_key = {profile.profile_key: profile for profile in self._all_profiles()}
        checked: list[IndustrialSourceProfile] = []
        for index in range(self.source_check_list.count()):
            item = self.source_check_list.item(index)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            profile = profiles_by_key.get(str(item.data(Qt.ItemDataRole.UserRole)))
            if profile is not None:
                checked.append(profile)
        return tuple(checked)

    def _ensure_checked_source_selection(self) -> None:
        if self.access_only or self.checked_profiles():
            return
        self.select_current_source_only()

    def _all_profiles(self) -> tuple[IndustrialSourceProfile, ...]:
        profiles: list[IndustrialSourceProfile] = []
        for index in range(self.profile_combo.count()):
            profile = self.profile_combo.itemData(index)
            if isinstance(profile, IndustrialSourceProfile):
                profiles.append(profile)
        return tuple(profiles)

    def _load_stored_credentials_for_current_profile(self) -> None:
        profile = self.current_profile()
        if profile is None:
            self.username_edit.clear()
            self.password_edit.clear()
            self._update_credentials_location_label(None)
            return
        stored = load_industrial_credentials(profile.profile_key)
        self.username_edit.setText(stored.username)
        self.password_edit.setText(stored.password)
        self._update_credentials_location_label(stored)

    def _update_credentials_location_label(self, stored=None, *, saved_path: Path | None = None) -> None:
        profile = self.current_profile()
        default_path = default_industrial_credential_path()
        forget_enabled = False
        variant = "neutral"
        if profile is None:
            text = f"No production source selected. File store: {default_path}"
        elif saved_path is not None:
            text = f"Credentials saved in {saved_path}"
            forget_enabled = True
            variant = "success"
        elif stored is not None and getattr(stored, "source", "") == "environment":
            text = f"Credentials loaded from environment. File store: {default_path}"
            variant = "success"
        elif stored is not None and stored.has_values and stored.source:
            text = f"Credentials loaded from {stored.source}"
            forget_enabled = True
            variant = "success"
        else:
            text = f"No saved credentials for this source. File store: {default_path}"
        self.credentials_location_label.setText(text)
        set_status_variant(self.credentials_location_label, variant)
        self._can_forget_credentials = forget_enabled
        self.forget_credentials_button.setEnabled(
            forget_enabled and not self._is_oznak_operation_running()
        )

    def forget_saved_credentials(self) -> None:
        profile = self.current_profile()
        if profile is None:
            self._update_credentials_location_label(None)
            return
        try:
            credential_path = forget_industrial_credentials(profile.profile_key)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Industrial data credentials",
                f"Could not forget saved credentials: {redact_sensitive_text(exc)}",
            )
            return
        self.remember_credentials_checkbox.setChecked(False)
        self.username_edit.clear()
        self.password_edit.clear()
        self._update_credentials_location_label(None)
        self.status_label.setText(f"Saved credentials forgotten from {credential_path}")
        set_status_variant(self.status_label, "neutral")

    def _profile_for_current_filter(
        self,
        profile: IndustrialSourceProfile | None = None,
    ) -> IndustrialSourceProfile:
        profile = profile or self.current_profile()
        if profile is None:
            raise ValueError("Create or select a production source before fetching rows.")
        if not profile.allowed_columns:
            return profile
        required_columns: list[str] = []
        if self.filter_state.references:
            required_columns.append(self.filter_state.reference_column)
        required_columns.extend(filter_state.column for filter_state in self.filter_state.query_filters)
        missing_columns = [
            column
            for column in required_columns
            if column and column not in profile.allowed_columns
        ]
        if not missing_columns:
            return profile
        return replace(profile, allowed_columns=(*profile.allowed_columns, *tuple(dict.fromkeys(missing_columns))))

    def _read_credentials(self) -> tuple[str, str]:
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username:
            raise ValueError("Enter the production database username for this session.")
        if not password:
            raise ValueError("Enter the production database password for this session.")
        return username, password

    def get_industrial_filter_state(self) -> IndustrialFilterState:
        return self.filter_state

    def set_industrial_filter_state(self, state: IndustrialFilterState) -> None:
        self.filter_state = state
        self._sync_filter_fields_from_state()
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_sync_filter_state"):
            parent.set_sync_filter_state(state)
        self._sync_filter_status()

    def _sync_filter_fields_from_state(self) -> None:
        if not hasattr(self, "reference_column_edit"):
            return
        self.reference_column_edit.setText(self.filter_state.reference_column or "reference")
        self.reference_values_edit.setPlainText("\n".join(self.filter_state.references))
        self.additional_filters_edit.setPlainText(
            format_industrial_query_filters(self.filter_state.query_filters)
        )

    def _inline_filter_state(self) -> IndustrialFilterState:
        state = IndustrialFilterState(
            reference_column=self.reference_column_edit.text().strip() or "reference",
            references=parse_reference_values(self.reference_values_edit.toPlainText()),
            query_filters=parse_industrial_query_filter_lines(self.additional_filters_edit.toPlainText()),
        )
        require_identifier("Reference/ID column", state.reference_column)
        return state

    def _apply_inline_filter_state(self, *, show_errors: bool) -> bool:
        try:
            state = self._inline_filter_state()
        except ValueError as exc:
            if show_errors:
                QMessageBox.warning(self, "Industrial guided filters", str(exc))
            return False
        self.filter_state = state
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_sync_filter_state"):
            parent.set_sync_filter_state(state)
        self._sync_filter_status()
        return True

    def load_inline_database_references(self) -> None:
        if not self.report_db_file:
            QMessageBox.warning(
                self,
                "Industrial guided filters",
                "Select a Metroliza report database first.",
            )
            return
        try:
            with sqlite_connection_scope(self.report_db_file) as conn:
                ensure_report_schema(self.report_db_file, connection=conn)
                rows = conn.execute(
                    """
                    SELECT DISTINCT TRIM(reference)
                    FROM report_metadata
                    WHERE TRIM(COALESCE(reference, '')) <> ''
                    ORDER BY TRIM(reference) COLLATE NOCASE
                    """
                ).fetchall()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Industrial guided filters",
                f"Could not read references from the selected Metroliza report database: {exc}",
            )
            return

        references = [str(row[0]).strip() for row in rows if str(row[0]).strip()]
        self.reference_values_edit.setPlainText("\n".join(references))
        self._apply_inline_filter_state(show_errors=False)
        self.filter_status_label.setText(
            f"Only fetching {len(references)} Reference/ID value(s) from report DB."
        )

    def clear_inline_filters(self) -> None:
        self.reference_values_edit.clear()
        self.additional_filters_edit.clear()
        self._apply_inline_filter_state(show_errors=False)

    def _sync_filter_builder_value_state(self) -> None:
        if not hasattr(self, "filter_operator_combo"):
            return
        operator = str(self.filter_operator_combo.currentData() or "").upper()
        value_required = operator not in {"IS NULL", "IS NOT NULL"}
        self.filter_value_edit.setEnabled(value_required)
        if value_required:
            self.filter_value_edit.setPlaceholderText(
                "Value, or comma-separated values for IN"
                if operator in {"IN", "NOT IN"}
                else "Value"
            )
        else:
            self.filter_value_edit.clear()
            self.filter_value_edit.setPlaceholderText("No value required")

    def add_inline_filter_from_builder(self) -> None:
        column = str(self.filter_column_combo.currentData() or "").strip()
        operator = str(self.filter_operator_combo.currentData() or "").strip().upper()
        value_text = self.filter_value_edit.text().strip()
        values: tuple[str, ...]
        if operator in {"IS NULL", "IS NOT NULL"}:
            values = ()
        elif operator in {"IN", "NOT IN"}:
            values = parse_reference_values(value_text)
        else:
            values = (value_text,) if value_text else ()
        try:
            filter_state = IndustrialQueryFilter(
                column=column,
                operator=operator,
                values=values,
            ).validated()
        except ValueError as exc:
            QMessageBox.warning(self, "Industrial guided filters", str(exc))
            return

        current_text = self.additional_filters_edit.toPlainText().strip()
        filter_line = format_industrial_query_filters((filter_state,))
        self.additional_filters_edit.setPlainText(
            f"{current_text}\n{filter_line}" if current_text else filter_line
        )
        self.filter_value_edit.clear()
        self._apply_inline_filter_state(show_errors=False)

    def _sync_filter_status(self) -> None:
        self.filter_status_label.setText(self.filter_state.summary())
        idle_variant = "neutral" if self.access_only else "warning"
        set_status_variant(
            self.filter_status_label,
            "success" if self.filter_state.is_applied else idle_variant,
        )
        self._sync_action_buttons()

    def open_filter_dialog(self) -> None:
        self.filter_window = IndustrialFilterDialog(
            self,
            db_file=self.report_db_file,
            state=self.filter_state,
        )
        self.filter_window.exec()

    def test_connection(self) -> None:
        self._open_csv_summary_after_fetch = False
        self._start_oznak_operation(test_only=True)

    def sync_now(self) -> None:
        self._open_csv_summary_after_fetch = False
        self._start_oznak_operation(test_only=False)

    def fetch_to_csv_summary(self) -> None:
        self._open_csv_summary_after_fetch = True
        self._start_oznak_operation(test_only=False)

    def preview_sql(self) -> None:
        self.mode_tabs.setCurrentIndex(1)
        self._open_csv_summary_after_fetch = False
        self._start_oznak_operation(test_only=True)

    def open_sql_editor(self) -> None:
        if self.sql_editor_window is None:
            self.sql_editor_window = IndustrialSqlQueryDialog(self)
            self.sql_editor_window.finished.connect(lambda _result: self._clear_sql_editor_window())
        else:
            self.sql_editor_window.sync_from_parent()
        self.sql_editor_window.show()
        self.sql_editor_window.raise_()
        self.sql_editor_window.activateWindow()

    def _clear_sql_editor_window(self) -> None:
        self.sql_editor_window = None

    def _sync_sql_editor_from_parent(self) -> None:
        if self.sql_editor_window is not None:
            self.sql_editor_window.sync_from_parent()

    def _sync_sql_editor_status(self) -> None:
        if self.sql_editor_window is not None:
            self.sql_editor_window.sync_status_from_parent()

    def open_sql_recipe(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open SQL recipe",
            str(self._sql_recipe_path or DEFAULT_SQL_RECIPE_DIR),
            "SQL files (*.sql);;All files (*)",
        )
        if not filename:
            return
        try:
            text = Path(filename).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "SQL recipe", f"Could not open SQL recipe: {exc}")
            return
        self._sql_recipe_path = Path(filename)
        self.sql_query_edit.setPlainText(text)
        self.sql_status_label.setText(f"SQL recipe loaded: {self._sql_recipe_path.name}")
        set_status_variant(self.sql_status_label, "success")
        self._sync_sql_editor_from_parent()

    def save_sql_recipe(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save SQL recipe",
            str(self._sql_recipe_path or (DEFAULT_SQL_RECIPE_DIR / "industrial_query.sql")),
            "SQL files (*.sql);;All files (*)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".sql":
            path = path.with_suffix(".sql")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.sql_query_edit.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "SQL recipe", f"Could not save SQL recipe: {exc}")
            return
        self._sql_recipe_path = path
        self.sql_status_label.setText(f"SQL recipe saved: {path.name}")
        set_status_variant(self.sql_status_label, "success")
        self._sync_sql_editor_status()

    def _current_fetch_mode(self) -> str:
        return "sql" if self.mode_tabs.currentIndex() == 1 else "guided"

    def cancel_sync(self) -> None:
        self._batch_operations.clear()
        if self._active_batch_total > 1:
            self._active_batch_total = len(self._batch_results) + 1
        thread = self.oznak_sync_thread
        if thread is not None and thread.isRunning():
            thread.cancel()
            self.status_label.setText("Cancelling industrial fetch...")
            set_status_variant(self.status_label, "neutral")

    def _is_oznak_operation_running(self) -> bool:
        thread = self.oznak_sync_thread
        return bool(thread is not None and thread.isRunning()) or bool(self._batch_operations)

    def _start_oznak_operation(self, *, test_only: bool) -> None:
        if self.oznak_sync_thread is not None and self.oznak_sync_thread.isRunning():
            self.status_label.setText("Industrial operation already running")
            set_status_variant(self.status_label, "neutral")
            return
        try:
            fetch_mode = self._current_fetch_mode()
            if fetch_mode == "guided" and not self._apply_inline_filter_state(show_errors=True):
                return
            profiles = self._profiles_for_operation(fetch_mode=fetch_mode, test_only=test_only)
            if not profiles:
                raise ValueError("Create or select a production source before checking access.")
            if self.access_only and not test_only:
                raise ValueError(
                    "Access-only mode supports Check access only. Select or create a local industrial cache to fetch rows."
                )
            if not test_only:
                if self.fetch_all_checkbox.isChecked():
                    scope_text = (
                        "the SQL query result"
                        if fetch_mode == "sql"
                        else f"{len(profiles)} selected production source(s)"
                    )
                    confirmed = QMessageBox.question(
                        self,
                        "Fetch all industrial data",
                        (
                            f"Fetch all rows from {scope_text}? This can take a long time "
                            "and may create a large local SQLite cache."
                        ),
                    )
                    if confirmed != QMessageBox.StandardButton.Yes:
                        return
            operations = self._build_oznak_operations(
                profiles=profiles,
                fetch_mode=fetch_mode,
                test_only=test_only,
            )
            self._pending_sql_preview = bool(test_only and fetch_mode == "sql")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Industrial data fetch", str(exc))
            return

        action = "Checking production database access" if test_only else "Fetching production data"
        self.status_label.setText(
            f"{action}..." if len(operations) == 1 else f"{action}: 0/{len(operations)} source(s)"
        )
        set_status_variant(self.status_label, "neutral")
        self._set_action_buttons_enabled(False)
        self.cancel_sync_button.setEnabled(True)
        self._batch_results = []
        self._active_batch_total = len(operations)
        self._batch_operations = list(operations)
        self._start_next_oznak_operation()

    def _profiles_for_operation(
        self,
        *,
        fetch_mode: str,
        test_only: bool,
    ) -> tuple[IndustrialSourceProfile, ...]:
        profile = self.current_profile()
        if self.access_only or test_only or fetch_mode == "sql":
            return (profile,) if profile is not None else ()
        checked = self.checked_profiles()
        if checked:
            return checked
        return (profile,) if profile is not None else ()

    def _fetch_state_for_operation(self, *, fetch_mode: str, test_only: bool) -> IndustrialFetchState:
        if not test_only:
            if fetch_mode == "sql":
                return IndustrialFetchState.from_sql(
                    self.sql_query_edit.toPlainText(),
                    limit_rows=None if self.fetch_all_checkbox.isChecked() else self.limit_spin.value(),
                    fetch_all_confirmed=self.fetch_all_checkbox.isChecked(),
                    sql_preview_limit=self.sql_preview_limit_spin.value(),
                    sql_recipe_path=str(self._sql_recipe_path) if self._sql_recipe_path else None,
                )
            return IndustrialFetchState.from_reference_state(
                self.filter_state,
                limit_rows=None if self.fetch_all_checkbox.isChecked() else self.limit_spin.value(),
                fetch_all_confirmed=self.fetch_all_checkbox.isChecked(),
            )
        if fetch_mode == "sql":
            return IndustrialFetchState.from_sql(
                self.sql_query_edit.toPlainText(),
                limit_rows=self.sql_preview_limit_spin.value(),
                sql_preview_limit=self.sql_preview_limit_spin.value(),
                sql_recipe_path=str(self._sql_recipe_path) if self._sql_recipe_path else None,
            )
        return IndustrialFetchState.from_reference_state(
            self.filter_state,
            limit_rows=1,
        )

    def _build_oznak_operations(
        self,
        *,
        profiles: tuple[IndustrialSourceProfile, ...],
        fetch_mode: str,
        test_only: bool,
    ) -> tuple[_OznakOperation, ...]:
        use_form_credentials = (
            len(profiles) == 1
            or self.batch_use_current_credentials_checkbox.isChecked()
            or test_only
            or fetch_mode == "sql"
            or self.access_only
        )
        form_credentials: tuple[str, str] | None = None
        if use_form_credentials:
            form_credentials = self._read_credentials()
        operations: list[_OznakOperation] = []
        fetch_state = self._fetch_state_for_operation(fetch_mode=fetch_mode, test_only=test_only)
        for profile in profiles:
            runtime_profile = (
                self._profile_for_current_filter(profile)
                if fetch_mode == "guided" and (not test_only or self.filter_state.is_applied)
                else profile
            )
            if form_credentials is not None:
                username, password = form_credentials
                pending_save = (
                    (profile.profile_key, username, password)
                    if self.remember_credentials_checkbox.isChecked()
                    else None
                )
            else:
                stored = load_industrial_credentials(profile.profile_key)
                username, password = stored.username, stored.password
                if not username or not password:
                    raise ValueError(
                        "Saved credentials are missing for "
                        f"{profile.profile_name}. Enable 'Use entered credentials for all checked sources' "
                        "or save credentials for each selected source first."
                    )
                pending_save = None
            operations.append(
                _OznakOperation(
                    profile=runtime_profile,
                    username=username,
                    password=password,
                    fetch_state=fetch_state,
                    test_only=test_only,
                    access_only=self.access_only,
                    pending_credential_save=pending_save,
                )
            )
        return tuple(operations)

    def _start_next_oznak_operation(self) -> None:
        if not self._batch_operations:
            self._active_operation = None
            return
        operation = self._batch_operations.pop(0)
        self._active_operation = operation
        self._pending_credential_save = operation.pending_credential_save
        completed = len(self._batch_results)
        if self._active_batch_total > 1:
            action = "Checking" if operation.test_only else "Fetching"
            self.status_label.setText(
                f"{action} {operation.profile.profile_name} "
                f"({completed + 1}/{self._active_batch_total})..."
            )
            set_status_variant(self.status_label, "neutral")
        if operation.access_only:
            self.oznak_sync_thread = IndustrialOznakAccessCheckThread(
                profile=operation.profile,
                username=operation.username,
                password=operation.password,
                timeout_seconds=self.timeout_spin.value(),
                reference_filter_column=self.filter_state.reference_column
                if self.filter_state.references
                else None,
                reference_values=self.filter_state.references,
            )
        else:
            self.oznak_sync_thread = IndustrialOznakSyncThread(
                db_file=str(self.db_file),
                profile=operation.profile,
                username=operation.username,
                password=operation.password,
                limit=self.limit_spin.value(),
                timeout_seconds=self.timeout_spin.value(),
                reference_filter_column=self.filter_state.reference_column
                if self.filter_state.references
                else None,
                reference_values=self.filter_state.references,
                test_only=operation.test_only,
                fetch_state=operation.fetch_state,
                report_db_file=None
                if self._active_batch_total > 1 and not operation.test_only
                else self.report_db_file,
            )
        self.oznak_sync_thread.progress_message.connect(self.on_oznak_progress)
        self.oznak_sync_thread.result_ready.connect(self.on_oznak_result)
        self.oznak_sync_thread.error_occurred.connect(self.on_oznak_error)
        self.oznak_sync_thread.finished.connect(self.on_oznak_thread_stopped)
        self.oznak_sync_thread.start()

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        if enabled:
            self._sync_action_buttons()
            self.close_button.setEnabled(True)
            self.profile_combo.setEnabled(True)
            self.username_edit.setEnabled(True)
            self.password_edit.setEnabled(True)
            self.remember_credentials_checkbox.setEnabled(True)
            self.source_check_list.setEnabled(not self.access_only)
            self.select_all_sources_button.setEnabled(not self.access_only)
            self.current_source_only_button.setEnabled(not self.access_only)
            self.batch_use_current_credentials_checkbox.setEnabled(not self.access_only)
            self.mode_tabs.setEnabled(not self.access_only)
            self.timeout_spin.setEnabled(True)
            return
        for button in (
            self.profile_combo,
            self.source_check_list,
            self.select_all_sources_button,
            self.current_source_only_button,
            self.batch_use_current_credentials_checkbox,
            self.username_edit,
            self.password_edit,
            self.remember_credentials_checkbox,
            self.timeout_spin,
            self.forget_credentials_button,
            self.edit_filter_button,
            self.open_sql_button,
            self.save_sql_button,
            self.open_sql_editor_button,
            self.preview_sql_button,
            self.test_connection_button,
            self.sync_now_button,
            self.fetch_csv_summary_button,
            self.close_button,
            self.fetch_all_checkbox,
            self.limit_spin,
            self.mode_tabs,
        ):
            button.setEnabled(enabled)

    def on_oznak_progress(self, message: str) -> None:
        self.status_label.setText(str(message))
        set_status_variant(self.status_label, "neutral")

    def on_oznak_result(self, result: dict[str, Any]) -> None:
        self._save_pending_credentials_after_success(result)
        active_operation = self._active_operation
        if active_operation is not None:
            result = dict(result)
            result.setdefault("profile_key", active_operation.profile.profile_key)
            result.setdefault("profile_name", active_operation.profile.profile_name)
        if self._active_batch_total > 1:
            self._batch_results.append(result)
            completed = len(self._batch_results)
            if completed < self._active_batch_total:
                self.status_label.setText(
                    f"Completed {completed}/{self._active_batch_total} source(s); "
                    "waiting for next source..."
                )
                set_status_variant(self.status_label, "neutral")
                return
            self._show_batch_result_status()
            self._finish_batch_fetch_after_optional_link_refresh()
            return
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_status"):
            parent.refresh_status()
        if result.get("status") == "completed_with_warnings":
            detail = self._result_error_detail(result)
            if result.get("test_only"):
                if self._pending_sql_preview:
                    row_count = int(result.get("row_count", 0) or 0)
                    self._populate_sql_preview_table(result.get("preview_records") or ())
                    self.sql_status_label.setText(
                        f"SQL preview returned {row_count} row(s) with warnings; nothing saved."
                    )
                    set_status_variant(self.sql_status_label, "warning")
                    self._sync_sql_editor_status()
                    self.status_label.setText(
                        f"SQL preview completed with warnings: {detail}"
                        if detail
                        else f"SQL preview completed with warnings: {row_count} row(s)"
                    )
                    set_status_variant(self.status_label, "warning")
                    return
                base = (
                    "Access check completed with warnings: "
                    f"{result.get('row_count', 0)} row(s) visible, nothing saved"
                )
            else:
                upsert_summary = result.get("upsert_summary") or {}
                base = (
                    "Fetch complete with warnings: "
                    f"{upsert_summary.get('processed', result.get('row_count', 0))} rows"
                )
            self.status_label.setText(f"{base}: {detail}" if detail else base)
            set_status_variant(self.status_label, "warning")
            if (not result.get("test_only")) and self._open_csv_summary_after_fetch:
                self._open_csv_summary_after_fetch = False
                parent = self.parent()
                if parent is not None and hasattr(parent, "open_analytics_dialog"):
                    parent.open_analytics_dialog()
            return
        if result["status"] != "succeeded":
            self._open_csv_summary_after_fetch = False
            status_text = self._format_failed_result_status(result)
            self.status_label.setText(status_text)
            set_status_variant(
                self.status_label,
                "neutral" if result.get("status") == "cancelled" else "danger",
            )
            return
        if result["test_only"]:
            row_count = int(result.get("row_count", 0) or 0)
            if self._pending_sql_preview:
                self._populate_sql_preview_table(result.get("preview_records") or ())
                self.sql_status_label.setText(
                    f"SQL preview returned {row_count} row(s); nothing saved."
                )
                set_status_variant(
                    self.sql_status_label,
                    "success" if row_count > 0 else "warning",
                )
                self._sync_sql_editor_status()
                self.status_label.setText(
                    f"SQL preview passed: {row_count} row(s) visible, nothing saved"
                )
                set_status_variant(self.status_label, "success" if row_count > 0 else "warning")
                return
            if row_count <= 0:
                self.status_label.setText(
                    "Access check reached the database: 0 rows visible, nothing saved"
                )
                set_status_variant(self.status_label, "warning")
                return
            self.status_label.setText(f"Access check passed: {row_count} row(s) visible, nothing saved")
            set_status_variant(self.status_label, "success")
            return
        upsert_summary = result.get("upsert_summary") or {}
        link_summary = result.get("link_summary")
        link_text = ""
        if link_summary is not None:
            link_text = (
                f", {link_summary.accepted_links} links, "
                f"{link_summary.ambiguous_reports} ambiguous"
            )
        self.status_label.setText(
            f"Fetch complete: {upsert_summary.get('processed', result['row_count'])} rows{link_text}"
        )
        set_status_variant(self.status_label, "success")
        if self._open_csv_summary_after_fetch:
            self._open_csv_summary_after_fetch = False
            parent = self.parent()
            if parent is not None and hasattr(parent, "open_analytics_dialog"):
                parent.open_analytics_dialog()

    def _show_batch_result_status(self) -> None:
        results = tuple(self._batch_results)
        failed = [
            result
            for result in results
            if result.get("status") not in {"succeeded", "completed_with_warnings"}
        ]
        warnings = [result for result in results if result.get("status") == "completed_with_warnings"]
        processed = 0
        for result in results:
            upsert_summary = result.get("upsert_summary") or {}
            processed += int(upsert_summary.get("processed", result.get("row_count", 0)) or 0)
        if failed:
            failed_names = ", ".join(str(result.get("profile_name") or "unknown") for result in failed[:3])
            suffix = "..." if len(failed) > 3 else ""
            self.status_label.setText(
                f"Batch fetch completed with {len(failed)} failed source(s): "
                f"{failed_names}{suffix}. {processed} row(s) saved from successful sources."
            )
            set_status_variant(self.status_label, "warning")
            return
        if warnings:
            self.status_label.setText(
                f"Batch fetch completed with warnings: {processed} row(s) saved from "
                f"{len(results)} source(s)."
            )
            set_status_variant(self.status_label, "warning")
            return
        self.status_label.setText(
            f"Batch fetch complete: {processed} row(s) saved from {len(results)} source(s)."
        )
        set_status_variant(self.status_label, "success")

    def _finish_batch_fetch_after_optional_link_refresh(self) -> None:
        if self._should_refresh_links_after_batch():
            self.status_label.setText(f"{self.status_label.text()} Refreshing report links...")
            set_status_variant(self.status_label, "neutral")
            self.link_refresh_thread = IndustrialLinkRefreshThread(str(self.report_db_file))
            self.link_refresh_thread.summary_ready.connect(self._on_batch_link_refresh_ready)
            self.link_refresh_thread.error_occurred.connect(self._on_batch_link_refresh_error)
            self.link_refresh_thread.finished.connect(self._clear_batch_link_refresh_thread)
            self.link_refresh_thread.start()
            return
        self._finish_batch_fetch_ui_actions()

    def _should_refresh_links_after_batch(self) -> bool:
        if self._active_batch_total <= 1 or not self.report_db_file:
            return False
        return any(
            (not result.get("test_only"))
            and result.get("status") in {"succeeded", "completed_with_warnings"}
            for result in self._batch_results
        )

    def _on_batch_link_refresh_ready(self, summary: Any) -> None:
        self.status_label.setText(
            f"{self.status_label.text()} Links refreshed: "
            f"{summary.accepted_links} links, {summary.ambiguous_reports} ambiguous."
        )
        set_status_variant(self.status_label, self._batch_final_status_variant())
        self._finish_batch_fetch_ui_actions()

    def _on_batch_link_refresh_error(self, message: str) -> None:
        self.status_label.setText(
            f"{self.status_label.text()} Link refresh failed: {redact_sensitive_text(message)}"
        )
        set_status_variant(self.status_label, "warning")
        self._finish_batch_fetch_ui_actions()

    def _clear_batch_link_refresh_thread(self) -> None:
        self.link_refresh_thread = None

    def _batch_final_status_variant(self) -> str:
        return (
            "success"
            if all(result.get("status") == "succeeded" for result in self._batch_results)
            else "warning"
        )

    def _finish_batch_fetch_ui_actions(self) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_status"):
            parent.refresh_status()
        if self._open_csv_summary_after_fetch:
            self._open_csv_summary_after_fetch = False
            if parent is not None and hasattr(parent, "open_analytics_dialog"):
                parent.open_analytics_dialog()

    def _populate_sql_preview_table(self, records: Any) -> None:
        _populate_preview_table(self.sql_preview_table, records)
        if self.sql_editor_window is not None:
            self.sql_editor_window.set_preview_records(records)

    def on_oznak_error(self, message: str) -> None:
        self._pending_credential_save = None
        self._pending_sql_preview = False
        self._open_csv_summary_after_fetch = False
        self._batch_operations.clear()
        self._batch_results.clear()
        self._active_batch_total = 0
        self._active_operation = None
        QMessageBox.warning(
            self,
            "Industrial data fetch",
            f"Oznak operation failed: {redact_sensitive_text(message)}",
        )
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_status"):
            parent.refresh_status()

    def on_oznak_thread_stopped(self) -> None:
        self._pending_credential_save = None
        self._pending_sql_preview = False
        self.oznak_sync_thread = None
        if self._batch_operations:
            self._start_next_oznak_operation()
            return
        self._active_operation = None
        self._active_batch_total = 0
        self._set_action_buttons_enabled(True)
        self.cancel_sync_button.setEnabled(False)

    def _save_pending_credentials_after_success(self, result: dict[str, Any]) -> None:
        pending = self._pending_credential_save
        if result.get("status") not in {"succeeded", "completed_with_warnings"}:
            self._pending_credential_save = None
            return
        self._pending_credential_save = None
        if pending is None:
            return
        profile_key, username, password = pending
        try:
            saved_path = save_industrial_credentials(
                profile_key,
                username=username,
                password=password,
            )
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Industrial data credentials",
                f"Access passed, but credentials could not be saved: {redact_sensitive_text(exc)}",
            )
            return
        self._update_credentials_location_label(saved_path=saved_path)

    def closeEvent(self, event) -> None:
        thread = self.oznak_sync_thread
        if thread is not None and thread.isRunning():
            QMessageBox.information(self, "Industrial data fetch", "Cancel or wait for the operation to finish.")
            event.ignore()
            return
        super().closeEvent(event)

    def _sync_action_buttons(self) -> None:
        thread = self.oznak_sync_thread
        if (thread is not None and thread.isRunning()) or self._batch_operations:
            self.edit_filter_button.setEnabled(False)
            self.open_sql_button.setEnabled(False)
            self.save_sql_button.setEnabled(False)
            self.open_sql_editor_button.setEnabled(False)
            self.preview_sql_button.setEnabled(False)
            self.test_connection_button.setEnabled(False)
            self.sync_now_button.setEnabled(False)
            self.fetch_csv_summary_button.setEnabled(False)
            return
        has_source = self.current_profile() is not None
        self.forget_credentials_button.setEnabled(
            has_source and self._can_forget_credentials
        )
        self.edit_filter_button.setEnabled(has_source and not self.access_only)
        self.open_sql_button.setEnabled(not self.access_only)
        self.save_sql_button.setEnabled(not self.access_only)
        self.open_sql_editor_button.setEnabled(not self.access_only)
        self.preview_sql_button.setEnabled(has_source and not self.access_only)
        self.test_connection_button.setEnabled(has_source)
        has_fetch_source = bool(self.checked_profiles() or has_source)
        self.sync_now_button.setEnabled(
            has_fetch_source and (not self.access_only)
        )
        self.fetch_csv_summary_button.setEnabled(has_fetch_source and (not self.access_only))
        self._sync_limit_controls()

    def _sync_limit_controls(self) -> None:
        if hasattr(self, "limit_spin"):
            self.limit_spin.setEnabled(
                (not self.access_only) and not self.fetch_all_checkbox.isChecked()
            )
        if hasattr(self, "fetch_all_checkbox"):
            self.fetch_all_checkbox.setEnabled(not self.access_only)

    def _format_failed_result_status(self, result: dict[str, Any]) -> str:
        if result.get("status") == "cancelled":
            base = "Industrial fetch cancelled"
        elif result.get("test_only"):
            base = "Access check failed"
        else:
            base = "Industrial fetch failed"
        detail = self._result_error_detail(result)
        return f"{base}: {detail}" if detail else base

    @staticmethod
    def _result_error_detail(result: dict[str, Any]) -> str:
        candidates: list[Any] = [result.get("error")]
        diagnostics = result.get("diagnostics")
        if isinstance(diagnostics, dict):
            candidates.extend(diagnostics.get("errors") or ())
            candidates.extend(diagnostics.get("warnings") or ())
        for candidate in candidates:
            text = redact_sensitive_text(candidate)
            if text:
                return text
        return ""

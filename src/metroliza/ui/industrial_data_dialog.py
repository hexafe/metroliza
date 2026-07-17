"""Compact launcher for Oznak industrial-data workflows."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QComboBox,
    QMenu,
    QPushButton,
    QVBoxLayout,
)

from metroliza.industrial.industrial_data_repository import (
    IndustrialDataRepository,
    IndustrialSyncRunSummary,
    redact_sensitive_text,
)
from metroliza.industrial.industrial_cache_target import (
    IndustrialCacheTarget,
    cleanup_temporary_industrial_cache,
    create_temporary_industrial_cache_target,
    disposable_cache_counts,
    existing_metroliza_cache_target,
    persist_temporary_industrial_cache,
    persistent_industrial_cache_target,
)
from metroliza.industrial.industrial_tabular_bridge import load_industrial_cache_tabular_result
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog
from metroliza.ui.industrial_export_dialog import IndustrialExportDialog
from metroliza.ui.industrial_linking_dialog import IndustrialLinkingDialog
from metroliza.industrial.industrial_source_config import (
    IndustrialSourceConfigError,
    default_industrial_source_config_path,
    import_source_profiles_to_repository,
    load_source_profiles_from_config,
    source_profile_configuration_signature,
)
from metroliza.ui.industrial_source_profiles_dialog import IndustrialSourceProfilesDialog
from metroliza.ui.industrial_sync_dialog import IndustrialSyncDialog
from metroliza.industrial.industrial_workers import (
    IndustrialExportThread as IndustrialExportThread,
    IndustrialLinkRefreshThread,
    IndustrialOznakSyncThread as IndustrialOznakSyncThread,
)
from metroliza.industrial.industrial_workflow_state import IndustrialFilterState, IndustrialGroupingState
from metroliza.industrial.oznak_adapter import get_oznak_adapter_status
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_dialog_button_roles,
    configure_window_size,
    path_field,
    section_label,
    set_status_variant,
    status_chip,
    update_path_field,
)


class IndustrialDataDialog(QDialog):
    """Show industrial-data status and launch source, sync, and export dialogs."""

    def __init__(self, parent=None, db_file: str | None = None):
        super().__init__(parent)
        self.report_db_file = db_file
        self._workspace_db_file = db_file
        self.cache_target: IndustrialCacheTarget = (
            existing_metroliza_cache_target(db_file)
            if db_file
            else create_temporary_industrial_cache_target()
        )
        self.db_file = self.cache_target.cache_db_file
        self.config_path = default_industrial_source_config_path()
        self.link_refresh_thread = None
        self.source_window = None
        self.sync_window = None
        self.export_window = None
        self.analytics_window = None
        self.linking_window = None
        self.sync_filter_state = IndustrialFilterState()
        self.export_filter_state = IndustrialFilterState()
        self.grouping_state = IndustrialGroupingState()
        self.include_plots = True

        self.setWindowTitle("Industrial data")
        configure_window_size(self, minimum=(680, 420), initial=(900, 620), screen_margin=20)

        self.database_field = path_field(
            self._storage_field_text(),
            empty_text="Temporary industrial cache",
        )
        self.status_label = status_chip(
            "Fetch rows to cache, then open CSV Summary.",
            "neutral",
        )
        self.storage_lifecycle_label = status_chip(
            "Temporary storage is disposable until it is saved.",
            "warning",
        )
        self.workflow_steps_label = section_label(
            "1  Source   ·   2  Test access   ·   3  Fetch cache   ·   4  Analyze"
        )
        self.oznak_label = status_chip("Oznak connector: checking...", "neutral")
        self.workflow_label = status_chip(
            "Source -> Access -> Cache -> CSV Summary: checking...",
            "neutral",
        )
        self.sync_summary_label = status_chip("Last sync/cache outcome: not checked", "neutral")
        self.cache_label = status_chip("Local industrial cache: not checked", "neutral")
        self.sources_label = status_chip("Production sources: none", "neutral")
        self.sync_filter_label = status_chip(self.sync_filter_state.summary(), "warning")
        self.export_filter_label = status_chip(self.export_filter_state.summary(), "neutral")
        self.grouping_label = status_chip(self.grouping_state.summary(), "neutral")
        self.export_options_label = status_chip("Export plots: included", "neutral")
        self.analytics_status_label = status_chip("CSV Summary needs cached production rows.", "neutral")
        self.analysis_source_combo = QComboBox()
        self.analysis_source_combo.setToolTip(
            "Choose which cached production source rows are opened in CSV Summary."
        )

        self.use_temp_button = QPushButton("Temp")
        self.select_database_button = QPushButton("Open...")
        self.create_database_button = QPushButton("Save cache as...")
        self.sources_button = QPushButton("Production sources...")
        self.sync_button = QPushButton("Fetch to cache...")
        self.links_button = QPushButton("Production links...")
        self.export_button = QPushButton("Export workbook...")
        self.analyze_button = QPushButton("CSV Summary...")
        self.initialize_button = QPushButton("Initialize cache")
        self.diagnostics_button = QPushButton("Diagnostics...")
        self.diagnostics_menu = QMenu(self)
        self.initialize_cache_action = self.diagnostics_menu.addAction("Initialize cache")
        self.diagnostics_button.setMenu(self.diagnostics_menu)
        self.refresh_links_button = QPushButton("Refresh links")
        self.close_button = QPushButton("Close")
        self.sync_button.setToolTip(
            "Fetch rows from the selected production source into the active local industrial cache."
        )
        self.export_button.setToolTip(
            "Create an industrial workbook from cached rows in the active local industrial cache."
        )
        self.analyze_button.setToolTip(
            "Open cached industrial rows in the shared CSV Summary workflow."
        )
        self.create_database_button.setToolTip(
            "Save the active temporary cache, or create a durable industrial cache database."
        )

        self.use_temp_button.clicked.connect(self.use_temporary_cache)
        self.select_database_button.clicked.connect(self.select_database_file)
        self.create_database_button.clicked.connect(self.create_database_file)
        self.sources_button.clicked.connect(self.open_sources_dialog)
        self.sync_button.clicked.connect(self.open_sync_dialog)
        self.links_button.clicked.connect(self.open_links_dialog)
        self.export_button.clicked.connect(self.open_export_dialog)
        self.analyze_button.clicked.connect(self.open_analytics_dialog)
        self.initialize_button.clicked.connect(self.initialize_cache)
        self.initialize_cache_action.triggered.connect(self.initialize_cache)
        self.refresh_links_button.clicked.connect(self.refresh_links)
        self.close_button.clicked.connect(self.reject)

        self._build_layout()
        self._configure_accessibility()
        self.refresh_status()
        apply_metroliza_theme(self)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        attach_help_menu_to_layout(layout, self, [("Industrial Data manual", "industrial_data")])
        layout.addWidget(section_label("Industrial data"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        row = 0
        grid.addWidget(section_label("Storage"), row, 0)
        grid.addWidget(self.database_field, row, 1)
        storage_actions = QHBoxLayout()
        storage_actions.setContentsMargins(0, 0, 0, 0)
        storage_actions.setSpacing(6)
        storage_actions.addWidget(self.select_database_button)
        storage_actions.addWidget(self.create_database_button)
        grid.addLayout(storage_actions, row, 2)

        row += 1
        grid.addWidget(self.storage_lifecycle_label, row, 0, 1, 3)

        row += 1
        grid.addWidget(self.workflow_steps_label, row, 0, 1, 3)

        row += 1
        grid.addWidget(section_label("Oznak connector"), row, 0)
        grid.addWidget(self.oznak_label, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Workflow"), row, 0)
        grid.addWidget(self.workflow_label, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Last cache outcome"), row, 0)
        grid.addWidget(self.sync_summary_label, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Local industrial cache"), row, 0)
        grid.addWidget(self.cache_label, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Production sources"), row, 0)
        grid.addWidget(self.sources_label, row, 1)
        grid.addWidget(self.sources_button, row, 2)

        row += 1
        grid.addWidget(section_label("Fetch scope"), row, 0)
        grid.addWidget(self.sync_filter_label, row, 1)
        grid.addWidget(self.sync_button, row, 2)

        row += 1
        grid.addWidget(section_label("Workbook filter"), row, 0)
        grid.addWidget(self.export_filter_label, row, 1)
        grid.addWidget(self.export_button, row, 2)

        row += 1
        analytics_row = QHBoxLayout()
        analytics_row.setContentsMargins(0, 0, 0, 0)
        analytics_row.setSpacing(8)
        analytics_row.addWidget(self.analytics_status_label, 1)
        analytics_row.addWidget(self.analysis_source_combo)
        grid.addWidget(section_label("CSV Summary cache"), row, 0)
        grid.addLayout(analytics_row, row, 1)
        grid.addWidget(self.analyze_button, row, 2)

        row += 1
        grid.addWidget(section_label("Workbook groups"), row, 0)
        grid.addWidget(self.grouping_label, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Workbook options"), row, 0)
        grid.addWidget(self.export_options_label, row, 1, 1, 2)

        row += 1
        grid.addWidget(self.status_label, row, 0, 1, 3)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        actions.addWidget(self.use_temp_button)
        actions.addWidget(self.initialize_button)
        self.initialize_button.hide()
        actions.addWidget(self.diagnostics_button)
        actions.addWidget(self.refresh_links_button)
        actions.addWidget(self.links_button)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

    def update_db_file(self, db_file: str | None) -> bool:
        """Point an already-open dialog at the current main-window database."""

        if db_file:
            updated = self._set_cache_target(existing_metroliza_cache_target(db_file))
        else:
            updated = self._set_cache_target(create_temporary_industrial_cache_target())
        if not updated:
            return False
        self._workspace_db_file = db_file
        self.refresh_status()
        return True

    def _set_cache_target(self, target: IndustrialCacheTarget) -> bool:
        previous = getattr(self, "cache_target", None)
        if previous is not None and previous != target and self._link_refresh_owns_context():
            if previous.cache_db_file != target.cache_db_file:
                cleanup_temporary_industrial_cache(target)
            self._show_link_refresh_context_guard()
            return False
        if previous is not None and previous.cache_db_file != target.cache_db_file:
            if not self._resolve_temporary_cache_before_discard(
                previous,
                additional_forbidden=(target.cache_db_file,),
            ):
                cleanup_temporary_industrial_cache(target)
                return False
            cleanup_temporary_industrial_cache(previous)
        self.cache_target = target
        self.db_file = target.cache_db_file
        self.report_db_file = target.report_db_file
        return True

    def _storage_field_text(self) -> str:
        target = getattr(self, "cache_target", None)
        if target is None:
            return ""
        if target.is_temporary:
            return f"{target.storage_label}: {target.cache_db_file}"
        return target.cache_db_file

    def use_temporary_cache(self) -> None:
        """Switch industrial caching to a disposable session SQLite file."""

        if self._link_refresh_owns_context():
            self._show_link_refresh_context_guard()
            return
        if self._set_cache_target(create_temporary_industrial_cache_target()):
            self.refresh_status()

    def select_database_file(self) -> None:
        """Select an existing Metroliza database used for cache and links."""

        if self._link_refresh_owns_context():
            self._show_link_refresh_context_guard()
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open Metroliza database for industrial cache",
            str(self.report_db_file or self.db_file or ""),
            "SQLite database (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if not filename:
            return

        if not self._set_cache_target(existing_metroliza_cache_target(filename)):
            return
        self._workspace_db_file = filename
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_db_file"):
            parent.set_db_file(filename)
        self.refresh_status()

    def create_database_file(self) -> None:
        """Create durable storage, preserving any populated temporary cache."""

        if self._link_refresh_owns_context():
            self._show_link_refresh_context_guard()
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save industrial cache database",
            str(self.report_db_file or self.db_file or "industrial_cache.db"),
            "SQLite database (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if not filename:
            return
        if not filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
            filename = f"{filename}.db"
        previous = self.cache_target
        try:
            if previous.is_temporary:
                target = persist_temporary_industrial_cache(
                    previous,
                    filename,
                    forbidden_destinations=self._forbidden_cache_destinations(),
                )
            else:
                IndustrialDataRepository(filename).ensure_schema()
                target = persistent_industrial_cache_target(filename)
        except Exception as exc:
            QMessageBox.warning(self, self.windowTitle(), f"Could not save cache: {exc}")
            return
        cleanup_temporary_industrial_cache(previous)
        self.cache_target = target
        self.db_file = target.cache_db_file
        self.report_db_file = target.report_db_file
        self.refresh_status()

    def _resolve_temporary_cache_before_discard(
        self,
        target: IndustrialCacheTarget | None,
        *,
        additional_forbidden: tuple[str, ...] = (),
    ) -> bool:
        counts = self._temporary_cache_lifecycle_counts(target)
        if not any(counts.values()):
            return True
        persisted_rows = sum(counts.values())
        choice = QMessageBox.question(
            self,
            "Temporary industrial data",
            f"This temporary cache contains {persisted_rows:,} persisted data row(s). "
            "Save it before removing the temporary files?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Discard:
            return True

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save temporary industrial cache",
            "industrial_cache.db",
            "SQLite database (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if not filename:
            return False
        if not filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
            filename = f"{filename}.db"
        try:
            persist_temporary_industrial_cache(
                target,
                filename,
                forbidden_destinations=self._forbidden_cache_destinations(
                    *additional_forbidden
                ),
            )
        except Exception as exc:
            QMessageBox.warning(self, self.windowTitle(), f"Could not save cache: {exc}")
            return False
        return True

    def _forbidden_cache_destinations(self, *additional: str) -> tuple[str, ...]:
        destinations = {
            str(candidate)
            for candidate in (self._workspace_db_file, *additional)
            if str(candidate or "").strip()
        }
        return tuple(sorted(destinations))

    def _temporary_cache_lifecycle_counts(
        self,
        target: IndustrialCacheTarget | None,
    ) -> dict[str, int]:
        """Count disposable rows, excluding exact copies of durable YAML profiles."""

        if target is None or not target.is_temporary:
            return {}
        try:
            counts = disposable_cache_counts(target.cache_db_file)
        except Exception:
            # An unreadable cache may still contain recoverable operator data.
            # Force an explicit retention decision instead of crashing shutdown.
            return {"unreadable_industrial_cache": 1}
        if not counts.get("industrial_source_profiles"):
            return counts
        try:
            configured_signatures = {
                source_profile_configuration_signature(profile)
                for profile in load_source_profiles_from_config(self.config_path)
            }
            stored_profiles = IndustrialDataRepository(
                target.cache_db_file
            ).list_source_profiles(include_disabled=True)
        except Exception:
            # If profile provenance cannot be proven, retain the conservative
            # prompt so user-authored temporary configuration is not discarded.
            return counts
        derived_profile_count = sum(
            source_profile_configuration_signature(profile) in configured_signatures
            for profile in stored_profiles
        )
        counts["industrial_source_profiles"] = max(
            0,
            counts["industrial_source_profiles"] - derived_profile_count,
        )
        return counts

    def _refresh_storage_lifecycle(self) -> None:
        if self.cache_target.is_temporary:
            persisted_rows = sum(
                self._temporary_cache_lifecycle_counts(self.cache_target).values()
            )
            if persisted_rows:
                self.storage_lifecycle_label.setText(
                    f"Temporary storage · {persisted_rows:,} persisted data row(s) will be "
                    "deleted when this window closes. Save cache as… to keep them."
                )
                set_status_variant(self.storage_lifecycle_label, "danger")
            else:
                self.storage_lifecycle_label.setText(
                    "Temporary storage · data will be deleted when this window closes."
                )
                set_status_variant(self.storage_lifecycle_label, "warning")
            self.create_database_button.setText("Save cache as...")
        else:
            self.storage_lifecycle_label.setText("Durable storage · cached data is retained.")
            set_status_variant(self.storage_lifecycle_label, "success")
            self.create_database_button.setText("Create...")

    def _refresh_filter_and_grouping_status(self) -> None:
        self.oznak_label.setText(self._format_oznak_status())
        self.sync_filter_label.setText(self._sync_scope_summary())
        self.export_filter_label.setText(self.export_filter_state.summary())
        self.grouping_label.setText(self.grouping_state.summary())
        self.export_options_label.setText(
            "Export plots: included" if self.include_plots else "Export plots: disabled"
        )
        set_status_variant(
            self.sync_filter_label,
            "success" if self.sync_filter_state.is_applied else "neutral",
        )
        set_status_variant(
            self.export_filter_label,
            "success" if self.export_filter_state.is_applied else "neutral",
        )
        set_status_variant(
            self.grouping_label,
            "success" if self.grouping_state.is_applied else "neutral",
        )

    def _refresh_unavailable_cache_status(self) -> None:
        self.cache_label.setText("Local industrial cache: unavailable")
        self.sources_label.setText(self._format_config_source_status())
        self.workflow_label.setText(
            self._format_workflow_strip(
                source_text="configure source",
                access_text="check access",
                cache_text="cache unavailable",
                csv_text="waiting",
            )
        )
        self.sync_summary_label.setText("Last sync/cache outcome: cache diagnostics unavailable")
        set_status_variant(self.workflow_label, "warning")
        set_status_variant(self.sync_summary_label, "neutral")
        self.analytics_status_label.setText("Select or create a cache before opening CSV Summary.")
        self._populate_analysis_source_options(None, (), 0)
        set_status_variant(self.analytics_status_label, "warning")
        self._set_action_buttons_enabled(cache_available=False)
        self.status_label.setText("Configure production sources, then fetch rows into a local cache.")
        set_status_variant(self.status_label, "warning")
        self._configure_action_roles(self.sources_button)

    def _load_cache_status(self):
        config_error = ""
        try:
            repository = IndustrialDataRepository(self.db_file)
            try:
                import_source_profiles_to_repository(self.config_path, repository)
            except IndustrialSourceConfigError as exc:
                config_error = str(exc)
            counts = repository.summarize_counts()
            profiles = repository.list_source_profiles(include_disabled=True)
            latest_sync = repository.latest_sync_run()
        except Exception:
            self.cache_label.setText("Local industrial cache: not initialized")
            self.cache_label.setToolTip(
                "The selected file could not be opened as a Metroliza SQLite cache."
            )
            self.sources_label.setText("Production sources: not loaded")
            self.workflow_label.setText(
                self._format_workflow_strip(
                    source_text="unknown",
                    access_text="not checked",
                    cache_text="initialize cache",
                    csv_text="waiting",
                )
            )
            self.sync_summary_label.setText("Last sync/cache outcome: cache diagnostics unavailable")
            set_status_variant(self.workflow_label, "warning")
            set_status_variant(self.sync_summary_label, "warning")
            self.status_label.setText("Initialize the active local industrial cache.")
            set_status_variant(self.status_label, "warning")
            self._configure_action_roles(self.sources_button)
            return None
        return repository, counts, profiles, latest_sync, config_error

    def _refresh_loaded_cache_status(
        self,
        repository,
        counts,
        profiles,
        latest_sync,
        config_error: str,
    ) -> None:
        self.cache_label.setText(
            f"{self.cache_target.status_prefix}: "
            f"{counts.records} records, {counts.sync_runs} sync runs, {counts.link_candidates} links"
        )
        self.sources_label.setText(f"{len(profiles)} production source(s) configured")
        self.workflow_label.setText(self._format_workflow_summary(len(profiles), counts.records, latest_sync))
        set_status_variant(
            self.workflow_label,
            self._workflow_status_variant(
                profiles_count=len(profiles),
                records=counts.records,
                latest_sync=latest_sync,
            ),
        )
        self.sync_summary_label.setText(self._format_latest_sync_summary(latest_sync))
        set_status_variant(self.sync_summary_label, self._sync_summary_variant(latest_sync))
        self._populate_analysis_source_options(repository, profiles, counts.records)
        if counts.records > 0:
            self.analytics_status_label.setText("CSV Summary ready from cached production rows.")
            set_status_variant(self.analytics_status_label, "success")
        else:
            self.analytics_status_label.setText("CSV Summary needs fetched rows in the local cache.")
            set_status_variant(self.analytics_status_label, "warning")
        if config_error:
            self.status_label.setText(config_error)
            set_status_variant(self.status_label, "warning")
        elif counts.records > 0:
            self.status_label.setText(
                "Industrial cache ready. Open CSV Summary to analyze cached production rows."
            )
            set_status_variant(self.status_label, "success")
        elif profiles:
            self.status_label.setText(
                "Industrial cache empty. Fetch selected production rows into the local cache before opening CSV Summary."
            )
            set_status_variant(self.status_label, "warning")
        else:
            self.status_label.setText(
                "Industrial cache empty. Create or import a production source before fetching rows."
            )
            set_status_variant(self.status_label, "warning")
        if counts.records > 0:
            self._configure_action_roles(self.analyze_button)
        elif profiles:
            self._configure_action_roles(self.sync_button)
        else:
            self._configure_action_roles(self.sources_button)

    def refresh_status(self) -> None:
        update_path_field(
            self.database_field,
            self._storage_field_text(),
            empty_text="Temporary industrial cache",
        )
        self._refresh_storage_lifecycle()
        self._refresh_filter_and_grouping_status()
        if not self.db_file:
            self._refresh_unavailable_cache_status()
            return
        self._set_action_buttons_enabled(cache_available=True)
        cache_status = self._load_cache_status()
        if cache_status is None:
            return
        self._refresh_loaded_cache_status(*cache_status)

    def _configure_action_roles(self, primary: QPushButton) -> None:
        workflow_actions = (
            self.sources_button,
            self.sync_button,
            self.export_button,
            self.analyze_button,
            self.initialize_button,
        )
        configure_dialog_button_roles(
            primary=primary,
            secondary=tuple(button for button in workflow_actions if button is not primary),
            quiet=(
                self.use_temp_button,
                self.select_database_button,
                self.create_database_button,
                self.diagnostics_button,
                self.refresh_links_button,
                self.links_button,
                self.close_button,
            ),
        )

    @staticmethod
    def _format_oznak_status() -> str:
        status = get_oznak_adapter_status()
        if not status.available:
            return f"Unavailable ({status.error})"
        version = status.version or "unknown version"
        fetch_state = "fetch ready" if status.fetch_available else "fetch unavailable"
        contract_state = "contracts ready" if status.contracts_available else "contracts incomplete"
        sql_state = "SQL ready" if status.raw_sql_available else "SQL unavailable"
        return f"{version}, {contract_state}, {fetch_state}, {sql_state}"

    @staticmethod
    def _format_workflow_strip(
        *,
        source_text: str,
        access_text: str,
        cache_text: str,
        csv_text: str,
    ) -> str:
        return (
            "Source -> Access -> Cache -> CSV Summary | "
            f"Source: {source_text} -> Access: {access_text} -> "
            f"Cache: {cache_text} -> CSV Summary: {csv_text}"
        )

    def _format_workflow_summary(
        self,
        profiles_count: int,
        records: int,
        latest_sync: IndustrialSyncRunSummary | None,
    ) -> str:
        source_text = f"{profiles_count} configured" if profiles_count else "setup needed"
        access_text = self._format_access_step(latest_sync)
        cache_text = self._format_cache_step(records)
        csv_text = "ready" if records > 0 else "waiting"
        return self._format_workflow_strip(
            source_text=source_text,
            access_text=access_text,
            cache_text=cache_text,
            csv_text=csv_text,
        )

    @staticmethod
    def _format_access_step(latest_sync: IndustrialSyncRunSummary | None) -> str:
        if latest_sync is None:
            return "not checked"
        status = latest_sync.status.replace("_", " ")
        if latest_sync.status == "succeeded":
            return "last passed"
        if latest_sync.status == "completed_with_warnings":
            return "warnings"
        return status

    @staticmethod
    def _format_cache_step(records: int) -> str:
        if records == 1:
            return "1 row"
        if records > 1:
            return f"{records:,} rows"
        return "empty"

    def _format_latest_sync_summary(self, latest_sync: IndustrialSyncRunSummary | None) -> str:
        if latest_sync is None:
            return "Last sync/cache outcome: no sync recorded"
        finished_text = latest_sync.finished_at or latest_sync.started_at
        status_text = latest_sync.status.replace("_", " ")
        row_text = "1 row" if latest_sync.row_count == 1 else f"{latest_sync.row_count:,} rows"
        summary = (
            "Last sync/cache outcome: "
            f"{latest_sync.profile_name} {status_text}, {row_text}, {finished_text}"
        )
        detail = self._sync_diagnostic_detail(latest_sync)
        if detail:
            summary = f"{summary} - {detail}"
        return summary

    @staticmethod
    def _sync_diagnostic_detail(latest_sync: IndustrialSyncRunSummary) -> str:
        if latest_sync.error_summary:
            return redact_sensitive_text(latest_sync.error_summary, max_len=180)
        diagnostics = latest_sync.diagnostics
        for key in ("errors", "warnings"):
            value = diagnostics.get(key)
            if isinstance(value, str):
                return redact_sensitive_text(value, max_len=180)
            if isinstance(value, (list, tuple)):
                for item in value:
                    detail = redact_sensitive_text(item, max_len=180)
                    if detail:
                        return detail
        return ""

    @staticmethod
    def _workflow_status_variant(
        *,
        profiles_count: int,
        records: int,
        latest_sync: IndustrialSyncRunSummary | None,
    ) -> str:
        if latest_sync is not None and latest_sync.status == "failed":
            return "danger"
        if profiles_count > 0 and records > 0:
            return "success"
        return "warning"

    @staticmethod
    def _sync_summary_variant(latest_sync: IndustrialSyncRunSummary | None) -> str:
        if latest_sync is None:
            return "neutral"
        if latest_sync.status == "failed":
            return "danger"
        if latest_sync.status in {"cancelled", "completed_with_warnings"}:
            return "warning"
        if latest_sync.status == "succeeded":
            return "success"
        return "neutral"

    def initialize_cache(self) -> None:
        if not self.db_file:
            self.refresh_status()
            return
        try:
            IndustrialDataRepository(self.db_file).ensure_schema()
        except Exception as exc:
            QMessageBox.warning(self, "Industrial data", f"Could not initialize cache: {exc}")
            self.refresh_status()
            return
        self.status_label.setText("Local industrial cache initialized.")
        set_status_variant(self.status_label, "success")
        self.refresh_status()

    def open_sources_dialog(self) -> None:
        self.source_window = IndustrialSourceProfilesDialog(
            self,
            db_file=self.db_file,
            config_path=self.config_path,
        )
        self.source_window.exec()
        self.config_path = self.source_window.config_path
        self.refresh_status()

    def open_sync_dialog(self) -> None:
        self.sync_window = IndustrialSyncDialog(
            self,
            db_file=self.db_file,
            report_db_file=self.report_db_file,
            config_path=self.config_path,
            access_only=False,
            filter_state=self.sync_filter_state,
        )
        self.sync_window.exec()
        self.refresh_status()

    def open_export_dialog(self) -> None:
        self.export_window = IndustrialExportDialog(
            self,
            db_file=self.db_file,
            report_db_file=self.report_db_file,
            filter_state=self.export_filter_state,
            grouping_state=self.grouping_state,
            include_plots=self.include_plots,
            config_path=self.config_path,
        )
        self.export_window.exec()
        self.refresh_status()

    def open_analytics_dialog(self) -> None:
        source_profile_id = self.analysis_source_combo.currentData()
        source_profile_ids = (int(source_profile_id),) if source_profile_id is not None else None
        try:
            loaded = load_industrial_cache_tabular_result(
                self.db_file,
                source_profile_ids=source_profile_ids,
            )
        except Exception as exc:
            QMessageBox.warning(self, self.windowTitle(), f"Could not load industrial cache: {exc}")
            return
        if int(getattr(loaded, "row_count", 0) or 0) <= 0:
            QMessageBox.warning(
                self,
                self.windowTitle(),
                "Fetch industrial data into the local cache before creating CSV Summary analytics.",
            )
            return
        source_label = self.analysis_source_combo.currentText().strip()
        source_suffix = f" ({source_label})" if source_label and source_profile_id is not None else ""
        self.analytics_window = IndustrialAnalyticsDialog(
            self,
            db_file=self.db_file,
            source_kind="tabular_file",
            tabular_load_result=loaded,
            input_file=self.db_file,
            source_label_override=(
                f"Industrial cache for CSV Summary{source_suffix}: {int(loaded.row_count or 0):,} rows"
            ),
            presentation_mode="industrial_cache",
        )
        self.analytics_window.exec()
        self.refresh_status()

    def open_links_dialog(self) -> None:
        if not self.report_db_file:
            QMessageBox.information(
                self,
                self.windowTitle(),
                "Report-to-production links need an open Metroliza report database.",
            )
            return
        self.linking_window = IndustrialLinkingDialog(self, db_file=self.report_db_file)
        self.linking_window.exec()
        self.refresh_status()

    def refresh_links(self) -> None:
        if not self.report_db_file:
            self.refresh_status()
            return
        if self._link_refresh_owns_context():
            self.status_label.setText("Report-to-production link refresh already running.")
            set_status_variant(self.status_label, "neutral")
            return

        self.status_label.setText("Refreshing report-to-production links...")
        set_status_variant(self.status_label, "neutral")
        self.link_refresh_thread = IndustrialLinkRefreshThread(self.report_db_file)
        self.link_refresh_thread.summary_ready.connect(self.on_link_refresh_finished)
        self.link_refresh_thread.error_occurred.connect(self.on_link_refresh_error)
        self.link_refresh_thread.finished.connect(self.on_link_refresh_thread_stopped)
        self._set_action_buttons_enabled(cache_available=False)
        self.link_refresh_thread.start()

    def on_link_refresh_finished(self, summary) -> None:
        self.refresh_status()
        self.status_label.setText(
            "Industrial links refreshed: "
            f"{summary.accepted_links} accepted, "
            f"{summary.ambiguous_reports} ambiguous, "
            f"{summary.unmatched_reports} unmatched"
        )
        set_status_variant(self.status_label, "success")

    def on_link_refresh_error(self, message: str) -> None:
        QMessageBox.warning(self, "Industrial data", f"Could not refresh links: {message}")
        self.refresh_status()

    def on_link_refresh_thread_stopped(self) -> None:
        self.link_refresh_thread = None
        self._set_action_buttons_enabled(cache_available=bool(self.db_file))

    def _link_refresh_owns_context(self) -> bool:
        """Return whether a refresh worker still owns the report/cache context."""

        # Keep ownership until QThread.finished is handled.  summary_ready and
        # error_occurred can be delivered before the worker has fully stopped.
        return self.link_refresh_thread is not None

    def _show_link_refresh_context_guard(self) -> None:
        self.status_label.setText(
            "Wait for report-to-production link refresh to finish before changing storage."
        )
        set_status_variant(self.status_label, "warning")

    def set_sync_filter_state(self, state: IndustrialFilterState) -> None:
        self.sync_filter_state = state
        self.refresh_status()

    def set_export_filter_state(self, state: IndustrialFilterState) -> None:
        self.export_filter_state = state
        self.refresh_status()

    def set_industrial_grouping_state(self, state: IndustrialGroupingState) -> None:
        self.grouping_state = state
        self.refresh_status()

    def set_include_plots_state(self, include_plots: bool) -> None:
        self.include_plots = bool(include_plots)
        self.refresh_status()

    def _sync_scope_summary(self) -> str:
        if self.sync_filter_state.is_applied:
            return self.sync_filter_state.summary()
        return "No reference filter; fetch uses the row limit by default"

    def _populate_analysis_source_options(
        self,
        repository: IndustrialDataRepository | None,
        profiles,
        total_records: int,
    ) -> None:
        current = self.analysis_source_combo.currentData()
        self.analysis_source_combo.blockSignals(True)
        try:
            self.analysis_source_combo.clear()
            if repository is None:
                self.analysis_source_combo.addItem("Select cache storage", None)
                self.analysis_source_combo.setEnabled(False)
                return
            if total_records <= 0:
                self.analysis_source_combo.addItem("No cached rows", None)
                self.analysis_source_combo.setEnabled(False)
                return
            self.analysis_source_combo.addItem(f"All sources ({int(total_records):,} rows)", None)
            for profile in profiles:
                try:
                    source_records = repository.summarize_counts(
                        source_profile_id=profile.id
                    ).records
                except Exception:
                    source_records = 0
                if source_records <= 0:
                    continue
                self.analysis_source_combo.addItem(
                    f"{profile.profile_name} ({int(source_records):,} rows)",
                    profile.id,
                )
            selected_index = self.analysis_source_combo.findData(current)
            if selected_index >= 0:
                self.analysis_source_combo.setCurrentIndex(selected_index)
            self.analysis_source_combo.setEnabled(True)
        finally:
            self.analysis_source_combo.blockSignals(False)

    def _format_config_source_status(self) -> str:
        try:
            profiles = load_source_profiles_from_config(self.config_path)
        except Exception as exc:
            return f"Config file issue: {exc}"
        if profiles:
            return f"{len(profiles)} production source(s) configured in file"
        return "Production source config file ready"

    def _has_configured_sources(self) -> bool:
        try:
            return bool(load_source_profiles_from_config(self.config_path))
        except Exception:
            return False

    def _set_action_buttons_enabled(self, *, cache_available: bool) -> None:
        refresh_active = self._link_refresh_owns_context()
        storage_change_enabled = not refresh_active
        cache_action_enabled = bool(cache_available and not refresh_active)
        self.select_database_button.setEnabled(storage_change_enabled)
        self.use_temp_button.setEnabled(storage_change_enabled)
        self.create_database_button.setEnabled(storage_change_enabled)
        self.sources_button.setEnabled(storage_change_enabled)
        self.initialize_button.setEnabled(cache_action_enabled)
        self.initialize_cache_action.setEnabled(cache_action_enabled)
        self.diagnostics_button.setEnabled(cache_action_enabled)
        self.sync_button.setEnabled(cache_action_enabled)
        self.export_button.setEnabled(cache_action_enabled)
        self.analyze_button.setEnabled(cache_action_enabled)
        links_available = bool(cache_action_enabled and self.report_db_file)
        self.links_button.setEnabled(links_available)
        self.refresh_links_button.setEnabled(links_available)

    def _configure_accessibility(self) -> None:
        configure_accessibility(self.database_field, name="Selected industrial cache storage")
        configure_accessibility(
            self.storage_lifecycle_label,
            name="Industrial cache data retention status",
        )
        configure_accessibility(self.oznak_label, name="Oznak connector readiness")
        configure_accessibility(self.workflow_label, name="Industrial workflow status")
        configure_accessibility(self.sync_summary_label, name="Industrial last cache outcome")
        configure_accessibility(self.cache_label, name="Industrial cache readiness")
        configure_accessibility(self.sources_label, name="Production source readiness")
        configure_accessibility(self.sync_filter_label, name="Industrial references-to-fetch summary")
        configure_accessibility(self.export_filter_label, name="Industrial export filter summary")
        configure_accessibility(self.analytics_status_label, name="Industrial CSV Summary readiness")
        configure_accessibility(self.grouping_label, name="Industrial export grouping summary")
        configure_accessibility(self.export_options_label, name="Industrial export option summary")
        configure_accessibility(self.use_temp_button, name="Use temporary industrial cache")
        configure_accessibility(self.select_database_button, name="Open Metroliza database for industrial cache")
        configure_accessibility(self.create_database_button, name="Create industrial cache database")
        configure_accessibility(self.sources_button, name="Open production sources")
        configure_accessibility(self.sync_button, name="Fetch industrial rows into cache")
        configure_accessibility(self.links_button, name="Open production links")
        configure_accessibility(self.export_button, name="Open industrial workbook export")
        configure_accessibility(self.analyze_button, name="Open industrial cache in CSV Summary")
        configure_accessibility(self.initialize_button, name="Initialize industrial cache")
        configure_accessibility(self.diagnostics_button, name="Open industrial diagnostics")
        configure_accessibility(self.refresh_links_button, name="Refresh industrial links")
        configure_accessibility(self.close_button, name="Close industrial data")

        self.setTabOrder(self.use_temp_button, self.select_database_button)
        self.setTabOrder(self.select_database_button, self.create_database_button)
        self.setTabOrder(self.create_database_button, self.sources_button)
        self.setTabOrder(self.sources_button, self.sync_button)
        self.setTabOrder(self.sync_button, self.export_button)
        self.setTabOrder(self.export_button, self.analyze_button)
        self.setTabOrder(self.analyze_button, self.initialize_button)
        self.setTabOrder(self.initialize_button, self.refresh_links_button)
        self.setTabOrder(self.refresh_links_button, self.links_button)
        self.setTabOrder(self.links_button, self.close_button)

    def reject(self) -> None:
        if self._link_refresh_owns_context():
            QMessageBox.information(
                self,
                "Industrial data",
                "Wait for report-to-production link refresh to finish.",
            )
            return
        target = getattr(self, "cache_target", None)
        if not self._resolve_temporary_cache_before_discard(target):
            return
        cleanup_temporary_industrial_cache(target)
        super().reject()

    def closeEvent(self, event) -> None:
        if self._link_refresh_owns_context():
            QMessageBox.information(
                self,
                "Industrial data",
                "Wait for report-to-production link refresh to finish.",
            )
            event.ignore()
            return
        target = getattr(self, "cache_target", None)
        if not self._resolve_temporary_cache_before_discard(target):
            event.ignore()
            return
        cleanup_temporary_industrial_cache(target)
        super().closeEvent(event)

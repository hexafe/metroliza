"""Compact launcher for Oznak industrial-data workflows."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QComboBox,
    QPushButton,
    QVBoxLayout,
)

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_tabular_bridge import load_industrial_cache_tabular_result
from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog
from metroliza.ui.industrial_export_dialog import IndustrialExportDialog
from metroliza.ui.industrial_linking_dialog import IndustrialLinkingDialog
from metroliza.industrial.industrial_source_config import (
    IndustrialSourceConfigError,
    default_industrial_source_config_path,
    import_source_profiles_to_repository,
    load_source_profiles_from_config,
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
        self.db_file = db_file
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
        configure_window_size(self, minimum=(620, 380), initial=(820, 500), screen_margin=20)

        self.database_field = path_field(
            str(db_file or ""),
            empty_text="No Metroliza report database selected",
        )
        self.status_label = status_chip(
            "Fetch rows to cache, then open CSV Summary.",
            "neutral",
        )
        self.oznak_label = status_chip("Oznak connector: checking...", "neutral")
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

        self.select_database_button = QPushButton("Select DB...")
        self.sources_button = QPushButton("Production sources...")
        self.sync_button = QPushButton("Fetch to cache...")
        self.links_button = QPushButton("Production links...")
        self.export_button = QPushButton("Export workbook...")
        self.analyze_button = QPushButton("CSV Summary...")
        self.initialize_button = QPushButton("Initialize cache")
        self.refresh_links_button = QPushButton("Refresh links")
        self.close_button = QPushButton("Close")
        self.sync_button.setToolTip(
            "Fetch rows from the selected production source into the local industrial cache. "
            "Select a Metroliza report database first so cached rows have a destination."
        )
        self.export_button.setToolTip(
            "Create an industrial workbook from the local cache, or fetch directly from a "
            "configured production source when no Metroliza report database is selected."
        )
        self.analyze_button.setToolTip(
            "Open cached industrial rows in the shared CSV Summary workflow."
        )

        self.select_database_button.clicked.connect(self.select_database_file)
        self.sources_button.clicked.connect(self.open_sources_dialog)
        self.sync_button.clicked.connect(self.open_sync_dialog)
        self.links_button.clicked.connect(self.open_links_dialog)
        self.export_button.clicked.connect(self.open_export_dialog)
        self.analyze_button.clicked.connect(self.open_analytics_dialog)
        self.initialize_button.clicked.connect(self.initialize_cache)
        self.refresh_links_button.clicked.connect(self.refresh_links)
        self.close_button.clicked.connect(self.reject)

        self._build_layout()
        self._configure_accessibility()
        self.refresh_status()
        apply_metroliza_theme(self)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(section_label("Industrial data"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        row = 0
        grid.addWidget(section_label("Metroliza report database"), row, 0)
        grid.addWidget(self.database_field, row, 1)
        grid.addWidget(self.select_database_button, row, 2)

        row += 1
        grid.addWidget(section_label("Oznak connector"), row, 0)
        grid.addWidget(self.oznak_label, row, 1, 1, 2)

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
        actions.setSpacing(8)
        actions.addWidget(self.initialize_button)
        actions.addWidget(self.refresh_links_button)
        actions.addWidget(self.links_button)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

    def update_db_file(self, db_file: str | None) -> None:
        """Point an already-open dialog at the current main-window database."""

        self.db_file = db_file
        self.refresh_status()

    def select_database_file(self) -> None:
        """Select the local Metroliza report database used for cache and links."""

        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Metroliza report database",
            str(self.db_file or ""),
            "SQLite database (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if not filename:
            return

        self.db_file = filename
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_db_file"):
            parent.set_db_file(filename)
        self.refresh_status()

    def refresh_status(self) -> None:
        update_path_field(
            self.database_field,
            str(self.db_file or ""),
            empty_text="No Metroliza report database selected",
        )
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

        if not self.db_file:
            self.cache_label.setText("Local industrial cache: unavailable until a report DB is selected")
            self.sources_label.setText(self._format_config_source_status())
            self.analytics_status_label.setText("Select a report DB with cached rows to open CSV Summary.")
            self._populate_analysis_source_options(None, (), 0)
            set_status_variant(self.analytics_status_label, "warning")
            self._set_action_buttons_enabled(db_available=False)
            self.status_label.setText(
                "Configure production sources and select a report DB to fetch rows into the cache. Export can fetch directly without a report DB."
            )
            set_status_variant(self.status_label, "warning")
            return

        self._set_action_buttons_enabled(db_available=True)
        config_error = ""
        try:
            repository = IndustrialDataRepository(self.db_file)
            try:
                import_source_profiles_to_repository(self.config_path, repository)
            except IndustrialSourceConfigError as exc:
                config_error = str(exc)
            counts = repository.summarize_counts()
            profiles = repository.list_source_profiles(include_disabled=True)
        except Exception as exc:
            self.cache_label.setText(f"Local industrial cache: not initialized ({exc})")
            self.sources_label.setText("Production sources: not loaded")
            self.status_label.setText(
                "Initialize the local industrial cache in the selected Metroliza report database."
            )
            set_status_variant(self.status_label, "warning")
            return

        self.cache_label.setText(
            f"{counts.records} records, {counts.sync_runs} sync runs, {counts.link_candidates} links"
        )
        self.sources_label.setText(f"{len(profiles)} production source(s) configured")
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

    @staticmethod
    def _format_oznak_status() -> str:
        status = get_oznak_adapter_status()
        if not status.available:
            return f"Unavailable ({status.error})"
        version = status.version or "unknown version"
        fetch_state = "fetch ready" if status.fetch_available else "fetch unavailable"
        contract_state = "contracts ready" if status.contracts_available else "contracts incomplete"
        return f"{version}, {contract_state}, {fetch_state}"

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
        self.status_label.setText("Local industrial cache initialized in the Metroliza report database.")
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
        if not self.db_file:
            QMessageBox.warning(
                self,
                self.windowTitle(),
                "Select a Metroliza report database before fetching industrial rows into the cache.",
            )
            self.refresh_status()
            return
        self.sync_window = IndustrialSyncDialog(
            self,
            db_file=self.db_file,
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
            filter_state=self.export_filter_state,
            grouping_state=self.grouping_state,
            include_plots=self.include_plots,
            config_path=self.config_path,
        )
        self.export_window.exec()
        self.refresh_status()

    def open_analytics_dialog(self) -> None:
        if not self.db_file:
            QMessageBox.warning(
                self,
                self.windowTitle(),
                "Select a Metroliza report database before analyzing industrial data.",
            )
            return
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
        self.linking_window = IndustrialLinkingDialog(self, db_file=self.db_file)
        self.linking_window.exec()
        self.refresh_status()

    def refresh_links(self) -> None:
        if not self.db_file:
            self.refresh_status()
            return
        if self.link_refresh_thread is not None and self.link_refresh_thread.isRunning():
            self.status_label.setText("Report-to-production link refresh already running.")
            set_status_variant(self.status_label, "neutral")
            return

        self.status_label.setText("Refreshing report-to-production links...")
        set_status_variant(self.status_label, "neutral")
        self._set_action_buttons_enabled(db_available=False)
        self.link_refresh_thread = IndustrialLinkRefreshThread(self.db_file)
        self.link_refresh_thread.summary_ready.connect(self.on_link_refresh_finished)
        self.link_refresh_thread.error_occurred.connect(self.on_link_refresh_error)
        self.link_refresh_thread.finished.connect(self.on_link_refresh_thread_stopped)
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
        self._set_action_buttons_enabled(db_available=bool(self.db_file))
        self.link_refresh_thread = None

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
                self.analysis_source_combo.addItem("Select report DB", None)
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

    def _set_action_buttons_enabled(self, *, db_available: bool) -> None:
        self.select_database_button.setEnabled(True)
        self.sources_button.setEnabled(True)
        self.initialize_button.setEnabled(db_available)
        self.sync_button.setEnabled(db_available)
        self.links_button.setEnabled(db_available)
        self.export_button.setEnabled(db_available or self._has_configured_sources())
        self.analyze_button.setEnabled(db_available)
        self.refresh_links_button.setEnabled(db_available)

    def _configure_accessibility(self) -> None:
        configure_accessibility(self.database_field, name="Selected Metroliza report database")
        configure_accessibility(self.oznak_label, name="Oznak connector readiness")
        configure_accessibility(self.cache_label, name="Industrial cache readiness")
        configure_accessibility(self.sources_label, name="Production source readiness")
        configure_accessibility(self.sync_filter_label, name="Industrial references-to-fetch summary")
        configure_accessibility(self.export_filter_label, name="Industrial export filter summary")
        configure_accessibility(self.analytics_status_label, name="Industrial CSV Summary readiness")
        configure_accessibility(self.grouping_label, name="Industrial export grouping summary")
        configure_accessibility(self.export_options_label, name="Industrial export option summary")
        configure_accessibility(self.select_database_button, name="Select Metroliza report database")
        configure_accessibility(self.sources_button, name="Open production sources")
        configure_accessibility(self.sync_button, name="Fetch industrial rows into cache")
        configure_accessibility(self.links_button, name="Open production links")
        configure_accessibility(self.export_button, name="Open industrial workbook export")
        configure_accessibility(self.analyze_button, name="Open industrial cache in CSV Summary")
        configure_accessibility(self.initialize_button, name="Initialize industrial cache")
        configure_accessibility(self.refresh_links_button, name="Refresh industrial links")
        configure_accessibility(self.close_button, name="Close industrial data")

        self.setTabOrder(self.select_database_button, self.sources_button)
        self.setTabOrder(self.sources_button, self.sync_button)
        self.setTabOrder(self.sync_button, self.export_button)
        self.setTabOrder(self.export_button, self.analyze_button)
        self.setTabOrder(self.analyze_button, self.initialize_button)
        self.setTabOrder(self.initialize_button, self.refresh_links_button)
        self.setTabOrder(self.refresh_links_button, self.links_button)
        self.setTabOrder(self.links_button, self.close_button)

    def closeEvent(self, event) -> None:
        thread = self.link_refresh_thread
        if thread is not None and thread.isRunning():
            QMessageBox.information(
                self,
                "Industrial data",
                "Wait for report-to-production link refresh to finish.",
            )
            event.ignore()
            return
        super().closeEvent(event)

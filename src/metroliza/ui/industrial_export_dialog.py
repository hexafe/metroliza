"""CSV-summary style export dialog for cached Oznak industrial data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_credentials import load_industrial_credentials, save_industrial_credentials
from metroliza.ui.industrial_filter_dialog import IndustrialFilterDialog
from metroliza.ui.industrial_grouping_dialog import IndustrialGroupingDialog
from metroliza.industrial.industrial_source_config import (
    default_industrial_source_config_path,
    load_source_profiles_from_config,
)
from metroliza.industrial.industrial_workflow_state import IndustrialFilterState, IndustrialGroupingState
from metroliza.industrial.industrial_workers import IndustrialExportThread, IndustrialLiveExportThread
from metroliza.exporting.export_dialog_service import build_export_artifact_link_line
from metroliza.shared.progress_status import build_three_line_status
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_window_size,
    path_field,
    section_label,
    set_status_variant,
    status_chip,
    update_path_field,
)
from metroliza.ui.worker_progress_dialog import create_worker_progress_dialog


class IndustrialExportDialog(QDialog):
    """Configure and run cached or live industrial workbook export."""

    def __init__(
        self,
        parent=None,
        *,
        db_file: str | None = None,
        filter_state: IndustrialFilterState | None = None,
        grouping_state: IndustrialGroupingState | None = None,
        include_plots: bool = True,
        config_path: str | Path | None = None,
    ):
        super().__init__(parent)
        self.db_file = db_file
        self.config_path = Path(config_path or default_industrial_source_config_path()).expanduser()
        self.live_mode = not bool(db_file)
        self._live_profile_load_error = ""
        self._pending_credentials_to_save: tuple[str, str, str] | None = None
        self.output_file = ""
        self.filter_state = filter_state or IndustrialFilterState()
        self.grouping_state = grouping_state or IndustrialGroupingState()
        self.export_thread = None
        self.filter_window = None
        self.grouping_window = None
        self.setWindowTitle("Export industrial data")
        configure_window_size(self, minimum=(620, 420), initial=(780, 560))

        self.database_field = path_field(
            str(db_file or ""),
            empty_text="No Metroliza report database selected",
        )
        self.profile_combo = QComboBox()
        self.cache_status_label = status_chip("Local industrial cache not checked", "neutral")
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.remember_credentials_checkbox = QCheckBox("Remember locally on this computer")
        self.remember_credentials_checkbox.setChecked(True)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 1_000_000)
        self.limit_spin.setValue(5000)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 3600)
        self.timeout_spin.setValue(30)
        self.filter_status_label = status_chip(self.filter_state.summary(), "neutral")
        self.grouping_status_label = status_chip(self.grouping_state.summary(), "neutral")
        self.plot_status_label = status_chip("Plots included", "neutral")
        self.live_fetch_hint_label = status_chip(
            "Fetch row limit and timeout protect large live database exports.",
            "info",
        )
        self.include_plots_checkbox = QCheckBox("Include plots")
        self.include_plots_checkbox.setChecked(bool(include_plots))
        self.output_path_field = path_field("", empty_text="No output workbook selected")
        self.readiness_label = status_chip("Select an output workbook to enable export.", "warning")

        self.edit_filter_button = QPushButton("Edit...")
        self.clear_filter_button = QPushButton("Clear")
        self.edit_grouping_button = QPushButton("Edit...")
        self.clear_grouping_button = QPushButton("Clear")
        self.output_button = QPushButton("Browse")
        self.close_button = QPushButton("Close")
        self.start_button = QPushButton("Create industrial export")

        self.edit_filter_button.clicked.connect(self.open_filter_dialog)
        self.clear_filter_button.clicked.connect(self.clear_filter)
        self.edit_grouping_button.clicked.connect(self.open_grouping_dialog)
        self.clear_grouping_button.clicked.connect(self.clear_grouping)
        self.output_button.clicked.connect(self.select_output_file)
        self.close_button.clicked.connect(self.reject)
        self.start_button.clicked.connect(self.handle_start_button)
        self.include_plots_checkbox.stateChanged.connect(self._sync_ui_state)
        self.profile_combo.currentIndexChanged.connect(self._handle_profile_changed)
        self.username_edit.textChanged.connect(self._sync_ui_state)
        self.password_edit.textChanged.connect(self._sync_ui_state)

        self._build_layout()
        self.reload_live_profiles()
        self._sync_ui_state()
        apply_metroliza_theme(self)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = "Live production workbook" if self.live_mode else "Cached industrial workbook"
        layout.addWidget(section_label(title))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        row = 0
        if self.live_mode:
            grid.addWidget(section_label("Production source"), row, 0)
            grid.addWidget(self.profile_combo, row, 1, 1, 2)

            row += 1
            grid.addWidget(section_label("Source config"), row, 0)
            grid.addWidget(self.cache_status_label, row, 1, 1, 2)

            row += 1
            grid.addWidget(section_label("Production DB username"), row, 0)
            grid.addWidget(self.username_edit, row, 1, 1, 2)

            row += 1
            grid.addWidget(section_label("Production DB password"), row, 0)
            grid.addWidget(self.password_edit, row, 1, 1, 2)

            row += 1
            grid.addWidget(section_label("Credentials"), row, 0)
            grid.addWidget(self.remember_credentials_checkbox, row, 1, 1, 2)

            row += 1
            grid.addWidget(section_label("Fetch row limit"), row, 0)
            grid.addWidget(self.limit_spin, row, 1, 1, 2)

            row += 1
            grid.addWidget(section_label("Timeout seconds"), row, 0)
            grid.addWidget(self.timeout_spin, row, 1, 1, 2)

            row += 1
            grid.addWidget(self.live_fetch_hint_label, row, 1, 1, 2)
        else:
            grid.addWidget(section_label("Metroliza report database"), row, 0)
            grid.addWidget(self.database_field, row, 1, 1, 2)

            row += 1
            grid.addWidget(section_label("Cache"), row, 0)
            grid.addWidget(self.cache_status_label, row, 1, 1, 2)

        row += 1
        filter_actions = QHBoxLayout()
        filter_actions.setContentsMargins(0, 0, 0, 0)
        filter_actions.setSpacing(8)
        filter_actions.addWidget(self.edit_filter_button)
        filter_actions.addWidget(self.clear_filter_button)
        grid.addWidget(section_label("Filter"), row, 0)
        grid.addWidget(self.filter_status_label, row, 1)
        grid.addLayout(filter_actions, row, 2)

        row += 1
        grouping_actions = QHBoxLayout()
        grouping_actions.setContentsMargins(0, 0, 0, 0)
        grouping_actions.setSpacing(8)
        grouping_actions.addWidget(self.edit_grouping_button)
        grouping_actions.addWidget(self.clear_grouping_button)
        grid.addWidget(section_label("Grouping"), row, 0)
        grid.addWidget(self.grouping_status_label, row, 1)
        grid.addLayout(grouping_actions, row, 2)

        row += 1
        grid.addWidget(section_label("Plots"), row, 0)
        grid.addWidget(self.plot_status_label, row, 1)
        grid.addWidget(self.include_plots_checkbox, row, 2)

        row += 1
        grid.addWidget(section_label("Output workbook"), row, 0)
        grid.addWidget(self.output_path_field, row, 1)
        grid.addWidget(self.output_button, row, 2)

        row += 1
        grid.addWidget(self.readiness_label, row, 0, 1, 3)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)

    def _cache_summary(self) -> str:
        if self.live_mode:
            if self._live_profile_load_error:
                return self._live_profile_load_error
            if self.profile_combo.count() > 0:
                return f"{self.profile_combo.count()} production source(s) configured in file"
            return "No production sources configured in the local source file"
        if not self.db_file:
            return "No Metroliza report database selected"
        try:
            counts = IndustrialDataRepository(self.db_file).summarize_counts()
        except Exception as exc:
            return f"Cache unavailable: {exc}"
        return (
            f"{counts.records} cached production rows, {counts.link_candidates} report links, "
            f"{counts.source_profiles} production sources"
        )

    def reload_live_profiles(self) -> None:
        if not self.live_mode:
            return
        self.profile_combo.clear()
        self._live_profile_load_error = ""
        try:
            profiles = load_source_profiles_from_config(self.config_path)
        except Exception as exc:
            self._live_profile_load_error = f"Could not load source config: {exc}"
            return
        for profile in profiles:
            self.profile_combo.addItem(profile.profile_name, profile)
        self._load_stored_credentials_for_current_profile()

    def _sync_ui_state(self) -> None:
        update_path_field(
            self.database_field,
            str(self.db_file or ""),
            empty_text="No Metroliza report database selected",
        )
        update_path_field(self.output_path_field, self.output_file, empty_text="No output workbook selected")
        self.cache_status_label.setText(self._cache_summary())
        self.filter_status_label.setText(self.filter_state.summary())
        self.grouping_status_label.setText(self.grouping_state.summary())
        self.plot_status_label.setText(
            "Plots included" if self.include_plots_checkbox.isChecked() else "Plots disabled"
        )
        self.clear_filter_button.setEnabled(self.filter_state.is_applied)
        self.clear_grouping_button.setEnabled(self.grouping_state.is_applied)
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_include_plots_state"):
            parent.set_include_plots_state(self.include_plots_checkbox.isChecked())
        set_status_variant(self.filter_status_label, "success" if self.filter_state.is_applied else "neutral")
        set_status_variant(self.grouping_status_label, "success" if self.grouping_state.is_applied else "neutral")
        set_status_variant(self.plot_status_label, "neutral")

        ready = bool(self.output_file)
        if self.live_mode:
            ready = ready and self.current_profile() is not None and bool(
                self.username_edit.text().strip()
            ) and bool(self.password_edit.text())
        else:
            ready = ready and bool(self.db_file)
        self.start_button.setEnabled(ready)
        if ready:
            if self.live_mode:
                self.readiness_label.setText(
                    "Ready to fetch production rows directly and create the workbook."
                )
            else:
                self.readiness_label.setText(
                    "Ready to create industrial workbook from cached production rows."
                )
            set_status_variant(self.readiness_label, "success")
        elif self.live_mode:
            if self.current_profile() is None:
                self.readiness_label.setText("Create a production source before exporting.")
            elif not self.username_edit.text().strip() or not self.password_edit.text():
                self.readiness_label.setText("Enter production database credentials to enable export.")
            else:
                self.readiness_label.setText("Select an output workbook to enable export.")
            set_status_variant(self.readiness_label, "warning")
        elif self.db_file:
            self.readiness_label.setText("Select an output workbook to enable export.")
            set_status_variant(self.readiness_label, "warning")
        else:
            self.readiness_label.setText("Select a Metroliza report database before exporting.")
            set_status_variant(self.readiness_label, "warning")

    def set_industrial_filter_state(self, state: IndustrialFilterState) -> None:
        self.filter_state = state
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_export_filter_state"):
            parent.set_export_filter_state(state)
        self._sync_ui_state()

    def current_profile(self):
        profile = self.profile_combo.currentData()
        return profile if self.live_mode and profile is not None else None

    def _handle_profile_changed(self, _index: int) -> None:
        self._load_stored_credentials_for_current_profile()
        self._sync_ui_state()

    def _load_stored_credentials_for_current_profile(self) -> None:
        profile = self.current_profile()
        self.username_edit.blockSignals(True)
        self.password_edit.blockSignals(True)
        try:
            if profile is None:
                self.username_edit.clear()
                self.password_edit.clear()
                return
            stored = load_industrial_credentials(profile.profile_key)
            self.username_edit.setText(stored.username or "")
            self.password_edit.setText(stored.password or "")
        finally:
            self.username_edit.blockSignals(False)
            self.password_edit.blockSignals(False)

    def _read_live_credentials(self) -> tuple[str, str]:
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username:
            raise ValueError("Enter the production database username.")
        if not password:
            raise ValueError("Enter the production database password.")
        return username, password

    def set_industrial_grouping_state(self, state: IndustrialGroupingState) -> None:
        self.grouping_state = state
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_industrial_grouping_state"):
            parent.set_industrial_grouping_state(state)
        self._sync_ui_state()

    def clear_filter(self) -> None:
        self.set_industrial_filter_state(IndustrialFilterState())

    def clear_grouping(self) -> None:
        self.set_industrial_grouping_state(IndustrialGroupingState())

    def open_filter_dialog(self) -> None:
        self.filter_window = IndustrialFilterDialog(self, db_file=self.db_file, state=self.filter_state)
        self.filter_window.exec()

    def open_grouping_dialog(self) -> None:
        self.grouping_window = IndustrialGroupingDialog(self, state=self.grouping_state)
        self.grouping_window.exec()

    def select_output_file(self) -> None:
        default_path = Path("industrial_data.xlsx")
        if self.output_file:
            default_path = Path(self.output_file)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export industrial data",
            str(default_path),
            "Excel workbook (*.xlsx);;All files (*)",
        )
        if filename:
            selected = Path(filename)
            if selected.suffix.lower() != ".xlsx":
                selected = selected.with_suffix(".xlsx")
            self.output_file = str(selected)
            self._sync_ui_state()

    def handle_start_button(self) -> None:
        self._sync_ui_state()
        if not self.start_button.isEnabled():
            return
        try:
            self.show_loading_screen()
        except Exception as exc:
            QMessageBox.warning(self, "Industrial export", f"Could not start export: {exc}")

    def create_export_thread(self) -> IndustrialExportThread:
        self._pending_credentials_to_save = None
        if self.live_mode:
            profile = self.current_profile()
            if profile is None:
                raise ValueError("Create or select a production source before exporting.")
            username, password = self._read_live_credentials()
            if self.remember_credentials_checkbox.isChecked():
                self._pending_credentials_to_save = (profile.profile_key, username, password)
            return IndustrialLiveExportThread(
                profile=profile,
                username=username,
                password=password,
                output_file=self.output_file,
                limit=self.limit_spin.value(),
                timeout_seconds=self.timeout_spin.value(),
                filter_state=self.filter_state,
                grouping_state=self.grouping_state,
                include_charts=self.include_plots_checkbox.isChecked(),
            )
        return IndustrialExportThread(
            db_file=str(self.db_file),
            output_file=self.output_file,
            filter_state=self.filter_state,
            grouping_state=self.grouping_state,
            include_charts=self.include_plots_checkbox.isChecked(),
        )

    def show_loading_screen(self) -> None:
        export_thread = self.create_export_thread()
        self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif = (
            create_worker_progress_dialog(
                self,
                window_title="Exporting industrial data...",
                initial_status_text=build_three_line_status(
                    (
                        "Fetching production rows..."
                        if self.live_mode
                        else "Exporting cached industrial data..."
                    ),
                    (
                        "Creating workbook from live Oznak data"
                        if self.live_mode
                        else "Creating workbook from local Metroliza cache"
                    ),
                    "ETA --",
                ),
                on_cancel=self.cancel_export,
            )
        )
        self.loading_bar.setValue(0)
        self.export_thread = export_thread
        self.export_thread.result_ready.connect(self.on_export_finished)
        self.export_thread.error_occurred.connect(self.on_export_error)
        self.export_thread.cancelled.connect(self.on_export_cancelled)
        if hasattr(self.export_thread, "update_label"):
            self.export_thread.update_label.connect(self.loading_label.setText)
        self.export_thread.finished.connect(self.on_export_thread_stopped)
        self.export_thread.start()
        self.loading_dialog.show()

    def cancel_export(self) -> None:
        thread = self.export_thread
        if thread is not None and thread.isRunning():
            thread.cancel()
            self.loading_label.setText("Cancel requested. Waiting for workbook writer to stop.")

    def on_export_finished(self, result: dict[str, Any]) -> None:
        if hasattr(self, "loading_bar"):
            self.loading_bar.setValue(100)
        output_file = str(result.get("output_file") or self.output_file)
        workbook_line = build_export_artifact_link_line("Industrial workbook", output_file)
        message_lines = [
            "Industrial export complete.",
            "",
            workbook_line,
            "",
            f"Rows: {result['row_count']}",
            f"Summary rows: {result['summary_rows']}",
        ]
        credential_save_error = self._save_pending_credentials_after_success()
        try:
            from metroliza.ui.export_dialog import show_export_result_message

            show_export_result_message(
                self,
                "info",
                "Industrial export complete",
                "\n".join(line for line in message_lines if line is not None),
                excel_file=output_file,
            )
        except Exception:
            QMessageBox.information(
                self,
                "Industrial export complete",
                "\n".join(line for line in message_lines if line),
            )
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_status"):
            parent.refresh_status()
        if credential_save_error:
            QMessageBox.warning(
                self,
                "Industrial export",
                f"Export completed, but credentials could not be saved: {credential_save_error}",
            )

    def on_export_error(self, message: str) -> None:
        self._pending_credentials_to_save = None
        QMessageBox.warning(self, "Industrial export", f"Could not export industrial data: {message}")

    def on_export_cancelled(self, message: str) -> None:
        self._pending_credentials_to_save = None
        QMessageBox.information(self, "Industrial export", message or "Industrial export was cancelled.")

    def on_export_thread_stopped(self) -> None:
        if hasattr(self, "loading_dialog"):
            self.loading_dialog.close()
        self.export_thread = None
        self._sync_ui_state()

    def _save_pending_credentials_after_success(self) -> str | None:
        pending = self._pending_credentials_to_save
        self._pending_credentials_to_save = None
        if pending is None:
            return None
        profile_key, username, password = pending
        try:
            save_industrial_credentials(
                profile_key,
                username=username,
                password=password,
            )
        except Exception as exc:
            return str(exc)
        return None

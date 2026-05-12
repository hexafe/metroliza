"""CSV-summary style export dialog for cached Oznak industrial data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from modules.industrial_data_repository import IndustrialDataRepository
from modules.industrial_filter_dialog import IndustrialFilterDialog
from modules.industrial_grouping_dialog import IndustrialGroupingDialog
from modules.industrial_workflow_state import IndustrialFilterState, IndustrialGroupingState
from modules.industrial_workers import IndustrialExportThread
from modules.export_dialog_service import build_export_artifact_link_line
from modules.progress_status import build_three_line_status
from modules.ui_foundation import (
    apply_metroliza_theme,
    configure_window_size,
    path_field,
    section_label,
    set_status_variant,
    status_chip,
    update_path_field,
)
from modules.worker_progress_dialog import create_worker_progress_dialog


class IndustrialExportDialog(QDialog):
    """Configure and run cached industrial workbook export."""

    def __init__(
        self,
        parent=None,
        *,
        db_file: str | None = None,
        filter_state: IndustrialFilterState | None = None,
        grouping_state: IndustrialGroupingState | None = None,
        include_plots: bool = True,
    ):
        super().__init__(parent)
        self.db_file = db_file
        self.output_file = ""
        self.filter_state = filter_state or IndustrialFilterState()
        self.grouping_state = grouping_state or IndustrialGroupingState()
        self.export_thread = None
        self.filter_window = None
        self.grouping_window = None
        self.setWindowTitle("Export industrial data")
        configure_window_size(self, minimum=(620, 380), initial=(760, 430))

        self.database_field = path_field(
            str(db_file or ""),
            empty_text="No Metroliza report database selected",
        )
        self.cache_status_label = status_chip("Local industrial cache not checked", "neutral")
        self.filter_status_label = status_chip(self.filter_state.summary(), "neutral")
        self.grouping_status_label = status_chip(self.grouping_state.summary(), "neutral")
        self.plot_status_label = status_chip("Plots included", "neutral")
        self.include_plots_checkbox = QCheckBox("Include plots")
        self.include_plots_checkbox.setChecked(bool(include_plots))
        self.output_path_field = path_field("", empty_text="No output workbook selected")
        self.readiness_label = status_chip("Select an output workbook to enable export.", "warning")

        self.edit_filter_button = QPushButton("Edit...")
        self.edit_grouping_button = QPushButton("Edit...")
        self.output_button = QPushButton("Browse")
        self.close_button = QPushButton("Close")
        self.start_button = QPushButton("Create industrial export")

        self.edit_filter_button.clicked.connect(self.open_filter_dialog)
        self.edit_grouping_button.clicked.connect(self.open_grouping_dialog)
        self.output_button.clicked.connect(self.select_output_file)
        self.close_button.clicked.connect(self.reject)
        self.start_button.clicked.connect(self.handle_start_button)
        self.include_plots_checkbox.stateChanged.connect(self._sync_ui_state)

        self._build_layout()
        self._sync_ui_state()
        apply_metroliza_theme(self)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(section_label("Cached industrial workbook"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        row = 0
        grid.addWidget(section_label("Metroliza report database"), row, 0)
        grid.addWidget(self.database_field, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Cache"), row, 0)
        grid.addWidget(self.cache_status_label, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Filter"), row, 0)
        grid.addWidget(self.filter_status_label, row, 1)
        grid.addWidget(self.edit_filter_button, row, 2)

        row += 1
        grid.addWidget(section_label("Grouping"), row, 0)
        grid.addWidget(self.grouping_status_label, row, 1)
        grid.addWidget(self.edit_grouping_button, row, 2)

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
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_include_plots_state"):
            parent.set_include_plots_state(self.include_plots_checkbox.isChecked())
        set_status_variant(self.filter_status_label, "success" if self.filter_state.is_applied else "neutral")
        set_status_variant(self.grouping_status_label, "success" if self.grouping_state.is_applied else "neutral")
        set_status_variant(self.plot_status_label, "neutral")

        ready = bool(self.db_file and self.output_file)
        self.start_button.setEnabled(ready)
        if ready:
            self.readiness_label.setText(
                "Ready to create industrial workbook from cached production rows."
            )
            set_status_variant(self.readiness_label, "success")
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

    def set_industrial_grouping_state(self, state: IndustrialGroupingState) -> None:
        self.grouping_state = state
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_industrial_grouping_state"):
            parent.set_industrial_grouping_state(state)
        self._sync_ui_state()

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
        self.show_loading_screen()

    def create_export_thread(self) -> IndustrialExportThread:
        return IndustrialExportThread(
            db_file=str(self.db_file),
            output_file=self.output_file,
            filter_state=self.filter_state,
            grouping_state=self.grouping_state,
            include_charts=self.include_plots_checkbox.isChecked(),
        )

    def show_loading_screen(self) -> None:
        self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif = (
            create_worker_progress_dialog(
                self,
                window_title="Exporting industrial data...",
                initial_status_text=build_three_line_status(
                    "Exporting cached industrial data...",
                    "Creating workbook from local Metroliza cache",
                    "ETA --",
                ),
                on_cancel=self.cancel_export,
            )
        )
        self.loading_bar.setValue(0)
        self.export_thread = self.create_export_thread()
        self.export_thread.result_ready.connect(self.on_export_finished)
        self.export_thread.error_occurred.connect(self.on_export_error)
        self.export_thread.cancelled.connect(self.on_export_cancelled)
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
        try:
            from modules.export_dialog import show_export_result_message

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

    def on_export_error(self, message: str) -> None:
        QMessageBox.warning(self, "Industrial export", f"Could not export industrial data: {message}")

    def on_export_cancelled(self, message: str) -> None:
        QMessageBox.information(self, "Industrial export", message or "Industrial export was cancelled.")

    def on_export_thread_stopped(self) -> None:
        if hasattr(self, "loading_dialog"):
            self.loading_dialog.close()
        self.export_thread = None
        self._sync_ui_state()

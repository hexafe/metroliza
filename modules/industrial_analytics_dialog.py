"""Compact analytics dialog for cached production and CSV/Excel data."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from modules.industrial_analytics_service import discover_production_metric_candidates
from modules.industrial_analytics_filter_dialog import IndustrialAnalyticsFilterDialog
from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionFilterState,
    ProductionMetricSelection,
    ReferenceCohortState,
)
from modules.industrial_analytics_workflow import default_dashboard_path, default_workbook_path
from modules.industrial_data_repository import IndustrialDataRepository
from modules.industrial_workers import IndustrialAnalyticsThread
from modules.progress_status import build_three_line_status
from modules.tabular_analytics_service import load_tabular_analytics_file
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

SOURCE_PRODUCTION_CACHE = "production_cache"
SOURCE_TABULAR_FILE = "tabular_file"


class IndustrialAnalyticsDialog(QDialog):
    """Configure and run production or CSV/Excel analytics."""

    def __init__(
        self,
        parent=None,
        *,
        db_file: str | None = None,
        source_kind: str = SOURCE_PRODUCTION_CACHE,
    ):
        super().__init__(parent)
        self.db_file = db_file or ""
        self.source_kind = source_kind
        self.input_file = ""
        self.output_dashboard_file = default_dashboard_path(self.db_file or "production_analytics")
        self.output_workbook_file = default_workbook_path(self.db_file or "production_analytics")
        self.analytics_thread = None
        self.metric_candidates: tuple[ProductionMetricSelection, ...] = ()
        self.filter_state = ProductionFilterState()

        self.setWindowTitle("Production analytics" if self.is_production_source else "CSV / Excel analytics")
        configure_window_size(self, minimum=(720, 560), initial=(880, 680))

        self.source_label = status_chip(self._source_summary(), "neutral")
        self.database_row_label = section_label("Report database")
        self.input_file_row_label = section_label("CSV/Excel file")
        self.sheet_name_row_label = section_label("Excel sheet")
        self.timestamp_column_row_label = section_label("Time column")
        self.reference_column_row_label = section_label("Reference column")
        self.database_field = path_field(self.db_file, empty_text="No Metroliza report database selected")
        self.input_file_field = path_field("", empty_text="No CSV/Excel file selected")
        self.dashboard_path_field = path_field(
            self.output_dashboard_file,
            empty_text="No dashboard path selected",
        )
        self.workbook_path_field = path_field(
            self.output_workbook_file,
            empty_text="No workbook path selected",
        )
        self.readiness_label = status_chip("Load metrics and choose an output path.", "warning")
        self.filter_row_label = section_label("Filters")
        self.filter_summary_label = status_chip(self.filter_state.summary(), "neutral")

        self.sheet_name_combo = QComboBox()
        self.sheet_name_combo.setEditable(True)
        self.sheet_name_combo.addItem("First sheet", "")
        self.sheet_name_combo.currentTextChanged.connect(self._handle_tabular_source_changed)
        self.timestamp_column_combo = QComboBox()
        self.reference_column_combo = QComboBox()
        self._reset_tabular_column_options()

        self.metrics_list = QListWidget()
        self.metrics_list.setMinimumHeight(120)
        self.metrics_list.itemChanged.connect(lambda _item: self._sync_ui_state())

        self.group_field_combo = QComboBox()
        self.time_bucket_combo = QComboBox()
        for value, label in (
            ("none", "Raw rows"),
            ("hour", "Hour"),
            ("day", "Day"),
            ("week", "Week"),
            ("month", "Month"),
            ("year", "Year"),
        ):
            self.time_bucket_combo.addItem(label, value)
        self.aggregation_combo = QComboBox()
        for method in ("mean", "median", "count", "sum", "min", "max", "std", "p05", "p95"):
            self.aggregation_combo.addItem(method.upper() if method.startswith("p") else method.title(), method)

        self.reference_mode_combo = QComboBox()
        for value, label in (
            ("highlight", "Highlight"),
            ("compare_rest", "Compare selected vs rest"),
            ("filter_selected", "Analyze selected only"),
            ("group_selected", "Create selected group"),
        ):
            self.reference_mode_combo.addItem(label, value)
        self.references_edit = QPlainTextEdit()
        self.references_edit.setPlaceholderText("Paste references or IDs to mark/filter, one per line")
        self.references_edit.setMaximumHeight(90)

        self.time_series_checkbox = QCheckBox("Time series")
        self.histogram_checkbox = QCheckBox("Histogram")
        self.violin_checkbox = QCheckBox("Violin")
        self.box_checkbox = QCheckBox("Box")
        self.groupstats_checkbox = QCheckBox("Groupstats")
        self.workbook_checkbox = QCheckBox("Create workbook")
        self.parameter_sheets_checkbox = QCheckBox("Separate sheet per selected parameter")
        self.time_series_checkbox.setChecked(True)
        self.histogram_checkbox.setChecked(True)
        self.violin_checkbox.setChecked(True)
        self.box_checkbox.setChecked(True)
        self.groupstats_checkbox.setChecked(True)
        self.workbook_checkbox.setChecked(True)
        self.parameter_sheets_checkbox.setChecked(True)

        self.browse_input_button = QPushButton("Browse")
        self.filters_button = QPushButton("Filters...")
        self.load_metrics_button = QPushButton("Load metrics")
        self.select_all_metrics_button = QPushButton("Select all")
        self.clear_metrics_button = QPushButton("Clear")
        self.dashboard_button = QPushButton("Browse")
        self.workbook_button = QPushButton("Browse")
        self.close_button = QPushButton("Close")
        self.start_button = QPushButton("Create analytics")
        self.start_button.setDefault(True)

        self.browse_input_button.clicked.connect(self.select_input_file)
        self.filters_button.clicked.connect(self.open_filters_dialog)
        self.load_metrics_button.clicked.connect(self.load_metrics)
        self.select_all_metrics_button.clicked.connect(lambda: self._set_metric_checks(True))
        self.clear_metrics_button.clicked.connect(lambda: self._set_metric_checks(False))
        self.dashboard_button.clicked.connect(self.select_dashboard_file)
        self.workbook_button.clicked.connect(self.select_workbook_file)
        self.close_button.clicked.connect(self.reject)
        self.start_button.clicked.connect(self.handle_start_button)
        for checkbox in (
            self.time_series_checkbox,
            self.histogram_checkbox,
            self.violin_checkbox,
            self.box_checkbox,
            self.groupstats_checkbox,
            self.workbook_checkbox,
        ):
            checkbox.stateChanged.connect(lambda _state: self._sync_ui_state())

        self._build_layout()
        self._sync_source_visibility()
        self._reset_group_options(())
        self._sync_ui_state()
        apply_metroliza_theme(self)

    @property
    def is_production_source(self) -> bool:
        return self.source_kind != SOURCE_TABULAR_FILE

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(section_label("Analytics source"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        row = 0
        grid.addWidget(section_label("Source"), row, 0)
        grid.addWidget(self.source_label, row, 1, 1, 2)

        row += 1
        grid.addWidget(self.filter_row_label, row, 0)
        grid.addWidget(self.filter_summary_label, row, 1)
        grid.addWidget(self.filters_button, row, 2)

        row += 1
        grid.addWidget(self.database_row_label, row, 0)
        grid.addWidget(self.database_field, row, 1, 1, 2)

        row += 1
        grid.addWidget(self.input_file_row_label, row, 0)
        grid.addWidget(self.input_file_field, row, 1)
        grid.addWidget(self.browse_input_button, row, 2)

        row += 1
        grid.addWidget(self.sheet_name_row_label, row, 0)
        grid.addWidget(self.sheet_name_combo, row, 1, 1, 2)

        row += 1
        grid.addWidget(self.timestamp_column_row_label, row, 0)
        grid.addWidget(self.timestamp_column_combo, row, 1, 1, 2)

        row += 1
        grid.addWidget(self.reference_column_row_label, row, 0)
        grid.addWidget(self.reference_column_combo, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Metrics"), row, 0)
        grid.addWidget(self.metrics_list, row, 1, 1, 2)

        row += 1
        metric_actions = QHBoxLayout()
        metric_actions.setContentsMargins(0, 0, 0, 0)
        metric_actions.setSpacing(8)
        metric_actions.addWidget(self.load_metrics_button)
        metric_actions.addWidget(self.select_all_metrics_button)
        metric_actions.addWidget(self.clear_metrics_button)
        metric_actions.addStretch(1)
        grid.addLayout(metric_actions, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Group by"), row, 0)
        grid.addWidget(self.group_field_combo, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Time bucket"), row, 0)
        grid.addWidget(self.time_bucket_combo, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Aggregation"), row, 0)
        grid.addWidget(self.aggregation_combo, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Reference mode"), row, 0)
        grid.addWidget(self.reference_mode_combo, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("References"), row, 0)
        grid.addWidget(self.references_edit, row, 1, 1, 2)

        row += 1
        chart_actions = QHBoxLayout()
        chart_actions.setContentsMargins(0, 0, 0, 0)
        chart_actions.setSpacing(10)
        for checkbox in (
            self.time_series_checkbox,
            self.histogram_checkbox,
            self.violin_checkbox,
            self.box_checkbox,
            self.groupstats_checkbox,
        ):
            chart_actions.addWidget(checkbox)
        chart_actions.addStretch(1)
        grid.addWidget(section_label("Outputs"), row, 0)
        grid.addLayout(chart_actions, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Dashboard"), row, 0)
        grid.addWidget(self.dashboard_path_field, row, 1)
        grid.addWidget(self.dashboard_button, row, 2)

        row += 1
        grid.addWidget(section_label("Workbook"), row, 0)
        grid.addWidget(self.workbook_path_field, row, 1)
        grid.addWidget(self.workbook_button, row, 2)

        row += 1
        workbook_options = QHBoxLayout()
        workbook_options.setContentsMargins(0, 0, 0, 0)
        workbook_options.setSpacing(10)
        workbook_options.addWidget(self.workbook_checkbox)
        workbook_options.addWidget(self.parameter_sheets_checkbox)
        workbook_options.addStretch(1)
        grid.addLayout(workbook_options, row, 1, 1, 2)

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

    def _source_summary(self) -> str:
        if self.is_production_source:
            return "Cached Oznak production data"
        return "CSV or Excel table"

    def _sync_source_visibility(self) -> None:
        show_file = not self.is_production_source
        self.input_file_row_label.setVisible(show_file)
        self.sheet_name_row_label.setVisible(show_file)
        self.timestamp_column_row_label.setVisible(show_file)
        self.reference_column_row_label.setVisible(show_file)
        for widget in (
            self.input_file_field,
            self.browse_input_button,
            self.sheet_name_combo,
            self.timestamp_column_combo,
            self.reference_column_combo,
        ):
            widget.setVisible(show_file)
        self.filter_row_label.setVisible(self.is_production_source)
        self.filter_summary_label.setVisible(self.is_production_source)
        self.filters_button.setVisible(self.is_production_source)
        self.database_row_label.setVisible(self.is_production_source)
        self.database_field.setVisible(self.is_production_source)
        self._sync_filter_summary()

    def _sync_filter_summary(self) -> None:
        self.filter_summary_label.setText(self.filter_state.summary())
        set_status_variant(self.filter_summary_label, "info" if self.filter_state.is_applied else "neutral")

    def _handle_tabular_source_changed(self, _text: str = "") -> None:
        if self.is_production_source:
            return
        self.metric_candidates = ()
        self.metrics_list.clear()
        self._reset_group_options(())
        self._reset_tabular_column_options()
        self._sync_ui_state()

    def _reset_tabular_column_options(self) -> None:
        for combo in (self.timestamp_column_combo, self.reference_column_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Auto detect", "")
            combo.blockSignals(False)

    def _populate_tabular_column_options(
        self,
        column_mapping: dict[str, str],
        *,
        timestamp_column: str | None,
        reference_column: str | None,
    ) -> None:
        for combo, selected_column in (
            (self.timestamp_column_combo, timestamp_column),
            (self.reference_column_combo, reference_column),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Auto detect", "")
            for original, normalized in column_mapping.items():
                label = original if original == normalized else f"{original} ({normalized})"
                combo.addItem(label, normalized)
            index = combo.findData(selected_column or "")
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _selected_tabular_column(self, combo: QComboBox) -> str | None:
        if self.is_production_source:
            return None
        value = str(combo.currentData() or "").strip()
        return value or None

    def _cache_summary(self) -> str:
        if not self.db_file:
            return "No Metroliza report database selected"
        try:
            counts = IndustrialDataRepository(self.db_file).summarize_counts()
        except Exception as exc:
            return f"Cache unavailable: {exc}"
        return f"Cached production rows: {counts.records}; sources: {counts.source_profiles}"

    def select_input_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open CSV or Excel data",
            self.input_file or "",
            "CSV / Excel (*.csv *.xlsx *.xls);;CSV (*.csv);;Excel (*.xlsx *.xls);;All files (*)",
        )
        if not filename:
            return
        self.input_file = filename
        self.output_dashboard_file = default_dashboard_path(filename)
        self.output_workbook_file = default_workbook_path(filename)
        self.metric_candidates = ()
        self.metrics_list.clear()
        self._reset_tabular_column_options()
        self._reset_group_options(())
        self._sync_ui_state()

    def open_filters_dialog(self) -> None:
        dialog = IndustrialAnalyticsFilterDialog(self, filter_state=self.filter_state)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.filter_state = dialog.filter_state
        self.metric_candidates = ()
        self.metrics_list.clear()
        self._reset_group_options(())
        self._sync_filter_summary()
        self._sync_ui_state()

    def select_dashboard_file(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save analytics dashboard",
            self.output_dashboard_file,
            "HTML dashboard (*.html);;All files (*)",
        )
        if filename:
            path = Path(filename)
            self.output_dashboard_file = str(path if path.suffix.lower() == ".html" else path.with_suffix(".html"))
            self._sync_ui_state()

    def select_workbook_file(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save analytics workbook",
            self.output_workbook_file,
            "Excel workbook (*.xlsx);;All files (*)",
        )
        if filename:
            path = Path(filename)
            self.output_workbook_file = str(path if path.suffix.lower() == ".xlsx" else path.with_suffix(".xlsx"))
            self._sync_ui_state()

    def load_metrics(self) -> None:
        try:
            if self.is_production_source:
                if not self.db_file:
                    raise ValueError("Select a Metroliza report database first.")
                candidates = discover_production_metric_candidates(
                    self.db_file,
                    filter_state=self.filter_state,
                )
                self.metric_candidates = tuple(candidate.to_selection() for candidate in candidates)
                self._reset_group_options(
                    (
                        ("Reference", "reference"),
                        ("Reference cohort", "reference_cohort"),
                        ("Station", "station"),
                        ("Line", "line"),
                        ("Operator", "operator_name"),
                        ("Status", "process_status"),
                        ("Source", "source_db_alias"),
                    )
                )
                self.source_label.setText(self._cache_summary())
                self._sync_filter_summary()
            else:
                if not self.input_file:
                    raise ValueError("Select a CSV or Excel file first.")
                sheet_name = self._selected_sheet_name()
                loaded = load_tabular_analytics_file(
                    self.input_file,
                    sheet_name=sheet_name,
                    timestamp_column=self._selected_tabular_column(self.timestamp_column_combo),
                    reference_column=self._selected_tabular_column(self.reference_column_combo),
                )
                self.metric_candidates = tuple(candidate.to_selection() for candidate in loaded.metric_candidates)
                self._reset_group_options(
                    tuple(
                        (column.replace("_", " ").title(), column)
                        for column in loaded.dataframe.columns
                        if column not in {metric.field_name for metric in self.metric_candidates}
                    )
                )
                self.source_label.setText(
                    f"{Path(self.input_file).name}: {len(loaded.dataframe.index)} rows"
                )
                self._populate_tabular_column_options(
                    loaded.column_mapping,
                    timestamp_column=loaded.timestamp_column,
                    reference_column=loaded.reference_column,
                )
        except Exception as exc:
            QMessageBox.warning(self, self.windowTitle(), f"Could not load metrics: {exc}")
            self._sync_ui_state()
            return

        self._populate_metrics()
        self._sync_ui_state()

    def _populate_metrics(self) -> None:
        self.metrics_list.blockSignals(True)
        self.metrics_list.clear()
        for metric in self.metric_candidates:
            item = QListWidgetItem(metric.display_label)
            item.setData(Qt.ItemDataRole.UserRole, metric)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.metrics_list.addItem(item)
        self.metrics_list.blockSignals(False)

    def _set_metric_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(self.metrics_list.count()):
            self.metrics_list.item(index).setCheckState(state)
        self._sync_ui_state()

    def _reset_group_options(self, options: tuple[tuple[str, str], ...]) -> None:
        self.group_field_combo.clear()
        self.group_field_combo.addItem("None", "")
        seen = {""}
        for label, value in options:
            if not value or value in seen:
                continue
            seen.add(value)
            self.group_field_combo.addItem(label, value)

    def _selected_metrics(self) -> tuple[ProductionMetricSelection, ...]:
        metrics = []
        for index in range(self.metrics_list.count()):
            item = self.metrics_list.item(index)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            metric = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(metric, ProductionMetricSelection):
                metrics.append(metric)
        return tuple(metrics)

    def _selected_sheet_name(self) -> str | None:
        if self.is_production_source:
            return None
        text = self.sheet_name_combo.currentText().strip()
        return text if text and text != "First sheet" else None

    def _aggregation_state(self) -> ProductionAggregationState:
        group_field = str(self.group_field_combo.currentData() or "").strip()
        return ProductionAggregationState(
            time_bucket=str(self.time_bucket_combo.currentData() or "none"),
            aggregation_methods=(str(self.aggregation_combo.currentData() or "mean"),),
            group_fields=(group_field,) if group_field else (),
        )

    def _cohort_state(self) -> ReferenceCohortState:
        return ReferenceCohortState.from_text(
            self.references_edit.toPlainText(),
            mode=str(self.reference_mode_combo.currentData() or "highlight"),
        )

    def _chart_selection(self) -> ProductionChartSelection:
        return ProductionChartSelection(
            time_series=self.time_series_checkbox.isChecked(),
            histogram=self.histogram_checkbox.isChecked(),
            violin=self.violin_checkbox.isChecked(),
            box=self.box_checkbox.isChecked(),
            groupstats=self.groupstats_checkbox.isChecked(),
        )

    def _sync_ui_state(self) -> None:
        update_path_field(self.database_field, self.db_file, empty_text="No Metroliza report database selected")
        update_path_field(self.input_file_field, self.input_file, empty_text="No CSV/Excel file selected")
        update_path_field(
            self.dashboard_path_field,
            self.output_dashboard_file,
            empty_text="No dashboard path selected",
        )
        update_path_field(
            self.workbook_path_field,
            self.output_workbook_file if self.workbook_checkbox.isChecked() else "",
            empty_text="Workbook disabled",
        )
        self.workbook_button.setEnabled(self.workbook_checkbox.isChecked())
        self.parameter_sheets_checkbox.setEnabled(self.workbook_checkbox.isChecked())

        metrics = self._selected_metrics()
        source_ready = bool(self.db_file) if self.is_production_source else bool(self.input_file)
        charts_ready = self._chart_selection().has_any
        workbook_ready = not self.workbook_checkbox.isChecked() or bool(self.output_workbook_file)
        ready = bool(source_ready and metrics and self.output_dashboard_file and charts_ready and workbook_ready)
        self.start_button.setEnabled(ready)
        if ready:
            self.readiness_label.setText(
                f"Ready: {len(metrics)} metric(s), dashboard"
                + (", workbook." if self.workbook_checkbox.isChecked() else ".")
            )
            set_status_variant(self.readiness_label, "success")
        elif not source_ready:
            self.readiness_label.setText("Select a source before creating analytics.")
            set_status_variant(self.readiness_label, "warning")
        elif not metrics:
            self.readiness_label.setText("Load metrics and select at least one parameter.")
            set_status_variant(self.readiness_label, "warning")
        elif not charts_ready:
            self.readiness_label.setText("Select at least one chart or groupstats output.")
            set_status_variant(self.readiness_label, "warning")
        else:
            self.readiness_label.setText("Select output paths before creating analytics.")
            set_status_variant(self.readiness_label, "warning")

    def handle_start_button(self) -> None:
        if not self.metric_candidates:
            self.load_metrics()
        self._sync_ui_state()
        if not self.start_button.isEnabled():
            return
        self.show_loading_screen()

    def create_analytics_thread(self) -> IndustrialAnalyticsThread:
        return IndustrialAnalyticsThread(
            source_kind=self.source_kind,
            db_file=self.db_file,
            input_file=self.input_file,
            output_dashboard_file=self.output_dashboard_file,
            output_workbook_file=self.output_workbook_file if self.workbook_checkbox.isChecked() else "",
            metric_selection=self._selected_metrics(),
            filter_state=self.filter_state,
            aggregation_state=self._aggregation_state(),
            cohort_state=self._cohort_state(),
            chart_selection=self._chart_selection(),
            separate_parameter_sheets=self.parameter_sheets_checkbox.isChecked(),
            sheet_name=self._selected_sheet_name(),
            timestamp_column=self._selected_tabular_column(self.timestamp_column_combo),
            reference_column=self._selected_tabular_column(self.reference_column_combo),
        )

    def show_loading_screen(self) -> None:
        self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif = (
            create_worker_progress_dialog(
                self,
                window_title="Creating analytics...",
                initial_status_text=build_three_line_status(
                    "Creating analytics dashboard...",
                    "Aggregating selected metrics and writing outputs",
                    "ETA --",
                ),
                on_cancel=self.cancel_analytics,
            )
        )
        self.loading_bar.setRange(0, 0)
        self.analytics_thread = self.create_analytics_thread()
        self.analytics_thread.result_ready.connect(self.on_analytics_finished)
        self.analytics_thread.error_occurred.connect(self.on_analytics_error)
        self.analytics_thread.cancelled.connect(self.on_analytics_cancelled)
        self.analytics_thread.finished.connect(self.on_analytics_thread_stopped)
        self.analytics_thread.start()
        self.loading_dialog.show()

    def cancel_analytics(self) -> None:
        if self.analytics_thread is not None:
            self.analytics_thread.cancel()
        if hasattr(self, "loading_label"):
            self.loading_label.setText("Canceling analytics after the current step...")

    def on_analytics_finished(self, result) -> None:
        if hasattr(self, "loading_dialog"):
            self.loading_dialog.close()
        message = (
            f"Dashboard: {result.html_dashboard_path}\n"
            f"Charts: {result.html_dashboard_chart_count}\n"
            f"Rows analyzed: {result.row_count}"
        )
        if result.workbook_path:
            message += f"\nWorkbook: {result.workbook_path}"
        QMessageBox.information(self, self.windowTitle(), message)

    def on_analytics_error(self, message: str) -> None:
        if hasattr(self, "loading_dialog"):
            self.loading_dialog.close()
        QMessageBox.warning(self, self.windowTitle(), f"Could not create analytics: {message}")

    def on_analytics_cancelled(self, message: str) -> None:
        if hasattr(self, "loading_dialog"):
            self.loading_dialog.close()
        QMessageBox.information(self, self.windowTitle(), message or "Analytics generation was canceled.")

    def on_analytics_thread_stopped(self) -> None:
        self.analytics_thread = None
        self._sync_ui_state()

    def closeEvent(self, event) -> None:
        thread = self.analytics_thread
        if thread is not None and thread.isRunning():
            QMessageBox.information(self, self.windowTitle(), "Wait for analytics generation to finish.")
            event.ignore()
            return
        super().closeEvent(event)


__all__ = [
    "IndustrialAnalyticsDialog",
    "SOURCE_PRODUCTION_CACHE",
    "SOURCE_TABULAR_FILE",
]

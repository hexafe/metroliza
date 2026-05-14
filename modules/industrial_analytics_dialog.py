"""Compact analytics dialog for cached production and CSV/Excel data."""

from __future__ import annotations

from pathlib import Path

from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modules.contracts import IndustrialAnalyticsRequest, validate_industrial_analytics_request
from modules.help_menu import attach_help_menu_to_layout
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
from modules.industrial_workers import IndustrialAnalyticsThread, TabularAnalyticsLoadThread
from modules.export_dialog_service import build_export_artifact_link_line
from modules.progress_status import build_three_line_status
from modules.tabular_analytics_filter_dialog import TabularAnalyticsFilterDialog
from modules.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog
from modules.tabular_analytics_service import (
    TABULAR_GROUP_COLUMN,
    TabularColumnFilter,
    cleanup_tabular_load_result,
    count_tabular_materialized_rows,
    list_tabular_excel_sheets,
    load_tabular_analytics_files,
    materialize_tabular_dataframe,
    tabular_load_result_row_count,
)
from modules.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
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


def build_analytics_completion_message(result) -> tuple[str, str, str, str]:
    """Build an export-style completion payload for generated analytics files."""

    dashboard_line = build_export_artifact_link_line("HTML dashboard", result.html_dashboard_path)
    workbook_line = build_export_artifact_link_line("Workbook", result.workbook_path)

    message_lines = ["Analytics created successfully!"]
    for artifact_line in (dashboard_line, workbook_line):
        if artifact_line:
            message_lines.extend(["", artifact_line])
    message_lines.extend(
        [
            "",
            f"Charts: {result.html_dashboard_chart_count}",
            f"Rows analyzed: {result.row_count}",
        ]
    )
    reveal_path = str(result.workbook_path or "")
    return "info", "Analytics successful", "\n".join(message_lines), reveal_path


class MetricSelectionDialog(QDialog):
    """Choose which discovered metrics should be included in the analytics run."""

    def __init__(
        self,
        parent=None,
        *,
        metrics: tuple[ProductionMetricSelection, ...],
        selected_fields: set[str] | None = None,
    ):
        super().__init__(parent)
        self.metrics = tuple(metrics)
        self.setWindowTitle("Select metrics")
        configure_window_size(self, minimum=(540, 420), initial=(640, 620))

        self.summary_label = status_chip("", "neutral")
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search metrics")
        self.metrics_list = QListWidget()
        self.metrics_list.setMinimumHeight(320)

        self.select_all_button = QPushButton("Select all")
        self.clear_button = QPushButton("Clear")
        self.cancel_button = QPushButton("Cancel")
        self.apply_button = QPushButton("Use metrics")
        self.apply_button.setDefault(True)

        self.select_all_button.clicked.connect(lambda: self._set_metric_checks(True))
        self.clear_button.clicked.connect(lambda: self._set_metric_checks(False))
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.accept)
        self.metrics_list.itemChanged.connect(lambda _item: self._sync_summary())
        self.search_field.textChanged.connect(self._filter_metrics)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(self.summary_label)
        layout.addWidget(section_label("Metrics"))
        layout.addWidget(self.search_field)
        layout.addWidget(self.metrics_list, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.select_all_button)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)

        self._populate_metrics(selected_fields)
        apply_metroliza_theme(self)

    def _populate_metrics(self, selected_fields: set[str] | None) -> None:
        selected_lookup = None if selected_fields is None else set(selected_fields)
        self.metrics_list.blockSignals(True)
        self.metrics_list.clear()
        for metric in self.metrics:
            item = QListWidgetItem(metric.display_label)
            item.setData(Qt.ItemDataRole.UserRole, metric)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            is_checked = selected_lookup is None or metric.field_name in selected_lookup
            item.setCheckState(Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)
            self.metrics_list.addItem(item)
        self.metrics_list.blockSignals(False)
        self._sync_summary()
        self._filter_metrics()

    def _set_metric_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.metrics_list.blockSignals(True)
        for index in range(self.metrics_list.count()):
            self.metrics_list.item(index).setCheckState(state)
        self.metrics_list.blockSignals(False)
        self._sync_summary()

    def _sync_summary(self) -> None:
        selected_count = len(self.selected_metrics())
        total_count = len(self.metrics)
        self.summary_label.setText(f"{selected_count} of {total_count} metrics selected")
        set_status_variant(self.summary_label, "success" if selected_count else "warning")

    def _filter_metrics(self) -> None:
        search = self.search_field.text().strip().casefold()
        for index in range(self.metrics_list.count()):
            item = self.metrics_list.item(index)
            metric = item.data(Qt.ItemDataRole.UserRole)
            label = item.text()
            field_name = metric.field_name if isinstance(metric, ProductionMetricSelection) else ""
            visible = not search or search in label.casefold() or search in field_name.casefold()
            item.setHidden(not visible)

    def selected_metrics(self) -> tuple[ProductionMetricSelection, ...]:
        metrics = []
        for index in range(self.metrics_list.count()):
            item = self.metrics_list.item(index)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            metric = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(metric, ProductionMetricSelection):
                metrics.append(metric)
        return tuple(metrics)


class MetricLimitsDialog(QDialog):
    """Edit per-metric absolute lower/upper specification limits."""

    def __init__(
        self,
        parent=None,
        *,
        metrics: tuple[ProductionMetricSelection, ...],
        limits: dict[str, tuple[float | None, float | None]] | None = None,
    ):
        super().__init__(parent)
        self.metrics = tuple(metrics)
        self._limits = dict(limits or {})
        self.setWindowTitle("Metric limits")
        configure_window_size(self, minimum=(560, 360), initial=(680, 520))

        self.table = QTableWidget(len(self.metrics), 3)
        self.table.setHorizontalHeaderLabels(("Metric", "LSL", "USL"))
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        for row, metric in enumerate(self.metrics):
            name_item = QTableWidgetItem(metric.display_label)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(Qt.ItemDataRole.UserRole, metric.field_name)
            self.table.setItem(row, 0, name_item)
            lsl, usl = self._limits.get(metric.field_name, (metric.lsl, metric.usl))
            self.table.setItem(row, 1, QTableWidgetItem("" if lsl is None else f"{lsl:g}"))
            self.table.setItem(row, 2, QTableWidgetItem("" if usl is None else f"{usl:g}"))

        self.status_label = status_chip(
            "Leave one side blank for one-sided tolerance; leave both blank for no limits.",
            "info",
        )
        self.cancel_button = QPushButton("Cancel")
        self.apply_button = QPushButton("Use limits")
        self.apply_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self._accept_if_valid)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(section_label("Absolute metric limits"))
        layout.addWidget(self.status_label)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)
        apply_metroliza_theme(self)

    def limits(self) -> dict[str, tuple[float | None, float | None]]:
        return dict(self._limits)

    def _accept_if_valid(self) -> None:
        parsed: dict[str, tuple[float | None, float | None]] = {}
        for row in range(self.table.rowCount()):
            metric_item = self.table.item(row, 0)
            if metric_item is None:
                continue
            field_name = str(metric_item.data(Qt.ItemDataRole.UserRole) or "").strip()
            lsl = self._optional_float(row, 1)
            usl = self._optional_float(row, 2)
            if isinstance(lsl, str) or isinstance(usl, str):
                self.status_label.setText(f"Invalid numeric limit for {metric_item.text()}.")
                set_status_variant(self.status_label, "danger")
                return
            if lsl is not None and usl is not None and lsl >= usl:
                self.status_label.setText(f"LSL must be lower than USL for {metric_item.text()}.")
                set_status_variant(self.status_label, "danger")
                return
            if field_name and (lsl is not None or usl is not None):
                parsed[field_name] = (lsl, usl)
        self._limits = parsed
        self.accept()

    def _optional_float(self, row: int, column: int) -> float | None | str:
        item = self.table.item(row, column)
        text = "" if item is None else item.text().strip()
        if not text:
            return None
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return "invalid"


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
        if source_kind not in {SOURCE_PRODUCTION_CACHE, SOURCE_TABULAR_FILE}:
            raise ValueError(f"Unsupported analytics source kind: {source_kind}")
        self.db_file = db_file or ""
        self.source_kind = source_kind
        self.input_file = ""
        self.input_files: tuple[str, ...] = ()
        self.output_dashboard_file = default_dashboard_path(self.db_file or "production_analytics")
        self.output_workbook_file = default_workbook_path(self.db_file or "production_analytics")
        self.analytics_thread = None
        self.tabular_load_thread = None
        self.metric_candidates: tuple[ProductionMetricSelection, ...] = ()
        self.metric_spec_limits: dict[str, tuple[float | None, float | None]] = {}
        self.filter_state = ProductionFilterState()
        self.tabular_load_result = None
        self.tabular_filter_columns: tuple[str, ...] = ()
        self.tabular_filter_keys: tuple[tuple[str, ...], ...] = ()
        self.tabular_column_filters: tuple[TabularColumnFilter, ...] = ()
        self.df_for_grouping = None
        self.grouping_applied = False
        self._tabular_reload_notice = ""

        self.setWindowTitle("Production analytics" if self.is_production_source else "CSV Summary")
        configure_window_size(self, minimum=(720, 560), initial=(880, 680))

        self.source_label = status_chip(self._source_summary(), "neutral")
        self.database_row_label = section_label("Report database")
        self.input_file_row_label = section_label("CSV/Excel file(s)")
        self.sheet_name_row_label = section_label("Excel sheet")
        self.timestamp_column_row_label = section_label("Time column")
        self.reference_column_row_label = section_label("Part / ID column")
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
        self.metrics_summary_label = status_chip("No metrics loaded", "warning")
        self.grouping_row_label = section_label("Group by")
        self.grouping_summary_label = status_chip("Groups: not applied", "neutral")

        self.sheet_name_combo = QComboBox()
        self.sheet_name_combo.setEditable(True)
        self.sheet_name_combo.addItem("First sheet", "")
        self.sheet_name_combo.currentTextChanged.connect(self._handle_tabular_source_changed)
        self.timestamp_column_combo = QComboBox()
        self.reference_column_combo = QComboBox()
        self.timestamp_column_combo.currentTextChanged.connect(self._handle_tabular_column_changed)
        self.reference_column_combo.currentTextChanged.connect(self._handle_tabular_column_changed)
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
            ("group_selected", "Group pasted references"),
        ):
            self.reference_mode_combo.addItem(label, value)
        reference_action_tooltip = (
            "Pasted references create an analysis-only cohort for this run. "
            "Group pasted references does not edit manual CSV groups."
        )
        self.reference_mode_combo.setToolTip(reference_action_tooltip)
        self.references_edit = QPlainTextEdit()
        self.references_edit.setPlaceholderText("Paste Part / IDs to highlight/filter; separate with comma, semicolon, space, or new line")
        self.references_edit.setMaximumHeight(90)
        self.references_edit.setToolTip(reference_action_tooltip)
        self.reference_mode_hint_label = status_chip(
            "Pasted references affect only this analytics run; manual CSV groups are unchanged.",
            "info",
        )

        self.time_series_checkbox = QCheckBox("Time series")
        self.histogram_checkbox = QCheckBox("Histogram")
        self.violin_checkbox = QCheckBox("Violin")
        self.box_checkbox = QCheckBox("Box")
        self.groupstats_checkbox = QCheckBox("Groupstats")
        self.groupstats_reason_label = status_chip("", "warning")
        self.groupstats_reason_label.setVisible(False)
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
        self.clear_filter_button = QPushButton("Clear filter")
        self.load_metrics_button = QPushButton("Load metrics")
        self.choose_metrics_button = QPushButton("Choose metrics...")
        self.edit_limits_button = QPushButton("Limits...")
        self.edit_groups_button = QPushButton("Edit groups...")
        self.clear_groups_button = QPushButton("Clear groups")
        self.dashboard_button = QPushButton("Browse")
        self.workbook_button = QPushButton("Browse")
        self.close_button = QPushButton("Close")
        self.start_button = QPushButton("Create analytics")
        self.start_button.setDefault(True)

        self.browse_input_button.clicked.connect(self.select_input_file)
        self.filters_button.clicked.connect(self.open_filters_dialog)
        self.clear_filter_button.clicked.connect(self.clear_tabular_filter_and_groups)
        self.load_metrics_button.clicked.connect(self.handle_load_metrics_clicked)
        self.choose_metrics_button.clicked.connect(self.open_metrics_dialog)
        self.edit_limits_button.clicked.connect(self.open_limits_dialog)
        self.edit_groups_button.clicked.connect(self.open_grouping_dialog)
        self.clear_groups_button.clicked.connect(self.clear_tabular_groups)
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
        self._configure_accessibility()
        self._sync_source_visibility()
        self._reset_group_options(())
        self._sync_ui_state()
        apply_metroliza_theme(self)

    @property
    def is_production_source(self) -> bool:
        return self.source_kind == SOURCE_PRODUCTION_CACHE

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        help_entries = [("Export manual", "export_overview")]
        if not self.is_production_source:
            help_entries.append(("CSV Summary manual", "csv_summary"))
        self.dialog_menu_bar, self.help_menu = attach_help_menu_to_layout(layout, self, help_entries)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        content_layout.addWidget(section_label("Analytics source"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        row = 0
        grid.addWidget(section_label("Source"), row, 0)
        grid.addWidget(self.source_label, row, 1, 1, 2)

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
        metric_actions = QHBoxLayout()
        metric_actions.setContentsMargins(0, 0, 0, 0)
        metric_actions.setSpacing(8)
        metric_actions.addWidget(self.load_metrics_button)
        metric_actions.addStretch(1)
        grid.addWidget(section_label("Data"), row, 0)
        grid.addLayout(metric_actions, row, 1, 1, 2)

        row += 1
        filter_actions = QHBoxLayout()
        filter_actions.setContentsMargins(0, 0, 0, 0)
        filter_actions.setSpacing(8)
        filter_actions.addWidget(self.filters_button)
        filter_actions.addWidget(self.clear_filter_button)
        filter_actions.addStretch(1)
        grid.addWidget(self.filter_row_label, row, 0)
        grid.addWidget(self.filter_summary_label, row, 1)
        grid.addLayout(filter_actions, row, 2)

        row += 1
        metric_buttons = QHBoxLayout()
        metric_buttons.setContentsMargins(0, 0, 0, 0)
        metric_buttons.setSpacing(8)
        metric_buttons.addWidget(self.choose_metrics_button)
        metric_buttons.addWidget(self.edit_limits_button)
        metric_buttons.addStretch(1)
        grid.addWidget(section_label("Metrics"), row, 0)
        grid.addWidget(self.metrics_summary_label, row, 1)
        grid.addLayout(metric_buttons, row, 2)

        row += 1
        grouping_actions = QHBoxLayout()
        grouping_actions.setContentsMargins(0, 0, 0, 0)
        grouping_actions.setSpacing(8)
        grouping_actions.addWidget(self.edit_groups_button)
        grouping_actions.addWidget(self.clear_groups_button)
        grouping_actions.addStretch(1)
        grid.addWidget(self.grouping_row_label, row, 0)
        grid.addWidget(self.group_field_combo, row, 1, 1, 2)
        grid.addWidget(self.grouping_summary_label, row, 1)
        grid.addLayout(grouping_actions, row, 2)

        row += 1
        grid.addWidget(section_label("Time bucket"), row, 0)
        grid.addWidget(self.time_bucket_combo, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Aggregation"), row, 0)
        grid.addWidget(self.aggregation_combo, row, 1, 1, 2)

        row += 1
        reference_mode_label = section_label("Pasted reference action")
        grid.addWidget(reference_mode_label, row, 0)
        grid.addWidget(self.reference_mode_combo, row, 1, 1, 2)

        row += 1
        references_label = section_label("References")
        grid.addWidget(references_label, row, 0)
        grid.addWidget(self.references_edit, row, 1, 1, 2)

        row += 1
        grid.addWidget(self.reference_mode_hint_label, row, 1, 1, 2)

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
        grid.addWidget(self.groupstats_reason_label, row, 1, 1, 2)

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
        content_layout.addLayout(grid)
        scroll_area.setWidget(content)
        layout.addWidget(scroll_area, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)

    def _configure_accessibility(self) -> None:
        configure_accessibility(self.source_label, name="Analytics source summary")
        configure_accessibility(self.database_field, name="Analytics report database")
        configure_accessibility(self.input_file_field, name="CSV or Excel input file")
        configure_accessibility(self.browse_input_button, name="Browse CSV or Excel input")
        configure_accessibility(self.sheet_name_combo, name="Excel sheet")
        configure_accessibility(self.timestamp_column_combo, name="Analytics time column")
        configure_accessibility(self.reference_column_combo, name="Analytics part or ID column")
        configure_accessibility(self.load_metrics_button, name="Load analytics metrics")
        configure_accessibility(self.filters_button, name="Edit analytics filters")
        configure_accessibility(self.clear_filter_button, name="Clear analytics filter")
        configure_accessibility(self.choose_metrics_button, name="Choose analytics metrics")
        configure_accessibility(self.edit_limits_button, name="Edit metric limits")
        configure_accessibility(self.edit_groups_button, name="Edit CSV analytics groups")
        configure_accessibility(self.clear_groups_button, name="Clear CSV analytics groups")
        configure_accessibility(self.group_field_combo, name="Production grouping field")
        configure_accessibility(self.grouping_summary_label, name="CSV grouping summary")
        configure_accessibility(self.time_bucket_combo, name="Analytics time bucket")
        configure_accessibility(self.aggregation_combo, name="Analytics aggregation")
        configure_accessibility(
            self.reference_mode_combo,
            name="Pasted reference action",
            description=self.reference_mode_combo.toolTip(),
        )
        configure_accessibility(
            self.references_edit,
            name="Pasted references",
            description=self.references_edit.toolTip(),
        )
        configure_accessibility(self.groupstats_checkbox, name="Include groupstats output")
        configure_accessibility(self.dashboard_button, name="Select analytics dashboard path")
        configure_accessibility(self.workbook_button, name="Select analytics workbook path")
        configure_accessibility(self.close_button, name="Close analytics dialog")
        configure_accessibility(self.start_button, name="Create analytics output")

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
        self.filter_row_label.setText("Filters" if self.is_production_source else "Row filter")
        self._sync_filter_visibility()
        self.filters_button.setText("Filters..." if self.is_production_source else "Filter rows...")
        self.clear_filter_button.setVisible(show_file)
        self.database_row_label.setVisible(self.is_production_source)
        self.database_field.setVisible(self.is_production_source)
        self.grouping_row_label.setText("Group by" if self.is_production_source else "Groups")
        self.group_field_combo.setVisible(self.is_production_source)
        self.grouping_summary_label.setVisible(show_file)
        self.edit_groups_button.setVisible(show_file)
        self.clear_groups_button.setVisible(show_file)
        self._sync_filter_summary()

    def _sync_filter_summary(self) -> None:
        if self.is_production_source:
            self.filter_summary_label.setText(self.filter_state.summary())
            set_status_variant(self.filter_summary_label, "info" if self.filter_state.is_applied else "neutral")
            return
        summary, variant = self._tabular_filter_summary()
        self.filter_summary_label.setText(summary)
        set_status_variant(self.filter_summary_label, variant)

    def _sync_filter_visibility(self) -> None:
        show_filter = self.is_production_source or self.tabular_load_result is not None
        self.filter_row_label.setVisible(show_filter)
        self.filter_summary_label.setVisible(show_filter)
        self.filters_button.setVisible(show_filter)
        self.clear_filter_button.setVisible(show_filter and not self.is_production_source)

    def _handle_tabular_source_changed(self, _text: str = "") -> None:
        if self.is_production_source:
            return
        if self.input_file and (self.tabular_load_result is not None or self.metric_candidates):
            self._tabular_reload_notice = "Reload CSV/Excel data after changing the selected sheet."
        self.metric_candidates = ()
        self._set_tabular_load_result(None)
        self.metric_spec_limits = {}
        self._clear_tabular_filter()
        self._clear_tabular_grouping()
        self.metrics_list.clear()
        self._reset_group_options(())
        self._reset_tabular_column_options()
        self._sync_ui_state()

    def _handle_tabular_column_changed(self, _text: str = "") -> None:
        if self.is_production_source:
            return
        if not self.metric_candidates:
            return
        self._tabular_reload_notice = "Reload CSV/Excel data after changing the time column or part / ID column."
        self.metric_candidates = ()
        self._set_tabular_load_result(None)
        self.metric_spec_limits = {}
        self._clear_tabular_filter()
        self._clear_tabular_grouping()
        self.metrics_list.clear()
        self._reset_group_options(())
        self._sync_ui_state()

    def _clear_tabular_grouping(self) -> None:
        self.df_for_grouping = None
        self.grouping_applied = False

    def _clear_tabular_filter(self) -> None:
        self.tabular_filter_columns = ()
        self.tabular_filter_keys = ()
        self.tabular_column_filters = ()

    def _set_tabular_load_result(self, loaded) -> None:
        current = self.tabular_load_result
        if current is not None and current is not loaded:
            cleanup_tabular_load_result(current)
        self.tabular_load_result = loaded

    def _selected_input_files(self) -> tuple[str, ...]:
        if self.input_files:
            return self.input_files
        return (self.input_file,) if self.input_file else ()

    def _input_files_display(self) -> str:
        input_files = self._selected_input_files()
        if not input_files:
            return ""
        if len(input_files) == 1:
            return input_files[0]
        names = [Path(path).name for path in input_files]
        preview = ", ".join(names[:3])
        if len(names) > 3:
            preview = f"{preview}, +{len(names) - 3} more"
        return f"{len(names)} CSV files: {preview}"

    def _tabular_filtered_row_count(self) -> int:
        if self.tabular_load_result is None:
            return 0
        return count_tabular_materialized_rows(
            self.tabular_load_result,
            filter_columns=self.tabular_filter_columns,
            selected_filter_keys=self.tabular_filter_keys,
            column_filters=self.tabular_column_filters,
        )

    def clear_tabular_filter_and_groups(self) -> None:
        if self.is_production_source:
            return
        self._clear_tabular_filter()
        self._clear_tabular_grouping()
        self._sync_ui_state()

    def clear_tabular_groups(self) -> None:
        if self.is_production_source:
            return
        self._clear_tabular_grouping()
        self._sync_ui_state()

    def _reset_tabular_column_options(self) -> None:
        for combo in (self.timestamp_column_combo, self.reference_column_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Auto detect", "")
            combo.blockSignals(False)

    def _populate_tabular_sheet_options(self) -> None:
        self.sheet_name_combo.blockSignals(True)
        self.sheet_name_combo.clear()
        if len(self._selected_input_files()) > 1:
            self.sheet_name_combo.addItem("CSV files", "")
            self.sheet_name_combo.setEnabled(False)
            self.sheet_name_combo.blockSignals(False)
            return
        path = Path(self.input_file) if self.input_file else None
        suffix = path.suffix.lower() if path is not None else ""
        if suffix in {".xlsx", ".xls"}:
            try:
                sheet_names = list_tabular_excel_sheets(path)
            except Exception:
                sheet_names = ()
            if sheet_names:
                for sheet in sheet_names:
                    self.sheet_name_combo.addItem(sheet, sheet)
            else:
                self.sheet_name_combo.addItem("First sheet", "")
            self.sheet_name_combo.setEnabled(True)
        elif suffix == ".csv":
            self.sheet_name_combo.addItem("CSV file", "")
            self.sheet_name_combo.setEnabled(False)
        else:
            self.sheet_name_combo.addItem("First sheet", "")
            self.sheet_name_combo.setEnabled(False)
        self.sheet_name_combo.blockSignals(False)

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
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "Open CSV or Excel data",
            self.input_file or "",
            "CSV / Excel (*.csv *.xlsx *.xls);;CSV (*.csv);;Excel (*.xlsx *.xls);;All files (*)",
        )
        if not filenames:
            return
        selected_files = tuple(str(Path(filename)) for filename in filenames)
        if len(selected_files) > 1 and any(Path(filename).suffix.lower() != ".csv" for filename in selected_files):
            QMessageBox.warning(
                self,
                self.windowTitle(),
                "Select only CSV files when loading multiple CSV Summary inputs.",
            )
            return
        self.input_files = selected_files
        self.input_file = selected_files[0]
        output_seed = self.input_file
        if len(selected_files) > 1:
            first_path = Path(self.input_file)
            output_seed = str(first_path.with_name(f"{first_path.stem}_combined.csv"))
        self.output_dashboard_file = default_dashboard_path(output_seed)
        self.output_workbook_file = default_workbook_path(output_seed)
        self._tabular_reload_notice = ""
        self.metric_candidates = ()
        self._set_tabular_load_result(None)
        self.metric_spec_limits = {}
        self._clear_tabular_filter()
        self._clear_tabular_grouping()
        self.metrics_list.clear()
        self._populate_tabular_sheet_options()
        self._reset_tabular_column_options()
        self._reset_group_options(())
        self.show_tabular_load_screen()

    def handle_load_metrics_clicked(self) -> None:
        if self.is_production_source:
            self.load_metrics()
            return
        self.show_tabular_load_screen()

    def open_filters_dialog(self) -> None:
        if not self.is_production_source:
            self.open_tabular_filter_dialog()
            return
        dialog = IndustrialAnalyticsFilterDialog(self, filter_state=self.filter_state)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.filter_state = dialog.filter_state
        self.metric_candidates = ()
        self.metrics_list.clear()
        self._reset_group_options(())
        self._sync_filter_summary()
        self._sync_ui_state()

    def open_tabular_filter_dialog(self) -> None:
        if self.tabular_load_result is None:
            self.load_metrics()
        if self.tabular_load_result is None or self.tabular_load_result.dataframe.empty:
            QMessageBox.warning(self, self.windowTitle(), "Load CSV/Excel metrics before filtering rows.")
            return
        dialog = TabularAnalyticsFilterDialog(
            self,
            dataframe=self.tabular_load_result.dataframe,
            column_mapping=self.tabular_load_result.column_mapping,
            filter_columns=self.tabular_filter_columns,
            selected_filter_keys=self.tabular_filter_keys,
            column_filters=self.tabular_column_filters,
            sqlite_store=self.tabular_load_result.sqlite_store,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.tabular_column_filters = dialog.get_column_filters()
        self.tabular_filter_columns = ()
        self.tabular_filter_keys = ()
        self._clear_tabular_grouping()
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
                input_files = self._selected_input_files()
                if not input_files:
                    raise ValueError("Select a CSV or Excel file first.")
                sheet_name = self._selected_sheet_name()
                loaded = load_tabular_analytics_files(
                    input_files,
                    sheet_name=sheet_name,
                    timestamp_column=self._selected_tabular_column(self.timestamp_column_combo),
                    reference_column=self._selected_tabular_column(self.reference_column_combo),
                )
                self._apply_tabular_load_result(loaded, populate_metrics=False)
        except Exception as exc:
            QMessageBox.warning(self, self.windowTitle(), f"Could not load metrics: {exc}")
            self._sync_ui_state()
            return

        self._populate_metrics()
        self._sync_ui_state()

    def _apply_tabular_load_result(self, loaded, *, populate_metrics: bool = True) -> None:
        self._tabular_reload_notice = ""
        self._set_tabular_load_result(loaded)
        self.metric_candidates = tuple(candidate.to_selection() for candidate in loaded.metric_candidates)
        self.metric_spec_limits = {
            field_name: limits
            for field_name, limits in self.metric_spec_limits.items()
            if field_name in {metric.field_name for metric in self.metric_candidates}
        }
        self._reset_group_options(
            tuple(
                (column.replace("_", " ").title(), column)
                for column in loaded.dataframe.columns
                if column not in {metric.field_name for metric in self.metric_candidates}
            )
        )
        self.source_label.setText(self._tabular_source_label(loaded))
        self._populate_tabular_column_options(
            loaded.column_mapping,
            timestamp_column=loaded.timestamp_column,
            reference_column=loaded.reference_column,
        )
        if populate_metrics:
            self._populate_metrics()
            self._sync_ui_state()

    def _tabular_source_label(self, loaded) -> str:
        row_count = tabular_load_result_row_count(loaded)
        source_files = tuple(getattr(loaded, "source_files", ()) or self._selected_input_files())
        if len(source_files) > 1:
            return f"{len(source_files)} CSV files: {row_count} rows"
        if source_files:
            return f"{Path(source_files[0]).name}: {row_count} rows"
        if self.input_file:
            return f"{Path(self.input_file).name}: {row_count} rows"
        return f"CSV/Excel table: {row_count} rows"

    def open_metrics_dialog(self) -> None:
        if not self.metric_candidates:
            self.load_metrics()
        if not self.metric_candidates:
            return
        dialog = MetricSelectionDialog(
            self,
            metrics=self.metric_candidates,
            selected_fields=(
                {metric.field_name for metric in self._selected_metrics()}
                if self.metrics_list.count()
                else None
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_metric_selection(dialog.selected_metrics())

    def open_limits_dialog(self) -> None:
        if not self.metric_candidates:
            self.load_metrics()
        metrics = self._selected_metrics()
        if not metrics:
            QMessageBox.information(self, self.windowTitle(), "Select at least one metric before editing limits.")
            return
        dialog = MetricLimitsDialog(self, metrics=metrics, limits=self.metric_spec_limits)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.metric_spec_limits = dialog.limits()
        self._sync_ui_state()

    def open_grouping_dialog(self) -> None:
        if self.is_production_source:
            return
        if self.tabular_load_result is None:
            self.load_metrics()
        if self.tabular_load_result is None or self.tabular_load_result.dataframe.empty:
            QMessageBox.warning(self, self.windowTitle(), "Load CSV/Excel metrics before editing groups.")
            return
        dialog = TabularAnalyticsGroupingDialog(
            self,
            dataframe=self._filtered_tabular_dataframe(),
            column_mapping=self.tabular_load_result.column_mapping,
            grouping_dataframe=self.df_for_grouping if self.grouping_applied else None,
        )
        dialog.exec()
        self._sync_ui_state()

    def set_df_for_grouping(self, df) -> None:
        self.df_for_grouping = df
        self._sync_grouping_summary()

    def set_grouping_applied(self, applied: bool) -> None:
        self.grouping_applied = bool(applied)
        if not self.grouping_applied:
            self.df_for_grouping = None
        self._sync_grouping_summary()

    def _sync_grouping_summary(self) -> None:
        if self.is_production_source:
            return
        if not self.grouping_applied or self.df_for_grouping is None or self.df_for_grouping.empty:
            self.grouping_summary_label.setText("Groups: not applied")
            set_status_variant(self.grouping_summary_label, "neutral")
            return
        groups = (
            self.df_for_grouping.get("GROUP", [])
            if hasattr(self.df_for_grouping, "get")
            else []
        )
        group_values = sorted({str(value).strip() for value in groups if str(value).strip()})
        custom_groups = [value for value in group_values if value != "POPULATION"]
        if custom_groups:
            self.grouping_summary_label.setText(
                f"Groups: {len(custom_groups)} custom + POPULATION"
            )
            set_status_variant(self.grouping_summary_label, "success")
        else:
            self.grouping_summary_label.setText("Groups: POPULATION only")
            set_status_variant(self.grouping_summary_label, "info")

    def _filtered_tabular_dataframe(self):
        if self.tabular_load_result is None:
            return None
        return materialize_tabular_dataframe(
            self.tabular_load_result,
            filter_columns=self.tabular_filter_columns,
            selected_filter_keys=self.tabular_filter_keys,
            column_filters=self.tabular_column_filters,
        ).dataframe

    def _tabular_filter_summary(self) -> tuple[str, str]:
        if self.tabular_load_result is None:
            return "No row filter", "neutral"
        row_count = self._tabular_filtered_row_count()
        if not self.tabular_column_filters and (
            not self.tabular_filter_columns or not self.tabular_filter_keys
        ):
            return f"All rows ({tabular_load_result_row_count(self.tabular_load_result)})", "neutral"
        label_lookup = {
            normalized: original
            for original, normalized in self.tabular_load_result.column_mapping.items()
        }
        if self.tabular_column_filters:
            columns_text = ", ".join(
                self._tabular_column_filter_label(item, label_lookup)
                for item in self.tabular_column_filters
            )
        else:
            columns_text = " | ".join(
                str(label_lookup.get(column, column)) for column in self.tabular_filter_columns
            )
        selection_count = (
            len(self.tabular_column_filters)
            if self.tabular_column_filters
            else len(self.tabular_filter_keys)
        )
        return (
            f"{columns_text}: {selection_count} filter(s), {row_count} rows",
            "success" if row_count else "danger",
        )

    @staticmethod
    def _tabular_column_filter_label(
        column_filter: TabularColumnFilter,
        label_lookup: dict[str, str],
    ) -> str:
        label = str(label_lookup.get(column_filter.column, column_filter.column))
        details: list[str] = []
        if column_filter.selected_values:
            details.append(f"{len(column_filter.selected_values)} value(s)")
        if column_filter.has_date_filter:
            if column_filter.date_mode == "from":
                details.append(f">= {column_filter.date_from}")
            elif column_filter.date_mode == "to":
                details.append(f"<= {column_filter.date_to}")
            elif column_filter.date_mode == "between":
                details.append(f"{column_filter.date_from} to {column_filter.date_to}")
        return f"{label} ({', '.join(details)})" if details else label

    def _populate_metrics(self, selected_fields: set[str] | None = None) -> None:
        selected_lookup = None if selected_fields is None else set(selected_fields)
        self.metrics_list.blockSignals(True)
        self.metrics_list.clear()
        for metric in self.metric_candidates:
            item = QListWidgetItem(metric.display_label)
            item.setData(Qt.ItemDataRole.UserRole, metric)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            is_checked = selected_lookup is None or metric.field_name in selected_lookup
            item.setCheckState(Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)
            self.metrics_list.addItem(item)
        self.metrics_list.blockSignals(False)

    def _apply_metric_selection(self, selected_metrics: tuple[ProductionMetricSelection, ...]) -> None:
        if self.metrics_list.count() != len(self.metric_candidates):
            self._populate_metrics({metric.field_name for metric in selected_metrics})
            self._sync_ui_state()
            return
        selected_fields = {metric.field_name for metric in selected_metrics}
        state_by_field = {
            metric.field_name: (
                Qt.CheckState.Checked if metric.field_name in selected_fields else Qt.CheckState.Unchecked
            )
            for metric in self.metric_candidates
        }
        self.metrics_list.blockSignals(True)
        for index in range(self.metrics_list.count()):
            item = self.metrics_list.item(index)
            metric = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(metric, ProductionMetricSelection):
                item.setCheckState(state_by_field.get(metric.field_name, Qt.CheckState.Unchecked))
        self.metrics_list.blockSignals(False)
        self._sync_ui_state()

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
                metrics.append(self._metric_with_limits(metric))
        return tuple(metrics)

    def _metric_with_limits(self, metric: ProductionMetricSelection) -> ProductionMetricSelection:
        lsl, usl = self.metric_spec_limits.get(metric.field_name, (metric.lsl, metric.usl))
        return replace(
            metric,
            lsl=lsl,
            usl=usl,
            limits_source="manual" if lsl is not None or usl is not None else metric.limits_source,
        )

    def _tabular_groupstats_available(self) -> bool:
        return self._tabular_groupstats_unavailable_reason() is None

    def _tabular_groupstats_unavailable_reason(self) -> str | None:
        if self.is_production_source:
            return None
        if not self.grouping_applied or self.df_for_grouping is None or self.df_for_grouping.empty:
            return "Groupstats requires manual CSV/Excel groups. Use Edit groups... first."
        groups = self.df_for_grouping.get("GROUP", [])
        values = {str(value).strip() for value in groups if str(value).strip()}
        if len(values) < 2:
            return "Groupstats requires at least 2 non-empty manual groups."
        return None

    def _selected_sheet_name(self) -> str | None:
        if self.is_production_source:
            return None
        data_value = self.sheet_name_combo.currentData()
        if data_value is not None:
            value = str(data_value).strip()
            return value or None
        text = self.sheet_name_combo.currentText().strip()
        return text if text and text not in {"First sheet", "CSV file", "CSV files"} else None

    def _aggregation_state(self) -> ProductionAggregationState:
        if not self.is_production_source and self.grouping_applied:
            group_fields = (TABULAR_GROUP_COLUMN,)
        else:
            group_field = str(self.group_field_combo.currentData() or "").strip()
            group_fields = (group_field,) if group_field else ()
        return ProductionAggregationState(
            time_bucket=str(self.time_bucket_combo.currentData() or "none"),
            aggregation_methods=(str(self.aggregation_combo.currentData() or "mean"),),
            group_fields=group_fields,
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
        self._sync_filter_summary()
        update_path_field(self.database_field, self.db_file, empty_text="No Metroliza report database selected")
        update_path_field(
            self.input_file_field,
            self._input_files_display(),
            empty_text="No CSV/Excel file selected",
        )
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
        source_ready = bool(self.db_file) if self.is_production_source else bool(self._selected_input_files())
        candidate_count = len(self.metric_candidates)
        filtered_row_count = None
        if not self.is_production_source and self.tabular_load_result is not None:
            filtered_row_count = self._tabular_filtered_row_count()
        self.choose_metrics_button.setEnabled(bool(candidate_count))
        self.edit_limits_button.setEnabled(bool(candidate_count and metrics))
        self.edit_groups_button.setEnabled(bool(candidate_count and not self.is_production_source))
        self.clear_filter_button.setEnabled(
            bool(
                not self.is_production_source
                and (
                    self.tabular_column_filters
                    or (self.tabular_filter_columns and self.tabular_filter_keys)
                )
            )
        )
        self.clear_groups_button.setEnabled(bool(not self.is_production_source and self.grouping_applied))
        self.load_metrics_button.setEnabled(source_ready)
        if self.is_production_source:
            self.load_metrics_button.setText("Reload metrics" if candidate_count else "Load metrics")
        else:
            self.load_metrics_button.setText(
                "Reload CSV/Excel data" if candidate_count else "Load CSV/Excel data"
            )
        self._sync_filter_visibility()
        groupstats_unavailable_reason = self._tabular_groupstats_unavailable_reason()
        groupstats_available = groupstats_unavailable_reason is None
        self.groupstats_checkbox.setEnabled(groupstats_available)
        self.groupstats_checkbox.setToolTip(groupstats_unavailable_reason or "")
        self.groupstats_reason_label.setVisible(bool(groupstats_unavailable_reason))
        self.groupstats_reason_label.setText(groupstats_unavailable_reason or "")
        set_status_variant(self.groupstats_reason_label, "warning")
        if not groupstats_available:
            self.groupstats_checkbox.blockSignals(True)
            self.groupstats_checkbox.setChecked(False)
            self.groupstats_checkbox.blockSignals(False)
        if candidate_count:
            self.metrics_summary_label.setText(f"{len(metrics)} of {candidate_count} metrics selected")
            set_status_variant(self.metrics_summary_label, "success" if metrics else "warning")
        else:
            self.metrics_summary_label.setText("No metrics loaded")
            set_status_variant(self.metrics_summary_label, "warning" if source_ready else "neutral")
        self._sync_grouping_summary()

        charts_ready = self._chart_selection().has_any
        workbook_ready = not self.workbook_checkbox.isChecked() or bool(self.output_workbook_file)
        tabular_rows_ready = self.is_production_source or filtered_row_count is None or filtered_row_count > 0
        self.filters_button.setEnabled(self.is_production_source or self.tabular_load_result is not None)
        ready = bool(
            source_ready
            and metrics
            and self.output_dashboard_file
            and charts_ready
            and workbook_ready
            and tabular_rows_ready
        )
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
        elif self._tabular_reload_notice:
            self.readiness_label.setText(self._tabular_reload_notice)
            set_status_variant(self.readiness_label, "warning")
        elif not metrics:
            self.readiness_label.setText("Load metrics and select at least one parameter.")
            set_status_variant(self.readiness_label, "warning")
        elif not tabular_rows_ready:
            self.readiness_label.setText("Row filter matches no CSV/Excel rows.")
            set_status_variant(self.readiness_label, "danger")
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

    def show_tabular_load_screen(self) -> None:
        if self.is_production_source:
            self.load_metrics()
            return
        input_files = self._selected_input_files()
        if not input_files:
            QMessageBox.warning(self, self.windowTitle(), "Select a CSV or Excel file first.")
            return
        if self.tabular_load_thread is not None and self.tabular_load_thread.isRunning():
            return
        self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif = (
            create_worker_progress_dialog(
                self,
                window_title="Loading CSV / Excel data...",
                initial_status_text=build_three_line_status(
                    "Loading CSV/Excel data...",
                    "Reading rows and detecting metric columns",
                    "ETA --",
                ),
                on_cancel=self.cancel_tabular_load,
            )
        )
        self.loading_bar.setRange(0, 0)
        self.tabular_load_thread = TabularAnalyticsLoadThread(
            input_file=self.input_file,
            input_files=input_files,
            sheet_name=self._selected_sheet_name(),
            timestamp_column=self._selected_tabular_column(self.timestamp_column_combo),
            reference_column=self._selected_tabular_column(self.reference_column_combo),
        )
        self.tabular_load_thread.result_ready.connect(self.on_tabular_load_finished)
        self.tabular_load_thread.error_occurred.connect(self.on_tabular_load_error)
        self.tabular_load_thread.cancelled.connect(self.on_tabular_load_cancelled)
        self.tabular_load_thread.update_label.connect(self.loading_label.setText)
        self.tabular_load_thread.finished.connect(self.on_tabular_load_thread_stopped)
        self.tabular_load_thread.start()
        self.loading_dialog.show()

    def cancel_tabular_load(self) -> None:
        if self.tabular_load_thread is not None:
            self.tabular_load_thread.cancel()
        if hasattr(self, "loading_label"):
            self.loading_label.setText(
                build_three_line_status(
                    "Canceling CSV/Excel load...",
                    "Waiting for the current loading step to stop",
                    "ETA --",
                )
            )

    def on_tabular_load_finished(self, loaded) -> None:
        if hasattr(self, "loading_dialog"):
            self.loading_dialog.close()
        self._apply_tabular_load_result(loaded)

    def on_tabular_load_error(self, message: str) -> None:
        if hasattr(self, "loading_dialog"):
            self.loading_dialog.close()
        QMessageBox.warning(self, self.windowTitle(), f"Could not load metrics: {message}")
        self._sync_ui_state()

    def on_tabular_load_cancelled(self, message: str) -> None:
        if hasattr(self, "loading_dialog"):
            self.loading_dialog.close()
        QMessageBox.information(self, self.windowTitle(), message or "CSV/Excel loading was canceled.")

    def on_tabular_load_thread_stopped(self) -> None:
        self.tabular_load_thread = None
        self._sync_ui_state()

    def _build_analytics_request(self, *, require_runnable: bool = False) -> IndustrialAnalyticsRequest:
        return validate_industrial_analytics_request(
            IndustrialAnalyticsRequest(
                source_kind=self.source_kind,
                db_file=self.db_file,
                input_file=self.input_file,
                output_dashboard_file=self.output_dashboard_file,
                output_workbook_file=(
                    self.output_workbook_file if self.workbook_checkbox.isChecked() else ""
                ),
                metric_selection=self._selected_metrics(),
                filter_state=self.filter_state,
                aggregation_state=self._aggregation_state(),
                cohort_state=self._cohort_state(),
                chart_selection=self._chart_selection(),
                separate_parameter_sheets=self.parameter_sheets_checkbox.isChecked(),
                sheet_name=self._selected_sheet_name(),
                timestamp_column=self._selected_tabular_column(self.timestamp_column_combo),
                reference_column=self._selected_tabular_column(self.reference_column_combo),
                tabular_load_result=self.tabular_load_result if not self.is_production_source else None,
                tabular_filter_columns=self.tabular_filter_columns,
                tabular_filter_keys=self.tabular_filter_keys,
                tabular_column_filters=self.tabular_column_filters,
                grouping_df=self.df_for_grouping if self.grouping_applied else None,
            ),
            require_runnable=require_runnable,
        )

    def create_analytics_thread(self) -> IndustrialAnalyticsThread:
        request = self._build_analytics_request()
        return IndustrialAnalyticsThread(
            source_kind=request.source_kind,
            db_file=request.db_file,
            input_file=request.input_file,
            output_dashboard_file=request.output_dashboard_file,
            output_workbook_file=request.output_workbook_file,
            metric_selection=request.metric_selection,
            filter_state=request.filter_state,
            aggregation_state=request.aggregation_state,
            cohort_state=request.cohort_state,
            chart_selection=request.chart_selection,
            separate_parameter_sheets=request.separate_parameter_sheets,
            sheet_name=request.sheet_name,
            timestamp_column=request.timestamp_column,
            reference_column=request.reference_column,
            tabular_load_result=request.tabular_load_result,
            tabular_filter_columns=request.tabular_filter_columns,
            tabular_filter_keys=request.tabular_filter_keys,
            tabular_column_filters=request.tabular_column_filters,
            grouping_df=request.grouping_df,
        )

    def show_loading_screen(self) -> None:
        try:
            request = self._build_analytics_request(require_runnable=True)
        except ValueError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        self.output_dashboard_file = request.output_dashboard_file
        if request.output_workbook_file:
            self.output_workbook_file = request.output_workbook_file
        self._sync_ui_state()
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
        self.analytics_thread.update_label.connect(self.loading_label.setText)
        self.analytics_thread.finished.connect(self.on_analytics_thread_stopped)
        self.analytics_thread.start()
        self.loading_dialog.show()

    def cancel_analytics(self) -> None:
        if self.analytics_thread is not None:
            self.analytics_thread.cancel()
        if hasattr(self, "loading_label"):
            self.loading_label.setText(
                build_three_line_status(
                    "Canceling analytics...",
                    "Waiting for the current analytics step to stop",
                    "ETA --",
                )
            )

    def on_analytics_finished(self, result) -> None:
        if hasattr(self, "loading_dialog"):
            self.loading_dialog.close()
        level, title, message, reveal_path = build_analytics_completion_message(result)
        try:
            from modules.export_dialog import show_export_result_message

            show_export_result_message(self, level, title, message, excel_file=reveal_path)
        except Exception:
            QMessageBox.information(self, title, message)

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

    def reject(self) -> None:
        thread = self.tabular_load_thread
        if thread is not None and thread.isRunning():
            QMessageBox.information(self, self.windowTitle(), "Wait for CSV/Excel loading to finish.")
            return
        thread = self.analytics_thread
        if thread is not None and thread.isRunning():
            QMessageBox.information(self, self.windowTitle(), "Wait for analytics generation to finish.")
            return
        self._set_tabular_load_result(None)
        super().reject()

    def closeEvent(self, event) -> None:
        thread = self.tabular_load_thread
        if thread is not None and thread.isRunning():
            QMessageBox.information(self, self.windowTitle(), "Wait for CSV/Excel loading to finish.")
            event.ignore()
            return
        thread = self.analytics_thread
        if thread is not None and thread.isRunning():
            QMessageBox.information(self, self.windowTitle(), "Wait for analytics generation to finish.")
            event.ignore()
            return
        self._set_tabular_load_result(None)
        super().closeEvent(event)


__all__ = [
    "build_analytics_completion_message",
    "IndustrialAnalyticsDialog",
    "MetricSelectionDialog",
    "SOURCE_PRODUCTION_CACHE",
    "SOURCE_TABULAR_FILE",
]

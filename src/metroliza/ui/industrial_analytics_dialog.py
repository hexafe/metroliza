"""Compact analytics dialog for cached production and CSV/Excel data."""

from __future__ import annotations

from pathlib import Path
from time import monotonic

from dataclasses import dataclass, replace
import inspect
import sqlite3

from metroliza.ui.result_actions import LastResultRow, existing_result_files
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from metroliza.industrial.contracts import (
    IndustrialAnalyticsRequest,
    validate_industrial_analytics_request,
)
from metroliza.shared.dashboard_interactivity import DashboardInteractivityOptions
from metroliza.shared.dashboard_interactivity import (
    DASHBOARD_LARGE_GROUP_STATIC_THRESHOLD,
    DASHBOARD_LARGE_GROUP_TOTAL_STATIC_THRESHOLD,
    DASHBOARD_SIZE_LIMIT_DEFAULT_MB,
    summarize_dashboard_large_group_layer_options,
    summarize_dashboard_size_limit_options,
    summarize_dashboard_sampling_options,
)
from metroliza.charts.dashboard_visual_options import (
    dashboard_visual_group_names_from_grouping_frame,
    dashboard_visual_settings_summary,
    dashboard_visual_swatch_palette,
    load_dashboard_visual_settings,
)
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.shortcuts import (apply_dialog_mnemonics, bind_search_shortcut, install_button_commands,
                                    refresh_button_command_hints, set_mnemonic, visible_shortcut)
from metroliza.ui.output_request_summary import (
    analytics_summary, install_output_commands, output_summary, set_output_summary, tabular_scope,
)
from metroliza.industrial.industrial_analytics_service import discover_production_metric_candidates
from metroliza.ui.industrial_analytics_filter_dialog import IndustrialAnalyticsFilterDialog
from metroliza.industrial.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionFilterState,
    ProductionMetricSelection,
    ReferenceCohortState,
)
from metroliza.industrial.industrial_analytics_workflow import default_dashboard_path, default_workbook_path
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_workers import IndustrialAnalyticsThread, TabularAnalyticsLoadThread
from metroliza.industrial.tabular_output_publication import TabularOutputFiles, TabularOutputPublication
from metroliza.exporting.export_dialog_service import build_export_artifact_link_line
from metroliza.shared.progress_status import build_three_line_status
from metroliza.shared.safe_bugreport import BugReportAction, recorder as _bugreport_recorder
from metroliza.shared.safe_bugreport_context import ContextOperationOutcome, OptionSnapshotKind
from metroliza.ui.tabular_analytics_filter_dialog import (
    OPEN_TYPED_FILTER, TabularAnalyticsFilterDialog, TabularTypedFilterDialog,
)
from metroliza.tabular.tabular_typed_filter import (
    STALE_TYPED_FILTER, TYPED_FILTER_COMBINATION, supports_tabular_typed_filter,
)
from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog, _run_csv_scope_query
from metroliza.tabular.csv_summary_scope import canonical_filter_state, preview_filter_change
from metroliza.tabular.column_types import column_conversion_examples
from metroliza.tabular.reload_scope import (
    compatible_columns, compatible_filters, reconcile_reload_grouping, same_tabular_source,
)
from metroliza.analytics.row_table import RowTable
from metroliza.tabular.contracts import _GroupingSnapshotOwner, _ValidatedGroupingSnapshot
from metroliza.tabular.tabular_analytics_service import (
    TABULAR_DEFAULT_GROUP,
    TABULAR_EXCEL_SUFFIXES,
    TABULAR_GROUP_COLUMN,
    TABULAR_INPUT_SUFFIXES,
    TabularAnalyticsLoadResult,
    TabularColumnFilter,
    TabularSqliteStore,
    build_tabular_file_grouping_dataframe,
    cleanup_tabular_load_result,
    count_tabular_materialized_rows,
    list_tabular_excel_sheets,
    materialize_tabular_dataframe,
    tabular_file_group_labels,
    tabular_load_result_row_count,
    tabular_source_display_names,
)
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
try:
    from metroliza.ui.worker_progress_dialog import (
        dismiss_worker_progress_dialog,
        create_delayed_worker_progress_dialog as create_worker_progress_dialog,
    )
except ImportError:  # pragma: no cover - compatibility with lightweight test stubs.
    from metroliza.ui.worker_progress_dialog import create_worker_progress_dialog as _create_worker_progress_dialog

    def create_worker_progress_dialog(parent, *, window_title, initial_status_text, on_cancel, **_kwargs):
        return _create_worker_progress_dialog(
            parent, window_title=window_title, initial_status_text=initial_status_text, on_cancel=on_cancel,
        )

    def dismiss_worker_progress_dialog(dialog, *, rejected: bool = False) -> None:
        if dialog is None:
            return
        close_method = getattr(dialog, "reject" if rejected else "accept", None)
        if callable(close_method):
            close_method()
            return
        close = getattr(dialog, "close", None)
        if callable(close):
            close()

SOURCE_PRODUCTION_CACHE = "production_cache"
SOURCE_TABULAR_FILE = "tabular_file"
PRESENTATION_INDUSTRIAL_CACHE = "industrial_cache"


def _explicit_output_path(path: str) -> str:
    """Resolve generated relative paths so the UI always shows a real destination folder."""

    candidate = Path(path).expanduser()
    return str(candidate if candidate.is_absolute() else candidate.resolve())


def _coerce_int_or_none(value):
    try:
        if value is None or value != value:
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def dashboard_interactivity_options_summary(options: DashboardInteractivityOptions) -> str:
    sampling = summarize_dashboard_sampling_options(options)
    size_limit = summarize_dashboard_size_limit_options(options)
    return f"{sampling}; {size_limit}"


def dashboard_population_layer_options_summary(options: DashboardInteractivityOptions) -> str:
    return summarize_dashboard_large_group_layer_options(options)


class DashboardInteractivityOptionsDialog(QDialog):
    """Edit CSV Summary dashboard sample/interactivity options."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        options: DashboardInteractivityOptions | None = None,
        row_count: int | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Dashboard interactivity")
        self._options = options or DashboardInteractivityOptions()
        configure_window_size(self, minimum=(380, 220), initial=(460, 280))

        layout = QVBoxLayout(self)
        if row_count is not None and row_count > self._options.sample_size:
            notice = status_chip(
                f"{row_count:,} rows selected; interactive charts use a random sample limit",
                "warning",
            )
            layout.addWidget(notice)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Auto", "auto")
        self.mode_combo.addItem("Interactive random sample", "sampled")
        self.mode_combo.addItem("Snapshots only", "static")
        self.mode_combo.addItem("All rows", "full")
        index = self.mode_combo.findData(self._options.mode)
        self.mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self.mode_combo.currentIndexChanged.connect(self._sync_sample_size_enabled)
        form.addRow("Mode", self.mode_combo)

        self.sample_size_spin = QSpinBox()
        self.sample_size_spin.setRange(5_000, 200_000)
        self.sample_size_spin.setSingleStep(5_000)
        self.sample_size_spin.setValue(self._options.sample_size)
        form.addRow("Random sample limit", self.sample_size_spin)

        self.size_limit_combo = QComboBox()
        self.size_limit_combo.addItem("Default limit", "default")
        self.size_limit_combo.addItem("Custom limit", "custom")
        self.size_limit_combo.addItem("No size limit", "unlimited")
        size_index = self.size_limit_combo.findData(self._options.size_limit_mode)
        self.size_limit_combo.setCurrentIndex(size_index if size_index >= 0 else 0)
        self.size_limit_combo.currentIndexChanged.connect(self._sync_size_limit_enabled)
        form.addRow("Dashboard size limit", self.size_limit_combo)

        self.size_limit_spin = QSpinBox()
        self.size_limit_spin.setRange(1, 100_000)
        self.size_limit_spin.setSingleStep(24)
        self.size_limit_spin.setSuffix(" MB")
        self.size_limit_spin.setValue(
            self._options.size_limit_mb or DASHBOARD_SIZE_LIMIT_DEFAULT_MB
        )
        form.addRow("Size limit", self.size_limit_spin)
        layout.addLayout(form)
        layout.addWidget(
            status_chip(
                "No size limit can create very large HTML files and may freeze the browser.",
                "neutral",
            )
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        apply_button.setText("Apply")
        configure_dialog_button_roles(primary=apply_button, secondary=(cancel_button,))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        configure_accessibility(self.mode_combo, name="Dashboard interactivity mode")
        configure_accessibility(self.sample_size_spin, name="Dashboard interactivity sample size")
        configure_accessibility(self.size_limit_combo, name="Dashboard size limit mode")
        configure_accessibility(self.size_limit_spin, name="Dashboard size limit megabytes")
        self._sync_sample_size_enabled()
        self._sync_size_limit_enabled()

    def _sync_sample_size_enabled(self) -> None:
        self.sample_size_spin.setEnabled(self.mode_combo.currentData() in {"auto", "sampled"})

    def _sync_size_limit_enabled(self) -> None:
        self.size_limit_spin.setEnabled(self.size_limit_combo.currentData() == "custom")

    def interactivity_options(self) -> DashboardInteractivityOptions:
        return DashboardInteractivityOptions(
            mode=str(self.mode_combo.currentData() or "auto"),
            sample_size=self.sample_size_spin.value(),
            population_layer_mode=self._options.population_layer_mode,
            large_group_layer_mode=self._options.large_group_layer_mode,
            large_group_static_threshold=self._options.large_group_static_threshold,
            large_group_total_static_threshold=self._options.large_group_total_static_threshold,
            size_limit_mode=str(self.size_limit_combo.currentData() or "default"),
            size_limit_mb=self.size_limit_spin.value(),
        )


class DashboardPopulationLayerOptionsDialog(QDialog):
    """Edit CSV Summary large group layer rendering options."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        options: DashboardInteractivityOptions | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Large group layers")
        self._options = options or DashboardInteractivityOptions()
        configure_window_size(self, minimum=(380, 240), initial=(460, 320))

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.population_layer_combo = QComboBox()
        self.population_layer_combo.addItem("Auto", "auto")
        self.population_layer_combo.addItem("Interactive points", "interactive")
        self.population_layer_combo.addItem("Static image", "static")
        population_index = self.population_layer_combo.findData(
            self._options.large_group_layer_mode
        )
        self.population_layer_combo.setCurrentIndex(population_index if population_index >= 0 else 0)
        self.population_layer_combo.setToolTip(
            "Choose whether large CSV Summary groups stay interactive or render as static image layers."
        )
        form.addRow("Render as", self.population_layer_combo)

        self.group_threshold_spin = QSpinBox()
        self.group_threshold_spin.setRange(1, 10_000_000)
        self.group_threshold_spin.setSingleStep(1_000)
        self.group_threshold_spin.setValue(
            self._options.large_group_static_threshold
            or DASHBOARD_LARGE_GROUP_STATIC_THRESHOLD
        )
        form.addRow("Group threshold", self.group_threshold_spin)

        self.total_threshold_spin = QSpinBox()
        self.total_threshold_spin.setRange(1, 100_000_000)
        self.total_threshold_spin.setSingleStep(5_000)
        self.total_threshold_spin.setValue(
            self._options.large_group_total_static_threshold
            or DASHBOARD_LARGE_GROUP_TOTAL_STATIC_THRESHOLD
        )
        form.addRow("Total threshold", self.total_threshold_spin)

        layout.addLayout(form)
        layout.addWidget(
            status_chip(
                "Auto renders a group as a static image above the group threshold, or all supported groups above the total threshold.",
                "neutral",
            )
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        apply_button.setText("Apply")
        configure_dialog_button_roles(primary=apply_button, secondary=(cancel_button,))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        configure_accessibility(
            self.population_layer_combo,
            name="Dashboard large group layer mode",
        )
        configure_accessibility(
            self.group_threshold_spin,
            name="Dashboard large group static threshold",
        )
        configure_accessibility(
            self.total_threshold_spin,
            name="Dashboard total static threshold",
        )

    def interactivity_options(self) -> DashboardInteractivityOptions:
        mode = str(self.population_layer_combo.currentData() or "auto")
        return replace(
            self._options,
            population_layer_mode=mode,
            large_group_layer_mode=mode,
            large_group_static_threshold=self.group_threshold_spin.value(),
            large_group_total_static_threshold=self.total_threshold_spin.value(),
        )


def _analytics_has_warnings(result):
    return any(diagnostic.severity in {"warning", "error"}
               for diagnostic in getattr(result, "diagnostics", ()))


def build_analytics_completion_message(result) -> tuple[str, str, str, str]:
    """Build an export-style completion payload for generated analytics files."""

    dashboard_line = build_export_artifact_link_line("HTML dashboard", result.html_dashboard_path)
    workbook_line = build_export_artifact_link_line("Workbook", result.workbook_path)

    has_warnings = _analytics_has_warnings(result)
    message_lines = ["Analytics created with warnings." if has_warnings else "Analytics created successfully!"]
    for artifact_line in (dashboard_line, workbook_line):
        if artifact_line:
            message_lines.extend(["", artifact_line])
    message_lines.extend(
        [
            "",
            f"Charts: {result.html_dashboard_chart_count}",
            f"Rows analyzed: {result.row_count}",
            f"Metrics: {getattr(result, 'metric_count', 0)}",
        ]
    )
    reveal_path = str(result.workbook_path or "")
    level, title = ("warning", "Analytics completed with warnings") if has_warnings else ("info", "Analytics successful")
    return level, title, "\n".join(message_lines), reveal_path


class ColumnTypesDialog(QDialog):
    """Choose explicit types using raw input and the loader's converted values."""

    def __init__(self, parent, loaded, overrides):
        super().__init__(parent)
        self.loaded = loaded
        self.overrides = dict(overrides)
        self.setWindowTitle("Typy kolumn CSV i Excel")
        self.columns = QComboBox()
        self.kinds = QComboBox()
        self.inferred = QLabel()
        self.examples = QLabel()
        for label in (self.inferred, self.examples):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
        for identity in loaded.source_column_identities:
            name, occurrence = identity
            self.columns.addItem(name if occurrence == 1 else f"{name} ({occurrence})", identity)
        for label, kind in (("Wykryj automatycznie", "auto"), ("Tekst", "text"), ("Liczba", "number")):
            self.kinds.addItem(label, kind)
        self.columns.setAccessibleName("Kolumna źródłowa")
        self.kinds.setAccessibleName("Wybrany typ kolumny")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("&Kolumna", self.columns)
        form.addRow("&Typ", self.kinds)
        layout.addLayout(form)
        layout.addWidget(self.inferred)
        layout.addWidget(self.examples)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Zastosuj i odśwież")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.columns.currentIndexChanged.connect(self._show_column)
        self.kinds.currentIndexChanged.connect(self._set_type)
        self._show_column()
        apply_metroliza_theme(self)

    def _show_column(self):
        identity = self.columns.currentData()
        self.kinds.blockSignals(True)
        self.kinds.setCurrentIndex(self.kinds.findData(self.overrides.get(identity, "auto")))
        self.kinds.blockSignals(False)
        self._update_preview()

    def _set_type(self):
        identity, kind = self.columns.currentData(), self.kinds.currentData()
        if kind == "auto":
            self.overrides.pop(identity, None)
        else:
            self.overrides[identity] = kind
        self._update_preview()

    def _update_preview(self):
        identity = self.columns.currentData()
        kind = self.kinds.currentData()
        field = self.loaded.source_column_identities[identity]
        inferred = "liczba" if field in self.loaded.inferred_metric_columns else "tekst"
        if field == self.loaded.timestamp_column:
            inferred = "data i godzina"
        self.inferred.setText(f"Wykryty typ — {inferred}")
        try:
            examples = column_conversion_examples(self.loaded, identity, kind)
        except (OSError, sqlite3.Error):
            self.examples.setText("Nie udało się odczytać próbki. Odśwież dane.")
            return
        display = [f"{raw} → {converted if converted is not None else 'brak poprawnej liczby'}"
                   for raw, converted in examples if raw is not None]
        invalid = self.loaded.invalid_numeric_counts.get(field, 0)
        if kind == "number" and invalid:
            display.append(f"Liczba nieprawidłowych wartości w kolumnie — {invalid}")
        self.examples.setText("\n".join(display) or "Brak danych w próbce.")


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

        self.select_all_button = QPushButton("Zaznacz widoczne")
        self.clear_button = QPushButton("Odznacz widoczne")
        self.cancel_button = QPushButton("Cancel")
        self.apply_button = QPushButton("Use metrics")
        self.apply_button.setDefault(True)

        self.select_all_button.clicked.connect(lambda: self._set_metric_checks(True))
        self.clear_button.clicked.connect(lambda: self._set_metric_checks(False))
        self.cancel_button.clicked.connect(self._request_cancel)
        self.apply_button.clicked.connect(self._accept_selection)
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

        install_button_commands(self, "metrics")
        self.search_action = bind_search_shortcut(self, [(self.search_field, self.metrics_list)])
        self.search_field.setPlaceholderText("Search metrics [Ctrl+F]")
        self._populate_metrics(selected_fields)
        self._committed_metric_fields = self._selected_metric_fields()
        configure_dialog_button_roles(
            primary=self.apply_button,
            secondary=(self.cancel_button,),
            quiet=(self.select_all_button, self.clear_button),
        )
        apply_metroliza_theme(self)

    def _selected_metric_fields(self) -> tuple[str, ...]:
        return tuple(metric.field_name for metric in self.selected_metrics())

    def _request_cancel(self) -> None:
        if self._selected_metric_fields() != self._committed_metric_fields:
            answer = QMessageBox.question(
                self,
                "Discard metric changes?",
                "Discard changes to the selected metrics?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.reject()

    def _accept_selection(self) -> None:
        if not self.selected_metrics():
            return
        self._committed_metric_fields = self._selected_metric_fields()
        self.accept()

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
        self._filter_metrics()

    def _set_metric_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.metrics_list.blockSignals(True)
        for index in range(self.metrics_list.count()):
            item = self.metrics_list.item(index)
            if not item.isHidden():
                item.setCheckState(state)
        self.metrics_list.blockSignals(False)
        self._sync_summary()

    def _sync_summary(self) -> None:
        selected_count = len(self.selected_metrics())
        total_count = len(self.metrics)
        summary = f"Zaznaczono {selected_count} z {total_count} metryk"
        items = [self.metrics_list.item(index) for index in range(self.metrics_list.count())]
        visible = sum(not item.isHidden() for item in items)
        if self.search_field.text().strip():
            hidden_selected = sum(item.isHidden() and item.checkState() == Qt.CheckState.Checked for item in items)
            summary += f" · Widoczne {visible} · Zaznaczone poza wynikami {hidden_selected}"
        self.summary_label.setText(summary)
        self.select_all_button.setEnabled(bool(visible))
        self.clear_button.setEnabled(bool(visible))
        set_status_variant(self.summary_label, "success" if selected_count else "warning")
        self.apply_button.setEnabled(bool(selected_count))

    def _filter_metrics(self) -> None:
        search = self.search_field.text().strip().casefold()
        for index in range(self.metrics_list.count()):
            item = self.metrics_list.item(index)
            metric = item.data(Qt.ItemDataRole.UserRole)
            label = item.text()
            field_name = metric.field_name if isinstance(metric, ProductionMetricSelection) else ""
            visible = not search or search in label.casefold() or search in field_name.casefold()
            item.setHidden(not visible)
        self._sync_summary()

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
            self.table.setItem(row, 1, QTableWidgetItem("" if lsl is None else str(lsl)))
            self.table.setItem(row, 2, QTableWidgetItem("" if usl is None else str(usl)))

        self.status_label = status_chip(
            "Leave one side blank for one-sided tolerance; leave both blank for no limits.",
            "info",
        )
        self.cancel_button = QPushButton("Cancel")
        self.apply_button = QPushButton("Use limits")
        self.apply_button.setDefault(True)
        self.cancel_button.clicked.connect(self._request_cancel)
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
        install_button_commands(self, "limits")
        self._committed_limits_signature = self._limits_signature()
        self._initial_limits, _error = self._parsed_limits()
        self.table.itemChanged.connect(lambda _item: self._sync_validation())
        configure_dialog_button_roles(
            primary=self.apply_button,
            secondary=(self.cancel_button,),
        )
        apply_metroliza_theme(self)

    def _limits_signature(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                "" if self.table.item(row, 1) is None else self.table.item(row, 1).text().strip(),
                "" if self.table.item(row, 2) is None else self.table.item(row, 2).text().strip(),
            )
            for row in range(self.table.rowCount())
        )

    def _request_cancel(self) -> None:
        if self._limits_signature() != self._committed_limits_signature:
            answer = QMessageBox.question(
                self,
                "Discard limit changes?",
                "Discard changes to metric limits?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.reject()

    def _parsed_limits(self) -> tuple[dict[str, tuple[float | None, float | None]], str]:
        parsed: dict[str, tuple[float | None, float | None]] = {}
        for row in range(self.table.rowCount()):
            metric_item = self.table.item(row, 0)
            if metric_item is None:
                continue
            field_name = str(metric_item.data(Qt.ItemDataRole.UserRole) or "").strip()
            lsl = self._optional_float(row, 1)
            usl = self._optional_float(row, 2)
            if isinstance(lsl, str) or isinstance(usl, str):
                return {}, f"Invalid numeric limit for {metric_item.text()}."
            if lsl is not None and usl is not None and lsl >= usl:
                return {}, f"LSL must be lower than USL for {metric_item.text()}."
            if field_name:
                parsed[field_name] = (lsl, usl)
        return parsed, ""

    def _sync_validation(self) -> None:
        _parsed, error = self._parsed_limits()
        self.apply_button.setEnabled(not error)
        if error:
            self.status_label.setText(error)
            set_status_variant(self.status_label, "danger")
            return
        self.status_label.setText(
            "Leave one side blank for one-sided tolerance; leave both blank for no limits."
        )
        set_status_variant(self.status_label, "info")

    def limits(self) -> dict[str, tuple[float | None, float | None]]:
        return dict(self._limits)

    def _accept_if_valid(self) -> None:
        parsed, error = self._parsed_limits()
        if error:
            self._sync_validation()
            return
        self._limits = {field: value for field, value in parsed.items() if value != self._initial_limits.get(field)}
        self._committed_limits_signature = self._limits_signature()
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


@dataclass(frozen=True)
class _TabularChoices:
    selected: tuple[ProductionMetricSelection, ...]
    limits: dict[str, tuple[float | None, float | None]]
    group_field: str
    grouping: object
    groupstats: bool
    filters: tuple


class IndustrialAnalyticsDialog(QDialog):
    analysis_completed = pyqtSignal(object)

    """Configure and run production or CSV/Excel analytics."""

    def __init__(
        self,
        parent=None,
        *,
        db_file: str | None = None,
        source_kind: str = SOURCE_PRODUCTION_CACHE,
        tabular_load_result=None,
        input_file: str | None = None,
        source_label_override: str | None = None,
        presentation_mode: str | None = None,
    ):
        super().__init__(parent)
        if source_kind not in {SOURCE_PRODUCTION_CACHE, SOURCE_TABULAR_FILE}:
            raise ValueError(f"Unsupported analytics source kind: {source_kind}")
        self.db_file = db_file or ""
        self.source_kind = source_kind
        self.input_file = input_file or ""
        self.input_files: tuple[str, ...] = (self.input_file,) if self.input_file else ()
        self._source_label_override = source_label_override
        self.presentation_mode = self._normalize_presentation_mode(
            presentation_mode,
            tabular_load_result=tabular_load_result,
        )
        self._preloaded_tabular_source = bool(
            source_kind == SOURCE_TABULAR_FILE and tabular_load_result is not None
        )
        self.output_dashboard_file = _explicit_output_path(
            default_dashboard_path(self.db_file or "production_analytics")
        )
        self.output_workbook_file = _explicit_output_path(
            default_workbook_path(self.db_file or "production_analytics")
        )
        self.analytics_thread = None
        self._analysis_source_stamp = None
        self.tabular_load_thread = None
        self._applying_tabular_load = None
        self._worker_progress = {}
        self.metric_candidates: tuple[ProductionMetricSelection, ...] = ()
        self.metric_spec_limits: dict[str, tuple[float | None, float | None]] = {}
        self.dashboard_visual_settings = load_dashboard_visual_settings()
        self.filter_state = ProductionFilterState()
        self.tabular_load_result = None
        self.tabular_filter_columns: tuple[str, ...] = ()
        self.tabular_filter_keys: tuple[tuple[str, ...], ...] = ()
        self.tabular_column_filters: tuple[TabularColumnFilter, ...] = ()
        self.tabular_filter_expression = ""
        self._tabular_typed_filter = None
        self._tabular_typed_count = 0
        self._tabular_row_count_cache: tuple[object, tuple, int] | None = None
        self.df_for_grouping = None
        self.grouping_applied = False
        self._grouping_snapshot_owner = _GroupingSnapshotOwner()
        self._pending_analytics_request = None
        self._pending_output_publication: TabularOutputPublication | None = None
        self._choosing_output = False
        self._pending_grouping_snapshot: _ValidatedGroupingSnapshot | None = None
        self._auto_group_selected_files = False
        self._tabular_reload_notice = ""
        self._tabular_refresh_result = ""
        self._tabular_refresh_lost = False
        self._pending_role_reload = None
        self._column_type_overrides = {}
        self.dashboard_interactivity_options = DashboardInteractivityOptions()

        self.setWindowTitle(self._window_title_for_source())
        configure_window_size(self, minimum=(720, 560), initial=(880, 680))

        self.source_label = status_chip(self._source_summary(), "neutral")
        self.tabular_source_status_label = status_chip(
            "Load CSV/Excel data to review detected rows, files, and columns.",
            "neutral",
        )
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
        self.dashboard_interactivity_row_label = section_label("Dashboard interactivity")
        self.dashboard_interactivity_summary_label = status_chip("", "neutral")
        self.dashboard_interactivity_button = QPushButton("Change...")
        self.dashboard_interactivity_button.setToolTip(
            "Adjust CSV Summary chart interactivity and random sample limits for large datasets."
        )
        self.dashboard_interactivity_button.clicked.connect(self.open_dashboard_interactivity_options)
        self.population_layer_row_label = section_label("Large group layers")
        self.population_layer_summary_label = status_chip("", "neutral")
        self.population_layer_button = QPushButton("Change...")
        self.population_layer_button.setToolTip(
            "Choose whether large CSV Summary groups are interactive or static, and tune thresholds."
        )
        self.population_layer_button.clicked.connect(self.open_population_layer_options)
        self.dashboard_visuals_row_label = section_label("Dashboard style")
        self.dashboard_visuals_summary_label = status_chip("", "neutral")
        self.dashboard_visuals_button = QPushButton("Change...")
        self.dashboard_visuals_button.setToolTip(
            "Adjust dashboard style, colors, markers, selected-element opacity, group appearance, and reference/stat lines."
        )
        self.dashboard_visuals_button.clicked.connect(self.open_dashboard_visual_options)
        self.readiness_label = status_chip("Load metrics and choose an output path.", "warning")
        self.readiness_label.setTextFormat(Qt.TextFormat.PlainText)
        self.readiness_label.setWordWrap(True)
        self.request_summary_label = status_chip("", "info")
        self.request_summary_label.setWordWrap(True)
        configure_accessibility(self.request_summary_label, name="Analytics request scope and outputs")
        self.filter_row_label = section_label("Filters")
        self.filter_summary_label = status_chip(self.filter_state.summary(), "neutral")
        self.metrics_summary_label = status_chip("No metrics loaded", "warning")
        self.grouping_row_label = section_label("Group by")
        self.group_rule_label = section_label("Reguła grupowania")
        self.grouping_summary_label = status_chip("Groups: not applied", "neutral")
        self.advanced_section_label = section_label("Advanced")
        self.advanced_toggle_button = QPushButton("Show advanced options")
        self.advanced_toggle_button.setCheckable(True)
        self.advanced_toggle_button.setToolTip(
            "Show dashboard tuning and advanced chart settings."
        )
        self.advanced_toggle_button.toggled.connect(self._toggle_advanced_options)
        self.advanced_options_container = QWidget()
        self.advanced_options_container.setVisible(False)

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
        self.group_rule_label.setBuddy(self.group_field_combo)
        self.group_field_combo.activated.connect(self._apply_grouping_rule)
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
        reference_action_tooltip = "Pasted references create an analysis-only cohort for this run."
        self.reference_mode_combo.setToolTip(reference_action_tooltip)
        self.references_edit = QPlainTextEdit()
        self.references_edit.setPlaceholderText("Paste Part / IDs to highlight/filter; separate with comma, semicolon, space, or new line")
        self.references_edit.setMaximumHeight(90)
        self.references_edit.setToolTip(reference_action_tooltip)
        self.reference_mode_hint_label = status_chip(
            "Pasted references affect only this analytics run.",
            "info",
        )

        self.time_series_checkbox = QCheckBox("Time series")
        self.histogram_checkbox = QCheckBox("Histogram")
        self.violin_checkbox = QCheckBox("Violin")
        self.box_checkbox = QCheckBox("Box")
        self.groupstats_checkbox = QCheckBox("Groupstats")
        self.groupstats_reason_label = status_chip("", "warning")
        self.groupstats_reason_label.setVisible(False)
        self.workbook_checkbox = QCheckBox("Output workbook (XLSX)")
        self.parameter_sheets_checkbox = QCheckBox("Separate sheet per selected parameter")
        self.time_series_checkbox.setChecked(True)
        self.histogram_checkbox.setChecked(True)
        self.violin_checkbox.setChecked(True)
        self.box_checkbox.setChecked(True)
        self.groupstats_checkbox.setChecked(True)
        self.workbook_checkbox.setChecked(False)
        self.parameter_sheets_checkbox.setChecked(True)
        self.reference_mode_combo.currentIndexChanged.connect(
            lambda _index: self._sync_groupstats_output_for_reference_change()
        )
        self.references_edit.textChanged.connect(self._sync_groupstats_output_for_reference_change)

        self.browse_input_button = QPushButton("Browse")
        self.filters_button = QPushButton("Filters...")
        self.clear_filter_button = QPushButton("Clear filter")
        self.load_metrics_button = QPushButton("Load metrics")
        self.column_types_button = QPushButton("Typy kolumn…")
        self.column_types_button.clicked.connect(self.open_column_types)
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
        self.clear_filter_button.clicked.connect(self.clear_tabular_filter)
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
        install_output_commands(self, self.start_button, self._stop_active_analytics, self.reject, self.choose_metrics_button.click)
        visible_shortcut(self.close_button, "Ctrl+W / Esc")
        visible_shortcut(self.choose_metrics_button, "Ctrl+F")
        install_button_commands(self, "csv_summary")
        self._configure_accessibility()
        configure_dialog_button_roles(
            primary=self.start_button,
            secondary=(self.close_button,),
            quiet=(
                self.browse_input_button,
                self.filters_button,
                self.clear_filter_button,
                self.load_metrics_button,
                self.choose_metrics_button,
                self.edit_limits_button,
                self.edit_groups_button,
                self.clear_groups_button,
                self.dashboard_button,
                self.workbook_button,
                self.dashboard_interactivity_button,
                self.population_layer_button,
                self.dashboard_visuals_button,
                self.advanced_toggle_button,
            ),
        )
        self._sync_source_visibility()
        self._reset_group_options(())
        if tabular_load_result is not None:
            self._apply_tabular_load_result(tabular_load_result, populate_metrics=True)
            if source_label_override:
                self.source_label.setText(source_label_override)
        self._sync_ui_state()
        apply_metroliza_theme(self)

    @property
    def is_production_source(self) -> bool:
        return self.source_kind == SOURCE_PRODUCTION_CACHE

    @property
    def is_preloaded_tabular_source(self) -> bool:
        return bool(self._preloaded_tabular_source and not self.is_production_source)

    @property
    def is_industrial_cache_presentation(self) -> bool:
        return bool(
            self.is_preloaded_tabular_source
            and self.presentation_mode == PRESENTATION_INDUSTRIAL_CACHE
        )

    @staticmethod
    def _normalize_presentation_mode(
        presentation_mode: str | None,
        *,
        tabular_load_result=None,
    ) -> str:
        value = str(presentation_mode or "").strip().lower()
        if not value:
            csv_config = getattr(tabular_load_result, "csv_config", {}) or {}
            if isinstance(csv_config, dict) and csv_config.get("source") == PRESENTATION_INDUSTRIAL_CACHE:
                return PRESENTATION_INDUSTRIAL_CACHE
            return ""
        if value != PRESENTATION_INDUSTRIAL_CACHE:
            raise ValueError(f"Unsupported analytics presentation mode: {presentation_mode}")
        return value

    def _window_title_for_source(self) -> str:
        if self.is_production_source:
            return "Production analytics"
        if self.is_industrial_cache_presentation:
            return "Industrial cache CSV Summary"
        return "CSV Summary"

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        help_entries = [("Export manual", "export_overview")]
        if not self.is_production_source:
            help_entries.append(("CSV Summary manual", "csv_summary"))
        if self.is_industrial_cache_presentation:
            help_entries.append(("Industrial Data manual", "industrial_data"))
        # F1 opens this window's own manual, not the Export manual listed first.
        f1_manual = help_entries[-1][1]
        self.dialog_menu_bar, self.help_menu = attach_help_menu_to_layout(
            layout, self, help_entries, f1_manual=f1_manual
        )

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
        grid.addWidget(self.tabular_source_status_label, row, 0, 1, 3)

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
        metric_actions.addWidget(self.column_types_button)
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
        if self.is_production_source:
            grid.addWidget(self.group_field_combo, row, 1, 1, 2)
        grid.addWidget(self.grouping_summary_label, row, 1)
        grid.addLayout(grouping_actions, row, 2)

        if not self.is_production_source:
            row += 1
            grid.addWidget(self.group_rule_label, row, 0)
            grid.addWidget(self.group_field_combo, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Time bucket"), row, 0)
        grid.addWidget(self.time_bucket_combo, row, 1, 1, 2)

        row += 1
        grid.addWidget(section_label("Aggregation"), row, 0)
        grid.addWidget(self.aggregation_combo, row, 1, 1, 2)

        row += 1
        self.reference_mode_row_label = section_label("Pasted reference action")
        grid.addWidget(self.reference_mode_row_label, row, 0)
        grid.addWidget(self.reference_mode_combo, row, 1, 1, 2)

        row += 1
        self.references_row_label = section_label("References")
        grid.addWidget(self.references_row_label, row, 0)
        grid.addWidget(self.references_edit, row, 1, 1, 2)

        row += 1
        grid.addWidget(self.reference_mode_hint_label, row, 1, 1, 2)

        if self.is_production_source:
            row = self._add_chart_option_rows(grid, row)
            row = self._add_dashboard_output_row(grid, row)
            row = self._add_dashboard_tuning_rows(grid, row)
            row = self._add_workbook_rows(grid, row)
        else:
            row = self._add_dashboard_output_row(grid, row)
            row = self._add_workbook_rows(grid, row)
            self._build_advanced_options_layout()
            row += 1
            grid.addWidget(self.advanced_section_label, row, 0, 1, 3)

            row += 1
            grid.addWidget(self.advanced_toggle_button, row, 0, 1, 3)

            row += 1
            grid.addWidget(self.advanced_options_container, row, 0, 1, 3)

        content_layout.addLayout(grid)
        scroll_area.setWidget(content)
        layout.addWidget(scroll_area, 1)
        layout.addWidget(self.request_summary_label)
        layout.addWidget(self.readiness_label)
        self.last_result_row = LastResultRow(self, "Last run")
        layout.addWidget(self.last_result_row)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        self.save_recipe_button = QPushButton("Save as recipe")
        self.save_recipe_button.clicked.connect(self._save_as_recipe)
        actions.addWidget(self.save_recipe_button)
        actions.addWidget(self.close_button)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)

    def _build_advanced_options_layout(self) -> None:
        advanced_layout = QGridLayout(self.advanced_options_container)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setHorizontalSpacing(10)
        advanced_layout.setVerticalSpacing(8)
        advanced_layout.setColumnStretch(1, 1)
        row = -1
        row = self._add_chart_option_rows(advanced_layout, row)
        self._add_dashboard_tuning_rows(advanced_layout, row)

    def _add_chart_option_rows(self, grid: QGridLayout, row: int) -> int:
        row += 1
        chart_actions = QHBoxLayout()
        chart_actions.setContentsMargins(0, 0, 0, 0)
        chart_actions.setSpacing(10)
        for checkbox in (
            self.time_series_checkbox,
            self.histogram_checkbox,
            self.violin_checkbox,
            self.box_checkbox,
        ):
            chart_actions.addWidget(checkbox)
        chart_actions.addStretch(1)
        grid.addWidget(section_label("Charts"), row, 0)
        grid.addLayout(chart_actions, row, 1, 1, 2)

        row += 1
        statistics_actions = QHBoxLayout()
        statistics_actions.setContentsMargins(0, 0, 0, 0)
        statistics_actions.setSpacing(10)
        statistics_actions.addWidget(self.groupstats_checkbox)
        statistics_actions.addStretch(1)
        grid.addWidget(section_label("Statistics"), row, 0)
        grid.addLayout(statistics_actions, row, 1, 1, 2)

        row += 1
        grid.addWidget(self.groupstats_reason_label, row, 1, 1, 2)
        return row

    def _add_dashboard_output_row(self, grid: QGridLayout, row: int) -> int:
        row += 1
        grid.addWidget(section_label("Dashboard (HTML, always)"), row, 0)
        grid.addWidget(self.dashboard_path_field, row, 1)
        grid.addWidget(self.dashboard_button, row, 2)
        return row

    def _add_dashboard_tuning_rows(self, grid: QGridLayout, row: int) -> int:
        row += 1
        dashboard_interactivity_actions = QHBoxLayout()
        dashboard_interactivity_actions.setContentsMargins(0, 0, 0, 0)
        dashboard_interactivity_actions.setSpacing(8)
        dashboard_interactivity_actions.addWidget(self.dashboard_interactivity_summary_label)
        dashboard_interactivity_actions.addWidget(self.dashboard_interactivity_button)
        dashboard_interactivity_actions.addStretch(1)
        grid.addWidget(self.dashboard_interactivity_row_label, row, 0)
        grid.addLayout(dashboard_interactivity_actions, row, 1, 1, 2)

        row += 1
        population_layer_actions = QHBoxLayout()
        population_layer_actions.setContentsMargins(0, 0, 0, 0)
        population_layer_actions.setSpacing(8)
        population_layer_actions.addWidget(self.population_layer_summary_label)
        population_layer_actions.addWidget(self.population_layer_button)
        population_layer_actions.addStretch(1)
        grid.addWidget(self.population_layer_row_label, row, 0)
        grid.addLayout(population_layer_actions, row, 1, 1, 2)

        row += 1
        dashboard_visuals_actions = QHBoxLayout()
        dashboard_visuals_actions.setContentsMargins(0, 0, 0, 0)
        dashboard_visuals_actions.setSpacing(8)
        dashboard_visuals_actions.addWidget(self.dashboard_visuals_summary_label)
        dashboard_visuals_actions.addWidget(self.dashboard_visuals_button)
        dashboard_visuals_actions.addStretch(1)
        grid.addWidget(self.dashboard_visuals_row_label, row, 0)
        grid.addLayout(dashboard_visuals_actions, row, 1, 1, 2)
        return row

    def _add_workbook_rows(self, grid: QGridLayout, row: int) -> int:
        row += 1
        grid.addWidget(section_label("Output workbook"), row, 0)
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
        return row

    def _configure_accessibility(self) -> None:
        configure_accessibility(self.source_label, name="Analytics source summary")
        configure_accessibility(self.tabular_source_status_label, name="Detected CSV Summary source")
        configure_accessibility(self.database_field, name="Analytics report database")
        configure_accessibility(self.input_file_field, name="CSV or Excel input file")
        configure_accessibility(self.dashboard_path_field, name="CSV Summary dashboard output path")
        configure_accessibility(self.workbook_path_field, name="CSV Summary workbook output path")
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
        configure_accessibility(self.group_field_combo, name=(
            "Production grouping field" if self.is_production_source else "Kolumna reguły grupowania"
        ))
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
        configure_accessibility(
            self.dashboard_interactivity_button,
            name="Edit dashboard interactivity",
            description=self.dashboard_interactivity_button.toolTip(),
        )
        configure_accessibility(
            self.population_layer_button,
            name="Edit dashboard large group layers",
            description=self.population_layer_button.toolTip(),
        )
        configure_accessibility(self.groupstats_checkbox, name="Include groupstats output")
        configure_accessibility(self.dashboard_visuals_button, name="Edit dashboard visuals")
        configure_accessibility(
            self.advanced_toggle_button,
            name="Show advanced CSV Summary analytics options",
            description=self.advanced_toggle_button.toolTip(),
        )
        configure_accessibility(self.dashboard_button, name="Select analytics dashboard path")
        configure_accessibility(self.workbook_button, name="Select analytics workbook path")
        configure_accessibility(self.close_button, name="Close analytics dialog")
        configure_accessibility(self.start_button, name="Create analytics output")

    def _source_summary(self) -> str:
        if self._source_label_override:
            return self._source_label_override
        if self.is_production_source:
            return "Cached Oznak production data"
        if self.is_industrial_cache_presentation:
            return "Industrial cache for CSV Summary"
        if self.is_preloaded_tabular_source:
            return "Preloaded CSV Summary data"
        return "CSV or Excel table"

    def _sync_source_visibility(self) -> None:
        show_tabular = not self.is_production_source
        show_file = show_tabular and not self.is_preloaded_tabular_source
        show_database = self.is_production_source or self.is_industrial_cache_presentation
        self.tabular_source_status_label.setVisible(show_tabular and self.tabular_load_result is not None)
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
        if self.is_production_source:
            self.filter_row_label.setText("Filters")
        elif self.is_industrial_cache_presentation:
            self.filter_row_label.setText("Cache row filter")
        else:
            self.filter_row_label.setText("Row filter")
        self._sync_filter_visibility()
        if self.is_production_source:
            self.filters_button.setText("Filters...")
        elif self.is_industrial_cache_presentation:
            self.filters_button.setText("Filter cached rows...")
        else:
            self.filters_button.setText("Filter rows...")
        if not self.is_production_source:
            set_mnemonic(self.filters_button, "f")
        refresh_button_command_hints(self, "csv_summary")
        self.clear_filter_button.setVisible(show_tabular)
        self.dashboard_interactivity_row_label.setVisible(show_tabular)
        self.dashboard_interactivity_summary_label.setVisible(show_tabular)
        self.dashboard_interactivity_button.setVisible(show_tabular)
        self.population_layer_row_label.setVisible(show_tabular)
        self.population_layer_summary_label.setVisible(show_tabular)
        self.population_layer_button.setVisible(show_tabular)
        show_reference_cohort = self.is_production_source
        for widget in (
            self.reference_mode_row_label,
            self.reference_mode_combo,
            self.references_row_label,
            self.references_edit,
            self.reference_mode_hint_label,
        ):
            widget.setVisible(show_reference_cohort)
        self.database_row_label.setVisible(show_database)
        self.database_field.setVisible(show_database)
        self.grouping_row_label.setText("Group by" if self.is_production_source else "Groups")
        show_rules = show_tabular and not self.is_preloaded_tabular_source
        self.group_rule_label.setVisible(show_rules)
        self.group_field_combo.setVisible(self.is_production_source or show_rules)
        self.grouping_summary_label.setVisible(show_tabular)
        self.edit_groups_button.setVisible(show_tabular)
        self.clear_groups_button.setVisible(show_tabular)
        self._sync_filter_summary()
        self._sync_tabular_source_status()
        self._sync_advanced_options_visibility()
        self._sync_dashboard_interactivity_controls()
        self._sync_population_layer_controls()
        self._sync_dashboard_visual_controls()

    def _toggle_advanced_options(self, expanded: bool) -> None:
        self._sync_advanced_options_visibility(expanded=expanded)

    def _sync_advanced_options_visibility(self, *, expanded: bool | None = None) -> None:
        if not hasattr(self, "advanced_options_container"):
            return
        show_advanced = not self.is_production_source
        if expanded is None:
            expanded = self.advanced_toggle_button.isChecked()
        self.advanced_section_label.setVisible(show_advanced)
        self.advanced_toggle_button.setVisible(show_advanced)
        self.advanced_options_container.setVisible(show_advanced and bool(expanded))
        self.advanced_toggle_button.setText(
            "Hide advanced options" if show_advanced and expanded else "Show advanced options"
        )
        if show_advanced:
            set_mnemonic(self.advanced_toggle_button, "a")

    def _sync_tabular_source_status(self) -> None:
        if not hasattr(self, "tabular_source_status_label"):
            return
        if self.is_production_source or self.tabular_load_result is None:
            self.tabular_source_status_label.setText(
                "Load CSV/Excel data to review detected rows, files, and columns."
            )
            self.tabular_source_status_label.setVisible(False)
            set_status_variant(self.tabular_source_status_label, "neutral")
            return
        self.tabular_source_status_label.setText(
            self._tabular_source_status_summary(self.tabular_load_result)
        )
        self.tabular_source_status_label.setVisible(True)
        set_status_variant(self.tabular_source_status_label, "success")

    def _tabular_source_status_summary(self, loaded) -> str:
        row_count = tabular_load_result_row_count(loaded)
        metric_count = len(tuple(getattr(loaded, "metric_candidates", ()) or ()))
        source_files = tuple(getattr(loaded, "source_files", ()) or self._selected_input_files())
        source_text = self._tabular_source_status_source_text(source_files)
        details = [
            f"Detected source: {self._count_phrase(row_count, 'row')} from {source_text}",
            f"{self._count_phrase(metric_count, 'metric')}",
        ]
        sheet_name = str(getattr(loaded, "sheet_name", "") or "").strip()
        if sheet_name:
            details.append(f"sheet {sheet_name}")
        details.append(
            "time column "
            + self._tabular_column_status_label(
                loaded,
                getattr(loaded, "timestamp_column", None),
                missing="not detected",
            )
        )
        details.append(
            "part / ID column "
            + self._tabular_column_status_label(
                loaded,
                getattr(loaded, "reference_column", None),
                missing="not detected",
            )
        )
        if str(getattr(loaded, "storage_mode", "") or "") == "sqlite":
            details.append("large-file row store")
        return "; ".join(details) + "."

    def _tabular_source_status_source_text(self, source_files: tuple[str, ...]) -> str:
        if len(source_files) > 1:
            suffixes = {Path(path).suffix.lower() for path in source_files}
            kind = "CSV" if suffixes == {".csv"} else "Excel" if suffixes <= TABULAR_EXCEL_SUFFIXES else "CSV/Excel"
            return self._count_phrase(len(source_files), f"{kind} file")
        if source_files:
            return Path(source_files[0]).name
        if self.input_file:
            return Path(self.input_file).name
        return "loaded table"

    @staticmethod
    def _tabular_column_status_label(loaded, normalized_column: str | None, *, missing: str) -> str:
        normalized = str(normalized_column or "").strip()
        if not normalized:
            return missing
        for original, mapped in (getattr(loaded, "column_mapping", {}) or {}).items():
            if str(mapped) != normalized:
                continue
            original_text = str(original)
            return (
                f"{original_text} ({normalized})"
                if original_text and original_text != normalized
                else normalized
            )
        return normalized

    @staticmethod
    def _count_phrase(count: int, singular: str) -> str:
        count = int(count or 0)
        if count == 1:
            return f"{count:,} {singular}"
        return f"{count:,} {singular}s"

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

    def _sync_dashboard_visual_controls(self) -> None:
        if not hasattr(self, "dashboard_visuals_summary_label"):
            return
        summary = dashboard_visual_settings_summary(self.dashboard_visual_settings)
        palette = dashboard_visual_swatch_palette(self.dashboard_visual_settings, count=6)
        self.dashboard_visuals_summary_label.setText(summary)
        self.dashboard_visuals_summary_label.setToolTip(" ".join(palette))

    def _sync_dashboard_interactivity_controls(self) -> None:
        if not hasattr(self, "dashboard_interactivity_summary_label"):
            return
        summary = dashboard_interactivity_options_summary(self.dashboard_interactivity_options)
        self.dashboard_interactivity_summary_label.setText(summary)
        self.dashboard_interactivity_summary_label.setToolTip(
            f"{summary}. This controls the interactive Plotly payload and random sampling limit."
        )

    def _sync_population_layer_controls(self) -> None:
        if not hasattr(self, "population_layer_summary_label"):
            return
        summary = dashboard_population_layer_options_summary(self.dashboard_interactivity_options)
        self.population_layer_summary_label.setText(summary)
        self.population_layer_summary_label.setToolTip(
            f"{summary}. Static image appearance follows each group element in Dashboard style."
        )

    def open_dashboard_interactivity_options(self) -> None:
        dialog = DashboardInteractivityOptionsDialog(
            self,
            options=self.dashboard_interactivity_options,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            request = validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind=self.source_kind,
                    output_dashboard_file=self.output_dashboard_file,
                    dashboard_interactivity_options=dialog.interactivity_options(),
                )
            )
            self.dashboard_interactivity_options = request.dashboard_interactivity_options
            self._sync_dashboard_interactivity_controls()
            self._sync_population_layer_controls()

    def open_population_layer_options(self) -> None:
        dialog = DashboardPopulationLayerOptionsDialog(
            self,
            options=self.dashboard_interactivity_options,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            request = validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind=self.source_kind,
                    output_dashboard_file=self.output_dashboard_file,
                    dashboard_interactivity_options=dialog.interactivity_options(),
                )
            )
            self.dashboard_interactivity_options = request.dashboard_interactivity_options
            self._sync_dashboard_interactivity_controls()
            self._sync_population_layer_controls()

    def open_dashboard_visual_options(self) -> None:
        try:
            from metroliza.ui.dashboard_visual_options_dialog import DashboardVisualOptionsDialog

            dialog = DashboardVisualOptionsDialog(
                self,
                settings=self.dashboard_visual_settings,
                preview_group_names=dashboard_visual_group_names_from_grouping_frame(
                    self.df_for_grouping if self.grouping_applied else None
                ),
            )
            if dialog.exec():
                self.dashboard_visual_settings = dialog.visual_settings()
                self._sync_dashboard_visual_controls()
        except Exception as exc:
            QMessageBox.warning(self, self.windowTitle(), f"Could not open dashboard visuals: {exc}")

    def _tabular_source_busy(self) -> bool:
        # The terminal handler releases ownership after all worker signals finish.
        return not self.is_production_source and (
            self.tabular_load_thread is not None or self.analytics_thread is not None
            or getattr(self, "_scope_query_running", False)
        )

    def _tabular_reload_busy(self) -> bool:
        return not self.is_production_source and self.tabular_load_thread is not None

    def _handle_tabular_source_changed(self, _text: str = "") -> None:
        if self.is_production_source or self._tabular_source_busy():
            return
        if self.input_file and (self.tabular_load_result is not None or self.metric_candidates):
            self._tabular_reload_notice = "Reload CSV/Excel data after changing the selected sheet."
        self.metric_candidates = ()
        self._column_type_overrides = {}
        self._discard_role_reload()
        self._set_tabular_load_result(None)
        self.metric_spec_limits = {}
        self._clear_tabular_filter()
        self._clear_tabular_grouping()
        self.metrics_list.clear()
        self._reset_group_options(())
        self._reset_tabular_column_options()
        self._sync_ui_state()

    def _handle_tabular_column_changed(self, _text: str = "") -> None:
        if self.is_production_source or self._tabular_source_busy():
            return
        if self.tabular_load_result is None or self.is_preloaded_tabular_source:
            return
        self._pending_role_reload = (self.tabular_load_result, self._tabular_choices())
        self.tabular_load_result = None  # Keep the previous store until the proposed reload is accepted.
        self._tabular_reload_notice = (
            "Odśwież dane po zmianie roli kolumny. Przed zastosowaniem zobaczysz, które ustawienia wymagają poprawy."
        )
        self.metric_candidates = ()
        self._set_tabular_load_result(None)
        self.metric_spec_limits = {}
        self._clear_tabular_filter()
        self._clear_tabular_grouping()
        self.metrics_list.clear()
        self._reset_group_options(())
        self._sync_ui_state()

    def _discard_role_reload(self):
        if self._pending_role_reload is not None:
            cleanup_tabular_load_result(self._pending_role_reload[0])
            self._pending_role_reload = None

    def _clear_tabular_grouping(self) -> None:
        self._grouping_snapshot_owner.invalidate()
        self.df_for_grouping = None
        self.grouping_applied = False
        self._set_groupstats_output_checked(False)

    def _clear_tabular_filter(self) -> None:
        self.tabular_filter_columns = ()
        self.tabular_filter_keys = ()
        self.tabular_column_filters = ()
        self.tabular_filter_expression = ""
        self._tabular_typed_filter = None
        self._tabular_typed_count = 0

    def _set_tabular_load_result(self, loaded) -> None:
        current = self.tabular_load_result
        if current is not None and current is not loaded:
            cleanup_tabular_load_result(current)
        self.tabular_load_result = loaded
        self._tabular_row_count_cache = None
        self._tabular_refresh_result = ""
        self._tabular_refresh_lost = False

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
        names = tabular_source_display_names(input_files)
        preview = ", ".join(names[:3])
        if len(names) > 3:
            preview = f"{preview}, +{len(names) - 3} more"
        return f"{self._tabular_source_status_source_text(input_files)}: {preview}"

    def _tabular_filter_state_key(self) -> tuple:
        return (
            tuple(self.tabular_filter_columns or ()),
            tuple(tuple(keys) for keys in (self.tabular_filter_keys or ())),
            tuple(self.tabular_column_filters or ()),
            str(self.tabular_filter_expression or ""),
        )

    def _is_bugreport_industrial_context(self) -> bool:
        return bool(self.is_production_source or self.is_industrial_cache_presentation)

    def _record_bugreport_analytics_outcome(self, outcome: str, *, warnings: bool = False) -> None:
        industrial_context = self._is_bugreport_industrial_context()
        if industrial_context:
            action = {
                "finished": (
                    BugReportAction.INDUSTRIAL_ANALYSIS_FINISHED_WITH_WARNINGS
                    if warnings
                    else BugReportAction.INDUSTRIAL_ANALYSIS_FINISHED
                ),
                "failed": BugReportAction.INDUSTRIAL_ANALYSIS_FAILED,
                "cancelled": BugReportAction.INDUSTRIAL_ANALYSIS_CANCELLED,
            }[outcome]
        else:
            action = {
                "finished": (
                    BugReportAction.ANALYSIS_FINISHED_WITH_WARNINGS
                    if warnings
                    else BugReportAction.ANALYSIS_FINISHED
                ),
                "failed": BugReportAction.ANALYSIS_FAILED,
                "cancelled": BugReportAction.ANALYSIS_CANCELLED,
            }[outcome]
        _bugreport_recorder.record(action)

    def _tabular_scope_revision(self, *, include_filter: bool = True):
        """Snapshot native scope metadata; custom inputs retain the general path."""
        loaded = self.tabular_load_result
        if type(loaded) is not TabularAnalyticsLoadResult or type(loaded.sqlite_store) is not TabularSqliteStore:
            return None
        if type(self.tabular_column_filters) is not tuple and type(self.tabular_column_filters) is not list:
            return None
        store = loaded.sqlite_store
        if type(store.path) is not str or any(type(item) is not TabularColumnFilter for item in self.tabular_column_filters):
            return None
        token = _literal_cache_token((
            (store.path, store.table_name, store.columns, store.date_filter_columns,
             store.numeric_filter_columns, store.metric_columns, loaded.column_mapping),
            (self.tabular_filter_columns, self.tabular_filter_keys,
             tuple(vars(item) for item in self.tabular_column_filters), self.tabular_filter_expression),
        ))
        if token is None:
            return None
        if not include_filter:
            # Row-count memoization keeps its original filter-state equality;
            # population summaries use the full typed token and fresh counts.
            token = token[0]
        try:
            family = []
            for path in (Path(store.path), Path(f"{store.path}-wal")):
                stat = path.stat() if path.exists() else None
                family.append((stat.st_ino, stat.st_size, stat.st_mtime_ns) if stat else None)
        except OSError:
            return None
        return token, tuple(family)

    def _tabular_group_values(self):
        grouping = self.df_for_grouping
        revision = _native_grouping_revision(grouping)
        cached = getattr(self, "_tabular_group_values_cache", None)
        if revision is not None and cached is not None and cached[0] == revision:
            return cached[1]
        groups = grouping.get("GROUP", []) if hasattr(grouping, "get") else []
        values = tuple(sorted({str(value).strip() for value in groups if str(value).strip()}))
        self._tabular_group_values_cache = (revision, values) if revision is not None else None
        return values

    def _tabular_filtered_row_count(self) -> int:
        """Return the filtered row count, computed once per load result and filter state."""

        loaded = self.tabular_load_result
        if loaded is None:
            return 0
        typed = getattr(self, "_tabular_typed_filter", None)
        if typed is not None:
            return self._tabular_typed_count if typed.matches_loaded(loaded) else 0
        state = self._tabular_filter_state_key()
        revision = IndustrialAnalyticsDialog._tabular_scope_revision(self, include_filter=False)
        cached = self._tabular_row_count_cache
        if cached is not None and cached[0] is loaded and cached[1] == (state, revision):
            return cached[2]
        if (
            self.is_industrial_cache_presentation
            and not any(state)
            and loaded.sqlite_store is not None
            and loaded.row_count is not None
        ):
            # The industrial bridge counted this exact scope while it built the view; an
            # unfiltered state needs no second pass over the wide view.
            count = int(loaded.row_count)
        else:
            count = count_tabular_materialized_rows(
                loaded,
                filter_columns=self.tabular_filter_columns,
                selected_filter_keys=self.tabular_filter_keys,
                column_filters=self.tabular_column_filters,
                row_filter_expression=self.tabular_filter_expression,
            )
        self._tabular_row_count_cache = (loaded, (state, revision), count)
        return count

    def clear_tabular_filter(self) -> None:
        if not self.is_production_source and self.tabular_load_result is not None:
            if self._tabular_typed_filter is not None:
                self._clear_tabular_filter()
                self._sync_filter_summary()
                self._sync_ui_state()
            else:
                self._apply_tabular_filter((), "")

    def clear_tabular_groups(self) -> None:
        if self.is_production_source:
            return
        self._auto_group_selected_files = False
        self._clear_tabular_grouping()
        self._sync_ui_state()

    def _apply_grouping_rule(self, _index):
        if not self.is_production_source:
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
        input_files = self._selected_input_files()
        if len(input_files) > 1:
            includes_excel = any(Path(path).suffix.lower() in TABULAR_EXCEL_SUFFIXES for path in input_files)
            self.sheet_name_combo.addItem("First sheet of each workbook" if includes_excel else "CSV files", "")
            self.sheet_name_combo.setEnabled(False)
            self.sheet_name_combo.blockSignals(False)
            return
        path = Path(self.input_file) if self.input_file else None
        suffix = path.suffix.lower() if path is not None else ""
        if suffix in TABULAR_EXCEL_SUFFIXES:
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
        if self._tabular_source_busy():
            return
        action_started_at = monotonic()
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "Open CSV or Excel data",
            self.input_file or "",
            "CSV / Excel (*.csv *.xlsx *.xls);;CSV (*.csv);;Excel (*.xlsx *.xls);;All files (*)",
        )
        if not filenames or self._tabular_source_busy():
            return
        selected_files = tuple(str(Path(filename)) for filename in filenames)
        if any(Path(filename).suffix.lower() not in TABULAR_INPUT_SUFFIXES for filename in selected_files):
            QMessageBox.warning(
                self,
                self.windowTitle(),
                "Select only CSV (.csv) or Excel (.xlsx, .xls) files.",
            )
            return
        if any(not Path(filename).is_file() for filename in selected_files):
            QMessageBox.warning(self, self.windowTitle(), "One or more selected files are unavailable. Choose the files again.")
            return
        self._auto_group_selected_files = self._confirm_auto_group_selected_files(selected_files)
        self.input_files = selected_files
        self.input_file = selected_files[0]
        output_seed = self.input_file
        if len(selected_files) > 1:
            first_path = Path(self.input_file)
            output_seed = str(first_path.with_name(f"{first_path.stem}_combined.csv"))
        self.output_dashboard_file = _explicit_output_path(default_dashboard_path(output_seed))
        self.output_workbook_file = _explicit_output_path(default_workbook_path(output_seed))
        self._column_type_overrides = {}
        self._tabular_reload_notice = ""
        self.metric_candidates = ()
        self._discard_role_reload()
        self._set_tabular_load_result(None)
        self.metric_spec_limits = {}
        self._clear_tabular_filter()
        self._clear_tabular_grouping()
        self.metrics_list.clear()
        self._populate_tabular_sheet_options()
        self._reset_tabular_column_options()
        self._reset_group_options(())
        self.show_tabular_load_screen(action_started_at=action_started_at)

    def _confirm_auto_group_selected_files(self, selected_files: tuple[str, ...]) -> bool:
        if len(selected_files) <= 1:
            return False
        labels = tabular_file_group_labels(selected_files)
        if not labels:
            return False
        group_names = [group_name for _source_name, group_name in labels]
        preview = ", ".join(group_names[:5])
        if len(group_names) > 5:
            preview = f"{preview}, +{len(group_names) - 5} more"
        sheet_notice = (
            "This selection uses the first sheet of each workbook.\n\n"
            if any(Path(path).suffix.lower() in TABULAR_EXCEL_SUFFIXES for path in selected_files) else ""
        )
        result = QMessageBox.question(
            self,
            self.windowTitle(),
            (
                "Create groups from the selected file names?\n\n"
                f"{sheet_notice}"
                f"Groups: {preview}\n\n"
                "Each loaded row will be assigned to the group for its source file. "
                "No POPULATION group will be created unless you add or rename one later."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return result == QMessageBox.StandardButton.Yes

    def handle_load_metrics_clicked(self) -> None:
        if self._tabular_source_busy():
            return
        if self.is_production_source:
            self.load_metrics()
            return
        if self.is_preloaded_tabular_source:
            if self.tabular_load_result is None:
                QMessageBox.warning(self, self.windowTitle(), "Cached industrial rows are not loaded.")
                return
            if not self.metric_candidates:
                self.metric_candidates = tuple(
                    candidate.to_selection()
                    for candidate in self.tabular_load_result.metric_candidates
                )
                self._populate_metrics()
            self._sync_ui_state()
            return
        self.show_tabular_load_screen()

    def open_filters_dialog(self) -> None:
        if not self.is_production_source:
            self.open_tabular_filter_dialog()
            return
        dialog = IndustrialAnalyticsFilterDialog(self, filter_state=self.filter_state)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        _bugreport_recorder.record(BugReportAction.INDUSTRIAL_FILTER_APPLIED)
        self.filter_state = dialog.filter_state
        self.metric_candidates = ()
        self.metrics_list.clear()
        self._reset_group_options(())
        self._sync_filter_summary()
        self._sync_ui_state()

    def open_tabular_filter_dialog(self) -> None:
        if self._tabular_reload_busy():
            return
        if self.tabular_load_result is None:
            self.show_tabular_load_screen()
            return
        if (
            self.tabular_load_result is None
            or (
                self.tabular_load_result.sqlite_store is None
                and self.tabular_load_result.dataframe.empty
            )
        ):
            QMessageBox.warning(self, self.windowTitle(), "Load CSV/Excel metrics before filtering rows.")
            return
        if self._tabular_typed_filter is not None:
            self._open_typed_tabular_filter()
            return
        typed_available = (
            not self.is_preloaded_tabular_source and supports_tabular_typed_filter(self.tabular_load_result)
        )
        dialog = TabularAnalyticsFilterDialog(
            self,
            dataframe=self.tabular_load_result.dataframe,
            column_mapping=self.tabular_load_result.column_mapping,
            filter_columns=self.tabular_filter_columns,
            selected_filter_keys=self.tabular_filter_keys,
            column_filters=self.tabular_column_filters,
            filter_expression=self.tabular_filter_expression,
            sqlite_store=self.tabular_load_result.sqlite_store,
            **({"typed_filter_blocker": self._typed_filter_blocker()} if typed_available else {}),
        )
        action = dialog.exec()
        if action == OPEN_TYPED_FILTER:
            self._open_typed_tabular_filter()
        elif action == QDialog.DialogCode.Accepted:
            self._apply_tabular_filter(dialog.get_column_filters(), dialog.get_filter_expression())

    def _typed_filter_blocker(self) -> str:
        if self._tabular_source_busy():
            return "Wait for the current CSV/Excel operation before applying a typed expression."
        if any(self._tabular_filter_state_key()) or self.grouping_applied or self.group_field_combo.currentData():
            return TYPED_FILTER_COMBINATION
        return ""

    def _open_typed_tabular_filter(self) -> None:
        loaded = self.tabular_load_result
        if self.is_preloaded_tabular_source or not supports_tabular_typed_filter(loaded):
            return
        blocker = self._typed_filter_blocker()
        if blocker:
            QMessageBox.warning(self, self.windowTitle(), blocker)
            return
        current = self._tabular_typed_filter
        dialog = TabularTypedFilterDialog(self, loaded=loaded, expression=current.text if current else "")
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_scope is None:
            return
        if self.tabular_load_result is not loaded or self._typed_filter_blocker():
            QMessageBox.warning(self, self.windowTitle(), STALE_TYPED_FILTER)
            return
        self._tabular_typed_filter = dialog.result_scope
        self._tabular_typed_count = dialog.result_preview.matching_count
        _bugreport_recorder.record(BugReportAction.FILTER_APPLIED)
        self._sync_filter_summary()
        self._sync_ui_state()

    def _apply_tabular_filter(self, filters: tuple[TabularColumnFilter, ...], expression: str) -> None:
        if self._tabular_typed_filter is not None:
            return
        loaded = self.tabular_load_result
        previous_grouping = self.df_for_grouping
        try:
            old_state = canonical_filter_state(loaded, self.tabular_column_filters, self.tabular_filter_expression,
                                               self.tabular_filter_columns, self.tabular_filter_keys)
            if old_state == canonical_filter_state(loaded, filters, expression):
                return
            reconciled = _run_csv_scope_query(
                self, lambda: preview_filter_change(
                    loaded, previous_grouping, filters, expression,
                    cancel_check=QThread.currentThread().isInterruptionRequested,
                ),
                "Checking group memberships for the new filter",
            )
        except (KeyError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, self.windowTitle(), f"Could not apply row filter: {exc}")
            return
        if reconciled is None:
            return
        if self.tabular_load_result is not loaded or self.df_for_grouping is not previous_grouping:
            QMessageBox.warning(self, self.windowTitle(), "CSV source or groups changed. Apply the filter again.")
            return
        grouping, dropped_rows, dropped_groups, row_count, has_population = reconciled
        if dropped_rows and QMessageBox.question(
            self, "Change row filter?",
            f"{dropped_rows} row(s) in {dropped_groups} group(s) will lose membership. "
            "Compatible members and colours will be kept. Apply this filter?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.tabular_column_filters = filters
        self.tabular_filter_expression = expression
        self.tabular_filter_columns = ()
        self.tabular_filter_keys = ()
        _bugreport_recorder.record(
            BugReportAction.INDUSTRIAL_FILTER_APPLIED
            if self._is_bugreport_industrial_context()
            else BugReportAction.FILTER_APPLIED
        )
        if self.grouping_applied:
            self._grouping_snapshot_owner.invalidate()
            self.df_for_grouping = grouping
        state = self._tabular_filter_state_key()
        revision = self._tabular_scope_revision(include_filter=False)
        self._tabular_row_count_cache = (loaded, (state, revision), row_count)
        self._tabular_population_cache = ((_native_grouping_revision(grouping), self._tabular_scope_revision()), has_population)
        self._sync_filter_summary()
        self._sync_ui_state()

    def select_dashboard_file(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Dashboard (HTML)",
            self.output_dashboard_file,
            "HTML dashboard (*.html);;All files (*)",
            options=QFileDialog.Option(0) if self.is_production_source else QFileDialog.Option.DontConfirmOverwrite,
        )
        if filename:
            path = Path(filename)
            self.output_dashboard_file = str(path if path.suffix.lower() == ".html" else path.with_suffix(".html"))
            self._sync_ui_state()

    def select_workbook_file(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Output workbook (XLSX)",
            self.output_workbook_file,
            "Excel workbook (*.xlsx);;All files (*)",
            options=QFileDialog.Option(0) if self.is_production_source else QFileDialog.Option.DontConfirmOverwrite,
        )
        if filename:
            path = Path(filename)
            self.output_workbook_file = str(path if path.suffix.lower() == ".xlsx" else path.with_suffix(".xlsx"))
            self._sync_ui_state()

    def load_metrics(self) -> None:
        if self._tabular_source_busy():
            return
        action_started_at = monotonic()
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
                self.show_tabular_load_screen(action_started_at=action_started_at)
                return
        except Exception as exc:
            QMessageBox.warning(self, self.windowTitle(), f"Could not load metrics: {exc}")
            self._sync_ui_state()
            return

        self._populate_metrics()
        self._sync_ui_state()

    def _tabular_choices(self):
        return _TabularChoices(self._selected_metrics(), dict(self.metric_spec_limits),
                               self.group_field_combo.currentData() or "",
                               self.df_for_grouping if self.grouping_applied else None,
                               self.groupstats_checkbox.isChecked(), self._tabular_filter_state_key())

    def _reloaded_tabular_choices(self, previous, choices, loaded):
        fields = compatible_columns(previous, loaded)
        candidates = {metric.field_name for metric in loaded.metric_candidates}
        selected = tuple(replace(metric, field_name=fields[metric.field_name]) for metric in choices.selected
                         if fields.get(metric.field_name) in candidates)
        limits = {fields[name]: limit for name, limit in choices.limits.items() if fields.get(name) in candidates}
        group_field = fields.get(choices.group_field, "")
        if group_field not in _tabular_load_columns(loaded) or group_field in candidates:
            group_field = ""
        filters, lost_filters = compatible_filters(choices.filters, previous, loaded, fields)
        groups = (choices.grouping, ())
        if choices.grouping is not None and previous.source_snapshots != loaded.source_snapshots:
            groups = _run_csv_scope_query(
                self, lambda: reconcile_reload_grouping(previous, loaded, choices.grouping,
                    cancel_check=QThread.currentThread().isInterruptionRequested),
                "Sprawdzanie przypisań grup po odświeżeniu",
            )
        if groups is None:
            return None
        lost = self._tabular_reload_losses(choices, fields, selected, limits, group_field, groups[1], lost_filters)
        return _TabularChoices(selected, limits, group_field, groups[0], choices.groupstats, filters), lost

    @staticmethod
    def _tabular_reload_losses(choices, fields, selected, limits, group_field, lost_groups, lost_filters):
        labels = {metric.field_name: metric.display_label for metric in choices.selected}
        selected_names = {metric.field_name for metric in selected}
        lost = [("Niedostępne metryki", [label for name, label in labels.items()
                                         if fields.get(name) not in selected_names]),
                ("Limity wymagające ponownego ustawienia", [labels.get(name, name) for name in choices.limits
                                                          if fields.get(name) not in limits]),
                ("Niedostępna kolumna grupowania", [choices.group_field] if choices.group_field and not group_field else []),
                ("Niepotwierdzone przypisania w grupach", lost_groups),
                ("Filtry wymagające poprawy", lost_filters)]
        return tuple(f"{label}: {', '.join(names)}" for label, names in lost if names)

    def _accept_role_reload(self, lost):
        if not lost:
            return True
        return QMessageBox.question(
            self, "Zastosować zmianę roli kolumny?",
            "Zgodne ustawienia zostaną zachowane. Sprawdź zakres przed zastosowaniem.\n\n" + "\n".join(lost),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def _apply_tabular_load_result(self, loaded, *, populate_metrics: bool = True) -> None:
        pending = self._pending_role_reload
        previous = pending[0] if pending else self.tabular_load_result
        choices = None
        lost = ()
        if (
            isinstance(previous, TabularAnalyticsLoadResult) and same_tabular_source(previous, loaded)
            and self._tabular_worksheet_scope(previous) == self._tabular_worksheet_scope(loaded)
        ):
            original = pending[1] if pending else self._tabular_choices()
            try:
                result = self._reloaded_tabular_choices(previous, original, loaded)
            except (RuntimeError, ValueError) as exc:
                QMessageBox.warning(self, self.windowTitle(), f"Nie udało się sprawdzić ustawień po odświeżeniu. {exc}")
                result = None
            if result is None or (pending and not self._accept_role_reload(result[1])):
                cleanup_tabular_load_result(loaded)
                if pending:
                    self._pending_role_reload = None
                    self._replace_tabular_snapshot(previous, original, populate_metrics)
                if previous.source_snapshots != loaded.source_snapshots:
                    self._tabular_reload_notice = "Źródło zmieniło się. Odśwież dane przed analizą."
                    self._tabular_refresh_result = ""
                self._sync_ui_state()
                return
            choices, lost = result
        self._discard_role_reload()
        self._replace_tabular_snapshot(loaded, choices, populate_metrics)
        lost = (*lost, *self._column_type_messages(loaded))
        if choices is not None or lost:
            self._tabular_refresh_result = "\n".join(lost) if lost else "Odświeżono dane i zachowano ustawienia analizy."
            self._tabular_refresh_lost = bool(lost)
        if populate_metrics:
            self._sync_ui_state()

    @staticmethod
    def _tabular_worksheet_scope(loaded):
        return tuple(snapshot.sheet_name for snapshot in loaded.source_snapshots)

    def _replace_tabular_snapshot(self, loaded, choices, populate_metrics):
        self._tabular_reload_notice = ""
        self._set_tabular_load_result(loaded)
        self._column_type_overrides = dict(getattr(loaded, "column_types", {}))
        self.metric_candidates = tuple(candidate.to_selection() for candidate in loaded.metric_candidates)
        self.metric_spec_limits = choices.limits if choices else {}
        self._reset_group_options(
            tuple(
                (column.replace("_", " ").title(), column)
                for column in _tabular_load_columns(loaded)
                if column not in {metric.field_name for metric in self.metric_candidates}
            )
        )
        self.source_label.setText(self._tabular_source_label(loaded))
        self._populate_tabular_column_options(
            loaded.column_mapping,
            timestamp_column=loaded.timestamp_column,
            reference_column=loaded.reference_column,
        )
        if choices is None:
            self._apply_auto_file_grouping(loaded)
        else:
            self._apply_tabular_choices(choices)
        if populate_metrics:
            self._populate_metrics(None if choices is None else {metric.field_name for metric in choices.selected})

    def _apply_tabular_choices(self, choices):
        self.group_field_combo.setCurrentIndex(self.group_field_combo.findData(choices.group_field))
        (self.tabular_filter_columns, self.tabular_filter_keys,
         self.tabular_column_filters, self.tabular_filter_expression) = choices.filters
        self._grouping_snapshot_owner.invalidate()
        self.df_for_grouping = choices.grouping
        self.grouping_applied = choices.grouping is not None and not choices.grouping.empty
        self._set_groupstats_output_checked(choices.groupstats and self._tabular_groupstats_available())

    @staticmethod
    def _column_type_messages(loaded):
        messages = [note.message for note in getattr(loaded, "diagnostics", ())
                    if note.code == "tabular_number_override_invalid_values"]
        messages.extend(f"Brak kolumny z wybranym typem — {name} ({occurrence})"
                        for name, occurrence in getattr(loaded, "unavailable_column_types", ()))
        return messages

    def open_column_types(self):
        loaded = self.tabular_load_result
        if (self._tabular_source_busy() or self._tabular_typed_filter is not None
                or loaded is None or not loaded.source_column_identities):
            return
        dialog = ColumnTypesDialog(self, loaded, self._column_type_overrides)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.overrides != self._column_type_overrides:
            self._column_type_overrides = dialog.overrides
            self.show_tabular_load_screen()

    def _apply_auto_file_grouping(self, loaded) -> None:
        if self.is_production_source or not self._auto_group_selected_files:
            return
        source_files = tuple(getattr(loaded, "source_files", ()) or self._selected_input_files())
        if len(source_files) <= 1:
            return
        grouping_df = build_tabular_file_grouping_dataframe(
            getattr(loaded, "dataframe", None),
            source_files=source_files,
            source_snapshots=tuple(getattr(loaded, "source_snapshots", ()) or ()),
        )
        if grouping_df.empty:
            self._clear_tabular_grouping()
            return
        self.set_df_for_grouping(grouping_df)
        self.set_grouping_applied(True)

    def _tabular_source_label(self, loaded) -> str:
        if self._source_label_override:
            return self._source_label_override
        row_count = tabular_load_result_row_count(loaded)
        source_files = tuple(getattr(loaded, "source_files", ()) or self._selected_input_files())
        if len(source_files) > 1:
            return f"{self._tabular_source_status_source_text(source_files)}: {row_count} rows"
        if source_files:
            return f"{Path(source_files[0]).name}: {row_count} rows"
        if self.input_file:
            return f"{Path(self.input_file).name}: {row_count} rows"
        return f"CSV/Excel table: {row_count} rows"

    def open_metrics_dialog(self) -> None:
        if self._tabular_reload_busy():
            return
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
        if self._tabular_reload_busy():
            return
        if not self.metric_candidates:
            self.load_metrics()
        metrics = self._selected_metrics()
        if not metrics:
            QMessageBox.information(self, self.windowTitle(), "Select at least one metric before editing limits.")
            return
        dialog = MetricLimitsDialog(self, metrics=metrics, limits=self.metric_spec_limits)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.metric_spec_limits.update(dialog.limits())
        self._sync_ui_state()

    def open_grouping_dialog(self) -> None:
        if self.is_production_source or self._tabular_reload_busy() or self._tabular_typed_filter is not None:
            return
        if self.tabular_load_result is None:
            self.load_metrics()
        if (
            self.tabular_load_result is None
            or (
                self.tabular_load_result.sqlite_store is None
                and self.tabular_load_result.dataframe.empty
            )
        ):
            QMessageBox.warning(self, self.windowTitle(), "Load CSV/Excel metrics before editing groups.")
            return
        if self.tabular_load_result.sqlite_store is not None:
            dialog = self._create_tabular_grouping_dialog(
                self,
                dataframe=self.tabular_load_result.dataframe,
                column_mapping=self.tabular_load_result.column_mapping,
                identity_column=self._selected_tabular_column(self.reference_column_combo),
                datetime_column=self._selected_tabular_column(self.timestamp_column_combo),
                grouping_dataframe=self.df_for_grouping if self.grouping_applied else None,
                sqlite_store=self.tabular_load_result.sqlite_store,
                filter_columns=self.tabular_filter_columns,
                selected_filter_keys=self.tabular_filter_keys,
                column_filters=self.tabular_column_filters,
                filter_expression=self.tabular_filter_expression,
            )
            dialog.exec()
            self._sync_ui_state()
            return
        dialog = self._create_tabular_grouping_dialog(
            self,
            dataframe=self._filtered_tabular_dataframe(),
            column_mapping=self.tabular_load_result.column_mapping,
            identity_column=self._selected_tabular_column(self.reference_column_combo),
            datetime_column=self._selected_tabular_column(self.timestamp_column_combo),
            grouping_dataframe=self.df_for_grouping if self.grouping_applied else None,
        )
        dialog.exec()
        self._sync_ui_state()

    @staticmethod
    def _create_tabular_grouping_dialog(parent, **kwargs):
        try:
            signature = inspect.signature(TabularAnalyticsGroupingDialog)
            parameters = signature.parameters
            accepts_var_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            accepts_sqlite_scope = accepts_var_kwargs or "sqlite_store" in parameters
            if not accepts_var_kwargs:
                if (
                    not accepts_sqlite_scope
                    and "sqlite_store" in kwargs
                    and hasattr(parent, "_filtered_tabular_dataframe")
                ):
                    kwargs["dataframe"] = parent._filtered_tabular_dataframe()
                kwargs = {
                    key: value
                    for key, value in kwargs.items()
                    if key in parameters
                }
        except (TypeError, ValueError):
            pass
        return TabularAnalyticsGroupingDialog(parent, **kwargs)

    def set_df_for_grouping(self, df) -> None:
        self._grouping_snapshot_owner.invalidate()
        self.df_for_grouping = df
        self._sync_grouping_summary()

    def set_grouping_applied(self, applied: bool) -> None:
        self._grouping_snapshot_owner.invalidate()
        self.grouping_applied = bool(applied)
        if self.grouping_applied:
            _bugreport_recorder.record(
                BugReportAction.INDUSTRIAL_GROUPING_APPLIED
                if self._is_bugreport_industrial_context()
                else BugReportAction.GROUPING_APPLIED
            )
        if not self.grouping_applied:
            self.df_for_grouping = None
        self._sync_grouping_summary()
        self._sync_groupstats_output_for_grouping_change()

    def _set_groupstats_output_checked(self, checked: bool) -> None:
        self.groupstats_checkbox.blockSignals(True)
        self.groupstats_checkbox.setChecked(bool(checked))
        self.groupstats_checkbox.blockSignals(False)

    def _sync_groupstats_output_for_grouping_change(self) -> None:
        if self.is_production_source:
            return
        self._set_groupstats_output_checked(self._tabular_groupstats_available())

    def _sync_groupstats_output_for_reference_change(self) -> None:
        if self.is_production_source:
            return
        was_available = self.groupstats_checkbox.isEnabled()
        available = self._tabular_groupstats_available()
        if available and not was_available:
            self._set_groupstats_output_checked(True)
        elif not available:
            self._set_groupstats_output_checked(False)
        self._sync_ui_state()

    def _sync_grouping_summary(self) -> None:
        if self.is_production_source:
            return
        if not self.grouping_applied or self.df_for_grouping is None or self.df_for_grouping.empty:
            rule = self.group_field_combo.currentText() if self.group_field_combo.currentData() else ""
            self.grouping_summary_label.setText(f"Grupy według kolumny {rule}" if rule else "Groups: not applied")
            self._grouping_summary_names = ()
            set_status_variant(self.grouping_summary_label, "info" if rule else "neutral")
            return
        group_values = IndustrialAnalyticsDialog._tabular_group_values(self)
        self._grouping_summary_names = tuple(group_values[:3])
        has_population = self._tabular_grouping_has_population(set(group_values))
        custom_groups = [value for value in group_values if value != TABULAR_DEFAULT_GROUP]
        if custom_groups:
            suffix = f" + {TABULAR_DEFAULT_GROUP}" if has_population else ""
            self.grouping_summary_label.setText(f"Groups: {len(custom_groups)} custom{suffix}")
            set_status_variant(self.grouping_summary_label, "success")
        elif has_population:
            self.grouping_summary_label.setText(f"Groups: {TABULAR_DEFAULT_GROUP} only")
            set_status_variant(self.grouping_summary_label, "info")
        else:
            self.grouping_summary_label.setText("Groups: not applied")
            set_status_variant(self.grouping_summary_label, "neutral")

    def _tabular_grouping_has_population(self, group_values: set[str] | None = None) -> bool:
        group_values = set(group_values or ())
        if TABULAR_DEFAULT_GROUP in group_values:
            return True
        if self.tabular_load_result is not None and self.tabular_load_result.sqlite_store is None and self.df_for_grouping is not None:
            return self._tabular_filtered_row_count() > len(set(self.df_for_grouping["REPORT_ID"]))
        if (
            self.tabular_load_result is None
            or self.tabular_load_result.sqlite_store is None
            or self.df_for_grouping is None
            or self.df_for_grouping.empty
            or "REPORT_ID" not in self.df_for_grouping.columns
            or "GROUP" not in self.df_for_grouping.columns
        ):
            return False
        revision = _native_grouping_revision(self.df_for_grouping)
        scope = IndustrialAnalyticsDialog._tabular_scope_revision(self)
        key = (revision, scope) if revision is not None and scope is not None else None
        cached = getattr(self, "_tabular_population_cache", None)
        if key is not None and cached is not None and cached[0] == key:
            return cached[1]
        total_rows = count_tabular_materialized_rows(
            self.tabular_load_result,
            filter_columns=self.tabular_filter_columns,
            selected_filter_keys=self.tabular_filter_keys,
            column_filters=self.tabular_column_filters,
            row_filter_expression=self.tabular_filter_expression,
        )
        assignment_columns = self.df_for_grouping[["REPORT_ID", "GROUP"]]
        if hasattr(assignment_columns, "iter_rows"):
            assigned_rows = list(assignment_columns.iter_rows(as_dict=True))
        else:
            assigned_rows = assignment_columns.to_dict("records")
        valid_assigned_rows = []
        for row in assigned_rows:
            report_id = _coerce_int_or_none(row.get("REPORT_ID"))
            if report_id is None:
                continue
            group_label = str(row.get("GROUP") or TABULAR_DEFAULT_GROUP).strip() or TABULAR_DEFAULT_GROUP
            valid_assigned_rows.append((report_id, group_label))
        if not valid_assigned_rows:
            return total_rows > 0
        custom_assigned_ids = [
            report_id
            for report_id, group_label in valid_assigned_rows
            if group_label != TABULAR_DEFAULT_GROUP
        ]
        assigned_count = self.tabular_load_result.sqlite_store.count_source_row_numbers(
            custom_assigned_ids,
            filter_columns=self.tabular_filter_columns,
            selected_filter_keys=self.tabular_filter_keys,
            column_filters=self.tabular_column_filters,
            grouping_filter_expression=self.tabular_filter_expression,
            grouping_filter_aliases=self.tabular_load_result.column_mapping,
        )
        result = assigned_count < total_rows
        self._tabular_population_cache = (key, result) if key is not None else None
        return result

    def _filtered_tabular_dataframe(self):
        if self.tabular_load_result is None:
            return None
        return materialize_tabular_dataframe(
            self.tabular_load_result,
            filter_columns=self.tabular_filter_columns,
            selected_filter_keys=self.tabular_filter_keys,
            column_filters=self.tabular_column_filters,
            row_filter_expression=self.tabular_filter_expression,
        ).dataframe

    def _tabular_filter_summary(self) -> tuple[str, str]:
        if self.tabular_load_result is None:
            return "No row filter", "neutral"
        if self._tabular_typed_filter is not None:
            if not self._tabular_typed_filter.matches_loaded(self.tabular_load_result):
                return STALE_TYPED_FILTER, "warning"
            count = self._tabular_typed_count
            return f"Typed expression: {count} rows", "success" if count else "danger"
        if (
            not self.tabular_column_filters
            and not self.tabular_filter_expression
            and (not self.tabular_filter_columns or not self.tabular_filter_keys)
        ):
            return f"All rows ({tabular_load_result_row_count(self.tabular_load_result)})", "neutral"
        row_count = self._tabular_filtered_row_count()
        label_lookup = {
            normalized: original
            for original, normalized in self.tabular_load_result.column_mapping.items()
        }
        if self.tabular_column_filters:
            columns_text = ", ".join(
                self._tabular_column_filter_label(item, label_lookup)
                for item in self.tabular_column_filters
            )
        elif self.tabular_filter_expression:
            columns_text = "Advanced expression"
        else:
            columns_text = " | ".join(
                str(label_lookup.get(column, column)) for column in self.tabular_filter_columns
            )
        selection_count = (
            len(self.tabular_column_filters)
            if self.tabular_column_filters
            else 1 if self.tabular_filter_expression else len(self.tabular_filter_keys)
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
        self.group_field_combo.addItem("None" if self.is_production_source else "Brak reguły", "")
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

    def _tabular_manual_groups_can_form_groupstats(self) -> bool:
        return self._tabular_manual_group_count() >= 2

    def _tabular_manual_group_count(self) -> int:
        if self.is_production_source:
            return 0
        if not self.grouping_applied or self.df_for_grouping is None or self.df_for_grouping.empty:
            return 0
        if type(self.df_for_grouping) is RowTable:
            values = set(IndustrialAnalyticsDialog._tabular_group_values(self))
        else:
            groups = self.df_for_grouping.get("GROUP", [])
            values = {str(value).strip() for value in groups if str(value).strip()}
        if self._tabular_grouping_has_population(values):
            values.add(TABULAR_DEFAULT_GROUP)
        return len(values)

    def _tabular_groupstats_unavailable_reason(self) -> str | None:
        if self.is_production_source:
            return None
        if self._tabular_manual_groups_can_form_groupstats():
            return None
        if self.grouping_applied:
            return "Groupstats requires at least 2 non-empty manual groups."
        if self.group_field_combo.currentData():
            return None
        return "Groupstats requires manual CSV/Excel groups."

    def _selected_sheet_name(self) -> str | None:
        if self.is_production_source or len(self._selected_input_files()) != 1:
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
        if not self.is_production_source:
            return ReferenceCohortState()
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
        self.workbook_path_field.setEnabled(self.workbook_checkbox.isChecked())
        self.parameter_sheets_checkbox.setEnabled(self.workbook_checkbox.isChecked())
        self._sync_tabular_source_status()

        metrics = self._selected_metrics()
        source_ready = (
            bool(self.db_file)
            if self.is_production_source
            else bool(self.tabular_load_result)
            if self.is_preloaded_tabular_source
            else bool(self._selected_input_files())
        )
        candidate_count = len(self.metric_candidates)
        source_stable = not self._tabular_reload_busy()
        typed = self._tabular_typed_filter
        typed_stale = typed is not None and not typed.matches_loaded(self.tabular_load_result)
        clear_typed = "Clear the typed filter first."
        filtered_row_count = None
        if not self.is_production_source and self.tabular_load_result is not None:
            filtered_row_count = self._tabular_filtered_row_count()
        self.choose_metrics_button.setEnabled(bool(candidate_count) and source_stable)
        self.edit_limits_button.setEnabled(bool(candidate_count and metrics) and source_stable)
        rule_active = not self.is_production_source and bool(self.group_field_combo.currentData())
        self.edit_groups_button.setEnabled(
            bool(candidate_count and not self.is_production_source) and source_stable and not rule_active and typed is None
        )
        self.edit_groups_button.setToolTip(
            clear_typed if typed is not None else "Wybierz „Brak reguły”, aby ustawić grupy ręczne." if rule_active else ""
        )
        if not self.is_production_source:
            self.group_field_combo.setEnabled(source_stable and typed is None and not self.grouping_applied
                                              and self.group_field_combo.count() > 1)
            self.group_field_combo.setToolTip(
                clear_typed if typed is not None else "Usuń grupy ręczne, aby wybrać regułę." if self.grouping_applied
                else "Podziel analizę według wartości kolumny. Receptura zapisze wybraną regułę."
            )
        self.clear_filter_button.setEnabled(
            bool(
                not self.is_production_source
                and (
                    typed is not None
                    or self.tabular_column_filters
                    or self.tabular_filter_expression
                    or (self.tabular_filter_columns and self.tabular_filter_keys)
                )
            )
        )
        self.clear_groups_button.setEnabled(bool(not self.is_production_source and self.grouping_applied))
        self.load_metrics_button.setEnabled(source_ready)
        self.column_types_button.setVisible(not self.is_production_source and not self.is_preloaded_tabular_source)
        self.column_types_button.setEnabled(typed is None and bool(getattr(self.tabular_load_result, "source_column_identities", {}))
                                            and not self._tabular_source_busy())
        if not self.is_production_source:
            source_idle = not self._tabular_source_busy()
            self.browse_input_button.setEnabled(source_idle)
            self.load_metrics_button.setEnabled(source_ready and source_idle)
            self.timestamp_column_combo.setEnabled(source_idle and typed is None)
            self.reference_column_combo.setEnabled(source_idle and typed is None)
            self.sheet_name_combo.setEnabled(
                source_idle and typed is None and len(self._selected_input_files()) == 1
                and Path(self.input_file).suffix.lower() in TABULAR_EXCEL_SUFFIXES
            )
        if self.is_production_source:
            self.load_metrics_button.setText("Reload metrics" if candidate_count else "Load metrics")
        elif self.is_preloaded_tabular_source:
            self.load_metrics_button.setText(
                "Refresh cached CSV Summary metrics"
                if candidate_count
                else "Load cached CSV Summary metrics"
            )
        else:
            needs_reload = bool(candidate_count or self._tabular_reload_notice)
            self.load_metrics_button.setText(
                "Reload CSV/Excel data and refresh metrics"
                if needs_reload
                else "Load CSV/Excel data and detect metrics"
            )
        if not self.is_production_source:
            apply_dialog_mnemonics(self, "csv_summary")
        refresh_button_command_hints(self, "csv_summary")
        self._sync_filter_visibility()
        groupstats_unavailable_reason = self._tabular_groupstats_unavailable_reason()
        groupstats_available = groupstats_unavailable_reason is None
        self.groupstats_checkbox.setEnabled(groupstats_available)
        self.groupstats_checkbox.setToolTip(groupstats_unavailable_reason or "")
        self.groupstats_reason_label.setVisible(bool(groupstats_unavailable_reason))
        self.groupstats_reason_label.setText(groupstats_unavailable_reason or "")
        set_status_variant(self.groupstats_reason_label, "warning")
        if not groupstats_available:
            self._set_groupstats_output_checked(False)
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
        self.filters_button.setEnabled((self.is_production_source or self.tabular_load_result is not None) and source_stable)
        ready = bool(
            source_stable
            and source_ready
            and not self._tabular_reload_notice
            and not typed_stale
            and metrics
            and self.output_dashboard_file
            and charts_ready
            and workbook_ready
            and tabular_rows_ready
        )
        self.start_button.setEnabled(ready)
        if source_stable and self._tabular_refresh_result and not typed_stale:
            self.readiness_label.setText(self._tabular_refresh_result)
            set_status_variant(self.readiness_label, "warning" if self._tabular_refresh_lost else "info")
        elif ready:
            self.readiness_label.setText(
                f"Ready: {len(metrics)} metric(s), dashboard"
                + (", workbook." if self.workbook_checkbox.isChecked() else ".")
            )
            set_status_variant(self.readiness_label, "success")
        elif not source_stable:
            self.readiness_label.setText("Loading CSV/Excel data. Wait before creating analytics.")
            set_status_variant(self.readiness_label, "info")
        elif not source_ready:
            self.readiness_label.setText("Select a source before creating analytics.")
            set_status_variant(self.readiness_label, "warning")
        elif self._tabular_reload_notice:
            self.readiness_label.setText(self._tabular_reload_notice)
            set_status_variant(self.readiness_label, "warning")
        elif typed_stale:
            self.readiness_label.setText(STALE_TYPED_FILTER)
            set_status_variant(self.readiness_label, "warning")
        elif not metrics:
            self.readiness_label.setText("Load metrics and select at least one parameter.")
            set_status_variant(self.readiness_label, "warning")
        elif not tabular_rows_ready:
            source_label = "cached industrial rows" if self.is_preloaded_tabular_source else "CSV/Excel rows"
            self.readiness_label.setText(f"Row filter matches no {source_label}.")
            set_status_variant(self.readiness_label, "danger")
        elif not charts_ready:
            self.readiness_label.setText("Select at least one chart or groupstats output.")
            set_status_variant(self.readiness_label, "warning")
        else:
            self.readiness_label.setText("Select output paths before creating analytics.")
            set_status_variant(self.readiness_label, "warning")
        can_save_recipe = ready and self.analytics_thread is None and typed is None
        self.save_recipe_button.setEnabled(can_save_recipe)
        self.save_recipe_button.setToolTip(
            clear_typed if typed is not None else (
                "Save these analysis settings for reuse." if can_save_recipe else self.readiness_label.text()
            )
        )
        self.start_button.setToolTip(self.readiness_label.text() + " Ctrl+S generates; Ctrl+Shift+S stops.")
        if self.analytics_thread is None:
            set_output_summary(self.request_summary_label, output_summary(
                source=self.db_file if self.is_production_source else self.input_file,
                scope=(self.filter_state.summary() if self.is_production_source else
                       "Typed row filter" if typed is not None else tabular_scope(
                    self.tabular_filter_expression, self.tabular_column_filters,
                    self.tabular_filter_columns, self.tabular_filter_keys)),
                grouping=self.grouping_summary_label.text() + " " + ", ".join(getattr(self, "_grouping_summary_names", ())),
                dashboard=self.output_dashboard_file,
                workbook=self.output_workbook_file if self.workbook_checkbox.isChecked() else "",
            ))

    def handle_start_button(self) -> None:
        action_started_at = monotonic()
        if not self.metric_candidates:
            self.load_metrics()
        self._sync_ui_state()
        if not self.start_button.isEnabled():
            return
        self._analytics_action_started_at = action_started_at
        try:
            self.show_loading_screen()
        finally:
            self._analytics_action_started_at = None

    def show_tabular_load_screen(self, *, action_started_at=None) -> None:
        if self._tabular_source_busy():
            return
        action_started_at = monotonic() if action_started_at is None else action_started_at
        if self.is_production_source:
            self.load_metrics()
            return
        input_files = self._selected_input_files()
        if self.is_preloaded_tabular_source:
            if self.tabular_load_result is None:
                QMessageBox.warning(self, self.windowTitle(), "Cached industrial rows are not loaded.")
            else:
                self._sync_ui_state()
            return
        if not input_files:
            QMessageBox.warning(self, self.windowTitle(), "Select a CSV or Excel file first.")
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
                action_started_at=action_started_at,
            )
        )
        if self.source_kind == SOURCE_TABULAR_FILE and not self.is_industrial_cache_presentation:
            self.loading_dialog.setWindowModality(Qt.WindowModality.NonModal)
        self.loading_bar.setRange(0, 0)
        self.tabular_load_thread = TabularAnalyticsLoadThread(
            input_file=self.input_file,
            input_files=input_files,
            sheet_name=self._selected_sheet_name(),
            timestamp_column=self._selected_tabular_column(self.timestamp_column_combo),
            reference_column=self._selected_tabular_column(self.reference_column_combo),
            column_types=self._column_type_overrides,
        )
        # Terminal handlers can enter a nested event loop. Retain each worker's
        # own widgets so late cleanup cannot dispose a newer analytics window.
        self._worker_progress[self.tabular_load_thread] = (
            self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif
        )
        self.tabular_load_thread.result_ready.connect(self.on_tabular_load_finished)
        self.tabular_load_thread.error_occurred.connect(self.on_tabular_load_error)
        self.tabular_load_thread.cancelled.connect(self.on_tabular_load_cancelled)
        self.tabular_load_thread.update_label.connect(self.loading_label.setText)
        self.tabular_load_thread.finished.connect(self.on_tabular_load_thread_stopped)
        self._sync_ui_state()
        _bugreport_recorder.record(BugReportAction.CSV_LOAD_STARTED)
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
        # A nested reconciliation loop may retire this slot's originating
        # thread. Keep the progress owner without asking Qt for sender again.
        owner = self.sender()
        self._applying_tabular_load = owner
        try:
            self._apply_tabular_load_result(loaded)
            _bugreport_recorder.record(BugReportAction.CSV_LOAD_FINISHED)
        finally:
            self._applying_tabular_load = None
            if owner is None:
                self._close_worker_progress()
            else:
                self._dispose_worker_progress(owner)

    def on_tabular_load_error(self, message: str) -> None:
        _bugreport_recorder.record(BugReportAction.CSV_LOAD_FAILED)
        self._close_worker_progress()
        self._tabular_reload_notice = "Odświeżenie nie powiodło się. Wczytaj źródło ponownie przed analizą."
        self._tabular_refresh_result = ""
        QMessageBox.warning(self, self.windowTitle(), f"Could not load metrics: {message}")
        self._sync_ui_state()

    def on_tabular_load_cancelled(self, message: str) -> None:
        _bugreport_recorder.record(BugReportAction.CSV_LOAD_CANCELLED)
        self._close_worker_progress()
        QMessageBox.information(self, self.windowTitle(), message or "CSV/Excel loading was canceled.")

    def on_tabular_load_thread_stopped(self) -> None:
        thread = self.sender()
        if not isinstance(thread, TabularAnalyticsLoadThread):
            thread = self.tabular_load_thread
        if thread is not None:
            thread.wait()
            thread.deleteLater()
            if thread is not self._applying_tabular_load:
                self._dispose_worker_progress(thread)
        if self.tabular_load_thread is thread:
            self.tabular_load_thread = None
        self._sync_ui_state()

    def _close_worker_progress(self) -> None:
        thread = self.sender()
        progress = self._worker_progress.get(thread)
        if progress is not None:
            self._dispose_worker_progress(thread)
        elif thread is None and hasattr(self, "loading_dialog"):
            # Direct handler calls have no signal sender.
            dismiss_worker_progress_dialog(self.loading_dialog)

    def _dispose_worker_progress(self, thread) -> None:
        progress = self._worker_progress.pop(thread, None)
        if progress is None:
            return
        dialog, _label, _bar, movie = progress
        dismiss_worker_progress_dialog(dialog)
        for name, widget in zip(
            ("loading_dialog", "loading_label", "loading_bar", "loading_gif"), progress
        ):
            if getattr(self, name, None) is widget:
                delattr(self, name)

    def _save_as_recipe(self):
        if self._tabular_typed_filter is not None:
            return
        from metroliza.ui.recipe_workspace import open_capture_editor
        try:
            request = self._build_analytics_request(require_runnable=True)
            module = "industrial" if self.is_production_source else "tabular"
            open_capture_editor(self, module, request)
        except ValueError:
            self.readiness_label.setText("Review the data source, metrics and output paths before saving the recipe.")
            set_status_variant(self.readiness_label, "warning")
            if not self._selected_metrics():
                target = self.choose_metrics_button if self.metric_candidates else self.load_metrics_button
            else:
                target = self.dashboard_button
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _build_analytics_request(self, *, require_runnable: bool = False) -> IndustrialAnalyticsRequest:
        snapshot = self._pending_grouping_snapshot
        if snapshot is not None and snapshot.source_id != id(
            self.df_for_grouping if self.grouping_applied else None
        ):
            raise ValueError("Grouping snapshot is stale or does not match its source.")
        pending = self._pending_analytics_request
        if pending is not None:
            if (self.db_file != pending.db_file or self.input_file != pending.input_file
                    or (not self.is_production_source and self.tabular_load_result is not pending.tabular_load_result)):
                raise ValueError("Source changed while preparing analytics. Review the scope and generate again.")
            return pending
        return validate_industrial_analytics_request(
            IndustrialAnalyticsRequest(
                source_kind=self.source_kind,
                db_file=self.db_file,
                input_file=self.input_file,
                output_dashboard_file=self.output_dashboard_file,
                dashboard_detail_mode="full",
                output_workbook_file=(
                    self.output_workbook_file if self.workbook_checkbox.isChecked() else ""
                ),
                metric_selection=self._selected_metrics(),
                filter_state=self.filter_state,
                aggregation_state=self._aggregation_state(),
                cohort_state=self._cohort_state(),
                chart_selection=self._chart_selection(),
                separate_parameter_sheets=(
                    self.workbook_checkbox.isChecked()
                    and self.parameter_sheets_checkbox.isChecked()
                ),
                sheet_name=self._selected_sheet_name(),
                timestamp_column=self._selected_tabular_column(self.timestamp_column_combo),
                reference_column=self._selected_tabular_column(self.reference_column_combo),
                tabular_load_result=self.tabular_load_result if not self.is_production_source else None,
                tabular_filter_columns=self.tabular_filter_columns,
                tabular_filter_keys=self.tabular_filter_keys,
                tabular_column_filters=self.tabular_column_filters,
                tabular_filter_expression=self.tabular_filter_expression,
                tabular_typed_filter=self._tabular_typed_filter,
                grouping_df=(snapshot.assignments if snapshot is not None
                             else self.df_for_grouping if self.grouping_applied else None),
                _grouping_snapshot=snapshot,
                _grouping_owner=self._grouping_snapshot_owner,
                dashboard_visual_settings=self.dashboard_visual_settings,
                dashboard_interactivity_options=self.dashboard_interactivity_options,
            ),
            require_runnable=require_runnable,
        )

    def create_analytics_thread(self) -> IndustrialAnalyticsThread:
        request = self._build_analytics_request()
        snapshot = request._grouping_snapshot
        publication = self._pending_output_publication
        return IndustrialAnalyticsThread(
            source_kind=request.source_kind,
            db_file=request.db_file,
            input_file=request.input_file,
            output_dashboard_file=str(publication.outputs.dashboard) if publication else request.output_dashboard_file,
            output_workbook_file=(str(publication.outputs.workbook or "") if publication else request.output_workbook_file),
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
            tabular_filter_expression=request.tabular_filter_expression,
            **({"tabular_typed_filter": request.tabular_typed_filter}
               if request.tabular_typed_filter is not None else {}),
            dashboard_detail_mode=request.dashboard_detail_mode,
            grouping_df=(request.grouping_df if snapshot is not None
                         else self.df_for_grouping if self.grouping_applied else None),
            _grouping_snapshot=snapshot,
            **({"grouping_default_group_label": request.grouping_default_group_label}
               if snapshot is not None else {}),
            dashboard_visual_settings=request.dashboard_visual_settings,
            dashboard_interactivity_options=request.dashboard_interactivity_options,
            output_publication=publication,
        )

    def _tabular_publication_scope(self) -> tuple:
        return (self._selected_input_files(), self.output_dashboard_file,
                self.output_workbook_file if self.workbook_checkbox.isChecked() else "",
                self._tabular_filter_state_key(), self._tabular_typed_filter, self._grouping_snapshot_owner.revision)

    def _tabular_publication_sources(self, request) -> tuple[Path, ...]:
        loaded = request.tabular_load_result
        sources = (*self._selected_input_files(), request.db_file, request.input_file)
        if loaded is not None:
            sources += (loaded.source_file, *loaded.source_files)
            if loaded.sqlite_store is not None:
                sources += (loaded.sqlite_store.path,)
        return tuple(Path(value).expanduser().absolute() for value in dict.fromkeys(sources) if value)

    def _confirm_tabular_publication(self, request) -> TabularOutputPublication | None:
        outputs = TabularOutputFiles.from_paths(request.output_dashboard_file, request.output_workbook_file)
        sources = self._tabular_publication_sources(request)
        outputs.validate_sources(sources)
        conflicts = outputs.conflicts()
        if not conflicts:
            return TabularOutputPublication(outputs, sources)
        consents = outputs.replacement_consents()
        if consents:
            conflicts = tuple(dict.fromkeys((*(consent.path for consent in consents), *conflicts)))
        copy = outputs.free_copy(sources)
        scope = self._tabular_publication_scope()
        self._choosing_output = True
        try:
            choice = self._choose_tabular_output(conflicts, copy, can_replace=consents is not None)
        finally:
            self._choosing_output = False
        if choice == "cancel":
            return None
        if scope != self._tabular_publication_scope() or self.tabular_load_result is not request.tabular_load_result:
            raise ValueError("Settings changed while choosing outputs. Review the scope and generate again.")
        if choice == "replace":
            return TabularOutputPublication(outputs, sources, replace_outputs=consents)
        return TabularOutputPublication(copy, sources, copy_from=outputs)

    def _choose_tabular_output(self, conflicts, copy, *, can_replace: bool) -> str:
        prompt = QMessageBox(self)
        prompt.setWindowTitle("Wynik analizy już istnieje")
        prompt.setTextFormat(Qt.TextFormat.PlainText)
        existing = "\n".join(str(path) for path in conflicts[:10])
        if len(conflicts) > 10:
            existing += f"\n… i jeszcze {len(conflicts) - 10}"
        copied = "\n".join(str(path) for path in copy.paths)
        prompt.setText(f"Istniejące wyniki\n{existing}\n\nZapisz kopię jako\n{copied}")
        prompt.setInformativeText(
            "Opcja „Zastąp” dotyczy tylko tego uruchomienia."
            if can_replace else "Zastąpienie wymaga zwykłego pliku. Wybierz kopię lub anuluj."
        )
        copy_button = prompt.addButton("Zapisz kopię", QMessageBox.ButtonRole.AcceptRole)
        replace_button = prompt.addButton("Zastąp", QMessageBox.ButtonRole.DestructiveRole)
        replace_button.setEnabled(can_replace)
        cancel_button = prompt.addButton("Anuluj", QMessageBox.ButtonRole.RejectRole)
        prompt.setDefaultButton(copy_button)
        prompt.setEscapeButton(cancel_button)
        prompt.exec()
        if prompt.clickedButton() is copy_button:
            return "copy"
        if prompt.clickedButton() is replace_button and can_replace:
            return "replace"
        return "cancel"

    def show_loading_screen(self) -> None:
        action_started_at = getattr(self, "_analytics_action_started_at", None)
        action_started_at = monotonic() if action_started_at is None else action_started_at
        if self._choosing_output or self.tabular_load_thread is not None or self.analytics_thread is not None:
            return
        try:
            request = self._build_analytics_request(require_runnable=True)
            publication = None if self.is_production_source else self._confirm_tabular_publication(request)
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        if not self.is_production_source and publication is None:
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
                action_started_at=action_started_at,
            )
        )
        if self.source_kind == SOURCE_TABULAR_FILE and not self.is_industrial_cache_presentation:
            self.loading_dialog.setWindowModality(Qt.WindowModality.NonModal)
        self.loading_bar.setRange(0, 0)
        self._pending_grouping_snapshot = request._grouping_snapshot
        self._pending_analytics_request = request
        self._pending_output_publication = publication
        try:
            self.analytics_thread = self.create_analytics_thread()
        except ValueError as exc:
            self._close_worker_progress()
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        finally:
            self._pending_grouping_snapshot = None
            self._pending_analytics_request = None
            self._pending_output_publication = None
        set_output_summary(self.request_summary_label, analytics_summary(getattr(self.analytics_thread, "request", request)))
        self.last_result_row.clear()
        self._worker_progress[self.analytics_thread] = (
            self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif
        )
        self.analytics_thread.result_ready.connect(self.on_analytics_finished)
        self.analytics_thread.error_occurred.connect(self.on_analytics_error)
        self.analytics_thread.cancelled.connect(self.on_analytics_cancelled)
        self.analytics_thread.update_label.connect(self.loading_label.setText)
        self.analytics_thread.finished.connect(self.on_analytics_thread_stopped)
        if not self.is_production_source:
            self._sync_ui_state()
        self.start_button.setEnabled(False)
        self.readiness_label.setText("Generating analytics. Ctrl+Shift+S requests stop.")
        try:
            industrial_context = self._is_bugreport_industrial_context()
            _bugreport_recorder.record(
                BugReportAction.OPTION_INDUSTRIAL_ANALYTICS_WORKBOOK
                if industrial_context
                else BugReportAction.OPTION_WORKBOOK,
                enabled=bool(request.output_workbook_file),
            )
            _bugreport_recorder.record(
                BugReportAction.OPTION_INDUSTRIAL_ANALYTICS_DASHBOARD
                if industrial_context
                else BugReportAction.OPTION_HTML,
                enabled=bool(request.output_dashboard_file),
            )
            _bugreport_recorder.record(
                BugReportAction.OPTION_INDUSTRIAL_ANALYTICS_GROUPING
                if industrial_context
                else BugReportAction.OPTION_GROUPING,
                enabled=bool(self.grouping_applied),
            )
            _bugreport_recorder.record(
                BugReportAction.OPTION_INDUSTRIAL_ANALYTICS_CHARTS
                if industrial_context
                else BugReportAction.OPTION_CHARTS,
                enabled=bool(request.chart_selection.has_any),
            )
            worker_request = getattr(self.analytics_thread, "request", None)
            if (
                not industrial_context
                and type(worker_request) is IndustrialAnalyticsRequest
            ):
                self._record_safe_request_checks(request, worker_request)
            _bugreport_recorder.record(
                BugReportAction.INDUSTRIAL_ANALYSIS_STARTED
                if industrial_context
                else BugReportAction.ANALYSIS_STARTED
            )
        except Exception:
            # Diagnostic observation must not block the actual operation.
            pass
        self.analytics_thread._bugreport_option_token = self._record_safe_request_options(request)


        self._capture_analysis_source(request)
        self.analytics_thread.start()
        self.loading_dialog.show()

    def _record_safe_request_options(self, request: IndustrialAnalyticsRequest):
        """Retain only closed option flags from the accepted execution request."""
        try:
            charts = request.chart_selection
            aggregation = request.aggregation_state
            industrial_cache = self.is_industrial_cache_presentation
            production_cache = request.source_kind == SOURCE_PRODUCTION_CACHE
            tabular_file = request.source_kind == SOURCE_TABULAR_FILE and not industrial_cache
            # Inspect only the existing source descriptor, without opening the
            # input. Neither the path nor its suffix enters diagnostic storage.
            loaded = request.tabular_load_result
            sources = getattr(loaded, "source_files", ()) or (getattr(loaded, "source_file", "") or request.input_file,)
            suffixes = {Path(source).suffix.lower() for source in sources} if tabular_file else set()
            return _bugreport_recorder.record_option_snapshot(
                OptionSnapshotKind.INDUSTRIAL_ANALYSIS
                if production_cache or industrial_cache
                else OptionSnapshotKind.CSV_ANALYSIS,
                {
                    "workbook": bool(request.output_workbook_file),
                    "html": bool(request.output_dashboard_file),
                    "separate_parameter_sheets": bool(request.separate_parameter_sheets),
                    "chart_time_series": bool(charts.time_series),
                    "chart_histogram": bool(charts.histogram),
                    "chart_violin": bool(charts.violin),
                    "chart_box": bool(charts.box),
                    "chart_groupstats": bool(charts.groupstats),
                    "filters_applied": bool(
                        request.filter_state.is_applied
                        or request.tabular_typed_filter is not None
                        or request.tabular_filter_expression
                        or request.tabular_column_filters
                        or (request.tabular_filter_columns and request.tabular_filter_keys)
                    ),
                    "grouping_applied": request.grouping_df is not None,
                    "aggregation_configured": bool(
                        aggregation.is_aggregated
                        or aggregation.aggregation_methods != ("mean",)
                    ),
                    "cohort_configured": bool(request.cohort_state.is_applied),
                    "source_production_cache": production_cache,
                    "source_industrial_cache": industrial_cache,
                    "source_csv": ".csv" in suffixes,
                    "source_xlsx": ".xlsx" in suffixes,
                },
            )
        except Exception:
            # Option evidence must not affect worker startup or its outcome.
            return None

    def _record_safe_option_outcome(self, outcome: ContextOperationOutcome) -> None:
        """Only the actual signal sender may complete its own option snapshot."""
        try:
            thread = self.sender()
            if isinstance(thread, IndustrialAnalyticsThread):
                token = getattr(thread, "_bugreport_option_token", None)
                if token is not None:
                    _bugreport_recorder.record_option_outcome(token, outcome)
        except Exception:
            return

    def _record_safe_request_checks(self, request, worker_request) -> None:
        """Compare bounded execution parameters locally; record booleans only."""
        try:
            _bugreport_recorder.record(
                BugReportAction.CHECK_WORKBOOK_REQUEST_MATCH,
                enabled=(self.workbook_checkbox.isChecked() == bool(request.output_workbook_file)
                         == bool(worker_request.output_workbook_file)),
            )
            _bugreport_recorder.record(
                BugReportAction.CHECK_CHART_REQUEST_MATCH,
                enabled=request.chart_selection == worker_request.chart_selection,
            )
            # Large user filters/groupings are intentionally not walked on the GUI thread.
            a, b = request.tabular_column_filters, worker_request.tabular_column_filters
            x, y = request.tabular_filter_expression, worker_request.tabular_filter_expression
            if (type(a) is tuple and type(b) is tuple and len(a) <= 16 and len(b) <= 16
                    and type(x) is str and type(y) is str and len(x) <= 2048 and len(y) <= 2048
                    and all(len(f.selected_values) <= 64 for f in (*a, *b))):
                _bugreport_recorder.record(BugReportAction.CHECK_FILTER_REQUEST_MATCH,
                    enabled=a == b and x == y and request.tabular_typed_filter is worker_request.tabular_typed_filter,
                )
            a, b = request.grouping_df, worker_request.grouping_df
            if ((a is None or type(a) is tuple and len(a) <= 128)
                    and (b is None or type(b) is tuple and len(b) <= 128)):
                _bugreport_recorder.record(BugReportAction.CHECK_GROUPING_REQUEST_MATCH, enabled=a == b)
        except Exception:
            # Missing or uncomparable checks remain unknown, never a success.
            return

    def _stop_active_analytics(self) -> None:
        if self.analytics_thread is not None:
            self.cancel_analytics()

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
        self._record_safe_option_outcome(
            ContextOperationOutcome.COMPLETED_WITH_WARNINGS
            if _analytics_has_warnings(result)
            else ContextOperationOutcome.COMPLETED
        )
        self._record_safe_result_paths(result)
        self._record_bugreport_analytics_outcome(
            "finished",
            warnings=_analytics_has_warnings(result),
        )
        if (
            not self._is_bugreport_industrial_context()
            and type(result.html_dashboard_chart_count) is int
        ):
            _bugreport_recorder.record(
                BugReportAction.CHECK_CHARTS_PRESENT, enabled=result.html_dashboard_chart_count > 0,
            )
        self._close_worker_progress()
        level, title, message, reveal_path = build_analytics_completion_message(result)
        paths = existing_result_files((result.workbook_path, result.html_dashboard_path))
        self.last_result_row.set_result(
            "completed with warnings" if _analytics_has_warnings(result) else "completed", paths,
            counts=f"Rows analyzed: {result.row_count} · Metrics: {getattr(result, 'metric_count', 0)} · Charts: {result.html_dashboard_chart_count}",
        )
        if paths:
            assets = getattr(result, "html_dashboard_assets_path", "")
            self._emit_analysis_completion(paths, assets)
        try:
            from metroliza.ui.export_dialog import show_export_result_message

            show_export_result_message(self, level, title, message, excel_file=reveal_path, artifacts=paths)
        except Exception:
            QMessageBox.information(self, title, message)

    def _record_safe_result_paths(self, result) -> None:
        """Compare request/result targets locally; this does not validate file content."""
        try:
            thread = self.sender()
            request = getattr(thread, "request", None)
            if not isinstance(thread, IndustrialAnalyticsThread) or type(request) is not IndustrialAnalyticsRequest:
                return
            for action, expected, actual in (
                (BugReportAction.CHECK_ANALYTICS_WORKBOOK_RESULT_MATCH,
                 request.output_workbook_file, result.workbook_path),
                (BugReportAction.CHECK_ANALYTICS_DASHBOARD_RESULT_MATCH,
                 request.output_dashboard_file, result.html_dashboard_path),
            ):
                matches = Path(expected) == Path(actual) if expected and actual else not expected and not actual
                _bugreport_recorder.record(action, enabled=bool(matches))
        except Exception:
            # Without an exact worker request, no match claim is recorded.
            return


    def _analysis_source(self, request):
        loaded = request.tabular_load_result
        source_files = getattr(loaded, "source_files", ()) or ((request.input_file,) if request.input_file else ())
        industrial = request.source_kind == SOURCE_PRODUCTION_CACHE or self.is_industrial_cache_presentation
        source = request.db_file if industrial else source_files[0] if len(source_files) == 1 else None
        return source, industrial, len(source_files)

    def _capture_analysis_source(self, request):
        from metroliza.app.analysis_history import capture_source_stamp
        source, _, _ = self._analysis_source(request)
        self._analysis_source_stamp = None if self.is_preloaded_tabular_source else capture_source_stamp(source)

    def _emit_analysis_completion(self, paths, assets):
        request = getattr(self.analytics_thread, "request", None)
        if request is None:
            return
        source, industrial, source_count = self._analysis_source(request)
        settings = {"sheet": request.sheet_name, "metrics": [metric.field_name for metric in request.metric_selection],
                    "groups": list(request.aggregation_state.group_fields), "source_count": source_count}
        html_published = any(path.suffix.lower() in {".html", ".htm"} for path in paths)
        self.analysis_completed.emit({"kind": "industrial" if industrial else "csv",
                                      "artifacts": [str(path) for path in paths], "source": source or None,
                                      "source_stamp": self._analysis_source_stamp,
                                      "settings": settings, "assets": [str(assets)] if assets and html_published else []})

    def on_analytics_error(self, message: str) -> None:
        self._record_safe_option_outcome(ContextOperationOutcome.FAILED)
        self._record_bugreport_analytics_outcome("failed")
        self._close_worker_progress()
        self.last_result_row.set_result("failed")
        QMessageBox.warning(self, self.windowTitle(), f"Could not create analytics: {message}")

    def on_analytics_cancelled(self, message: str) -> None:
        self._record_safe_option_outcome(ContextOperationOutcome.CANCELLED)
        self._record_bugreport_analytics_outcome("cancelled")
        self._close_worker_progress()
        self.last_result_row.set_result("cancelled")
        QMessageBox.information(self, self.windowTitle(), message or "Analytics generation was canceled.")

    def on_analytics_thread_stopped(self) -> None:
        thread = self.sender()
        if not isinstance(thread, IndustrialAnalyticsThread):
            thread = self.analytics_thread
        if thread is not None:
            thread.wait()
            thread.deleteLater()
            self._dispose_worker_progress(thread)
        if self.analytics_thread is thread:
            self.analytics_thread = None
        self._sync_ui_state()

    def reject(self) -> None:
        if getattr(self, "_scope_query_running", False):
            return
        thread = self.tabular_load_thread
        if thread is not None and thread.isRunning():
            QMessageBox.information(self, self.windowTitle(), "Wait for CSV/Excel loading to finish.")
            return
        thread = self.analytics_thread
        if thread is not None and thread.isRunning():
            QMessageBox.information(self, self.windowTitle(), "Wait for analytics generation to finish.")
            return
        self._discard_role_reload()
        self._set_tabular_load_result(None)
        self._grouping_snapshot_owner.invalidate()
        super().reject()

    def closeEvent(self, event) -> None:
        if getattr(self, "_scope_query_running", False):
            event.ignore()
            return
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
        self._discard_role_reload()
        self._set_tabular_load_result(None)
        self._grouping_snapshot_owner.invalidate()
        super().closeEvent(event)


def _literal_cache_token(value):
    """Copy only exact native values without hashing or comparing custom keys."""
    if type(value) is float:
        return (float, float.hex(value))
    if any(type(value) is native for native in (str, int, bool, type(None))):
        return (type(value), value)
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            return None
        value = tuple(value.items())
    if type(value) is not tuple and type(value) is not list:
        return None
    parts = tuple(_literal_cache_token(item) for item in value)
    return None if any(item is None for item in parts) else parts


_NATIVE_GROUPING_PRODUCERS = tuple(
    (name, vars(RowTable)[name]) for name in ("get", "__getitem__", "iter_rows", "row_mapping")
)


def _native_grouping_revision(grouping):
    if type(grouping) is not RowTable:
        return None
    namespace = vars(RowTable)
    if namespace.get("__getattribute__", object.__getattribute__) is not object.__getattribute__:
        return None
    if any(namespace.get(name) is not method for name, method in _NATIVE_GROUPING_PRODUCERS):
        return None
    raw = vars(grouping)
    if type(raw) is not dict or any(type(name) is not str for name in raw):
        return None
    if any(name in raw for name, _ in _NATIVE_GROUPING_PRODUCERS):
        return None
    columns, rows = grouping.columns, grouping.rows
    if type(columns) is not tuple or any(type(column) is not str for column in columns):
        return None
    if type(rows) is not tuple or any(
        type(row) is not tuple
        or any(not any(type(value) is native for native in (str, int, float, bool, type(None))) for value in row)
        for row in rows
    ):
        return None
    # Payload identity distinguishes equal-but-differently-rendered primitives
    # (1/True, +0/-0). Retained tuple references prevent identity reuse.
    return id(columns), id(rows), columns, rows


def _tabular_load_columns(loaded) -> tuple[str, ...]:
    sqlite_store = getattr(loaded, "sqlite_store", None)
    if sqlite_store is not None:
        return tuple(str(column) for column in getattr(sqlite_store, "source_columns", ()) or ())
    dataframe = getattr(loaded, "dataframe", None)
    columns = getattr(dataframe, "columns", ())
    return tuple(str(column) for column in columns)


__all__ = [
    "build_analytics_completion_message",
    "IndustrialAnalyticsDialog",
    "MetricSelectionDialog",
    "PRESENTATION_INDUSTRIAL_CACHE",
    "SOURCE_PRODUCTION_CACHE",
    "SOURCE_TABULAR_FILE",
]

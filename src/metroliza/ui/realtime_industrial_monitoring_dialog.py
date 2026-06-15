"""Modeless realtime industrial monitoring dialog."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

from PyQt6.QtCore import Qt, QTimer, QUrl
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository, IndustrialSourceProfile
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
from metroliza.industrial.industrial_workers import RealtimeMonitorPollThread
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_table,
    configure_window_size,
    path_field,
    section_label,
    separator,
    set_status_variant,
    status_chip,
    update_path_field,
)


class RealtimeIndustrialMonitoringDialog(QDialog):
    """Configure and run live polling for one or more industrial source profiles."""

    def __init__(self, parent=None, db_file: str | None = None):
        super().__init__(parent)
        self.db_file = str(db_file or "")
        self.repository = RealtimeMonitorConfigRepository(self.db_file)
        self.source_repository = IndustrialDataRepository(self.db_file)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_once)
        self.poll_thread: RealtimeMonitorPollThread | None = None
        self.profiles: list[IndustrialSourceProfile] = []
        self.configs_by_profile_id: dict[int, RealtimeMonitorConfig] = {}
        self.last_saved_configs: tuple[RealtimeMonitorConfig, ...] = ()
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
        header_row.addWidget(section_label("Real-time industrial monitoring"))
        self.status_label = status_chip("Stopped", "neutral")
        header_row.addWidget(self.status_label)
        layout.addLayout(header_row)

        body_row = QHBoxLayout()
        body_row.addWidget(self._build_source_panel(), 1)
        body_row.addWidget(self._build_config_panel(), 2)
        layout.addLayout(body_row, 2)

        layout.addWidget(separator())
        layout.addLayout(self._build_action_row())
        layout.addWidget(self._build_status_panel(), 2)
        layout.addWidget(self._build_diagnostics_panel(), 1)
        self._sync_running_state(False)

    def _build_source_panel(self) -> QWidget:
        panel = QGroupBox("Sources")
        layout = QVBoxLayout(panel)
        self.source_list = QListWidget()
        self.source_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.source_list.currentItemChanged.connect(self._on_current_source_changed)
        self.source_list.itemChanged.connect(self._on_source_check_changed)
        layout.addWidget(self.source_list)
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
        self.signal_columns_edit.setFixedHeight(86)

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
        form.addRow("Polling interval seconds", self.interval_spin)
        form.addRow("Query timeout seconds", self.timeout_spin)
        form.addRow("Rows per fetch", self.chunk_spin)
        form.addRow("Max catchup rows", self.max_catchup_spin)
        form.addRow("Dashboard mode", self.display_mode_combo)
        form.addRow("Aggregation bucket", self.aggregation_bucket_combo)
        form.addRow("Aggregation methods", self.aggregation_methods_edit)
        form.addRow("Aggregation groups", self.aggregation_groups_edit)
        form.addRow("Context fields", self.context_fields_edit)
        form.addRow("Segment fields", self.segment_fields_edit)
        form.addRow("Detectors", self.detectors_edit)
        layout.addLayout(form)

        path_row = QHBoxLayout()
        self.dashboard_path_field = path_field("", empty_text="Default temp dashboard")
        self.choose_dashboard_button = QPushButton("Choose")
        self.choose_dashboard_button.clicked.connect(self.choose_dashboard_path)
        path_row.addWidget(QLabel("Dashboard file"))
        path_row.addWidget(self.dashboard_path_field, 1)
        path_row.addWidget(self.choose_dashboard_button)
        layout.addLayout(path_row)
        return panel

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.save_button = QPushButton("Save Config")
        self.start_button = QPushButton("Start")
        self.poll_once_button = QPushButton("Poll Once")
        self.stop_button = QPushButton("Stop")
        self.open_dashboard_button = QPushButton("Open Dashboard")
        self.close_button = QPushButton("Close")

        self.save_button.clicked.connect(self.save_selected_configs)
        self.start_button.clicked.connect(self.start_monitoring)
        self.poll_once_button.clicked.connect(self.poll_once)
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.open_dashboard_button.clicked.connect(self.open_dashboard)
        self.close_button.clicked.connect(self.close)

        for button in (
            self.save_button,
            self.start_button,
            self.poll_once_button,
            self.stop_button,
            self.open_dashboard_button,
        ):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(self.close_button)
        return row

    def _build_status_panel(self) -> QWidget:
        panel = QGroupBox("Status")
        layout = QVBoxLayout(panel)
        self.status_table = QTableWidget(0, 8)
        self.status_table.setHorizontalHeaderLabels(
            ("Source", "Stream", "Status", "Rows", "Samples", "Events", "Lag", "Error")
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

    def reload_from_database(self) -> None:
        try:
            self.source_repository.ensure_schema()
            self.repository.ensure_schema()
            self.profiles = self.source_repository.list_source_profiles(include_disabled=True)
            configs = self.repository.list_configs()
            self.configs_by_profile_id = {config.source_profile_id: config for config in configs}
            self._populate_sources()
            self._set_status("Ready" if self.profiles else "No industrial sources configured", "info")
        except Exception as exc:
            self._set_status(f"Load failed: {exc}", "danger")

    def _populate_sources(self) -> None:
        self.source_list.blockSignals(True)
        self.source_list.clear()
        for index, profile in enumerate(self.profiles):
            item = QListWidgetItem(_profile_label(profile))
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            saved = self.configs_by_profile_id.get(profile.id)
            checked = bool(saved and saved.enabled) or (len(self.profiles) == 1 and saved is None)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.source_list.addItem(item)
            if index == 0:
                self.source_list.setCurrentItem(item)
        self.source_list.blockSignals(False)
        self._load_current_source_config()

    def _on_current_source_changed(self, _current, _previous) -> None:
        self._load_current_source_config()

    def _on_source_check_changed(self, _item) -> None:
        self._sync_buttons()

    def _load_current_source_config(self) -> None:
        profile = self.current_profile()
        if profile is None:
            self._apply_config_to_form(None)
            return
        self._apply_config_to_form(self.configs_by_profile_id.get(profile.id) or _default_config(profile))
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
        return tuple(profile for profile in self.profiles if profile.id in selected_ids)

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
            context_fields=_parse_csv_text(self.context_fields_edit.text()) or DEFAULT_CONTEXT_FIELDS,
            segment_fields=_parse_csv_text(self.segment_fields_edit.text()) or DEFAULT_SEGMENT_FIELDS,
            detectors=_parse_csv_text(self.detectors_edit.text()) or ("spec_limits",),
            dashboard_output_path=_field_path(self.dashboard_path_field.text()),
        ).validated()

    def save_selected_configs(self) -> tuple[RealtimeMonitorConfig, ...]:
        profiles = self.selected_profiles()
        if not profiles:
            self._set_status("Select at least one source to monitor.", "warning")
            return ()
        saved: list[RealtimeMonitorConfig] = []
        try:
            for profile in profiles:
                config = self.repository.upsert_config(self._config_from_form(profile))
                self.configs_by_profile_id[profile.id] = config
                saved.append(config)
            self.last_saved_configs = tuple(saved)
            self._set_status(f"Saved {len(saved)} realtime monitor config(s).", "success")
            self._sync_buttons()
            return tuple(saved)
        except Exception as exc:
            self._set_status(f"Config save failed: {exc}", "danger")
            QMessageBox.warning(self, "Realtime monitor config", str(exc))
            return ()

    def start_monitoring(self) -> None:
        configs = self.save_selected_configs()
        if not configs:
            return
        interval_ms = max(1_000, int(min(config.polling_interval_seconds for config in configs) * 1_000))
        self.poll_timer.start(interval_ms)
        self._sync_running_state(True)
        self.poll_once()

    def stop_monitoring(self, _checked: bool = False, *, wait_for_thread: bool = False) -> None:
        self.poll_timer.stop()
        if self.poll_thread is not None and self.poll_thread.isRunning():
            self.poll_thread.cancel()
            if wait_for_thread:
                self.poll_thread.wait(3_000)
        self._sync_running_state(False)
        self._set_status("Stopped", "neutral")

    def poll_once(self) -> None:
        configs = self.last_saved_configs or tuple(
            self.configs_by_profile_id.get(profile.id)
            for profile in self.selected_profiles()
            if self.configs_by_profile_id.get(profile.id) is not None
        )
        configs = tuple(config for config in configs if config is not None)
        if not configs:
            configs = self.save_selected_configs()
            if not configs:
                return
        if self.poll_thread is not None and self.poll_thread.isRunning():
            self._append_diagnostic("Poll skipped because a previous cycle is still running.")
            return
        self.poll_thread = RealtimeMonitorPollThread(db_file=self.db_file, configs=configs)
        self.poll_thread.update_label.connect(lambda text: self._set_status(text, "info"))
        self.poll_thread.result_ready.connect(self._on_poll_results)
        self.poll_thread.error_occurred.connect(self._on_poll_error)
        self.poll_thread.cancelled.connect(lambda text: self._set_status(text, "warning"))
        self.poll_thread.finished.connect(self._clear_poll_thread)
        self._set_status("Polling realtime industrial sources...", "info")
        self.poll_thread.start()

    def _on_poll_results(self, results: tuple[Any, ...]) -> None:
        self.last_poll_results = tuple(results or ())
        self._populate_result_table(self.last_poll_results)
        failed = [result for result in self.last_poll_results if getattr(result, "status", "") == "failed"]
        inserted = sum(int(getattr(result, "samples_inserted", 0) or 0) for result in self.last_poll_results)
        event_count = sum(
            int(getattr(result, "detector_events_created", 0) or 0) for result in self.last_poll_results
        )
        self._append_diagnostic(_format_results_for_diagnostics(self.last_poll_results))
        self.write_dashboard(open_after=False)
        if failed:
            self._set_status(f"Polling completed with {len(failed)} failed stream(s).", "warning")
        else:
            self._set_status(
                f"Polling completed: {inserted} sample(s), {event_count} event(s).",
                "success",
            )

    def _on_poll_error(self, message: str) -> None:
        self._set_status(f"Polling failed: {message}", "danger")
        self._append_diagnostic(message)

    def _clear_poll_thread(self) -> None:
        self.poll_thread = None
        self._sync_buttons()

    def _populate_result_table(self, results: tuple[Any, ...]) -> None:
        self.status_table.setRowCount(len(results))
        profile_names = {profile.id: profile.profile_name for profile in self.profiles}
        for row, result in enumerate(results):
            values = (
                profile_names.get(getattr(result, "source_profile_id", None), "Unknown source"),
                getattr(result, "stream_key", ""),
                getattr(result, "status", ""),
                str(getattr(result, "rows_fetched", 0)),
                str(getattr(result, "samples_inserted", 0)),
                str(getattr(result, "detector_events_created", 0)),
                _format_lag(getattr(result, "lag_seconds", None)),
                str(getattr(result, "error", "") or ""),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column != 0:
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
        path = self.write_dashboard(open_after=True)
        if path is not None:
            self._set_status(f"Dashboard opened: {path}", "success")

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
            self._set_status(f"Dashboard write failed: {exc}", "warning")
            return None

    def _default_dashboard_path(self) -> Path:
        output_dir = Path(tempfile.gettempdir()) / "metroliza" / "realtime_dashboards"
        return output_dir / "realtime_industrial_monitoring.html"

    def _sync_running_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.poll_once_button.setEnabled(not running)
        self.reload_button.setEnabled(not running)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has_sources = bool(self.selected_profiles())
        self.save_button.setEnabled(has_sources)
        self.start_button.setEnabled(has_sources and not self.poll_timer.isActive())
        self.poll_once_button.setEnabled(has_sources and not self.poll_timer.isActive())
        self.open_dashboard_button.setEnabled(True)

    def _set_status(self, text: str, variant: str) -> None:
        self.status_label.setText(text)
        set_status_variant(self.status_label, variant)

    def _append_diagnostic(self, text: str) -> None:
        if not str(text or "").strip():
            return
        current = self.diagnostics_text.toPlainText()
        separator_text = "\n\n" if current else ""
        self.diagnostics_text.setPlainText(f"{current}{separator_text}{text}")
        cursor = self.diagnostics_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.diagnostics_text.setTextCursor(cursor)

    def closeEvent(self, event) -> None:
        self.stop_monitoring(wait_for_thread=True)
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


def _format_results_for_diagnostics(results: tuple[Any, ...]) -> str:
    lines: list[str] = []
    for result in results:
        diagnostics = dict(getattr(result, "diagnostics", {}) or {})
        safe_diagnostics = {
            key: value
            for key, value in diagnostics.items()
            if key not in {"sql_text", "parameters", "password", "token", "credentials"}
        }
        lines.append(
            " | ".join(
                (
                    f"stream={getattr(result, 'stream_key', '')}",
                    f"status={getattr(result, 'status', '')}",
                    f"rows={getattr(result, 'rows_fetched', 0)}",
                    f"samples={getattr(result, 'samples_inserted', 0)}",
                    f"events={getattr(result, 'detector_events_created', 0)}",
                    f"diagnostics={safe_diagnostics}",
                )
            )
        )
    return "\n".join(lines)

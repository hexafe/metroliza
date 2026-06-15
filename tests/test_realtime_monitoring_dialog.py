from pathlib import Path

import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from metroliza.ui.realtime_industrial_monitoring_dialog import (
        RealtimeIndustrialMonitoringDialog,
    )
except ImportError as exc:  # pragma: no cover - environment-dependent import
    Qt = None
    QApplication = None
    RealtimeIndustrialMonitoringDialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.monitor_config import RealtimeMonitorConfigRepository


@pytest.fixture
def qapp():
    if PYQT_IMPORT_ERROR is not None:
        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    return QApplication.instance() or QApplication([])


def _profile(repository, key: str, name: str, *, is_enabled: bool = True):
    return repository.upsert_source_profile(
        profile_key=key,
        profile_name=name,
        source_db_alias=f"{key}_mes",
        database_type="mssql",
        source_object_name="dbo.events",
        allowed_columns=("event_id", "process_timestamp", "record_id", "cycle_time_s", "station"),
        timestamp_column="process_timestamp",
        default_pagination_column="event_id",
        is_enabled=is_enabled,
    )


def test_realtime_monitoring_dialog_saves_checked_source_configs(qapp, tmp_path):
    db_path = str(tmp_path / "dialog.db")
    repository = IndustrialDataRepository(db_path)
    line_a = _profile(repository, "line_a", "Line A")
    line_b = _profile(repository, "line_b", "Line B")
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    try:
        for index in range(dialog.source_list.count()):
            dialog.source_list.item(index).setCheckState(Qt.CheckState.Checked)
        dialog.cursor_column_edit.setText("event_id")
        dialog.event_time_column_edit.setText("process_timestamp")
        dialog.record_key_column_edit.setText("record_id")
        dialog.signal_columns_edit.setPlainText("cycle_time=cycle_time_s")
        dialog.interval_spin.setValue(10)
        dialog.timeout_spin.setValue(5)

        saved = dialog.apply_current_to_checked_configs()
        listed = RealtimeMonitorConfigRepository(db_path).list_configs()

        assert len(saved) == 2
        assert {config.source_profile_id for config in listed} == {line_a.id, line_b.id}
        assert {config.stream_key for config in listed} == {"line_a", "line_b"}
        assert all(config.polling_interval_seconds == 10 for config in listed)
        assert all(config.signal_columns == {"cycle_time": "cycle_time_s"} for config in listed)
    finally:
        dialog.close()


def test_realtime_monitoring_dialog_disabled_sources_are_not_selectable(qapp, tmp_path):
    db_path = str(tmp_path / "dialog.db")
    repository = IndustrialDataRepository(db_path)
    _profile(repository, "disabled_line", "Disabled Line", is_enabled=False)
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    try:
        item = dialog.source_list.item(0)

        assert item.checkState() == Qt.CheckState.Unchecked
        assert not bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        assert not dialog.selected_profiles()
        assert "disabled" in dialog.source_summary_label.text().lower()
        assert not dialog.start_button.isEnabled()
        assert not dialog.poll_once_button.isEnabled()
        assert not dialog.open_dashboard_button.isEnabled()
    finally:
        dialog.close()


def test_realtime_monitoring_dialog_source_bulk_controls_update_selection(qapp, tmp_path):
    db_path = str(tmp_path / "dialog.db")
    repository = IndustrialDataRepository(db_path)
    line_a = _profile(repository, "line_a", "Line A")
    line_b = _profile(repository, "line_b", "Line B")
    _profile(repository, "disabled_line", "Disabled Line", is_enabled=False)
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    try:
        dialog.clear_selected_sources()
        assert dialog.selected_profiles() == ()
        assert "0 of 2 enabled source(s) selected" in dialog.source_summary_label.text()

        dialog.select_all_sources()

        assert {profile.id for profile in dialog.selected_profiles()} == {line_a.id, line_b.id}
        assert "2 of 2 enabled source(s) selected" in dialog.source_summary_label.text()
    finally:
        dialog.close()


def test_realtime_monitoring_dialog_poll_once_uses_current_checked_sources(
    qapp,
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "dialog.db")
    repository = IndustrialDataRepository(db_path)
    line_a = _profile(repository, "line_a", "Line A")
    line_b = _profile(repository, "line_b", "Line B")
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)

    class _Signal:
        def connect(self, _callback):
            return None

    class _FakePollThread:
        instances = []

        def __init__(self, *, db_file, configs):
            self.db_file = db_file
            self.configs = tuple(configs)
            self.update_label = _Signal()
            self.result_ready = _Signal()
            self.error_occurred = _Signal()
            self.cancelled = _Signal()
            self.finished = _Signal()
            self.instances.append(self)

        def isRunning(self):
            return False

        def start(self):
            return None

        def cancel(self):
            return None

        def wait(self, _timeout):
            return None

    try:
        import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module

        monkeypatch.setattr(dialog_module, "RealtimeMonitorPollThread", _FakePollThread)
        dialog.select_all_sources()
        dialog.cursor_column_edit.setText("event_id")
        dialog.event_time_column_edit.setText("process_timestamp")
        dialog.record_key_column_edit.setText("record_id")
        dialog.signal_columns_edit.setPlainText("cycle_time=cycle_time_s")
        dialog.apply_current_to_checked_configs()

        for index in range(dialog.source_list.count()):
            item = dialog.source_list.item(index)
            if int(item.data(Qt.ItemDataRole.UserRole)) == line_b.id:
                item.setCheckState(Qt.CheckState.Unchecked)
        dialog.poll_once()

        assert len(_FakePollThread.instances) == 1
        assert [config.source_profile_id for config in _FakePollThread.instances[0].configs] == [
            line_a.id
        ]
    finally:
        dialog.close()


def test_realtime_monitoring_dialog_writes_empty_dashboard(qapp, tmp_path):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    dashboard_path = tmp_path / "dashboard.html"
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    try:
        dialog.dashboard_path_field.setText(str(dashboard_path))

        written = dialog.write_dashboard()

        assert written == dashboard_path
        html = Path(written).read_text(encoding="utf-8")
        assert "Real-time Industrial Monitoring" in html
        assert 'data-section="summary-cards"' in html
    finally:
        dialog.close()

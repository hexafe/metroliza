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


def _profile(repository, key: str, name: str):
    return repository.upsert_source_profile(
        profile_key=key,
        profile_name=name,
        source_db_alias=f"{key}_mes",
        database_type="mssql",
        source_object_name="dbo.events",
        allowed_columns=("event_id", "process_timestamp", "record_id", "cycle_time_s", "station"),
        timestamp_column="process_timestamp",
        default_pagination_column="event_id",
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

        saved = dialog.save_selected_configs()
        listed = RealtimeMonitorConfigRepository(db_path).list_configs()

        assert len(saved) == 2
        assert {config.source_profile_id for config in listed} == {line_a.id, line_b.id}
        assert {config.stream_key for config in listed} == {"line_a", "line_b"}
        assert all(config.polling_interval_seconds == 10 for config in listed)
        assert all(config.signal_columns == {"cycle_time": "cycle_time_s"} for config in listed)
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

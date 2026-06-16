from pathlib import Path
from types import SimpleNamespace

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
from modules.industrial_source_config import build_source_profile, upsert_source_profile_in_config
from metroliza.industrial.realtime.monitor_config import RealtimeMonitorConfigRepository


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


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


def test_realtime_monitoring_dialog_imports_shared_yaml_source_config(qapp, tmp_path):
    db_path = str(tmp_path / "dialog.db")
    config_path = tmp_path / "industrial_sources.yaml"
    upsert_source_profile_in_config(
        config_path,
        build_source_profile(
            profile_key="line_yaml",
            profile_name="Line YAML",
            source_db_alias="line_yaml",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "process_timestamp", "cycle_time_s"),
            timestamp_column="process_timestamp",
            default_pagination_column="event_id",
        ),
    )

    dialog = RealtimeIndustrialMonitoringDialog(None, db_path, config_path=config_path)
    try:
        assert dialog.source_config_path_field.text() == str(config_path)
        assert dialog.source_list.count() == 1
        assert dialog.profiles[0].profile_key == "line_yaml"
        assert "imported 1 source(s) from YAML" in dialog.status_label.text()
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


def test_realtime_monitoring_dialog_poll_results_schedule_dashboard_write_async(
    qapp,
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    dashboard_path = tmp_path / "dashboard.html"
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)

    class _FakeDashboardThread:
        instances = []

        def __init__(self, *, db_file, output_file):
            self.db_file = db_file
            self.output_file = output_file
            self.result_ready = _Signal()
            self.error_occurred = _Signal()
            self.finished = _Signal()
            self.running = False
            self.instances.append(self)

        def isRunning(self):
            return self.running

        def start(self):
            self.running = True

        def wait(self, _timeout):
            return True

    def fail_sync_write(*_args, **_kwargs):
        raise AssertionError("poll results must not write the dashboard synchronously")

    try:
        import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module

        monkeypatch.setattr(dialog_module, "RealtimeDashboardWriterThread", _FakeDashboardThread)
        monkeypatch.setattr(dialog, "write_dashboard", fail_sync_write)
        dialog.dashboard_write_debounce_timer.setInterval(0)
        dialog.dashboard_path_field.setText(str(dashboard_path))

        dialog._on_poll_results((_poll_result(),))
        qapp.processEvents()

        assert len(_FakeDashboardThread.instances) == 1
        assert _FakeDashboardThread.instances[0].db_file == db_path
        assert _FakeDashboardThread.instances[0].output_file == str(dashboard_path)
    finally:
        dialog.close()


def test_realtime_monitoring_dialog_dashboard_writes_are_coalesced(
    qapp,
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)

    class _FakeDashboardThread:
        instances = []

        def __init__(self, *, db_file, output_file):
            self.db_file = db_file
            self.output_file = output_file
            self.result_ready = _Signal()
            self.error_occurred = _Signal()
            self.finished = _Signal()
            self.running = False
            self.instances.append(self)

        def isRunning(self):
            return self.running

        def start(self):
            self.running = True

        def finish(self):
            self.running = False
            self.finished.emit()

        def wait(self, _timeout):
            return True

    try:
        import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module

        monkeypatch.setattr(dialog_module, "RealtimeDashboardWriterThread", _FakeDashboardThread)
        dialog.dashboard_write_debounce_timer.setInterval(0)

        dialog._on_poll_results((_poll_result(stream_key="line_a"),))
        qapp.processEvents()
        dialog._on_poll_results((_poll_result(stream_key="line_b"),))
        dialog._on_poll_results((_poll_result(stream_key="line_c"),))
        qapp.processEvents()

        assert len(_FakeDashboardThread.instances) == 1

        _FakeDashboardThread.instances[0].finish()
        qapp.processEvents()

        assert len(_FakeDashboardThread.instances) == 2
    finally:
        dialog.close()


def test_realtime_monitoring_dialog_open_dashboard_writes_then_opens_async(
    qapp,
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    dashboard_path = tmp_path / "dashboard.html"
    opened: list[str] = []
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)

    class _FakeDashboardThread:
        instances = []

        def __init__(self, *, db_file, output_file):
            self.db_file = db_file
            self.output_file = output_file
            self.result_ready = _Signal()
            self.error_occurred = _Signal()
            self.finished = _Signal()
            self.running = False
            self.instances.append(self)

        def isRunning(self):
            return self.running

        def start(self):
            self.running = True

        def finish(self, path):
            self.running = False
            self.result_ready.emit(path)
            self.finished.emit()

        def wait(self, _timeout):
            return True

    try:
        import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module

        monkeypatch.setattr(dialog_module, "RealtimeDashboardWriterThread", _FakeDashboardThread)
        monkeypatch.setattr(
            dialog_module.QDesktopServices,
            "openUrl",
            lambda url: opened.append(url.toLocalFile()) or True,
        )
        dialog.dashboard_path_field.setText(str(dashboard_path))

        dialog.open_dashboard()

        assert len(_FakeDashboardThread.instances) == 1
        assert opened == []

        _FakeDashboardThread.instances[0].finish(dashboard_path)

        assert opened == [str(dashboard_path)]
        assert f"Dashboard opened: {dashboard_path}" == dialog.status_label.text()
    finally:
        dialog.close()


def test_realtime_monitoring_dialog_diagnostics_append_does_not_rebuild_text(
    qapp,
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)

    def fail_rebuild(*_args, **_kwargs):
        raise AssertionError("diagnostics append must not rebuild the whole text buffer")

    try:
        monkeypatch.setattr(dialog.diagnostics_text, "toPlainText", fail_rebuild)
        monkeypatch.setattr(dialog.diagnostics_text, "setPlainText", fail_rebuild)
        dialog.diagnostics_text.setMaximumBlockCount(3)

        dialog._append_diagnostic("first")
        dialog._append_diagnostic("second")
        dialog._append_diagnostic("third")

        document = dialog.diagnostics_text.document()
        assert document.blockCount() <= 3
        assert "third" in document.toPlainText()
        assert dialog.diagnostics_text.textCursor().atEnd()
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


def _poll_result(**overrides):
    values = {
        "source_profile_id": 1,
        "stream_key": "line_a",
        "status": "succeeded",
        "rows_fetched": 1,
        "samples_inserted": 1,
        "detector_events_created": 0,
        "lag_seconds": 0.0,
        "error": "",
        "diagnostics": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)

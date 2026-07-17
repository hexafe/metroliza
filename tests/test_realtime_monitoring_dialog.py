from pathlib import Path
from types import SimpleNamespace

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from metroliza.ui.realtime_industrial_monitoring_dialog import (
    RealtimeIndustrialMonitoringDialog,
)

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_source_config import (
    build_source_profile,
    upsert_source_profile_in_config,
)
from metroliza.industrial.realtime.monitor_config import RealtimeMonitorConfigRepository
from metroliza.industrial.realtime.monitor_config import RealtimeMonitorConfig


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


def test_realtime_monitoring_refuses_implicit_configs_for_other_checked_sources(
    qapp,
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "dialog.db")
    repository = IndustrialDataRepository(db_path)
    _profile(repository, "line_a", "Line A")
    _profile(repository, "line_b", "Line B")
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **_kwargs: warnings.append(args),
    )
    try:
        dialog.select_all_sources()

        configs = dialog._configs_for_checked_sources(save_current=True)

        assert configs == ()
        assert RealtimeMonitorConfigRepository(db_path).list_configs() == []
        assert "Save realtime setup" in dialog.config_readiness_label.text()
        assert "Line B" in dialog.config_readiness_label.text()
        assert warnings
        assert dialog.workflow_tabs.currentIndex() == 1
    finally:
        dialog.close()


def test_realtime_stop_remains_stopping_until_poll_worker_finishes(qapp, tmp_path):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)

    class _RunningPoll:
        def __init__(self):
            self.running = True
            self.cancel_calls = 0

        def isRunning(self):
            return self.running

        def cancel(self):
            self.cancel_calls += 1

    poll = _RunningPoll()
    try:
        dialog.poll_thread = poll

        dialog.stop_monitoring()

        assert poll.cancel_calls == 1
        assert dialog._stop_requested is True
        assert "stopping" in dialog.monitor_state_label.text().lower()
        assert not dialog.start_button.isEnabled()

        poll.running = False
        dialog._clear_poll_thread()

        assert dialog.poll_thread is None
        assert dialog._stop_requested is False
        assert dialog.monitor_state_label.text() == "Monitor: stopped"
    finally:
        dialog.poll_thread = None
        dialog.close()


def test_realtime_event_review_requires_operator_comment_and_persists_action(
    qapp,
    tmp_path,
    monkeypatch,
):
    import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module

    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    calls = []
    event = SimpleNamespace(
        id=41,
        event_time="2026-07-17T10:00:00Z",
        profile_name="Line A",
        signal_key="cycle_time",
        severity="warning",
        observed_value=12.5,
        detector_key="spec_limits",
        explanation="Above warning limit.",
    )

    class _FakeDashboardService:
        def __init__(self, database):
            self.database = database

        def list_open_anomaly_events(self, *, limit):
            assert limit == 100
            return [event]

        def acknowledge_event(self, **kwargs):
            calls.append(("acknowledge", kwargs))

        def resolve_event(self, **kwargs):
            calls.append(("resolve", kwargs))

        def mark_event_false_positive(self, **kwargs):
            calls.append(("false_positive", kwargs))

    monkeypatch.setattr(dialog_module, "RealtimeDashboardService", _FakeDashboardService)
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    try:
        dialog.event_review_table.selectRow(0)
        dialog.event_operator_edit.setText("operator-a")

        dialog._apply_selected_event_action("resolve")

        assert calls == []
        assert "comment" in dialog.event_review_status_label.text().lower()

        dialog.event_comment_edit.setText("Verified after line inspection")
        dialog._apply_selected_event_action("resolve")

        assert calls == [
            (
                "resolve",
                {
                    "event_id": 41,
                    "resolved_by": "operator-a",
                    "comment": "Verified after line inspection",
                    "expected_status": "open",
                },
            )
        ]
        assert "resolved by operator-a" in dialog.event_review_status_label.text()
    finally:
        dialog.close()


def test_realtime_event_review_refreshes_instead_of_overwriting_stale_decision(
    qapp,
    tmp_path,
    monkeypatch,
):
    import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module
    from metroliza.industrial.anomaly.event_repository import AnomalyEventStatusConflictError

    db_path = str(tmp_path / "dialog-conflict.db")
    IndustrialDataRepository(db_path).ensure_schema()
    event = SimpleNamespace(
        id=42,
        event_time="2026-07-17T10:00:00Z",
        profile_name="Line A",
        signal_key="cycle_time",
        severity="warning",
        observed_value=12.5,
        detector_key="spec_limits",
        explanation="Above warning limit.",
    )

    class _ConflictingDashboardService:
        load_count = 0

        def __init__(self, _database):
            pass

        def list_open_anomaly_events(self, *, limit):
            assert limit == 100
            type(self).load_count += 1
            return [event] if type(self).load_count == 1 else []

        def resolve_event(self, **_kwargs):
            raise AnomalyEventStatusConflictError(42, "open", "acknowledged")

    monkeypatch.setattr(
        dialog_module,
        "RealtimeDashboardService",
        _ConflictingDashboardService,
    )
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    try:
        dialog.event_review_table.selectRow(0)
        dialog.event_operator_edit.setText("operator-b")
        dialog.event_comment_edit.setText("stale review")

        dialog._apply_selected_event_action("resolve")

        assert dialog.event_review_table.rowCount() == 0
        assert "already reviewed elsewhere" in dialog.event_review_status_label.text().lower()
        assert dialog.event_review_status_label.property("statusVariant") == "warning"
    finally:
        dialog.close()


def test_realtime_monitoring_dialog_preserves_cleared_context_and_segment_fields(
    qapp,
    tmp_path,
):
    db_path = str(tmp_path / "dialog.db")
    repository = IndustrialDataRepository(db_path)
    profile = _profile(repository, "line_a", "Line A")
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    try:
        dialog.cursor_column_edit.setText("event_id")
        dialog.event_time_column_edit.setText("process_timestamp")
        dialog.record_key_column_edit.setText("record_id")
        dialog.signal_columns_edit.setPlainText("cycle_time=cycle_time_s")
        dialog.context_fields_edit.clear()
        dialog.segment_fields_edit.clear()

        saved = dialog.save_current_source_config()
        persisted = RealtimeMonitorConfigRepository(db_path).list_configs(
            source_profile_id=profile.id
        )

        assert len(saved) == 1
        assert saved[0].context_fields == ()
        assert saved[0].segment_fields == ()
        assert len(persisted) == 1
        assert persisted[0].context_fields == ()
        assert persisted[0].segment_fields == ()
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
        if dialog.poll_thread is not None:
            dialog.poll_thread.finished.emit()
        dialog.close()


def test_realtime_monitoring_dialog_timer_polls_only_due_sources(qapp, tmp_path, monkeypatch):
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

    def _monitor_config(profile, interval):
        return RealtimeMonitorConfig(
            source_profile_id=profile.id,
            stream_key=profile.profile_key,
            cursor_column="event_id",
            event_time_column="process_timestamp",
            record_key_column="record_id",
            signal_keys=("cycle_time",),
            signal_columns={"cycle_time": "cycle_time_s"},
            polling_interval_seconds=interval,
        )

    try:
        import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module

        monkeypatch.setattr(dialog_module, "RealtimeMonitorPollThread", _FakePollThread)
        monkeypatch.setattr(dialog_module, "monotonic", lambda: 5.0)
        dialog.active_configs = (_monitor_config(line_a, 5), _monitor_config(line_b, 60))
        dialog._next_poll_due_by_profile_id = {line_a.id: 5.0, line_b.id: 60.0}
        dialog.poll_timer.start(1_000_000)

        dialog.poll_once()

        assert len(_FakePollThread.instances) == 1
        assert [config.source_profile_id for config in _FakePollThread.instances[0].configs] == [
            line_a.id
        ]
        assert dialog._next_poll_due_by_profile_id[line_a.id] == 10.0
        assert dialog._next_poll_due_by_profile_id[line_b.id] == 60.0
    finally:
        dialog.poll_timer.stop()
        if dialog.poll_thread is not None:
            dialog.poll_thread.finished.emit()
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
        if dialog.dashboard_thread is not None:
            dialog.dashboard_thread.running = False
            dialog.dashboard_thread.finished.emit()
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
        if dialog.dashboard_thread is not None:
            dialog.dashboard_thread.running = False
            dialog.dashboard_thread.finished.emit()
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


def test_realtime_monitoring_dialog_failed_result_shows_actionable_safe_diagnostics(
    qapp,
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "dialog.db")
    repository = IndustrialDataRepository(db_path)
    line_a = _profile(repository, "line_a", "Line A")
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    result = _poll_result(
        source_profile_id=line_a.id,
        stream_key="line_a",
        status="failed",
        rows_fetched=7,
        samples_inserted=0,
        detector_events_created=0,
        cursor_value="105",
        error="login failed password=rawsecret",
        diagnostics={
            "stage": "credentials",
            "failure_stage": "source_read",
            "sql_hash": "abcdef1234567890",
            "query_summary": "bounded mssql poll, source=dbo.events, stream=line_a, limit=100",
            "rows_fetched": 7,
            "cursor_value": "105",
            "sql_text": "SELECT password FROM dbo.events",
            "warnings": ["token=diagnostic-secret"],
        },
    )

    try:
        monkeypatch.setattr(dialog, "_schedule_dashboard_write", lambda open_after: None)

        dialog._on_poll_results((result,))

        assert dialog.status_label.text() == (
            "Polling completed with 1 failed stream(s): line_a credentials - "
            "login failed password=<redacted>"
        )
        assert dialog.status_table.item(0, 2).text() == "failed"
        assert dialog.status_table.item(0, 3).text() == "credentials"
        assert dialog.status_table.item(0, 4).text() == "7"
        assert dialog.status_table.item(0, 7).text() == "105"
        assert dialog.status_table.item(0, 8).text().startswith("bounded mssql poll")
        assert dialog.status_table.item(0, 10).text() == "login failed password=<redacted>"
        diagnostics_text = dialog.diagnostics_text.toPlainText()
        assert "SELECT password FROM dbo.events" not in diagnostics_text
        assert "rawsecret" not in diagnostics_text
        assert "diagnostic-secret" not in diagnostics_text
        assert "token=<redacted>" in diagnostics_text
    finally:
        dialog.close()


def test_realtime_monitoring_dialog_detector_consumer_failure_is_warning(
    qapp,
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "dialog.db")
    repository = IndustrialDataRepository(db_path)
    line_a = _profile(repository, "line_a", "Line A")
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    result = _poll_result(
        source_profile_id=line_a.id,
        stream_key="line_a",
        status="completed",
        rows_fetched=3,
        samples_inserted=3,
        detector_events_created=0,
        detector_consumer_status="failed",
        detector_consumer_error="detector crashed password=rawsecret",
    )

    try:
        monkeypatch.setattr(dialog, "_schedule_dashboard_write", lambda open_after: None)

        dialog._on_poll_results((result,))

        assert dialog.status_label.text() == (
            "Polling completed with 1 failed stream(s): line_a detector_consumer - "
            "detector crashed password=<redacted>"
        )
        assert dialog.status_table.item(0, 2).text() == "completed_with_warnings"
        assert dialog.status_table.item(0, 3).text() == "detector_consumer"
        assert dialog.status_table.item(0, 10).text() == "detector crashed password=<redacted>"
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


def test_realtime_monitoring_dialog_defers_shutdown_until_all_workers_finish(qapp, tmp_path):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)

    class _RunningThread:
        def __init__(self, *, cancellable: bool):
            self.running = True
            self.cancel_calls = 0
            self.cancellable = cancellable

        def isRunning(self):
            return self.running

        def cancel(self):
            assert self.cancellable
            self.cancel_calls += 1

    poll_thread = _RunningThread(cancellable=True)
    dashboard_thread = _RunningThread(cancellable=False)
    default_directory = dialog._default_dashboard_path().parent
    completions: list[str] = []
    dialog.shutdown_complete.connect(lambda: completions.append("complete"))
    dialog.poll_thread = poll_thread
    dialog.dashboard_thread = dashboard_thread

    assert dialog.request_shutdown() is False
    assert poll_thread.cancel_calls == 1
    assert default_directory.exists()

    poll_thread.running = False
    dialog._clear_poll_thread()
    assert completions == []
    assert default_directory.exists()

    dashboard_thread.running = False
    dialog._on_dashboard_writer_finished()
    assert completions == ["complete"]
    assert not default_directory.exists()
    assert dialog.request_shutdown() is True
    assert completions == ["complete"]
    dialog.close()
    qapp.processEvents()


def test_stale_finished_callbacks_do_not_clear_new_worker_ownership(qapp, tmp_path):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    old_poll = object()
    new_poll = object()
    old_dashboard = object()
    new_dashboard = object()
    try:
        dialog.poll_thread = new_poll
        dialog._clear_poll_thread(old_poll)
        assert dialog.poll_thread is new_poll

        dialog.dashboard_thread = new_dashboard
        dialog._on_dashboard_writer_finished(old_dashboard)
        assert dialog.dashboard_thread is new_dashboard
    finally:
        dialog.poll_thread = None
        dialog.dashboard_thread = None
        dialog.close()


def test_realtime_parent_close_observes_dirty_modeless_source_editor(
    qapp,
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: answers.pop(0),
    )
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    dialog.show()
    dialog.open_source_profiles_dialog()
    qapp.processEvents()
    source_window = dialog.source_window
    assert source_window is not None
    source_window.source_name_edit.setText("Unsaved line source")

    assert dialog.close() is False
    qapp.processEvents()

    assert dialog.isVisible()
    assert source_window.isVisible()
    assert source_window.source_name_edit.text() == "Unsaved line source"
    assert dialog.source_window is source_window
    assert dialog._closing is False
    assert "before closing realtime monitoring" in dialog.config_readiness_label.text()

    assert dialog.close() is True
    qapp.processEvents()

    assert not dialog.isVisible()
    assert not source_window.isVisible()
    assert dialog.source_window is None
    assert answers == []
    dialog.deleteLater()
    qapp.processEvents()


def test_realtime_rebind_refuses_dirty_source_editor_bound_to_previous_database(
    qapp,
    tmp_path,
    monkeypatch,
):
    first_db = str(tmp_path / "first.db")
    second_db = str(tmp_path / "second.db")
    IndustrialDataRepository(first_db).ensure_schema()
    IndustrialDataRepository(second_db).ensure_schema()
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: answers.pop(0),
    )
    dialog = RealtimeIndustrialMonitoringDialog(None, first_db)
    dialog.show()
    dialog.open_source_profiles_dialog()
    qapp.processEvents()
    source_window = dialog.source_window
    assert source_window is not None
    assert source_window.db_file == first_db
    source_window.source_name_edit.setText("Unsaved line source")

    assert dialog.rebind_database(second_db) is False

    assert dialog.db_file == first_db
    assert dialog.source_window is source_window
    assert source_window.isVisible()
    assert source_window.source_name_edit.text() == "Unsaved line source"
    assert "before changing the workspace database" in dialog.config_readiness_label.text()

    assert dialog.rebind_database(second_db) is True

    assert dialog.db_file == second_db
    assert dialog.source_window is None
    assert not source_window.isVisible()
    assert answers == []
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_realtime_monitoring_dialog_default_dashboard_directory_is_private(qapp, tmp_path):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    dialog = RealtimeIndustrialMonitoringDialog(None, db_path)
    try:
        output_directory = dialog._default_dashboard_path().parent

        assert output_directory.exists()
        assert output_directory.stat().st_mode & 0o777 == 0o700
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
        "cursor_value": None,
        "error": "",
        "diagnostics": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)

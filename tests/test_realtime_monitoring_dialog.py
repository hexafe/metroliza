from pathlib import Path
from types import SimpleNamespace
from contextlib import ExitStack
import json
import gc
import os
import sys
import tempfile
import threading

import pytest

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, QThread, QTimer, Qt
from PyQt6.QtTest import QSignalSpy
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
    app = QApplication.instance() or QApplication([])
    expected = os.environ.get("METROLIZA_EXPECT_QT_PLATFORM")
    if expected:
        assert app.platformName() == expected
    return app


def _wait_for(predicate, description, *, timeout_ms=3000):
    """Observe an outcome within a test-only bound, not a runtime deadline."""
    if predicate():
        return
    loop = QEventLoop()
    poll = QTimer(loop)
    poll.setInterval(5)
    deadline = QTimer(loop)
    deadline.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.timeout.connect(loop.quit)
    try:
        poll.start()
        deadline.start(timeout_ms)
        loop.exec()
        observed = predicate()
    finally:
        poll.stop()
        deadline.stop()
        loop.deleteLater()
        QCoreApplication.sendPostedEvents(loop, QEvent.Type.DeferredDelete)
    assert observed, f"timed out waiting for {description}"


@pytest.fixture
def dashboard_dialog(qapp, tmp_path):
    """Own the dialog through terminal worker callbacks and C++ destruction."""
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    dialog = RealtimeIndustrialMonitoringDialog(
        None, db_path, config_path=tmp_path / "unused-sources.yaml"
    )
    dialog.dashboard_path_field.setText(str(tmp_path / "dashboard.html"))
    try:
        yield dialog
    finally:
        dialog.request_shutdown()
        worker = dialog.dashboard_thread
        if worker is not None:
            finish = getattr(worker, "finish", None)
            if callable(finish):
                finish()
            _wait_for(lambda: dialog.dashboard_thread is None, "owned dashboard cleanup")
        assert dialog.close()
        assert not dialog.is_monitoring_active()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
        assert sip.isdeleted(dialog)


@pytest.fixture(params=["normal", "deferred"])
def dashboard_writers(dashboard_dialog, monkeypatch, request):
    import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module

    instances = []

    class FakeDashboardThread:
        def __init__(self, *, db_file, output_file):
            self.db_file = db_file
            self.output_file = output_file
            self.result_ready = _Signal()
            self.error_occurred = _Signal()
            self.finished = _Signal()
            self.running = False
            self.starts = 0
            instances.append(self)

        def isRunning(self):
            return self.running

        def start(self):
            self.running = True
            self.starts += 1

        def finish(self):
            self.running = False
            self.finished.emit()

    monkeypatch.setattr(dialog_module, "RealtimeDashboardWriterThread", FakeDashboardThread)

    def fail_sync_write(*_args, **_kwargs):
        raise AssertionError("poll results must not write the dashboard synchronously")

    monkeypatch.setattr(dashboard_dialog, "write_dashboard", fail_sync_write)
    if request.param == "deferred":
        # Controlled delayed dispatch, not a claim about the historical ordering.
        class DeferredDispatch(QObject):
            def eventFilter(self, watched, event):
                return (
                    event.type() == QEvent.Type.Timer
                    and QThread.currentThread().loopLevel() == 0
                )

        timer = dashboard_dialog.dashboard_write_debounce_timer
        guard = DeferredDispatch(timer)
        timer.installEventFilter(guard)
        timer.setInterval(0)
    else:
        assert dashboard_dialog.dashboard_write_debounce_timer.interval() == 250
    yield instances


def _queued_poll_results(dialog):
    """Deliver a late result through Qt, with an observable completion boundary."""
    delivered = []
    timer = QTimer(dialog)
    timer.setSingleShot(True)

    def deliver():
        dialog._on_poll_results((_poll_result(stream_key="late"),))
        delivered.append(True)

    timer.timeout.connect(deliver)
    timer.start(0)
    _wait_for(lambda: bool(delivered), "queued poll result")


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
    dashboard_dialog, dashboard_writers,
):
    dialog = dashboard_dialog
    dialog._on_poll_results((_poll_result(),))

    assert dashboard_writers == []
    assert dialog._dashboard_write_pending
    assert dialog.is_monitoring_active()
    _wait_for(lambda: bool(dashboard_writers), "dashboard writer start")

    assert len(dashboard_writers) == 1
    writer = dashboard_writers[0]
    assert writer.starts == 1
    assert writer.isRunning()
    assert writer.db_file == dialog.db_file
    assert writer.output_file == dialog.dashboard_path_field.text()
    assert dialog.dashboard_thread is writer
    assert not dialog._dashboard_write_pending
    assert not dialog.dashboard_write_debounce_timer.isActive()


def test_realtime_monitoring_dialog_dashboard_writes_are_coalesced(
    dashboard_dialog, dashboard_writers,
):
    dialog = dashboard_dialog
    idle = QSignalSpy(dialog.database_work_idle)
    dialog._on_poll_results((_poll_result(stream_key="line_a"),))
    _wait_for(lambda: bool(dashboard_writers), "first dashboard writer")
    first = dashboard_writers[0]
    dialog._on_poll_results((_poll_result(stream_key="line_b"),))
    dialog._on_poll_results((_poll_result(stream_key="line_c"),))

    assert len(dashboard_writers) == 1
    assert first.isRunning()
    assert dialog._dashboard_write_pending
    assert not dialog.dashboard_write_debounce_timer.isActive()
    assert dialog.is_monitoring_active()
    assert len(idle) == 0

    # A stopped worker still owns its context until its finished callback arrives.
    first.running = False
    assert dialog.is_monitoring_active()
    first.finish()
    assert dialog.dashboard_thread is None
    assert dialog._dashboard_write_pending
    assert dialog.is_monitoring_active()
    assert len(idle) == 0
    _wait_for(lambda: len(dashboard_writers) >= 2, "coalesced follow-up writer")

    assert len(dashboard_writers) == 2
    second = dashboard_writers[1]
    assert second is dialog.dashboard_thread
    assert second.db_file == first.db_file
    assert second.output_file == first.output_file
    assert [worker.starts for worker in dashboard_writers] == [1, 1]
    assert dialog.last_poll_results[0].stream_key == "line_c"
    assert not dialog._dashboard_write_pending
    first.finished.emit()
    assert dialog.dashboard_thread is second
    assert len(idle) == 0
    second.finish()
    assert not dialog.is_monitoring_active()
    assert len(idle) == 1
    assert len(dashboard_writers) == 2


def test_dashboard_observation_rejects_a_writer_prevented_from_starting(
    dashboard_dialog, dashboard_writers,
):
    dialog = dashboard_dialog
    timer = dialog.dashboard_write_debounce_timer
    timer.setInterval(0)
    timer.timeout.disconnect(dialog._start_dashboard_write)
    dispatched = QSignalSpy(timer.timeout)
    dialog._on_poll_results((_poll_result(),))

    # This shorter bound is only the deliberate negative control, not the
    # positive liveness deadline or a change to production's 250 ms debounce.
    with pytest.raises(AssertionError, match="timed out waiting for blocked writer"):
        _wait_for(lambda: bool(dashboard_writers), "blocked writer", timeout_ms=100)
    assert len(dispatched) == 1
    assert dashboard_writers == []
    assert dialog._dashboard_write_pending
    assert dialog.is_monitoring_active()


def test_dashboard_close_cancels_pending_dispatch_and_ignores_late_results(
    dashboard_dialog, dashboard_writers,
):
    dialog = dashboard_dialog
    directory = dialog._default_dashboard_path().parent
    dialog._on_poll_results((_poll_result(),))
    assert dialog.is_monitoring_active()

    assert dialog.request_shutdown()
    _queued_poll_results(dialog)

    assert dashboard_writers == []
    assert not dialog.dashboard_write_debounce_timer.isActive()
    assert not dialog._dashboard_write_pending
    assert not dialog.is_monitoring_active()
    assert not directory.exists()


def test_dashboard_close_retains_worker_ownership_until_finished(
    dashboard_dialog, dashboard_writers,
):
    dialog = dashboard_dialog
    directory = dialog._default_dashboard_path().parent
    closed = QSignalSpy(dialog.shutdown_complete)
    idle = QSignalSpy(dialog.database_work_idle)
    dialog._on_poll_results((_poll_result(),))
    _wait_for(lambda: bool(dashboard_writers), "dashboard writer before close")
    writer = dashboard_writers[0]
    dialog._on_poll_results((_poll_result(stream_key="queued"),))
    assert dialog._dashboard_write_pending

    assert not dialog.request_shutdown()
    assert dialog.is_close_deferred()
    assert not dialog._dashboard_write_pending
    assert dialog.is_monitoring_active()
    assert directory.exists()
    writer.running = False
    assert dialog.is_monitoring_active()
    assert len(closed) == len(idle) == 0
    writer.finish()
    _queued_poll_results(dialog)

    assert len(dashboard_writers) == 1
    assert dialog.dashboard_thread is None
    assert not dialog.is_monitoring_active()
    assert len(closed) == 1
    assert len(idle) == 0
    assert not directory.exists()


def test_dashboard_dispatch_is_owned_by_its_dialog(
    dashboard_dialog, dashboard_writers, tmp_path,
):
    first = dashboard_dialog
    first._on_poll_results((_poll_result(),))
    assert first.request_shutdown()
    second_db = str(tmp_path / "second.db")
    IndustrialDataRepository(second_db).ensure_schema()
    second = RealtimeIndustrialMonitoringDialog(
        None, second_db, config_path=tmp_path / "unused-second-sources.yaml"
    )
    try:
        second._on_poll_results((_poll_result(),))
        _queued_poll_results(first)
        _wait_for(lambda: bool(dashboard_writers), "second dialog writer")
        assert len(dashboard_writers) == 1
        assert dashboard_writers[0].db_file == second_db
        assert second.dashboard_thread is dashboard_writers[0]
        assert first.dashboard_thread is None
        assert not first.is_monitoring_active()
    finally:
        second.request_shutdown()
        if second.dashboard_thread is not None:
            second.dashboard_thread.finish()
        assert second.close()
        second.deleteLater()
        QCoreApplication.sendPostedEvents(second, QEvent.Type.DeferredDelete)
        assert sip.isdeleted(second)


def test_poll_results_use_real_dashboard_worker_and_sqlite(dashboard_dialog, monkeypatch):
    from metroliza.industrial.realtime.realtime_dashboard_service import RealtimeDashboardService

    dialog = dashboard_dialog
    output = Path(dialog.dashboard_path_field.text())
    entered = threading.Event()
    release = threading.Event()
    worker_threads = []
    gui_thread = threading.get_ident()
    original = RealtimeDashboardService.dashboard_snapshot
    idle = QSignalSpy(dialog.database_work_idle)
    errors = []
    monkeypatch.setattr(dialog, "_on_dashboard_write_error", errors.append)

    def gated_snapshot(service):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(3), "test did not release the real dashboard worker"
        return original(service)

    monkeypatch.setattr(RealtimeDashboardService, "dashboard_snapshot", gated_snapshot)
    try:
        dialog._on_poll_results((_poll_result(),))
        assert not entered.is_set()
        assert not output.exists()
        _wait_for(entered.is_set, "real dashboard worker entry")
        assert len(worker_threads) == 1
        assert worker_threads[0] != gui_thread
        worker = dialog.dashboard_thread
        assert worker.db_file == dialog.db_file
        assert worker.output_file == str(output)
        assert dialog.is_monitoring_active()
        assert len(idle) == 0
        assert not output.exists()
        release.set()
        _wait_for(lambda: dialog.dashboard_thread is None, "real dashboard cleanup")
        if not sip.isdeleted(worker):
            QCoreApplication.sendPostedEvents(worker, QEvent.Type.DeferredDelete)
        assert sip.isdeleted(worker)
        assert errors == []
        assert dialog.last_dashboard_path == output
        assert "Real-time Industrial Monitoring" in output.read_text(encoding="utf-8")
        assert len(idle) == 1
        assert not dialog.is_monitoring_active()
    finally:
        release.set()


@pytest.mark.parametrize("queued", [False, True])
def test_realtime_monitoring_dialog_open_dashboard_writes_then_opens_async(
    dashboard_dialog, dashboard_writers, monkeypatch, queued,
):
    import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module

    dialog = dashboard_dialog
    output = Path(dialog.dashboard_path_field.text())
    opened = []
    monkeypatch.setattr(
        dialog_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url) or True,
    )
    if queued:
        dialog._on_poll_results((_poll_result(),))
        _wait_for(lambda: bool(dashboard_writers), "writer before queued open")
        first = dashboard_writers[0]
        dialog.open_dashboard()
        assert len(dashboard_writers) == 1
        assert dialog._dashboard_write_pending
        assert dialog._dashboard_open_pending
        first.result_ready.emit(output)
        assert opened == []
        first.finish()
    else:
        dialog.open_dashboard()

    assert len(dashboard_writers) == (2 if queued else 1)
    assert opened == []
    writer = dashboard_writers[-1]
    assert writer.starts == 1
    assert writer.isRunning()
    assert writer.db_file == dialog.db_file
    assert writer.output_file == str(output)
    assert dialog._dashboard_open_after_current
    writer.result_ready.emit(output)
    writer.finish()

    assert len(opened) == 1
    assert opened[0].isLocalFile()
    assert Path(opened[0].toLocalFile()) == output
    assert dialog.status_label.text() == f"Dashboard opened: {output}"
    assert not dialog._dashboard_open_after_current
    assert not dialog._dashboard_open_pending
    assert not dialog.is_monitoring_active()


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


def _assert_dashboard_privacy(directory, html_path):
    if os.name == "nt":
        from tests.windows_dashboard_privacy import inspect_dashboard_privacy

        expected_python = os.environ.get("METROLIZA_EXPECT_PRIVACY_PYTHON")
        if expected_python:
            assert ".".join(map(str, sys.version_info[:3])) == expected_python
        receipt = inspect_dashboard_privacy(directory, html_path)
        print("dashboard_privacy=" + json.dumps(receipt.as_dict(), sort_keys=True))
    else:
        # POSIX retains its original protection contract; Windows uses the DACL.
        assert directory.stat().st_mode & 0o777 == 0o700


def test_private_dashboard_directory_creation_failure_is_safe(tmp_path, monkeypatch):
    from metroliza.ui.private_dashboard_directory import (
        PrivateDashboardDirectoryError,
        create_private_dashboard_directory,
    )

    not_directory = tmp_path / "not-a-directory"
    not_directory.write_text("synthetic unchanged control", encoding="utf-8")
    monkeypatch.setattr(tempfile, "tempdir", str(not_directory))
    with pytest.raises(PrivateDashboardDirectoryError, match="^private_dashboard_directory_unavailable$"):
        create_private_dashboard_directory()
    assert not_directory.read_text(encoding="utf-8") == "synthetic unchanged control"
    assert list(tmp_path.iterdir()) == [not_directory]


def test_private_dashboard_directory_finalizer_keeps_unowned_files(tmp_path, monkeypatch):
    from metroliza.ui.private_dashboard_directory import create_private_dashboard_directory

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    sentinel = tmp_path / "unowned.txt"
    sentinel.write_text("retained", encoding="utf-8")
    owner = create_private_dashboard_directory()
    directory = Path(owner.name)
    (directory / "synthetic.html").write_text("owned synthetic output", encoding="utf-8")
    del owner
    gc.collect()
    assert not directory.exists()
    assert sentinel.read_text(encoding="utf-8") == "retained"


@pytest.mark.parametrize("failure_stage", ["creation", "security"])
@pytest.mark.parametrize("dispatch", ["synchronous", "open", "queued"])
def test_private_dashboard_storage_failure_blocks_default_output(
    qapp, tmp_path, monkeypatch, failure_stage, dispatch,
):
    import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module
    from metroliza.ui.private_dashboard_directory import PrivateDashboardDirectoryError

    def unavailable():
        raise PrivateDashboardDirectoryError(f"synthetic {failure_stage} detail")

    def unexpected_output(*args, **kwargs):
        pytest.fail("unavailable private storage must not start output")

    monkeypatch.setattr(dialog_module, "create_private_dashboard_directory", unavailable)
    monkeypatch.setattr(dialog_module, "RealtimeDashboardWriterThread", unexpected_output)
    monkeypatch.setattr(dialog_module.RealtimeDashboardService, "dashboard_snapshot", unexpected_output)
    monkeypatch.setattr(dialog_module.QDesktopServices, "openUrl", unexpected_output)
    db_path = tmp_path / "unavailable.db"
    IndustrialDataRepository(str(db_path)).ensure_schema()
    dialog = RealtimeIndustrialMonitoringDialog(
        None, str(db_path), config_path=tmp_path / "unused.yaml"
    )
    try:
        assert dialog._dashboard_temp_dir is None
        assert "Private temporary dashboard storage is unavailable" in dialog.dashboard_status_label.text()
        if dispatch == "synchronous":
            assert dialog.write_dashboard() is None
        elif dispatch == "open":
            dialog.open_dashboard()
        else:
            dispatched = QSignalSpy(dialog.dashboard_write_debounce_timer.timeout)
            dialog._schedule_dashboard_write(open_after=False)
            assert dialog._dashboard_write_pending
            _wait_for(lambda: len(dispatched) == 1, "unavailable storage dispatch")
        assert dialog.dashboard_thread is None
        assert dialog.last_dashboard_path is None
        assert not dialog._dashboard_write_pending
        assert not dialog._dashboard_open_pending
        assert not dialog.dashboard_write_debounce_timer.isActive()
        assert "Private temporary dashboard storage is unavailable" in dialog.dashboard_status_label.text()
        assert "synthetic" not in dialog.dashboard_status_label.text()
        assert "synthetic" not in dialog.diagnostics_text.toPlainText()
        assert not list(tmp_path.rglob("*.html"))
    finally:
        assert dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
        assert sip.isdeleted(dialog)


def test_private_dashboard_storage_failure_allows_explicit_output_choice(qapp, tmp_path, monkeypatch):
    import metroliza.ui.realtime_industrial_monitoring_dialog as dialog_module
    from metroliza.ui.private_dashboard_directory import PrivateDashboardDirectoryError

    def unavailable():
        raise PrivateDashboardDirectoryError("synthetic creation failure")

    monkeypatch.setattr(dialog_module, "create_private_dashboard_directory", unavailable)
    destination = tmp_path / "chosen.html"
    choices = []

    def choose(parent, title, initial, filters):
        choices.append(initial)
        return str(destination), "HTML files (*.html)"

    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", choose)
    db_path = tmp_path / "chosen.db"
    IndustrialDataRepository(str(db_path)).ensure_schema()
    dialog = RealtimeIndustrialMonitoringDialog(None, str(db_path), config_path=tmp_path / "unused.yaml")
    try:
        dialog.choose_dashboard_path()
        assert choices == ["realtime_industrial_monitoring.html"]
        assert dialog.write_dashboard() == destination
        assert "Real-time Industrial Monitoring" in destination.read_text(encoding="utf-8")
    finally:
        assert dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
        assert sip.isdeleted(dialog)
    assert destination.exists()  # Explicit operator output is not owned session storage.


@pytest.mark.parametrize("deferred", [False, True])
def test_private_dashboard_cleanup_failure_retains_ownership_until_retry(
    dashboard_dialog, monkeypatch, deferred,
):
    dialog = dashboard_dialog
    owned = dialog._dashboard_temp_dir
    directory = Path(owned.name)
    attempts = []

    def cleanup():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("synthetic cleanup detail")
        owned.cleanup()

    retained = SimpleNamespace(name=owned.name, cleanup=cleanup)
    monkeypatch.setattr(dialog, "_dashboard_temp_dir", retained)
    completed = QSignalSpy(dialog.shutdown_complete)
    if deferred:
        dialog._closing = True
        dialog._shutdown_waiting = True
        dialog._complete_deferred_shutdown()
    else:
        assert not dialog.close()
    assert len(completed) == 0
    assert dialog._dashboard_temp_dir is retained
    assert directory.is_dir()
    assert not dialog.is_close_deferred()
    assert "Close again to retry" in dialog.dashboard_status_label.text()
    assert "synthetic" not in dialog.dashboard_status_label.text()
    assert dialog.close()
    assert len(attempts) == 2
    assert dialog._dashboard_temp_dir is None
    assert not directory.exists()


@pytest.mark.parametrize("parent_policy", ["default", "permissive"])
def test_realtime_monitoring_dialog_default_dashboard_directory_is_private(
    qapp, tmp_path, monkeypatch, parent_policy,
):
    db_path = str(tmp_path / "dialog.db")
    IndustrialDataRepository(db_path).ensure_schema()
    with ExitStack() as stack:
        if os.name == "nt" and parent_policy == "default":
            import metroliza.ui.private_dashboard_directory as private_directory
            from tests.windows_dashboard_privacy import (
                inspect_dashboard_privacy,
                null_dacl_directory,
                untrusted_child_delete_directory,
            )

            missing = tmp_path / "missing-private-directory"
            with pytest.raises(AssertionError, match="privacy_oracle_get_named_security_info_failed"):
                inspect_dashboard_privacy(missing, missing / "missing.html")
            with pytest.raises(AssertionError, match="privacy_oracle_get_named_security_info_failed"):
                inspect_dashboard_privacy(tmp_path, tmp_path / "missing.html")
            null_control = tmp_path / "owned-null-dacl-control"
            null_control.mkdir()
            with null_dacl_directory(null_control):
                control_html = null_control / "control.html"
                control_html.write_text("synthetic null-DACL control", encoding="utf-8")
                with pytest.raises(AssertionError, match="privacy_oracle_null_dacl"):
                    inspect_dashboard_privacy(null_control, control_html)

            delete_control = tmp_path / "owned-untrusted-child-delete-control"
            delete_control.mkdir()
            with untrusted_child_delete_directory(delete_control):
                inherited = delete_control / "inherited"
                inherited.mkdir()
                control_html = inherited / "control.html"
                control_html.write_text("synthetic child-delete control", encoding="utf-8")
                with pytest.raises(AssertionError, match="^privacy_oracle_untrusted_allow_ace$"):
                    inspect_dashboard_privacy(inherited, control_html)

            # A real pinned/owned object must be removed if its security check fails.
            failed_parent = tmp_path / "owned-security-failure"
            failed_parent.mkdir()
            validated = []
            original_validate = private_directory._validate_pinned_directory

            def reject_validated_directory(*args):
                original_validate(*args)
                validated.append(True)
                raise private_directory.PrivateDashboardDirectoryError()

            with monkeypatch.context() as failure:
                failure.setattr(tempfile, "tempdir", str(failed_parent))
                failure.setattr(private_directory, "_validate_pinned_directory", reject_validated_directory)
                with pytest.raises(private_directory.PrivateDashboardDirectoryError):
                    private_directory.create_private_dashboard_directory()
            assert validated == [True]
            assert list(failed_parent.iterdir()) == []

            # Fault injection is a failure control; positive creation below uses real NtCreateFile.
            for ntstatus in (-1073741790, 0x103):  # ACCESS_DENIED, PENDING
                denied_parent = tmp_path / f"owned-atomic-failure-{ntstatus}"
                denied_parent.mkdir()
                denied_calls = []

                def deny_atomic_create(_ntdll, candidate, _attributes):
                    denied_calls.append(candidate)
                    return ntstatus, None, 0

                with monkeypatch.context() as failure:
                    failure.setattr(tempfile, "tempdir", str(denied_parent))
                    failure.setattr(private_directory, "_nt_create_private_directory", deny_atomic_create)
                    with pytest.raises(private_directory.PrivateDashboardDirectoryError):
                        private_directory.create_private_dashboard_directory()
                assert len(denied_calls) == 1
                assert list(denied_parent.iterdir()) == []

            collision_parent = tmp_path / "owned-collision-control"
            collision_parent.mkdir()
            existing = collision_parent / "metroliza-realtime-dashboard-collision"
            existing.mkdir()
            sentinel = existing / "unowned.txt"
            sentinel.write_text("retained collision control", encoding="utf-8")
            names = iter(("collision", "new-owned"))
            with monkeypatch.context() as collision:
                collision.setattr(tempfile, "tempdir", str(collision_parent))
                collision.setattr(private_directory.secrets, "token_hex", lambda _size: next(names))
                created = private_directory.create_private_dashboard_directory()
            try:
                assert Path(created.name).name == "metroliza-realtime-dashboard-new-owned"
                assert sentinel.read_text(encoding="utf-8") == "retained collision control"
            finally:
                created.cleanup()
            assert list(collision_parent.iterdir()) == [existing]

        if parent_policy == "permissive":
            parent = tmp_path / "owned-permissive-parent"
            parent.mkdir()
            if os.name == "nt":
                from tests.windows_dashboard_privacy import permissive_directory

                stack.enter_context(permissive_directory(parent))
            else:
                parent.chmod(0o777)
            control = parent / "permissive-control"
            control.mkdir()
            control_html = control / "control.html"
            control_html.write_text("synthetic privacy control", encoding="utf-8")
            if os.name != "nt":
                control.chmod(0o777)
            # The identical oracle must reject actually permissive scratch bytes.
            expected_error = "native_privacy_broad_content" if os.name == "nt" else None
            with pytest.raises(AssertionError, match=expected_error):
                _assert_dashboard_privacy(control, control_html)
            monkeypatch.setattr(tempfile, "tempdir", str(parent))

        dialog = RealtimeIndustrialMonitoringDialog(
            None, db_path, config_path=tmp_path / "unused-sources.yaml"
        )
        output_directory = dialog._default_dashboard_path().parent
        try:
            assert output_directory.exists()
            if os.name == "nt":
                with pytest.raises(OSError) as blocked:
                    output_directory.rename(output_directory.with_name("owned-replacement-attempt"))
                assert blocked.value.winerror == 32  # Held handle refuses delete/rename sharing.
                assert output_directory.is_dir()
            output_path = dialog.write_dashboard()
            assert output_path == dialog._default_dashboard_path()
            assert "Real-time Industrial Monitoring" in output_path.read_text(encoding="utf-8")
            _assert_dashboard_privacy(output_directory, output_path)
        finally:
            assert dialog.close()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
            assert sip.isdeleted(dialog)
            assert not output_directory.exists()


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

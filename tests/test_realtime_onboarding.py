"""Operator presentation keeps the existing monitor and event ownership paths."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QDialog, QLineEdit, QMessageBox, QPushButton

from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.ui.realtime_industrial_monitoring_dialog import RealtimeIndustrialMonitoringDialog
from metroliza.ui.window_coordinator import WindowCoordinator
from metroliza.ui.workspace_context import WorkspaceContext
from tests.test_realtime_dashboard_service import _seed_dashboard_data
from tests.test_realtime_monitoring_dialog import (
    _Signal, _poll_result, _profile, _wait_for, dashboard_dialog as _dashboard_dialog, qapp as _qapp,
)


qapp = _qapp
dashboard_dialog = _dashboard_dialog


def _ready(dialog):
    profile = _profile(IndustrialDataRepository(dialog.db_file), "line_a", "Line A")
    dialog.reload_from_database()
    dialog.cursor_column_edit.setText("event_id")
    dialog.event_time_column_edit.setText("process_timestamp")
    dialog.record_key_column_edit.setText("record_id")
    dialog.signal_columns_edit.setPlainText("cycle_time=cycle_time_s")
    dialog.save_current_source_config()
    assert profile.id in dialog.configs_by_profile_id
    return profile


def _show(dialog, qapp):
    dialog.show()
    dialog.activateWindow()
    qapp.processEvents()


def _assert_one_primary(dialog):
    assert [button for button in dialog.findChildren(QPushButton)
            if button.property("buttonRole") == "primary"] == [dialog.next_button]
    assert dialog.next_button.isDefault() == dialog._next_control.isVisibleTo(dialog)


class _ControlledWorker:
    """Own terminal delivery explicitly without a live source connection."""
    def __init__(self, **kwargs):
        self.configs = kwargs.get("configs", ())
        for name in ("update_label", "result_ready", "error_occurred", "cancelled", "finished"):
            setattr(self, name, _Signal())
        self.running = False
        self.cancel_count = 0

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancel_count += 1

    def finish(self):
        self.running = False
        self.finished.emit()


@pytest.fixture
def controlled_poll(monkeypatch):
    monkeypatch.setattr("metroliza.ui.realtime_industrial_monitoring_dialog.RealtimeMonitorPollThread",
                        _ControlledWorker)


@pytest.fixture
def owned_monitor(qapp, tmp_path):
    db_file = str(tmp_path / "owned.db")
    IndustrialDataRepository(db_file).ensure_schema()
    workspace = WorkspaceContext(database_file=db_file)
    owner = WindowCoordinator(workspace)
    owner.register_modeless("realtime", lambda context: RealtimeIndustrialMonitoringDialog(
        None, context.database_file, config_path=tmp_path / "private-sources.yaml",
    ))
    dialog = owner.open_modeless("realtime")
    qapp.processEvents()
    assert dialog.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    try:
        yield dialog, owner
    finally:
        if not sip.isdeleted(dialog):
            dialog.request_shutdown()
            for worker in (dialog.poll_thread, dialog.dashboard_thread):
                if worker is not None:
                    worker.finish()
            dialog.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert sip.isdeleted(dialog)


@pytest.mark.parametrize("source", ["none", "disabled", "incomplete"])
def test_unready_sources_route_to_setup_without_start(dashboard_dialog, source, qapp):
    dialog = dashboard_dialog
    if source != "none":
        _profile(IndustrialDataRepository(dialog.db_file), "line_a", "Line A",
                 is_enabled=source != "disabled")
        dialog.reload_from_database()
    assert not dialog.start_button.isEnabled()
    _assert_one_primary(dialog)
    assert dialog._next_control is dialog.configure_source_button
    dialog.next_button.click()
    assert dialog.workflow_tabs.currentIndex() == 1
    assert dialog.poll_thread is None and not dialog.poll_timer.isActive()
    expected = dialog.save_button if source == "incomplete" else dialog.edit_sources_button
    assert dialog._next_control is expected
    _assert_one_primary(dialog)
    _show(dialog, qapp)
    QTest.keyClick(dialog, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(dialog, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert dialog.poll_thread is None and not dialog.poll_timer.isActive()


def test_ready_start_stop_retains_owned_poll_and_observed_snapshot(dashboard_dialog, monkeypatch, qapp):
    import metroliza.ui.realtime_industrial_monitoring_dialog as module

    class Poll:
        def __init__(self, **kwargs):
            self.configs = kwargs["configs"]
            for name in ("update_label", "result_ready", "error_occurred", "cancelled", "finished"):
                setattr(self, name, _Signal())
            self.running = False
            self.cancelled_count = 0

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

        def cancel(self):
            self.cancelled_count += 1

        def finish(self):
            self.running = False
            self.finished.emit()

    monkeypatch.setattr(module, "RealtimeMonitorPollThread", Poll)
    dialog = dashboard_dialog
    monkeypatch.setattr(dialog, "_schedule_dashboard_write", lambda **kwargs: None)
    profile = _ready(dialog)
    assert dialog._next_control is dialog.start_button
    _assert_one_primary(dialog)
    assert "source access" in dialog.next_action_label.text()
    _show(dialog, qapp)
    QTest.keyClick(dialog, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    worker = dialog.poll_thread
    try:
        assert worker is not None and worker.configs[0].source_profile_id == profile.id
        assert dialog.poll_timer.isActive()
        _assert_one_primary(dialog)
        dialog.workflow_tabs.setCurrentIndex(2)
        assert dialog._next_control is dialog.stop_button  # Stop remains discoverable in review.
        _assert_one_primary(dialog)
        dialog.event_operator_edit.setFocus()
        QTest.keyClick(dialog.event_operator_edit, Qt.Key.Key_Return)
        assert worker.cancelled_count == 0 and dialog.poll_timer.isActive()
        worker.result_ready.emit((_poll_result(lag_seconds=12.5,
                                  event_time_watermark="2026-06-13T10:02:00Z"),))
        assert "max lag 12.5s" in dialog.freshness_label.text()
        assert "scheduled monitoring running" in dialog.freshness_label.text()
        worker.error_occurred.emit("synthetic source unavailable")
        assert "failed" in dialog.poll_status_label.text()
        assert "max lag 12.5s" in dialog.freshness_label.text()
        QTest.keyClick(dialog, Qt.Key.Key_S,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert worker.cancelled_count == 1
        assert dialog.poll_thread is worker and not dialog.poll_timer.isActive()
        assert not dialog.next_button.isEnabled()
        _assert_one_primary(dialog)
        assert "stopping" in dialog.freshness_label.text()
    finally:
        dialog.stop_monitoring()
        worker.finish()
    assert dialog.poll_thread is None
    assert "monitoring stopped" in dialog.freshness_label.text()
    assert "Snapshot, not live age" in dialog.freshness_label.text()
    assert dialog.request_shutdown()


@pytest.mark.parametrize("field,value", [
    ("cursor_column_edit", "record_id"),
    ("signal_columns_edit", "cycle_time=cycle_time_s\nsecond=cycle_time_s"),
    ("interval_spin", 61),
    ("display_mode_combo", "aggregated"),
    ("aggregation_methods_edit", "mean, median"),
    ("dashboard_path_field", "synthetic-changed-dashboard.html"),
])
def test_saved_setup_advances_to_monitor_and_current_edits_return_to_save(
    dashboard_dialog, qapp, field, value,
):
    dialog = dashboard_dialog
    _ready(dialog)
    _show(dialog, qapp)
    QTest.keyClick(dialog, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert dialog.workflow_tabs.currentIndex() == 1
    assert dialog._next_control is dialog.monitor_view_button
    assert "Current setup saved" in dialog.next_action_label.text()
    _assert_one_primary(dialog)
    saved = dict(dialog.configs_by_profile_id)
    control = getattr(dialog, field)
    if field == "signal_columns_edit":
        control.setPlainText(value)
    elif field == "interval_spin":
        control.setValue(value)
    elif field == "display_mode_combo":
        control.setCurrentText(value)
    else:
        control.setText(value)
    assert dialog._next_control is dialog.save_button  # Live signal, no tab switch/cache.
    assert dialog.configs_by_profile_id == saved
    _assert_one_primary(dialog)
    QTest.keyClick(dialog, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert dialog.workflow_tabs.currentIndex() == 1  # Ctrl+S retains Save semantics.
    assert dialog._next_control is dialog.monitor_view_button
    assert dialog.configs_by_profile_id != saved
    QTest.keyClick(dialog, Qt.Key.Key_Return)  # Saved Setup default navigates only, never starts.
    assert dialog.workflow_tabs.currentIndex() == 0
    assert dialog.poll_thread is None and not dialog.poll_timer.isActive()
    assert dialog._next_control is dialog.start_button
    QTest.keyClick(dialog, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    dialog.cursor_column_edit.setText("event_id" if field == "cursor_column_edit" else "event_id ")
    if field != "cursor_column_edit":
        assert dialog._next_control is dialog.monitor_view_button  # Normalized whitespace is not dirty.
    QTest.keyClick(dialog, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    assert dialog.workflow_tabs.currentIndex() == 0


def test_saved_setup_navigation_does_not_enable_unchecked_or_missing_source(dashboard_dialog, qapp):
    dialog = dashboard_dialog
    profile = _ready(dialog)
    saved = dialog.configs_by_profile_id[profile.id]
    persisted = dialog.repository.upsert_config(replace(
        saved, allowed_lateness_seconds=5.0, source_timezone="Europe/Warsaw",
    ))
    dialog.reload_from_database()
    assert dialog.configs_by_profile_id[profile.id] == persisted
    dialog.source_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    dialog.workflow_tabs.setCurrentIndex(1)
    assert dialog._next_control is dialog.monitor_view_button
    assert dialog.configs_by_profile_id[profile.id] == persisted  # Hidden runtime values are untouched.
    assert not dialog.start_button.isEnabled()
    assert "requires checked enabled sources" in dialog.next_action_label.text()
    dialog.next_button.click()
    _show(dialog, qapp)
    QTest.keyClick(dialog, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert dialog.poll_thread is None and not dialog.poll_timer.isActive()
    _profile(IndustrialDataRepository(dialog.db_file), "missing", "Missing setup")
    dialog.reload_from_database()
    for index in range(dialog.source_list.count()):
        dialog.source_list.item(index).setCheckState(Qt.CheckState.Checked)
    dialog.workflow_tabs.setCurrentIndex(1)
    assert dialog._next_control is dialog.monitor_view_button
    assert not dialog.start_button.isEnabled()
    dialog.next_button.click()
    QTest.keyClick(dialog, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert dialog.poll_thread is None and not dialog.poll_timer.isActive()


@pytest.mark.parametrize("valid", [True, False])
def test_monitor_start_advertises_and_uses_current_checked_edits(
    dashboard_dialog, controlled_poll, monkeypatch, qapp, valid,
):
    dialog = dashboard_dialog
    profile = _ready(dialog)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    _show(dialog, qapp)
    QTest.keyClick(dialog, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    dialog.cursor_column_edit.setFocus()
    QTest.keyClick(dialog.cursor_column_edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    if valid:
        QTest.keyClicks(dialog.cursor_column_edit, "record_id")
    else:
        QTest.keyClick(dialog.cursor_column_edit, Qt.Key.Key_Backspace)
    assert dialog._next_control is dialog.save_button
    QTest.keyClick(dialog, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    message = dialog.next_action_label.text()
    assert dialog._next_control is dialog.start_button  # Existing enabled/preflight contract.
    if valid:
        assert "validates and saves the current checked source setup" in message
    else:
        assert "invalid" in message and "without polling" in message
        assert "saved" not in message and "ready" not in message
    QTest.keyClick(dialog, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    worker = dialog.poll_thread
    try:
        saved = {config.source_profile_id: config for config in dialog.repository.list_configs()}
        if valid:
            assert worker is not None and dialog.poll_timer.isActive()
            assert worker.configs[0].cursor_column == saved[profile.id].cursor_column == "record_id"
            assert not warnings
        else:
            assert worker is None and not dialog.poll_timer.isActive()
            assert saved[profile.id].cursor_column == "event_id" and len(warnings) == 1
    finally:
        if worker is not None:
            dialog.stop_monitoring()
            worker.finish()


def test_monitor_start_advertises_unchecked_edits_are_not_applied(
    dashboard_dialog, controlled_poll, qapp,
):
    dialog = dashboard_dialog
    first = _ready(dialog)
    second = _profile(IndustrialDataRepository(dialog.db_file), "line_b", "Line B")
    dialog.repository.upsert_config(replace(
        dialog.configs_by_profile_id[first.id], source_profile_id=second.id,
        stream_key="line_b", id=None, created_at=None, updated_at=None,
    ))
    dialog.reload_from_database()
    for index in range(dialog.source_list.count()):
        item = dialog.source_list.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == first.id:
            item.setCheckState(Qt.CheckState.Unchecked)
            dialog.source_list.setCurrentItem(item)
    _show(dialog, qapp)
    QTest.keyClick(dialog, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    dialog.cursor_column_edit.setFocus()
    QTest.keyClick(dialog.cursor_column_edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(dialog.cursor_column_edit, "record_id")
    QTest.keyClick(dialog, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    assert "Current unchecked source edits are not applied" in dialog.next_action_label.text()
    QTest.keyClick(dialog, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    worker = dialog.poll_thread
    try:
        assert [config.source_profile_id for config in worker.configs] == [second.id]
        assert worker.configs[0].cursor_column == "event_id"
        assert all(config.cursor_column == "event_id" for config in dialog.repository.list_configs())
    finally:
        dialog.stop_monitoring()
        worker.finish()


def test_escape_owned_poll_defers_coordinator_destruction_until_terminal(
    owned_monitor, controlled_poll, qapp,
):
    dialog, owner = owned_monitor
    _ready(dialog)
    _show(dialog, qapp)
    QTest.keyClick(dialog, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    worker = dialog.poll_thread
    assert worker is not None and worker.isRunning()
    QTest.keyClick(dialog, Qt.Key.Key_Escape, Qt.KeyboardModifier.ControlModifier)
    repeat = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier, "", True)
    QCoreApplication.sendEvent(dialog, repeat)
    assert worker.cancel_count == 0 and dialog.poll_timer.isActive()
    closed = QSignalSpy(owner.window_closed)
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert worker.cancel_count == 1 and worker.isRunning()
    assert dialog.poll_thread is worker and dialog.is_close_deferred()
    assert dialog.isVisible() and not sip.isdeleted(dialog)
    assert owner.open_window_ids == ("realtime",) and len(closed) == 0
    worker.finish()
    _wait_for(lambda: sip.isdeleted(dialog), "guarded Esc destruction after poll terminal")
    assert owner.open_window_ids == () and len(closed) == 1


def test_escape_owned_dashboard_retains_cleanup_refusal_then_retries(
    owned_monitor, monkeypatch,
):
    dialog, owner = owned_monitor
    monkeypatch.setattr("metroliza.ui.realtime_industrial_monitoring_dialog.RealtimeDashboardWriterThread",
                        _ControlledWorker)
    owned = dialog._dashboard_temp_dir
    directory = Path(owned.name)
    attempts = []

    def cleanup():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("synthetic cleanup refusal")
        owned.cleanup()

    retained = SimpleNamespace(name=owned.name, cleanup=cleanup)
    monkeypatch.setattr(dialog, "_dashboard_temp_dir", retained)
    dialog._on_poll_results((_poll_result(),))
    _wait_for(lambda: dialog.dashboard_thread is not None, "controlled dashboard worker")
    worker = dialog.dashboard_thread
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not sip.isdeleted(dialog) and dialog.dashboard_thread is worker
    assert dialog.is_close_deferred() and owner.open_window_ids == ("realtime",)
    worker.finish()
    assert attempts == [True] and directory.is_dir()
    assert dialog.dashboard_cleanup_retry_required() and not dialog.is_close_deferred()
    assert dialog.isVisible() and not sip.isdeleted(dialog)
    QTest.keyPress(dialog, Qt.Key.Key_Escape)
    assert attempts == [True, True] and not directory.exists()
    assert not dialog.isVisible() and dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.dashboard_thread is None and dialog.poll_thread is None
    assert dialog._dashboard_temp_dir is None and not dialog.is_close_deferred()
    assert owner.open_window_ids == ("realtime",)
    # This close posted DeferredDelete before a nested wait loop could start.
    # Deliver the existing event only after all safe-close conditions hold.
    QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(dialog)
    assert owner.open_window_ids == ()


def test_escape_owned_source_editor_refusal_then_safe_idle_close(owned_monitor, monkeypatch, qapp):
    dialog, owner = owned_monitor
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    consent = []

    def question(*args, **kwargs):
        answer = next(answers)
        consent.append(answer)
        return answer

    monkeypatch.setattr(QMessageBox, "question", question)
    dialog.open_source_profiles_dialog()
    qapp.processEvents()
    source = dialog.source_window
    source.source_name_edit.setText("Unsaved synthetic source")
    dialog.activateWindow()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not sip.isdeleted(dialog) and dialog.isVisible() and source.isVisible()
    assert not dialog._closing and dialog.source_window is source
    assert owner.open_window_ids == ("realtime",)
    QTest.keyPress(dialog, Qt.Key.Key_Escape)
    assert consent == [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    assert not dialog.isVisible() and dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.source_window is None and not dialog._workers_own_context()
    assert dialog._dashboard_temp_dir is None and not dialog.is_close_deferred()
    assert owner.open_window_ids == ("realtime",)
    QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(dialog)
    assert owner.open_window_ids == ()


@pytest.mark.parametrize("key,status", [(Qt.Key.Key_A, "acknowledged"),
                                        (Qt.Key.Key_E, "resolved"),
                                        (Qt.Key.Key_Q, "false_positive")])
def test_review_commands_update_only_selected_persisted_event(dashboard_dialog, qapp, key, status):
    dialog = dashboard_dialog
    seeded = _seed_dashboard_data(dialog.db_file)
    _show(dialog, qapp)
    QTest.keyClick(dialog, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert dialog.workflow_tabs.currentIndex() == 2
    dialog.event_review_table.selectRow(0)
    selected = dialog._selected_event_id()
    assert selected in seeded["event_ids"]
    modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    QTest.keyClick(dialog, key, modifiers)
    assert "required" in dialog.event_review_status_label.text()
    assert all(e.status == "open" for e in AnomalyEventRepository(dialog.db_file).list_events())
    dialog.event_operator_edit.setText("synthetic-operator")
    dialog.event_comment_edit.setText("reviewed synthetic event")
    QTest.keyClick(dialog, key, modifiers)
    events = AnomalyEventRepository(dialog.db_file).list_events()
    assert {e.id for e in events if e.status == status} == {selected}
    assert sum(e.status == "open" for e in events) == 2


def test_shortcuts_preserve_text_altgr_and_modal_boundary(dashboard_dialog, qapp):
    dialog = dashboard_dialog
    _show(dialog, qapp)
    QTest.keyClick(dialog, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert dialog.workflow_tabs.currentIndex() == 1
    editor = dialog.cursor_column_edit
    editor.setText("editable cursor")
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert editor.selectedText() == "editable cursor"
    QTest.keyClick(editor, Qt.Key.Key_E,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert dialog.workflow_tabs.currentIndex() == 1
    child = QDialog(dialog)
    child.setModal(True)
    child_editor = QLineEdit(child)
    child.show()
    child.activateWindow()
    child_editor.setFocus()
    qapp.processEvents()
    QTest.keyClick(child_editor, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    assert dialog.workflow_tabs.currentIndex() == 1
    QTest.keyClick(child_editor, Qt.Key.Key_Escape)
    assert not child.isVisible() and dialog.isVisible()
    assert "Ctrl+D" in dialog.configure_source_button.text()


@pytest.mark.parametrize("tab", [0, 1, 2])
def test_small_window_keeps_state_and_next_action_visible(dashboard_dialog, qapp, tab, monkeypatch):
    from metroliza.ui import ui_foundation

    dialog = dashboard_dialog
    monkeypatch.setattr(ui_foundation, "_available_window_size", lambda *_args: (760, 620))
    ui_foundation.configure_window_size(dialog, minimum=(900, 620), initial=(1120, 760))
    dialog.workflow_tabs.setCurrentIndex(tab)
    _show(dialog, qapp)
    print(f"Realtime geometry screen={qapp.primaryScreen().availableGeometry()} "
          f"dpr={dialog.devicePixelRatioF()} dialog={dialog.size()}")
    controls = [dialog.freshness_label, dialog.next_action_label, dialog.next_button,
                dialog.configure_source_button, dialog.event_review_button, dialog.close_button]
    if tab == 2:
        controls += [dialog.event_operator_edit, dialog.event_comment_edit,
                     dialog.acknowledge_event_button, dialog.resolve_event_button,
                     dialog.false_positive_event_button]
    rectangles = []
    for control in controls:
        rect = control.rect().translated(control.mapTo(dialog, QPoint()))
        assert control.isVisibleTo(dialog) and dialog.rect().contains(rect)
        rectangles.append(rect)
    assert all(not a.intersects(b) for i, a in enumerate(rectangles) for b in rectangles[i + 1:])
    assert dialog.width() <= 760 and dialog.height() <= 620

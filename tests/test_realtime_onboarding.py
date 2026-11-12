"""Operator presentation keeps the existing monitor and event ownership paths."""
import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialog, QLineEdit

from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from tests.test_realtime_dashboard_service import _seed_dashboard_data
from tests.test_realtime_monitoring_dialog import (
    _Signal, _poll_result, _profile, dashboard_dialog as _dashboard_dialog, qapp as _qapp,
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


@pytest.mark.parametrize("source", ["none", "disabled", "incomplete"])
def test_unready_sources_route_to_setup_without_start(dashboard_dialog, source, qapp):
    dialog = dashboard_dialog
    if source != "none":
        _profile(IndustrialDataRepository(dialog.db_file), "line_a", "Line A",
                 is_enabled=source != "disabled")
        dialog.reload_from_database()
    assert not dialog.start_button.isEnabled()
    assert dialog._next_control is dialog.configure_source_button
    dialog.next_button.click()
    assert dialog.workflow_tabs.currentIndex() == 1
    assert dialog.poll_thread is None and not dialog.poll_timer.isActive()
    expected = dialog.save_button if source == "incomplete" else dialog.edit_sources_button
    assert dialog._next_control is expected
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
    assert "source access" in dialog.next_action_label.text()
    _show(dialog, qapp)
    QTest.keyClick(dialog, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    worker = dialog.poll_thread
    try:
        assert worker is not None and worker.configs[0].source_profile_id == profile.id
        assert dialog.poll_timer.isActive()
        dialog.workflow_tabs.setCurrentIndex(2)
        assert dialog._next_control is dialog.stop_button  # Stop remains discoverable in review.
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
        assert "stopping" in dialog.freshness_label.text()
    finally:
        dialog.stop_monitoring()
        worker.finish()
    assert dialog.poll_thread is None
    assert "monitoring stopped" in dialog.freshness_label.text()
    assert "Snapshot, not live age" in dialog.freshness_label.text()
    assert dialog.request_shutdown()


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
    child.close()
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

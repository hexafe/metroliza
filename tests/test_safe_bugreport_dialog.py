from PyQt6.QtGui import QGuiApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QWidget
from threading import Event
import time
from types import SimpleNamespace

from metroliza.shared.safe_bugreport import (
    BugReportAction,
    BugReportCategory,
    SafeBugReportRecorder,
    BugReportSnapshot,
    PreviousSessionState,
)
import metroliza.ui.safe_bugreport_dialog as dialog_module
import metroliza.shared.safe_bugreport as report_module
from metroliza.ui.safe_bugreport_dialog import SafeBugReportDialog


def test_safe_bug_report_preview_and_copy_contains_only_fixed_schema(qapplication_session, monkeypatch):
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.CSV_OPENED)
    recorder.record(BugReportAction.FILTER_APPLIED)
    monkeypatch.setattr(dialog_module, "recorder", recorder)
    dialog = SafeBugReportDialog()
    try:
        assert dialog.category_combo.count() == len(BugReportCategory)
        dialog.category_combo.setCurrentIndex(0)
        assert "wrong_output" in dialog.preview.toPlainText()
        assert "csv_opened" in dialog.preview.toPlainText()
        assert "filter_applied" in dialog.preview.toPlainText()
        assert "input data was not captured" in dialog.preview.toPlainText().lower()

        dialog.copy_report()
        clipboard = QGuiApplication.clipboard()
        assert clipboard.text() == dialog.preview.toPlainText()
        assert "Copied locally" in dialog.status_label.text()
    finally:
        dialog.close()


def test_safe_bug_report_fails_closed_when_snapshot_cannot_be_built(qapplication_session, monkeypatch):
    dialog = SafeBugReportDialog()
    try:
        monkeypatch.setattr(dialog, "_report_text", lambda: None)
        dialog._refresh_preview()
        assert dialog.preview.toPlainText() == ""
        assert not dialog.copy_button.isEnabled()
        dialog.copy_report()
        assert "unavailable" in dialog.status_label.text().lower()
    finally:
        dialog.close()


def test_start_history_offers_previous_activity_without_calling_it_a_crash(
    qapplication_session, monkeypatch, tmp_path,
):
    scheduled = []
    connected = []

    class Recorder:
        def configure_history(self, root):
            self.root = root
            return True

        def snapshot(self):
            return BugReportSnapshot((), False, PreviousSessionState.AVAILABLE.value)

        def record(self, action):
            self.action = action
            return True

        def close_history(self, timeout):
            return True

    class Signal:
        def connect(self, callback):
            connected.append(callback)

    class App:
        aboutToQuit = Signal()

    class Store:
        root = tmp_path / "diagnostics"

    recorder = Recorder()
    monkeypatch.setattr(dialog_module, "recorder", recorder)
    monkeypatch.setattr(dialog_module, "IncidentStore", Store)
    monkeypatch.setattr(dialog_module.QTimer, "singleShot", lambda delay, callback: scheduled.append(callback))
    parent = QWidget()
    parent.show()
    try:
        dialog_module.start_local_bugreport_history(parent, App())
        assert recorder.root == tmp_path / "safe-bugreport-activity"
        assert recorder.action is BugReportAction.APP_OPENED
        assert len(connected) == 1
        scheduled.pop()()
        notice = parent._safe_bugreport_history_notice
        assert notice.isVisible()
        assert "does not indicate a crash" in notice.informativeText()
        notice.done(QMessageBox.StandardButton.No)
    finally:
        parent.close()


def test_delayed_history_write_does_not_block_gui_events(qapplication_session, monkeypatch, tmp_path):
    entered, release = Event(), Event()
    original = report_module.LocalBugReportHistoryStore.append_locked

    def delayed(store, event, *, max_events, events_lost=False):
        entered.set()
        if not release.wait(5):
            return False
        return original(store, event, max_events=max_events, events_lost=events_lost)

    monkeypatch.setattr(report_module.LocalBugReportHistoryStore, "append_locked", delayed)
    recorder = SafeBugReportRecorder()
    assert recorder.configure_history(tmp_path / "history")
    assert recorder.flush(3)
    try:
        assert recorder.record(BugReportAction.CSV_OPENED)
        assert entered.wait(3)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        started = time.monotonic()
        assert recorder.record(BugReportAction.FILTER_APPLIED)
        qapplication_session.processEvents()
        assert heartbeat == [True]
        assert time.monotonic() - started < 1
        assert not release.is_set()
    finally:
        release.set()
        assert recorder.close_history(5)


def test_clear_history_confirms_only_after_writer_completion(qapplication_session, monkeypatch):
    callbacks = []

    class Recorder:
        state = None

        def clear_history(self):
            self.state = "pending"
            return True

        def snapshot(self):
            return SimpleNamespace(clear_state=self.state)

    recorder = Recorder()
    monkeypatch.setattr(dialog_module, "recorder", recorder)
    monkeypatch.setattr(dialog_module.QTimer, "singleShot", lambda delay, callback: callbacks.append(callback))
    dialog = SafeBugReportDialog()
    monkeypatch.setattr(dialog, "_report_text", lambda: "safe report")
    callbacks.clear()
    try:
        dialog.clear_button.click()
        assert not dialog.clear_button.isEnabled()
        assert not dialog.copy_button.isEnabled()
        assert "Clearing" in dialog.status_label.text()
        dialog._poll_history_clear(200)
        assert len(callbacks) == 2  # Slow storage must not stop the completion check.
        recorder.state = "complete"
        callbacks.pop()()
        assert dialog.clear_button.isEnabled()
        assert dialog.copy_button.isEnabled()
        assert "cleared" in dialog.status_label.text()
    finally:
        dialog.close()


def test_immediately_completed_history_clear_is_acknowledged(qapplication_session, monkeypatch):
    callbacks = []

    class Recorder:
        state = None

        def clear_history(self):
            self.state = "complete"
            return True

        def snapshot(self):
            return SimpleNamespace(clear_state=self.state)

    recorder = Recorder()
    monkeypatch.setattr(dialog_module, "recorder", recorder)
    monkeypatch.setattr(dialog_module.QTimer, "singleShot", lambda delay, callback: callbacks.append(callback))
    monkeypatch.setattr(dialog_module, "build_bug_report_markdown", lambda *_args, **_kwargs: "safe report")
    dialog = SafeBugReportDialog()
    callbacks.clear()
    try:
        dialog.clear_history()
        assert not dialog.clear_button.isEnabled()
        assert len(callbacks) == 1
        callbacks.pop()()
        assert dialog.clear_button.isEnabled()
        assert "cleared" in dialog.status_label.text()
    finally:
        dialog.close()


def test_reject_stops_polling_pending_history_clear(qapplication_session, monkeypatch):
    callbacks = []

    class Recorder:
        def clear_history(self):
            return True

        def snapshot(self):
            return SimpleNamespace(clear_state="pending")

    monkeypatch.setattr(dialog_module, "recorder", Recorder())
    monkeypatch.setattr(dialog_module.QTimer, "singleShot", lambda delay, callback: callbacks.append(callback))
    dialog = SafeBugReportDialog()
    try:
        assert dialog._clear_polling
        dialog.reject()
        count = len(callbacks)
        callbacks[-1]()
        assert len(callbacks) == count
        assert not dialog._clear_polling
    finally:
        dialog.close()


def test_second_dialog_cannot_copy_preview_while_history_clear_pending(qapplication_session, monkeypatch):
    callbacks = []

    class Recorder:
        state = None

        def clear_history(self):
            self.state = "pending"
            return True

        def snapshot(self):
            return SimpleNamespace(clear_state=self.state)

    recorder = Recorder()
    monkeypatch.setattr(dialog_module, "recorder", recorder)
    monkeypatch.setattr(dialog_module, "build_bug_report_markdown", lambda *_args, **_kwargs: "safe preview")
    monkeypatch.setattr(dialog_module.QTimer, "singleShot", lambda delay, callback: callbacks.append(callback))
    first = SafeBugReportDialog()
    second = SafeBugReportDialog()
    clipboard = QGuiApplication.clipboard()
    clipboard.setText("existing clipboard")
    try:
        first.clear_history()
        second.copy_report()
        assert clipboard.text() == "existing clipboard"
        assert not second.copy_button.isEnabled()
        assert "Clearing" in second.status_label.text()
        recorder.state = "complete"
        for callback in tuple(callbacks):
            callback()
        assert second.copy_button.isEnabled()
        second.copy_report()
        assert clipboard.text() == "safe preview"
    finally:
        first.close()
        second.close()


def test_changed_activity_requires_reviewing_refreshed_preview(qapplication_session, monkeypatch):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(dialog_module, "recorder", recorder)
    dialog = SafeBugReportDialog()
    clipboard = QGuiApplication.clipboard()
    clipboard.setText("existing clipboard")
    try:
        recorder.record(BugReportAction.CSV_OPENED)
        dialog.copy_report()
        assert clipboard.text() == "existing clipboard"
        assert "Review the updated report" in dialog.status_label.text()
        assert "csv_opened" in dialog.preview.toPlainText()
        dialog.copy_report()
        assert clipboard.text() == dialog.preview.toPlainText()
    finally:
        dialog.close()

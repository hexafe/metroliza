import hashlib
import json
import os
from pathlib import Path
import zipfile

import pytest

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
from metroliza.shared import diagnostic_store
from metroliza.shared.safe_bugreport_context import SafeBugReportContextSnapshot
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
        assert not dialog.save_button.isEnabled()
        dialog.copy_report()
        assert "unavailable" in dialog.status_label.text().lower()
    finally:
        dialog.close()


def test_save_diagnostic_zip_preserves_reviewed_bytes(qapplication_session, monkeypatch, tmp_path):
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.CSV_OPENED)
    monkeypatch.setattr(dialog_module, "recorder", recorder)
    destination = tmp_path / "diagnostic.zip"
    choices = iter(("", str(destination.with_suffix("")), str(destination)))
    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", lambda *_a, **_kw: (next(choices), ""))
    dialog = SafeBugReportDialog()
    try:
        shown = dialog.preview.toPlainText().encode("utf-8")
        recorder.record(BugReportAction.FILTER_APPLIED)
        dialog.save_button.click()
        assert list(tmp_path.iterdir()) == []

        dialog.save_button.click()
        assert "saved" in dialog.status_label.text()
        with zipfile.ZipFile(destination) as archive:
            assert archive.namelist() == ["report.md", "manifest.json"]
            assert archive.read("report.md") == shown
            assert json.loads(archive.read("manifest.json")) == {
                "schema_version": 1,
                "bundle_format": "metroliza_safe_bug_report_v1",
                "files": [{"name": "report.md", "size_bytes": len(shown), "sha256": hashlib.sha256(shown).hexdigest()}],
            }

        original_bytes = destination.read_bytes()
        dialog.refresh_snapshot()
        assert b"filter_applied" in dialog.preview.toPlainText().encode("utf-8")
        dialog.save_button.click()
        assert "already exists" in dialog.status_label.text()
        assert destination.read_bytes() == original_bytes
        assert list(tmp_path.iterdir()) == [destination]
    finally:
        dialog.close()


def test_changing_preview_while_save_picker_is_open_requires_review(
    qapplication_session, monkeypatch, tmp_path,
):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(dialog_module, "recorder", recorder)
    dialog = SafeBugReportDialog()

    def change_preview(*_a, **_kw):
        recorder.record(BugReportAction.CSV_OPENED)
        dialog.refresh_snapshot()
        return str(tmp_path / "diagnostic.zip"), ""

    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", change_preview)
    try:
        dialog.save_button.click()
        assert "preview changed" in dialog.status_label.text()
        assert list(tmp_path.iterdir()) == []
    finally:
        dialog.close()


def test_clearing_history_while_save_picker_is_open_requires_review(
    qapplication_session, monkeypatch, tmp_path,
):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(dialog_module, "recorder", recorder)
    dialog = SafeBugReportDialog()

    def clear_during_picker(*_a, **_kw):
        monkeypatch.setattr(recorder, "history_generation", lambda: 1)
        return str(tmp_path / "diagnostic.zip"), ""

    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", clear_during_picker)
    try:
        original = dialog.preview.toPlainText()
        dialog.save_button.click()
        assert "History was cleared" in dialog.status_label.text()
        assert dialog.preview.toPlainText() == original
        assert list(tmp_path.iterdir()) == []
    finally:
        dialog.close()


@pytest.mark.parametrize("colliding_file", [False, True])
def test_diagnostic_zip_failure_cleans_staging_and_preserves_foreign_file(
    qapplication_session, monkeypatch, tmp_path, colliding_file,
):
    dialog = SafeBugReportDialog()
    try:
        report = dialog.preview.toPlainText()
    finally:
        dialog.close()
    destination = tmp_path / "diagnostic.zip"
    real_commit = diagnostic_store._commit_stage_no_replace

    def fail_commit(stage, target):
        assert stage.is_file()
        if colliding_file:
            target.write_bytes(b"unrelated")
            real_commit(stage, target)
        raise OSError("simulated failure")

    monkeypatch.setattr(diagnostic_store, "_commit_stage_no_replace", fail_commit)
    status = diagnostic_store.export_safe_bug_report(report, destination)
    if colliding_file:
        assert status is diagnostic_store.StoreStatus.DESTINATION_EXISTS
        assert destination.read_bytes() == b"unrelated"
        assert list(tmp_path.iterdir()) == [destination]
    else:
        assert status is diagnostic_store.StoreStatus.IO_FAILED
        assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("field", ["password", "sql", "customer", "measurement", "environment"])
def test_diagnostic_zip_rejects_non_schema_preview_values(qapplication_session, tmp_path, field):
    dialog = SafeBugReportDialog()
    try:
        report = dialog.preview.toPlainText().replace(
            'json\n{\n', f'json\n{{\n  "{field}": {{"nested": "synthetic confidential text"}},\n', 1,
        )
    finally:
        dialog.close()
    assert "synthetic confidential text" in report
    assert diagnostic_store.export_safe_bug_report(report, tmp_path / "diagnostic.zip") is (
        diagnostic_store.StoreStatus.INVALID
    )
    assert list(tmp_path.iterdir()) == []


def test_diagnostic_zip_does_not_delete_target_after_verification_failure(
    qapplication_session, monkeypatch, tmp_path,
):
    dialog = SafeBugReportDialog()
    destination = tmp_path / "diagnostic.zip"
    read_bytes = diagnostic_store._safe_file_bytes

    def fail_readback(path, maximum):
        if path == destination:
            raise OSError("simulated read-back failure")
        return read_bytes(path, maximum)

    monkeypatch.setattr(diagnostic_store, "_safe_file_bytes", fail_readback)
    try:
        report = dialog.preview.toPlainText()
        result = diagnostic_store.export_safe_bug_report(report, destination)
        assert result is diagnostic_store.StoreStatus.PUBLISH_INCOMPLETE
        assert list(tmp_path.iterdir()) == [destination]
        with zipfile.ZipFile(destination) as bundle:
            assert bundle.read("report.md") == report.encode("utf-8")
    finally:
        dialog.close()


@pytest.mark.skipif(os.name == "nt", reason="Windows moves rather than links the staging name")
def test_diagnostic_zip_reports_staging_cleanup_failure(
    qapplication_session, monkeypatch, tmp_path,
):
    dialog = SafeBugReportDialog()
    destination = tmp_path / "diagnostic.zip"
    unlink = Path.unlink

    def fail_stage_cleanup(path, *args, **kwargs):
        if path.parent == tmp_path and path.name.startswith(".stage-"):
            raise PermissionError("simulated cleanup failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_stage_cleanup)
    try:
        report = dialog.preview.toPlainText()
        result = diagnostic_store.export_safe_bug_report(report, destination)
        assert result is diagnostic_store.StoreStatus.PUBLISH_INCOMPLETE
        assert destination.stat().st_nlink == 2
        for stage in tmp_path.glob(".stage-*.tmp"):
            unlink(stage)
        with zipfile.ZipFile(destination) as bundle:
            assert bundle.read("report.md") == report.encode("utf-8")
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

        def report_snapshot(self):
            return BugReportSnapshot((), False), SafeBugReportContextSnapshot()

        def history_generation(self):
            return 0

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


def test_changed_activity_is_frozen_until_explicit_refresh(qapplication_session, monkeypatch):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(dialog_module, "recorder", recorder)
    dialog = SafeBugReportDialog()
    clipboard = QGuiApplication.clipboard()
    clipboard.setText("existing clipboard")
    try:
        original_preview = dialog.preview.toPlainText()
        recorder.record(BugReportAction.CSV_OPENED)
        dialog.copy_report()
        assert clipboard.text() == original_preview
        assert "csv_opened" not in original_preview
        dialog.refresh_snapshot()
        assert "csv_opened" in dialog.preview.toPlainText()
        dialog.copy_report()
        assert clipboard.text() == dialog.preview.toPlainText()
    finally:
        dialog.close()

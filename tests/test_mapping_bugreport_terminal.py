from __future__ import annotations

import json
import threading
import time

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QObject

from metroliza.shared.safe_bugreport import BugReportAction, SafeBugReportRecorder
from metroliza.ui import characteristic_mapping_dialog as mapping


def _wait_for_thread(thread, qapplication_session):
    deadline = time.monotonic() + 5
    while thread.isRunning() and time.monotonic() < deadline:
        qapplication_session.processEvents()
        thread.wait(5)
    qapplication_session.processEvents()
    assert not thread.isRunning(), "mapping worker did not finish"


def _actions(recorder):
    return [event.action for event in recorder.snapshot().events]


def test_export_close_during_persistent_write_records_worker_success(
    monkeypatch, tmp_path, qapplication_session
):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(mapping, "_bugreport_recorder", recorder)
    entered, release = threading.Event(), threading.Event()
    output = tmp_path / "CONFIDENTIAL-path-export.csv"
    confidential = "CONFIDENTIAL-sheet-value"

    def persist(_db_file, filename):
        entered.set()
        assert release.wait(3)
        with open(filename, "w", encoding="utf-8") as stream:
            stream.write(confidential)
        return 1

    monkeypatch.setattr(mapping, "_DEFAULT_ALIAS_SCHEMA", lambda _path: None)
    monkeypatch.setattr(mapping, "_DEFAULT_ALIAS_EXPORT", persist)
    mapping._record_mapping_action(BugReportAction.WORKFLOW_MAPPING_EXPORT_STARTED)
    worker = mapping._AliasCsvThread("export", "CONFIDENTIAL-db-path", str(output))
    worker.start()
    assert entered.wait(2)

    # Closing the owner discards result delivery; the already-started write runs on.
    worker.cancel_review()
    release.set()
    _wait_for_thread(worker, qapplication_session)

    assert output.read_text(encoding="utf-8") == confidential
    assert _actions(recorder) == [
        BugReportAction.WORKFLOW_MAPPING_EXPORT_STARTED,
        BugReportAction.WORKFLOW_MAPPING_EXPORT_COMPLETED,
    ]
    serialized = json.dumps([event.__dict__ if hasattr(event, "__dict__") else str(event)
                             for event in recorder.snapshot().events])
    assert confidential not in serialized
    assert str(output) not in serialized
    assert "CONFIDENTIAL-db-path" not in serialized


def test_export_failure_after_close_records_failure_without_exception_data(
    monkeypatch, qapplication_session
):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(mapping, "_bugreport_recorder", recorder)
    entered, release = threading.Event(), threading.Event()

    def fail_after_close(_db_file, _filename):
        entered.set()
        assert release.wait(3)
        raise RuntimeError("CONFIDENTIAL-path and sheet value")

    monkeypatch.setattr(mapping, "_DEFAULT_ALIAS_SCHEMA", lambda _path: None)
    monkeypatch.setattr(mapping, "_DEFAULT_ALIAS_EXPORT", fail_after_close)
    mapping._record_mapping_action(BugReportAction.WORKFLOW_MAPPING_EXPORT_STARTED)
    worker = mapping._AliasCsvThread("export", "CONFIDENTIAL-db", "CONFIDENTIAL-output")
    worker.start()
    assert entered.wait(2)
    worker.cancel_review()
    release.set()
    _wait_for_thread(worker, qapplication_session)

    assert _actions(recorder) == [
        BugReportAction.WORKFLOW_MAPPING_EXPORT_STARTED,
        BugReportAction.WORKFLOW_MAPPING_EXPORT_FAILED,
    ]
    assert "CONFIDENTIAL" not in repr(recorder.snapshot().events)


def test_changed_database_drops_ui_delivery_without_reclassifying_worker_result(
    monkeypatch, tmp_path, qapplication_session
):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(mapping, "_bugreport_recorder", recorder)
    monkeypatch.setattr(mapping, "_DEFAULT_ALIAS_SCHEMA", lambda _path: None)
    monkeypatch.setattr(mapping, "_DEFAULT_ALIAS_EXPORT", lambda *_args: 3)
    mapping._record_mapping_action(BugReportAction.WORKFLOW_MAPPING_EXPORT_STARTED)
    worker = mapping._AliasCsvThread("export", "CONFIDENTIAL-old-db", "CONFIDENTIAL-file")
    worker.start()
    _wait_for_thread(worker, qapplication_session)

    owner = mapping.CharacteristicMappingDialog(db_file="")
    try:
        owner.db_file = "CONFIDENTIAL-new-db"
        owner._alias_csv_thread = worker
        monkeypatch.setattr(owner, "_release_alias_csv", lambda: None)
        monkeypatch.setattr(owner, "_sync_selection_actions", lambda: None)
        monkeypatch.setattr(owner, "_sync_warning_labels", lambda: None)
        owner._finish_alias_csv(worker)
        assert _actions(recorder) == [
            BugReportAction.WORKFLOW_MAPPING_EXPORT_STARTED,
            BugReportAction.WORKFLOW_MAPPING_EXPORT_COMPLETED,
        ]
        assert "CONFIDENTIAL" not in repr(recorder.snapshot().events)
    finally:
        owner.close()


def test_owner_destruction_during_apply_keeps_worker_terminal_event(
    monkeypatch, qapplication_session
):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(mapping, "_bugreport_recorder", recorder)
    entered, release = threading.Event(), threading.Event()

    def persist(_db_file, _filename):
        entered.set()
        assert release.wait(3)
        return 2

    monkeypatch.setattr(mapping, "_DEFAULT_ALIAS_SCHEMA", lambda _path: None)
    monkeypatch.setattr(mapping, "_DEFAULT_ALIAS_EXPORT", persist)
    mapping._record_mapping_action(BugReportAction.WORKFLOW_MAPPING_EXPORT_STARTED)
    worker = mapping._AliasCsvThread("export", "CONFIDENTIAL-db", "CONFIDENTIAL-file")
    owner = QObject()
    destroyed = threading.Event()
    owner.destroyed.connect(worker.cancel_review)
    owner.destroyed.connect(lambda: destroyed.set())
    worker.start()
    assert entered.wait(2)

    owner.deleteLater()
    QCoreApplication.sendPostedEvents(owner, QEvent.Type.DeferredDelete)
    qapplication_session.processEvents()
    assert destroyed.is_set()
    release.set()
    _wait_for_thread(worker, qapplication_session)

    assert _actions(recorder) == [
        BugReportAction.WORKFLOW_MAPPING_EXPORT_STARTED,
        BugReportAction.WORKFLOW_MAPPING_EXPORT_COMPLETED,
    ]
    assert "CONFIDENTIAL" not in repr(recorder.snapshot().events)


def test_import_cancel_before_apply_is_recorded_as_cancelled(
    monkeypatch, qapplication_session
):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(mapping, "_bugreport_recorder", recorder)
    monkeypatch.setattr(mapping, "preview_characteristic_aliases_csv", lambda *_args: object())
    monkeypatch.setattr(
        mapping,
        "apply_characteristic_alias_import",
        lambda *_args, **_kwargs: pytest.fail("cancelled preflight must not apply"),
    )
    mapping._record_mapping_action(BugReportAction.WORKFLOW_MAPPING_IMPORT_STARTED)
    worker = mapping._AliasCsvThread("import", "CONFIDENTIAL-db", "CONFIDENTIAL-file")
    worker.start()
    worker.cancel_review()
    _wait_for_thread(worker, qapplication_session)

    assert _actions(recorder) == [
        BugReportAction.WORKFLOW_MAPPING_IMPORT_STARTED,
        BugReportAction.WORKFLOW_MAPPING_IMPORT_CANCELLED,
    ]
    assert "CONFIDENTIAL" not in repr(recorder.snapshot().events)

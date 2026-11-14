from __future__ import annotations

from itertools import product
from types import SimpleNamespace

import pytest

from metroliza.shared.safe_bugreport import BugReportAction, SafeBugReportRecorder


@pytest.mark.parametrize(
    "worker_outcome, terminal_action",
    [
        ("success", BugReportAction.INDUSTRIAL_EXPORT_FINISHED),
        ("failure", BugReportAction.INDUSTRIAL_EXPORT_FAILED),
        ("cancelled", BugReportAction.INDUSTRIAL_EXPORT_CANCELLED),
    ],
)
def test_industrial_export_cancel_request_does_not_hide_worker_outcome(
    monkeypatch, worker_outcome, terminal_action
):
    from metroliza.ui import industrial_export_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    monkeypatch.setattr(module, "dismiss_worker_progress_dialog", lambda *_args, **_kwargs: None)
    from metroliza.ui import export_dialog

    monkeypatch.setattr(export_dialog, "show_export_result_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.QMessageBox, "information", lambda *_args, **_kwargs: None)

    class Worker:
        def isRunning(self):
            return True

        def cancel(self):
            self.cancel_called = True

    dialog = SimpleNamespace(
        export_thread=Worker(),
        _bugreport_export_reported=False,
        _bugreport_export_cancel_requested=False,
        loading_label=SimpleNamespace(setText=lambda _text: None),
        output_file="synthetic.xlsx",
        parent=lambda: None,
        _save_pending_credentials_after_success=lambda: None,
    )
    dialog._record_bugreport_export_outcome = lambda action: module.IndustrialExportDialog._record_bugreport_export_outcome(
        dialog, action
    )

    module.IndustrialExportDialog.cancel_export(dialog)
    if worker_outcome == "success":
        module.IndustrialExportDialog.on_export_finished(
            dialog,
            {"output_file": "synthetic.xlsx", "row_count": 1, "summary_rows": 1},
        )
    elif worker_outcome == "failure":
        module.IndustrialExportDialog.on_export_error(dialog, "synthetic worker error")
    else:
        module.IndustrialExportDialog.on_export_cancelled(dialog, "synthetic cancellation")

    assert dialog.export_thread.cancel_called
    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.INDUSTRIAL_EXPORT_CANCEL_REQUESTED,
        terminal_action,
    ]


@pytest.mark.parametrize(
    "profile_keys, second_status, expected_action",
    [
        (("line_a", "line_b"), "cancelled", BugReportAction.INDUSTRIAL_SYNC_CANCELLED),
        (("line_a", "line_b"), "succeeded", BugReportAction.INDUSTRIAL_SYNC_FINISHED),
        (("line_a", "line_b", "line_c"), "succeeded", BugReportAction.INDUSTRIAL_SYNC_CANCELLED),
    ],
)
def test_industrial_batch_cancel_uses_worker_result_and_skipped_work(
    monkeypatch, tmp_path, qapplication_session, profile_keys, second_status, expected_action
):
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    database = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(database)
    for key in profile_keys:
        repository.upsert_source_profile(
            profile_key=key,
            profile_name=key,
            source_db_alias=key,
            database_type="mssql",
            source_object_name="events",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            allowed_columns=("event_id", "reference"),
            default_pagination_column="event_id",
        )

    class Signal:
        def connect(self, _callback):
            pass

    class Worker:
        instances = []

        def __init__(self, **_kwargs):
            self.progress_message = Signal()
            self.result_ready = Signal()
            self.error_occurred = Signal()
            self.finished = Signal()
            self.running = False
            self.instances.append(self)

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

        def cancel(self):
            self.running = False

    monkeypatch.setattr(module, "IndustrialOznakSyncThread", Worker)
    dialog = module.IndustrialSyncDialog(db_file=database, report_db_file=None)
    dialog.username_edit.setText("operator")
    dialog.password_edit.setText("synthetic-secret")
    dialog.select_all_sources()

    dialog.sync_now()
    dialog.on_oznak_result(
        {"status": "succeeded", "test_only": False, "row_count": 1, "upsert_summary": {"processed": 1}}
    )
    Worker.instances[0].running = False
    dialog.on_oznak_thread_stopped()
    assert len(Worker.instances) == 2

    dialog.cancel_sync()
    dialog.on_oznak_result(
        {"status": second_status, "test_only": False, "error": "cancelled by user", "row_count": 0}
    )

    terminal = [
        event.action
        for event in recorder.snapshot().events
        if event.action
        in {
            BugReportAction.INDUSTRIAL_SYNC_FINISHED,
            BugReportAction.INDUSTRIAL_SYNC_FAILED,
            BugReportAction.INDUSTRIAL_SYNC_CANCELLED,
        }
    ]
    assert terminal == [expected_action]
    dialog.close()


@pytest.mark.parametrize(
    "test_only, pending_sql_preview, expected_action",
    [
        (False, False, BugReportAction.INDUSTRIAL_SYNC_RESULT_UNKNOWN),
        (True, True, BugReportAction.INDUSTRIAL_SQL_PREVIEW_RESULT_UNKNOWN),
    ],
)
def test_industrial_thread_stop_without_result_or_error_is_unknown(
    monkeypatch, test_only, pending_sql_preview, expected_action
):
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    host = SimpleNamespace(
        _active_operation=SimpleNamespace(test_only=test_only),
        _pending_sql_preview=pending_sql_preview,
        _bugreport_worker_terminal_seen=False,
        _bugreport_sync_reported=False,
        _bugreport_sql_preview_reported=False,
        _bugreport_sync_cancel_requested=True,
        _bugreport_sql_preview_cancel_requested=True,
        _batch_results=[],
        _batch_operations=[],
        _pending_credential_save=None,
        _active_batch_total=1,
        oznak_sync_thread=object(),
        cancel_sync_button=SimpleNamespace(setEnabled=lambda _enabled: None),
        _set_action_buttons_enabled=lambda _enabled: None,
    )
    host._record_bugreport_sync_outcome = lambda status: module.IndustrialSyncDialog._record_bugreport_sync_outcome(
        host, status
    )
    host._observe_bugreport_sync_status = lambda status: module.IndustrialSyncDialog._observe_bugreport_sync_status(
        host, status
    )
    host._set_bugreport_state_flag = lambda state, key: module.IndustrialSyncDialog._set_bugreport_state_flag(
        state, key
    )
    host._bugreport_state_flag = lambda state, key: module.IndustrialSyncDialog._bugreport_state_flag(
        state, key
    )
    host._record_bugreport_sql_preview_outcome = lambda status: module.IndustrialSyncDialog._record_bugreport_sql_preview_outcome(
        host, status
    )
    host._record_stopped_worker_bugreport_outcome = lambda: module.IndustrialSyncDialog._record_stopped_worker_bugreport_outcome(
        host
    )
    host._record_live_worker_bugreport_outcome = lambda: module.IndustrialSyncDialog._record_live_worker_bugreport_outcome(
        host
    )

    module.IndustrialSyncDialog.on_oznak_thread_stopped(host)

    assert [event.action for event in recorder.snapshot().events] == [expected_action]


@pytest.mark.parametrize(
    "first_status, expected_action",
    [
        ("succeeded", BugReportAction.INDUSTRIAL_SYNC_CANCELLED),
        ("failed", BugReportAction.INDUSTRIAL_SYNC_FAILED),
    ],
)
def test_batch_cancel_after_result_before_thread_stop_records_known_batch_outcome(
    monkeypatch, tmp_path, qapplication_session, first_status, expected_action
):
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    database = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(database)
    for key in ("line_a", "line_b"):
        repository.upsert_source_profile(
            profile_key=key,
            profile_name=key,
            source_db_alias=key,
            database_type="mssql",
            source_object_name="events",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            allowed_columns=("event_id", "reference"),
            default_pagination_column="event_id",
        )

    class Signal:
        def connect(self, _callback):
            pass

    class Worker:
        instances = []

        def __init__(self, **_kwargs):
            self.progress_message = Signal()
            self.result_ready = Signal()
            self.error_occurred = Signal()
            self.finished = Signal()
            self.running = False
            self.instances.append(self)

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

        def cancel(self):
            self.running = False

    monkeypatch.setattr(module, "IndustrialOznakSyncThread", Worker)
    dialog = module.IndustrialSyncDialog(db_file=database, report_db_file=None)
    dialog.username_edit.setText("operator")
    dialog.password_edit.setText("synthetic-secret")
    dialog.select_all_sources()

    dialog.sync_now()
    dialog.on_oznak_result(
        {"status": first_status, "test_only": False, "row_count": 1, "upsert_summary": {"processed": 1}}
    )
    dialog.cancel_sync()
    Worker.instances[0].running = False
    dialog.on_oznak_thread_stopped()

    assert [
        event.action
        for event in recorder.snapshot().events
        if event.action
        in {
            BugReportAction.INDUSTRIAL_SYNC_FINISHED,
            BugReportAction.INDUSTRIAL_SYNC_FAILED,
            BugReportAction.INDUSTRIAL_SYNC_CANCELLED,
        }
    ] == [expected_action]
    dialog.close()


@pytest.mark.parametrize(
    "first_status, expected_action",
    [
        ("succeeded", BugReportAction.INDUSTRIAL_SYNC_CANCELLED),
        ("failed", BugReportAction.INDUSTRIAL_SYNC_FAILED),
    ],
)
def test_batch_cancel_after_worker_stops_preserves_known_result(
    monkeypatch, tmp_path, qapplication_session, first_status, expected_action
):
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    database = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(database)
    for key in ("line_a", "line_b"):
        repository.upsert_source_profile(
            profile_key=key,
            profile_name=key,
            source_db_alias=key,
            database_type="mssql",
            source_object_name="events",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            allowed_columns=("event_id", "reference"),
            default_pagination_column="event_id",
        )

    class Signal:
        def connect(self, _callback):
            pass

    class Worker:
        instances = []

        def __init__(self, **_kwargs):
            self.progress_message = Signal()
            self.result_ready = Signal()
            self.error_occurred = Signal()
            self.finished = Signal()
            self.running = False
            self.instances.append(self)

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

        def cancel(self):
            self.running = False

    monkeypatch.setattr(module, "IndustrialOznakSyncThread", Worker)
    dialog = module.IndustrialSyncDialog(db_file=database, report_db_file=None)
    dialog.username_edit.setText("operator")
    dialog.password_edit.setText("synthetic-secret")
    dialog.select_all_sources()

    dialog.sync_now()
    dialog.on_oznak_result(
        {"status": first_status, "test_only": False, "row_count": 1, "upsert_summary": {"processed": 1}}
    )
    Worker.instances[0].running = False
    dialog.cancel_sync()
    dialog.on_oznak_thread_stopped()

    assert [
        event.action
        for event in recorder.snapshot().events
        if event.action
        in {
            BugReportAction.INDUSTRIAL_SYNC_FINISHED,
            BugReportAction.INDUSTRIAL_SYNC_FAILED,
            BugReportAction.INDUSTRIAL_SYNC_CANCELLED,
        }
    ] == [expected_action]
    dialog.close()


@pytest.mark.parametrize(
    "previous_status, current_status, truncated, stop_before_finished",
    list(
        product(
            ("succeeded", "failed"),
            ("succeeded", "cancelled", "failed", "unknown"),
            (False, True),
            (False, True),
        )
    ),
)
def test_batch_terminal_matrix_preserves_known_result_and_current_uncertainty(
    monkeypatch,
    tmp_path,
    qapplication_session,
    previous_status,
    current_status,
    truncated,
    stop_before_finished,
):
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    database = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(database)
    profile_keys = ("line_a", "line_b", "line_c") if truncated else ("line_a", "line_b")
    for key in profile_keys:
        repository.upsert_source_profile(
            profile_key=key,
            profile_name=key,
            source_db_alias=key,
            database_type="mssql",
            source_object_name="events",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            allowed_columns=("event_id", "reference"),
            default_pagination_column="event_id",
        )

    class Signal:
        def connect(self, _callback):
            pass

    class Worker:
        instances = []

        def __init__(self, **_kwargs):
            self.progress_message = Signal()
            self.result_ready = Signal()
            self.error_occurred = Signal()
            self.finished = Signal()
            self.running = False
            self.instances.append(self)

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

        def cancel(self):
            self.running = False

    monkeypatch.setattr(module, "IndustrialOznakSyncThread", Worker)
    dialog = module.IndustrialSyncDialog(db_file=database, report_db_file=None)
    dialog.username_edit.setText("operator")
    dialog.password_edit.setText("synthetic-secret")
    dialog.select_all_sources()
    dialog.sync_now()
    dialog.on_oznak_result(
        {
            "status": previous_status,
            "test_only": False,
            "row_count": 1,
            "upsert_summary": {"processed": 1},
        }
    )
    Worker.instances[0].running = False
    dialog.on_oznak_thread_stopped()
    current_worker = Worker.instances[1]

    if current_status != "unknown":
        current_worker.running = not stop_before_finished
        dialog.on_oznak_result(
            {
                "status": current_status,
                "test_only": False,
                "row_count": 1,
                "upsert_summary": {"processed": 1},
            }
        )
    if current_status == "unknown" or truncated or stop_before_finished:
        if current_status == "unknown":
            current_worker.running = not stop_before_finished
        dialog.cancel_sync()
    current_worker.running = False
    dialog.on_oznak_thread_stopped()

    if previous_status == "failed":
        expected = (
            BugReportAction.INDUSTRIAL_SYNC_FAILED_WITH_UNKNOWN
            if current_status == "unknown"
            else BugReportAction.INDUSTRIAL_SYNC_FAILED
        )
    elif current_status == "unknown":
        expected = BugReportAction.INDUSTRIAL_SYNC_RESULT_UNKNOWN
    elif current_status == "failed":
        expected = BugReportAction.INDUSTRIAL_SYNC_FAILED
    elif current_status == "cancelled" or truncated:
        expected = BugReportAction.INDUSTRIAL_SYNC_CANCELLED
    else:
        expected = BugReportAction.INDUSTRIAL_SYNC_FINISHED

    terminal_actions = {
        BugReportAction.INDUSTRIAL_SYNC_FINISHED,
        BugReportAction.INDUSTRIAL_SYNC_FAILED,
        BugReportAction.INDUSTRIAL_SYNC_FAILED_WITH_UNKNOWN,
        BugReportAction.INDUSTRIAL_SYNC_CANCELLED,
        BugReportAction.INDUSTRIAL_SYNC_RESULT_UNKNOWN,
    }
    assert [event.action for event in recorder.snapshot().events if event.action in terminal_actions] == [expected]
    dialog.close()


@pytest.mark.parametrize(
    "current_status, path",
    list(product(("succeeded", "cancelled", "failed", "error"), ("finished", "stop"))),
)
def test_batch_unknown_previous_combines_with_current_outcome(
    monkeypatch, tmp_path, qapplication_session, current_status, path
):
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *_args, **_kwargs: None)
    database = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(database)
    for key in ("line_a", "line_b"):
        repository.upsert_source_profile(
            profile_key=key,
            profile_name=key,
            source_db_alias=key,
            database_type="mssql",
            source_object_name="events",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            allowed_columns=("event_id", "reference"),
            default_pagination_column="event_id",
        )

    class Signal:
        def connect(self, _callback):
            pass

    class Worker:
        instances = []

        def __init__(self, **_kwargs):
            self.progress_message = Signal()
            self.result_ready = Signal()
            self.error_occurred = Signal()
            self.finished = Signal()
            self.running = False
            self.instances.append(self)

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

        def cancel(self):
            self.running = False

    monkeypatch.setattr(module, "IndustrialOznakSyncThread", Worker)
    dialog = module.IndustrialSyncDialog(db_file=database, report_db_file=None)
    dialog.username_edit.setText("operator")
    dialog.password_edit.setText("synthetic-secret")
    dialog.select_all_sources()
    dialog.sync_now()

    Worker.instances[0].running = False
    dialog.on_oznak_thread_stopped()
    assert len(Worker.instances) == 2
    terminal_actions = {
        BugReportAction.INDUSTRIAL_SYNC_FINISHED,
        BugReportAction.INDUSTRIAL_SYNC_FAILED,
        BugReportAction.INDUSTRIAL_SYNC_FAILED_WITH_UNKNOWN,
        BugReportAction.INDUSTRIAL_SYNC_CANCELLED,
        BugReportAction.INDUSTRIAL_SYNC_RESULT_UNKNOWN,
    }
    assert not any(event.action in terminal_actions for event in recorder.snapshot().events)

    current_worker = Worker.instances[1]
    if path == "stop":
        current_worker.running = False
        dialog.cancel_sync()
    if current_status == "error":
        dialog.on_oznak_error("synthetic worker failure")
    else:
        dialog.on_oznak_result(
            {
                "status": current_status,
                "test_only": False,
                "row_count": 1,
                "upsert_summary": {"processed": 1},
            }
        )
    current_worker.running = False
    dialog.on_oznak_thread_stopped()

    expected = (
        BugReportAction.INDUSTRIAL_SYNC_FAILED_WITH_UNKNOWN
        if current_status in {"failed", "error"}
        else BugReportAction.INDUSTRIAL_SYNC_RESULT_UNKNOWN
    )
    assert [event.action for event in recorder.snapshot().events if event.action in terminal_actions] == [expected]
    dialog.close()


@pytest.mark.parametrize(
    "test_only, pending_sql_preview, expected_action",
    [
        (False, False, BugReportAction.INDUSTRIAL_SYNC_RESULT_UNKNOWN),
        (True, True, BugReportAction.INDUSTRIAL_SQL_PREVIEW_RESULT_UNKNOWN),
    ],
)
def test_cancel_stopped_worker_without_terminal_signal_records_unknown(
    monkeypatch, test_only, pending_sql_preview, expected_action
):
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    monkeypatch.setattr(module, "set_status_variant", lambda *_args: None)

    class Worker:
        def isRunning(self):
            return False

    host = SimpleNamespace(
        _active_operation=SimpleNamespace(test_only=test_only),
        _pending_sql_preview=pending_sql_preview,
        _bugreport_worker_terminal_seen=False,
        _bugreport_sync_reported=False,
        _bugreport_sql_preview_reported=False,
        _bugreport_sync_cancel_requested=False,
        _bugreport_sql_preview_cancel_requested=False,
        _bugreport_sync_batch_truncated=False,
        _bugreport_sync_batch_mode=False,
        _bugreport_sync_unknown_seen=False,
        _bugreport_sync_known_failure=False,
        _bugreport_sync_known_cancelled=False,
        _bugreport_sync_known_warning=False,
        _bugreport_sync_known_success=False,
        _bugreport_stopped_worker_snapshot=None,
        _batch_results=[],
        _batch_operations=[],
        _active_batch_total=1,
        oznak_sync_thread=Worker(),
        cancel_sync_button=SimpleNamespace(setEnabled=lambda _enabled: None),
        _present_stage=lambda *_args: None,
        _set_action_buttons_enabled=lambda _enabled: None,
        status_label=SimpleNamespace(setText=lambda _text: None),
        sql_status_label=SimpleNamespace(setText=lambda _text: None),
        _open_csv_summary_after_fetch=False,
        parent=lambda: None,
        _present_result_stage=lambda _result: None,
        _save_pending_credentials_after_success=lambda _result: None,
        _populate_sql_preview_table=lambda _records: None,
        _sync_sql_editor_status=lambda: None,
    )
    host._record_bugreport_sync_outcome = lambda status: module.IndustrialSyncDialog._record_bugreport_sync_outcome(
        host, status
    )
    host._observe_bugreport_sync_status = lambda status: module.IndustrialSyncDialog._observe_bugreport_sync_status(
        host, status
    )
    host._set_bugreport_state_flag = lambda state, key: module.IndustrialSyncDialog._set_bugreport_state_flag(
        state, key
    )
    host._bugreport_state_flag = lambda state, key: module.IndustrialSyncDialog._bugreport_state_flag(
        state, key
    )
    host._record_bugreport_sql_preview_outcome = lambda status: module.IndustrialSyncDialog._record_bugreport_sql_preview_outcome(
        host, status
    )
    host._record_stopped_worker_bugreport_outcome = lambda: module.IndustrialSyncDialog._record_stopped_worker_bugreport_outcome(
        host
    )
    host._record_snapshot_worker_bugreport_outcome = lambda snapshot: module.IndustrialSyncDialog._record_snapshot_worker_bugreport_outcome(
        host, snapshot
    )
    host._batch_bugreport_outcome = lambda: module.IndustrialSyncDialog._batch_bugreport_outcome(host)
    host._record_live_worker_bugreport_outcome = lambda: module.IndustrialSyncDialog._record_live_worker_bugreport_outcome(
        host
    )
    host._capture_stopped_worker_bugreport_snapshot = lambda: module.IndustrialSyncDialog._capture_stopped_worker_bugreport_snapshot(
        host
    )

    module.IndustrialSyncDialog.cancel_sync(host)
    module.IndustrialSyncDialog.on_oznak_thread_stopped(host)
    module.IndustrialSyncDialog.on_oznak_result(
        host,
        {
            "status": "succeeded",
            "test_only": test_only,
            "row_count": 1,
            "upsert_summary": {"processed": 1},
            "preview_records": (),
        }
    )
    assert [event.action for event in recorder.snapshot().events] == [expected_action]


def test_industrial_bugreport_projection_handles_unexpected_status_shapes(monkeypatch):
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    sync_status = {"private": "value"}
    preview_status = ["private", "value"]

    sync_ui = SimpleNamespace(
        _active_batch_total=1,
        _present_fetch_outcome=lambda *_args, **_kwargs: None,
    )
    preview_ui = SimpleNamespace(
        _active_batch_total=1,
        _present_stage=lambda *_args, **_kwargs: None,
        test_connection_button=object(),
    )
    module.IndustrialSyncDialog._present_result_stage(
        sync_ui, {"status": sync_status, "test_only": False}
    )
    module.IndustrialSyncDialog._present_result_stage(
        preview_ui, {"status": preview_status, "test_only": True}
    )

    sync_projection = SimpleNamespace(_bugreport_sync_reported=False)
    preview_projection = SimpleNamespace(_bugreport_sql_preview_reported=False)
    module.IndustrialSyncDialog._record_bugreport_sync_outcome(sync_projection, sync_status)
    module.IndustrialSyncDialog._record_bugreport_sql_preview_outcome(preview_projection, preview_status)

    batch_projection = SimpleNamespace(
        _batch_results=[{"status": sync_status}],
        _bugreport_sync_batch_truncated=False,
        _bugreport_sync_reported=False,
    )
    batch_projection._bugreport_state_flag = lambda state, key: module.IndustrialSyncDialog._bugreport_state_flag(
        state, key
    )
    outcome = module.IndustrialSyncDialog._batch_bugreport_outcome(batch_projection)
    module.IndustrialSyncDialog._record_bugreport_sync_outcome(batch_projection, outcome)

    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.INDUSTRIAL_SYNC_RESULT_UNKNOWN,
        BugReportAction.INDUSTRIAL_SQL_PREVIEW_RESULT_UNKNOWN,
        BugReportAction.INDUSTRIAL_SYNC_RESULT_UNKNOWN,
    ]


@pytest.mark.parametrize("status", [{"private": "value"}, ["private", "value"]])
def test_industrial_unexpected_sync_status_does_not_interrupt_ui(
    monkeypatch, tmp_path, qapplication_session, status
):
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    dialog = module.IndustrialSyncDialog(
        db_file=str(tmp_path / "industrial.db"),
        report_db_file=None,
    )
    dialog._active_operation = SimpleNamespace(
        test_only=False,
        profile=SimpleNamespace(profile_key="synthetic", profile_name="synthetic"),
    )
    dialog._active_batch_total = 1
    dialog._bugreport_sync_reported = False
    dialog._bugreport_sync_batch_truncated = False
    dialog._bugreport_worker_terminal_seen = False
    dialog._pending_credential_save = None
    dialog._pending_sql_preview = False
    dialog._open_csv_summary_after_fetch = False

    dialog.on_oznak_result(
        {
            "status": status,
            "test_only": False,
            "row_count": 0,
            "upsert_summary": {},
        }
    )

    assert dialog.status_label.text() == "Industrial fetch failed"
    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.INDUSTRIAL_SYNC_RESULT_UNKNOWN,
    ]
    dialog.close()


@pytest.mark.parametrize(
    "cancellation_requested, termination_reason",
    [(True, "completed"), (False, "cancelled")],
)
def test_metadata_enrichment_late_cancel_uses_worker_termination(
    monkeypatch, cancellation_requested, termination_reason
):
    from metroliza.ui import main_window as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    monkeypatch.setattr(module, "set_status_variant", lambda *_args: None)
    result = SimpleNamespace(
        enriched_files=1,
        total_files=1,
        failed_files=0,
        skipped_files=0,
        cancelled_files=0,
        cancellation_requested=cancellation_requested,
        termination_reason=termination_reason,
    )
    host = SimpleNamespace(
        enrich_metadata_action=SimpleNamespace(setEnabled=lambda _enabled: None),
        cancel_metadata_enrichment_button=SimpleNamespace(
            setEnabled=lambda _enabled: None,
            setVisible=lambda _visible: None,
        ),
        metadata_enrichment_error_message=None,
        metadata_enrichment_thread=SimpleNamespace(result=result),
        metadata_enrichment_warnings=(),
        metadata_enrichment_status_label=SimpleNamespace(setText=lambda _text: None, setToolTip=lambda _text: None),
        metadata_enrichment_progress_bar=SimpleNamespace(setValue=lambda _value: None),
        _pdf_execution_available=lambda: True,
        log_and_exit=lambda error: pytest.fail(str(error)),
    )
    host._show_metadata_enrichment_result = lambda value: module.MainWindow._show_metadata_enrichment_result(host, value)
    host._record_metadata_enrichment_bugreport = lambda action: module.MainWindow._record_metadata_enrichment_bugreport(
        host, action
    )

    module.MainWindow.on_metadata_enrichment_finished(host)

    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.METADATA_ENRICHMENT_CANCELLED,
    ]

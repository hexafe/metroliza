from types import SimpleNamespace

from metroliza.shared.safe_bugreport import (
    BugReportAction,
    BugReportCategory,
    SafeBugReportRecorder,
    build_bug_report_markdown,
)


def test_industrial_sync_outcomes_are_closed_and_deduplicated(monkeypatch):
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    dialog = SimpleNamespace(_bugreport_sync_reported=False)

    module.IndustrialSyncDialog._record_bugreport_sync_outcome(dialog, "succeeded")
    module.IndustrialSyncDialog._record_bugreport_sync_outcome(dialog, "failed")

    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.INDUSTRIAL_SYNC_FINISHED,
    ]


def test_industrial_export_outcomes_and_options_contain_no_input_values(monkeypatch):
    from metroliza.ui import industrial_export_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    monkeypatch.setattr(module, "dismiss_worker_progress_dialog", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module.QMessageBox,
        "warning",
        lambda *_args, **_kwargs: None,
    )
    dialog = SimpleNamespace(_bugreport_export_reported=False)
    dialog._record_bugreport_export_outcome = lambda action: (
        module.IndustrialExportDialog._record_bugreport_export_outcome(dialog, action)
    )

    module.IndustrialExportDialog.on_export_error(
        dialog,
        "CUSTOMER_NAME_SENTINEL PRIVATE_PATH_SENTINEL QUERY_TEXT_SENTINEL",
    )
    module.IndustrialExportDialog._record_bugreport_export_outcome(
        dialog, BugReportAction.INDUSTRIAL_EXPORT_FINISHED
    )
    recorder.record(BugReportAction.OPTION_INDUSTRIAL_EXPORT_RAW, enabled=True)
    report = build_bug_report_markdown(
        BugReportCategory.OPERATION_FAILED,
        recorder.snapshot(),
    )

    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.INDUSTRIAL_EXPORT_FAILED,
        BugReportAction.OPTION_INDUSTRIAL_EXPORT_RAW,
    ]
    for sentinel in (
        "CUSTOMER_NAME_SENTINEL",
        "PRIVATE_PATH_SENTINEL",
        "QUERY_TEXT_SENTINEL",
    ):
        assert sentinel not in report


def test_realtime_storage_state_records_only_boolean(monkeypatch):
    from metroliza.ui import realtime_industrial_monitoring_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    monkeypatch.setattr(module, "set_status_variant", lambda *_args: None)
    dialog = SimpleNamespace(storage_lifecycle_label=SimpleNamespace(
        setText=lambda _text: None,
    ))

    module.RealtimeIndustrialMonitoringDialog.set_temporary_session_storage(
        dialog, True
    )
    event = recorder.snapshot().events[-1]
    assert event.action is BugReportAction.REALTIME_TEMPORARY_STORAGE
    assert event.enabled is True


def test_industrial_analytics_uses_distinct_context_outcomes(monkeypatch):
    from metroliza.ui import industrial_analytics_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    dialog = SimpleNamespace(
        _is_bugreport_industrial_context=lambda: True,
    )

    module.IndustrialAnalyticsDialog._record_bugreport_analytics_outcome(
        dialog, "finished", warnings=True
    )
    module.IndustrialAnalyticsDialog._record_bugreport_analytics_outcome(
        dialog, "failed"
    )
    csv_dialog = SimpleNamespace(
        _is_bugreport_industrial_context=lambda: False,
    )
    module.IndustrialAnalyticsDialog._record_bugreport_analytics_outcome(
        csv_dialog, "finished"
    )

    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.INDUSTRIAL_ANALYSIS_FINISHED_WITH_WARNINGS,
        BugReportAction.INDUSTRIAL_ANALYSIS_FAILED,
        BugReportAction.ANALYSIS_FINISHED,
    ]


def test_industrial_source_save_failure_does_not_record_profile_text(monkeypatch):
    from metroliza.ui import industrial_source_profiles_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    monkeypatch.setattr(
        module,
        "upsert_source_profile_in_config",
        lambda *_args: (_ for _ in ()).throw(ValueError("PRIVATE_SOURCE_SENTINEL")),
    )
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *_args: None)
    dialog = SimpleNamespace(
        config_path="PRIVATE_PATH_SENTINEL",
        db_file="PRIVATE_PATH_SENTINEL",
        profile_from_form=lambda: SimpleNamespace(order_by_enabled=True),
    )

    module.IndustrialSourceProfilesDialog.save_source(dialog)
    report = build_bug_report_markdown(BugReportCategory.OPERATION_FAILED, recorder.snapshot())

    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.INDUSTRIAL_SOURCE_PROFILE_SAVE_STARTED,
        BugReportAction.OPTION_INDUSTRIAL_SOURCE_ORDER_BY,
        BugReportAction.INDUSTRIAL_SOURCE_PROFILE_SAVE_FAILED,
    ]
    assert "PRIVATE_SOURCE_SENTINEL" not in report
    assert "PRIVATE_PATH_SENTINEL" not in report


def test_industrial_sql_preview_terminal_states_are_closed_codes(monkeypatch):
    from metroliza.ui import industrial_sync_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    dialog = SimpleNamespace(_bugreport_sql_preview_reported=False)
    module.IndustrialSyncDialog._record_bugreport_sql_preview_outcome(dialog, "succeeded")
    dialog._bugreport_sql_preview_reported = False
    module.IndustrialSyncDialog._record_bugreport_sql_preview_outcome(dialog, "failed")
    dialog._bugreport_sql_preview_reported = False
    module.IndustrialSyncDialog._record_bugreport_sql_preview_outcome(dialog, "cancelled")

    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.INDUSTRIAL_SQL_PREVIEW_FINISHED,
        BugReportAction.INDUSTRIAL_SQL_PREVIEW_FAILED,
        BugReportAction.INDUSTRIAL_SQL_PREVIEW_CANCELLED,
    ]


def test_realtime_review_never_records_operator_comment_or_event_id(monkeypatch):
    from metroliza.ui import realtime_industrial_monitoring_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    monkeypatch.setattr(module, "set_status_variant", lambda *_args: None)

    class Service:
        def __init__(self, _db_file):
            pass

        def acknowledge_event(self, **_kwargs):
            return None

    monkeypatch.setattr(module, "RealtimeDashboardService", Service)
    status = SimpleNamespace(setText=lambda _text: None)
    comment = SimpleNamespace(text=lambda: "COMMENT_SENTINEL", clear=lambda: None)
    dialog = SimpleNamespace(
        _selected_event_id=lambda: 82731,
        event_operator_edit=SimpleNamespace(text=lambda: "OPERATOR_SENTINEL"),
        event_comment_edit=comment,
        event_review_status_label=status,
        db_file="PRIVATE_PATH_SENTINEL",
        refresh_event_review=lambda: None,
    )

    module.RealtimeIndustrialMonitoringDialog._apply_selected_event_action(
        dialog, "acknowledge"
    )
    report = build_bug_report_markdown(BugReportCategory.OTHER, recorder.snapshot())

    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.REALTIME_EVENT_ACKNOWLEDGE_STARTED,
        BugReportAction.REALTIME_EVENT_ACKNOWLEDGE_FINISHED,
    ]
    for sentinel in (
        "COMMENT_SENTINEL",
        "OPERATOR_SENTINEL",
        "PRIVATE_PATH_SENTINEL",
        "82731",
    ):
        assert sentinel not in report


def test_realtime_gui_worker_path_keeps_signal_values_out_of_report(
    monkeypatch, tmp_path, qapplication_session
):
    from PyQt6.QtCore import QThread, pyqtSignal
    from PyQt6.QtTest import QSignalSpy

    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.ui import realtime_industrial_monitoring_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    db_file = str(tmp_path / "PRIVATE_DATABASE_PATH_SENTINEL.sqlite")
    IndustrialDataRepository(db_file).ensure_schema()

    class SyntheticPollThread(QThread):
        update_label = pyqtSignal(str)
        result_ready = pyqtSignal(tuple)
        error_occurred = pyqtSignal(str)
        cancelled = pyqtSignal(str)

        def __init__(self, *, db_file, configs):
            super().__init__()

        def run(self):
            self.result_ready.emit((SimpleNamespace(
                source_profile_id=1,
                stream_key="PRIVATE_STREAM_SENTINEL",
                status="succeeded",
                rows_fetched=1,
                samples_inserted=1,
                detector_events_created=0,
                cursor_value="PRIVATE_CURSOR_SENTINEL",
                diagnostics={"query_summary": "PRIVATE_SQL_SENTINEL"},
            ),))

    monkeypatch.setattr(module, "RealtimeMonitorPollThread", SyntheticPollThread)
    dialog = module.RealtimeIndustrialMonitoringDialog(
        None,
        db_file,
        config_path=tmp_path / "PRIVATE_CONFIG_PATH_SENTINEL.yaml",
    )
    dialog._configs_for_checked_sources = lambda **_kwargs: (object(),)
    dialog._schedule_dashboard_write = lambda **_kwargs: None
    idle_spy = QSignalSpy(dialog.database_work_idle)

    try:
        dialog.poll_once()
        assert idle_spy.wait(3000)
        report = build_bug_report_markdown(BugReportCategory.OPERATION_FAILED, recorder.snapshot())
    finally:
        dialog.request_shutdown()
        dialog.deleteLater()
        qapplication_session.processEvents()

    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.REALTIME_TEMPORARY_STORAGE,
        BugReportAction.REALTIME_POLL_STARTED,
        BugReportAction.REALTIME_POLL_FINISHED,
    ]
    for sentinel in (
        "PRIVATE_DATABASE_PATH_SENTINEL",
        "PRIVATE_CONFIG_PATH_SENTINEL",
        "PRIVATE_STREAM_SENTINEL",
        "PRIVATE_CURSOR_SENTINEL",
        "PRIVATE_SQL_SENTINEL",
    ):
        assert sentinel not in report


def test_instrumented_ui_modules_use_the_shared_closed_action_enum():
    from pathlib import Path

    root = Path(__file__).parents[1] / "src" / "metroliza" / "ui"
    modules = (
        "main_window.py",
        "industrial_data_dialog.py",
        "industrial_source_profiles_dialog.py",
        "industrial_linking_dialog.py",
        "industrial_filter_dialog.py",
        "industrial_grouping_dialog.py",
        "industrial_analytics_dialog.py",
        "industrial_sync_dialog.py",
        "industrial_export_dialog.py",
        "realtime_industrial_monitoring_dialog.py",
        "parser_plugin_wizard.py",
    )
    for filename in modules:
        source = (root / filename).read_text(encoding="utf-8")
        assert "BugReportAction" in source
        assert "recorder as _bugreport_recorder" in source
        assert "_bugreport_recorder.record(" in source

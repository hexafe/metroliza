"""Synthetic request-bound UI evidence; no worker or private input is opened."""

from dataclasses import replace
from types import SimpleNamespace
import uuid

import pytest

from metroliza.shared.safe_bugreport import (
    BUG_REPORT_UNAVAILABLE,
    BugReportAction,
    BugReportCategory,
    SafeBugReportRecorder,
    build_bug_report_markdown,
)
from metroliza.shared.safe_bugreport_context import (
    BugReportContextSelection,
    ContextOperationOutcome,
    OptionSnapshotKind,
)


pytestmark = pytest.mark.usefixtures("qapplication_session")
PRIVATE = "PRIVATE_CUSTOMER_VALUE_SENTINEL"


def _report(recorder):
    report = build_bug_report_markdown(
        BugReportCategory.WRONG_OUTPUT,
        recorder.snapshot(),
        context=BugReportContextSelection(recorder.context_snapshot()),
    )
    assert report != BUG_REPORT_UNAVAILABLE
    return report


def _analysis_request(**overrides):
    from metroliza.industrial.contracts import IndustrialAnalyticsRequest, validate_industrial_analytics_request

    fields = dict(
        source_kind="tabular_file", input_file=f"/synthetic/{PRIVATE}.csv",
        output_dashboard_file=f"/synthetic/{PRIVATE}.html",
        output_workbook_file=f"/synthetic/{PRIVATE}.xlsx",
    )
    fields.update(overrides)
    return validate_industrial_analytics_request(IndustrialAnalyticsRequest(**fields))


def _requests(recorder):
    return [event.request for event in recorder.context_snapshot().events if event.request is not None]


@pytest.mark.parametrize("source,cache,extension,kind,source_flag", [
    ("tabular_file", False, ".csv", OptionSnapshotKind.CSV_ANALYSIS, "source_csv"),
    ("tabular_file", False, ".xlsx", OptionSnapshotKind.CSV_ANALYSIS, "source_xlsx"),
    ("tabular_file", True, ".csv", OptionSnapshotKind.INDUSTRIAL_ANALYSIS, "source_industrial_cache"),
    ("production_cache", False, ".csv", OptionSnapshotKind.INDUSTRIAL_ANALYSIS, "source_production_cache"),
])
def test_analysis_request_snapshot_has_closed_source_and_exact_chart_flags(
    monkeypatch, source, cache, extension, kind, source_flag,
):
    from metroliza.industrial.industrial_analytics_state import (
        ProductionAggregationState, ProductionChartSelection, ProductionFilterState, ReferenceCohortState,
    )
    from metroliza.ui import industrial_analytics_dialog as module

    recorder = SafeBugReportRecorder(max_events=2)
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    request = _analysis_request(
        source_kind=source, input_file=f"/synthetic/{PRIVATE}{extension}",
        separate_parameter_sheets=False,
        chart_selection=ProductionChartSelection(False, True, False, True, False),
        filter_state=ProductionFilterState(references=(PRIVATE,)),
        aggregation_state=ProductionAggregationState(group_fields=("station",)),
        cohort_state=ReferenceCohortState(references=(PRIVATE,)),
    )
    token = module.IndustrialAnalyticsDialog._record_safe_request_options(
        SimpleNamespace(is_industrial_cache_presentation=cache), request,
    )
    assert type(token) is uuid.UUID
    for _ in range(140):
        recorder.record(BugReportAction.APP_OPENED)
    snapshot = recorder.context_snapshot().options[-1]
    flags = dict(snapshot.options)
    assert snapshot.kind is kind
    assert snapshot.operation_id == token
    assert flags["workbook"] is True and flags["html"] is True
    assert flags["separate_parameter_sheets"] is False
    assert [flags[key] for key in (
        "chart_time_series", "chart_histogram", "chart_violin", "chart_box", "chart_groupstats",
    )] == [False, True, False, True, False]
    assert flags["filters_applied"] and flags["aggregation_configured"] and flags["cohort_configured"]
    assert flags["grouping_applied"] is False
    assert [key for key, value in flags.items() if key.startswith("source_") and value] == [source_flag]
    assert PRIVATE not in _report(recorder)


def test_analysis_snapshots_keep_each_accepted_request_not_later_ui_values(monkeypatch):
    from metroliza.ui import industrial_analytics_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    dialog = SimpleNamespace(is_industrial_cache_presentation=False)
    first = _analysis_request(separate_parameter_sheets=True)
    second = replace(first, output_workbook_file="", separate_parameter_sheets=False,
                     tabular_filter_expression=f"{PRIVATE} > 0")
    tokens = [module.IndustrialAnalyticsDialog._record_safe_request_options(dialog, request)
              for request in (first, second)]
    snapshots = recorder.context_snapshot().options
    assert [item.operation_id for item in snapshots] == tokens
    assert [dict(item.options)["workbook"] for item in snapshots] == [True, False]
    assert [dict(item.options)["separate_parameter_sheets"] for item in snapshots] == [True, False]
    assert [dict(item.options)["filters_applied"] for item in snapshots] == [False, True]
    assert PRIVATE not in _report(recorder)


@pytest.mark.parametrize("filtered,grouped", [(False, False), (True, True)])
def test_export_snapshot_uses_accepted_request_and_does_not_store_query_or_groups(monkeypatch, filtered, grouped):
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
    from metroliza.ui import export_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    options = ExportOptions(
        preset="full_report", export_type="scatter", export_target="google_sheets_drive_convert",
        backend_target="google", generate_html_dashboard=True, generate_summary_sheet=True,
        hide_ok_results=True, include_industrial_context=True, group_analysis_level="standard",
    )
    request = ExportRequest(
        AppPaths(f"/{PRIVATE}.db", f"/{PRIVATE}.xlsx"), options,
        filter_query=f"SELECT {PRIVATE}" if filtered else module.DEFAULT_FILTER_QUERY,
        grouping_df=() if grouped else None,
    )
    module._record_export_request_options(request)
    snapshot = recorder.context_snapshot().options[-1]
    flags = dict(snapshot.options)
    assert snapshot.kind is OptionSnapshotKind.REPORT_EXPORT
    assert flags["cloud"] and flags["html"] and flags["workbook"]
    assert flags["chart_scatter"] is True and flags["chart_line"] is False
    assert flags["preset_full_report"] is True and flags["preset_fast_diagnostics"] is False
    assert flags["summary_sheet"] and flags["industrial_context"] and flags["hide_ok"]
    assert flags["filters_applied"] is filtered and flags["grouping_applied"] is grouped
    assert [event.outcome for event in _requests(recorder)] == [ContextOperationOutcome.STARTED]
    assert PRIVATE not in _report(recorder)


def test_planner_records_semantic_actions_without_values_or_automatic_initialization(monkeypatch):
    from PyQt6.QtCore import Qt
    from metroliza.ui import report_planner_model as module
    from tests.metadata_review_fakes import make_selection, review_result

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    model = module.ReportPlannerModel()
    model.set_review(review_result((f"{PRIVATE}-a.pdf", f"{PRIVATE}-b.pdf")))
    for row in model.metadata_rows.values():
        row.apply_fast(make_selection({"reference": PRIVATE}))
    assert recorder.snapshot().events == ()
    comment = model.index(0, model.column_for_field("comment"))
    assert model.setData(comment, PRIVATE)
    changed, error = model.copy_value_to_checked("comment", PRIVATE)
    assert changed == 1 and error is None
    assert model.undo_copy() == 1
    assert model.reset_row(f"{PRIVATE}-a.pdf") == 1
    model.clear_selection()
    model.clear_selection()  # A no-op is not another manual selection change.
    assert model.setData(model.index(0, model.CHECKBOX_COLUMN), Qt.CheckState.Checked,
                         Qt.ItemDataRole.CheckStateRole)
    assert [event.action for event in recorder.snapshot().events] == [
        BugReportAction.REPORT_PLAN_EDIT, BugReportAction.REPORT_PLAN_COPY_CHECKED,
        BugReportAction.REPORT_PLAN_UNDO, BugReportAction.REPORT_PLAN_RESET,
        BugReportAction.REPORT_PLAN_SELECTION, BugReportAction.REPORT_PLAN_SELECTION,
    ]
    assert [event.enabled for event in recorder.snapshot().events[-2:]] == [False, True]
    assert PRIVATE not in _report(recorder)


def _analytics_worker(module):
    return module.IndustrialAnalyticsThread(
        source_kind="tabular_file", input_file=f"/{PRIVATE}.csv",
        output_dashboard_file=f"/{PRIVATE}.html", output_workbook_file=f"/{PRIVATE}.xlsx",
    )


@pytest.mark.parametrize("matching", [True, False])
def test_analysis_result_target_comparison_uses_only_actual_sender_request(monkeypatch, matching):
    from metroliza.ui import industrial_analytics_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    worker = _analytics_worker(module)
    result = SimpleNamespace(
        workbook_path=worker.request.output_workbook_file if matching else f"/other/{PRIVATE}.xlsx",
        html_dashboard_path=worker.request.output_dashboard_file,
    )
    dialog = SimpleNamespace(sender=lambda: worker)
    module.IndustrialAnalyticsDialog._record_safe_result_paths(dialog, result)
    assert [(event.action, event.enabled) for event in recorder.snapshot().events] == [
        (BugReportAction.CHECK_ANALYTICS_WORKBOOK_RESULT_MATCH, matching),
        (BugReportAction.CHECK_ANALYTICS_DASHBOARD_RESULT_MATCH, True),
    ]
    assert PRIVATE not in _report(recorder)


@pytest.mark.parametrize("sender_kind", ["none", "lookalike", "bad_request"])
def test_analysis_result_checks_omit_unknown_sender_even_with_current_worker(monkeypatch, sender_kind):
    from metroliza.ui import industrial_analytics_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    worker = _analytics_worker(module)
    sender = {"none": None, "lookalike": SimpleNamespace(request=worker.request), "bad_request": worker}[sender_kind]
    if sender_kind == "bad_request":
        worker.request = SimpleNamespace(output_workbook_file=f"/{PRIVATE}.xlsx")
    dialog = SimpleNamespace(sender=lambda: sender, analytics_thread=worker)
    module.IndustrialAnalyticsDialog._record_safe_result_paths(
        dialog, SimpleNamespace(workbook_path=f"/{PRIVATE}.xlsx", html_dashboard_path=f"/{PRIVATE}.html"),
    )
    assert recorder.snapshot().events == ()


@pytest.mark.parametrize("outcome", [ContextOperationOutcome.COMPLETED,
                                    ContextOperationOutcome.COMPLETED_WITH_WARNINGS,
                                    ContextOperationOutcome.FAILED, ContextOperationOutcome.CANCELLED])
def test_analysis_outcome_finishes_the_sender_token_not_latest_request(monkeypatch, outcome):
    from metroliza.ui import industrial_analytics_dialog as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    worker = _analytics_worker(module)
    worker._bugreport_option_token = recorder.record_option_snapshot(OptionSnapshotKind.CSV_ANALYSIS, {"html": True})
    newer = recorder.record_option_snapshot(OptionSnapshotKind.CSV_ANALYSIS, {"html": False})
    module.IndustrialAnalyticsDialog._record_safe_option_outcome(SimpleNamespace(sender=lambda: worker), outcome)
    terminal = _requests(recorder)[-1]
    assert terminal.operation_id == worker._bugreport_option_token != newer
    assert terminal.outcome is outcome
    module.IndustrialAnalyticsDialog._record_safe_option_outcome(
        SimpleNamespace(sender=lambda: None, analytics_thread=worker), ContextOperationOutcome.FAILED,
    )
    assert _requests(recorder)[-1] == terminal


def _edit_payload():
    return dict(storage_flavor="current", normalization_changes={
        "reference": [(PRIVATE, PRIVATE + "-old")], "sample_number": [], "header": [],
    }, report_updates=[(419, {"comment": PRIVATE})], measurement_updates=[])


@pytest.mark.parametrize("failure", [False, True])
def test_database_sync_payload_has_fixed_categories_and_exact_terminal_token(monkeypatch, failure):
    from metroliza.ui import modify_db as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    payload = _edit_payload()
    calls = []

    def apply_changes(**received):
        calls.append(received)
        if failure:
            raise ValueError(PRIVATE)

    dialog = SimpleNamespace(db_file=f"/{PRIVATE}.db", _create_report_edit_service=lambda: SimpleNamespace(
        apply_changes=apply_changes,
    ))
    if failure:
        with pytest.raises(ValueError, match=PRIVATE):
            module.ModifyDB._apply_edit_payload(dialog, payload)
    else:
        assert module.ModifyDB._apply_edit_payload(dialog, payload) is True
    assert calls == [payload]
    option = recorder.context_snapshot().options[-1]
    assert option.kind is OptionSnapshotKind.DATABASE_EDIT
    assert dict(option.options) == {
        "normalization_reference": True, "normalization_sample_number": False,
        "normalization_header": False, "report_updates_present": True, "measurement_updates_present": False,
    }
    events = _requests(recorder)
    assert [event.operation_id for event in events] == [option.operation_id, option.operation_id]
    assert [event.outcome for event in events] == [ContextOperationOutcome.STARTED,
        ContextOperationOutcome.FAILED if failure else ContextOperationOutcome.COMPLETED]
    assert PRIVATE not in _report(recorder)


@pytest.mark.parametrize("failure", [False, True])
def test_database_async_finish_is_bound_to_owned_worker_token(monkeypatch, failure):
    from metroliza.ui import modify_db as module

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(module, "_bugreport_recorder", recorder)
    monkeypatch.setattr(module, "dismiss_worker_progress_dialog", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.detached_threads, "delete_on_owner_thread", lambda _obj: None)
    token = module._record_database_edit_options(_edit_payload())
    newer = module._record_database_edit_options(_edit_payload())
    thread = SimpleNamespace(_bugreport_option_token=token, error=ValueError(PRIVATE) if failure else None)
    results = []
    dialog = SimpleNamespace(
        _edit_thread=thread, _edit_progress=object(), _save_in_progress=True,
        _report_save_error=lambda _error: results.append("failed"),
        _edit_succeeded=lambda: results.append("completed"),
    )
    module.ModifyDB._finish_edit(dialog, SimpleNamespace(_bugreport_option_token=newer))
    assert len(_requests(recorder)) == 2
    module.ModifyDB._finish_edit(dialog, thread)
    terminal = _requests(recorder)[-1]
    assert terminal.operation_id == token != newer
    assert terminal.outcome is (ContextOperationOutcome.FAILED if failure else ContextOperationOutcome.COMPLETED)
    assert results == ["failed" if failure else "completed"]
    assert PRIVATE not in _report(recorder)

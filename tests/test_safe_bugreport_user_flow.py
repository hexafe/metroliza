"""Real synthetic CSV worker, report menu, clipboard and replay matching."""

import pandas as pd
import pytest
from PyQt6.QtGui import QGuiApplication

from metroliza.industrial.industrial_analytics_workflow import AnalyticsCancelled
from metroliza.industrial.industrial_workers import IndustrialAnalyticsThread
from metroliza.shared import safe_bugreport
from metroliza.shared.safe_bugreport import BugReportAction, SafeBugReportRecorder
from metroliza.shared.safe_bugreport_context import (
    OptionSnapshotKind,
    TemporaryResourceKind,
    TemporaryResourcePhase,
    parse_v2_report,
)
from metroliza.ui.safe_bugreport_dialog import SafeBugReportDialog
import metroliza.ui.safe_bugreport_dialog as report_ui
import metroliza.ui.industrial_analytics_dialog as analytics_ui
from scripts.reproduce_safe_bugreport import match_safe_bugreport
from tests.test_csv_progress_nonmodal import owner, _owned_notifications, _wait  # noqa: F401


def test_real_csv_analysis_can_be_reported_and_matched(owner, qapplication_session, tmp_path, monkeypatch):  # noqa: F811
    window, dialog, source = owner
    trace = SafeBugReportRecorder()
    monkeypatch.setattr(safe_bugreport, "recorder", trace)
    monkeypatch.setattr(analytics_ui, "_bugreport_recorder", trace)
    monkeypatch.setattr(report_ui, "recorder", trace)
    dialog.load_metrics_button.click()
    _wait(qapplication_session, lambda: dialog.tabular_load_thread is None)
    assert dialog.tabular_load_result is not None
    dialog.set_df_for_grouping(pd.DataFrame({
        "REPORT_ID": list(range(1, 9)), "GROUP": ["SYNTHETIC_A", "SYNTHETIC_B"] * 4,
    }))
    dialog.set_grouping_applied(True)
    dialog.workbook_checkbox.setChecked(True)
    dialog.output_dashboard_file = str(tmp_path / "result.html")
    dialog.output_workbook_file = str(tmp_path / "result.xlsx")
    dialog._sync_ui_state()
    assert dialog.start_button.isEnabled()
    with _owned_notifications(qapplication_session, dialog) as (errors, notifications):
        dialog.start_button.click()
        _wait(qapplication_session, lambda: dialog.analytics_thread is None, seconds=40)
        assert not errors and len(notifications) == 1
    assert (tmp_path / "result.xlsx").is_file()
    assert BugReportAction.ANALYSIS_FINISHED in [item.action for item in trace.snapshot().events]
    window.report_problem_action.trigger()
    report_dialog = window.findChild(SafeBugReportDialog)
    assert report_dialog is not None and report_dialog.isVisible()
    try:
        report_dialog.copy_button.click()
        report = QGuiApplication.clipboard().text()
        assert report == report_dialog.preview.toPlainText()
        assert str(source) not in report
        assert "LOT-1" not in report
        assert str(tmp_path) not in report
        assert ".metroliza-analytics-" not in report
        context = parse_v2_report(report)["context"]
        operation_id, = (item["operation_id"] for item in context["options"] if item["kind"] == "csv_analysis")
        events = [event["temporary_resource"] for event in context["events"] if event["kind"] == "temporary_resource"]
        assert len(events) == 4
        assert {event["kind"] for event in events} == {"analytics_dashboard_staging", "analytics_workbook_staging"}
        assert len({event["resource_id"] for event in events}) == 2
        for created, transferred in zip(events[::2], events[1::2], strict=True):
            assert set(created) == {"kind", "phase", "resource_id", "size", "operation_id"}
            assert created == {
                **transferred, "phase": "created", "size": None, "operation_id": operation_id,
            }
            assert transferred["operation_id"] == operation_id
            assert transferred["phase"] == "transferred"
            assert transferred["size"] == "under_1_mib"
        assert match_safe_bugreport(report).status == "SCENARIO_MATCHED"
    finally:
        report_dialog.close()


@pytest.mark.parametrize(("failure", "signal"), [
    (None, "result_ready"),
    (AnalyticsCancelled, "cancelled"),
    (RuntimeError, "error_occurred"),
])
def test_analytics_worker_clears_resource_correlation_after_each_outcome(
    qapplication_session, monkeypatch, tmp_path, failure, signal,
):
    trace = SafeBugReportRecorder()
    monkeypatch.setattr(safe_bugreport, "recorder", trace)
    token = trace.record_option_snapshot(OptionSnapshotKind.CSV_ANALYSIS, {"html": True})
    assert token is not None
    source = tmp_path / "synthetic.csv"
    source.write_text("value\n1\n")

    def observe():
        safe_bugreport.record_temporary_resource(
            TemporaryResourceKind.ANALYTICS_DASHBOARD_STAGING, TemporaryResourcePhase.CREATED,
        )

    def render(thread, _runner):
        observe()
        if thread is worker and failure is not None:
            raise failure("synthetic")
        return object()

    monkeypatch.setattr(IndustrialAnalyticsThread, "_run_tabular_analytics", render)
    worker = IndustrialAnalyticsThread(
        source_kind="tabular_file", input_file=str(source), output_dashboard_file=str(tmp_path / "output.html"),
    )
    worker._bugreport_option_token = token
    legacy_worker = IndustrialAnalyticsThread(
        source_kind="tabular_file", input_file=str(source), output_dashboard_file=str(tmp_path / "older.html"),
    )
    outcomes = []
    getattr(worker, signal).connect(outcomes.append)
    legacy_worker.result_ready.connect(outcomes.append)

    # Running synchronously reuses one execution context, so a leaked token is observable.
    worker.run()
    observe()
    legacy_worker.run()

    assert len(outcomes) == 2
    resources = [event.temporary_resource for event in trace.context_snapshot().events if event.temporary_resource]
    assert [item.operation_id for item in resources] == [token, None, None]

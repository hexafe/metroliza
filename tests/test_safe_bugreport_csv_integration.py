"""The real CSV request boundary emits only allowlisted diagnostic facts."""

import pandas as pd

from metroliza.industrial.industrial_workers import IndustrialAnalyticsThread
from metroliza.shared.safe_bugreport import (
    BugReportAction,
    BugReportCategory,
    SafeBugReportRecorder,
    build_bug_report_markdown,
)
from metroliza.tabular.tabular_analytics_service import (
    TabularColumnFilter,
    load_tabular_analytics_file,
)
from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog
import metroliza.ui.industrial_analytics_dialog as analytics_ui


def test_csv_request_records_options_without_source_data(qapplication_session, monkeypatch, tmp_path):
    marker = "private_marker_only_for_test_947a"
    source = tmp_path / f"{marker}.csv"
    pd.DataFrame({"ID": [marker, "B"], "Line": [marker, "West"], "Value": [1, 2]}).to_csv(source, index=False)
    loaded = load_tabular_analytics_file(source, force_sqlite=True)
    trace = SafeBugReportRecorder()
    history_root = tmp_path / "safe-history"
    assert trace.configure_history(history_root)
    assert trace.flush(5)
    monkeypatch.setattr(analytics_ui, "_bugreport_recorder", trace)
    monkeypatch.setattr(IndustrialAnalyticsThread, "start", lambda self: None)
    window = IndustrialAnalyticsDialog(source_kind="tabular_file", input_file=str(source), tabular_load_result=loaded)
    try:
        window.show()
        qapplication_session.processEvents()
        window.workbook_checkbox.setChecked(True)
        window.output_dashboard_file = str(tmp_path / f"{marker}.html")
        window.output_workbook_file = str(tmp_path / f"{marker}.xlsx")
        window.tabular_column_filters = (TabularColumnFilter(column="line", selected_values=(marker,)),)
        window.set_df_for_grouping(pd.DataFrame({"REPORT_ID": [1], "GROUP": [marker]}))
        window.set_grouping_applied(True)
        window._sync_ui_state()
        window.show_loading_screen()
        actions = [event.action for event in trace.snapshot().events]
        assert BugReportAction.ANALYSIS_STARTED in actions
        assert BugReportAction.GROUPING_APPLIED in actions
        report = build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, trace.snapshot())
        assert marker not in report
        assert str(tmp_path) not in report
        assert "option_workbook" in report
        assert trace.flush(5)
        stored = (history_root / "activity.json").read_text(encoding="ascii")
        assert marker not in stored
        assert str(tmp_path) not in stored
    finally:
        if window.analytics_thread is not None:
            window.analytics_thread.finished.emit()
        window.close()
        assert trace.close_history(5)

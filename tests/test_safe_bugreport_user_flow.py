"""Real synthetic CSV worker, report menu, clipboard and replay matching."""

import pandas as pd
from PyQt6.QtGui import QGuiApplication

from metroliza.shared.safe_bugreport import BugReportAction, SafeBugReportRecorder
from metroliza.ui.safe_bugreport_dialog import SafeBugReportDialog
import metroliza.ui.safe_bugreport_dialog as report_ui
import metroliza.ui.industrial_analytics_dialog as analytics_ui
from scripts.reproduce_safe_bugreport import match_safe_bugreport
from tests.test_csv_progress_nonmodal import owner, _owned_notifications, _wait  # noqa: F401


def test_real_csv_analysis_can_be_reported_and_matched(owner, qapplication_session, tmp_path, monkeypatch):  # noqa: F811
    window, dialog, source = owner
    trace = SafeBugReportRecorder()
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
        assert match_safe_bugreport(report).status == "SCENARIO_MATCHED"
    finally:
        report_dialog.close()

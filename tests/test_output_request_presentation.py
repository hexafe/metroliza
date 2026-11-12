"""Output choices and request-bound scope presentation without running analysis."""
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialog, QLineEdit, QMessageBox

from metroliza.industrial.industrial_workers import IndustrialAnalyticsThread
from metroliza.shared.filter_state import FilterState
from metroliza.tabular.tabular_analytics_service import load_tabular_analytics_file, TabularColumnFilter
from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog
from metroliza.ui.output_request_summary import analytics_summary
from tests.test_export_dialog_behavior import _build_dialog
import metroliza.ui.export_dialog as export_module


class _ExportThread(QThread):
    update_label = pyqtSignal(str)
    update_progress = pyqtSignal(int)
    error_occurred = pyqtSignal(str)
    completed = pyqtSignal(object)
    canceled = pyqtSignal()

    def start(self):
        self.started = True

    def stop_exporting(self):
        self.stopped = True


@pytest.mark.parametrize("workbook", [False, True])
def test_csv_visible_outputs_and_frozen_summary_use_worker_scope(qapplication_session, monkeypatch, tmp_path, workbook):
    source = tmp_path / "current.csv"
    pd.DataFrame({"ID": ["A", "B"], "Line": ["East", "West"], "Value": [1, 2]}).to_csv(source, index=False)
    loaded = load_tabular_analytics_file(source, force_sqlite=True)
    window = IndustrialAnalyticsDialog(source_kind="tabular_file", input_file=str(source), tabular_load_result=loaded)
    monkeypatch.setattr(IndustrialAnalyticsThread, "start", lambda self: None)
    try:
        window.show()
        qapplication_session.processEvents()
        assert not window.advanced_options_container.isVisible()
        assert window.workbook_checkbox.isVisibleTo(window)
        assert window.workbook_path_field.isVisibleTo(window)
        assert not window.advanced_options_container.isAncestorOf(window.workbook_checkbox)
        # Checkbox changes must never call validation or capture/scan grouping for presentation.
        with monkeypatch.context() as guard:
            guard.setattr(window, "_build_analytics_request", lambda **_k: pytest.fail("draft validated input"))
            window.workbook_checkbox.setChecked(workbook)
        window.output_dashboard_file = str(tmp_path / "chosen.html")
        window.output_workbook_file = str(tmp_path / "chosen.xlsx")
        window.tabular_column_filters = (TabularColumnFilter(column="line", selected_values=("East",)),)
        window.tabular_filter_expression = "Value > 0"
        window.set_df_for_grouping(pd.DataFrame({"REPORT_ID": [1], "GROUP": ["East group"]}))
        window.set_grouping_applied(True)
        window._sync_ui_state()
        assert "Draft" in window.request_summary_label.text()
        assert "chosen.html" in window.request_summary_label.text()
        window.show_loading_screen()
        request = window.analytics_thread.request
        assert request.input_file == str(source)
        assert request.tabular_column_filters[0].selected_values == ("East",)
        assert request.tabular_filter_expression == "Value > 0"
        assert request.grouping_df[0].report_id == 1
        assert request.output_workbook_file == (str(tmp_path / "chosen.xlsx") if workbook else "")
        assert window.request_summary_label.text() == analytics_summary(request)[0]
        assert "East" in window.request_summary_label.text()
        assert window._pending_analytics_request is None
        assert window._pending_grouping_snapshot is None
    finally:
        if window.analytics_thread is not None:
            window.analytics_thread.finished.emit()
        window.close()


@pytest.mark.parametrize("mode", ["xlsx", "sidecar", "html", "google"])
def test_export_frozen_summary_uses_post_collision_request(qapplication_session, monkeypatch, tmp_path, mode):
    window = _build_dialog(monkeypatch, tmp_path, db_file=str(tmp_path / "source.db"))
    captured = []
    thread = _ExportThread()
    monkeypatch.setattr(export_module, "create_export_data_thread", lambda request: captured.append(request) or thread)
    monkeypatch.setattr(export_module, "save_export_dialog_config", lambda *_a: None)
    try:
        window.excel_file = tmp_path / "chosen.xlsx"
        if mode == "html":
            window.preset_combobox.setCurrentText("HTML dashboard only")
        window.generate_html_dashboard_checkbox.setChecked(mode in {"sidecar", "html"})
        window.include_google_sheets_checkbox.setChecked(mode == "google")
        window.set_filter_query("SELECT * FROM reports WHERE REFERENCE = 'East'")
        window.set_filter_state(FilterState(reference_values=("East",)))
        window.set_df_for_grouping(pd.DataFrame({"REPORT_ID": [1], "GROUP": ["Chosen"]}) if mode == "sidecar" else None)
        window.set_grouping_applied(mode == "sidecar")
        window._update_export_button_enabled_state()
        original_confirm = window._confirm_output_publication

        def choose_copy(request):
            # Publication may choose a different destination; summary must describe that request.
            paths = replace(request.paths,
                            excel_file=str(tmp_path / "copy.xlsx") if request.paths.excel_file else None,
                            html_dashboard_file=str(tmp_path / "copy.html") if not request.paths.excel_file else None)
            return replace(request, paths=paths)

        monkeypatch.setattr(window, "_confirm_output_publication", choose_copy)
        window.show_loading_screen()
        assert len(captured) == 1
        request = captured[0]
        assert request.filter_query.endswith("REFERENCE = 'East'")
        assert window.request_summary_label.text() == window._export_request_summary(request)[0]
        assert "Launch request" in window.request_summary_label.text()
        assert "copy" in window.request_summary_label.text()
        assert "source.db" in window.request_summary_label.text()
        assert "East" in window.request_summary_label.text()
        assert bool(request.paths.excel_file) is (mode != "html")
        assert request.options.generate_html_dashboard is (mode in {"sidecar", "html"})
        if mode == "sidecar":
            assert request.grouping_df[0].report_id == 1
            assert "copy_dashboard.html" in window.request_summary_label.text()
        if mode == "google":
            assert "local workbook + upload attempt" in window.request_summary_label.text()
        monkeypatch.setattr(window, "_confirm_output_publication", original_confirm)
    finally:
        thread.finished.emit()
        window.close()


def test_export_does_not_launch_stale_database_after_output_prompt(qapplication_session, monkeypatch, tmp_path):
    window = _build_dialog(monkeypatch, tmp_path, db_file=str(tmp_path / "first.db"))
    window.excel_file = tmp_path / "chosen.xlsx"
    captured = []
    messages = []
    monkeypatch.setattr(export_module, "create_export_data_thread", lambda request: captured.append(request))
    monkeypatch.setattr(QMessageBox, "information", lambda *_a: messages.append(_a[-1]))

    def change_database(request):
        window._update_database_context(str(tmp_path / "second.db"))
        return request

    monkeypatch.setattr(window, "_confirm_output_publication", change_database)
    try:
        window.show_loading_screen()
        assert not captured
        assert "second.db" in window.request_summary_label.text()
        assert messages and "Settings changed" in messages[0]
    finally:
        window.close()


def test_output_shortcuts_preserve_text_and_modal_child_isolation(qapplication_session, monkeypatch, tmp_path):
    window = _build_dialog(monkeypatch, tmp_path)
    calls = []
    # Replace the signal receiver, retaining the actual disabled-aware button path.
    window.export_button.clicked.disconnect()
    window.export_button.clicked.connect(lambda: calls.append("generate"))
    window.show()
    window.activateWindow()
    qapplication_session.processEvents()
    edit = window.violin_plot_min_samplesize
    edit.setFocus()
    QTest.keyClick(edit, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert not calls  # missing database/output keeps primary disabled
    window.db_file = str(tmp_path / "source.db")
    window.excel_file = Path(tmp_path / "chosen.xlsx")
    window._update_export_button_enabled_state()
    QTest.keyClick(edit, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert calls == ["generate"]
    edit.setText("123")
    QTest.keyClick(edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert edit.selectedText() == "123"
    child = QDialog(window)
    child.setWindowModality(Qt.WindowModality.WindowModal)
    child_edit = QLineEdit(child)
    child.show()
    child.activateWindow()
    child_edit.setFocus()
    qapplication_session.processEvents()
    QTest.keyClick(child_edit, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert calls == ["generate"]
    child.close()
    window.close()


def test_analytics_rejects_changed_source_during_progress_admission(qapplication_session, monkeypatch, tmp_path):
    import metroliza.ui.industrial_analytics_dialog as module

    window = IndustrialAnalyticsDialog(source_kind="tabular_file", input_file="first.csv")
    warnings = []
    original_progress = module.create_worker_progress_dialog

    def change_source(*args, **kwargs):
        result = original_progress(*args, **kwargs)
        window.input_file = "second.csv"
        return result

    monkeypatch.setattr(module, "create_worker_progress_dialog", change_source)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a: warnings.append(_a[-1]))
    try:
        window.show_loading_screen()
        assert window.analytics_thread is None
        assert window._pending_analytics_request is None
        assert warnings and "Source changed" in warnings[0]
        assert not window.loading_dialog.isVisible()
    finally:
        window.close()


def test_csv_filter_group_reopen_and_clear_update_draft_and_next_worker(qapplication_session, monkeypatch, tmp_path):
    from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog

    source = tmp_path / "scope.csv"
    pd.DataFrame({"Line": ["East", "West"], "Value": [1, 2]}).to_csv(source, index=False)
    loaded = load_tabular_analytics_file(source, force_sqlite=True)
    window = IndustrialAnalyticsDialog(source_kind="tabular_file", input_file=str(source), tabular_load_result=loaded)
    monkeypatch.setattr(IndustrialAnalyticsThread, "start", lambda self: None)

    def apply_same_grouping(dialog):
        dialog.use_grouping()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TabularAnalyticsGroupingDialog, "exec", apply_same_grouping)
    try:
        window.tabular_column_filters = (TabularColumnFilter(column="line", selected_values=("East",)),)
        window.set_df_for_grouping(pd.DataFrame({"REPORT_ID": [1], "GROUP": ["Chosen"]}))
        window.set_grouping_applied(True)
        window._sync_ui_state()
        filtered_draft = window.request_summary_label.text()
        assert "Draft" in filtered_draft
        assert "line" in filtered_draft.lower()
        assert "East" in filtered_draft and "Chosen" in filtered_draft
        window.tabular_column_filters = (TabularColumnFilter(column="line", selected_values=("West",)),)
        window._sync_ui_state()
        assert "West" in window.request_summary_label.text() and "East" not in window.request_summary_label.text()
        window.tabular_column_filters = (TabularColumnFilter(column="line", selected_values=("East",)),)
        window._sync_ui_state()
        window.open_grouping_dialog()  # actual constructor + Use grouping, unchanged logical assignments
        window.show_loading_screen()
        first = window.analytics_thread.request
        assert [(row.report_id, row.group) for row in first.grouping_df] == [(1, "Chosen")]
        assert first.tabular_column_filters[0].selected_values == ("East",)
        assert "East" in window.request_summary_label.text()
        window.analytics_thread.finished.emit()
        window.clear_tabular_filter_and_groups()  # existing clear contract clears both dependent states
        cleared_draft = window.request_summary_label.text()
        assert cleared_draft != filtered_draft
        assert "East" not in cleared_draft
        window.show_loading_screen()
        second = window.analytics_thread.request
        assert second is not first
        assert second.tabular_column_filters == ()
        assert second.tabular_filter_expression == ""
        assert second.grouping_df is None
        assert "East" not in window.request_summary_label.text()
        assert "Launch request" in window.request_summary_label.text()
    finally:
        if window.analytics_thread is not None:
            window.analytics_thread.finished.emit()
        window.close()


def test_export_cancelled_output_choice_cannot_retain_request_for_next_launch(qapplication_session, monkeypatch, tmp_path):
    window = _build_dialog(monkeypatch, tmp_path, db_file=str(tmp_path / "first.db"))
    window.excel_file = tmp_path / "first.xlsx"
    captured = []
    thread = _ExportThread()
    monkeypatch.setattr(export_module, "create_export_data_thread", lambda request: captured.append(request) or thread)
    monkeypatch.setattr(export_module, "save_export_dialog_config", lambda *_a: None)
    monkeypatch.setattr(window, "_confirm_output_publication", lambda request: None)
    try:
        window.show_loading_screen()
        assert not captured and window.export_thread is None
        window._update_database_context(str(tmp_path / "second.db"))
        window.excel_file = tmp_path / "second.xlsx"
        monkeypatch.setattr(window, "_confirm_output_publication", lambda request: request)
        window.show_loading_screen()
        assert len(captured) == 1
        assert captured[0].paths.db_file.endswith("second.db")
        assert captured[0].paths.excel_file.endswith("second.xlsx")
        assert "second.db" in window.request_summary_label.text()
    finally:
        thread.finished.emit()
        window.close()


def test_analytics_native_start_error_clears_prepared_request(qapplication_session, monkeypatch, tmp_path):
    window = IndustrialAnalyticsDialog(source_kind="tabular_file", input_file="first.csv")
    monkeypatch.setattr(IndustrialAnalyticsThread, "start", lambda _self: (_ for _ in ()).throw(RuntimeError("start error")))
    try:
        with pytest.raises(RuntimeError, match="start error"):
            window.show_loading_screen()
        assert window._pending_analytics_request is None
        assert window._pending_grouping_snapshot is None
        window.analytics_thread.finished.emit()
        window.input_file = "second.csv"
        monkeypatch.setattr(IndustrialAnalyticsThread, "start", lambda _self: None)
        window.show_loading_screen()
        assert window.analytics_thread.request.input_file == "second.csv"
        assert "second.csv" in window.request_summary_label.text()
    finally:
        if window.analytics_thread is not None:
            window.analytics_thread.finished.emit()
        window.close()


@pytest.mark.parametrize("kind", ["csv", "export"])
def test_output_summary_and_disabled_reason_stay_with_primary_actions(
    qapplication_session, monkeypatch, tmp_path, kind,
):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QScrollArea
    from metroliza.ui import ui_foundation

    monkeypatch.setattr(ui_foundation, "_available_window_size", lambda *_a: (1240, 680))
    window = (_build_dialog(monkeypatch, tmp_path) if kind == "export"
              else IndustrialAnalyticsDialog(source_kind="tabular_file"))
    try:
        window.show()
        qapplication_session.processEvents()
        window.resize(760, 560)
        qapplication_session.processEvents()
        assert (window.width(), window.height()) == (760, 560)
        primary = window.export_button if kind == "export" else window.start_button
        readiness = window.path_readiness_label if kind == "export" else window.readiness_label
        scroll = window.content_scroll_area if kind == "export" else window.findChild(QScrollArea)
        assert not primary.isEnabled()
        assert readiness.text()
        for control in (primary, window.close_button, readiness, window.request_summary_label):
            assert control.isVisibleTo(window)
            assert not scroll.isAncestorOf(control)
            rect = control.rect().translated(control.mapTo(window, QPoint()))
            assert window.rect().contains(rect)
    finally:
        window.close()

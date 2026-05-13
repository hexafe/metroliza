from __future__ import annotations

import sys
import time
import types

import pandas as pd

from tests.industrial_analytics_fixtures import seed_production_analytics_cache

try:
    from PyQt6.QtWidgets import QApplication
    from modules.industrial_analytics_dialog import (
        build_analytics_completion_message,
        IndustrialAnalyticsDialog,
        MetricSelectionDialog,
        SOURCE_PRODUCTION_CACHE,
        SOURCE_TABULAR_FILE,
    )
    from modules.industrial_analytics_filter_dialog import IndustrialAnalyticsFilterDialog
    from modules.industrial_analytics_state import ProductionFilterState, ProductionMetricSelection
    from modules.industrial_workers import IndustrialAnalyticsThread
except ImportError as exc:  # pragma: no cover - environment/order dependent
    build_analytics_completion_message = None
    QApplication = None
    IndustrialAnalyticsDialog = None
    IndustrialAnalyticsFilterDialog = None
    IndustrialAnalyticsThread = None
    MetricSelectionDialog = None
    ProductionFilterState = None
    ProductionMetricSelection = None
    SOURCE_PRODUCTION_CACHE = "production_cache"
    SOURCE_TABULAR_FILE = "tabular_file"
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

_APP = None


def _app():
    if PYQT_IMPORT_ERROR is not None:
        import pytest

        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def _wait_for_tabular_load(dialog, *, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    app = _app()
    while dialog.tabular_load_thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert dialog.tabular_load_thread is None


def test_production_analytics_dialog_loads_cached_metric_candidates(tmp_path) -> None:
    _app()
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)

    dialog = IndustrialAnalyticsDialog(db_file=db_path, source_kind=SOURCE_PRODUCTION_CACHE)
    try:
        dialog.load_metrics()

        metric_labels = [
            dialog.metrics_list.item(index).text()
            for index in range(dialog.metrics_list.count())
        ]
        group_values = [
            dialog.group_field_combo.itemData(index)
            for index in range(dialog.group_field_combo.count())
        ]
        assert "Cycle Time S" in metric_labels
        assert "line" in group_values
        assert dialog.start_button.isEnabled()
    finally:
        dialog.close()


def test_production_analytics_dialog_passes_filter_state_to_worker(tmp_path) -> None:
    _app()
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)

    dialog = IndustrialAnalyticsDialog(db_file=db_path, source_kind=SOURCE_PRODUCTION_CACHE)
    try:
        dialog.filter_state = ProductionFilterState(references=("REF-100",), stations=("S1",))
        dialog.load_metrics()

        assert "Reference: REF-100" in dialog.filter_summary_label.text()
        thread = dialog.create_analytics_thread()
        assert thread.filter_state.references == ("REF-100",)
        assert thread.filter_state.stations == ("S1",)
    finally:
        dialog.close()


def test_production_filter_dialog_builds_fixed_and_dynamic_filters() -> None:
    _app()
    dialog = IndustrialAnalyticsFilterDialog()
    try:
        dialog.source_profile_ids_field.setText("1, 2")
        dialog.time_start_field.setText("2026-05-10T00:00:00Z")
        dialog.time_end_field.setText("2026-05-11T00:00:00Z")
        dialog.text_fields["stations"].setText("S1; S2")
        dialog.text_fields["references"].setText("REF-100 REF-200")
        dialog.dynamic_filters_edit.setPlainText(
            "cycle_time_s gt 40\nfixture_text_code contains alpha\ncavity in 1,2"
        )

        state = dialog.current_state()

        assert state.source_profile_ids == (1, 2)
        assert state.time_start == "2026-05-10T00:00:00Z"
        assert state.time_end == "2026-05-11T00:00:00Z"
        assert state.stations == ("S1", "S2")
        assert state.references == ("REF-100", "REF-200")
        assert [dynamic_filter.field_name for dynamic_filter in state.dynamic_filters] == [
            "cycle_time_s",
            "fixture_text_code",
            "cavity",
        ]
        assert state.dynamic_filters[0].operator == "gt"
        assert state.dynamic_filters[2].values == ("1", "2")
    finally:
        dialog.close()


def test_tabular_analytics_dialog_loads_csv_metrics_and_group_columns(tmp_path) -> None:
    _app()
    input_file = tmp_path / "table.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "Reference ID": ["R1", "R1", "R2", "R2"],
            "Line": ["L1", "L2", "L1", "L2"],
            "Length mm": [10.0, 10.2, 10.1, 10.4],
            "Width mm": [5.0, 5.2, 5.1, 5.4],
        }
    ).to_csv(input_file, index=False)

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.input_file = str(input_file)
        dialog.output_dashboard_file = str(tmp_path / "table_analytics.html")
        dialog.output_workbook_file = str(tmp_path / "table_analytics.xlsx")
        dialog.load_metrics()

        metric_labels = [
            dialog.metrics_list.item(index).text()
            for index in range(dialog.metrics_list.count())
        ]
        group_values = [
            dialog.group_field_combo.itemData(index)
            for index in range(dialog.group_field_combo.count())
        ]
        assert {"Length Mm", "Width Mm"}.issubset(metric_labels)
        assert "line" in group_values
        assert dialog.timestamp_column_combo.currentData() == "time_stamp"
        assert dialog.reference_column_combo.currentData() == "reference_id"
        assert dialog.start_button.isEnabled()
        thread = dialog.create_analytics_thread()
        assert thread.timestamp_column == "time_stamp"
        assert thread.reference_column == "reference_id"
    finally:
        dialog.close()


def test_tabular_analytics_dialog_uses_part_id_wording_and_delimiters() -> None:
    _app()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.references_edit.setPlainText("R1,R2; R3\nR4")

        assert dialog.reference_column_row_label.text() == "Part / ID column"
        assert "comma, semicolon, space, or new line" in dialog.references_edit.placeholderText()
        assert dialog._cohort_state().references == ("R1", "R2", "R3", "R4")
    finally:
        dialog.close()


def test_tabular_analytics_dialog_auto_loads_metrics_after_file_selection(
    tmp_path,
    monkeypatch,
) -> None:
    _app()
    input_file = tmp_path / "table.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=3, freq="h"),
            "Reference ID": ["R1", "R2", "R3"],
            "Length mm": [10.0, 10.2, 10.4],
            "Width mm": [5.0, 5.2, 5.4],
        }
    ).to_csv(input_file, index=False)
    monkeypatch.setattr(
        "modules.industrial_analytics_dialog.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(input_file), "CSV (*.csv)"),
    )

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.select_input_file()
        _wait_for_tabular_load(dialog)

        assert dialog.input_file == str(input_file)
        assert dialog.metrics_list.count() == 2
        assert dialog.metrics_summary_label.text() == "2 of 2 metrics selected"
        assert dialog.choose_metrics_button.isEnabled()
        assert dialog.load_metrics_button.text() == "Reload CSV/Excel data"
        assert not dialog.filter_row_label.isHidden()
        assert not dialog.filter_summary_label.isHidden()
        assert not dialog.filters_button.isHidden()
        assert dialog.start_button.isEnabled()

        dialog.timestamp_column_combo.setCurrentIndex(0)

        assert dialog.metric_candidates == ()
        assert dialog.metrics_list.count() == 0
        assert dialog.load_metrics_button.text() == "Load CSV/Excel data"
        assert dialog.filter_row_label.isHidden()
        assert dialog.filter_summary_label.isHidden()
        assert dialog.filters_button.isHidden()
        assert not dialog.start_button.isEnabled()
    finally:
        dialog.close()


def test_tabular_analytics_dialog_lists_excel_sheets_after_file_selection(
    tmp_path,
    monkeypatch,
) -> None:
    _app()
    input_file = tmp_path / "table.xlsx"
    with pd.ExcelWriter(input_file) as writer:
        pd.DataFrame({"Length mm": [10.0, 10.2]}).to_excel(
            writer,
            index=False,
            sheet_name="FirstLine",
        )
        pd.DataFrame({"Width mm": [5.0, 5.2]}).to_excel(
            writer,
            index=False,
            sheet_name="SecondLine",
        )
    monkeypatch.setattr(
        "modules.industrial_analytics_dialog.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(input_file), "Excel (*.xlsx)"),
    )

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.select_input_file()
        _wait_for_tabular_load(dialog)

        sheet_names = [
            dialog.sheet_name_combo.itemText(index)
            for index in range(dialog.sheet_name_combo.count())
        ]
        assert sheet_names == ["FirstLine", "SecondLine"]
        assert dialog.sheet_name_combo.isEnabled()
        assert dialog.metrics_list.count() == 1
        assert dialog.metrics_list.item(0).text() == "Length Mm"

        dialog.sheet_name_combo.setCurrentIndex(1)
        assert dialog.metric_candidates == ()
        dialog.load_metrics()

        assert dialog.metrics_list.count() == 1
        assert dialog.metrics_list.item(0).text() == "Width Mm"
    finally:
        dialog.close()


def test_tabular_row_filter_is_summarized_passed_to_worker_and_used_for_grouping(
    tmp_path,
    monkeypatch,
) -> None:
    _app()
    input_file = tmp_path / "table.csv"
    pd.DataFrame(
        {
            "TraceCode": ["TC-001", "TC-002", "TC-003"],
            "Batch": ["B1", "B2", "B1"],
            "Length mm": [10.0, 10.2, 10.4],
        }
    ).to_csv(input_file, index=False)
    calls = {}

    class FakeGroupingDialog:
        def __init__(self, parent, *, dataframe, column_mapping, grouping_dataframe):
            calls["parent"] = parent
            calls["rows"] = len(dataframe.index)
            calls["tracecodes"] = tuple(dataframe["tracecode"])
            calls["column_mapping"] = column_mapping
            calls["grouping_dataframe"] = grouping_dataframe

        def exec(self):
            calls["executed"] = True
            return 0

    monkeypatch.setattr(
        "modules.industrial_analytics_dialog.TabularAnalyticsGroupingDialog",
        FakeGroupingDialog,
    )

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.input_file = str(input_file)
        dialog.load_metrics()
        dialog.tabular_filter_columns = ("tracecode",)
        dialog.tabular_filter_keys = (("TC-001",), ("TC-003",))
        dialog._sync_ui_state()

        assert dialog.filter_summary_label.text() == "TraceCode: 2 selected, 2 rows"
        assert dialog.start_button.isEnabled()

        thread = dialog.create_analytics_thread()
        assert thread.tabular_filter_columns == ("tracecode",)
        assert thread.tabular_filter_keys == (("TC-001",), ("TC-003",))

        dialog.open_grouping_dialog()

        assert calls["rows"] == 2
        assert calls["tracecodes"] == ("TC-001", "TC-003")
        assert calls["column_mapping"]["TraceCode"] == "tracecode"
        assert calls["executed"] is True
    finally:
        dialog.close()


def test_tabular_analytics_dialog_starts_with_load_before_row_filter() -> None:
    _app()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        assert dialog.load_metrics_button.text() == "Load CSV/Excel data"
        assert dialog.filter_row_label.isHidden()
        assert dialog.filter_summary_label.isHidden()
        assert dialog.filters_button.isHidden()
    finally:
        dialog.close()


def test_tabular_analytics_dialog_uses_manual_groups_for_aggregation_state() -> None:
    _app()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        grouping_df = pd.DataFrame(
            {
                "REPORT_ID": [1, 2, 3],
                "GROUP": ["Selected", "POPULATION", "POPULATION"],
            }
        )
        dialog.metric_candidates = (
            ProductionMetricSelection("length_mm", "Length Mm"),
        )
        dialog._populate_metrics()
        dialog.set_df_for_grouping(grouping_df)
        dialog.set_grouping_applied(True)

        thread = dialog.create_analytics_thread()

        assert thread.grouping_df is grouping_df
        assert thread.aggregation_state.group_fields == ("GROUP",)
        assert dialog.grouping_summary_label.text() == "Groups: 1 custom + POPULATION"
    finally:
        dialog.close()


def test_tabular_groupstats_is_disabled_until_manual_groups_are_available() -> None:
    _app()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.metric_candidates = (ProductionMetricSelection("length_mm", "Length Mm"),)
        dialog._populate_metrics()
        dialog._sync_ui_state()

        assert not dialog.groupstats_checkbox.isEnabled()
        assert not dialog.groupstats_checkbox.isChecked()

        grouping_df = pd.DataFrame(
            {
                "REPORT_ID": [1, 2],
                "GROUP": ["Fixture A", "POPULATION"],
            }
        )
        dialog.set_df_for_grouping(grouping_df)
        dialog.set_grouping_applied(True)
        dialog._sync_ui_state()

        assert dialog.groupstats_checkbox.isEnabled()
    finally:
        dialog.close()


def test_metric_limits_dialog_applies_absolute_one_sided_limits_to_worker_metric() -> None:
    _app()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.input_file = "table.csv"
        dialog.output_dashboard_file = "table_analytics.html"
        dialog.metric_candidates = (ProductionMetricSelection("length_mm", "Length Mm"),)
        dialog._populate_metrics()
        dialog.metric_spec_limits = {"length_mm": (9.5, None)}

        thread = dialog.create_analytics_thread()

        assert thread.metric_selection[0].lsl == 9.5
        assert thread.metric_selection[0].usl is None
    finally:
        dialog.close()


def test_tabular_grouping_dialog_reopens_with_existing_groups_and_column_labels(
    tmp_path,
    monkeypatch,
) -> None:
    _app()
    input_file = tmp_path / "table.csv"
    pd.DataFrame(
        {
            "TraceCode": ["TC-001", "TC-002", "TC-003"],
            "Batch": ["B1", "B1", "B2"],
            "Length mm": [10.0, 10.2, 10.4],
        }
    ).to_csv(input_file, index=False)
    calls = {}

    class FakeGroupingDialog:
        def __init__(self, parent, *, dataframe, column_mapping, grouping_dataframe):
            calls["parent"] = parent
            calls["columns"] = tuple(dataframe.columns)
            calls["column_mapping"] = column_mapping
            calls["grouping_dataframe"] = grouping_dataframe

        def exec(self):
            calls["executed"] = True
            return 0

    monkeypatch.setattr(
        "modules.industrial_analytics_dialog.TabularAnalyticsGroupingDialog",
        FakeGroupingDialog,
    )

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.input_file = str(input_file)
        dialog.load_metrics()
        existing_grouping = pd.DataFrame(
            {
                "REPORT_ID": [1, 3],
                "GROUP": ["Fixture A", "Fixture B"],
            }
        )
        dialog.set_df_for_grouping(existing_grouping)
        dialog.set_grouping_applied(True)

        dialog.open_grouping_dialog()

        assert calls["parent"] is dialog
        assert "tracecode" in calls["columns"]
        assert calls["column_mapping"]["TraceCode"] == "tracecode"
        assert calls["grouping_dataframe"] is existing_grouping
        assert calls["executed"] is True
    finally:
        dialog.close()


def test_metric_selection_dialog_select_all_and_clear_are_in_large_dialog() -> None:
    _app()
    metrics = (
        ProductionMetricSelection("length_mm", "Length Mm"),
        ProductionMetricSelection("width_mm", "Width Mm"),
    )

    dialog = MetricSelectionDialog(metrics=metrics, selected_fields={"length_mm"})
    try:
        assert [metric.field_name for metric in dialog.selected_metrics()] == ["length_mm"]

        dialog.clear_button.click()
        assert dialog.selected_metrics() == ()
        assert dialog.summary_label.text() == "0 of 2 metrics selected"

        dialog.select_all_button.click()
        assert [metric.field_name for metric in dialog.selected_metrics()] == [
            "length_mm",
            "width_mm",
        ]
        assert dialog.summary_label.text() == "2 of 2 metrics selected"
    finally:
        dialog.close()


def test_metric_selection_dialog_filters_visible_metrics_without_losing_selection() -> None:
    _app()
    metrics = (
        ProductionMetricSelection("length_mm", "Length Mm"),
        ProductionMetricSelection("width_mm", "Width Mm"),
        ProductionMetricSelection("cycle_time_s", "Cycle Time S"),
    )

    dialog = MetricSelectionDialog(metrics=metrics, selected_fields={"length_mm", "cycle_time_s"})
    try:
        dialog.search_field.setText("cycle")

        visible = [
            dialog.metrics_list.item(index).text()
            for index in range(dialog.metrics_list.count())
            if not dialog.metrics_list.item(index).isHidden()
        ]
        assert visible == ["Cycle Time S"]
        assert [metric.field_name for metric in dialog.selected_metrics()] == [
            "length_mm",
            "cycle_time_s",
        ]
    finally:
        dialog.close()


def test_analytics_completion_message_uses_export_style_file_links(tmp_path, monkeypatch) -> None:
    _app()
    dashboard_file = tmp_path / "analytics.html"
    workbook_file = tmp_path / "analytics.xlsx"

    class AnalyticsResult:
        html_dashboard_path = str(dashboard_file)
        workbook_path = str(workbook_file)
        html_dashboard_chart_count = 7
        row_count = 42

    level, title, message, reveal_path = build_analytics_completion_message(AnalyticsResult)
    assert level == "info"
    assert title == "Analytics successful"
    assert f"HTML dashboard: {dashboard_file.resolve().as_uri()}" in message
    assert f"Workbook: {workbook_file.resolve().as_uri()}" in message
    assert "Charts: 7" in message
    assert "Rows analyzed: 42" in message
    assert reveal_path == str(workbook_file)

    calls = []
    fake_export_dialog = types.SimpleNamespace(
        show_export_result_message=lambda parent, level, title, message, excel_file=None: calls.append(
            (parent, level, title, message, excel_file)
        )
    )
    monkeypatch.setitem(sys.modules, "modules.export_dialog", fake_export_dialog)

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.on_analytics_finished(AnalyticsResult)

        assert len(calls) == 1
        assert calls[0][0] is dialog
        assert calls[0][1] == "info"
        assert calls[0][2] == "Analytics successful"
        assert f"HTML dashboard: {dashboard_file.resolve().as_uri()}" in calls[0][3]
        assert f"Workbook: {workbook_file.resolve().as_uri()}" in calls[0][3]
        assert calls[0][4] == str(workbook_file)
    finally:
        dialog.close()


def test_analytics_completion_message_reveals_dashboard_when_workbook_disabled(tmp_path) -> None:
    _app()
    dashboard_file = tmp_path / "analytics.html"

    class AnalyticsResult:
        html_dashboard_path = str(dashboard_file)
        workbook_path = ""
        html_dashboard_chart_count = 4
        row_count = 12

    level, title, message, reveal_path = build_analytics_completion_message(AnalyticsResult)

    assert level == "info"
    assert title == "Analytics successful"
    assert f"HTML dashboard: {dashboard_file.resolve().as_uri()}" in message
    assert "Workbook:" not in message
    assert reveal_path == str(dashboard_file)


def test_analytics_dialog_wires_cancellable_worker_without_running_job(tmp_path) -> None:
    _app()

    class NonStartingAnalyticsThread(IndustrialAnalyticsThread):
        def __init__(self) -> None:
            super().__init__(
                source_kind=SOURCE_PRODUCTION_CACHE,
                output_dashboard_file=str(tmp_path / "analytics.html"),
            )
            self.started = False
            self.cancel_called = False

        def start(self) -> None:
            self.started = True

        def cancel(self) -> None:
            self.cancel_called = True

    thread = NonStartingAnalyticsThread()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_PRODUCTION_CACHE)
    try:
        dialog.create_analytics_thread = lambda: thread

        dialog.show_loading_screen()

        assert dialog.analytics_thread is thread
        assert thread.started
        status_text = "Writing dashboard...\nRendering HTML dashboard (5/6)\n0:04 elapsed, ETA 0:01"
        thread.update_label.emit(status_text)
        assert dialog.loading_label.text() == status_text

        dialog.cancel_analytics()
        assert thread.cancel_called
        assert dialog.loading_label.text() == (
            "Canceling analytics...\n"
            "Waiting for the current analytics step to stop\n"
            "ETA --"
        )

        thread.finished.emit()
        assert dialog.analytics_thread is None
    finally:
        if hasattr(dialog, "loading_dialog"):
            dialog.loading_dialog.close()
        dialog.close()

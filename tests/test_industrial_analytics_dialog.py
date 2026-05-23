from __future__ import annotations

import sys
import time
import types

import pandas as pd

from tests.industrial_analytics_fixtures import seed_production_analytics_cache

try:
    from PyQt6.QtWidgets import QApplication, QDialog
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
    from modules.tabular_analytics_service import (
        TabularColumnFilter,
        cleanup_tabular_load_result,
        load_tabular_analytics_files,
    )
except ImportError as exc:  # pragma: no cover - environment/order dependent
    build_analytics_completion_message = None
    QApplication = None
    cleanup_tabular_load_result = None
    QDialog = None
    IndustrialAnalyticsDialog = None
    IndustrialAnalyticsFilterDialog = None
    IndustrialAnalyticsThread = None
    load_tabular_analytics_files = None
    MetricSelectionDialog = None
    ProductionFilterState = None
    ProductionMetricSelection = None
    TabularColumnFilter = None
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
        assert not dialog.workbook_checkbox.isChecked()
        assert not dialog.workbook_button.isEnabled()
        assert not dialog.parameter_sheets_checkbox.isEnabled()
        assert dialog.start_button.isEnabled()
    finally:
        dialog.close()


def test_reference_cohort_labels_describe_pasted_reference_action(tmp_path) -> None:
    _app()
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)

    dialog = IndustrialAnalyticsDialog(db_file=db_path, source_kind=SOURCE_PRODUCTION_CACHE)
    try:
        group_selected_index = dialog.reference_mode_combo.findData("group_selected")

        assert dialog.reference_mode_combo.itemText(group_selected_index) == "Group pasted references"
        assert "analysis-only cohort" in dialog.reference_mode_combo.toolTip()
        assert "comma, semicolon, space, or new line" in dialog.references_edit.placeholderText()
        assert "only this analytics run" in dialog.reference_mode_hint_label.text()
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
        _wait_for_tabular_load(dialog)

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
        assert not dialog.workbook_checkbox.isChecked()
        assert not dialog.workbook_button.isEnabled()
        assert not dialog.parameter_sheets_checkbox.isEnabled()
        assert dialog.start_button.isEnabled()
        thread = dialog.create_analytics_thread()
        assert thread.output_workbook_file == ""
        assert thread.timestamp_column == "time_stamp"
        assert thread.reference_column == "reference_id"
    finally:
        dialog.close()


def test_tabular_analytics_dialog_uses_workbook_path_only_when_opted_in(tmp_path) -> None:
    _app()
    input_file = tmp_path / "table.csv"
    workbook_file = tmp_path / "table_analytics.xlsx"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "Reference ID": ["R1", "R1", "R2", "R2"],
            "Line": ["L1", "L2", "L1", "L2"],
            "Length mm": [10.0, 10.2, 10.1, 10.4],
        }
    ).to_csv(input_file, index=False)

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.input_file = str(input_file)
        dialog.output_dashboard_file = str(tmp_path / "table_analytics.html")
        dialog.output_workbook_file = str(workbook_file)
        dialog.load_metrics()
        _wait_for_tabular_load(dialog)

        disabled_thread = dialog.create_analytics_thread()
        assert disabled_thread.output_workbook_file == ""
        assert disabled_thread.separate_parameter_sheets is False

        dialog.workbook_checkbox.setChecked(True)
        dialog._sync_ui_state()

        assert dialog.workbook_button.isEnabled()
        assert dialog.parameter_sheets_checkbox.isEnabled()
        enabled_thread = dialog.create_analytics_thread()
        assert enabled_thread.output_workbook_file == str(workbook_file)
        assert enabled_thread.separate_parameter_sheets is True
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


def test_tabular_analytics_dialog_dashboard_detail_mode_is_selectable_and_in_request() -> None:
    _app()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        assert not dialog.dashboard_detail_mode_combo.isHidden()
        assert dialog.dashboard_detail_mode_combo.currentData() == "fast"

        dialog.dashboard_detail_mode_combo.setCurrentIndex(
            dialog.dashboard_detail_mode_combo.findData("full")
        )
        request = dialog._build_analytics_request()

        assert request.dashboard_detail_mode == "full"
    finally:
        dialog.close()


def test_analytics_dashboard_visuals_button_is_visible_for_production_and_tabular(monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(
        "modules.industrial_analytics_dialog.load_dashboard_visual_settings",
        lambda: {"preset": "auto"},
    )
    dialogs = [
        IndustrialAnalyticsDialog(source_kind=SOURCE_PRODUCTION_CACHE),
        IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE),
    ]
    try:
        for dialog in dialogs:
            dialog.show()
        app.processEvents()

        for dialog in dialogs:
            assert dialog.dashboard_visuals_button.isVisible()
            assert dialog.dashboard_visuals_button.isEnabled()
            assert dialog.dashboard_visuals_button.text() == "Dashboard visuals..."
            assert dialog.dashboard_visuals_summary_label.text() == "Auto"
            assert "Adjust dashboard colors" in dialog.dashboard_visuals_button.toolTip()
    finally:
        for dialog in dialogs:
            dialog.close()


def test_analytics_dashboard_visuals_button_launches_dialog(monkeypatch) -> None:
    _app()
    monkeypatch.setattr(
        "modules.industrial_analytics_dialog.load_dashboard_visual_settings",
        lambda: {"preset": "auto"},
    )
    calls = {}

    class FakeDashboardVisualOptionsDialog:
        def __init__(self, parent=None, *, settings=None):
            calls["parent"] = parent
            calls["settings"] = settings

        def exec(self):
            calls["exec_called"] = True
            return QDialog.DialogCode.Accepted

        def visual_settings(self):
            return {"preset": "distinct"}

    monkeypatch.setitem(
        sys.modules,
        "modules.dashboard_visual_options_dialog",
        types.SimpleNamespace(DashboardVisualOptionsDialog=FakeDashboardVisualOptionsDialog),
    )

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        assert dialog.dashboard_visuals_button.isEnabled()

        dialog.open_dashboard_visual_options()

        assert calls["parent"] is dialog
        assert calls["settings"]["preset"] == "auto"
        assert calls["exec_called"] is True
        assert dialog.dashboard_visual_settings["preset"] == "distinct"
        assert dialog.dashboard_visuals_summary_label.text() == "Distinct groups"
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
        "modules.industrial_analytics_dialog.QFileDialog.getOpenFileNames",
        lambda *_args, **_kwargs: ([str(input_file)], "CSV (*.csv)"),
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


def test_tabular_analytics_dialog_loads_multiple_csv_files(
    tmp_path,
    monkeypatch,
) -> None:
    _app()
    first_file = tmp_path / "line_a.csv"
    second_file = tmp_path / "line_b.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=2, freq="h"),
            "Line": ["A", "B"],
            "Length mm": [10.0, 10.2],
        }
    ).to_csv(first_file, index=False)
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-11 08:00", periods=2, freq="h"),
            "Line": ["A", "B"],
            "Length mm": [10.4, 10.6],
        }
    ).to_csv(second_file, index=False)
    monkeypatch.setattr(
        "modules.industrial_analytics_dialog.QFileDialog.getOpenFileNames",
        lambda *_args, **_kwargs: ([str(first_file), str(second_file)], "CSV (*.csv)"),
    )

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.select_input_file()
        _wait_for_tabular_load(dialog)

        assert dialog.input_file == str(first_file)
        assert dialog.input_files == (str(first_file), str(second_file))
        assert dialog.tabular_load_result.storage_mode == "sqlite"
        assert dialog.source_label.text() == "2 CSV files: 4 rows"
        assert dialog.filter_summary_label.text() == "All rows (4)"
        assert dialog.sheet_name_combo.itemText(0) == "CSV files"
        assert not dialog.sheet_name_combo.isEnabled()
        assert dialog.metrics_list.count() == 1
        assert dialog.input_file_field.text().startswith("2 CSV files:")
    finally:
        dialog.close()


def test_tabular_grouping_dialog_uses_sqlite_store_without_materializing_rows(
    tmp_path,
    monkeypatch,
) -> None:
    _app()
    first_file = tmp_path / "line_a.csv"
    second_file = tmp_path / "line_b.csv"
    pd.DataFrame(
        {
            "Line": ["A", "B"],
            "Length mm": [10.0, 10.2],
        }
    ).to_csv(first_file, index=False)
    pd.DataFrame(
        {
            "Line": ["A", "B"],
            "Length mm": [10.4, 10.6],
        }
    ).to_csv(second_file, index=False)
    loaded = load_tabular_analytics_files((first_file, second_file))
    calls = {}

    class FakeGroupingDialog:
        def __init__(
            self,
            parent,
            *,
            dataframe,
            column_mapping,
            grouping_dataframe,
            sqlite_store,
            filter_columns,
            selected_filter_keys,
            column_filters,
        ):
            calls["parent"] = parent
            calls["rows"] = len(dataframe.index)
            calls["column_mapping"] = column_mapping
            calls["grouping_dataframe"] = grouping_dataframe
            calls["sqlite_store"] = sqlite_store
            calls["filter_columns"] = filter_columns
            calls["selected_filter_keys"] = selected_filter_keys
            calls["column_filters"] = column_filters

        def exec(self):
            calls["executed"] = True
            return 0

    def fail_materialize(*_args, **_kwargs):
        raise AssertionError("SQLite-backed grouping should not materialize all tabular rows")

    monkeypatch.setattr(
        "modules.industrial_analytics_dialog.TabularAnalyticsGroupingDialog",
        FakeGroupingDialog,
    )
    monkeypatch.setattr(
        "modules.industrial_analytics_dialog.materialize_tabular_dataframe",
        fail_materialize,
    )

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.tabular_load_result = loaded
        dialog.tabular_column_filters = (TabularColumnFilter("line", selected_values=("A",)),)

        dialog.open_grouping_dialog()

        assert calls["parent"] is dialog
        assert calls["rows"] == len(loaded.dataframe.index)
        assert calls["column_mapping"]["Line"] == "line"
        assert calls["grouping_dataframe"] is None
        assert calls["sqlite_store"] is loaded.sqlite_store
        assert calls["filter_columns"] == ()
        assert calls["selected_filter_keys"] == ()
        assert calls["column_filters"] == (TabularColumnFilter("line", selected_values=("A",)),)
        assert calls["executed"] is True
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


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
        "modules.industrial_analytics_dialog.QFileDialog.getOpenFileNames",
        lambda *_args, **_kwargs: ([str(input_file)], "Excel (*.xlsx)"),
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
        _wait_for_tabular_load(dialog)

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
        _wait_for_tabular_load(dialog)
        dialog.tabular_filter_columns = ("tracecode",)
        dialog.tabular_filter_keys = (("TC-001",), ("TC-003",))
        dialog.tabular_column_filters = (TabularColumnFilter("tracecode", selected_values=("TC-001", "TC-003")),)
        dialog._sync_ui_state()

        assert dialog.filter_summary_label.text() == "TraceCode (2 value(s)): 1 filter(s), 2 rows"
        assert dialog.start_button.isEnabled()

        thread = dialog.create_analytics_thread()
        assert thread.tabular_filter_columns == ("tracecode",)
        assert thread.tabular_filter_keys == (("TC-001",), ("TC-003",))
        assert thread.tabular_column_filters == (
            TabularColumnFilter("tracecode", selected_values=("TC-001", "TC-003")),
        )
        assert thread.tabular_load_result is dialog.tabular_load_result

        dialog.open_grouping_dialog()

        assert calls["rows"] == 2
        assert calls["tracecodes"] == ("TC-001", "TC-003")
        assert calls["column_mapping"]["TraceCode"] == "tracecode"
        assert calls["executed"] is True
    finally:
        dialog.close()


def test_tabular_filter_dialog_accept_uses_column_filters_without_legacy_keys(
    tmp_path,
    monkeypatch,
) -> None:
    _app()
    input_file = tmp_path / "table.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=3, freq="h"),
            "TraceCode": ["TC-001", "TC-002", "TC-003"],
            "Length mm": [10.0, 10.2, 10.4],
        }
    ).to_csv(input_file, index=False)

    class FakeFilterDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def get_column_filters(self):
            return (TabularColumnFilter("tracecode", selected_values=("TC-001",)),)

        def get_filter(self):
            raise AssertionError("legacy filter keys should not be built on accept")

    monkeypatch.setattr(
        "modules.industrial_analytics_dialog.TabularAnalyticsFilterDialog",
        FakeFilterDialog,
    )
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.input_file = str(input_file)
        dialog.load_metrics()
        _wait_for_tabular_load(dialog)
        dialog.open_tabular_filter_dialog()

        assert dialog.tabular_column_filters == (
            TabularColumnFilter("tracecode", selected_values=("TC-001",)),
        )
        assert dialog.tabular_filter_columns == ()
        assert dialog.tabular_filter_keys == ()
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
        assert dialog.clear_filter_button.isHidden()
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

        assert thread.grouping_df is not grouping_df
        assert thread.grouping_df.equals(grouping_df)
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
        assert "manual CSV/Excel groups" in dialog.groupstats_checkbox.toolTip()
        assert "pasted references" in dialog.groupstats_checkbox.toolTip()
        assert not dialog.groupstats_reason_label.isHidden()
        assert "manual CSV/Excel groups" in dialog.groupstats_reason_label.text()
        assert "pasted references" in dialog.groupstats_reason_label.text()

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
        assert dialog.groupstats_checkbox.isChecked()
        assert dialog.groupstats_checkbox.toolTip() == ""
        assert dialog.groupstats_reason_label.isHidden()

        population_only_grouping = pd.DataFrame(
            {
                "REPORT_ID": [1, 2],
                "GROUP": ["POPULATION", "POPULATION"],
            }
        )
        dialog.set_df_for_grouping(population_only_grouping)
        dialog.set_grouping_applied(True)
        dialog._sync_ui_state()

        assert not dialog.groupstats_checkbox.isEnabled()
        assert not dialog.groupstats_checkbox.isChecked()
        assert "at least 2 non-empty manual groups" in dialog.groupstats_checkbox.toolTip()
    finally:
        dialog.close()


def _select_tabular_reference_mode(dialog, mode: str) -> None:
    index = dialog.reference_mode_combo.findData(mode)
    assert index >= 0
    dialog.reference_mode_combo.setCurrentIndex(index)


def _assert_reference_groupstats_mode_enables_request(mode: str) -> None:
    _app()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.metric_candidates = (ProductionMetricSelection("length_mm", "Length Mm"),)
        dialog._populate_metrics()
        dialog._sync_ui_state()

        assert not dialog.groupstats_checkbox.isEnabled()
        assert not dialog.groupstats_checkbox.isChecked()

        _select_tabular_reference_mode(dialog, mode)
        dialog.references_edit.setPlainText("R1\nR2")

        assert dialog.groupstats_checkbox.isEnabled()
        assert dialog.groupstats_checkbox.isChecked()
        assert dialog.groupstats_checkbox.toolTip() == ""
        assert dialog.groupstats_reason_label.isHidden()

        request = dialog._build_analytics_request()
        assert request.grouping_df is None
        assert request.cohort_state.mode == mode
        assert request.cohort_state.references == ("R1", "R2")
        assert request.chart_selection.groupstats is True
    finally:
        dialog.close()


def test_tabular_groupstats_compare_rest_refs_enable_without_manual_groups() -> None:
    _assert_reference_groupstats_mode_enables_request("compare_rest")


def test_tabular_groupstats_group_selected_refs_enable_without_manual_groups() -> None:
    _assert_reference_groupstats_mode_enables_request("group_selected")


def test_tabular_groupstats_toggle_does_not_start_analysis_worker(monkeypatch) -> None:
    _app()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.metric_candidates = (ProductionMetricSelection("length_mm", "Length Mm"),)
        dialog._populate_metrics()
        grouping_df = pd.DataFrame(
            {
                "REPORT_ID": [1, 2],
                "GROUP": ["Fixture A", "POPULATION"],
            }
        )
        dialog.set_df_for_grouping(grouping_df)
        dialog.set_grouping_applied(True)

        def _unexpected_worker(*_args, **_kwargs):
            raise AssertionError("Toggling groupstats should not create an analytics worker")

        monkeypatch.setattr("modules.industrial_analytics_dialog.IndustrialAnalyticsThread", _unexpected_worker)

        dialog.groupstats_checkbox.setChecked(False)
        dialog._sync_ui_state()
        assert not dialog.groupstats_checkbox.isChecked()
        dialog.groupstats_checkbox.setChecked(True)
        dialog._sync_ui_state()

        assert dialog.groupstats_checkbox.isEnabled()
        assert dialog.analytics_thread is None
    finally:
        dialog.close()


def test_tabular_grouping_summary_and_groupstats_do_not_require_population_group() -> None:
    _app()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.metric_candidates = (ProductionMetricSelection("length_mm", "Length Mm"),)
        dialog._populate_metrics()
        grouping_df = pd.DataFrame(
            {
                "REPORT_ID": [1, 2, 3, 4],
                "GROUP": ["Fixture A", "Fixture A", "Fixture B", "Fixture B"],
            }
        )

        dialog.set_df_for_grouping(grouping_df)
        dialog.set_grouping_applied(True)
        dialog._sync_ui_state()

        assert dialog.grouping_summary_label.text() == "Groups: 2 custom"
        assert dialog.groupstats_checkbox.isEnabled()
        assert dialog.groupstats_reason_label.isHidden()
    finally:
        dialog.close()


def test_tabular_clear_controls_reset_filters_and_groups(tmp_path) -> None:
    _app()
    input_file = tmp_path / "table.csv"
    pd.DataFrame(
        {
            "TraceCode": ["TC-001", "TC-002"],
            "Length mm": [10.0, 10.2],
        }
    ).to_csv(input_file, index=False)

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.input_file = str(input_file)
        dialog.load_metrics()
        _wait_for_tabular_load(dialog)
        grouping_df = pd.DataFrame(
            {
                "REPORT_ID": [1, 2],
                "GROUP": ["Fixture A", "POPULATION"],
            }
        )
        dialog.tabular_column_filters = (TabularColumnFilter("tracecode", selected_values=("TC-001",)),)
        dialog.set_df_for_grouping(grouping_df)
        dialog.set_grouping_applied(True)
        dialog._sync_ui_state()

        assert dialog.clear_filter_button.isEnabled()
        assert dialog.clear_groups_button.isEnabled()
        assert dialog.groupstats_checkbox.isChecked()

        dialog.clear_tabular_filter_and_groups()

        assert dialog.tabular_column_filters == ()
        assert dialog.tabular_filter_columns == ()
        assert dialog.tabular_filter_keys == ()
        assert dialog.df_for_grouping is None
        assert dialog.grouping_applied is False
        assert not dialog.clear_filter_button.isEnabled()
        assert not dialog.clear_groups_button.isEnabled()
        assert not dialog.groupstats_checkbox.isChecked()
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
        _wait_for_tabular_load(dialog)
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


def test_analytics_completion_message_opens_dashboard_normally_when_workbook_disabled(
    tmp_path, monkeypatch
) -> None:
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
    assert reveal_path == ""

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
        assert f"HTML dashboard: {dashboard_file.resolve().as_uri()}" in calls[0][3]
        assert calls[0][4] == ""
    finally:
        dialog.close()


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
    dialog = IndustrialAnalyticsDialog(
        db_file=str(tmp_path / "production.db"),
        source_kind=SOURCE_PRODUCTION_CACHE,
    )
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

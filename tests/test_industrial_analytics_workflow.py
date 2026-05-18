from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionMetricSelection,
    ReferenceCohortState,
)
import modules.industrial_analytics_workflow as workflow_module
from modules.industrial_analytics_workflow import (
    AnalyticsCancelled,
    default_dashboard_path,
    default_workbook_path,
    run_production_cache_analytics,
    run_tabular_file_analytics,
)
from modules.tabular_analytics_service import (
    TabularColumnFilter,
    cleanup_tabular_load_result,
    load_tabular_analytics_file,
)
from tests.industrial_analytics_fixtures import seed_production_analytics_cache


def test_run_production_cache_analytics_writes_dashboard_and_workbook(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    dashboard_file = tmp_path / "production_analytics.html"
    workbook_file = tmp_path / "production_analytics.xlsx"
    progress_messages: list[str] = []

    result = run_production_cache_analytics(
        db_file=db_path,
        output_dashboard_file=str(dashboard_file),
        output_workbook_file=str(workbook_file),
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
        aggregation_state=ProductionAggregationState(
            time_bucket="day",
            aggregation_methods=("mean",),
            group_fields=("line",),
        ),
        cohort_state=ReferenceCohortState.from_text("REF-100", mode="compare_rest"),
        chart_selection=ProductionChartSelection(
            time_series=True,
            histogram=True,
            violin=True,
            box=True,
            groupstats=True,
        ),
        separate_parameter_sheets=True,
        progress_callback=progress_messages.append,
    )

    assert Path(result.html_dashboard_path).exists()
    assert Path(result.workbook_path).exists()
    assert result.row_count == 16
    assert result.metric_count == 1
    assert result.groupstats_metric_count == 1
    assert result.parameter_sheet_count == 1
    assert {"Production Data", "Aggregates", "Metrics", "Groupstats", "Diagnostics"}.issubset(
        result.workbook_sheet_names
    )
    assert "Charts" in result.workbook_sheet_names
    with zipfile.ZipFile(workbook_file) as workbook_zip:
        names = set(workbook_zip.namelist())
    assert any(name.startswith("xl/charts/chart") for name in names)
    assert any(name.startswith("xl/media/image") for name in names)
    production_columns = pd.read_excel(workbook_file, sheet_name="Production Data").columns
    assert "raw_record_json" not in production_columns
    assert progress_messages
    assert progress_messages[0].startswith("Loading production data...")
    assert any(message.startswith("Writing dashboard...") for message in progress_messages)
    assert progress_messages[-1].startswith("Analytics complete")
    assert all("ETA" in message for message in progress_messages)


def test_default_analytics_paths_add_collision_suffixes(tmp_path) -> None:
    source_file = tmp_path / "table.csv"
    source_file.write_text("x\n1\n", encoding="utf-8")
    (tmp_path / "table_analytics.html").write_text("old", encoding="utf-8")
    (tmp_path / "table_analytics_1.html").write_text("old", encoding="utf-8")
    (tmp_path / "table_analytics.xlsx").write_text("old", encoding="utf-8")

    assert default_dashboard_path(source_file) == str(tmp_path / "table_analytics_2.html")
    assert default_workbook_path(source_file) == str(tmp_path / "table_analytics_1.xlsx")


def test_run_tabular_file_analytics_reuses_shared_dashboard_and_parameter_workbook(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    dashboard_file = tmp_path / "table_analytics.html"
    workbook_file = tmp_path / "table_analytics.xlsx"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=6, freq="12h"),
            "Reference ID": ["R1", "R1", "R2", "R2", "R3", "R3"],
            "Line": ["L1", "L1", "L2", "L2", "L1", "L2"],
            "Length mm": [10.0, 10.1, 10.2, 10.4, 10.3, 10.5],
            "Width mm": [5.0, 5.1, 5.2, 5.4, 5.3, 5.5],
        }
    ).to_csv(input_file, index=False)
    progress_messages: list[str] = []

    result = run_tabular_file_analytics(
        input_file=str(input_file),
        output_dashboard_file=str(dashboard_file),
        output_workbook_file=str(workbook_file),
        metric_selection=(ProductionMetricSelection("length_mm", display_label="Length mm"),),
        aggregation_state=ProductionAggregationState(
            time_bucket="day",
            aggregation_methods=("mean",),
            group_fields=("line",),
        ),
        chart_selection=ProductionChartSelection(groupstats=True),
        separate_parameter_sheets=True,
        progress_callback=progress_messages.append,
    )

    assert Path(result.html_dashboard_path).exists()
    assert Path(result.workbook_path).exists()
    html_text = dashboard_file.read_text(encoding="utf-8")
    assert "CSV / Excel Analytics" in html_text
    assert "CSV/Excel data dashboard generated by Metroliza." in html_text
    assert "Cached production data dashboard" not in html_text
    assert result.source_kind == "tabular_file"
    assert result.metric_count == 1
    assert result.parameter_sheet_count == 1
    assert "Length Mm" in result.workbook_sheet_names
    assert "Charts" in result.workbook_sheet_names
    with zipfile.ZipFile(workbook_file) as workbook_zip:
        names = set(workbook_zip.namelist())
    assert any(name.startswith("xl/charts/chart") for name in names)
    assert progress_messages
    assert progress_messages[0].startswith("Loading CSV/Excel data...")
    assert any(message.startswith("Writing dashboard...") for message in progress_messages)
    assert progress_messages[-1].startswith("Analytics complete")
    assert all("ETA" in message for message in progress_messages)


def test_run_tabular_file_analytics_uses_loaded_snapshot_without_reloading(
    tmp_path,
    monkeypatch,
) -> None:
    input_file = tmp_path / "snapshot_table.csv"
    dashboard_file = tmp_path / "snapshot_table_analytics.html"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=3, freq="h"),
            "Reference ID": ["R1", "R2", "R3"],
            "Length mm": [10.0, 10.2, 10.4],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)

    def fail_reload(*args, **kwargs):
        raise AssertionError("loaded tabular analytics snapshot should be reused")

    monkeypatch.setattr(workflow_module, "load_tabular_analytics_file", fail_reload)

    result = run_tabular_file_analytics(
        input_file=str(input_file),
        output_dashboard_file=str(dashboard_file),
        tabular_load_result=loaded,
        metric_selection=(ProductionMetricSelection("length_mm", display_label="Length mm"),),
        chart_selection=ProductionChartSelection(time_series=True),
    )

    assert result.row_count == 3
    assert Path(result.html_dashboard_path).exists()


def test_run_tabular_file_analytics_fast_detail_samples_dashboard_frame(
    tmp_path,
    monkeypatch,
) -> None:
    input_file = tmp_path / "detail_table.csv"
    dashboard_file = tmp_path / "detail_table_analytics.html"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=6, freq="h"),
            "Reference ID": [f"R{index}" for index in range(6)],
            "Length mm": [10.0, 10.2, 10.4, 10.6, 10.8, 11.0],
        }
    ).to_csv(input_file, index=False)
    captured_lengths: list[int] = []
    monkeypatch.setattr(workflow_module, "TABULAR_FAST_DASHBOARD_ROW_LIMIT", 3)

    def capture_dashboard(**kwargs):
        captured_lengths.append(len(kwargs["frame"].index))
        return {
            "html_dashboard_path": str(dashboard_file),
            "html_dashboard_assets_path": str(tmp_path / "detail_table_analytics_assets"),
            "html_dashboard_chart_count": 1,
        }

    monkeypatch.setattr(workflow_module, "_write_dashboard", capture_dashboard)

    result = run_tabular_file_analytics(
        input_file=str(input_file),
        output_dashboard_file=str(dashboard_file),
        metric_selection=(ProductionMetricSelection("length_mm", display_label="Length mm"),),
        chart_selection=ProductionChartSelection(time_series=True),
    )

    assert result.row_count == 6
    assert captured_lengths == [3]
    assert any(
        diagnostic.code == "tabular_dashboard_fast_sample"
        and diagnostic.context["input_row_count"] == 6
        and diagnostic.context["dashboard_row_count"] == 3
        for diagnostic in result.diagnostics
    )


def test_run_tabular_file_analytics_full_detail_uses_full_dashboard_frame(
    tmp_path,
    monkeypatch,
) -> None:
    input_file = tmp_path / "full_detail_table.csv"
    dashboard_file = tmp_path / "full_detail_table_analytics.html"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=6, freq="h"),
            "Reference ID": [f"R{index}" for index in range(6)],
            "Length mm": [10.0, 10.2, 10.4, 10.6, 10.8, 11.0],
        }
    ).to_csv(input_file, index=False)
    captured_lengths: list[int] = []
    monkeypatch.setattr(workflow_module, "TABULAR_FAST_DASHBOARD_ROW_LIMIT", 3)

    def capture_dashboard(**kwargs):
        captured_lengths.append(len(kwargs["frame"].index))
        return {
            "html_dashboard_path": str(dashboard_file),
            "html_dashboard_assets_path": str(tmp_path / "full_detail_table_analytics_assets"),
            "html_dashboard_chart_count": 1,
        }

    monkeypatch.setattr(workflow_module, "_write_dashboard", capture_dashboard)

    result = run_tabular_file_analytics(
        input_file=str(input_file),
        output_dashboard_file=str(dashboard_file),
        metric_selection=(ProductionMetricSelection("length_mm", display_label="Length mm"),),
        chart_selection=ProductionChartSelection(time_series=True),
        dashboard_detail_mode="full",
    )

    assert result.row_count == 6
    assert captured_lengths == [6]
    assert not any(diagnostic.code == "tabular_dashboard_fast_sample" for diagnostic in result.diagnostics)


def test_run_tabular_file_analytics_uses_sqlite_backed_loaded_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    input_file = tmp_path / "sqlite_snapshot_table.csv"
    dashboard_file = tmp_path / "sqlite_snapshot_table_analytics.html"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "Line": ["A", "B", "A", "B"],
            "Length mm": [10.0, 10.2, 10.4, 10.6],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)

    def fail_reload(*args, **kwargs):
        raise AssertionError("sqlite-backed tabular analytics snapshot should be reused")

    monkeypatch.setattr(workflow_module, "load_tabular_analytics_file", fail_reload)
    try:
        result = run_tabular_file_analytics(
            input_file=str(input_file),
            output_dashboard_file=str(dashboard_file),
            tabular_load_result=loaded,
            metric_selection=(ProductionMetricSelection("length_mm", display_label="Length mm"),),
            tabular_column_filters=(TabularColumnFilter("line", selected_values=("A",)),),
            chart_selection=ProductionChartSelection(time_series=True),
        )
    finally:
        cleanup_tabular_load_result(loaded)

    assert result.row_count == 2
    assert Path(result.html_dashboard_path).exists()


def test_run_tabular_file_analytics_rejects_stale_loaded_snapshot(tmp_path) -> None:
    input_file = tmp_path / "stale_table.csv"
    dashboard_file = tmp_path / "stale_table_analytics.html"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=3, freq="h"),
            "Reference ID": ["R1", "R2", "R3"],
            "Length mm": [10.0, 10.2, 10.4],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "Reference ID": ["R1", "R2", "R3", "R4"],
            "Length mm": [10.0, 10.2, 10.4, 10.6],
        }
    ).to_csv(input_file, index=False)

    with pytest.raises(ValueError, match="Reload CSV/Excel data before export"):
        run_tabular_file_analytics(
            input_file=str(input_file),
            output_dashboard_file=str(dashboard_file),
            tabular_load_result=loaded,
            metric_selection=(ProductionMetricSelection("length_mm", display_label="Length mm"),),
            chart_selection=ProductionChartSelection(time_series=True),
        )

    assert not dashboard_file.exists()


def test_run_tabular_file_analytics_uses_manual_population_grouping(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    dashboard_file = tmp_path / "grouped_table_analytics.html"
    workbook_file = tmp_path / "grouped_table_analytics.xlsx"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=6, freq="12h"),
            "Reference ID": ["R1", "R1", "R2", "R2", "R3", "R3"],
            "Length mm": [10.0, 10.1, 10.2, 10.4, 10.3, 10.5],
        }
    ).to_csv(input_file, index=False)
    grouping_df = pd.DataFrame(
        {
            "REPORT_ID": [1, 2, 3, 4, 5, 6],
            "GROUP": ["Selected", "Selected", "POPULATION", "POPULATION", "POPULATION", ""],
        }
    )

    result = run_tabular_file_analytics(
        input_file=str(input_file),
        output_dashboard_file=str(dashboard_file),
        output_workbook_file=str(workbook_file),
        metric_selection=(ProductionMetricSelection("length_mm", display_label="Length mm"),),
        grouping_df=grouping_df,
        aggregation_state=ProductionAggregationState(
            time_bucket="none",
            aggregation_methods=("mean",),
        ),
        chart_selection=ProductionChartSelection(groupstats=True),
        separate_parameter_sheets=False,
    )

    assert result.metric_count == 1
    assert result.groupstats_metric_count == 1
    table_data = pd.read_excel(workbook_file, sheet_name="Table Data")
    assert set(table_data["GROUP"]) == {"POPULATION", "Selected"}
    aggregates = pd.read_excel(workbook_file, sheet_name="Aggregates")
    assert set(aggregates["GROUP"]) == {"POPULATION", "Selected"}
    assert "tabular_grouping_applied" in {diagnostic.code for diagnostic in result.diagnostics}


def test_run_tabular_file_analytics_applies_visual_row_filter_before_outputs(tmp_path) -> None:
    input_file = tmp_path / "filtered_table.csv"
    dashboard_file = tmp_path / "filtered_table_analytics.html"
    workbook_file = tmp_path / "filtered_table_analytics.xlsx"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004"],
            "Line": ["L1", "L2", "L1", "L2"],
            "Length mm": [10.0, 10.2, 10.4, 10.6],
        }
    ).to_csv(input_file, index=False)

    result = run_tabular_file_analytics(
        input_file=str(input_file),
        output_dashboard_file=str(dashboard_file),
        output_workbook_file=str(workbook_file),
        metric_selection=(ProductionMetricSelection("length_mm", display_label="Length mm"),),
        tabular_filter_columns=("tracecode",),
        tabular_filter_keys=(("TC-001",), ("TC-003",)),
        aggregation_state=ProductionAggregationState(
            time_bucket="none",
            aggregation_methods=("mean",),
            group_fields=("line",),
        ),
        chart_selection=ProductionChartSelection(groupstats=False),
        separate_parameter_sheets=False,
    )

    table_data = pd.read_excel(workbook_file, sheet_name="Table Data")
    assert result.row_count == 2
    assert table_data["tracecode"].tolist() == ["TC-001", "TC-003"]
    assert "tabular_filters_applied" in {diagnostic.code for diagnostic in result.diagnostics}


def test_run_tabular_file_analytics_applies_column_scoped_row_filters(tmp_path) -> None:
    input_file = tmp_path / "column_filtered_table.csv"
    dashboard_file = tmp_path / "column_filtered_table_analytics.html"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=5, freq="D"),
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004", "TC-005"],
            "Line": ["L1", "L2", "L1", "L1", "L2"],
            "Length mm": [10.0, 10.2, 10.4, 10.6, 10.8],
        }
    ).to_csv(input_file, index=False)

    result = run_tabular_file_analytics(
        input_file=str(input_file),
        output_dashboard_file=str(dashboard_file),
        metric_selection=(ProductionMetricSelection("length_mm", display_label="Length mm"),),
        tabular_column_filters=(
            TabularColumnFilter("line", selected_values=("L1",)),
            TabularColumnFilter(
                "time_stamp",
                date_mode="between",
                date_from="2026-05-11",
                date_to="2026-05-12",
            ),
        ),
        aggregation_state=ProductionAggregationState(time_bucket="none", aggregation_methods=("mean",)),
        chart_selection=ProductionChartSelection(groupstats=False),
    )

    assert result.row_count == 1
    assert "tabular_filters_applied" in {diagnostic.code for diagnostic in result.diagnostics}


def test_run_production_cache_analytics_cancel_removes_temp_outputs(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    dashboard_file = tmp_path / "production_analytics.html"
    workbook_file = tmp_path / "production_analytics.xlsx"
    calls = {"count": 0}

    def cancel_after_dashboard_write() -> bool:
        calls["count"] += 1
        return calls["count"] >= 7

    with pytest.raises(AnalyticsCancelled):
        run_production_cache_analytics(
            db_file=db_path,
            output_dashboard_file=str(dashboard_file),
            output_workbook_file=str(workbook_file),
            metric_selection=(ProductionMetricSelection("cycle_time_s"),),
            chart_selection=ProductionChartSelection(time_series=True, histogram=False),
            cancel_check=cancel_after_dashboard_write,
        )

    assert not dashboard_file.exists()
    assert not workbook_file.exists()
    assert not list(tmp_path.glob(".production_analytics.*.tmp.html"))
    assert not list(tmp_path.glob(".production_analytics.*.tmp.xlsx"))

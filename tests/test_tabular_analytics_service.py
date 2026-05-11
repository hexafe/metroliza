from __future__ import annotations

from pathlib import Path
import zipfile

import pandas as pd

from modules.industrial_analytics_dashboard import build_production_dashboard_manifest
from modules.industrial_analytics_service import aggregate_production_frame
from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
)
from modules.tabular_analytics_service import (
    TABULAR_GROUP_COLUMN,
    apply_tabular_grouping,
    build_tabular_grouping_dataframe,
    export_tabular_analytics_workbook,
    load_tabular_analytics_file,
)


def _sample_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=6, freq="12h"),
            "Reference ID": ["R1", "R1", "R2", "R2", "R3", "R3"],
            "Line": ["L1", "L1", "L2", "L2", "L1", "L2"],
            "Length mm": [10.0, 10.1, 10.2, 10.4, 10.3, 10.5],
            "Width mm": [5.0, 5.1, 5.2, 5.4, 5.3, 5.5],
            "Comment": ["ok", "ok", "review", "ok", "ok", "review"],
        }
    )


def test_load_tabular_analytics_file_detects_csv_metrics_and_contract_columns(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    _sample_table().to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file)
    by_name = {candidate.field_name: candidate for candidate in result.metric_candidates}

    assert {"length_mm", "width_mm"}.issubset(by_name)
    assert "comment" not in by_name
    assert "process_datetime" in result.dataframe.columns
    assert "reference" in result.dataframe.columns
    assert set(result.dataframe["reference"]) == {"R1", "R2", "R3"}
    assert result.csv_config["delimiter"] == ","


def test_load_tabular_analytics_file_uses_explicit_time_and_reference_columns(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    pd.DataFrame(
        {
            "Created At": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "Batch Number": [1001, 1001, 1002, 1002],
            "Numeric ID": [1, 2, 3, 4],
            "Length mm": [10.0, 10.2, 10.1, 10.4],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(
        input_file,
        timestamp_column="Created At",
        reference_column="Batch Number",
    )

    assert result.timestamp_column == "created_at"
    assert result.reference_column == "batch_number"
    assert set(result.dataframe["reference"]) == {"1001", "1002"}
    assert result.dataframe["process_datetime"].notna().all()
    assert "batch_number" not in {candidate.field_name for candidate in result.metric_candidates}


def test_load_tabular_analytics_file_detects_excel_metrics(tmp_path) -> None:
    input_file = tmp_path / "table.xlsx"
    _sample_table().to_excel(input_file, index=False, sheet_name="Measurements")

    result = load_tabular_analytics_file(input_file, sheet_name="Measurements")
    metric_names = {candidate.field_name for candidate in result.metric_candidates}

    assert {"length_mm", "width_mm"}.issubset(metric_names)
    assert result.sheet_name == "Measurements"
    assert result.dataframe["process_datetime"].notna().all()


def test_tabular_grouping_dataframe_builds_source_row_identity_rows(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)

    grouping_frame = build_tabular_grouping_dataframe(loaded.dataframe)

    assert grouping_frame["REPORT_ID"].tolist() == [1, 2, 3, 4, 5, 6]
    assert set(grouping_frame["REFERENCE"]) == {"R1", "R2", "R3"}
    assert grouping_frame["SAMPLE_NUMBER"].tolist() == ["1", "2", "3", "4", "5", "6"]
    assert grouping_frame["FILENAME"].str.contains("table.csv").all()


def test_apply_tabular_grouping_keeps_unassigned_rows_in_population(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)
    grouping_frame = build_tabular_grouping_dataframe(loaded.dataframe)
    grouping_frame["GROUP"] = "POPULATION"
    grouping_frame.loc[grouping_frame["REPORT_ID"].isin([1, 2]), "GROUP"] = "Selected"

    grouped = apply_tabular_grouping(loaded.dataframe, grouping_frame)

    assert grouped.applied
    assert grouped.group_count == 2
    assert grouped.custom_group_count == 1
    assert grouped.dataframe[TABULAR_GROUP_COLUMN].tolist() == [
        "Selected",
        "Selected",
        "POPULATION",
        "POPULATION",
        "POPULATION",
        "POPULATION",
    ]
    assert [diagnostic.code for diagnostic in grouped.diagnostics] == ["tabular_grouping_applied"]


def test_tabular_data_reuses_dashboard_and_aggregation_path(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)
    metrics = tuple(candidate.to_selection() for candidate in loaded.metric_candidates[:1])
    aggregation = ProductionAggregationState(
        time_bucket="day",
        aggregation_methods=("mean",),
        group_fields=("line",),
    )

    aggregated = aggregate_production_frame(loaded.dataframe, aggregation, metrics)
    manifest = build_production_dashboard_manifest(
        frame=loaded.dataframe,
        metric_selection=metrics,
        aggregation_state=aggregation,
        aggregation_result=aggregated,
        chart_selection=ProductionChartSelection(time_series=True, histogram=True, violin=True, box=True),
        diagnostics=loaded.diagnostics + aggregated.diagnostics,
    )

    assert aggregated.is_aggregated
    assert "line" in aggregated.dataframe.columns
    assert manifest["summary"]["chart_count"] == 4
    assert {chart["chart_type"] for chart in manifest["charts"]} == {
        "time_series",
        "histogram",
        "violin",
        "box",
    }
    histogram = next(chart for chart in manifest["charts"] if chart["chart_type"] == "histogram")
    traces = histogram["plotly_spec"]["data"]
    assert traces[0]["bingroup"] == f"hist-{metrics[0].field_name}"
    assert traces[0]["xbins"]["size"] > 0


def test_tabular_workbook_export_writes_separate_parameter_sheets(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    output_file = tmp_path / "analytics.xlsx"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)
    metrics = tuple(candidate.to_selection() for candidate in loaded.metric_candidates)
    aggregated = aggregate_production_frame(
        loaded.dataframe,
        ProductionAggregationState(time_bucket="day", aggregation_methods=("mean",)),
        metrics,
    )

    result = export_tabular_analytics_workbook(
        dataframe=loaded.dataframe,
        metric_candidates=loaded.metric_candidates,
        output_file=output_file,
        aggregation_result=aggregated,
        diagnostics=loaded.diagnostics + aggregated.diagnostics,
        separate_parameter_sheets=True,
    )

    assert Path(result.output_file).exists()
    assert result.parameter_sheet_count == len(loaded.metric_candidates)
    workbook = pd.ExcelFile(output_file)
    assert {"Table Data", "Aggregates", "Metrics", "Diagnostics"}.issubset(workbook.sheet_names)
    assert {"Length Mm", "Width Mm"}.issubset(workbook.sheet_names)


def test_tabular_workbook_export_includes_selected_chart_outputs(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    output_file = tmp_path / "analytics_with_charts.xlsx"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)

    result = export_tabular_analytics_workbook(
        dataframe=loaded.dataframe,
        metric_candidates=loaded.metric_candidates[:1],
        output_file=output_file,
        chart_selection=ProductionChartSelection(
            time_series=True,
            histogram=True,
            violin=True,
            box=True,
        ),
        separate_parameter_sheets=False,
    )

    assert "Charts" in result.sheet_names
    with zipfile.ZipFile(output_file) as workbook_zip:
        names = set(workbook_zip.namelist())
    assert any(name.startswith("xl/charts/chart") for name in names)
    assert any(name.startswith("xl/media/image") for name in names)

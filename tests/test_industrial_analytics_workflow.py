from __future__ import annotations

from pathlib import Path

import pandas as pd

from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionMetricSelection,
    ReferenceCohortState,
)
from modules.industrial_analytics_workflow import (
    run_production_cache_analytics,
    run_tabular_file_analytics,
)
from tests.industrial_analytics_fixtures import seed_production_analytics_cache


def test_run_production_cache_analytics_writes_dashboard_and_workbook(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    dashboard_file = tmp_path / "production_analytics.html"
    workbook_file = tmp_path / "production_analytics.xlsx"

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
    production_columns = pd.read_excel(workbook_file, sheet_name="Production Data").columns
    assert "raw_record_json" not in production_columns


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
    )

    assert Path(result.html_dashboard_path).exists()
    assert Path(result.workbook_path).exists()
    assert result.source_kind == "tabular_file"
    assert result.metric_count == 1
    assert result.parameter_sheet_count == 1
    assert "Length Mm" in result.workbook_sheet_names

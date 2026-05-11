from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from modules.industrial_analytics_dashboard import (
    DASHBOARD_SCHEMA,
    build_production_dashboard_manifest,
    write_production_dashboard,
)
from modules.industrial_analytics_service import (
    ProductionAggregationResult,
    aggregate_production_frame,
    analyze_production_groupstats,
    apply_reference_cohorts,
    load_production_analytics_frame,
)
from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionMetricSelection,
    ReferenceCohortState,
)
from tests.industrial_analytics_fixtures import seed_production_analytics_cache


def _production_dashboard_fixture(tmp_path):
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    metrics = (ProductionMetricSelection("cycle_time_s"),)
    loaded = load_production_analytics_frame(db_path, metric_selection=metrics)
    cohort = ReferenceCohortState.from_text("REF-100", mode="compare_rest")
    cohorted = apply_reference_cohorts(loaded.dataframe, cohort)
    aggregation = ProductionAggregationState(
        time_bucket="day",
        aggregation_methods=("mean", "median"),
        group_fields=("reference_cohort",),
    )
    aggregated = aggregate_production_frame(cohorted.dataframe, aggregation, metrics)
    groupstats = analyze_production_groupstats(
        cohorted.dataframe,
        metrics,
        aggregation_state=aggregation,
        cohort_state=cohort,
    )
    manifest = build_production_dashboard_manifest(
        frame=cohorted.dataframe,
        metric_selection=metrics,
        aggregation_state=aggregation,
        aggregation_result=aggregated,
        groupstats_result=groupstats,
        chart_selection=ProductionChartSelection(
            time_series=True,
            histogram=True,
            violin=True,
            box=True,
            groupstats=True,
        ),
        cohort_state=cohort,
        diagnostics=(
            loaded.diagnostics
            + cohorted.diagnostics
            + aggregated.diagnostics
            + groupstats.diagnostics
        ),
    )
    return manifest


def test_build_production_dashboard_manifest_contains_requested_chart_families(tmp_path) -> None:
    manifest = _production_dashboard_fixture(tmp_path)

    assert manifest["schema"] == DASHBOARD_SCHEMA
    assert manifest["summary"]["source_rows"] == 16
    assert manifest["summary"]["chart_count"] == 4
    assert manifest["summary"]["groupstats_metric_count"] == 1
    assert manifest["groupstats"]["metrics"][0]["descriptive_stats"]
    assert {chart["chart_type"] for chart in manifest["charts"]} == {
        "time_series",
        "histogram",
        "violin",
        "box",
    }
    assert "raw_record_json" not in json.dumps(manifest)
    assert "Selected references" in json.dumps(manifest)


def test_write_production_dashboard_writes_offline_plotly_html(tmp_path) -> None:
    manifest = _production_dashboard_fixture(tmp_path)
    output_file = tmp_path / "production_dashboard.html"

    result = write_production_dashboard(manifest, output_file)

    html_path = Path(result["html_dashboard_path"])
    assets_path = Path(result["html_dashboard_assets_path"])
    assert result["html_dashboard_chart_count"] == 4
    assert html_path.exists()
    assert (assets_path / "plotly-2.27.0.min.js").exists()

    html_text = html_path.read_text(encoding="utf-8")
    assert "Production Analytics" in html_text
    assert "plotly-2.27.0.min.js" in html_text
    assert "cdn.plot.ly" not in html_text
    assert "raw_record_json" not in html_text
    assert "Selected references" in html_text
    assert "Descriptive stats" in html_text

    match = re.search(
        r'<script id="production-dashboard-charts" type="application/json">(.*?)</script>',
        html_text,
        re.DOTALL,
    )
    assert match is not None
    chart_payload = json.loads(match.group(1))
    assert len(chart_payload) == 4


def test_time_series_trace_drops_sparse_aggregation_nan_pairs() -> None:
    frame = pd.DataFrame(
        {
            "process_datetime": pd.to_datetime(
                ["2026-05-10T00:00:00Z", "2026-05-11T00:00:00Z"],
                utc=True,
            ),
            "cycle_time_s": [35.0, 36.0],
            "station": ["S1", "S1"],
        }
    )
    aggregate_frame = pd.DataFrame(
        {
            "time_bucket_start": pd.to_datetime(
                ["2026-05-10T00:00:00Z", "2026-05-11T00:00:00Z"],
                utc=True,
            ),
            "station": ["S1", "S1"],
            "cycle_time_s__std": [float("nan"), 0.3],
            "raw_row_count": [1, 2],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
        aggregation_state=ProductionAggregationState(
            time_bucket="day",
            aggregation_methods=("std",),
            group_fields=("station",),
        ),
        aggregation_result=ProductionAggregationResult(
            dataframe=aggregate_frame,
            source_row_count=2,
            output_row_count=2,
            is_aggregated=True,
        ),
        chart_selection=ProductionChartSelection(
            time_series=True,
            histogram=False,
            violin=False,
            box=False,
            groupstats=False,
        ),
    )

    traces = manifest["charts"][0]["plotly_spec"]["data"]
    assert len(traces) == 1
    assert traces[0]["x"] == ["2026-05-11T00:00:00+00:00"]
    assert traces[0]["y"] == [0.3]

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
    assert manifest["summary"]["chart_count"] == 5
    assert manifest["summary"]["groupstats_metric_count"] == 1
    assert manifest["groupstats"]["metrics"][0]["descriptive_stats"]
    assert manifest["groupstats"]["metrics"][0]["distribution_rows"]
    assert {chart["chart_type"] for chart in manifest["charts"]} == {
        "time_series",
        "time_series_raw_aggregate",
        "histogram",
        "violin",
        "box",
    }
    assert "raw_record_json" not in json.dumps(manifest)
    assert "Selected references" in json.dumps(manifest)
    histogram = next(chart for chart in manifest["charts"] if chart["chart_type"] == "histogram")
    traces = histogram["plotly_spec"]["data"]
    assert traces
    assert {trace["bingroup"] for trace in traces} == {"hist-cycle_time_s"}
    assert all(trace["xbins"] == traces[0]["xbins"] for trace in traces)
    assert all(trace["histnorm"] == "probability" for trace in traces)
    assert histogram["plotly_spec"]["layout"]["yaxis"]["title"] == "Share of group"
    assert traces[0]["xbins"]["size"] > 0
    assert histogram["stats_tables"]
    assert histogram["image"]["mime_type"] == "image/png"
    assert any(
        row["label"] == "Samples"
        for table in histogram["stats_tables"]
        for row in table["rows"]
    )


def test_write_production_dashboard_writes_offline_plotly_html(tmp_path) -> None:
    manifest = _production_dashboard_fixture(tmp_path)
    output_file = tmp_path / "production_dashboard.html"

    result = write_production_dashboard(manifest, output_file)

    html_path = Path(result["html_dashboard_path"])
    assets_path = Path(result["html_dashboard_assets_path"])
    assert result["html_dashboard_chart_count"] == 5
    assert html_path.exists()
    assert (assets_path / "plotly-2.27.0.min.js").exists()

    html_text = html_path.read_text(encoding="utf-8")
    assert "Production Analytics" in html_text
    assert "plotly-2.27.0.min.js" in html_text
    assert "cdn.plot.ly" not in html_text
    assert "raw_record_json" not in html_text
    assert "Selected references" in html_text
    assert "Descriptive stats" in html_text
    assert "Samples" in html_text

    match = re.search(
        r'<script id="production-dashboard-charts" type="application/json">(.*?)</script>',
        html_text,
        re.DOTALL,
    )
    assert match is not None
    chart_payload = json.loads(match.group(1))
    assert len(chart_payload) == 5


def test_write_production_dashboard_collapses_diagnostics_by_default(tmp_path) -> None:
    manifest = _production_dashboard_fixture(tmp_path)
    manifest["diagnostics"] = [
        {"severity": "warning", "code": "sample", "message": "Diagnostic details"}
    ]
    output_file = tmp_path / "production_dashboard.html"

    write_production_dashboard(manifest, output_file)

    html_text = output_file.read_text(encoding="utf-8")
    assert '<details class="diagnostics">' in html_text
    assert "<summary>Diagnostics (1)</summary>" in html_text
    assert "<h2>Diagnostics</h2>" not in html_text


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
    assert traces[0]["x"] == ["2026-05-11"]
    assert traces[0]["y"] == [0.3]


def test_aggregated_time_series_adds_raw_overlay_with_x_markers() -> None:
    frame = pd.DataFrame(
        {
            "process_datetime": pd.to_datetime(
                [
                    "2026-01-10T00:00:00Z",
                    "2026-01-20T00:00:00Z",
                    "2026-01-11T00:00:00Z",
                    "2026-01-21T00:00:00Z",
                ],
                utc=True,
            ),
            "machine": ["M1", "M1", "M2", "M2"],
            "length_mm": [10.0, 12.0, 20.0, 22.0],
        }
    )
    aggregate_frame = pd.DataFrame(
        {
            "time_bucket_start": [
                pd.Timestamp("2026-01-01T00:00:00Z"),
                pd.Timestamp("2026-01-01T00:00:00Z"),
            ],
            "machine": ["M1", "M2"],
            "length_mm__mean": [11.0, 21.0],
            "raw_row_count": [2, 2],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm"),),
        aggregation_state=ProductionAggregationState(
            time_bucket="month",
            aggregation_methods=("mean",),
            group_fields=("machine",),
        ),
        aggregation_result=ProductionAggregationResult(
            dataframe=aggregate_frame,
            source_row_count=2,
            output_row_count=1,
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

    assert [chart["chart_type"] for chart in manifest["charts"]] == [
        "time_series",
        "time_series_raw_aggregate",
    ]
    overlay = manifest["charts"][1]["plotly_spec"]["data"]
    aggregate_trace = next(trace for trace in overlay if trace["name"] == "M1 aggregate")
    assert aggregate_trace["x"] == ["2026-01"]
    assert aggregate_trace["marker"]["symbol"] == "x"
    assert aggregate_trace["marker"]["line"]["width"] > 1


def test_metric_limits_flow_into_dashboard_stats_tables() -> None:
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10", periods=4, freq="h", tz="UTC"),
            "length_mm": [9.0, 10.0, 11.0, 12.5],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm", lsl=9.5, usl=12.0),),
        chart_selection=ProductionChartSelection(
            time_series=False,
            histogram=True,
            violin=False,
            box=False,
            groupstats=False,
        ),
    )

    histogram = manifest["charts"][0]
    rows = [row for table in histogram["stats_tables"] for row in table["rows"]]
    labels = {row["label"] for row in rows}
    assert {"Cp", "Cpk", "NOK", "NOK %"}.issubset(labels)
    assert any(row["label"] == "NOK" and row["value"].startswith("2") for row in rows)


def test_time_series_highlight_mode_uses_separate_selected_and_population_traces() -> None:
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=4, freq="h", tz="UTC"),
            "reference": ["R1", "R2", "R1", "R2"],
            "cycle_time_s": [35.0, 36.0, 35.2, 36.3],
        }
    )
    cohort = ReferenceCohortState(references=("R1",), mode="highlight")
    cohorted = apply_reference_cohorts(frame, cohort)

    manifest = build_production_dashboard_manifest(
        frame=cohorted.dataframe,
        metric_selection=(ProductionMetricSelection("cycle_time_s", "Cycle Time S"),),
        aggregation_state=ProductionAggregationState(
            time_bucket="day",
            aggregation_methods=("mean",),
            group_fields=(),
        ),
        aggregation_result=ProductionAggregationResult(
            dataframe=pd.DataFrame(
                {
                    "time_bucket_start": [pd.Timestamp("2026-05-10T00:00:00Z")],
                    "cycle_time_s__mean": [35.625],
                    "raw_row_count": [4],
                }
            ),
            source_row_count=4,
            output_row_count=1,
            is_aggregated=True,
        ),
        chart_selection=ProductionChartSelection(
            time_series=True,
            histogram=False,
            violin=False,
            box=False,
            groupstats=False,
        ),
        cohort_state=cohort,
    )

    traces = manifest["charts"][0]["plotly_spec"]["data"]

    assert {trace["name"] for trace in traces} == {"Selected references", "Other references"}
    assert {trace["mode"] for trace in traces} == {"markers"}
    assert {trace["marker"]["symbol"] for trace in traces} == {"diamond", "circle"}


def test_distribution_charts_use_selected_group_field_before_default_columns() -> None:
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "station": ["S1", "S1", "S1", "S1"],
            "machine": ["M1", "M2", "M1", "M2"],
            "cycle_time_s": [35.0, 36.0, 34.8, 36.2],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("cycle_time_s", "Cycle Time S"),),
        aggregation_state=ProductionAggregationState(
            time_bucket="none",
            aggregation_methods=("mean",),
            group_fields=("machine",),
        ),
        chart_selection=ProductionChartSelection(
            time_series=False,
            histogram=True,
            violin=True,
            box=True,
        ),
    )

    for chart_type in {"histogram", "violin", "box"}:
        chart = next(chart for chart in manifest["charts"] if chart["chart_type"] == chart_type)
        trace_names = {trace["name"] for trace in chart["plotly_spec"]["data"]}
        assert trace_names == {"M1", "M2"}

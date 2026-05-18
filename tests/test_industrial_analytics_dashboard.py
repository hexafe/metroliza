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
    ProductionGroupstatsResult,
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
    assert histogram["group_labels"] == ["Other references", "Selected references"]
    assert histogram["stats_tables"]
    if "plotly_spec" in histogram:
        assert histogram["plotly_spec"]["config"].get("staticPlot") is not True
        assert histogram["plotly_spec"]["layout"]["yaxis"]["title"]["text"] == "Frequency (%)"
    else:
        assert histogram["image"]["mime_type"] == "image/png"
    assert any(
        row["label"] == "Samples"
        for table in histogram["stats_tables"]
        for row in table["rows"]
    )


def test_dashboard_chart_layout_reserves_title_and_legend_spacing(tmp_path) -> None:
    manifest = _production_dashboard_fixture(tmp_path)

    layout = manifest["charts"][0]["plotly_spec"]["layout"]

    assert layout["margin"]["t"] >= 110
    assert layout["legend"]["y"] > 1.0
    assert layout["title"]["y"] >= 0.99


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
    assert (
        'class="plotly-chart" id="histogram-cycle_time_s"' in html_text
        or 'class="chart-image"' in html_text
    )
    assert "Static snapshot" not in html_text
    assert '<details class="chart-stats">' in html_text
    assert "<summary>Chart statistics (" in html_text
    assert 'class="plotly-expand-trigger"' in html_text
    assert 'id="chart-lightbox"' in html_text
    assert 'id="chart-lightbox-plotly"' in html_text
    assert "const chartById = new Map" in html_text
    assert ".chart-stats th" in html_text
    assert "background: #0f172a" in html_text
    assert '<header id="dashboard-start">' in html_text
    assert '<nav class="section-nav">' in html_text
    assert '<a class="section-chip" href="#groupstats">Groupstats</a>' in html_text
    assert 'Back to dashboard start</a>' in html_text
    assert 'id="chart-time-series-cycle-time-s-aggregated"' in html_text
    assert "color: #f8fafc" in html_text
    assert ".chart-stats-title" in html_text
    assert "color: #0f172a" in html_text
    assert "<th>Statistic</th><th>Value</th>" in html_text
    assert "grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr));" in html_text
    assert '<div class="card-label">Aggregated output points</div>' in html_text
    assert '<div class="card-label">Groups</div>' in html_text
    assert "Pasted reference cohorts" in html_text
    assert '<div class="card-label">Pasted references</div>' in html_text
    assert '<div class="card-label">Groupstats</div>' in html_text
    assert '<div class="card-label">Reference cohort</div>' not in html_text
    assert '<div class="card-label">Stats metrics</div>' not in html_text

    match = re.search(
        r'<script id="production-dashboard-charts" type="application/json">(.*?)</script>',
        html_text,
        re.DOTALL,
    )
    assert match is not None
    chart_payload = json.loads(match.group(1))
    chart_ids = {chart["id"] for chart in chart_payload}
    assert {"time-series-cycle_time_s-aggregated", "time-series-cycle_time_s-raw-aggregate"}.issubset(
        chart_ids
    )
    for chart in chart_payload:
        if chart["id"] in {"histogram-cycle_time_s", "violin-cycle_time_s", "box-cycle_time_s"}:
            assert chart["plotly_spec"]["config"].get("staticPlot") is not True


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
    assert "<h2>Diagnostics</h2>" in html_text
    assert '<a class="section-chip" href="#diagnostics">Diagnostics</a>' in html_text


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
    raw_aggregate_layout = manifest["charts"][1]["plotly_spec"]["layout"]
    aggregate_trace = next(trace for trace in overlay if trace["name"] == "M1 aggregate")
    assert aggregate_trace["x"] == ["2026-01"]
    assert aggregate_trace["marker"]["symbol"] == "x"
    assert aggregate_trace["marker"]["line"]["width"] > 1
    assert raw_aggregate_layout["xaxis"]["title"]["text"] == "Month"


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
    if "plotly_spec" in histogram:
        assert histogram["plotly_spec"]["config"].get("staticPlot") is not True
        xaxis = histogram["plotly_spec"]["layout"]["xaxis"]
        assert xaxis["tickformat"] == ".4~g"
        assert xaxis["tickfont"]["size"] == 10
        assert xaxis["tickangle"] == -30
        assert xaxis["automargin"] is True
        assert xaxis["title"]["standoff"] >= 20
        assert histogram["plotly_spec"]["layout"]["margin"]["b"] >= 92
    else:
        assert histogram["image"]["mime_type"] == "image/png"


def test_histogram_stats_rows_without_limits_show_capability_as_not_applicable() -> None:
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10", periods=4, freq="h", tz="UTC"),
            "length_mm": [9.0, 10.0, 11.0, 12.5],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm"),),
        chart_selection=ProductionChartSelection(
            time_series=False,
            histogram=True,
            violin=False,
            box=False,
            groupstats=False,
        ),
    )

    rows = {
        row["label"]: row["value"]
        for table in manifest["charts"][0]["stats_tables"]
        for row in table["rows"]
    }

    assert rows["Cp"] == "N/A"
    assert rows["Cpk"] == "N/A"
    assert rows["NOK"] == "N/A"
    assert rows["NOK %"] == "N/A"


def test_dashboard_snapshot_rendering_keeps_matplotlib_headless_backend(monkeypatch) -> None:
    monkeypatch.setattr(
        "modules.industrial_analytics_dashboard.build_dashboard_plotly_spec",
        lambda *args, **kwargs: None,
    )
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10", periods=4, freq="h", tz="UTC"),
            "length_mm": [9.0, 10.0, 11.0, 12.5],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm"),),
        chart_selection=ProductionChartSelection(
            time_series=False,
            histogram=True,
            violin=False,
            box=False,
            groupstats=False,
        ),
    )

    import matplotlib

    assert manifest["charts"][0]["image"]["mime_type"] == "image/png"
    assert matplotlib.get_backend().casefold() == "agg"


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


def test_large_time_series_uses_compact_marker_style() -> None:
    row_count = 12_000
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range(
                "2026-05-10 08:00",
                periods=row_count,
                freq="s",
                tz="UTC",
            ),
            "length_mm": [float(index % 100) for index in range(row_count)],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm"),),
        chart_selection=ProductionChartSelection(
            time_series=True,
            histogram=False,
            violin=False,
            box=False,
            groupstats=False,
        ),
    )

    chart_spec = manifest["charts"][0]["plotly_spec"]
    marker = chart_spec["data"][0]["marker"]
    xaxis = chart_spec["layout"]["xaxis"]

    assert marker["size"] <= 3.5
    assert marker["opacity"] <= 0.55
    assert marker["line"]["width"] == 0.0
    assert xaxis["automargin"] is True
    assert xaxis["tickangle"] <= -34
    assert xaxis["tickfont"]["size"] <= 10
    assert xaxis["ticklabeloverflow"] == "hide past div"
    assert xaxis["ticklabelstep"] >= 2
    assert xaxis["nticks"] <= 12


def test_very_large_aggregated_time_series_hybrid_keeps_raw_and_mean_axes_aligned() -> None:
    row_count = 60_000
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range(
                "2026-01-15 00:00",
                periods=row_count,
                freq="h",
                tz="UTC",
            ),
            "machine": ["M1" if index % 2 == 0 else "M2" for index in range(row_count)],
            "length_mm": [10.0 + float(index % 30) / 3.0 for index in range(row_count)],
        }
    )
    aggregate_frame = pd.DataFrame(
        {
            "time_bucket_start": [
                pd.Timestamp("2026-01-01T00:00:00Z"),
                pd.Timestamp("2026-01-01T00:00:00Z"),
                pd.Timestamp("2026-02-01T00:00:00Z"),
                pd.Timestamp("2026-02-01T00:00:00Z"),
                pd.Timestamp("2026-03-01T00:00:00Z"),
                pd.Timestamp("2026-03-01T00:00:00Z"),
            ],
            "machine": ["M1", "M2", "M1", "M2", "M1", "M2"],
            "length_mm__mean": [14.0, 14.8, 15.4, 16.1, 24.0, 23.6],
            "raw_row_count": [5_000, 5_000, 5_000, 5_000, 5_000, 5_000],
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
            source_row_count=row_count,
            output_row_count=len(aggregate_frame.index),
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

    hybrid_chart = manifest["charts"][1]
    spec = hybrid_chart["plotly_spec"]
    layout = spec["layout"]
    raw_layer_traces = [trace for trace in spec["data"] if "metroliza_raw_layer_index" in trace]
    aggregate_traces = [trace for trace in spec["data"] if trace["name"].endswith("aggregate")]

    assert hybrid_chart["chart_type"] == "time_series_raw_aggregate"
    assert layout["images"]
    assert raw_layer_traces
    assert layout["xaxis"]["autorange"] is False
    assert layout["yaxis"]["autorange"] is False
    assert pd.Timestamp(layout["xaxis"]["range"][0], tz="UTC") <= pd.Timestamp(
        "2026-01-01T00:00:00Z"
    )
    assert float(layout["yaxis"]["range"][1]) >= 24.0
    assert aggregate_traces
    assert all(trace["marker"]["symbol"] == "x" for trace in aggregate_traces)
    assert all("T00:00:00+00:00" in str(trace["x"][0]) for trace in aggregate_traces if trace["x"])
    assert all("-" in str(trace["x"][0]) for trace in aggregate_traces if trace["x"])


def test_very_large_time_series_uses_sampled_raw_image_layers(tmp_path) -> None:
    row_count = 60_000
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range(
                "2026-05-10 08:00",
                periods=row_count,
                freq="s",
                tz="UTC",
            ),
            "GROUP": ["A" if index % 2 == 0 else "B" for index in range(row_count)],
            "length_mm": [float(index % 100) for index in range(row_count)],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm"),),
        aggregation_state=ProductionAggregationState(
            time_bucket="none",
            aggregation_methods=("mean",),
            group_fields=("GROUP",),
        ),
        chart_selection=ProductionChartSelection(
            time_series=True,
            histogram=False,
            violin=False,
            box=False,
            groupstats=False,
        ),
    )

    chart = manifest["charts"][0]
    spec = chart["plotly_spec"]
    raw_traces = [
        trace for trace in spec["data"] if "metroliza_raw_layer_index" in trace
    ]
    aggregate_traces = [
        trace for trace in spec["data"] if "metroliza_raw_layer_index" not in trace
    ]

    assert raw_traces
    assert len(spec["layout"]["images"]) == 2
    assert all(image["source"].startswith("data:image/png;base64,") for image in spec["layout"]["images"])
    assert sum(len(trace["x"]) for trace in aggregate_traces) < 1_000
    assert chart["notes"] == [
        "Raw layer shows 50,000 randomly sampled points from 60,000 rows; statistics use all rows."
    ]

    output_file = tmp_path / "large_dashboard.html"
    write_production_dashboard(manifest, output_file)
    html_text = output_file.read_text(encoding="utf-8")

    assert "metroliza_raw_layer_index" in html_text
    assert len(html_text.encode("utf-8")) < 6 * 1024 * 1024


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
        assert chart["group_labels"] == ["M1", "M2"]
        if "plotly_spec" in chart:
            assert chart["plotly_spec"]["config"].get("staticPlot") is not True
            if chart_type == "histogram":
                assert chart["plotly_spec"]["layout"]["yaxis"]["title"]["text"] == "Frequency (%)"
        else:
            assert chart["image"]["mime_type"] == "image/png"


def test_distribution_charts_force_numeric_group_names_to_categories() -> None:
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=6, freq="h"),
            "GROUP": ["73211", "73211", "A", "A", "POPULATION", "POPULATION"],
            "length_mm": [10.0, 10.2, 11.0, 11.2, 9.8, 10.1],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm"),),
        aggregation_state=ProductionAggregationState(
            time_bucket="none",
            aggregation_methods=("mean",),
            group_fields=("GROUP",),
        ),
        chart_selection=ProductionChartSelection(
            time_series=False,
            histogram=False,
            violin=True,
            box=True,
            groupstats=False,
        ),
    )

    for chart_type in {"violin", "box"}:
        chart = next(chart for chart in manifest["charts"] if chart["chart_type"] == chart_type)
        assert chart["group_labels"] == ["73211", "A", "POPULATION"]
        if "plotly_spec" in chart:
            assert chart["plotly_spec"]["config"].get("staticPlot") is not True
        else:
            assert chart["image"]["mime_type"] == "image/png"


def test_dashboard_uses_plotstats_interactive_plotly_specs_when_available(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_plotstats_spec(payload, *, title, theme, static):
        calls.append({"payload": payload, "title": title, "theme": theme, "static": static})
        return {
            "data": [{"type": "scatter", "x": [1.0], "y": [2.0]}],
            "layout": {"title": {"text": title}},
            "config": {"responsive": True},
        }

    monkeypatch.setattr(
        "modules.industrial_analytics_dashboard.build_dashboard_plotly_spec",
        fake_plotstats_spec,
    )
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "length_mm": [10.0, 10.2, 10.4, 10.6],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm", lsl=9.0, usl=11.0),),
        chart_selection=ProductionChartSelection(
            time_series=False,
            histogram=True,
            violin=True,
            box=True,
            groupstats=False,
        ),
    )

    charts = {chart["chart_type"]: chart for chart in manifest["charts"]}
    assert charts["histogram"]["plotly_spec"]["config"].get("staticPlot") is not True
    assert charts["violin"]["plotly_spec"]["config"].get("staticPlot") is not True
    assert charts["box"]["plotly_spec"]["config"].get("staticPlot") is not True
    assert [call["payload"]["type"] for call in calls] == ["histogram", "distribution", "iqr"]
    assert all(call["static"] is False for call in calls)
    assert calls[0]["payload"]["limits"] == {"lsl": 9.0, "nominal": 10.0, "usl": 11.0}


def test_groupstats_html_renders_overall_and_ordered_pairwise_rows(tmp_path) -> None:
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=3, freq="h"),
            "GROUP": ["POPULATION", "A", "B"],
            "length_mm": [10.0, 12.0, 10.1],
        }
    )
    groupstats = ProductionGroupstatsResult(
        metrics=(
            {
                "metric": "Length Mm",
                "skipped": False,
                "primary_insight": {"headline": "A differs from the population."},
                "descriptive_stats": [],
                "distribution_rows": [],
                "omnibus": {
                    "test_name": "Welch ANOVA",
                    "p_value": 0.001,
                    "effect_size": 0.9,
                    "effect_type": "eta_squared",
                    "significant": True,
                },
                "pairwise_rows": [
                    {
                        "group_a": "POPULATION",
                        "group_b": "A",
                        "delta_mean": -2.0,
                        "p_value": 0.001,
                        "adjusted_p_value": 0.003,
                        "effect_size": 1.2,
                        "significant": True,
                        "test_used": "Tukey HSD",
                    },
                    {
                        "group_a": "POPULATION",
                        "group_b": "B",
                        "delta_mean": -0.1,
                        "p_value": 0.8,
                        "adjusted_p_value": 0.8,
                        "effect_size": 0.02,
                        "significant": False,
                        "test_used": "Tukey HSD",
                    },
                    {
                        "group_a": "A",
                        "group_b": "B",
                        "delta_mean": 1.9,
                        "p_value": 0.002,
                        "adjusted_p_value": 0.006,
                        "effect_size": 1.1,
                        "significant": True,
                        "test_used": "Tukey HSD",
                    },
                ],
                "posthoc_rows": [
                    {
                        "group_a": "POPULATION",
                        "group_b": "A",
                        "method_name": "Games-Howell",
                        "family": "parametric",
                        "adjusted_p_value": 0.003,
                        "effect_size": 1.2,
                        "effect_type": "hedges_g",
                        "significant": True,
                    }
                ],
            },
        ),
    )
    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm"),),
        chart_selection=ProductionChartSelection(
            time_series=False,
            histogram=False,
            violin=False,
            box=False,
            groupstats=True,
        ),
        groupstats_result=groupstats,
    )
    output_file = tmp_path / "dashboard.html"

    write_production_dashboard(manifest, output_file)

    html_text = output_file.read_text(encoding="utf-8")
    assert '<details class="stats-section">' in html_text
    assert "<summary>Groupstats (1 metric)</summary>" in html_text
    assert '<details class="stats-card">' in html_text
    assert "Overall group test" in html_text
    assert "<summary>Pairwise tests (3 rows)</summary>" in html_text
    assert "<summary>Post-hoc tests (1 row)</summary>" in html_text
    assert "<h3>Pairwise tests</h3>" not in html_text
    assert "Welch ANOVA" in html_text
    assert "Pairwise tests" in html_text
    assert "Post-hoc tests" in html_text
    assert "Games-Howell" in html_text
    assert "hedges_g" in html_text
    assert html_text.index("<td>POPULATION</td><td>A</td>") < html_text.index(
        "<td>POPULATION</td><td>B</td>"
    )
    assert html_text.index("<td>POPULATION</td><td>B</td>") < html_text.index(
        "<td>A</td><td>B</td>"
    )

from __future__ import annotations

import base64
from io import BytesIO
import json
import re
from pathlib import Path

import pandas as pd
import pytest

import modules.industrial_analytics_dashboard as dashboard_module
from modules.industrial_analytics_dashboard import (
    DASHBOARD_RAW_POINT_LIMIT,
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


def test_dashboard_visual_preview_labels_derive_from_industrial_chart_groups() -> None:
    labels = dashboard_module._dashboard_visual_preview_labels_from_charts(
        [
            {
                "group_labels": ["POPULATION", "DUPA", "TEST123"],
                "plotly_spec": {
                    "data": [
                        {"type": "histogram", "name": "POPULATION"},
                        {"type": "histogram", "name": "DUPA"},
                        {"type": "histogram", "name": "TEST123"},
                        {"type": "scatter", "mode": "lines", "name": "(DUPA) Mean=6.5"},
                    ],
                    "layout": {},
                },
            }
        ]
    )

    assert labels == ("POPULATION", "DUPA", "TEST123", "Group 3", "Group 4")


def _production_dashboard_fixture(tmp_path, *, include_plotly_specs: bool = True):
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
        include_plotly_specs=include_plotly_specs,
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
    assert histogram["image"]["mime_type"] == "image/png"
    if "plotly_spec" in histogram:
        assert histogram["plotly_spec"]["config"].get("staticPlot") is not True
        assert histogram["plotly_spec"]["layout"]["yaxis"]["title"]["text"] == "Frequency (%)"
    assert any(
        row["label"] == "Samples"
        for table in histogram["stats_tables"]
        for row in table["rows"]
    )


def test_build_production_dashboard_manifest_can_skip_plotly_specs(
    tmp_path,
    monkeypatch,
) -> None:
    def fail_plotly_spec(*_args, **_kwargs):
        raise AssertionError("static dashboard mode should not build Plotly specs")

    monkeypatch.setattr(dashboard_module, "build_dashboard_plotly_spec", fail_plotly_spec)
    monkeypatch.setattr(dashboard_module, "build_plotstats_dashboard_spec", fail_plotly_spec)

    manifest = _production_dashboard_fixture(tmp_path, include_plotly_specs=False)

    assert manifest["charts"]
    assert all("plotly_spec" not in chart for chart in manifest["charts"])
    time_series = next(chart for chart in manifest["charts"] if chart["chart_type"] == "time_series")
    assert any("Snapshots only mode" in note for note in time_series.get("notes", []))
    histogram = next(chart for chart in manifest["charts"] if chart["chart_type"] == "histogram")
    assert histogram["image"]["mime_type"] == "image/png"


def test_dashboard_chart_layout_reserves_title_and_legend_spacing(tmp_path) -> None:
    manifest = _production_dashboard_fixture(tmp_path)

    layout = manifest["charts"][0]["plotly_spec"]["layout"]

    assert layout["margin"]["t"] >= 110
    assert layout["legend"]["y"] > 1.0
    assert layout["title"]["y"] >= 0.99


def test_distribution_plotly_payloads_are_sampled_for_large_frames() -> None:
    row_count = DASHBOARD_RAW_POINT_LIMIT + 128
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-01", periods=row_count, freq="s", tz="UTC"),
            "line": ["L1" if index % 2 == 0 else "L2" for index in range(row_count)],
            "length_mm": [10.0 + (index % 100) * 0.01 for index in range(row_count)],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm"),),
        aggregation_state=ProductionAggregationState(group_fields=("line",)),
        chart_selection=ProductionChartSelection(
            time_series=False,
            histogram=True,
            violin=True,
            box=True,
            groupstats=False,
        ),
    )

    assert {chart["chart_type"] for chart in manifest["charts"]} == {"histogram", "violin", "box"}
    for chart in manifest["charts"]:
        assert chart["notes"]
        assert "statistics use all rows" in chart["notes"][0]
        if "plotly_spec" not in chart:
            assert chart["image"]["mime_type"] == "image/png"
            continue
        trace_points = 0
        for trace in chart["plotly_spec"]["data"]:
            if chart["chart_type"] in {"violin", "box"} and trace.get("type") == "scatter":
                continue
            trace_points += max(
                len(value)
                for key in ("x", "y")
                if isinstance((value := trace.get(key)), list)
            )
        assert trace_points <= DASHBOARD_RAW_POINT_LIMIT


def test_static_image_sampling_caps_total_when_group_count_exceeds_budget(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DASHBOARD_RAW_POINT_LIMIT", 3)
    groups = [
        (f"group-{index}", pd.DataFrame({"length_mm": [float(index)]}))
        for index in range(5)
    ]

    sampled_groups, note = dashboard_module._sample_plot_groups_for_static_image(
        groups,
        "length_mm",
        seed_parts=("cap-test",),
    )

    sampled_total = sum(len(group.index) for _label, group in sampled_groups)
    nonempty_groups = [label for label, group in sampled_groups if len(group.index) > 0]
    assert sampled_total == 3
    assert len(nonempty_groups) == 3
    assert note is not None
    assert "Plot shows 3 randomly sampled points from 5 rows" in note


def test_write_production_dashboard_writes_offline_plotly_html(tmp_path) -> None:
    manifest = _production_dashboard_fixture(tmp_path)
    output_file = tmp_path / "production_dashboard.html"

    result = write_production_dashboard(
        manifest,
        output_file,
        dashboard_visual_settings={
            "preset": "custom",
            "palette_preset": "custom",
            "palette_mode": "fixed",
            "palette": ["#123456", "#abcdef"],
        },
    )

    html_path = Path(result["html_dashboard_path"])
    assets_path = Path(result["html_dashboard_assets_path"])
    assert "plotly_budget_status" not in manifest["summary"]
    assert result["html_dashboard_chart_count"] == 5
    assert result["html_dashboard_interactive_chart_count"] == result[
        "html_dashboard_embedded_plotly_spec_count"
    ]
    assert result["html_dashboard_plotly_spec_count"] >= 2
    assert result["html_dashboard_plotly_serialized_json_bytes"] > 0
    assert result["html_dashboard_embedded_plotly_serialized_json_bytes"] == result[
        "html_dashboard_plotly_serialized_json_bytes"
    ]
    assert result["html_dashboard_html_bytes"] > 0
    assert result["html_dashboard_plotly_budget"]["status"] == "within_budget"
    assert html_path.exists()
    assert (assets_path / "plotly-2.27.0.min.js").exists()

    html_text = html_path.read_text(encoding="utf-8")
    assert "Production Analytics" in html_text
    assert "plotly-2.27.0.min.js" in html_text
    assert "cdn.plot.ly" not in html_text
    assert "theme-switch" in html_text
    assert "dashboard-control-bar" in html_text
    assert '.theme-option[data-active="1"]' in html_text
    assert 'data-theme-choice="auto"' in html_text
    assert 'data-theme-choice="light"' in html_text
    assert 'data-theme-choice="dark"' in html_text
    assert "metroliza-dashboard-theme" in html_text
    assert "prefers-color-scheme: dark" in html_text
    assert "dataset.themeChoice" in html_text
    assert "Plotly.react" in html_text
    assert "visual-settings-trigger" in html_text
    assert "dashboard-visual-dialog" in html_text
    assert "metroliza-dashboard-visuals" in html_text
    assert "applyDashboardVisualsToPlotlySpec(baseSpec)" in html_text
    assert '"initialSettings":{' in html_text
    assert '"preset":"custom"' in html_text
    assert '"palette_preset":"custom"' in html_text
    assert "#123456" in html_text
    assert "initializeDashboardVisualControls();" in html_text
    assert "refreshOpenLightboxPlotly();" in html_text
    assert "raw_record_json" not in html_text
    assert "Selected references" in html_text
    assert "Descriptive stats" in html_text
    assert "Samples" in html_text
    assert (
        'class="plotly-chart" id="histogram-cycle_time_s"' in html_text
        or 'class="chart-image"' in html_text
    )
    assert "Image snapshot" in html_text
    assert '<details class="chart-stats">' in html_text
    assert "<summary>Chart statistics (" in html_text
    assert 'class="plotly-expand-trigger"' in html_text
    assert 'id="chart-lightbox"' in html_text
    assert 'id="chart-lightbox-plotly"' in html_text
    assert "const chartById = new Map" in html_text
    assert ".chart-stats th" in html_text
    assert "background: #0f172a" in html_text
    assert '<header class="hero" id="dashboard-start">' in html_text
    assert '<nav class="section-nav">' in html_text
    assert '<a class="section-chip" href="#groupstats">Group comparison</a>' in html_text
    assert 'Back to dashboard start</a>' in html_text
    assert 'id="chart-time-series-cycle-time-s-aggregated"' in html_text
    assert "color: #f8fafc" in html_text
    assert ".chart-stats-title" in html_text
    assert "color: #0f172a" in html_text
    assert "<th>Statistic</th><th>Value</th>" in html_text
    assert "grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr));" in html_text
    assert '<div class="metric-label">Summary points</div>' in html_text
    assert '<div class="metric-label">Groups</div>' in html_text
    assert "Pasted reference cohorts" in html_text
    assert '<div class="metric-label">Reference rows</div>' in html_text
    assert '<div class="metric-label">Group comparison</div>' in html_text
    assert '<div class="metric-label">Reference cohort</div>' not in html_text
    assert '<div class="metric-label">Stats metrics</div>' not in html_text

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


def test_write_production_dashboard_omits_plotly_when_payload_exceeds_budget(tmp_path) -> None:
    manifest = _production_dashboard_fixture(tmp_path)
    output_file = tmp_path / "production_dashboard.html"

    result = write_production_dashboard(
        manifest,
        output_file,
        plotly_spec_count_budget=0,
        plotly_serialized_json_bytes_budget=10_000_000,
    )

    html_text = output_file.read_text(encoding="utf-8")
    assert result["html_dashboard_chart_count"] == 5
    assert result["html_dashboard_plotly_spec_count"] > 0
    assert result["html_dashboard_interactive_chart_count"] == 0
    assert result["html_dashboard_embedded_plotly_spec_count"] == 0
    assert result["html_dashboard_plotly_serialized_json_bytes"] > 0
    assert result["html_dashboard_embedded_plotly_serialized_json_bytes"] == 0
    assert result["html_dashboard_html_bytes"] > 0
    assert result["html_dashboard_plotly_budget"]["status"] == "over_budget"
    assert "spec_count>0" in result["html_dashboard_plotly_budget"]["reason"]
    assert "production-dashboard-charts" not in html_text
    assert "plotly-2.27.0.min.js" not in html_text
    assert "theme-switch" in html_text
    assert 'data-theme-choice="auto"' in html_text
    assert "metroliza-dashboard-theme" in html_text
    assert 'id="dashboard-visual-dialog"' not in html_text
    assert '<button type="button" class="visual-settings-trigger"' not in html_text
    assert 'class="chart-image"' in html_text
    histogram = next(chart for chart in manifest["charts"] if chart["chart_type"] == "histogram")
    assert histogram["image"]["mime_type"] == "image/png"
    assert "Cycle Time S distribution" in html_text
    assert "Cycle Time S violin" in html_text
    assert "Cycle Time S box" in html_text
    assert "Some interactive charts were replaced with image snapshots" in html_text
    assert "Interactive chart replaced with an image snapshot because this chart would make" in html_text
    assert not (Path(result["html_dashboard_assets_path"]) / "plotly-2.27.0.min.js").exists()
    assert any("plotly_spec" in chart for chart in manifest["charts"])


def test_write_production_dashboard_omits_plotly_chart_by_chart_when_payload_exceeds_budget(
    tmp_path,
) -> None:
    manifest = _production_dashboard_fixture(tmp_path)
    output_file = tmp_path / "production_dashboard.html"
    spec_count = dashboard_module._count_plotly_specs(manifest)

    result = write_production_dashboard(
        manifest,
        output_file,
        plotly_spec_count_budget=spec_count - 1,
        plotly_serialized_json_bytes_budget=10_000_000,
    )

    html_text = output_file.read_text(encoding="utf-8")
    assert result["html_dashboard_plotly_spec_count"] == spec_count
    assert result["html_dashboard_embedded_plotly_spec_count"] == spec_count - 1
    assert result["html_dashboard_interactive_chart_count"] == spec_count - 1
    assert result["html_dashboard_plotly_budget"]["status"] == "over_budget"
    assert "production-dashboard-charts" in html_text
    assert "plotly-2.27.0.min.js" in html_text
    assert "Some interactive charts were replaced with image snapshots" in html_text
    assert "Interactive chart replaced with an image snapshot because this chart would make" in html_text
    chart_payload = json.loads(
        re.search(
            r'<script id="production-dashboard-charts" type="application/json">(.*?)</script>',
            html_text,
            re.DOTALL,
        ).group(1)
    )
    assert len(chart_payload) == spec_count - 1


def test_write_production_dashboard_static_interactivity_suppresses_plotly_specs(
    tmp_path,
) -> None:
    manifest = _production_dashboard_fixture(tmp_path)
    output_file = tmp_path / "production_dashboard.html"

    result = write_production_dashboard(
        manifest,
        output_file,
        dashboard_interactivity_options={"mode": "static", "sample_size": 123},
    )

    html_text = output_file.read_text(encoding="utf-8")
    assert result["html_dashboard_plotly_spec_count"] > 0
    assert result["html_dashboard_embedded_plotly_spec_count"] == 0
    assert result["html_dashboard_interactive_chart_count"] == 0
    assert result["html_dashboard_plotly_runtime_status"] == "static_snapshot_only"
    assert result["html_dashboard_plotly_budget"]["status"] == "within_budget"
    assert result["html_dashboard_static_population_layer"]["status"] == "dashboard_static"
    assert "production-dashboard-charts" not in html_text
    assert "plotly-2.27.0.min.js" not in html_text
    assert "Interactive chart replaced with an image snapshot because Snapshots only mode was selected" in html_text
    assert any("plotly_spec" in chart for chart in manifest["charts"])


def test_write_production_dashboard_falls_back_to_snapshots_when_plotly_bundle_missing(
    tmp_path,
    monkeypatch,
) -> None:
    manifest = _production_dashboard_fixture(tmp_path)
    output_file = tmp_path / "production_dashboard.html"
    missing_bundle = tmp_path / "missing-plotly.min.js"
    monkeypatch.setattr(
        "modules.industrial_analytics_dashboard._resolve_bundled_plotly_js_path",
        lambda: missing_bundle,
    )

    result = write_production_dashboard(manifest, output_file)

    html_text = output_file.read_text(encoding="utf-8")
    assets_path = Path(result["html_dashboard_assets_path"])
    assert result["html_dashboard_plotly_spec_count"] > 0
    assert result["html_dashboard_interactive_chart_count"] == 0
    assert result["html_dashboard_embedded_plotly_spec_count"] == 0
    assert result["html_dashboard_plotly_runtime_status"] == "snapshot_only"
    assert result["html_dashboard_plotly_budget"]["status"] == "within_budget"
    assert "production-dashboard-charts" not in html_text
    assert "plotly-2.27.0.min.js" not in html_text
    assert 'id="dashboard-visual-dialog"' not in html_text
    assert "the bundled Plotly runtime asset was not found" in html_text
    assert "Interactive chart replaced with an image snapshot because the interactive chart library was unavailable" in html_text
    assert 'class="chart-image"' in html_text
    assert not (assets_path / "plotly-2.27.0.min.js").exists()
    assert any("plotly_spec" in chart for chart in manifest["charts"])


def test_write_production_dashboard_collapses_diagnostics_by_default(tmp_path) -> None:
    manifest = _production_dashboard_fixture(tmp_path)
    manifest["diagnostics"] = [
        {"severity": "warning", "code": "sample", "message": "Diagnostic details"},
        {
            "severity": "info",
            "code": "tabular_sqlite_column_pruning",
            "message": "CSV/Excel analytics projected a reduced SQLite column set before materialization.",
        },
        {"severity": "info", "code": "debug", "message": "Backend diagnostics: raw_record_json"},
    ]
    output_file = tmp_path / "production_dashboard.html"

    write_production_dashboard(manifest, output_file)

    html_text = output_file.read_text(encoding="utf-8")
    assert '<details id="attention-needed" class="dashboard-messages attention-needed" open>' in html_text
    assert "<summary>Attention needed (1)</summary>" in html_text
    assert "<summary>Run notes (1)</summary>" in html_text
    assert "Only the columns needed for this dashboard were prepared" in html_text
    assert "Backend diagnostics" not in html_text
    assert "raw_record_json" not in html_text
    assert "<h2>Diagnostics</h2>" not in html_text
    assert '<a class="section-chip" href="#attention-needed">Attention needed</a>' in html_text


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


def test_large_time_series_interactive_population_mode_keeps_plotly_markers(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DASHBOARD_RAW_POINT_LIMIT", 5)
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range(
                "2026-05-10 08:00",
                periods=8,
                freq="s",
                tz="UTC",
            ),
            "GROUP": ["POPULATION"] * 6 + ["A"] * 2,
            "length_mm": [float(index) for index in range(8)],
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
        dashboard_interactivity_options={"population_layer_mode": "interactive"},
    )

    spec = manifest["charts"][0]["plotly_spec"]
    assert {trace["name"] for trace in spec["data"]} == {"POPULATION", "A"}
    assert "images" not in spec["layout"]


def test_large_time_series_static_population_mode_marks_existing_raw_layer(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(dashboard_module, "DASHBOARD_RAW_POINT_LIMIT", 5)
    monkeypatch.setattr(
        dashboard_module,
        "_render_time_series_raw_layer_png",
        lambda *_args, **_kwargs: b"png",
    )
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range(
                "2026-05-10 08:00",
                periods=8,
                freq="s",
                tz="UTC",
            ),
            "GROUP": ["POPULATION"] * 6 + ["A"] * 2,
            "length_mm": [float(index) for index in range(8)],
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
        dashboard_interactivity_options={"population_layer_mode": "static"},
    )

    chart = manifest["charts"][0]
    spec = chart["plotly_spec"]
    population_trace = next(trace for trace in spec["data"] if trace["name"] == "POPULATION raw layer")
    image_index = population_trace["metroliza_static_population_layer_index"]
    assert spec["layout"]["images"][image_index]["metroliza_static_population_layer_label"] == "POPULATION"

    result = write_production_dashboard(
        manifest,
        tmp_path / "population_raw_layer.html",
        dashboard_interactivity_options={"population_layer_mode": "static"},
    )

    assert result["html_dashboard_static_population_layer"]["status"] == "applied"
    assert result["html_dashboard_static_population_layer"]["source_point_count"] == 6


def test_static_population_layer_optimization_marked_available(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DASHBOARD_RAW_POINT_LIMIT", 5)
    monkeypatch.setattr(
        dashboard_module,
        "_render_time_series_raw_layer_png",
        lambda *_args, **_kwargs: b"png",
    )
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range(
                "2026-05-10 08:00",
                periods=8,
                freq="s",
                tz="UTC",
            ),
            "GROUP": ["POPULATION"] * 8,
            "length_mm": [float(index) for index in range(8)],
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
        include_plotly_specs=False,
    )

    chart = manifest["charts"][0]
    option = chart["optimization_options"][0]
    assert "plotly_spec" not in chart
    assert manifest["summary"]["available_optimization_options"] == ["static_population_layer"]
    assert option["id"] == "static_population_layer"
    assert option["available"] is True
    assert option["group_label"] == "POPULATION"
    assert option["source_point_count"] == 8
    assert option["sample_point_limit"] == 5


def test_static_population_layer_converts_single_population_group_under_sample_cap(
    tmp_path,
) -> None:
    from PIL import Image

    point_count = 5_000
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range(
                "2026-05-10 08:00",
                periods=point_count,
                freq="s",
                tz="UTC",
            ),
            "GROUP": ["POPULATION"] * point_count,
            "length_mm": [10.0 + (index % 100) * 0.01 for index in range(point_count)],
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
        dashboard_interactivity_options={
            "mode": "sampled",
            "sample_size": 50_000,
            "population_layer_mode": "static",
        },
    )

    result = write_production_dashboard(
        manifest,
        tmp_path / "single_population_static.html",
        dashboard_interactivity_options={
            "mode": "sampled",
            "sample_size": 50_000,
            "population_layer_mode": "static",
        },
    )

    html_text = Path(result["html_dashboard_path"]).read_text(encoding="utf-8")
    chart = _embedded_dashboard_charts(html_text)[0]
    spec = chart["plotly_spec"]
    image_source = spec["layout"]["images"][0]["source"]
    png_bytes = base64.b64decode(image_source.removeprefix("data:image/png;base64,"))
    image = Image.open(BytesIO(png_bytes))

    assert [trace["name"] for trace in spec["data"]] == ["POPULATION static layer"]
    assert spec["layout"]["xaxis"]["type"] == "date"
    assert spec["layout"]["images"][0]["metroliza_static_population_layer_label"] == "POPULATION"
    assert image.getchannel("A").getextrema()[1] >= 32
    static_population = result["html_dashboard_static_population_layer"]
    assert static_population["mode"] == "static"
    assert static_population["applied_chart_count"] == 1
    assert static_population["source_point_count"] == point_count
    assert static_population["rendered_point_count"] == point_count
    assert static_population["contributed_point_count"] == point_count
    assert static_population["render_strategy_counts"] == {"marker_static": 1}
    assert static_population["skipped_chart_count"] == 0
    assert static_population["sample_size"] == 50_000
    assert static_population["status"] == "applied"
    assert "Interactive charts use all selected rows; random sampling was not needed." in html_text


def _static_population_layer_manifest(point_count: int = 8) -> dict[str, object]:
    x_values = [
        value.isoformat()
        for value in pd.date_range("2026-05-10 08:00", periods=point_count, freq="s", tz="UTC")
    ]
    return {
        "schema": DASHBOARD_SCHEMA,
        "summary": {
            "source_rows": point_count + 2,
            "metric_count": 1,
            "chart_count": 1,
        },
        "charts": [
            {
                "id": "time-series-length_mm",
                "title": "Length Mm over time",
                "chart_type": "time_series",
                "plotly_spec": {
                    "data": [
                        {
                            "type": "scatter",
                            "mode": "markers",
                            "name": "POPULATION",
                            "x": x_values,
                            "y": [float(index) for index in range(point_count)],
                            "marker": {"color": "#245a5a"},
                        },
                        {
                            "type": "scatter",
                            "mode": "markers",
                            "name": "A",
                            "x": x_values[:2],
                            "y": [1.0, 2.0],
                            "marker": {"color": "#d55e00"},
                        },
                    ],
                    "layout": {"xaxis": {"title": "Process time"}, "yaxis": {"title": "Length Mm"}},
                    "config": {"responsive": True},
                },
            }
        ],
        "groupstats": {},
        "diagnostics": [],
    }


def _embedded_dashboard_charts(html_text: str) -> list[dict[str, object]]:
    match = re.search(
        r'<script id="production-dashboard-charts" type="application/json">(.*?)</script>',
        html_text,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def test_write_dashboard_static_population_layer_mode_converts_supported_time_series(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        dashboard_module,
        "_render_time_series_raw_layer_png",
        lambda *_args, **_kwargs: b"png",
    )
    manifest = _static_population_layer_manifest()

    result = write_production_dashboard(
        manifest,
        tmp_path / "population_static.html",
        dashboard_interactivity_options={"population_layer_mode": "static"},
    )

    html_text = Path(result["html_dashboard_path"]).read_text(encoding="utf-8")
    chart = _embedded_dashboard_charts(html_text)[0]
    spec = chart["plotly_spec"]
    traces = spec["data"]
    assert [trace["name"] for trace in traces] == ["POPULATION static layer", "A"]
    assert traces[0]["metroliza_static_population_layer_index"] == 0
    assert traces[0]["meta"]["metroliza_role"] == "static_population_layer"
    assert spec["layout"]["images"][0]["source"].startswith("data:image/png;base64,")
    assert spec["layout"]["images"][0]["metroliza_static_population_layer_label"] == "POPULATION"
    assert spec["layout"]["xaxis"]["autorange"] is False
    assert spec["layout"]["yaxis"]["autorange"] is False
    assert result["html_dashboard_static_population_layer"]["status"] == "applied"
    assert result["html_dashboard_static_population_layer"]["applied_chart_count"] == 1
    assert "Static POPULATION layers keep the process background visible" in html_text
    assert "hover and point selection are unavailable" in html_text
    assert "plotly_spec" in manifest["charts"][0]


def test_static_population_layer_uses_population_marker_style(
    tmp_path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_raw_layer(*_args, **kwargs):
        captured.update(kwargs)
        return b"png"

    monkeypatch.setattr(dashboard_module, "_render_time_series_raw_layer_png", fake_raw_layer)
    manifest = _static_population_layer_manifest()
    population_trace = manifest["charts"][0]["plotly_spec"]["data"][0]
    population_trace["marker"]["size"] = 8.0
    population_trace["marker"]["opacity"] = 0.5

    write_production_dashboard(
        manifest,
        tmp_path / "population_static_style.html",
        dashboard_interactivity_options={"population_layer_mode": "static"},
    )

    assert captured["color"] == "#245a5a"
    assert captured["marker_size"] == pytest.approx(10.0)
    assert captured["opacity"] == pytest.approx(0.68)


def test_write_dashboard_static_population_layer_interactive_mode_keeps_trace(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        dashboard_module,
        "_render_time_series_raw_layer_png",
        lambda *_args, **_kwargs: b"png",
    )
    manifest = _static_population_layer_manifest()

    result = write_production_dashboard(
        manifest,
        tmp_path / "population_interactive.html",
        dashboard_interactivity_options={"populationLayerMode": "interactive"},
    )

    html_text = Path(result["html_dashboard_path"]).read_text(encoding="utf-8")
    chart = _embedded_dashboard_charts(html_text)[0]
    spec = chart["plotly_spec"]
    assert [trace["name"] for trace in spec["data"]] == ["POPULATION", "A"]
    assert "images" not in spec["layout"]
    assert result["html_dashboard_static_population_layer"]["status"] == "interactive"


def test_write_dashboard_static_population_layer_auto_applies_only_above_threshold(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(dashboard_module, "DASHBOARD_RAW_POINT_LIMIT", 5)
    monkeypatch.setattr(
        dashboard_module,
        "_render_time_series_raw_layer_png",
        lambda *_args, **_kwargs: b"png",
    )

    large_result = write_production_dashboard(
        _static_population_layer_manifest(point_count=8),
        tmp_path / "population_auto_large.html",
        dashboard_interactivity_options={"population_layer_mode": "auto"},
    )
    small_result = write_production_dashboard(
        _static_population_layer_manifest(point_count=4),
        tmp_path / "population_auto_small.html",
        dashboard_interactivity_options={"population_layer_mode": "auto"},
    )

    large_html = Path(large_result["html_dashboard_path"]).read_text(encoding="utf-8")
    small_html = Path(small_result["html_dashboard_path"]).read_text(encoding="utf-8")
    assert _embedded_dashboard_charts(large_html)[0]["plotly_spec"]["layout"]["images"]
    assert "images" not in _embedded_dashboard_charts(small_html)[0]["plotly_spec"]["layout"]
    assert large_result["html_dashboard_static_population_layer"]["status"] == "applied"
    assert small_result["html_dashboard_static_population_layer"]["status"] == "not_applicable"


def test_write_dashboard_static_population_layer_converts_sampled_dashboard_frame(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        dashboard_module,
        "_STATIC_POPULATION_DENSITY_POINT_THRESHOLD",
        5,
    )
    monkeypatch.setattr(
        dashboard_module,
        "_render_time_series_density_layer_png",
        lambda *_args, **_kwargs: (b"png", 4),
    )
    full_frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range(
                "2026-05-10 08:00",
                periods=12,
                freq="s",
                tz="UTC",
            ),
            "GROUP": ["POPULATION"] * 12,
            "length_mm": [10.0 + (index * 0.01) for index in range(12)],
        }
    )
    dashboard_frame = full_frame.iloc[:5].copy()
    manifest = build_production_dashboard_manifest(
        frame=dashboard_frame,
        static_population_source_frame=full_frame,
        source_row_count=len(full_frame.index),
        dashboard_row_count=len(dashboard_frame.index),
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
        dashboard_interactivity_options={
            "mode": "sampled",
            "sample_size": 5,
            "population_layer_mode": "static",
        },
    )
    spec = manifest["charts"][0]["plotly_spec"]
    for trace in spec["data"]:
        trace["x"] = [f"{index}.0" for index in range(len(trace.get("x") or []))]
    manifest["charts"][0]["optimization_options"][0][
        dashboard_module._STATIC_POPULATION_SOURCE_XY_KEY
    ] = pd.DataFrame(
        {
            "__x_numeric": [float(index) for index in range(12)],
            "__y": [10.0 + (index * 0.01) for index in range(12)],
            "__x_mode": ["linear"] * 12,
        }
    )

    result = write_production_dashboard(
        manifest,
        tmp_path / "population_static_sampled.html",
        dashboard_interactivity_options={
            "mode": "sampled",
            "sample_size": 5,
            "population_layer_mode": "static",
        },
    )

    html_text = Path(result["html_dashboard_path"]).read_text(encoding="utf-8")
    chart = _embedded_dashboard_charts(html_text)[0]
    spec = chart["plotly_spec"]
    static_population = result["html_dashboard_static_population_layer"]
    proxy_trace = spec["data"][0]
    assert proxy_trace["name"] == "POPULATION static layer"
    assert proxy_trace["meta"]["metroliza_render_strategy"] == "full_density"
    assert spec["layout"]["images"][0]["metroliza_static_population_layer_label"] == "POPULATION"
    image_bounds = proxy_trace["metroliza_static_population_image_bounds"]
    view_bounds = proxy_trace["metroliza_static_population_view_bounds"]
    assert image_bounds["x_max"] > view_bounds["x_max"]
    assert image_bounds["y_max"] > view_bounds["y_max"]
    assert spec["layout"]["yaxis"]["range"][1] == pytest.approx(view_bounds["y_max"])
    assert proxy_trace["x"] != [None]
    assert proxy_trace["y"][0] == pytest.approx(view_bounds["y_min"])
    assert proxy_trace["y"][1] == pytest.approx(view_bounds["y_max"])
    assert static_population["status"] == "applied"
    assert static_population["dashboard_sampled"] is True
    assert static_population["source_row_count"] == 12
    assert static_population["dashboard_row_count"] == 5
    assert static_population["source_point_count"] == 12
    assert static_population["rendered_point_count"] == 12
    assert static_population["contributed_point_count"] == 12
    assert static_population["render_strategy_counts"] == {"full_density": 1}
    assert "Static POPULATION density layers keep the full process background visible" in html_text


def test_write_dashboard_static_population_layer_keeps_unsupported_chart_honest(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        dashboard_module,
        "_render_time_series_raw_layer_png",
        lambda *_args, **_kwargs: b"png",
    )
    manifest = _static_population_layer_manifest()
    manifest["charts"][0]["chart_type"] = "histogram"
    manifest["charts"][0]["id"] = "histogram-length_mm"

    result = write_production_dashboard(
        manifest,
        tmp_path / "population_unsupported.html",
        dashboard_interactivity_options={"population_layer_mode": "static"},
    )

    html_text = Path(result["html_dashboard_path"]).read_text(encoding="utf-8")
    chart = _embedded_dashboard_charts(html_text)[0]
    assert [trace["name"] for trace in chart["plotly_spec"]["data"]] == ["POPULATION", "A"]
    assert "images" not in chart["plotly_spec"]["layout"]
    assert "Static POPULATION image layers are not available for this chart type yet." in html_text
    assert chart["optimization_options"][0]["skipped_reason"] == "unsupported_chart_type"


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
        assert chart["plotly_spec"]["config"].get("staticPlot") is not True
        xaxis = chart["plotly_spec"]["layout"]["xaxis"]
        assert xaxis["type"] == "linear"
        assert xaxis["tickvals"] == [1, 2, 3]
        assert xaxis["ticktext"] == ["73211", "A", "POPULATION"]


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


def test_csv_summary_dashboard_plotly_specs_include_stat_values_and_colored_group_means(
    monkeypatch,
) -> None:
    def fake_chart_artifact(payload, **_kwargs):
        payload_type = str(payload.get("type") or "")
        if payload_type == "histogram":
            data = [
                {
                    "type": "bar",
                    "name": str(group["group"]),
                    "x": [6.5],
                    "y": [1.0],
                }
                for group in payload["groups"]
            ]
        elif payload_type in {"distribution", "iqr"}:
            trace_type = "violin" if payload_type == "distribution" else "box"
            data = [
                {"type": trace_type, "name": label, "y": series}
                for label, series in zip(payload["labels"], payload["series"], strict=True)
            ]
        else:
            data = []
        return {
            "plotly_spec": {
                "data": data,
                "layout": {},
                "config": {"responsive": True},
            }
        }

    monkeypatch.setattr(
        "modules.hexafe_plotstats_adapter.build_chart_artifact",
        fake_chart_artifact,
    )
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=8, freq="h"),
            "line": ["A"] * 4 + ["B"] * 4,
            "length_mm": [6.469, 6.495, 6.501, 6.687, 7.0, 7.2, 7.4, 7.8],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length_mm", "Length Mm", lsl=6.2, usl=6.8),),
        aggregation_state=ProductionAggregationState(group_fields=("line",)),
        chart_selection=ProductionChartSelection(
            time_series=False,
            histogram=True,
            violin=True,
            box=True,
            groupstats=False,
        ),
    )

    charts = {chart["chart_type"]: chart for chart in manifest["charts"]}
    histogram_spec = charts["histogram"]["plotly_spec"]
    histogram_traces = {
        trace["name"]: trace
        for trace in histogram_spec["data"]
        if trace.get("type") == "bar"
    }
    histogram_mean_traces = {
        trace["name"]: trace
        for trace in histogram_spec["data"]
        if str(trace.get("name") or "").startswith(("(A) Mean=", "(B) Mean="))
    }
    assert "annotations" not in histogram_spec["layout"]
    assert "shapes" not in histogram_spec["layout"]

    assert histogram_mean_traces["(A) Mean=6.5380"]["line"]["color"] == histogram_traces["A"]["marker"]["color"]
    assert histogram_mean_traces["(B) Mean=7.3500"]["line"]["color"] == histogram_traces["B"]["marker"]["color"]
    assert histogram_mean_traces["(A) Mean=6.5380"].get("visible") != "legendonly"
    assert histogram_mean_traces["(B) Mean=7.3500"].get("visible") != "legendonly"

    violin_trace_names = {trace["name"] for trace in charts["violin"]["plotly_spec"]["data"]}
    assert "A (n=4)" in violin_trace_names
    assert "B (n=4)" in violin_trace_names
    assert "(A) Mean=6.5380" in violin_trace_names
    assert "(B) Max=7.800" in violin_trace_names
    assert "Nominal=6.5" in violin_trace_names

    box_trace_names = {trace["name"] for trace in charts["box"]["plotly_spec"]["data"]}
    assert "A (n=4)" in box_trace_names
    assert "B (n=4)" in box_trace_names
    assert "(A) Mean=6.5380" in box_trace_names
    assert "(B) Max=7.800" in box_trace_names
    assert "Nominal=6.5" in box_trace_names


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
    assert "<summary>Group comparison (1 metric)</summary>" in html_text
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

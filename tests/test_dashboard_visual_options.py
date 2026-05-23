from __future__ import annotations

import pandas as pd

from modules.contracts import (
    AppPaths,
    ExportOptions,
    ExportRequest,
    IndustrialAnalyticsRequest,
    validate_export_request,
    validate_industrial_analytics_request,
)
from modules.dashboard_visual_options import (
    build_dashboard_visual_preview_spec,
    dashboard_visual_settings_to_plotly_settings,
    dashboard_visual_swatch_palette,
    normalize_dashboard_visual_settings,
)
from modules.industrial_analytics_dashboard import build_production_dashboard_manifest
from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionMetricSelection,
)


def test_dashboard_visual_gradient_settings_build_distinct_palette() -> None:
    settings = normalize_dashboard_visual_settings(
        {
            "preset": "custom",
            "palette_mode": "highlight_gradient",
            "anchor_color": "#facc15",
            "gradient_spread": "wide",
            "distinguish": "always",
        }
    )

    palette = dashboard_visual_swatch_palette(settings, count=6)
    plotly_settings = dashboard_visual_settings_to_plotly_settings(settings)

    assert len(palette) == 6
    assert len(set(palette)) == 6
    assert plotly_settings["series"]["palette"] == palette
    assert plotly_settings["series"]["always_distinguish"] is True
    assert plotly_settings["series"]["marker_symbols"]


def test_dashboard_visual_preview_spec_uses_sample_groups_and_population() -> None:
    spec = build_dashboard_visual_preview_spec(
        {"preset": "distinct"},
        chart_type="violin",
    )

    assert spec is not None
    trace_names = {str(trace.get("name") or "") for trace in spec["data"]}
    assert any("Group 1" in name for name in trace_names)
    assert any("Group 4" in name for name in trace_names)
    assert any("Population points" in name for name in trace_names)


def test_dashboard_visual_preview_applies_custom_palette_to_plotly_spec() -> None:
    spec = build_dashboard_visual_preview_spec(
        {
            "preset": "custom",
            "palette": ["#123456", "#abcdef", "#fedcba"],
            "distinguish": "always",
        },
        chart_type="histogram",
    )

    assert spec is not None
    assert spec["metadata"]["dashboard_visual_settings_applied"] is True
    assert spec["data"][0]["marker"]["color"] == "#123456"
    assert spec["data"][1]["marker"]["color"] == "#abcdef"


def test_visual_settings_flow_through_export_and_analytics_contracts() -> None:
    settings = {"preset": "custom", "palette": ["#111111", "#222222"], "distinguish": "always"}

    export_request = validate_export_request(
        ExportRequest(
            paths=AppPaths(db_file="reports.db", excel_file="out.xlsx"),
            options=ExportOptions(dashboard_visual_settings=settings),
        )
    )
    analytics_request = validate_industrial_analytics_request(
        IndustrialAnalyticsRequest(
            source_kind="tabular_file",
            input_file="input.csv",
            output_dashboard_file="out.html",
            dashboard_visual_settings=settings,
        )
    )

    assert export_request.options.dashboard_visual_settings["preset"] == "custom"
    assert analytics_request.dashboard_visual_settings["preset"] == "custom"
    assert analytics_request.dashboard_visual_settings["distinguish"] == "always"


def test_csv_summary_dashboard_applies_visual_settings_to_plotly_specs() -> None:
    settings = dashboard_visual_settings_to_plotly_settings(
        {
            "preset": "custom",
            "palette": ["#123456", "#abcdef", "#fedcba"],
            "distinguish": "always",
            "opacity": {"grouped_histogram": 0.42},
        }
    )
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-01-01", periods=8, freq="h"),
            "group": ["A", "A", "B", "B", "A", "B", "A", "B"],
            "length": [6.1, 6.2, 6.6, 6.7, 6.3, 6.8, 6.4, 6.9],
        }
    )

    manifest = build_production_dashboard_manifest(
        frame=frame,
        metric_selection=(ProductionMetricSelection("length", "Length"),),
        aggregation_state=ProductionAggregationState(group_fields=("group",)),
        chart_selection=ProductionChartSelection(
            time_series=False,
            histogram=True,
            violin=False,
            box=False,
            groupstats=False,
        ),
        plotly_visual_settings=settings,
    )

    histogram = next(chart for chart in manifest["charts"] if chart["chart_type"] == "histogram")
    spec = histogram["plotly_spec"]
    assert spec["metadata"]["dashboard_visual_settings_applied"] is True
    series_traces = [
        trace
        for trace in spec["data"]
        if trace.get("meta", {}).get("dashboard_visual_role") == "series"
    ]
    assert series_traces
    assert series_traces[0]["marker"]["color"] == "#123456"

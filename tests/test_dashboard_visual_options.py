from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

import modules.dashboard_visual_options as dashboard_visual_options
from modules.contracts import (
    AppPaths,
    ExportOptions,
    ExportRequest,
    IndustrialAnalyticsRequest,
    validate_export_request,
    validate_industrial_analytics_request,
)
from modules.dashboard_visual_options import (
    build_dashboard_visual_preview_png,
    build_dashboard_visual_preview_spec,
    dashboard_visual_settings_to_plotly_settings,
    dashboard_visual_swatch_palette,
    normalize_dashboard_visual_settings,
)
from modules.dashboard_plotly_visuals import apply_dashboard_visual_settings
from modules.industrial_analytics_dashboard import build_production_dashboard_manifest
from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionMetricSelection,
)


def _png_color_count(image_bytes: bytes, color: str, *, tolerance: int = 16) -> int:
    pil_image = pytest.importorskip("PIL.Image")
    target = tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))
    image = pil_image.open(BytesIO(image_bytes)).convert("RGB")
    pixels = image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()
    return sum(
        1
        for pixel in pixels
        if all(abs(pixel[channel] - target[channel]) <= tolerance for channel in range(3))
    )


def _png_nonwhite_count(image_bytes: bytes) -> int:
    pil_image = pytest.importorskip("PIL.Image")
    image = pil_image.open(BytesIO(image_bytes)).convert("RGB")
    pixels = image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()
    return sum(1 for pixel in pixels if pixel != (255, 255, 255))


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


def test_dashboard_visual_preview_png_changes_with_custom_palette() -> None:
    red_preview = build_dashboard_visual_preview_png(
        {
            "preset": "custom",
            "palette": ["#ff0000", "#00aa00", "#0000ff"],
            "distinguish": "always",
        },
        chart_type="histogram",
    )
    blue_preview = build_dashboard_visual_preview_png(
        {
            "preset": "custom",
            "palette": ["#0000ff", "#00aa00", "#ff0000"],
            "distinguish": "always",
        },
        chart_type="histogram",
    )

    assert red_preview
    assert blue_preview
    assert red_preview != blue_preview
    assert _png_nonwhite_count(red_preview) > 20_000


def test_dashboard_visual_preview_png_reflects_stat_line_width() -> None:
    thin_preview = build_dashboard_visual_preview_png(
        {
            "preset": "custom",
            "palette": ["#ff0000", "#00aa00", "#0000ff"],
            "distinguish": "always",
            "stat_lines": {"width": 0.5, "accent_by_stat": True},
        },
        chart_type="violin",
    )
    thick_preview = build_dashboard_visual_preview_png(
        {
            "preset": "custom",
            "palette": ["#ff0000", "#00aa00", "#0000ff"],
            "distinguish": "always",
            "stat_lines": {"width": 6.0, "accent_by_stat": True},
        },
        chart_type="violin",
    )

    assert thin_preview
    assert thick_preview
    assert _png_color_count(thick_preview, "#FF2424") > _png_color_count(
        thin_preview,
        "#FF2424",
    )


def test_dashboard_visual_preview_png_reflects_reference_dash_styles() -> None:
    base_settings = {
        "preset": "custom",
        "reference_lines": {
            "lsl": {"color": "#112233", "dash": "solid", "width": 3.0},
        },
    }
    solid_histogram = build_dashboard_visual_preview_png(base_settings, chart_type="histogram")
    dotted_histogram = build_dashboard_visual_preview_png(
        {
            **base_settings,
            "reference_lines": {
                "lsl": {"color": "#112233", "dash": "dot", "width": 3.0},
            },
        },
        chart_type="histogram",
    )
    solid_iqr = build_dashboard_visual_preview_png(base_settings, chart_type="iqr")
    dotted_iqr = build_dashboard_visual_preview_png(
        {
            **base_settings,
            "reference_lines": {
                "lsl": {"color": "#112233", "dash": "dot", "width": 3.0},
            },
        },
        chart_type="iqr",
    )

    assert solid_histogram
    assert dotted_histogram
    assert solid_iqr
    assert dotted_iqr
    assert solid_histogram != dotted_histogram
    assert solid_iqr != dotted_iqr


def test_dashboard_visual_preview_png_synthesizes_reference_styles_without_traces() -> None:
    spec = {
        "data": [
            {
                "type": "histogram",
                "name": "Group 1",
                "marker": {"color": "#4d908e"},
                "x": [6.2, 6.4, 6.6, 6.8],
            },
        ],
        "layout": {},
        "config": {},
    }
    solid_preview = dashboard_visual_options._preview_plotly_spec_png(
        spec,
        chart_type="histogram",
        settings={
            "reference_lines": {
                "lsl": {"color": "#112233", "dash": "solid", "width": 3.0},
            },
        },
    )
    dotted_preview = dashboard_visual_options._preview_plotly_spec_png(
        spec,
        chart_type="histogram",
        settings={
            "reference_lines": {
                "lsl": {"color": "#112233", "dash": "dot", "width": 3.0},
            },
        },
    )

    assert solid_preview
    assert dotted_preview
    assert solid_preview != dotted_preview


def test_dashboard_visual_preview_line_renderer_uses_dash_styles() -> None:
    pil_image = pytest.importorskip("PIL.Image")
    pil_draw = pytest.importorskip("PIL.ImageDraw")

    def rendered_line_pixels(dash: str) -> int:
        image = pil_image.new("RGB", (140, 28), "white")
        draw = pil_draw.Draw(image)
        dashboard_visual_options._draw_preview_line(
            draw,
            (12, 14, 128, 14),
            fill="#112233",
            width=3,
            dash=dash,
        )
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return _png_color_count(buffer.getvalue(), "#112233", tolerance=0)

    assert rendered_line_pixels("solid") > rendered_line_pixels("dot")


def test_dashboard_visual_preview_png_renders_each_chart_type() -> None:
    for chart_type in ("histogram", "violin", "iqr", "scatter"):
        image_bytes = build_dashboard_visual_preview_png(
            {
                "preset": "custom",
                "palette": ["#ff0000", "#00aa00", "#0000ff"],
                "distinguish": "always",
            },
            chart_type=chart_type,
        )

        assert image_bytes
        assert _png_nonwhite_count(image_bytes) > 18_000


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


def test_dashboard_visual_settings_style_trend_roles_and_unprefixed_stat_lines() -> None:
    spec = {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": "Measurements",
                "x": [1, 2, 3],
                "y": [10.1, 10.2, 10.3],
                "marker": {"color": "#aaaaaa", "size": 8},
            },
            {
                "type": "scatter",
                "mode": "lines",
                "name": "Trend",
                "x": [1, 3],
                "y": [10.1, 10.3],
                "line": {"color": "#bbbbbb", "width": 1.1, "dash": "dash"},
            },
            {
                "type": "scatter",
                "mode": "lines",
                "name": "LSL=9.900",
                "x": [1, 3],
                "y": [9.9, 9.9],
                "line": {"color": "#cccccc", "dash": "dash"},
            },
            {
                "type": "scatter",
                "mode": "lines",
                "name": "Mean=10.2000",
                "x": [1, 3],
                "y": [10.2, 10.2],
                "line": {"color": "#dddddd", "dash": "dashdot"},
            },
            {
                "type": "scatter",
                "mode": "lines",
                "name": "Median=10.2000",
                "x": [1, 3],
                "y": [10.2, 10.2],
                "line": {"color": "#eeeeee", "dash": "dot"},
                "visible": "legendonly",
            },
        ],
        "layout": {},
        "metadata": {"kind": "trend"},
    }
    settings = {
        "preserve_colors_on_theme": True,
        "series": {
            "palette": ["#111111", "#222222"],
            "opacity": {"scatter": 0.73, "trend": 0.21},
            "marker_size": 12,
            "marker_symbols": ["diamond"],
            "always_distinguish": True,
        },
        "stat_lines": {"width": 3.0, "accent_by_stat": True},
        "reference_lines": {"lsl": {"color": "#ff0000", "dash": "dot", "width": 1.25}},
    }

    apply_dashboard_visual_settings(spec, visual_settings=settings)

    measurements, trend, lsl, mean, median = spec["data"]
    assert measurements["marker"]["color"] == "#111111"
    assert measurements["marker"]["size"] == 12
    assert measurements["marker"]["symbol"] == "diamond"
    assert measurements["opacity"] == 0.73
    assert measurements["meta"]["dashboard_visual_role"] == "series"
    assert measurements["meta"]["dashboard_visual_chart_kind"] == "scatter"

    assert trend["line"]["color"] == "#222222"
    assert trend["opacity"] == 0.21
    assert "marker" not in trend
    assert trend["meta"]["dashboard_visual_role"] == "trend"
    assert trend["meta"]["dashboard_visual_chart_kind"] == "trend"

    assert lsl["line"]["color"] == "#ff0000"
    assert lsl["line"]["dash"] == "dot"
    assert lsl["line"]["width"] == 1.25
    assert lsl.get("meta", {}).get("dashboard_visual_role") is None

    assert mean["line"]["width"] == 3.0
    assert mean["meta"]["dashboard_visual_role"] == "stat"
    assert "opacity" not in mean
    assert median["line"]["width"] == 3.0
    assert median["meta"]["dashboard_visual_role"] == "stat"
    assert median["visible"] == "legendonly"

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
    dashboard_visual_color_source,
    dashboard_visual_effective_series_styles,
    dashboard_visual_palette_presets,
    dashboard_visual_recipe_settings,
    dashboard_visual_resolved_palette_info,
    dashboard_visual_settings_to_plotly_settings,
    dashboard_visual_swatch_palette,
    normalize_dashboard_visual_settings,
    normalize_dashboard_visual_theme_library,
    upsert_dashboard_visual_theme,
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


def test_dashboard_visual_series_overrides_normalize_marker_outline_options() -> None:
    settings = normalize_dashboard_visual_settings(
        {
            "preset": "custom",
            "series_overrides": {
                "Group 1": {
                    "marker_size": 12,
                    "marker_symbol": "diamond",
                    "outline_width": 1.5,
                    "outline_color": "auto",
                }
            },
        }
    )

    override = settings["series_overrides"]["Group 1"]
    assert override["marker_size"] == 12
    assert override["marker_symbol"] == "diamond"
    assert override["outline_width"] == 1.5
    assert override["outline_color_mode"] == "auto"
    assert "outline_color" not in override


def test_dashboard_visual_marker_symbol_normalization_preserves_triangle_up() -> None:
    settings = normalize_dashboard_visual_settings(
        {
            "preset": "custom",
            "series_overrides": {"Group 1": {"marker_symbol": "Triangle Up"}},
            "population_baseline": {
                "aliases": ["population"],
                "marker_symbol": "triangle_up",
            },
            "comparison_focus": {"marker_symbol": "triangle-up"},
        }
    )

    assert settings["series_overrides"]["Group 1"]["marker_symbol"] == "triangle-up"
    assert settings["population_baseline"]["marker_symbol"] == "triangle-up"
    assert settings["comparison_focus"]["marker_symbol"] == "triangle-up"


def test_dashboard_visual_palette_presets_include_researched_data_viz_palettes() -> None:
    presets = dashboard_visual_palette_presets()

    assert {
        "okabe_ito",
        "tableau_10",
        "colorbrewer_set2",
        "ibm_carbon",
        "viridis",
        "cividis",
        "rdbu",
    }.issubset(presets)
    assert presets["okabe_ito"]["kind"] == "categorical"
    assert presets["viridis"]["kind"] == "sequential"
    assert presets["ibm_carbon"]["kind"] == "categorical"
    assert len(presets["tableau_10"]["colors"]) >= 10


def test_dashboard_visual_recipe_settings_update_dependent_color_sources() -> None:
    distinct = dashboard_visual_recipe_settings(
        "distinct",
        base={
            "theme_id": "saved",
            "palette_preset": "viridis",
            "palette_mode": "highlight_gradient",
            "palette": ["#111111", "#222222"],
            "series_overrides": {"Group 1": {"color": "#123456"}},
        },
    )
    print_friendly = dashboard_visual_recipe_settings("print")
    highlight = dashboard_visual_recipe_settings("highlight_gradient")
    toned = dashboard_visual_recipe_settings("toned_report")

    assert distinct["preset"] == "distinct"
    assert distinct["recipe"] == "distinct"
    assert distinct["palette_preset"] == "okabe_ito"
    assert distinct["palette_mode"] == "fixed"
    assert distinct["color_source"] == "preset"
    assert distinct["series_overrides"] == {}
    assert dashboard_visual_swatch_palette(distinct, count=4) == [
        "#0072b2",
        "#d55e00",
        "#009e73",
        "#cc79a7",
    ]

    assert print_friendly["preset"] == "print"
    assert print_friendly["color_source"] == "print"
    assert dashboard_visual_swatch_palette(print_friendly, count=3) == [
        "#111827",
        "#4b5563",
        "#737373",
    ]

    assert highlight["preset"] == "custom"
    assert highlight["recipe"] == "highlight_gradient"
    assert highlight["palette_mode"] == "highlight_gradient"
    assert highlight["color_source"] == "highlight"
    assert len(set(dashboard_visual_swatch_palette(highlight, count=6))) == 6

    assert toned["recipe"] == "toned_report"
    assert toned["preset"] == "custom"
    assert toned["population_baseline"]["aliases"] == ["population", "population points"]
    assert toned["population_baseline"]["marker_size"] < toned["comparison_focus"]["marker_size"]
    assert toned["comparison_focus"]["outline_width"] > 0


def test_dashboard_visual_population_baseline_normalizes_aliases_and_focus() -> None:
    settings = normalize_dashboard_visual_settings(
        {
            "preset": "custom",
            "population_baseline": {
                "aliases": "POPULATION",
                "color": "#999999",
                "opacity": {"scatter": 0.02, "grouped_histogram": 2},
                "marker_size": 1,
                "outline_width": 9,
            },
            "comparison_focus": {
                "opacity": {"scatter": 1.5},
                "marker_size": 30,
                "outline_width": 2,
                "outline_color_mode": "auto",
            },
        }
    )

    assert settings["population_baseline"]["aliases"] == ["population", "population points"]
    assert settings["population_baseline"]["opacity"]["scatter"] == 0.02
    assert settings["population_baseline"]["opacity"]["grouped_histogram"] == 1.0
    assert settings["population_baseline"]["marker_size"] == 2.0
    assert settings["population_baseline"]["outline_width"] == 6.0
    assert settings["comparison_focus"]["opacity"]["scatter"] == 1.0
    assert settings["comparison_focus"]["marker_size"] == 18.0
    assert settings["comparison_focus"]["outline_width"] == 2.0


def test_dashboard_visual_resolved_palette_info_covers_each_color_source() -> None:
    stale_distinct = normalize_dashboard_visual_settings(
        {
            "preset": "distinct",
            "palette_preset": "viridis",
            "palette_mode": "highlight_gradient",
            "anchor_color": "#ff00ff",
        }
    )
    custom = normalize_dashboard_visual_settings(
        {
            "preset": "custom",
            "palette_preset": "custom",
            "palette": ["#111111", "#222222", "#333333"],
        }
    )
    gradient = normalize_dashboard_visual_settings(
        {"preset": "custom", "palette_mode": "auto_gradient", "anchor_color": "#facc15"}
    )

    assert dashboard_visual_color_source(stale_distinct) == "preset"
    assert dashboard_visual_resolved_palette_info(stale_distinct, count=2) == {
        "recipe": "distinct",
        "color_source": "preset",
        "palette": ["#0072b2", "#d55e00"],
        "palette_preset": "okabe_ito",
        "palette_label": "Okabe-Ito",
        "palette_kind": "categorical",
        "palette_mode": "fixed",
        "anchor_color": "#ff00ff",
        "gradient_spread": "normal",
    }
    assert dashboard_visual_color_source(custom) == "custom"
    assert dashboard_visual_resolved_palette_info(custom, count=3)["palette"] == [
        "#111111",
        "#222222",
        "#333333",
    ]
    assert dashboard_visual_color_source(gradient) == "gradient"
    assert len(set(dashboard_visual_resolved_palette_info(gradient, count=5)["palette"])) == 5


def test_dashboard_visual_named_theme_library_upserts_normalized_settings() -> None:
    library, theme = upsert_dashboard_visual_theme(
        None,
        name="Operator review",
        settings={
            "preset": "custom",
            "palette_preset": "okabe_ito",
            "series_overrides": {"Group 1": {"color": "#123456", "opacity": 0.4}},
        },
        set_default=True,
    )
    normalized = normalize_dashboard_visual_theme_library(library)

    assert theme["id"] == "operator-review"
    assert normalized["default_theme_id"] == "operator-review"
    assert normalized["themes"][0]["settings"]["palette_preset"] == "okabe_ito"
    assert normalized["themes"][0]["settings"]["series_overrides"]["Group 1"]["color"] == "#123456"


def test_dashboard_visual_settings_convert_overrides_to_plotly_contract() -> None:
    settings = dashboard_visual_settings_to_plotly_settings(
        {
            "preset": "custom",
            "palette_preset": "okabe_ito",
            "series_overrides": {"Trend": {"color": "#123456", "width": 4.0, "dash": "dot"}},
            "stat_line_overrides": {"a::mean": {"color": "#654321", "opacity": 0.33}},
            "reference_lines": {"lsl": {"color": "#112233", "opacity": 0.44}},
        }
    )

    assert settings["schema"] == "metroliza.dashboard_plotly_visuals.v1"
    assert settings["recipe"] == "custom"
    assert settings["color_source"] == "preset"
    assert settings["resolved_palette"] == settings["series"]["palette"]
    assert settings["series"]["palette"][0] == "#0072b2"
    assert settings["series"]["overrides"]["Trend"]["color"] == "#123456"
    assert settings["stat_lines"]["overrides"]["a::mean"]["opacity"] == 0.33
    assert settings["reference_lines"]["lsl"]["opacity"] == 0.44


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
    series_traces = [
        trace
        for trace in spec["data"]
        if trace.get("meta", {}).get("dashboard_visual_role") == "series"
    ]
    assert series_traces[0]["name"] == "Population points"
    assert series_traces[0]["marker"]["color"] == "#8a949e"
    group_1 = next(trace for trace in series_traces if trace["name"] == "Group 1")
    group_2 = next(trace for trace in series_traces if trace["name"] == "Group 2")
    assert group_1["marker"]["color"] == "#123456"
    assert group_2["marker"]["color"] == "#abcdef"


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
    assert thick_preview != thin_preview


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


def test_dashboard_visual_preview_png_reflects_opacity_and_marker_border() -> None:
    base_spec = {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": "A",
                "x": [1, 2, 3],
                "y": [6.1, 6.2, 6.3],
                "marker": {"color": "#ff0000", "size": 14, "line": {"width": 0}},
                "opacity": 0.25,
            }
        ],
        "layout": {},
        "metadata": {"kind": "scatter"},
    }
    opaque_bordered_spec = {
        "data": [
            {
                **base_spec["data"][0],
                "marker": {"color": "#ff0000", "size": 14, "line": {"width": 4, "color": "#000000"}},
                "opacity": 1.0,
            }
        ],
        "layout": {},
        "metadata": {"kind": "scatter"},
    }

    faint = dashboard_visual_options._preview_plotly_spec_png(base_spec, chart_type="scatter")
    opaque_bordered = dashboard_visual_options._preview_plotly_spec_png(
        opaque_bordered_spec,
        chart_type="scatter",
    )

    assert faint
    assert opaque_bordered
    assert faint != opaque_bordered
    assert _png_color_count(opaque_bordered, "#ff0000", tolerance=12) > _png_color_count(
        faint,
        "#ff0000",
        tolerance=12,
    )
    assert _png_color_count(opaque_bordered, "#000000", tolerance=12) > _png_color_count(
        faint,
        "#000000",
        tolerance=12,
    )


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
            "overrides": {
                "Trend": {"color": "#334455", "width": 4.0, "dash": "dot"},
            },
        },
        "stat_lines": {
            "width": 3.0,
            "accent_by_stat": True,
            "overrides": {"mean": {"color": "#abcdef", "opacity": 0.5}},
        },
        "reference_lines": {
            "lsl": {"color": "#ff0000", "dash": "dot", "width": 1.25, "opacity": 0.4},
        },
    }

    apply_dashboard_visual_settings(spec, visual_settings=settings)

    measurements, trend, lsl, mean, median = spec["data"]
    assert measurements["marker"]["color"] == "#111111"
    assert measurements["marker"]["size"] == 12
    assert measurements["marker"]["symbol"] == "diamond"
    assert measurements["opacity"] == 0.73
    assert measurements["meta"]["dashboard_visual_role"] == "series"
    assert measurements["meta"]["dashboard_visual_chart_kind"] == "scatter"
    assert measurements["meta"]["metroliza_trace_schema"] == "metroliza.plotly_trace.v1"
    assert measurements["meta"]["metroliza_target_id"] == "series:measurements"
    assert measurements["meta"]["metroliza_visual_target_id"] == "series:measurements"
    assert measurements["meta"]["metroliza_style_capabilities"] == [
        "color",
        "opacity",
        "marker_size",
        "marker_symbol",
        "outline_width",
        "outline_color",
        "outline_color_mode",
    ]

    assert trend["line"]["color"] == "#334455"
    assert trend["line"]["width"] == 4.0
    assert trend["line"]["dash"] == "dot"
    assert trend["opacity"] == 0.21
    assert "marker" not in trend
    assert trend["meta"]["dashboard_visual_role"] == "trend"
    assert trend["meta"]["dashboard_visual_chart_kind"] == "trend"
    assert trend["meta"]["metroliza_style_capabilities"] == [
        "color",
        "opacity",
        "width",
        "dash",
    ]

    assert lsl["line"]["color"] == "#ff0000"
    assert lsl["line"]["dash"] == "dot"
    assert lsl["line"]["width"] == 1.25
    assert lsl["opacity"] == 0.4
    assert lsl["meta"]["dashboard_visual_role"] == "reference"
    assert lsl["meta"]["metroliza_reference_id"] == "lsl"
    assert lsl["meta"]["metroliza_style_capabilities"] == ["color", "opacity", "width", "dash"]

    assert mean["line"]["color"] == "#abcdef"
    assert mean["line"]["width"] == 3.0
    assert mean["meta"]["dashboard_visual_role"] == "stat"
    assert mean["meta"]["metroliza_stat_id"] == "mean"
    assert mean["meta"]["metroliza_style_capabilities"] == ["color", "opacity", "width", "dash"]
    assert mean["opacity"] == 0.5
    assert median["line"]["width"] == 3.0
    assert median["meta"]["dashboard_visual_role"] == "stat"
    assert median["visible"] == "legendonly"


def test_dashboard_visual_histogram_trace_metadata_exposes_pattern_capability() -> None:
    spec = {
        "data": [
            {
                "type": "histogram",
                "name": "A (n=4)",
                "x": [1.0, 1.1, 1.2, 1.3],
                "marker": {"color": "#aaaaaa"},
            }
        ],
        "layout": {},
        "metadata": {"kind": "histogram"},
    }

    apply_dashboard_visual_settings(
        spec,
        payload={"groups": [{"group": "A"}], "type": "histogram"},
        visual_settings=dashboard_visual_settings_to_plotly_settings(
            {"preset": "custom", "palette": ["#123456"], "distinguish": "always"}
        ),
    )

    meta = spec["data"][0]["meta"]
    assert meta["metroliza_target_id"] == "series:a"
    assert meta["metroliza_legend_label"] == "A"
    assert meta["metroliza_style_capabilities"] == [
        "color",
        "opacity",
        "pattern_shape",
    ]


def test_dashboard_visual_population_baseline_styles_real_and_preview_aliases() -> None:
    spec = {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": "Group A",
                "x": [1, 2],
                "y": [6.6, 6.7],
                "marker": {"color": "#aaaaaa"},
            },
            {
                "type": "scatter",
                "mode": "markers",
                "name": "POPULATION (n=3000)",
                "x": [1, 2, 3],
                "y": [6.1, 6.2, 6.3],
                "marker": {"color": "#bbbbbb"},
            },
        ],
        "layout": {},
        "metadata": {"kind": "scatter"},
    }

    apply_dashboard_visual_settings(
        spec,
        payload={"labels": ["Group A", "POPULATION"], "type": "distribution", "render_mode": "scatter"},
        visual_settings=dashboard_visual_settings_to_plotly_settings({"recipe": "toned_report"}),
    )

    population, group = spec["data"]
    assert population["name"] == "POPULATION (n=3000)"
    assert population["marker"]["color"] == "#8a949e"
    assert population["marker"]["size"] == 4.5
    assert population["opacity"] == 0.24
    assert population["marker"]["line"]["width"] == 0.0
    assert group["marker"]["size"] == 8.0
    assert group["marker"]["line"]["width"] == 1.15
    assert group["opacity"] == 0.92


def test_dashboard_visual_population_alias_matches_preview_label() -> None:
    spec = {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": "Population points",
                "x": [1, 2],
                "y": [6.1, 6.2],
                "marker": {"color": "#bbbbbb"},
            },
        ],
        "layout": {},
        "metadata": {"kind": "scatter"},
    }

    apply_dashboard_visual_settings(
        spec,
        payload={"labels": ["Population points"], "type": "distribution", "render_mode": "scatter"},
        visual_settings=dashboard_visual_settings_to_plotly_settings({"recipe": "professional_contrast"}),
    )

    assert spec["data"][0]["marker"]["color"] == "#7b8794"
    assert spec["data"][0]["marker"]["size"] == 4.5


def test_dashboard_visual_population_first_does_not_shift_comparison_palette() -> None:
    spec = {
        "data": [
            {"type": "bar", "name": "POPULATION", "x": ["A"], "y": [120], "marker": {}},
            {"type": "bar", "name": "GROUP1", "x": ["A"], "y": [4], "marker": {}},
            {"type": "bar", "name": "GROUP2", "x": ["A"], "y": [6], "marker": {}},
        ],
        "layout": {},
        "metadata": {"kind": "histogram"},
    }
    settings = dashboard_visual_settings_to_plotly_settings(
        {
            "preset": "custom",
            "palette": ["#111111", "#222222", "#333333"],
            "population_baseline": {
                "aliases": ["POPULATION"],
                "color": "#999999",
                "opacity": {"grouped_histogram": 0.3},
                "draw_first": True,
            },
        }
    )

    apply_dashboard_visual_settings(
        spec,
        payload={"groups": [{"group": "POPULATION"}, {"group": "GROUP1"}, {"group": "GROUP2"}], "type": "histogram"},
        visual_settings=settings,
    )

    population, group_1, group_2 = spec["data"]
    assert population["name"] == "POPULATION"
    assert population["marker"]["color"] == "#999999"
    assert group_1["name"] == "GROUP1"
    assert group_1["marker"]["color"] == "#111111"
    assert group_2["name"] == "GROUP2"
    assert group_2["marker"]["color"] == "#222222"


def test_dashboard_visual_triangle_up_marker_is_applied_to_scatter_preview() -> None:
    spec = {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": "Group 1",
                "x": [1, 2],
                "y": [3, 4],
                "marker": {},
            }
        ],
        "layout": {},
        "metadata": {"kind": "scatter"},
    }

    apply_dashboard_visual_settings(
        spec,
        payload={"labels": ["Group 1"], "type": "distribution", "render_mode": "scatter"},
        visual_settings=dashboard_visual_settings_to_plotly_settings(
            {"preset": "custom", "series_overrides": {"Group 1": {"marker_symbol": "Triangle Up"}}}
        ),
    )

    assert spec["data"][0]["marker"]["symbol"] == "triangle-up"


def test_dashboard_visual_population_stays_first_with_custom_series_override() -> None:
    spec = build_dashboard_visual_preview_spec(
        {
            "preset": "custom",
            "palette": ["#123456", "#abcdef", "#fedcba", "#334455", "#556677"],
            "series_overrides": {"Group 1": {"color": "#ff0000", "opacity": 0.44}},
        },
        chart_type="histogram",
    )

    assert spec is not None
    series_traces = [
        trace
        for trace in spec["data"]
        if trace.get("meta", {}).get("dashboard_visual_role") == "series"
    ]
    assert series_traces[0]["name"] == "Population points"
    assert series_traces[0]["marker"]["color"] == "#8a949e"
    assert series_traces[0]["opacity"] == 0.32
    group_1 = next(trace for trace in series_traces if trace["name"] == "Group 1")
    assert group_1["marker"]["color"] == "#ff0000"
    assert group_1["opacity"] == 0.44


def test_dashboard_visual_effective_series_styles_order_population_before_palette_groups() -> None:
    styles = dashboard_visual_effective_series_styles(
        {
            "preset": "custom",
            "palette": ["#111111", "#222222", "#333333"],
            "series_overrides": {"Group 2": {"color": "#abcdef"}},
        },
        labels=("Group 1", "Group 2", "Population points"),
        chart_type="grouped_histogram",
    )

    assert [(style["label"], style["color"], style["palette_index"]) for style in styles] == [
        ("Population points", "#8a949e", None),
        ("Group 1", "#111111", 0),
        ("Group 2", "#abcdef", 1),
    ]


def test_dashboard_visual_when_similar_only_distinguishes_similar_effective_colors() -> None:
    def histogram_patterns(palette: list[str]) -> list[str | None]:
        spec = {
            "data": [
                {"type": "histogram", "name": "A", "x": [1.0, 1.1], "marker": {}},
                {"type": "histogram", "name": "B", "x": [1.2, 1.3], "marker": {}},
                {"type": "histogram", "name": "C", "x": [1.4, 1.5], "marker": {}},
            ],
            "layout": {},
            "metadata": {"kind": "histogram"},
        }
        apply_dashboard_visual_settings(
            spec,
            payload={"groups": [{"group": "A"}, {"group": "B"}, {"group": "C"}], "type": "histogram"},
            visual_settings=dashboard_visual_settings_to_plotly_settings(
                {"preset": "custom", "palette": palette, "distinguish": "when_similar"}
            ),
        )
        return [
            trace.get("marker", {}).get("pattern", {}).get("shape")
            for trace in spec["data"]
        ]

    assert histogram_patterns(["#0072b2", "#d55e00", "#009e73"]) == [None, None, None]
    assert histogram_patterns(["#111111", "#121212", "#333333"]) == ["/", "\\", "x"]


def test_dashboard_visual_histogram_empty_pattern_override_clears_auto_pattern() -> None:
    spec = {
        "data": [
            {
                "type": "histogram",
                "name": "A",
                "x": [1.0, 1.1, 1.2],
                "marker": {"color": "#aaaaaa"},
            }
        ],
        "layout": {},
        "metadata": {"kind": "histogram"},
    }

    apply_dashboard_visual_settings(
        spec,
        payload={"groups": [{"group": "A"}], "type": "histogram"},
        visual_settings={
            "series": {
                "palette": ["#123456"],
                "patterns": ["/"],
                "always_distinguish": True,
                "overrides": {"A": {"pattern_shape": ""}},
            }
        },
    )

    assert spec["data"][0]["marker"]["pattern"]["shape"] == ""


def test_dashboard_visual_scatter_series_overrides_apply_marker_shape_and_auto_outline() -> None:
    spec = {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": "Light",
                "x": [1, 2],
                "y": [3, 4],
                "marker": {"color": "#aaaaaa"},
            },
            {
                "type": "scatter",
                "mode": "markers",
                "name": "Dark",
                "x": [1, 2],
                "y": [4, 5],
                "marker": {"color": "#bbbbbb"},
            },
        ],
        "layout": {},
        "metadata": {"kind": "scatter"},
    }

    apply_dashboard_visual_settings(
        spec,
        payload={"labels": ["Light", "Dark"], "type": "scatter"},
        visual_settings={
            "series": {
                "palette": ["#facc15", "#123456"],
                "overrides": {
                    "Light": {
                        "marker_size": 13,
                        "marker_symbol": "diamond",
                        "outline_width": 2,
                        "outline_color_mode": "auto",
                    },
                    "Dark": {
                        "outline_width": 2,
                        "outline_color_mode": "auto",
                    },
                },
            }
        },
    )

    light, dark = spec["data"]
    assert light["marker"]["size"] == 13
    assert light["marker"]["symbol"] == "diamond"
    assert light["marker"]["line"] == {"width": 2, "color": "#111827"}
    assert dark["marker"]["line"] == {"width": 2, "color": "#ffffff"}

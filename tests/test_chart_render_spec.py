from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pytest

from modules import native_chart_compositor
from modules.chart_render_spec import (
    build_resolved_distribution_spec,
    build_resolved_histogram_spec,
    build_resolved_iqr_spec,
    build_resolved_trend_spec,
    histogram_spec_to_mapping,
)
from modules.chart_renderer import build_distribution_native_payload, build_histogram_native_payload
from modules.native_chart_compositor import render_distribution_png, render_histogram_png, render_iqr_png, render_trend_png


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "chart_parity"


def _non_white_pixels(image: np.ndarray, *, y0: float, y1: float, x0: float, x1: float) -> int:
    height, width = image.shape[:2]
    region = image[int(height * y0): int(height * y1), int(width * x0): int(width * x1), :3]
    return int(np.count_nonzero(np.any(region < 0.97, axis=2)))


def _near_rgb_pixels(
    image: np.ndarray,
    *,
    y0: float,
    y1: float,
    x0: float,
    x1: float,
    rgb: tuple[int, int, int],
    atol: float = 0.12,
) -> int:
    height, width = image.shape[:2]
    region = image[int(height * y0): int(height * y1), int(width * x0): int(width * x1), :3]
    target = np.asarray(rgb, dtype=np.float32) / 255.0
    deltas = np.max(np.abs(region - target), axis=2)
    return int(np.count_nonzero(deltas <= float(atol)))


def _decode_png_bytes(png_bytes: bytes) -> np.ndarray:
    return plt.imread(BytesIO(png_bytes), format="png")[..., :3]


def _fixture_payload(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name / "payload.json").read_text(encoding="utf-8"))


def _fixture_reference_image(name: str) -> np.ndarray:
    return plt.imread(str(FIXTURE_ROOT / name / "matplotlib_reference.png"))[..., :3]


def _mean_absolute_image_difference(left: np.ndarray, right: np.ndarray) -> float:
    assert left.shape == right.shape
    return float(np.mean(np.abs(left.astype(np.float32) - right.astype(np.float32))))


def test_build_histogram_render_spec_exposes_layout_title_and_axes_contract():
    payload = build_histogram_native_payload(
        values=[1.0, 1.1, 1.2, 1.4, 1.8, 2.0],
        lsl=0.8,
        usl=2.2,
        title="Histogram Title",
        bin_count=6,
    )
    payload["canvas"] = {"width_px": 1320, "height_px": 600, "dpi": 150}
    payload["summary_table_rows"] = [{"label": "Mean", "value": "1.42"}, {"label": "Samples", "value": "6"}]

    spec = build_resolved_histogram_spec(payload)

    assert spec.plot_rect.width > 0.42
    assert spec.table_rect is not None
    assert spec.table_rect.x > spec.plot_rect.x
    assert spec.title.text == "Histogram Title"
    assert spec.title.x == 0.06
    assert spec.title.y == 0.985
    assert len(spec.x_ticks) == 6
    assert len(spec.y_ticks) == 5
    assert spec.x_label == "Measurement"
    assert spec.y_max > 0.0


def test_render_histogram_png_honors_resolved_render_spec_title_and_panel_geometry():
    payload = build_histogram_native_payload(
        values=[1.0, 1.05, 1.1, 1.2, 1.25, 1.35, 1.4],
        lsl=0.9,
        usl=1.5,
        title="Original Title",
        bin_count=5,
    )
    payload["summary_table_rows"] = [{"label": "Mean", "value": "1.19"}]
    payload["resolved_render_spec"] = {
        "title": {
            "text": "Moved Title",
            "x": 0.36,
            "y": 0.94,
            "font_size": 12.0,
            "bold": True,
            "color": "#0072B2",
        },
        "plot_rect": {"x": 0.10, "y": 0.14, "width": 0.45, "height": 0.60},
        "table_rect": {"x": 0.62, "y": 0.18, "width": 0.24, "height": 0.44},
        "x_label": "Measurement",
        "y_label": "Count",
        "grid_axis": "y",
        "y_min": 0.0,
        "y_max": 4.0,
    }

    image = plt.imread(BytesIO(render_histogram_png(payload)), format="png")
    height, width = image.shape[:2]

    left_title_region = image[: int(height * 0.12), : int(width * 0.16), :3]
    moved_title_region = image[: int(height * 0.18), int(width * 0.28): int(width * 0.52), :3]
    table_region = image[int(height * 0.18): int(height * 0.66), int(width * 0.62): int(width * 0.88), :3]

    moved_pixels = np.count_nonzero(np.any(moved_title_region < 0.97, axis=2))
    left_pixels = np.count_nonzero(np.any(left_title_region < 0.97, axis=2))
    table_pixels = np.count_nonzero(np.any(table_region < 0.97, axis=2))

    assert moved_pixels > 250
    assert moved_pixels > left_pixels
    assert table_pixels > 1200


def test_render_histogram_png_replays_resolved_bars_without_histogram_recompute(monkeypatch):
    payload = build_histogram_native_payload(
        values=[0.04, 0.05, 0.06, 0.07],
        lsl=None,
        usl=None,
        title="Resolved Bars Replay",
        bin_count=7,
    )
    payload["canvas"] = {"width_px": 900, "height_px": 450, "dpi": 150}
    payload["resolved_render_spec"] = {
        "title": {
            "text": "Resolved Bars Replay",
            "anchor": {"x": 0.10, "y": 0.96},
            "font": {"size": 10.0, "weight": "bold"},
            "color": "#0072B2",
        },
        "plot_area": {"x": 0.14, "y": 0.18, "width": 0.62, "height": 0.56},
        "axes": {
            "x_limits": {"min": 0.0, "max": 10.0},
            "y_limits": {"min": 0.0, "max": 10.0},
            "x_ticks": [{"value": 0.0, "label": "0"}, {"value": 10.0, "label": "10"}],
            "y_ticks": [{"value": 0.0, "label": "0"}, {"value": 5.0, "label": "5"}, {"value": 10.0, "label": "10"}],
            "x_label": "Measurement",
            "y_label": "Count",
            "grid_axis": "y",
        },
        "bars": [
            {
                "left_edge": 8.0,
                "right_edge": 9.0,
                "count": 9.0,
                "fill_color": "#ff007f",
                "fill_alpha": 1.0,
                "edge_color": "#111111",
                "edge_alpha": 1.0,
                "edge_width": 1.0,
            }
        ],
        "lines": {"mean": None, "specification": []},
        "overlays": [],
        "annotations": [],
    }

    def _forbidden_histogram(*_args, **_kwargs):
        raise AssertionError("np.histogram should not be called when resolved bars are provided")

    monkeypatch.setattr(native_chart_compositor.np, "histogram", _forbidden_histogram)
    _ = render_histogram_png(payload)


def test_histogram_spec_to_mapping_serializes_native_layout_contract():
    payload = build_histogram_native_payload(
        values=[1.0, 1.05, 1.1, 1.2, 1.3],
        lsl=0.9,
        usl=1.4,
        title="Spec Mapping",
        bin_count=4,
    )
    payload["canvas"] = {"width_px": 900, "height_px": 450, "dpi": 150}
    payload["summary_table_rows"] = [{"label": "Samples", "value": "5"}]

    mapping = histogram_spec_to_mapping(build_resolved_histogram_spec(payload))

    assert mapping["title"]["text"] == "Spec Mapping"
    assert mapping["plot_rect"]["width"] > 0.0
    assert mapping["table_rect"]["width"] > 0.0
    assert mapping["x_ticks"][0]["label"] != ""


def test_build_distribution_resolved_spec_violin_exposes_layout_legend_and_groups():
    payload = build_distribution_native_payload(
        values=[[1.0, 1.1, 1.2], [1.4, 1.5, 1.6]],
        labels=["Alpha", "Beta"],
        title="Distribution Title",
        lsl=0.9,
        usl=1.8,
    )
    payload.update(
        {
            "render_mode": "violin",
            "positions": [0.0, 1.0],
            "layout": {
                "rotation": 30,
                "display_positions": [0.0, 1.0],
                "display_labels": ["Alpha", "Beta"],
                "bottom_margin": 0.24,
            },
            "canvas": {"width_px": 960, "height_px": 560, "dpi": 150},
            "x_label": "Group",
            "y_label": "Measurement",
            "legend": {"items": [{"label": "Mean marker", "kind": "marker", "marker": "circle", "color": "#0072B2"}]},
            "annotation_style": {"show_minmax": True, "show_sigma": True},
            "violin_annotations": [{"position": 0.0, "mean": 1.1, "minimum": 1.0, "maximum": 1.2, "sigma_start": 1.0, "sigma_high": 1.2, "show_sigma_segment": True}],
        }
    )

    spec = build_resolved_distribution_spec(payload)

    assert spec["render_mode"] == "violin"
    assert spec["plot_area"]["x"] == pytest.approx(0.14)
    assert spec["plot_area"]["width"] == pytest.approx(0.82)
    assert spec["title"]["text"] == "Distribution Title"
    assert spec["title"]["anchor"]["x"] == pytest.approx(0.55)
    assert spec["title"]["ha"] == "center"
    assert spec["title"]["va"] == "baseline"
    assert spec["axes"]["rotation"] == 30
    assert len(spec["axes"]["x_ticks"]) == 2
    assert spec["legend"]["items"][0]["label"] == "Mean marker"
    assert spec["legend"]["rect"]["x"] > 0.75
    assert spec["legend"]["rect"]["y"] > 0.80
    assert len(spec["reference_bands"]) == 0
    assert len(spec["reference_lines"]) == 2
    assert spec["reference_lines"][0]["color"] == "#D55E00"
    assert len(spec["violin_groups"]) == 2
    assert len(spec["violin_bodies"]) == 2
    assert len(spec["annotations"]["markers"]) == 3


def test_build_resolved_iqr_spec_contains_precomputed_box_statistics():
    payload = {
        "type": "iqr",
        "labels": ["A", "B"],
        "series": [[1.0, 1.1, 1.2, 1.3], [2.0, 2.1, 2.2, 5.0]],
        "title": "IQR Title",
        "lsl": 0.8,
        "usl": 5.2,
        "nominal": 2.0,
        "one_sided": False,
        "layout": {"rotation": 0, "display_positions": [1.0, 2.0], "display_labels": ["A", "B"], "bottom_margin": 0.18},
        "canvas": {"width_px": 900, "height_px": 500, "dpi": 150},
        "x_label": "Group",
        "y_label": "Measurement",
        "legend": {"items": [{"label": "Median", "kind": "line", "color": "#E69F00"}]},
    }

    spec = build_resolved_iqr_spec(payload)

    assert spec["plot_area"]["x"] == pytest.approx(0.14)
    assert spec["plot_area"]["width"] == pytest.approx(0.82)
    assert spec["title"]["text"] == "IQR Title"
    assert spec["title"]["anchor"]["x"] == pytest.approx(0.55)
    assert spec["title"]["ha"] == "center"
    assert len(spec["boxes"]) == 2
    assert spec["boxes"][1]["outliers"] == [5.0]
    assert spec["boxes"][0]["median"] == pytest.approx(1.15)
    assert spec["legend"]["items"][0]["label"] == "Median"
    assert spec["legend"]["rect"]["x"] > 0.75
    assert spec["legend"]["rect"]["y"] > 0.80
    assert len(spec["reference_bands"]) == 0
    assert len(spec["reference_lines"]) == 3
    assert spec["reference_lines"][0]["color"] == "#D55E00"
    assert spec["boxes"][0]["box_left"] == pytest.approx(0.86)
    assert spec["boxes"][0]["box_right"] == pytest.approx(1.14)
    assert spec["boxes"][0]["fill_color"] == "#8cb8d9"


def test_build_resolved_trend_spec_contains_points_ticks_and_limit_lines():
    payload = {
        "type": "trend",
        "x_values": [0.0, 1.0, 2.0, 3.0],
        "y_values": [1.0, 1.2, 1.1, 1.3],
        "labels": ["S1", "S2", "S3", "S4"],
        "title": "Trend Title",
        "x_label": "Sample #",
        "y_label": "Measurement",
        "horizontal_limits": [0.9, 1.4],
        "x_limits": {"min": -0.25, "max": 3.25},
        "layout": {"rotation": 45, "display_positions": [0.0, 2.0, 3.0], "display_labels": ["S1", "S3", "S4"], "bottom_margin": 0.26},
        "canvas": {"width_px": 900, "height_px": 500, "dpi": 150},
    }

    spec = build_resolved_trend_spec(payload)

    assert spec["plot_area"]["x"] == pytest.approx(0.14)
    assert spec["plot_area"]["width"] == pytest.approx(0.82)
    assert spec["title"]["text"] == "Trend Title"
    assert spec["title"]["anchor"]["x"] == pytest.approx(0.55)
    assert spec["title"]["ha"] == "center"
    assert spec["x_min"] == pytest.approx(-0.25)
    assert spec["x_max"] == pytest.approx(3.25)
    assert spec["axes"]["rotation"] == 45
    assert [tick["label"] for tick in spec["axes"]["x_ticks"]] == ["S1", "S3", "S4"]
    assert len(spec["reference_lines"]) == 2
    assert len(spec["points"]) == 4


def test_render_distribution_png_honors_resolved_render_spec_for_title_and_scatter_points():
    payload = {
        "type": "distribution",
        "series": [[], []],
        "labels": ["A", "B"],
        "title": "Original Distribution",
        "render_mode": "scatter",
        "x_values": [0.0, 1.0],
        "y_values": [1.0, 1.2],
        "x_domain": {"min": 0.0, "max": 1.0},
        "canvas": {"width_px": 900, "height_px": 450, "dpi": 150},
    }
    payload["resolved_render_spec"] = {
        "title": {
            "text": "Shifted Distribution",
            "anchor": {"x": 0.36, "y": 0.96},
            "font": {"size": 10.0, "weight": "bold"},
            "color": "#0072B2",
        },
        "plot_area": {"x": 0.14, "y": 0.18, "width": 0.62, "height": 0.56},
        "axes": {
            "x_limits": {"min": 0.0, "max": 1.0},
            "y_limits": {"min": 0.0, "max": 10.0},
            "x_ticks": [{"value": 0.0, "label": "A"}, {"value": 1.0, "label": "B"}],
            "y_ticks": [{"value": 0.0, "label": "0"}, {"value": 5.0, "label": "5"}, {"value": 10.0, "label": "10"}],
            "x_label": "Group",
            "y_label": "Measurement",
            "grid_axis": "y",
            "rotation": 0,
        },
        "render_mode": "scatter",
        "scatter_points": [
            {"x": 0.2, "y": 8.4, "marker": "circle", "size": 14, "color": "#0072B2"},
            {"x": 0.8, "y": 9.0, "marker": "circle", "size": 14, "color": "#0072B2"},
        ],
    }

    image = plt.imread(BytesIO(render_distribution_png(payload)), format="png")

    moved_title_pixels = _non_white_pixels(image, y0=0.00, y1=0.18, x0=0.28, x1=0.56)
    left_title_pixels = _non_white_pixels(image, y0=0.00, y1=0.18, x0=0.00, x1=0.18)
    upper_plot_pixels = _non_white_pixels(image, y0=0.20, y1=0.42, x0=0.18, x1=0.72)
    lower_plot_pixels = _non_white_pixels(image, y0=0.60, y1=0.82, x0=0.18, x1=0.72)

    assert moved_title_pixels > 180
    assert moved_title_pixels > left_title_pixels
    assert upper_plot_pixels > lower_plot_pixels


def test_render_distribution_png_honors_resolved_title_rect_alignment():
    payload = {
        "type": "distribution",
        "series": [[], []],
        "labels": ["A", "B"],
        "title": "Original Distribution",
        "render_mode": "scatter",
        "x_values": [0.0, 1.0],
        "y_values": [1.0, 1.2],
        "x_domain": {"min": 0.0, "max": 1.0},
        "canvas": {"width_px": 900, "height_px": 450, "dpi": 150},
    }
    payload["resolved_render_spec"] = {
        "title": {
            "text": "Centered By Rect",
            "anchor": {"x": 0.10, "y": 0.98},
            "font": {"size": 12.0, "weight": "normal"},
            "color": "#000000",
            "ha": "center",
            "va": "baseline",
            "rect": {"x": 0.38, "y": 0.88, "width": 0.24, "height": 0.05},
        },
        "plot_area": {"x": 0.14, "y": 0.18, "width": 0.62, "height": 0.56},
        "axes": {
            "x_limits": {"min": 0.0, "max": 1.0},
            "y_limits": {"min": 0.0, "max": 10.0},
            "x_ticks": [{"value": 0.0, "label": "A"}, {"value": 1.0, "label": "B"}],
            "y_ticks": [{"value": 0.0, "label": "0"}, {"value": 5.0, "label": "5"}, {"value": 10.0, "label": "10"}],
            "x_label": "Group",
            "y_label": "Measurement",
            "grid_axis": "y",
            "rotation": 0,
        },
        "render_mode": "scatter",
        "reference_lines": [],
        "reference_bands": [],
        "scatter_points": [],
    }

    image = plt.imread(BytesIO(render_distribution_png(payload)), format="png")

    centered_title_pixels = _non_white_pixels(image, y0=0.04, y1=0.16, x0=0.34, x1=0.66)
    left_title_pixels = _non_white_pixels(image, y0=0.04, y1=0.16, x0=0.00, x1=0.18)

    assert centered_title_pixels > 180
    assert centered_title_pixels > left_title_pixels


def test_render_iqr_png_honors_resolved_render_spec_box_statistics():
    payload = {
        "type": "iqr",
        "labels": ["Only"],
        "series": [[1.0, 1.1, 1.2, 1.3]],
        "title": "Original IQR",
        "canvas": {"width_px": 900, "height_px": 450, "dpi": 150},
    }
    payload["resolved_render_spec"] = {
        "title": {
            "text": "Shifted IQR",
            "anchor": {"x": 0.34, "y": 0.96},
            "font": {"size": 10.0, "weight": "bold"},
            "color": "#0072B2",
        },
        "plot_area": {"x": 0.14, "y": 0.18, "width": 0.62, "height": 0.56},
        "axes": {
            "x_limits": {"min": 0.5, "max": 1.5},
            "y_limits": {"min": 0.0, "max": 12.0},
            "x_ticks": [{"value": 1.0, "label": "Only"}],
            "y_ticks": [{"value": 0.0, "label": "0"}, {"value": 6.0, "label": "6"}, {"value": 12.0, "label": "12"}],
            "x_label": "Group",
            "y_label": "Measurement",
            "grid_axis": "y",
            "rotation": 0,
        },
        "boxes": [
            {
                "position": 1.0,
                "q1": 8.0,
                "median": 9.0,
                "q3": 10.0,
                "whisker_low": 7.0,
                "whisker_high": 11.0,
                "outliers": [11.5],
            }
        ],
    }

    image = plt.imread(BytesIO(render_iqr_png(payload)), format="png")

    moved_title_pixels = _non_white_pixels(image, y0=0.00, y1=0.18, x0=0.26, x1=0.54)
    left_title_pixels = _non_white_pixels(image, y0=0.00, y1=0.18, x0=0.00, x1=0.18)
    upper_plot_pixels = _non_white_pixels(image, y0=0.18, y1=0.48, x0=0.28, x1=0.62)
    lower_plot_pixels = _non_white_pixels(image, y0=0.60, y1=0.82, x0=0.28, x1=0.62)

    assert moved_title_pixels > 140
    assert moved_title_pixels > left_title_pixels
    assert upper_plot_pixels > lower_plot_pixels


def test_render_iqr_png_replays_resolved_box_rect_and_style():
    payload = {
        "type": "iqr",
        "labels": ["Only"],
        "series": [[1.0, 1.1, 1.2, 1.3]],
        "title": "IQR Strict Replay",
        "canvas": {"width_px": 900, "height_px": 450, "dpi": 150},
    }
    payload["resolved_render_spec"] = {
        "title": {
            "text": "IQR Strict Replay",
            "anchor": {"x": 0.24, "y": 0.96},
            "font": {"size": 10.0, "weight": "bold"},
            "color": "#0072B2",
        },
        "plot_area": {"x": 0.14, "y": 0.18, "width": 0.62, "height": 0.56},
        "axes": {
            "x_limits": {"min": 0.0, "max": 10.0},
            "y_limits": {"min": 0.0, "max": 12.0},
            "x_ticks": [{"value": 0.0, "label": "0"}, {"value": 10.0, "label": "10"}],
            "y_ticks": [{"value": 0.0, "label": "0"}, {"value": 6.0, "label": "6"}, {"value": 12.0, "label": "12"}],
            "x_label": "Group",
            "y_label": "Measurement",
            "grid_axis": "y",
            "rotation": 0,
        },
        "reference_lines": [],
        "reference_bands": [],
        "boxes": [
            {
                "position": 1.0,
                "box_left": 0.46,
                "box_right": 0.54,
                "q1": 8.0,
                "median": 9.0,
                "q3": 10.0,
                "whisker_low": 7.0,
                "whisker_high": 11.0,
                "outliers": [],
                "fill_color": "#ff007f",
                "fill_alpha": 1.0,
                "edge_color": "#00ff00",
                "edge_width": 3.0,
                "median_color": "#ffff00",
            }
        ],
    }

    image = plt.imread(BytesIO(render_iqr_png(payload)), format="png")

    left_box_region = _non_white_pixels(image, y0=0.24, y1=0.74, x0=0.18, x1=0.30)
    center_box_region = _non_white_pixels(image, y0=0.24, y1=0.74, x0=0.44, x1=0.58)
    magenta_center = _near_rgb_pixels(image, y0=0.24, y1=0.74, x0=0.44, x1=0.58, rgb=(255, 0, 127))

    assert center_box_region > left_box_region
    assert magenta_center > 200


def test_render_trend_png_honors_resolved_render_spec_points_and_limit_lines():
    payload = {
        "type": "trend",
        "x_values": [0.0, 1.0],
        "y_values": [1.0, 1.2],
        "labels": ["A", "B"],
        "title": "Original Trend",
        "canvas": {"width_px": 900, "height_px": 450, "dpi": 150},
    }
    payload["resolved_render_spec"] = {
        "title": {
            "text": "Shifted Trend",
            "anchor": {"x": 0.34, "y": 0.96},
            "font": {"size": 10.0, "weight": "bold"},
            "color": "#0072B2",
        },
        "plot_area": {"x": 0.14, "y": 0.18, "width": 0.62, "height": 0.56},
        "axes": {
            "x_limits": {"min": 0.0, "max": 1.0},
            "y_limits": {"min": 0.0, "max": 10.0},
            "x_ticks": [{"value": 0.0, "label": "A"}, {"value": 1.0, "label": "B"}],
            "y_ticks": [{"value": 0.0, "label": "0"}, {"value": 5.0, "label": "5"}, {"value": 10.0, "label": "10"}],
            "x_label": "Sample #",
            "y_label": "Measurement",
            "grid_axis": "y",
            "rotation": 0,
        },
        "reference_lines": [
            {"axis": "y", "value": 7.0, "color": "#D55E00", "alpha": 0.9, "width": 2.0},
            {"axis": "y", "value": 8.5, "color": "#D55E00", "alpha": 0.9, "width": 2.0},
        ],
        "points": [
            {"x": 0.2, "y": 8.0, "marker": "circle", "size": 14, "color": "#0072B2"},
            {"x": 0.8, "y": 9.0, "marker": "circle", "size": 14, "color": "#0072B2"},
        ],
    }

    image = plt.imread(BytesIO(render_trend_png(payload)), format="png")

    moved_title_pixels = _non_white_pixels(image, y0=0.00, y1=0.18, x0=0.26, x1=0.54)
    left_title_pixels = _non_white_pixels(image, y0=0.00, y1=0.18, x0=0.00, x1=0.18)
    upper_plot_pixels = _non_white_pixels(image, y0=0.18, y1=0.48, x0=0.18, x1=0.72)
    lower_plot_pixels = _non_white_pixels(image, y0=0.60, y1=0.82, x0=0.18, x1=0.72)

    assert moved_title_pixels > 140
    assert moved_title_pixels > left_title_pixels
    assert upper_plot_pixels > lower_plot_pixels


@pytest.mark.parametrize(
    ("fixture_name", "max_mean_abs_diff"),
    [
        ("distribution_scatter", 0.03),
        ("distribution_violin", 0.04),
        ("iqr", 0.03),
    ],
)
def test_planner_built_resolved_specs_match_checked_in_parity_references(fixture_name: str, max_mean_abs_diff: float):
    payload = _fixture_payload(fixture_name)
    if fixture_name.startswith("distribution_"):
        payload["resolved_render_spec"] = build_resolved_distribution_spec(payload)
        native_image = _decode_png_bytes(render_distribution_png(payload))
    else:
        payload["resolved_render_spec"] = build_resolved_iqr_spec(payload)
        native_image = _decode_png_bytes(render_iqr_png(payload))

    assert _mean_absolute_image_difference(native_image, _fixture_reference_image(fixture_name)) <= max_mean_abs_diff

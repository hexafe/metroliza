from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
import numpy as np
from unittest import mock

from modules.chart_render_spec import (
    build_resolved_distribution_spec,
    build_resolved_iqr_spec,
    build_resolved_trend_spec,
)
from modules.chart_renderer import (
    build_chart_renderer,
    build_distribution_native_payload,
    native_full_chart_backend_available,
    native_chart_renderer_rollout_enabled,
    native_chart_renderer_rollout_enabled_for,
    resolve_histogram_renderer_backend,
    resolve_chart_renderer_backend,
    resolve_distribution_renderer_backend,
    resolve_iqr_renderer_backend,
    resolve_trend_renderer_backend,
)
from modules.native_chart_compositor import (
    render_distribution_png,
    render_iqr_png,
    render_trend_png,
)


@dataclass(frozen=True)
class ParityFixture:
    chart_type: str
    payload: dict[str, Any]
    spec: dict[str, Any]


def decode_png_bytes(png_bytes: bytes) -> np.ndarray:
    return plt.imread(BytesIO(png_bytes), format="png")[..., :3]


def coarse_region_occupancy(image: np.ndarray, *, y0: float, y1: float, x0: float, x1: float, threshold: float = 0.97) -> int:
    height, width = image.shape[:2]
    region = image[int(height * y0): int(height * y1), int(width * x0): int(width * x1), :3]
    return int(np.count_nonzero(np.any(region < threshold, axis=2)))


def mean_absolute_image_difference(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        raise ValueError(f"shape mismatch: {left.shape} != {right.shape}")
    return float(np.mean(np.abs(left.astype(np.float32) - right.astype(np.float32))))


def assert_metadata_contract(spec: Mapping[str, Any]) -> None:
    assert isinstance(spec.get("canvas"), Mapping)
    assert isinstance(spec.get("title"), Mapping)
    assert isinstance(spec.get("plot_area"), Mapping)
    assert isinstance(spec.get("axes"), Mapping)
    assert "x_ticks" in spec["axes"]
    assert "y_ticks" in spec["axes"]
    assert "x_label" in spec["axes"]
    assert "y_label" in spec["axes"]


def _spec_rect_to_axes_position(rect: Mapping[str, Any]) -> list[float]:
    return [
        float(rect.get("x") or 0.0),
        1.0 - float(rect.get("y") or 0.0) - float(rect.get("height") or 0.0),
        float(rect.get("width") or 0.0),
        float(rect.get("height") or 0.0),
    ]


def _apply_title(fig: plt.Figure, spec: Mapping[str, Any]) -> None:
    title = spec.get("title") if isinstance(spec.get("title"), Mapping) else {}
    anchor = title.get("anchor") if isinstance(title.get("anchor"), Mapping) else {}
    font = title.get("font") if isinstance(title.get("font"), Mapping) else {}
    text = str(title.get("text") or "")
    if not text:
        return
    fig.text(
        float(anchor.get("x") or 0.06),
        1.0 - float(anchor.get("y") or 0.985),
        text,
        ha=str(title.get("ha") or "left"),
        va=str(title.get("va") or "top"),
        fontsize=float(font.get("size") or 10.0),
        fontweight=str(font.get("weight") or "bold"),
        color=str(title.get("color") or "#1f1f1f"),
    )


def _matplotlib_marker_name(marker: Any) -> str:
    marker_text = str(marker or "circle").lower()
    return {
        "circle": "o",
        "triangle_up": "^",
        "triangle_down": "v",
        "square": "s",
    }.get(marker_text, marker_text)


def _apply_legend(fig: plt.Figure, spec: Mapping[str, Any]) -> None:
    legend = spec.get("legend") if isinstance(spec.get("legend"), Mapping) else {}
    items = list(legend.get("items") or [])
    if not items:
        return
    handles: list[Any] = []
    labels: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or "")
        if not label:
            continue
        kind = str(item.get("kind") or "line")
        if kind == "marker":
            handles.append(
                Line2D(
                    [0],
                    [0],
                    marker=str(item.get("marker") or "o"),
                    linestyle="None",
                    color=str(item.get("color") or "#1f1f1f"),
                    markersize=6,
                )
            )
        elif kind == "band":
            handles.append(
                Patch(
                    facecolor=str(item.get("fill_color") or "#d0d0d0"),
                    edgecolor=str(item.get("color") or "#1f1f1f"),
                    alpha=float(item.get("alpha") or 0.2),
                )
            )
        else:
            handles.append(
                Line2D(
                    [0],
                    [0],
                    color=str(item.get("color") or "#1f1f1f"),
                    linestyle="--" if item.get("dash") else "-",
                    linewidth=float(item.get("width") or 1.4),
                )
            )
        labels.append(label)
    if handles:
        fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.98, 0.98), framealpha=0.92)


def _draw_reference_lines(ax: plt.Axes, spec: Mapping[str, Any]) -> None:
    axes = spec.get("axes") if isinstance(spec.get("axes"), Mapping) else {}
    x_limits = axes.get("x_limits") if isinstance(axes.get("x_limits"), Mapping) else {}
    y_limits = axes.get("y_limits") if isinstance(axes.get("y_limits"), Mapping) else {}
    x_min = float(x_limits.get("min") or 0.0)
    x_max = float(x_limits.get("max") or 1.0)
    y_min = float(y_limits.get("min") or 0.0)
    y_max = float(y_limits.get("max") or 1.0)
    for band in list(spec.get("reference_bands") or []):
        if not isinstance(band, Mapping):
            continue
        axis = str(band.get("axis") or "y")
        start = float(band.get("start") or 0.0)
        end = float(band.get("end") or 0.0)
        if axis == "x":
            ax.axvspan(start, end, color=str(band.get("color") or "#d0d0d0"), alpha=float(band.get("alpha") or 0.12), zorder=0)
        else:
            ax.axhspan(start, end, color=str(band.get("color") or "#d0d0d0"), alpha=float(band.get("alpha") or 0.12), zorder=0)
    for line in list(spec.get("reference_lines") or []):
        if not isinstance(line, Mapping):
            continue
        axis = str(line.get("axis") or "y")
        value = float(line.get("value") or 0.0)
        color = str(line.get("color") or "#D55E00")
        width = float(line.get("width") or 1.5)
        linestyle = "--" if line.get("dash") else "-"
        if axis == "x":
            ax.axvline(value, color=color, linewidth=width, linestyle=linestyle, alpha=float(line.get("alpha") or 0.9))
        else:
            ax.axhline(value, color=color, linewidth=width, linestyle=linestyle, alpha=float(line.get("alpha") or 0.9))
    if x_max > x_min:
        ax.set_xlim(x_min, x_max)
    if y_max > y_min:
        ax.set_ylim(y_min, y_max)


def _apply_axes(ax: plt.Axes, spec: Mapping[str, Any]) -> None:
    axes = spec.get("axes") if isinstance(spec.get("axes"), Mapping) else {}
    x_limits = axes.get("x_limits") if isinstance(axes.get("x_limits"), Mapping) else {}
    y_limits = axes.get("y_limits") if isinstance(axes.get("y_limits"), Mapping) else {}
    ax.set_xlim(float(x_limits.get("min") or 0.0), float(x_limits.get("max") or 1.0))
    ax.set_ylim(float(y_limits.get("min") or 0.0), float(y_limits.get("max") or 1.0))
    x_ticks = [float(item.get("value") or 0.0) for item in list(axes.get("x_ticks") or []) if isinstance(item, Mapping)]
    x_labels = [str(item.get("label") or "") for item in list(axes.get("x_ticks") or []) if isinstance(item, Mapping)]
    y_ticks = [float(item.get("value") or 0.0) for item in list(axes.get("y_ticks") or []) if isinstance(item, Mapping)]
    y_labels = [str(item.get("label") or "") for item in list(axes.get("y_ticks") or []) if isinstance(item, Mapping)]
    if x_ticks:
        ax.set_xticks(x_ticks)
        ax.set_xticklabels(x_labels, rotation=int(axes.get("rotation") or 0))
    if y_ticks:
        ax.set_yticks(y_ticks)
        ax.set_yticklabels(y_labels)
    ax.set_xlabel(str(axes.get("x_label") or ""))
    ax.set_ylabel(str(axes.get("y_label") or ""))
    ax.grid(axis=str(axes.get("grid_axis") or "y"), color="#d9dfe7", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="both", colors="#4d5968")


def render_matplotlib_reference(spec: Mapping[str, Any], *, chart_type: str) -> np.ndarray:
    canvas = spec.get("canvas") if isinstance(spec.get("canvas"), Mapping) else {}
    width_px = int(canvas.get("width_px") or 900)
    height_px = int(canvas.get("height_px") or 450)
    dpi = int(canvas.get("dpi") or 150)
    fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    _apply_title(fig, spec)
    _apply_legend(fig, spec)
    plot_area = spec.get("plot_area") if isinstance(spec.get("plot_area"), Mapping) else {}
    ax = fig.add_axes(_spec_rect_to_axes_position(plot_area))
    _apply_axes(ax, spec)
    _draw_reference_lines(ax, spec)

    if chart_type == "distribution":
        render_mode = str(spec.get("render_mode") or "scatter")
        if render_mode == "scatter":
            for point in list(spec.get("scatter_points") or []):
                if not isinstance(point, Mapping):
                    continue
                ax.scatter(
                    [float(point.get("x") or 0.0)],
                    [float(point.get("y") or 0.0)],
                    marker=_matplotlib_marker_name(point.get("marker")),
                    s=float(point.get("size") or 6) * 4.0,
                    color=str(point.get("color") or "#1f77b4"),
                )
        else:
            for group in list(spec.get("violin_groups") or []):
                if not isinstance(group, Mapping):
                    continue
                values = np.asarray(group.get("values") or [], dtype=float)
                if values.size == 0:
                    continue
                parts = ax.violinplot([values], positions=[float(group.get("position") or 0.0)], showmeans=False, showmedians=False, showextrema=False)
                for body in parts.get("bodies", []):
                    body.set_facecolor("#8cb8d9")
                    body.set_edgecolor("#1f77b4")
                    body.set_alpha(0.45)
        for item in list(spec.get("violin_annotations") or []):
            if not isinstance(item, Mapping):
                continue
            x = float(item.get("position") or 0.0)
            y = float(item.get("mean") or 0.0)
            ax.scatter([x], [y], color="#1f77b4", s=30, zorder=4)
    elif chart_type == "iqr":
        boxes = list(spec.get("boxes") or [])
        positions = [float(item.get("position") or 0.0) for item in boxes if isinstance(item, Mapping)]
        for box, position in zip(boxes, positions):
            if not isinstance(box, Mapping):
                continue
            q1 = float(box.get("q1") or 0.0)
            median = float(box.get("median") or 0.0)
            q3 = float(box.get("q3") or 0.0)
            whisker_low = float(box.get("whisker_low") or q1)
            whisker_high = float(box.get("whisker_high") or q3)
            half_width = 0.14
            ax.add_patch(
                Rectangle(
                    (position - half_width, q1),
                    half_width * 2.0,
                    max(0.0, q3 - q1),
                    facecolor="#8cb8d9",
                    edgecolor="#1f77b4",
                    alpha=0.45,
                    linewidth=1.2,
                    zorder=2,
                )
            )
            ax.plot([position - half_width, position + half_width], [median, median], color="#1f77b4", linewidth=1.4, zorder=3)
            ax.plot([position, position], [whisker_low, q1], color="#1f77b4", linewidth=1.1, zorder=2)
            ax.plot([position, position], [q3, whisker_high], color="#1f77b4", linewidth=1.1, zorder=2)
            ax.plot([position - 0.05, position + 0.05], [whisker_high, whisker_high], color="#1f77b4", linewidth=1.1, zorder=2)
            ax.plot([position - 0.05, position + 0.05], [whisker_low, whisker_low], color="#1f77b4", linewidth=1.1, zorder=2)
            outliers = [float(item) for item in list(box.get("outliers") or [])]
            if outliers:
                ax.scatter([position] * len(outliers), outliers, color="#d55e00", s=16, zorder=4)
    elif chart_type == "trend":
        for point in list(spec.get("points") or []):
            if not isinstance(point, Mapping):
                continue
            ax.scatter(
                [float(point.get("x") or 0.0)],
                [float(point.get("y") or 0.0)],
                marker=_matplotlib_marker_name(point.get("marker")),
                s=float(point.get("size") or 6) * 4.0,
                color=str(point.get("color") or "#1f77b4"),
            )
    else:
        raise ValueError(f"Unsupported chart type: {chart_type}")

    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi)
    plt.close(fig)
    return plt.imread(BytesIO(buffer.getvalue()), format="png")[..., :3]


def assert_coarse_parity(native_image: np.ndarray, reference_image: np.ndarray, *, max_mean_abs_diff: float, min_overlap_pixels: int, overlap_region: tuple[float, float, float, float]) -> None:
    assert native_image.shape == reference_image.shape
    diff = mean_absolute_image_difference(native_image, reference_image)
    assert diff <= max_mean_abs_diff
    y0, y1, x0, x1 = overlap_region
    native_occupancy = coarse_region_occupancy(native_image, y0=y0, y1=y1, x0=x0, x1=x1)
    reference_occupancy = coarse_region_occupancy(reference_image, y0=y0, y1=y1, x0=x0, x1=x1)
    assert native_occupancy >= min_overlap_pixels
    assert reference_occupancy >= min_overlap_pixels


def build_distribution_parity_fixture() -> ParityFixture:
    payload = build_distribution_native_payload(
        values=[[1.0, 1.08, 1.12], [1.34, 1.43, 1.52]],
        labels=["Alpha", "Beta"],
        title="Distribution Parity",
        lsl=0.9,
        usl=1.8,
    )
    payload.update(
        {
            "render_mode": "scatter",
            "x_values": [0.2, 0.8],
            "y_values": [1.05, 1.41],
            "x_domain": {"min": 0.0, "max": 1.0},
            "canvas": {"width_px": 960, "height_px": 540, "dpi": 150},
        }
    )
    payload["resolved_render_spec"] = build_resolved_distribution_spec(payload)
    return ParityFixture(chart_type="distribution", payload=payload, spec=payload["resolved_render_spec"])


def build_iqr_parity_fixture() -> ParityFixture:
    payload = {
        "type": "iqr",
        "labels": ["Only"],
        "series": [[1.0, 1.1, 1.2, 1.3, 5.0]],
        "title": "IQR Parity",
        "lsl": 0.8,
        "usl": 5.2,
        "nominal": 1.2,
        "one_sided": False,
        "layout": {"rotation": 0, "display_positions": [1.0], "display_labels": ["Only"], "bottom_margin": 0.18},
        "canvas": {"width_px": 960, "height_px": 540, "dpi": 150},
        "x_label": "Group",
        "y_label": "Measurement",
        "legend": {"items": [{"label": "Median", "kind": "line", "color": "#E69F00"}]},
    }
    payload["resolved_render_spec"] = build_resolved_iqr_spec(payload)
    return ParityFixture(chart_type="iqr", payload=payload, spec=payload["resolved_render_spec"])


def build_trend_parity_fixture() -> ParityFixture:
    payload = {
        "type": "trend",
        "x_values": [0.0, 1.0, 2.0, 3.0],
        "y_values": [1.0, 1.2, 1.1, 1.35],
        "labels": ["S1", "S2", "S3", "S4"],
        "title": "Trend Parity",
        "x_label": "Sample #",
        "y_label": "Measurement",
        "horizontal_limits": [0.9, 1.4],
        "layout": {"rotation": 0, "display_positions": [0.0, 1.0, 2.0, 3.0], "display_labels": ["S1", "S2", "S3", "S4"], "bottom_margin": 0.22},
        "canvas": {"width_px": 960, "height_px": 540, "dpi": 150},
    }
    payload["resolved_render_spec"] = build_resolved_trend_spec(payload)
    return ParityFixture(chart_type="trend", payload=payload, spec=payload["resolved_render_spec"])


def test_parity_harness_helpers_decode_and_measure_images():
    fixture = build_trend_parity_fixture()
    native_image = decode_png_bytes(render_trend_png(fixture.payload))
    reference_image = render_matplotlib_reference(fixture.spec, chart_type=fixture.chart_type)

    assert native_image.shape == reference_image.shape
    assert coarse_region_occupancy(native_image, y0=0.10, y1=0.90, x0=0.10, x1=0.90) > 1000
    assert mean_absolute_image_difference(native_image, reference_image) < 0.03


def test_distribution_parity_harness_tracks_metadata_and_coarse_image_parity():
    fixture = build_distribution_parity_fixture()
    assert_metadata_contract(fixture.spec)

    native_image = decode_png_bytes(render_distribution_png(fixture.payload))
    reference_image = render_matplotlib_reference(fixture.spec, chart_type=fixture.chart_type)

    assert "scatter_points" in fixture.spec
    assert len(fixture.spec["scatter_points"]) == 2
    assert_coarse_parity(
        native_image,
        reference_image,
        max_mean_abs_diff=0.41,
        min_overlap_pixels=5000,
        overlap_region=(0.10, 0.90, 0.10, 0.90),
    )


def test_iqr_parity_harness_tracks_metadata_and_coarse_image_parity():
    fixture = build_iqr_parity_fixture()
    assert_metadata_contract(fixture.spec)

    native_image = decode_png_bytes(render_iqr_png(fixture.payload))
    reference_image = render_matplotlib_reference(fixture.spec, chart_type=fixture.chart_type)

    assert len(fixture.spec["boxes"]) == 1
    assert fixture.spec["boxes"][0]["outliers"] == [5.0]
    assert_coarse_parity(
        native_image,
        reference_image,
        max_mean_abs_diff=0.30,
        min_overlap_pixels=2000,
        overlap_region=(0.10, 0.90, 0.10, 0.90),
    )


def test_trend_parity_harness_tracks_metadata_and_coarse_image_parity():
    fixture = build_trend_parity_fixture()
    assert_metadata_contract(fixture.spec)

    native_image = decode_png_bytes(render_trend_png(fixture.payload))
    reference_image = render_matplotlib_reference(fixture.spec, chart_type=fixture.chart_type)

    assert len(fixture.spec["points"]) == 4
    assert len(fixture.spec["reference_lines"]) == 2
    assert_coarse_parity(
        native_image,
        reference_image,
        max_mean_abs_diff=0.05,
        min_overlap_pixels=1000,
        overlap_region=(0.10, 0.90, 0.10, 0.90),
    )


def test_backend_policy_defaults_to_matplotlib_until_native_is_opted_in(monkeypatch):
    monkeypatch.delenv("METROLIZA_CHART_RENDERER_BACKEND", raising=False)
    monkeypatch.delenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", raising=False)
    with (
        mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_distribution_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_iqr_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_trend_png", lambda payload: b"png"),
        mock.patch("warnings.warn") as warn,
    ):
        assert native_full_chart_backend_available() is True
        assert native_chart_renderer_rollout_enabled() is True
        assert native_chart_renderer_rollout_enabled_for("histogram") is True
        assert resolve_chart_renderer_backend() == "matplotlib"
        assert resolve_distribution_renderer_backend() == "matplotlib"
        assert resolve_histogram_renderer_backend() == "matplotlib"
        assert resolve_iqr_renderer_backend() == "matplotlib"
        assert resolve_trend_renderer_backend() == "matplotlib"
        assert type(build_chart_renderer()).__name__ == "MatplotlibChartRenderer"
    assert warn.call_count == 0


def test_backend_policy_enables_selected_chart_types_with_rollout_allowlist(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "auto")
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "distribution,trend")
    with (
        mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_distribution_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_iqr_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_trend_png", lambda payload: b"png"),
    ):
        assert native_chart_renderer_rollout_enabled() is True
        assert native_chart_renderer_rollout_enabled_for("histogram") is False
        assert native_chart_renderer_rollout_enabled_for("distribution") is True
        assert native_chart_renderer_rollout_enabled_for("iqr") is False
        assert native_chart_renderer_rollout_enabled_for("trend") is True
        assert resolve_histogram_renderer_backend() == "matplotlib"
        assert resolve_distribution_renderer_backend() == "native"
        assert resolve_iqr_renderer_backend() == "matplotlib"
        assert resolve_trend_renderer_backend() == "native"
        assert type(build_chart_renderer()).__name__ == "NativeChartRenderer"

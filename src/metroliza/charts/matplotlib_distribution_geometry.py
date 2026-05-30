"""Matplotlib artist geometry extraction for distribution chart parity."""

from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib import colors as mcolors


def _as_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return numeric


def _normalize_rgba(color: Any) -> tuple[str, float]:
    rgba = mcolors.to_rgba(color)
    return mcolors.to_hex(rgba, keep_alpha=False), float(rgba[3])


def _bbox_to_rect(fig, bbox) -> dict[str, float]:
    fig_bbox = fig.bbox
    width = max(float(fig_bbox.width), 1.0)
    height = max(float(fig_bbox.height), 1.0)
    return {
        "x": float((bbox.x0 - fig_bbox.x0) / width),
        "y": float((bbox.y0 - fig_bbox.y0) / height),
        "width": float(bbox.width / width),
        "height": float(bbox.height / height),
    }


def _axes_rect(ax) -> dict[str, float]:
    x0, y0, width, height = ax.get_position().bounds
    return {
        "x": float(x0),
        "y": float(y0),
        "width": float(width),
        "height": float(height),
    }


def _point_to_figure_coords(fig, transform, xy: tuple[float, float]) -> tuple[float, float]:
    display_xy = transform.transform(xy)
    figure_xy = fig.transFigure.inverted().transform(display_xy)
    return float(figure_xy[0]), float(figure_xy[1])


def _extract_title(fig, ax, renderer, payload: dict[str, Any]) -> dict[str, Any]:
    title_artist = ax.title
    title_text = str(title_artist.get_text() or payload.get("title") or "")
    anchor_x, anchor_y = _point_to_figure_coords(fig, title_artist.get_transform(), title_artist.get_position())
    color, alpha = _normalize_rgba(title_artist.get_color())
    return {
        "text": title_text,
        "anchor": {"x": anchor_x, "y": anchor_y},
        "font": {
            "size": float(title_artist.get_fontsize()),
            "weight": str(title_artist.get_fontweight()),
            "family": str(title_artist.get_fontfamily()[0] if title_artist.get_fontfamily() else ""),
        },
        "color": color,
        "alpha": alpha,
        "ha": str(title_artist.get_ha()),
        "va": str(title_artist.get_va()),
        "rect": _bbox_to_rect(fig, title_artist.get_window_extent(renderer=renderer)),
    }


def _extract_ticks(axis, labels) -> tuple[list[dict[str, Any]], int, str]:
    visible_ticks: list[dict[str, Any]] = []
    rotation = 0
    ha = "center"
    for value, label_artist in zip(axis.get_ticklocs(), labels):
        if not label_artist.get_visible():
            continue
        text = str(label_artist.get_text() or "")
        if text == "":
            continue
        rotation = int(round(float(label_artist.get_rotation())))
        ha = str(label_artist.get_ha())
        visible_ticks.append({"value": float(value), "label": text})
    return visible_ticks, rotation, ha


def _extract_axes(ax) -> dict[str, Any]:
    x_ticks, rotation, x_ha = _extract_ticks(ax.xaxis, ax.get_xticklabels())
    y_ticks, _y_rotation, _y_ha = _extract_ticks(ax.yaxis, ax.get_yticklabels())
    return {
        "x_limits": {"min": float(ax.get_xlim()[0]), "max": float(ax.get_xlim()[1])},
        "y_limits": {"min": float(ax.get_ylim()[0]), "max": float(ax.get_ylim()[1])},
        "x_ticks": x_ticks,
        "y_ticks": y_ticks,
        "x_label": str(ax.get_xlabel() or ""),
        "y_label": str(ax.get_ylabel() or ""),
        "grid_axis": "y" if any(line.get_visible() for line in ax.yaxis.get_gridlines()) else "x" if any(line.get_visible() for line in ax.xaxis.get_gridlines()) else "none",
        "rotation": rotation,
        "ha": x_ha,
    }


def _extract_legend(fig, ax, renderer) -> dict[str, Any] | None:
    legend = fig.legends[-1] if fig.legends else ax.get_legend()
    if legend is None:
        return None

    legend_handles = list(getattr(legend, "legend_handles", []) or getattr(legend, "legendHandles", []) or [])
    texts = legend.get_texts()
    items: list[dict[str, Any]] = []
    for handle, text_artist in zip(legend_handles, texts):
        label = str(text_artist.get_text() or "")
        item: dict[str, Any] = {"label": label}
        if hasattr(handle, "get_marker") and str(handle.get_marker() or "").lower() not in {"", "none", " "}:
            color, alpha = _normalize_rgba(handle.get_markerfacecolor() or handle.get_color())
            item.update(
                {
                    "kind": "marker",
                    "marker": str(handle.get_marker()),
                    "color": color,
                    "alpha": alpha,
                }
            )
        elif hasattr(handle, "get_facecolor") and not hasattr(handle, "get_xdata"):
            fill_color, fill_alpha = _normalize_rgba(handle.get_facecolor())
            item.update(
                {
                    "kind": "band",
                    "fill_color": fill_color,
                    "alpha": fill_alpha,
                }
            )
        else:
            color, alpha = _normalize_rgba(handle.get_color())
            dash = None
            if hasattr(handle, "get_linestyle"):
                linestyle = handle.get_linestyle()
                if isinstance(linestyle, tuple) and len(linestyle) == 2 and linestyle[1]:
                    dash = [int(piece) for piece in linestyle[1]]
            item.update(
                {
                    "kind": "line",
                    "color": color,
                    "alpha": alpha,
                    "dash": dash,
                }
            )
        items.append(item)

    return {
        "rect": _bbox_to_rect(fig, legend.get_window_extent(renderer=renderer)),
        "items": items,
    }


def _extract_reference_bands(ax) -> list[dict[str, Any]]:
    bands: list[dict[str, Any]] = []
    for patch in ax.patches:
        if type(patch).__name__ != "Rectangle":
            continue
        alpha = _as_float(patch.get_alpha())
        if alpha is None or alpha <= 0:
            continue
        x = _as_float(getattr(patch, "get_x", lambda: None)())
        width = _as_float(getattr(patch, "get_width", lambda: None)())
        y = _as_float(getattr(patch, "get_y", lambda: None)())
        height = _as_float(getattr(patch, "get_height", lambda: None)())
        if x is None or width is None or y is None or height is None:
            continue
        color, resolved_alpha = _normalize_rgba(patch.get_facecolor())
        bands.append(
            {
                "axis": "y",
                "start": float(y),
                "end": float(y + height),
                "color": color,
                "alpha": float(alpha if alpha is not None else resolved_alpha),
                "span0_axes": float(x),
                "span1_axes": float(x + width),
            }
        )
    return bands


def _extract_reference_lines(ax) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for line in ax.lines:
        x_data = np.asarray(line.get_xdata(), dtype=float)
        y_data = np.asarray(line.get_ydata(), dtype=float)
        if x_data.size < 2 or y_data.size < 2:
            continue
        if np.allclose(y_data, y_data[0], equal_nan=False):
            color, alpha = _normalize_rgba(line.get_color())
            dash = None
            linestyle = line.get_linestyle()
            if isinstance(linestyle, tuple) and len(linestyle) == 2 and linestyle[1]:
                dash = [int(piece) for piece in linestyle[1]]
            lines.append(
                {
                    "axis": "y",
                    "value": float(y_data[0]),
                    "color": color,
                    "alpha": float(line.get_alpha() if line.get_alpha() is not None else alpha),
                    "width": float(line.get_linewidth()),
                    "dash": dash,
                }
            )
    return lines


def _extract_violin_bodies(ax) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []
    for collection in ax.collections:
        collection_name = type(collection).__name__
        if collection_name in {"PathCollection", "LineCollection"}:
            continue
        paths = collection.get_paths()
        if not paths:
            continue
        facecolors = collection.get_facecolor()
        edgecolors = collection.get_edgecolor()
        linewidths = collection.get_linewidths()
        fill_color, fill_alpha = _normalize_rgba(facecolors[0] if len(facecolors) else collection.get_facecolor())
        edge_color, edge_alpha = _normalize_rgba(edgecolors[0] if len(edgecolors) else collection.get_edgecolor())
        vertices = paths[0].vertices
        bodies.append(
            {
                "polygon_points": [{"x": float(x), "y": float(y)} for x, y in vertices.tolist()],
                "fill_color": fill_color,
                "fill_alpha": fill_alpha,
                "edge_color": edge_color,
                "edge_alpha": edge_alpha,
                "edge_width": float(linewidths[0] if len(linewidths) else 1.0),
            }
        )
    return bodies


def _infer_marker_kind(vertices: np.ndarray) -> str:
    if vertices.shape[0] <= 4:
        return "triangle_up" if float(vertices[0][1]) > 0 else "triangle_down"
    if vertices.shape[0] > 6:
        return "circle"
    return "marker"


def _extract_annotation_geometry(fig, ax, renderer) -> dict[str, Any]:
    markers: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []

    for collection in ax.collections:
        collection_name = type(collection).__name__
        if collection_name == "PathCollection":
            offsets = np.asarray(collection.get_offsets(), dtype=float)
            if offsets.size == 0:
                continue
            paths = collection.get_paths()
            marker_kind = _infer_marker_kind(paths[0].vertices) if paths else "marker"
            facecolors = collection.get_facecolor()
            color, alpha = _normalize_rgba(facecolors[0] if len(facecolors) else collection.get_facecolor())
            sizes = collection.get_sizes()
            marker_size = float(np.sqrt(float(sizes[0]))) if len(sizes) else 0.0
            for x_value, y_value in offsets.tolist():
                markers.append(
                    {
                        "kind": marker_kind,
                        "x": float(x_value),
                        "y": float(y_value),
                        "size": marker_size,
                        "color": color,
                        "alpha": alpha,
                    }
                )
        elif collection_name == "LineCollection":
            segments_raw = collection.get_segments()
            colors = collection.get_colors()
            linewidths = collection.get_linewidths()
            color, alpha = _normalize_rgba(colors[0] if len(colors) else "#000000")
            dash = None
            linestyle = collection.get_linestyle()
            if linestyle and len(linestyle[0]) >= 2:
                dash = [int(piece) for piece in linestyle[0][1]]
            for segment in segments_raw:
                if len(segment) < 2:
                    continue
                start, end = segment[0], segment[1]
                segments.append(
                    {
                        "x0": float(start[0]),
                        "y0": float(start[1]),
                        "x1": float(end[0]),
                        "y1": float(end[1]),
                        "color": color,
                        "alpha": alpha,
                        "width": float(linewidths[0] if len(linewidths) else 1.0),
                        "dash": dash,
                    }
                )

    for text_artist in ax.texts:
        if not text_artist.get_visible():
            continue
        bbox = text_artist.get_window_extent(renderer=renderer)
        color, alpha = _normalize_rgba(text_artist.get_color())
        text_item = {
            "text": str(text_artist.get_text() or ""),
            "font_size": float(text_artist.get_fontsize()),
            "color": color,
            "alpha": alpha,
            "ha": str(text_artist.get_ha()),
            "va": str(text_artist.get_va()),
            "rect": _bbox_to_rect(fig, bbox),
        }
        if hasattr(text_artist, "xy"):
            text_item["point_x"] = float(text_artist.xy[0])
            text_item["point_y"] = float(text_artist.xy[1])
        if hasattr(text_artist, "xyann"):
            text_item["offset_points"] = {
                "x": float(text_artist.xyann[0]),
                "y": float(text_artist.xyann[1]),
            }
        texts.append(text_item)

    return {
        "markers": markers,
        "segments": segments,
        "texts": texts,
    }


def _extract_scatter_points(ax) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for collection in ax.collections:
        if type(collection).__name__ != "PathCollection":
            continue
        offsets = np.asarray(collection.get_offsets(), dtype=float)
        if offsets.size == 0:
            continue
        facecolors = collection.get_facecolor()
        color, alpha = _normalize_rgba(facecolors[0] if len(facecolors) else collection.get_facecolor())
        sizes = collection.get_sizes()
        marker_size = float(np.sqrt(float(sizes[0]))) if len(sizes) else 0.0
        for x_value, y_value in offsets.tolist():
            points.append(
                {
                    "x": float(x_value),
                    "y": float(y_value),
                    "marker": "circle",
                    "size": marker_size,
                    "color": color,
                    "alpha": alpha,
                }
            )
    return points


def extract_distribution_geometry(fig, ax, *, render_mode: str, payload: dict) -> dict:
    """Extract finalized matplotlib geometry for a distribution chart."""

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes = _extract_axes(ax)
    plot_area = _axes_rect(ax)
    geometry: dict[str, Any] = {
        "chart_type": "distribution",
        "source": "matplotlib_finalized",
        "canvas": {
            "width_px": int(round(float(fig.bbox.width))),
            "height_px": int(round(float(fig.bbox.height))),
            "dpi": int(round(float(fig.dpi))),
        },
        "render_mode": str(render_mode or "violin"),
        "title": _extract_title(fig, ax, renderer, payload),
        "plot_area": plot_area,
        "plot_rect": dict(plot_area),
        "axes": axes,
        "x_ticks": [{"position": tick["value"], "label": tick["label"]} for tick in axes["x_ticks"]],
        "y_ticks": [{"position": tick["value"], "label": tick["label"]} for tick in axes["y_ticks"]],
        "x_label": axes["x_label"],
        "y_label": axes["y_label"],
        "grid_axis": axes["grid_axis"],
        "x_min": axes["x_limits"]["min"],
        "x_max": axes["x_limits"]["max"],
        "y_min": axes["y_limits"]["min"],
        "y_max": axes["y_limits"]["max"],
        "legend": _extract_legend(fig, ax, renderer),
        "reference_bands": _extract_reference_bands(ax),
        "reference_lines": _extract_reference_lines(ax),
    }

    if str(render_mode or "").lower() == "scatter":
        geometry["scatter_points"] = _extract_scatter_points(ax)
        geometry["violin_bodies"] = []
        geometry["annotations"] = {"markers": [], "segments": [], "texts": []}
        return geometry

    geometry["violin_bodies"] = _extract_violin_bodies(ax)
    geometry["annotations"] = _extract_annotation_geometry(fig, ax, renderer)
    geometry["scatter_points"] = []
    return geometry

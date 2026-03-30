"""Finalized matplotlib geometry extraction for IQR and trend charts.

This module inspects rendered matplotlib artists after layout is finalized and
returns serializable geometry payloads that native rendering can consume
without re-running statistical/layout heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
from matplotlib import colors as mcolors
from matplotlib.collections import PathCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


_NONE_MARKERS = {"", " ", "none", "None", None}
_NONE_LINESTYLES = {"", " ", "none", "None", None}


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _to_hex(color: Any, *, default: str = "#000000") -> str:
    try:
        return str(mcolors.to_hex(color, keep_alpha=False))
    except Exception:
        return default


def _figure_rect_from_display_bbox(fig: Any, bbox: Any) -> dict[str, float]:
    fig_bbox = fig.bbox
    width = max(float(fig_bbox.width), 1.0)
    height = max(float(fig_bbox.height), 1.0)
    return {
        "x": float((bbox.x0 - fig_bbox.x0) / width),
        "y": float((bbox.y0 - fig_bbox.y0) / height),
        "width": float((bbox.x1 - bbox.x0) / width),
        "height": float((bbox.y1 - bbox.y0) / height),
    }


def _plot_rect(ax: Any) -> dict[str, float]:
    bbox = ax.get_position()
    return {
        "x": float(bbox.x0),
        "y": float(bbox.y0),
        "width": float(bbox.width),
        "height": float(bbox.height),
    }


def _title_payload(fig: Any, ax: Any) -> dict[str, Any]:
    title_artist = ax.title if str(ax.get_title() or "").strip() else None
    if title_artist is None and getattr(fig, "_suptitle", None) is not None:
        candidate = getattr(fig, "_suptitle")
        if str(candidate.get_text() or "").strip():
            title_artist = candidate

    if title_artist is None:
        return {
            "text": "",
            "anchor": {"x": 0.0, "y": 1.0},
            "font": {"size": 10.0, "weight": "normal", "family": ""},
            "color": "#000000",
            "ha": "center",
            "va": "top",
        }

    anchor_display = title_artist.get_transform().transform(title_artist.get_position())
    anchor_figure = fig.transFigure.inverted().transform(anchor_display)
    font_props = title_artist.get_fontproperties()
    family = ""
    try:
        family_list = list(font_props.get_family() or [])
        family = str(family_list[0]) if family_list else ""
    except Exception:
        family = ""

    return {
        "text": str(title_artist.get_text() or ""),
        "anchor": {
            "x": float(anchor_figure[0]),
            "y": float(anchor_figure[1]),
        },
        "font": {
            "size": float(font_props.get_size_in_points()),
            "weight": str(font_props.get_weight() or "normal"),
            "family": family,
        },
        "color": _to_hex(title_artist.get_color(), default="#1f2937"),
        "ha": str(title_artist.get_ha() or "center"),
        "va": str(title_artist.get_va() or "top"),
    }


def _axis_ticks(axis: Any, labels: list[Any]) -> list[dict[str, Any]]:
    tick_positions = [float(item) for item in axis.get_ticklocs()]
    label_texts = [str(label.get_text() or "") for label in labels]
    visible_flags = [bool(label.get_visible()) for label in labels]
    if len(label_texts) < len(tick_positions):
        missing = len(tick_positions) - len(label_texts)
        label_texts.extend([""] * missing)
        visible_flags.extend([False] * missing)
    elif len(label_texts) > len(tick_positions):
        label_texts = label_texts[: len(tick_positions)]
        visible_flags = visible_flags[: len(tick_positions)]
    return [
        {
            "value": float(value),
            "label": str(label_text),
            "visible": bool(visible),
        }
        for value, label_text, visible in zip(tick_positions, label_texts, visible_flags)
    ]


def _dominant_rotation(labels: list[Any]) -> int:
    visible = [label for label in labels if bool(label.get_visible())]
    if not visible:
        return 0
    rotations = [float(label.get_rotation() or 0.0) for label in visible]
    if not rotations:
        return 0
    return int(round(float(np.median(rotations))))


def _resolve_grid_axis(ax: Any) -> str:
    has_y_grid = any(bool(line.get_visible()) for line in ax.yaxis.get_gridlines())
    has_x_grid = any(bool(line.get_visible()) for line in ax.xaxis.get_gridlines())
    if has_y_grid and not has_x_grid:
        return "y"
    if has_x_grid and not has_y_grid:
        return "x"
    if has_x_grid and has_y_grid:
        return "both"
    return "none"


def _axes_payload(ax: Any) -> dict[str, Any]:
    x_ticks = _axis_ticks(ax.xaxis, list(ax.get_xticklabels()))
    y_ticks = _axis_ticks(ax.yaxis, list(ax.get_yticklabels()))
    return {
        "x_limits": {"min": float(ax.get_xlim()[0]), "max": float(ax.get_xlim()[1])},
        "y_limits": {"min": float(ax.get_ylim()[0]), "max": float(ax.get_ylim()[1])},
        "x_ticks": x_ticks,
        "y_ticks": y_ticks,
        "x_label": str(ax.get_xlabel() or ""),
        "y_label": str(ax.get_ylabel() or ""),
        "rotation": _dominant_rotation(list(ax.get_xticklabels())),
        "grid_axis": _resolve_grid_axis(ax),
    }


def _line_dash_pattern(line: Line2D) -> list[int] | None:
    try:
        _offset, dashes = line.get_dashes()
    except Exception:
        dashes = None
    if not dashes:
        return None
    return [int(max(1, round(float(item)))) for item in dashes]


def _legend_item(handle: Any, *, label: str) -> dict[str, Any]:
    if isinstance(handle, Line2D):
        marker = handle.get_marker()
        linestyle = handle.get_linestyle()
        marker_only = marker not in _NONE_MARKERS and linestyle in _NONE_LINESTYLES
        return {
            "label": label,
            "kind": "marker" if marker_only else "line",
            "marker": str(marker) if marker not in _NONE_MARKERS else None,
            "color": _to_hex(handle.get_color(), default="#1f2937"),
            "width": float(handle.get_linewidth() or 1.0),
            "dash": _line_dash_pattern(handle),
            "alpha": float(handle.get_alpha()) if _to_float(handle.get_alpha()) is not None else 1.0,
        }

    if isinstance(handle, Patch):
        alpha = _to_float(handle.get_alpha())
        face = handle.get_facecolor()
        edge = handle.get_edgecolor()
        return {
            "label": label,
            "kind": "band",
            "fill_color": _to_hex(face, default="#dbeafe"),
            "color": _to_hex(edge, default="#1f2937"),
            "alpha": float(alpha if alpha is not None else (face[3] if len(face) == 4 else 1.0)),
        }

    return {
        "label": label,
        "kind": "unknown",
    }


def _legend_payload(fig: Any, ax: Any, renderer: Any) -> dict[str, Any] | None:
    legend_artist = fig.legends[-1] if getattr(fig, "legends", None) else ax.get_legend()
    if legend_artist is None:
        return None

    labels = [str(text.get_text() or "") for text in legend_artist.get_texts()]
    handles = list(getattr(legend_artist, "legend_handles", []) or getattr(legend_artist, "legendHandles", []))
    if len(handles) < len(labels):
        axis_handles, axis_labels = ax.get_legend_handles_labels()
        lookup = {str(label): handle for label, handle in zip(axis_labels, axis_handles)}
        for label in labels:
            handles.append(lookup.get(label))
        handles = handles[: len(labels)]

    items = []
    for label, handle in zip(labels, handles):
        if handle is None:
            continue
        items.append(_legend_item(handle, label=label))

    bbox = legend_artist.get_window_extent(renderer=renderer)
    return {
        "rect": _figure_rect_from_display_bbox(fig, bbox),
        "items": items,
    }


def _line_xy_data(line: Line2D) -> np.ndarray:
    path = line.get_path()
    if path is not None:
        vertices = np.asarray(path.vertices, dtype=float)
        if vertices.ndim == 2 and vertices.shape[1] == 2 and vertices.shape[0] >= 2:
            finite = np.isfinite(vertices).all(axis=1)
            return vertices[finite]
    data = np.asarray(line.get_xydata(), dtype=float)
    if data.ndim != 2 or data.shape[1] != 2:
        return np.empty((0, 2), dtype=float)
    finite = np.isfinite(data).all(axis=1)
    return data[finite]


def _line_vertices_in_data(ax: Any, line: Line2D) -> np.ndarray:
    vertices = _line_xy_data(line)
    if vertices.shape[0] < 2:
        return vertices
    display_vertices = line.get_transform().transform(vertices)
    data_vertices = ax.transData.inverted().transform(display_vertices)
    finite = np.isfinite(data_vertices).all(axis=1)
    return data_vertices[finite]


def _extract_reference_lines(ax: Any, *, span_fraction: float = 0.72) -> list[dict[str, Any]]:
    x_min, x_max = ax.get_xlim()
    x_range = max(abs(float(x_max) - float(x_min)), 1e-12)
    y_min, y_max = ax.get_ylim()
    y_range = max(abs(float(y_max) - float(y_min)), 1e-12)
    tolerance = max(1e-9, 1e-6 * max(x_range, y_range))

    lines: list[dict[str, Any]] = []
    for line in ax.lines:
        if not bool(line.get_visible()):
            continue
        marker = line.get_marker()
        linestyle = line.get_linestyle()
        if marker not in _NONE_MARKERS and linestyle in _NONE_LINESTYLES:
            continue

        data = _line_vertices_in_data(ax, line)
        if data.shape[0] < 2:
            continue
        x_values = data[:, 0]
        y_values = data[:, 1]
        x_span = float(np.max(x_values) - np.min(x_values))
        y_span = float(np.max(y_values) - np.min(y_values))

        if y_span <= tolerance and x_span >= span_fraction * x_range:
            span0 = float((np.min(x_values) - x_min) / x_range)
            span1 = float((np.max(x_values) - x_min) / x_range)
            lines.append(
                {
                    "axis": "y",
                    "value": float(np.mean(y_values)),
                    "color": _to_hex(line.get_color(), default="#D55E00"),
                    "alpha": float(line.get_alpha()) if _to_float(line.get_alpha()) is not None else 1.0,
                    "width": float(line.get_linewidth() or 1.0),
                    "dash": _line_dash_pattern(line),
                    "span0_axes": max(0.0, min(1.0, span0)),
                    "span1_axes": max(0.0, min(1.0, span1)),
                }
            )
            continue

        if x_span <= tolerance and y_span >= span_fraction * y_range:
            span0 = float((np.min(y_values) - y_min) / y_range)
            span1 = float((np.max(y_values) - y_min) / y_range)
            lines.append(
                {
                    "axis": "x",
                    "value": float(np.mean(x_values)),
                    "color": _to_hex(line.get_color(), default="#D55E00"),
                    "alpha": float(line.get_alpha()) if _to_float(line.get_alpha()) is not None else 1.0,
                    "width": float(line.get_linewidth() or 1.0),
                    "dash": _line_dash_pattern(line),
                    "span0_axes": max(0.0, min(1.0, span0)),
                    "span1_axes": max(0.0, min(1.0, span1)),
                }
            )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in lines:
        key = (
            row.get("axis"),
            round(float(row.get("value", 0.0)), 10),
            row.get("color"),
            round(float(row.get("width", 0.0)), 4),
            tuple(row.get("dash") or []),
            round(float(row.get("span0_axes", 0.0)), 4),
            round(float(row.get("span1_axes", 0.0)), 4),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _patch_vertices_in_data(ax: Any, patch: Any) -> np.ndarray:
    path = patch.get_path()
    if path is None:
        return np.empty((0, 2), dtype=float)
    vertices = np.asarray(path.vertices, dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] != 2:
        return np.empty((0, 2), dtype=float)
    display_vertices = patch.get_transform().transform(vertices)
    data_vertices = ax.transData.inverted().transform(display_vertices)
    finite = np.isfinite(data_vertices).all(axis=1)
    return data_vertices[finite]


@dataclass(frozen=True)
class _BoxCandidate:
    index: int
    x_left: float
    x_right: float
    x_center: float
    q1: float
    q3: float
    fill_color: str
    edge_color: str
    fill_alpha: float
    edge_width: float

    @property
    def width(self) -> float:
        return max(1e-12, self.x_right - self.x_left)


def _extract_box_candidates(ax: Any) -> list[_BoxCandidate]:
    x_min, x_max = ax.get_xlim()
    x_range = max(abs(float(x_max) - float(x_min)), 1e-12)
    candidates: list[_BoxCandidate] = []
    for patch in list(ax.patches):
        if not bool(patch.get_visible()):
            continue
        verts = _patch_vertices_in_data(ax, patch)
        if verts.shape[0] < 4:
            continue
        x_left = float(np.min(verts[:, 0]))
        x_right = float(np.max(verts[:, 0]))
        y_low = float(np.min(verts[:, 1]))
        y_high = float(np.max(verts[:, 1]))
        x_span = x_right - x_left
        y_span = y_high - y_low
        if x_span <= 0 or y_span <= 0:
            continue
        if x_span >= 0.8 * x_range:
            continue
        face = patch.get_facecolor()
        alpha = _to_float(patch.get_alpha())
        fill_alpha = float(alpha if alpha is not None else (face[3] if len(face) == 4 else 1.0))
        candidates.append(
            _BoxCandidate(
                index=len(candidates),
                x_left=x_left,
                x_right=x_right,
                x_center=float((x_left + x_right) / 2.0),
                q1=y_low,
                q3=y_high,
                fill_color=_to_hex(face, default="#56B4E9"),
                edge_color=_to_hex(patch.get_edgecolor(), default="#1f2937"),
                fill_alpha=fill_alpha,
                edge_width=float(patch.get_linewidth() or 1.0),
            )
        )
    candidates.sort(key=lambda item: item.x_center)
    return [dataclass_replace(candidate, index=index) for index, candidate in enumerate(candidates)]


def dataclass_replace(item: _BoxCandidate, *, index: int) -> _BoxCandidate:
    return _BoxCandidate(
        index=index,
        x_left=item.x_left,
        x_right=item.x_right,
        x_center=item.x_center,
        q1=item.q1,
        q3=item.q3,
        fill_color=item.fill_color,
        edge_color=item.edge_color,
        fill_alpha=item.fill_alpha,
        edge_width=item.edge_width,
    )


def _assign_box_index(candidates: list[_BoxCandidate], *, x_value: float) -> int | None:
    if not candidates:
        return None
    distances = [abs(candidate.x_center - x_value) for candidate in candidates]
    best_index = int(np.argmin(np.asarray(distances, dtype=float)))
    candidate = candidates[best_index]
    tolerance = max(candidate.width, 0.28)
    if abs(candidate.x_center - x_value) > tolerance:
        return None
    return candidate.index


def _extract_iqr_boxes(ax: Any) -> list[dict[str, Any]]:
    candidates = _extract_box_candidates(ax)
    if not candidates:
        return []

    tolerance = 1e-9
    box_rows = [
        {
            "position": float(candidate.x_center),
            "box_left": float(candidate.x_left),
            "box_right": float(candidate.x_right),
            "q1": float(candidate.q1),
            "median": None,
            "q3": float(candidate.q3),
            "whisker_low": None,
            "whisker_high": None,
            "outliers": [],
            "fill_color": candidate.fill_color,
            "fill_alpha": float(candidate.fill_alpha),
            "edge_color": candidate.edge_color,
            "edge_width": float(candidate.edge_width),
            "median_color": None,
        }
        for candidate in candidates
    ]

    for line in ax.lines:
        if not bool(line.get_visible()):
            continue
        data = _line_vertices_in_data(ax, line)
        if data.shape[0] == 0:
            continue
        marker = line.get_marker()
        linestyle = line.get_linestyle()

        if marker not in _NONE_MARKERS and linestyle in _NONE_LINESTYLES:
            for x_value, y_value in data:
                box_index = _assign_box_index(candidates, x_value=float(x_value))
                if box_index is None:
                    continue
                box_rows[box_index]["outliers"].append(float(y_value))
            continue

        x_values = data[:, 0]
        y_values = data[:, 1]
        x_span = float(np.max(x_values) - np.min(x_values))
        y_span = float(np.max(y_values) - np.min(y_values))
        line_color = _to_hex(line.get_color(), default="#E69F00")

        if y_span <= tolerance:
            y_value = float(np.mean(y_values))
            x_mid = float((np.min(x_values) + np.max(x_values)) / 2.0)
            box_index = _assign_box_index(candidates, x_value=x_mid)
            if box_index is None:
                continue
            box = box_rows[box_index]
            box_width = max(1e-12, float(box["box_right"]) - float(box["box_left"]))
            if float(box["q1"]) - tolerance <= y_value <= float(box["q3"]) + tolerance and x_span >= 0.55 * box_width:
                box["median"] = y_value
                box["median_color"] = line_color
            elif y_value < float(box["q1"]) - tolerance:
                current = _to_float(box["whisker_low"])
                box["whisker_low"] = y_value if current is None else min(current, y_value)
            elif y_value > float(box["q3"]) + tolerance:
                current = _to_float(box["whisker_high"])
                box["whisker_high"] = y_value if current is None else max(current, y_value)
            continue

        if x_span <= tolerance:
            x_value = float(np.mean(x_values))
            box_index = _assign_box_index(candidates, x_value=x_value)
            if box_index is None:
                continue
            box = box_rows[box_index]
            y_low = float(np.min(y_values))
            y_high = float(np.max(y_values))
            if y_high <= float(box["q1"]) + tolerance:
                current = _to_float(box["whisker_low"])
                box["whisker_low"] = y_low if current is None else min(current, y_low)
            elif y_low >= float(box["q3"]) - tolerance:
                current = _to_float(box["whisker_high"])
                box["whisker_high"] = y_high if current is None else max(current, y_high)

    for box in box_rows:
        if _to_float(box["median"]) is None:
            box["median"] = float((float(box["q1"]) + float(box["q3"])) / 2.0)
        if _to_float(box["whisker_low"]) is None:
            box["whisker_low"] = float(box["q1"])
        if _to_float(box["whisker_high"]) is None:
            box["whisker_high"] = float(box["q3"])
        box["outliers"] = sorted(float(value) for value in box["outliers"])
        if box["median_color"] is None:
            box["median_color"] = "#E69F00"

    return box_rows


def _extract_reference_bands(ax: Any) -> list[dict[str, Any]]:
    x_min, x_max = ax.get_xlim()
    x_range = max(abs(float(x_max) - float(x_min)), 1e-12)
    bands: list[dict[str, Any]] = []
    for patch in list(ax.patches):
        if not bool(patch.get_visible()):
            continue
        verts = _patch_vertices_in_data(ax, patch)
        if verts.shape[0] < 4:
            continue
        x_left = float(np.min(verts[:, 0]))
        x_right = float(np.max(verts[:, 0]))
        y_low = float(np.min(verts[:, 1]))
        y_high = float(np.max(verts[:, 1]))
        if y_high <= y_low:
            continue
        if (x_right - x_left) < 0.92 * x_range:
            continue
        face = patch.get_facecolor()
        alpha = _to_float(patch.get_alpha())
        resolved_alpha = float(alpha if alpha is not None else (face[3] if len(face) == 4 else 1.0))
        if resolved_alpha <= 0:
            continue
        bands.append(
            {
                "axis": "y",
                "start": y_low,
                "end": y_high,
                "color": _to_hex(face, default="#56B4E9"),
                "alpha": resolved_alpha,
            }
        )
    bands.sort(key=lambda item: (float(item["start"]), float(item["end"])))
    return bands


def _trend_points(ax: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for collection in list(ax.collections):
        if not isinstance(collection, PathCollection):
            continue
        if not bool(collection.get_visible()):
            continue
        offsets = np.asarray(collection.get_offsets(), dtype=float)
        if offsets.ndim != 2 or offsets.shape[1] != 2 or offsets.shape[0] == 0:
            continue
        sizes = np.asarray(collection.get_sizes(), dtype=float)
        facecolors = np.asarray(collection.get_facecolors(), dtype=float)
        collection_alpha = _to_float(collection.get_alpha())

        for index, (x_value, y_value) in enumerate(offsets):
            if not (math.isfinite(float(x_value)) and math.isfinite(float(y_value))):
                continue
            size_area = float(sizes[index if index < sizes.size else 0]) if sizes.size else 36.0
            marker_size = max(1.0, math.sqrt(max(size_area, 0.0)))
            if facecolors.size:
                color_row = facecolors[index if index < facecolors.shape[0] else 0]
                color = _to_hex(color_row, default="#0072B2")
                color_alpha = float(color_row[3]) if color_row.shape[0] >= 4 else 1.0
            else:
                color = "#0072B2"
                color_alpha = 1.0
            rows.append(
                {
                    "x": float(x_value),
                    "y": float(y_value),
                    "marker": "circle",
                    "size": float(marker_size),
                    "color": color,
                    "alpha": float(collection_alpha if collection_alpha is not None else color_alpha),
                }
            )
    rows.sort(key=lambda item: (float(item["x"]), float(item["y"])))
    return rows


def _canvas_payload(fig: Any) -> dict[str, int]:
    width_px, height_px = fig.canvas.get_width_height()
    return {
        "width_px": int(width_px),
        "height_px": int(height_px),
        "dpi": int(round(float(fig.dpi))),
    }


def _extract_iqr_geometry_from_artists(fig: Any, ax: Any) -> dict[str, Any]:
    """Return finalized IQR geometry extracted from rendered matplotlib artists."""

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    axes = _axes_payload(ax)
    legend = _legend_payload(fig, ax, renderer)
    boxes = _extract_iqr_boxes(ax)

    tick_lookup = {
        round(float(tick.get("value", 0.0)), 8): str(tick.get("label") or "")
        for tick in axes["x_ticks"]
        if str(tick.get("label") or "").strip()
    }
    for box in boxes:
        label = tick_lookup.get(round(float(box["position"]), 8), "")
        box["label"] = label

    return {
        "chart_type": "iqr",
        "canvas": _canvas_payload(fig),
        "title": _title_payload(fig, ax),
        "plot_area": _plot_rect(ax),
        "axes": axes,
        "legend": legend,
        "reference_bands": _extract_reference_bands(ax),
        "reference_lines": _extract_reference_lines(ax),
        "boxplots": boxes,
    }


def _extract_trend_geometry_from_artists(fig: Any, ax: Any) -> dict[str, Any]:
    """Return finalized trend geometry extracted from rendered matplotlib artists."""

    fig.canvas.draw()
    axes = _axes_payload(ax)
    return {
        "chart_type": "trend",
        "canvas": _canvas_payload(fig),
        "title": _title_payload(fig, ax),
        "plot_area": _plot_rect(ax),
        "axes": axes,
        "reference_lines": _extract_reference_lines(ax),
        "points": _trend_points(ax),
    }


def extract_iqr_geometry(fig: Any, ax: Any, *, payload: dict[str, Any]) -> dict[str, Any]:
    """Public IQR geometry extraction interface with payload-aware fallbacks."""

    resolved = _extract_iqr_geometry_from_artists(fig, ax)
    source_payload = payload if isinstance(payload, dict) else {}

    if not str((resolved.get("title") or {}).get("text") or "").strip() and str(source_payload.get("title") or "").strip():
        resolved["title"]["text"] = str(source_payload.get("title"))
    if not str((resolved.get("axes") or {}).get("x_label") or "").strip() and str(source_payload.get("x_label") or "").strip():
        resolved["axes"]["x_label"] = str(source_payload.get("x_label"))
    if not str((resolved.get("axes") or {}).get("y_label") or "").strip() and str(source_payload.get("y_label") or "").strip():
        resolved["axes"]["y_label"] = str(source_payload.get("y_label"))

    labels = [str(item) for item in source_payload.get("labels") or []]
    boxplots = list(resolved.get("boxplots") or [])
    for index, box in enumerate(boxplots):
        if str(box.get("label") or "").strip():
            continue
        if index < len(labels):
            box["label"] = labels[index]
    resolved["boxplots"] = boxplots
    resolved["source"] = "matplotlib_finalized"
    return resolved


def extract_trend_geometry(fig: Any, ax: Any, *, payload: dict[str, Any]) -> dict[str, Any]:
    """Public trend geometry extraction interface with payload-aware fallbacks."""

    resolved = _extract_trend_geometry_from_artists(fig, ax)
    source_payload = payload if isinstance(payload, dict) else {}

    if not str((resolved.get("title") or {}).get("text") or "").strip() and str(source_payload.get("title") or "").strip():
        resolved["title"]["text"] = str(source_payload.get("title"))
    if not str((resolved.get("axes") or {}).get("x_label") or "").strip() and str(source_payload.get("x_label") or "").strip():
        resolved["axes"]["x_label"] = str(source_payload.get("x_label"))
    if not str((resolved.get("axes") or {}).get("y_label") or "").strip() and str(source_payload.get("y_label") or "").strip():
        resolved["axes"]["y_label"] = str(source_payload.get("y_label"))

    if not list(resolved.get("points") or []):
        x_values = [item for item in source_payload.get("x_values") or [] if _to_float(item) is not None]
        y_values = [item for item in source_payload.get("y_values") or [] if _to_float(item) is not None]
        resolved["points"] = [
            {
                "x": float(x_value),
                "y": float(y_value),
                "marker": "circle",
                "size": 5.0,
                "color": "#0072B2",
                "alpha": 1.0,
            }
            for x_value, y_value in zip(x_values, y_values)
        ]
    resolved["source"] = "matplotlib_finalized"
    return resolved


def extract_iqr_matplotlib_geometry(fig: Any, ax: Any) -> dict[str, Any]:
    """Backward-compatible alias for caller migration."""

    return _extract_iqr_geometry_from_artists(fig, ax)


def extract_trend_matplotlib_geometry(fig: Any, ax: Any) -> dict[str, Any]:
    """Backward-compatible alias for caller migration."""

    return _extract_trend_geometry_from_artists(fig, ax)

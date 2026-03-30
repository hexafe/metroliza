"""Shared resolved chart render specifications.

This module starts with histogram rendering because that chart has the largest
parity gap between matplotlib and the native compositor. The intent is to let
renderers consume a resolved layout/primitive specification rather than
recomputing layout heuristics independently.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import textwrap
from typing import Any, Iterable, Mapping

import numpy as np

from modules.export_histogram_layout import compute_histogram_plot_with_right_info_layout
from modules.export_summary_utils import prepare_categorical_x_axis
from modules.export_summary_sheet_planner import (
    build_histogram_annotation_specs as _build_histogram_annotation_specs,
    compute_histogram_annotation_rows as _compute_histogram_annotation_rows,
)
from modules.export_workbook_planning_helpers import compute_histogram_font_sizes
from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE


DEFAULT_DPI = 150
DEFAULT_WIDTH_PX = 1320
DEFAULT_HEIGHT_PX = 600
_HISTOGRAM_X_MARGIN_RATIO = 0.10


@dataclass(frozen=True)
class RectSpec:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class TickSpec:
    position: float
    label: str


@dataclass(frozen=True)
class TitleSpec:
    text: str
    x: float
    y: float
    font_size: float
    color: str
    bold: bool = True
    ha: str = "left"
    va: str = "top"


@dataclass(frozen=True)
class HistogramBarSpec:
    left_edge: float
    right_edge: float
    count: float
    fill_color: str
    fill_alpha: float
    edge_color: str
    edge_alpha: float
    edge_width: int


@dataclass(frozen=True)
class HistogramLineSpec:
    value: float
    color: str
    alpha: float
    width: int
    dash: tuple[int, int] | None = None
    y0_axes: float = 0.0
    y1_axes: float = 1.0


@dataclass(frozen=True)
class HistogramCurveSpec:
    kind: str
    x_values: list[float]
    y_values: list[float]
    color: str
    alpha: float
    width: int
    dash: tuple[int, int] | None = None
    fill_to_baseline: bool = False
    fill_color: str | None = None
    fill_alpha: float = 0.0


@dataclass(frozen=True)
class HistogramAnnotationSpec:
    text: str
    x_value: float
    row_index: int
    box_y: float
    leader_y: float
    color: str
    align: str = "center"


@dataclass(frozen=True)
class HistogramTableRowSpec:
    label: str
    value: str
    row_kind: str = "summary_metric"
    badge_palette: str | None = None
    section_break_before: bool = False


@dataclass(frozen=True)
class HistogramTableSpec:
    title: str
    rows: list[HistogramTableRowSpec]


@dataclass(frozen=True)
class HistogramNoteSpec:
    text: str
    x: float
    y: float
    align: str = "left"
    font_size: float = 9.0
    color: str = "#4d5968"


@dataclass(frozen=True)
class ResolvedHistogramSpec:
    canvas_width_px: int
    canvas_height_px: int
    dpi: int
    title: TitleSpec
    plot_rect: RectSpec
    table_rect: RectSpec | None
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    x_ticks: list[TickSpec]
    y_ticks: list[TickSpec]
    x_label: str
    y_label: str
    grid_axis: str
    bars: list[HistogramBarSpec]
    mean_line: HistogramLineSpec | None
    specification_lines: list[HistogramLineSpec]
    overlay_curves: list[HistogramCurveSpec]
    annotations: list[HistogramAnnotationSpec]
    table: HistogramTableSpec | None
    note: HistogramNoteSpec | None = None


def _as_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _finite_array(values: Iterable[Any]) -> np.ndarray:
    arr = np.asarray(list(values), dtype=float)
    return arr[np.isfinite(arr)]


def _canvas_size(payload: Mapping[str, Any]) -> tuple[int, int, int]:
    canvas = payload.get("canvas")
    if isinstance(canvas, Mapping):
        width = max(int(canvas.get("width_px") or DEFAULT_WIDTH_PX), 400)
        height = max(int(canvas.get("height_px") or DEFAULT_HEIGHT_PX), 260)
        dpi = max(int(canvas.get("dpi") or DEFAULT_DPI), 72)
        return width, height, dpi
    return DEFAULT_WIDTH_PX, DEFAULT_HEIGHT_PX, DEFAULT_DPI


def _line_ticks(min_value: float, max_value: float, *, count: int = 5) -> list[float]:
    if not math.isfinite(min_value) or not math.isfinite(max_value):
        return [0.0, 1.0]
    if math.isclose(min_value, max_value):
        return [min_value]
    return [min_value + ((max_value - min_value) * idx / max(1, count - 1)) for idx in range(count)]


def _format_tick(value: float) -> str:
    numeric = float(value)
    if abs(numeric) >= 100 or math.isclose(numeric, round(numeric), abs_tol=1e-9):
        return f"{numeric:.0f}"
    if abs(numeric) >= 10:
        return f"{numeric:.1f}"
    return f"{numeric:.3f}".rstrip("0").rstrip(".")


def build_wrapped_chart_title(title: str, *, width: int = 42, max_lines: int = 3) -> str:
    """Wrap long chart titles so renderers can reserve a stable top band."""

    safe_title = str(title or "").strip()
    if not safe_title:
        return ""

    wrapped_lines = textwrap.wrap(
        safe_title,
        width=max(20, int(width)),
        break_long_words=False,
        break_on_hyphens=False,
    )
    if len(wrapped_lines) > max_lines:
        wrapped_lines = wrapped_lines[:max_lines]
        wrapped_lines[-1] = wrapped_lines[-1].rstrip(" .") + "…"
    return "\n".join(wrapped_lines)


def build_histogram_mean_line_style() -> dict[str, Any]:
    """Return the canonical histogram mean-line style contract."""

    return {
        "color": SUMMARY_PLOT_PALETTE["central_tendency"],
        "linestyle": "--",
        "linewidth": 1.3,
        "alpha": 0.48,
        "zorder": 2,
    }


def resolve_histogram_x_view(
    values: Iterable[Any],
    *,
    lsl: float | None = None,
    usl: float | None = None,
    mean_value: float | None = None,
    margin_ratio: float = _HISTOGRAM_X_MARGIN_RATIO,
) -> dict[str, float | str]:
    """Resolve histogram x framing with local span and a safety margin."""

    finite_values = _finite_array(values)
    if finite_values.size == 0:
        return {"x_min": 0.0, "x_max": 1.0, "mode": "full"}

    data_min = float(np.min(finite_values))
    data_max = float(np.max(finite_values))
    left_limit = _as_float(lsl)
    right_limit = _as_float(usl)

    left_ref = data_min if left_limit is None else min(data_min, left_limit)
    right_ref = data_max if right_limit is None else max(data_max, right_limit)

    data_span = max(data_max - data_min, 0.0)
    if left_limit is not None and right_limit is not None:
        spec_span = max(right_limit - left_limit, 0.0)
    else:
        spec_span = max(right_ref - left_ref, 0.0)

    mean_magnitude = 0.0
    numeric_mean = _as_float(mean_value)
    if numeric_mean is not None:
        mean_magnitude = abs(numeric_mean)
    ref_magnitude = max(mean_magnitude, abs(data_min), abs(data_max), 1.0)
    fallback_span = max(1e-6, 1e-4 * ref_magnitude)
    effective_span = max(data_span, spec_span, fallback_span)
    margin = effective_span * max(0.0, float(margin_ratio))

    return {
        "x_min": left_ref - margin,
        "x_max": right_ref + margin,
        "mode": "full",
    }


def _normalize_table_rows(rows: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, Mapping):
            normalized.append(dict(row))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            normalized.append({"label": str(row[0]), "value": str(row[1])})
    return normalized


def _format_histogram_stat_value(value: Any, *, decimals: int = 3) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "N/A"
    if math.isclose(numeric, round(numeric), abs_tol=1e-9):
        return f"{numeric:.0f}"
    return f"{numeric:.{decimals}f}"


def _fallback_histogram_table_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    rows: list[dict[str, Any]] = []
    for label, key, decimals in (
        ("Min", "min", 3),
        ("Max", "max", 3),
        ("Mean", "mean", 3),
        ("Std Dev", "std", 3),
    ):
        if _as_float(summary.get(key)) is not None:
            rows.append({"label": label, "value": _format_histogram_stat_value(summary.get(key), decimals=decimals)})
    count_value = _as_float(summary.get("count"))
    if count_value is not None:
        rows.append({"label": "Samples", "value": _format_histogram_stat_value(count_value, decimals=0)})
    return rows


def _fallback_histogram_specification_lines(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    limits = payload.get("limits") if isinstance(payload.get("limits"), Mapping) else {}
    resolved = []
    for role, label, value in (
        ("lsl", "LSL", limits.get("lsl", payload.get("lsl"))),
        ("usl", "USL", limits.get("usl", payload.get("usl"))),
        ("nominal", "Nominal", limits.get("nominal")),
    ):
        numeric = _as_float(value)
        resolved.append(
            {
                "id": role,
                "label": label,
                "value": numeric,
                "enabled": numeric is not None,
            }
        )
    return resolved


def _fallback_histogram_annotation_rows(payload: Mapping[str, Any], *, x_min: float, x_max: float) -> list[dict[str, Any]]:
    mean_value = _as_float(((payload.get("mean_line") or {}) if isinstance(payload.get("mean_line"), Mapping) else {}).get("value"))
    limits = payload.get("limits") if isinstance(payload.get("limits"), Mapping) else {}
    lsl = _as_float(limits.get("lsl", payload.get("lsl")))
    usl = _as_float(limits.get("usl", payload.get("usl")))

    available = [item for item in (mean_value, lsl, usl) if item is not None]
    if not available:
        return []

    if mean_value is not None and lsl is not None and usl is not None:
        x_span = max(abs(float(x_max) - float(x_min)), 1e-12)
        annotation_specs = _build_histogram_annotation_specs(mean_value, usl, lsl, 1.0)
        resolved_specs, _ = _compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.04,
            threshold_mode="axis_fraction",
            x_span=x_span,
            base_text_y_axes=1.01,
            row_step=0.025,
        )
        return [
            {
                "label": spec.get("label"),
                "text": spec.get("text"),
                "kind": spec.get("kind"),
                "color": spec.get("color"),
                "x": spec.get("x"),
                "row_index": spec.get("row_index"),
                "placement_hint": {
                    "textcoords": spec.get("textcoords", "data"),
                    "va": spec.get("va", "bottom"),
                    "ha": spec.get("ha", "center"),
                },
            }
            for spec in resolved_specs
        ]

    fallback_annotations: list[dict[str, Any]] = []
    for row_index, (kind, label, value, color) in enumerate(
        (
            ("mean", "Mean", mean_value, SUMMARY_PLOT_PALETTE["annotation_text"]),
            ("usl", "USL", usl, SUMMARY_PLOT_PALETTE["spec_limit"]),
            ("lsl", "LSL", lsl, SUMMARY_PLOT_PALETTE["spec_limit"]),
        )
    ):
        if value is None:
            continue
        text = f"{label}={value:.3f}" if kind != "mean" else f"Mean = {value:.3f}"
        fallback_annotations.append(
            {
                "label": label,
                "text": text,
                "kind": kind,
                "color": color,
                "x": value,
                "row_index": row_index,
                "placement_hint": {"textcoords": "data", "va": "bottom", "ha": "center"},
            }
        )
    return fallback_annotations


def _resolve_histogram_visual_metadata(
    payload: Mapping[str, Any],
    *,
    x_min: float,
    x_max: float,
) -> tuple[dict[str, Any], bool]:
    visual_metadata = payload.get("visual_metadata") if isinstance(payload.get("visual_metadata"), Mapping) else {}
    nested_table = visual_metadata.get("summary_stats_table") if isinstance(visual_metadata.get("summary_stats_table"), Mapping) else {}
    nested_overlays = visual_metadata.get("modeled_overlays") if isinstance(visual_metadata.get("modeled_overlays"), Mapping) else {}

    table_rows = _normalize_table_rows(
        list(nested_table.get("rows") or [])
        or list(payload.get("summary_table_rows") or [])
        or _fallback_histogram_table_rows(payload)
    )
    annotation_rows = list(visual_metadata.get("annotation_rows") or []) or list(payload.get("annotation_rows") or [])
    if not annotation_rows:
        annotation_rows = _fallback_histogram_annotation_rows(payload, x_min=x_min, x_max=x_max)
    specification_lines = list(visual_metadata.get("specification_lines") or []) or list(payload.get("specification_lines") or [])
    if not specification_lines:
        specification_lines = _fallback_histogram_specification_lines(payload)
    overlay_rows = list(nested_overlays.get("rows") or []) or list(payload.get("modeled_overlay_rows") or [])

    resolved_visual_metadata = {
        "specification_lines": specification_lines,
        "summary_stats_table": {
            "title": str(nested_table.get("title") or payload.get("summary_table_title") or "Parameter"),
            "columns": list(nested_table.get("columns") or ["Parameter", "Value"]),
            "rows": table_rows,
        },
        "annotation_rows": annotation_rows,
        "modeled_overlays": {
            "advanced_annotations_enabled": bool(nested_overlays.get("advanced_annotations_enabled", bool(overlay_rows))),
            "overlays_enabled": bool(nested_overlays.get("overlays_enabled", bool(overlay_rows))),
            "rows": overlay_rows,
        },
    }
    compact_mode = bool(payload.get("compact_render")) or str(payload.get("render_variant") or "").strip().lower() == "compact"
    return resolved_visual_metadata, compact_mode


def _mapping_to_rect(rect: Mapping[str, Any]) -> RectSpec:
    return RectSpec(
        x=float(rect.get("x") or 0.0),
        y=float(rect.get("y") or 0.0),
        width=float(rect.get("width") or 0.0),
        height=float(rect.get("height") or 0.0),
    )


def _normalize_dash(raw_dash: Any) -> tuple[int, int] | None:
    if not raw_dash:
        return None
    if isinstance(raw_dash, (list, tuple)) and len(raw_dash) >= 2:
        return (max(1, int(raw_dash[0])), max(1, int(raw_dash[1])))
    return None


def build_resolved_histogram_spec(payload: Mapping[str, Any]) -> ResolvedHistogramSpec:
    values = _finite_array(payload.get("values") or [])
    if values.size == 0:
        raise RuntimeError("histogram payload requires finite values")

    width_px, height_px, dpi = _canvas_size(payload)
    x_view = payload.get("x_view") if isinstance(payload.get("x_view"), Mapping) else {}
    x_min = _as_float(x_view.get("min"))
    x_max = _as_float(x_view.get("max"))
    if x_min is None:
        x_min = float(np.min(values))
    if x_max is None:
        x_max = float(np.max(values))
    if math.isclose(x_min, x_max):
        x_min -= 0.5
        x_max += 0.5

    bin_count = max(1, int(payload.get("bin_count") or 20))
    counts, edges = np.histogram(values, bins=bin_count, range=(x_min, x_max))

    visual_metadata, compact_mode = _resolve_histogram_visual_metadata(payload, x_min=x_min, x_max=x_max)
    table_rows = _normalize_table_rows(list(((visual_metadata.get("summary_stats_table") or {}).get("rows") or [])))
    figure_size = (width_px / float(dpi), height_px / float(dpi))
    font_sizes = compute_histogram_font_sizes(figure_size, has_table=not compact_mode)
    panel_rects = compute_histogram_plot_with_right_info_layout(
        figure_size,
        table_fontsize=font_sizes["table_fontsize"],
        fit_row_count=0,
        stats_row_count=len(table_rows),
        fit_rows=[],
        stats_rows=[(str(row.get("label") or ""), str(row.get("value") or "")) for row in table_rows],
        note_line_count=0,
        right_container_width_hint=0.34,
        dpi=float(dpi),
    )
    plot_rect = _mapping_to_rect(panel_rects["plot_rect"])
    table_rect = None if compact_mode else _mapping_to_rect(panel_rects["right_container_rect"])

    overlay_rows = list(((visual_metadata.get("modeled_overlays") or {}).get("rows") or []))
    max_count = float(max(1, int(np.max(counts)) if counts.size else 1))
    for overlay in overlay_rows:
        if str(overlay.get("kind") or "").strip().lower() != "curve":
            continue
        curve_y = _finite_array(overlay.get("y") or [])
        if curve_y.size:
            max_count = max(max_count, float(np.max(curve_y)))
    max_count *= 1.08

    x_ticks = [TickSpec(position=tick, label=_format_tick(tick)) for tick in _line_ticks(x_min, x_max, count=6)]
    y_ticks = [TickSpec(position=tick, label=_format_tick(tick)) for tick in _line_ticks(0.0, max_count, count=5)]

    bars = [
        HistogramBarSpec(
            left_edge=float(left_edge),
            right_edge=float(right_edge),
            count=float(count),
            fill_color=SUMMARY_PLOT_PALETTE["distribution_base"],
            fill_alpha=0.84,
            edge_color="#ffffff",
            edge_alpha=0.72,
            edge_width=1,
        )
        for left_edge, right_edge, count in zip(edges[:-1], edges[1:], counts)
        if count > 0
    ]

    mean_line = None
    mean_meta = payload.get("mean_line") if isinstance(payload.get("mean_line"), Mapping) else {}
    mean_value = _as_float(mean_meta.get("value"))
    if mean_value is not None:
        mean_line = HistogramLineSpec(
            value=float(mean_value),
            color=str(mean_meta.get("color") or SUMMARY_PLOT_PALETTE["central_tendency"]),
            alpha=float(mean_meta.get("alpha") or 0.48),
            width=max(1, int(round(float(mean_meta.get("linewidth") or 1.3)))),
            dash=(8, 5),
        )

    specification_lines = [
        HistogramLineSpec(
            value=float(line_value),
            color=SUMMARY_PLOT_PALETTE["spec_limit"],
            alpha=0.82,
            width=2,
            y0_axes=0.0,
            y1_axes=1.0,
        )
        for line_meta in list(visual_metadata.get("specification_lines") or [])
        if isinstance(line_meta, Mapping)
        and bool(line_meta.get("enabled"))
        and (line_value := _as_float(line_meta.get("value"))) is not None
    ]

    overlay_curves: list[HistogramCurveSpec] = []
    note = None
    for overlay in overlay_rows:
        kind = str(overlay.get("kind") or "").strip().lower()
        if kind == "curve_note":
            note = HistogramNoteSpec(
                text=str(overlay.get("label") or ""),
                x=plot_rect.x + 0.012,
                y=plot_rect.y + 0.028,
            )
            continue
        x_values = _finite_array(overlay.get("x") or [])
        y_values = _finite_array(overlay.get("y") or [])
        if x_values.size == 0 or y_values.size == 0 or x_values.size != y_values.size:
            continue
        overlay_curves.append(
            HistogramCurveSpec(
                kind=kind or "curve",
                x_values=[float(item) for item in x_values.tolist()],
                y_values=[float(item) for item in y_values.tolist()],
                color=str(overlay.get("color") or SUMMARY_PLOT_PALETTE["density_line"]),
                alpha=float(overlay.get("alpha") or 1.0),
                width=max(1, int(round(float(overlay.get("linewidth") or 1.0)))),
                dash=_normalize_dash(overlay.get("dash")),
                fill_to_baseline=bool(overlay.get("fill_to_baseline")),
                fill_color=str(overlay.get("fill_color") or overlay.get("color") or SUMMARY_PLOT_PALETTE["spec_limit"])
                if bool(overlay.get("fill_to_baseline"))
                else None,
                fill_alpha=float(overlay.get("fill_alpha") or 0.0),
            )
        )

    annotations = [
        HistogramAnnotationSpec(
            text=str(annotation.get("text") or annotation.get("label") or ""),
            x_value=float(x_value),
            row_index=int(annotation.get("row_index") or 0),
            box_y=float(
                plot_rect.y + (
                    float(annotation.get("text_y_axes"))
                    if _as_float(annotation.get("text_y_axes")) is not None
                    else (1.01 + (int(annotation.get("row_index") or 0) * 0.045))
                ) * plot_rect.height
            ),
            leader_y=float((plot_rect.y + plot_rect.height) - (4.0 / max(height_px, 1))),
            color=str(
                annotation.get("color")
                or (
                    SUMMARY_PLOT_PALETTE["spec_limit"]
                    if str(annotation.get("kind") or "").strip().lower() in {"lsl", "usl"}
                    else SUMMARY_PLOT_PALETTE["annotation_text"]
                )
            ),
            align=str(((annotation.get("placement_hint") or {}) if isinstance(annotation.get("placement_hint"), Mapping) else {}).get("ha") or "center"),
        )
        for annotation in list(visual_metadata.get("annotation_rows") or [])
        if isinstance(annotation, Mapping)
        and (x_value := _as_float(annotation.get("x"))) is not None
        and str(annotation.get("text") or annotation.get("label") or "").strip()
    ]

    table = None
    if table_rect is not None:
        table = HistogramTableSpec(
            title=str(((visual_metadata.get("summary_stats_table") or {}).get("title")) or "Parameter"),
            rows=[
                HistogramTableRowSpec(
                    label=str(row.get("label") or ""),
                    value=str(row.get("value") or ""),
                    row_kind=str(row.get("row_kind") or "summary_metric"),
                    badge_palette=str(row.get("badge_palette") or "") or None,
                    section_break_before=bool(row.get("section_break_before")),
                )
                for row in table_rows
            ],
        )

    style = payload.get("style") if isinstance(payload.get("style"), Mapping) else {}
    title = TitleSpec(
        text=str(payload.get("title") or ""),
        x=0.06,
        y=0.985,
        font_size=max(float(font_sizes["annotation_fontsize"]) + 1.1, 8.8),
        color=SUMMARY_PLOT_PALETTE["distribution_foreground"],
    )
    return ResolvedHistogramSpec(
        canvas_width_px=width_px,
        canvas_height_px=height_px,
        dpi=dpi,
        title=title,
        plot_rect=plot_rect,
        table_rect=table_rect,
        x_min=float(x_min),
        x_max=float(x_max),
        y_min=0.0,
        y_max=float(max_count),
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_label=str(style.get("axis_label_x") or "Measurement"),
        y_label=str(style.get("axis_label_y") or "Count"),
        grid_axis=str(style.get("grid_axis") or "y"),
        bars=bars,
        mean_line=mean_line,
        specification_lines=specification_lines,
        overlay_curves=overlay_curves,
        annotations=annotations,
        table=table,
        note=note,
    )


def histogram_spec_to_mapping(spec: ResolvedHistogramSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chart_type": "histogram",
        "canvas": {
            "width_px": spec.canvas_width_px,
            "height_px": spec.canvas_height_px,
            "dpi": spec.dpi,
        },
        "title": {
            "text": spec.title.text,
            "anchor": {
                "x": spec.title.x,
                "y": spec.title.y,
            },
            "font": {
                "size": spec.title.font_size,
                "weight": "bold" if spec.title.bold else "normal",
            },
            "color": spec.title.color,
        },
        "plot_area": {
            "x": spec.plot_rect.x,
            "y": spec.plot_rect.y,
            "width": spec.plot_rect.width,
            "height": spec.plot_rect.height,
        },
        "plot_rect": {
            "x": spec.plot_rect.x,
            "y": spec.plot_rect.y,
            "width": spec.plot_rect.width,
            "height": spec.plot_rect.height,
        },
        "axes": {
            "x_limits": {"min": spec.x_min, "max": spec.x_max},
            "y_limits": {"min": spec.y_min, "max": spec.y_max},
            "x_ticks": [{"value": tick.position, "label": tick.label} for tick in spec.x_ticks],
            "y_ticks": [{"value": tick.position, "label": tick.label} for tick in spec.y_ticks],
            "x_label": spec.x_label,
            "y_label": spec.y_label,
            "grid_axis": spec.grid_axis,
        },
        "x_ticks": [{"position": tick.position, "label": tick.label} for tick in spec.x_ticks],
        "y_ticks": [{"position": tick.position, "label": tick.label} for tick in spec.y_ticks],
        "x_label": spec.x_label,
        "y_label": spec.y_label,
        "grid_axis": spec.grid_axis,
        "x_min": spec.x_min,
        "x_max": spec.x_max,
        "y_min": spec.y_min,
        "y_max": spec.y_max,
        "annotations": [
            {
                "text": item.text,
                "x_value": item.x_value,
                "row_index": item.row_index,
                "box_y": item.box_y,
                "leader_y": item.leader_y,
                "color": item.color,
                "align": item.align,
            }
            for item in spec.annotations
        ],
        "bars": [
            {
                "left_edge": item.left_edge,
                "right_edge": item.right_edge,
                "count": item.count,
                "fill_color": item.fill_color,
                "fill_alpha": item.fill_alpha,
                "edge_color": item.edge_color,
                "edge_alpha": item.edge_alpha,
                "edge_width": item.edge_width,
            }
            for item in spec.bars
        ],
        "overlays": [
            {
                "kind": item.kind,
                "x_values": list(item.x_values),
                "y_values": list(item.y_values),
                "color": item.color,
                "alpha": item.alpha,
                "width": item.width,
                "dash": list(item.dash) if item.dash is not None else None,
                "fill_to_baseline": item.fill_to_baseline,
                "fill_color": item.fill_color,
                "fill_alpha": item.fill_alpha,
            }
            for item in spec.overlay_curves
        ],
        "lines": {
            "mean": (
                {
                    "value": spec.mean_line.value,
                    "color": spec.mean_line.color,
                    "alpha": spec.mean_line.alpha,
                    "width": spec.mean_line.width,
                    "dash": list(spec.mean_line.dash) if spec.mean_line.dash is not None else None,
                    "y0_axes": spec.mean_line.y0_axes,
                    "y1_axes": spec.mean_line.y1_axes,
                }
                if spec.mean_line is not None
                else None
            ),
            "specification": [
                {
                    "value": item.value,
                    "color": item.color,
                    "alpha": item.alpha,
                    "width": item.width,
                    "dash": list(item.dash) if item.dash is not None else None,
                    "y0_axes": item.y0_axes,
                    "y1_axes": item.y1_axes,
                }
                for item in spec.specification_lines
            ],
        },
    }
    if spec.table_rect is not None:
        payload["side_panels"] = {
            "right_info": {
                "x": spec.table_rect.x,
                "y": spec.table_rect.y,
                "width": spec.table_rect.width,
                "height": spec.table_rect.height,
            }
        }
        payload["table_rect"] = {
            "x": spec.table_rect.x,
            "y": spec.table_rect.y,
            "width": spec.table_rect.width,
            "height": spec.table_rect.height,
        }
    if spec.table is not None:
        payload["table"] = {
            "title": spec.table.title,
            "rows": [
                {
                    "label": row.label,
                    "value": row.value,
                    "row_kind": row.row_kind,
                    "badge_palette": row.badge_palette,
                    "section_break_before": row.section_break_before,
                }
                for row in spec.table.rows
            ],
        }
    if spec.note is not None:
        payload["note"] = {
            "text": spec.note.text,
            "x": spec.note.x,
            "y": spec.note.y,
            "align": spec.note.align,
            "font_size": spec.note.font_size,
            "color": spec.note.color,
        }
    if spec.mean_line is not None:
        payload["mean_line"] = dict(payload["lines"]["mean"])
    payload["specification_lines"] = list(payload["lines"]["specification"])
    return payload


def histogram_spec_from_mapping(payload: Mapping[str, Any]) -> ResolvedHistogramSpec:
    title_payload = payload.get("title") if isinstance(payload.get("title"), Mapping) else {}
    axes_payload = payload.get("axes") if isinstance(payload.get("axes"), Mapping) else {}
    side_panels_payload = payload.get("side_panels") if isinstance(payload.get("side_panels"), Mapping) else {}
    lines_payload = payload.get("lines") if isinstance(payload.get("lines"), Mapping) else {}
    mean_payload = lines_payload.get("mean") if isinstance(lines_payload.get("mean"), Mapping) else None
    table_payload = payload.get("table") if isinstance(payload.get("table"), Mapping) else None
    note_payload = payload.get("note") if isinstance(payload.get("note"), Mapping) else None

    return ResolvedHistogramSpec(
        canvas_width_px=int(((payload.get("canvas") or {}) if isinstance(payload.get("canvas"), Mapping) else {}).get("width_px") or DEFAULT_WIDTH_PX),
        canvas_height_px=int(((payload.get("canvas") or {}) if isinstance(payload.get("canvas"), Mapping) else {}).get("height_px") or DEFAULT_HEIGHT_PX),
        dpi=int(((payload.get("canvas") or {}) if isinstance(payload.get("canvas"), Mapping) else {}).get("dpi") or DEFAULT_DPI),
        title=TitleSpec(
            text=str(title_payload.get("text") or ""),
            x=float(((title_payload.get("anchor") or {}) if isinstance(title_payload.get("anchor"), Mapping) else {}).get("x") or 0.0),
            y=float(((title_payload.get("anchor") or {}) if isinstance(title_payload.get("anchor"), Mapping) else {}).get("y") or 0.0),
            font_size=float(((title_payload.get("font") or {}) if isinstance(title_payload.get("font"), Mapping) else {}).get("size") or 15.0),
            color=str(title_payload.get("color") or SUMMARY_PLOT_PALETTE["distribution_foreground"]),
            bold=str(((title_payload.get("font") or {}) if isinstance(title_payload.get("font"), Mapping) else {}).get("weight") or "bold").lower() == "bold",
            ha=str(title_payload.get("ha") or "left"),
            va=str(title_payload.get("va") or "top"),
        ),
        plot_rect=_mapping_to_rect(payload.get("plot_area") or {}),
        table_rect=_mapping_to_rect(side_panels_payload.get("right_info") or {}) if isinstance(side_panels_payload.get("right_info"), Mapping) else None,
        x_min=float(((axes_payload.get("x_limits") or {}) if isinstance(axes_payload.get("x_limits"), Mapping) else {}).get("min") or 0.0),
        x_max=float(((axes_payload.get("x_limits") or {}) if isinstance(axes_payload.get("x_limits"), Mapping) else {}).get("max") or 1.0),
        y_min=float(((axes_payload.get("y_limits") or {}) if isinstance(axes_payload.get("y_limits"), Mapping) else {}).get("min") or 0.0),
        y_max=float(((axes_payload.get("y_limits") or {}) if isinstance(axes_payload.get("y_limits"), Mapping) else {}).get("max") or 1.0),
        x_ticks=[
            TickSpec(position=float(item.get("value") or 0.0), label=str(item.get("label") or ""))
            for item in list(axes_payload.get("x_ticks") or [])
            if isinstance(item, Mapping)
        ],
        y_ticks=[
            TickSpec(position=float(item.get("value") or 0.0), label=str(item.get("label") or ""))
            for item in list(axes_payload.get("y_ticks") or [])
            if isinstance(item, Mapping)
        ],
        x_label=str(axes_payload.get("x_label") or "Measurement"),
        y_label=str(axes_payload.get("y_label") or "Count"),
        grid_axis=str(axes_payload.get("grid_axis") or "y"),
        bars=[
            HistogramBarSpec(
                left_edge=float(item.get("left_edge") or 0.0),
                right_edge=float(item.get("right_edge") or 0.0),
                count=float(item.get("count") or 0.0),
                fill_color=str(item.get("fill_color") or SUMMARY_PLOT_PALETTE["distribution_base"]),
                fill_alpha=float(item.get("fill_alpha") or 0.84),
                edge_color=str(item.get("edge_color") or "#ffffff"),
                edge_alpha=float(item.get("edge_alpha") or 0.72),
                edge_width=max(1, int(item.get("edge_width") or 1)),
            )
            for item in list(payload.get("bars") or [])
            if isinstance(item, Mapping)
        ],
        mean_line=(
            HistogramLineSpec(
                value=float(mean_payload.get("value") or 0.0),
                color=str(mean_payload.get("color") or SUMMARY_PLOT_PALETTE["central_tendency"]),
                alpha=float(mean_payload.get("alpha") or 0.48),
                width=max(1, int(mean_payload.get("width") or 1)),
                dash=_normalize_dash(mean_payload.get("dash")),
                y0_axes=float(mean_payload.get("y0_axes") or 0.0),
                y1_axes=float(mean_payload.get("y1_axes") or 1.0),
            )
            if mean_payload is not None
            else None
        ),
        specification_lines=[
            HistogramLineSpec(
                value=float(item.get("value") or 0.0),
                color=str(item.get("color") or SUMMARY_PLOT_PALETTE["spec_limit"]),
                alpha=float(item.get("alpha") or 0.82),
                width=max(1, int(item.get("width") or 2)),
                dash=_normalize_dash(item.get("dash")),
                y0_axes=float(item.get("y0_axes") or 0.0),
                y1_axes=float(item.get("y1_axes") or 1.0),
            )
            for item in list(lines_payload.get("specification") or [])
            if isinstance(item, Mapping)
        ],
        overlay_curves=[
            HistogramCurveSpec(
                kind=str(item.get("kind") or "curve"),
                x_values=[float(value) for value in list(item.get("x_values") or [])],
                y_values=[float(value) for value in list(item.get("y_values") or [])],
                color=str(item.get("color") or SUMMARY_PLOT_PALETTE["density_line"]),
                alpha=float(item.get("alpha") or 1.0),
                width=max(1, int(item.get("width") or 1)),
                dash=_normalize_dash(item.get("dash")),
                fill_to_baseline=bool(item.get("fill_to_baseline")),
                fill_color=str(item.get("fill_color") or "") or None,
                fill_alpha=float(item.get("fill_alpha") or 0.0),
            )
            for item in list(payload.get("overlays") or [])
            if isinstance(item, Mapping)
        ],
        annotations=[
            HistogramAnnotationSpec(
                text=str(item.get("text") or ""),
                x_value=float(item.get("x_value") or 0.0),
                row_index=int(item.get("row_index") or 0),
                box_y=float(item.get("box_y") or 0.0),
                leader_y=float(item.get("leader_y") or 0.0),
                color=str(item.get("color") or SUMMARY_PLOT_PALETTE["annotation_text"]),
                align=str(item.get("align") or "center"),
            )
            for item in list(payload.get("annotations") or [])
            if isinstance(item, Mapping)
        ],
        table=(
            HistogramTableSpec(
                title=str(table_payload.get("title") or "Parameter"),
                rows=[
                    HistogramTableRowSpec(
                        label=str(item.get("label") or ""),
                        value=str(item.get("value") or ""),
                        row_kind=str(item.get("row_kind") or "summary_metric"),
                        badge_palette=str(item.get("badge_palette") or "") or None,
                        section_break_before=bool(item.get("section_break_before")),
                    )
                    for item in list(table_payload.get("rows") or [])
                    if isinstance(item, Mapping)
                ],
            )
            if table_payload is not None
            else None
        ),
        note=(
            HistogramNoteSpec(
                text=str(note_payload.get("text") or ""),
                x=float(note_payload.get("x") or 0.0),
                y=float(note_payload.get("y") or 0.0),
                align=str(note_payload.get("align") or "left"),
                font_size=float(note_payload.get("font_size") or 9.0),
                color=str(note_payload.get("color") or "#4d5968"),
            )
            if note_payload is not None
            else None
        ),
    )


def build_histogram_render_spec(
    *,
    values: Iterable[Any],
    canvas: Mapping[str, Any],
    title: str,
    title_fontsize: float = 15.0,
    x_min: float | None = None,
    x_max: float | None = None,
    bin_count: int | None = None,
    x_label: str = "Measurement",
    y_label: str = "Count",
    table_fontsize: float | None = None,
    statistics_rows: list[tuple[str, str]] | None = None,
    grid_axis: str = "y",
) -> dict[str, Any]:
    del table_fontsize
    payload: dict[str, Any] = {
        "values": list(values),
        "title": str(title),
        "bin_count": bin_count,
        "canvas": dict(canvas),
        "style": {
            "axis_label_x": x_label,
            "axis_label_y": y_label,
            "grid_axis": grid_axis,
        },
    }
    if x_min is not None or x_max is not None:
        payload["x_view"] = {
            "min": x_min,
            "max": x_max,
        }
    if statistics_rows:
        payload["summary_table_rows"] = [{"label": str(label), "value": str(value)} for label, value in statistics_rows]
    mapping = histogram_spec_to_mapping(build_resolved_histogram_spec(payload))
    title_payload = mapping.get("title") if isinstance(mapping.get("title"), Mapping) else None
    if title_payload is not None:
        title_payload["font"]["size"] = float(title_fontsize)
    return mapping


def _rect_mapping(rect: RectSpec | None) -> dict[str, float] | None:
    if rect is None:
        return None
    return {
        "x": float(rect.x),
        "y": float(rect.y),
        "width": float(rect.width),
        "height": float(rect.height),
    }


def _build_title_mapping(
    *,
    text: str,
    x: float,
    y: float,
    font_size: float = 10.0,
    color: str = SUMMARY_PLOT_PALETTE["distribution_foreground"],
    bold: bool = True,
) -> dict[str, Any]:
    return {
        "text": str(text or ""),
        "anchor": {
            "x": float(x),
            "y": float(y),
        },
        "font": {
            "size": float(font_size),
            "weight": "bold" if bold else "normal",
        },
        "color": str(color),
    }


def _build_standard_chart_layout(
    *,
    bottom_margin: float | None,
    has_legend: bool,
    left_margin: float = 0.12,
    right_margin: float = 0.965,
) -> tuple[RectSpec, RectSpec | None]:
    resolved_bottom = min(0.36, max(0.14, float(bottom_margin or 0.16)))
    resolved_top = 0.80 if has_legend else 0.84
    if resolved_top <= resolved_bottom + 0.20:
        resolved_top = min(0.94, resolved_bottom + 0.20)
    plot_rect = RectSpec(
        x=float(left_margin),
        y=float(resolved_bottom),
        width=float(max(0.30, right_margin - left_margin)),
        height=float(max(0.22, resolved_top - resolved_bottom)),
    )
    legend_rect = None
    if has_legend:
        legend_rect = RectSpec(
            x=float(plot_rect.x),
            y=0.905,
            width=float(plot_rect.width),
            height=0.05,
        )
    return plot_rect, legend_rect


def _truncate_tick_labels(labels: list[str], *, max_label_chars: int = 18) -> list[str]:
    normalized: list[str] = []
    for label in labels:
        plain_label = str(label).replace("\n", " ")
        if max_label_chars >= 2 and len(plain_label) > max_label_chars:
            plain_label = f"{plain_label[:max_label_chars - 1]}..."
        normalized.append(plain_label)
    return normalized


def _resolve_axis_layout(
    labels: list[str],
    *,
    positions: list[float],
    layout: Mapping[str, Any] | None,
    truncate_labels: bool = True,
    max_label_chars: int = 18,
) -> dict[str, Any]:
    safe_labels = [str(label) if label is not None else "" for label in labels]
    safe_positions = [float(position) for position in positions]
    strategy = prepare_categorical_x_axis(safe_labels)

    display_positions = list(layout.get("display_positions") or safe_positions) if isinstance(layout, Mapping) else list(safe_positions)
    display_labels = list(layout.get("display_labels") or strategy.get("processed_labels") or safe_labels) if isinstance(layout, Mapping) else list(strategy.get("processed_labels") or safe_labels)
    if truncate_labels:
        display_labels = _truncate_tick_labels([str(label) for label in display_labels], max_label_chars=max_label_chars)

    if len(display_positions) != len(display_labels):
        aligned = min(len(display_positions), len(display_labels))
        display_positions = display_positions[:aligned]
        display_labels = display_labels[:aligned]

    return {
        "rotation": int((layout or {}).get("rotation") or strategy.get("rotation") or 0),
        "display_positions": [float(position) for position in display_positions],
        "display_labels": [str(label) for label in display_labels],
        "bottom_margin": float((layout or {}).get("bottom_margin") or strategy.get("bottom_margin") or 0.16),
        "recommended_fig_width": float((layout or {}).get("recommended_fig_width") or strategy.get("recommended_fig_width") or 6.2),
    }


def _build_axes_mapping(
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    x_ticks: list[tuple[float, str]],
    y_ticks: list[tuple[float, str]],
    x_label: str,
    y_label: str,
    grid_axis: str = "y",
    rotation: int = 0,
) -> dict[str, Any]:
    return {
        "x_limits": {"min": float(x_min), "max": float(x_max)},
        "y_limits": {"min": float(y_min), "max": float(y_max)},
        "x_ticks": [{"value": float(value), "label": str(label)} for value, label in x_ticks],
        "y_ticks": [{"value": float(value), "label": str(label)} for value, label in y_ticks],
        "x_label": str(x_label),
        "y_label": str(y_label),
        "grid_axis": str(grid_axis),
        "rotation": int(rotation),
    }


def _build_reference_line_mapping(
    *,
    axis: str,
    value: float,
    color: str,
    alpha: float,
    width: float,
    dash: tuple[int, int] | None = None,
) -> dict[str, Any]:
    return {
        "axis": str(axis),
        "value": float(value),
        "color": str(color),
        "alpha": float(alpha),
        "width": float(width),
        "dash": list(dash) if dash is not None else None,
    }


def _coerce_finite_series_list(series_list: Iterable[Any]) -> list[list[float]]:
    normalized: list[list[float]] = []
    for series in series_list:
        numeric = _finite_array([] if series is None else series)
        normalized.append([float(item) for item in numeric.tolist()])
    return normalized


def build_resolved_distribution_spec(payload: Mapping[str, Any]) -> dict[str, Any]:
    width_px, height_px, dpi = _canvas_size(payload)
    labels = [str(item) for item in payload.get("labels") or []]
    render_mode = str(payload.get("render_mode") or "violin")
    layout = payload.get("layout") if isinstance(payload.get("layout"), Mapping) else {}
    legend_items = list(((payload.get("legend") or {}) if isinstance(payload.get("legend"), Mapping) else {}).get("items") or [])
    plot_rect, legend_rect = _build_standard_chart_layout(
        bottom_margin=_as_float(layout.get("bottom_margin")),
        has_legend=bool(legend_items),
    )

    series_list = _coerce_finite_series_list(payload.get("series") or [])
    all_values = _finite_array([value for series in series_list for value in series])
    if all_values.size == 0 and render_mode == "scatter":
        all_values = _finite_array(payload.get("y_values") or [])
    if all_values.size == 0:
        raise RuntimeError("distribution payload requires finite values")

    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), Mapping) else {}
    y_min = _as_float(y_limits.get("min"))
    y_max = _as_float(y_limits.get("max"))
    if y_min is None:
        y_min = float(np.min(all_values))
    if y_max is None:
        y_max = float(np.max(all_values))
    if math.isclose(y_min, y_max):
        y_min -= 0.5
        y_max += 0.5

    x_domain = payload.get("x_domain") if isinstance(payload.get("x_domain"), Mapping) else {}
    if render_mode == "scatter":
        x_values = _finite_array(payload.get("x_values") or [])
        if x_values.size == 0:
            raise RuntimeError("distribution scatter payload requires finite x values")
        x_min = _as_float(x_domain.get("min"))
        x_max = _as_float(x_domain.get("max"))
        if x_min is None:
            x_min = float(np.min(x_values))
        if x_max is None:
            x_max = float(np.max(x_values))
        if math.isclose(x_min, x_max):
            x_max += 1.0
        positions = list(layout.get("display_positions") or list(x_values.tolist()))
        scatter_points = [
            {
                "x": float(x_value),
                "y": float(y_value),
                "marker": "circle",
                "size": 6,
                "color": SUMMARY_PLOT_PALETTE["distribution_foreground"],
            }
            for x_value, y_value in zip(x_values.tolist(), _finite_array(payload.get("y_values") or []).tolist())
        ]
        violin_groups: list[dict[str, Any]] = []
    else:
        positions = [float(item) for item in list(payload.get("positions") or list(range(len(labels))))]
        x_min = _as_float(x_domain.get("min"))
        x_max = _as_float(x_domain.get("max"))
        if x_min is None:
            x_min = 0.0
        if x_max is None:
            x_max = max(float(len(labels) - 1), 1.0)
        if math.isclose(x_min, x_max):
            x_max += 1.0
        scatter_points = []
        violin_groups = [
            {
                "position": float(position),
                "values": list(series),
            }
            for position, series in zip(positions, series_list)
        ]

    axis_layout = _resolve_axis_layout(labels, positions=positions, layout=layout)
    x_ticks = list(zip(axis_layout["display_positions"], axis_layout["display_labels"]))
    y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(float(y_min), float(y_max), count=5)]

    reference_bands: list[dict[str, Any]] = []
    lsl = _as_float(payload.get("lsl"))
    usl = _as_float(payload.get("usl"))
    nominal = _as_float(payload.get("nominal"))
    one_sided = bool(payload.get("one_sided"))
    include_nominal = bool(payload.get("include_nominal"))
    if usl is not None and (lsl is not None or one_sided):
        reference_bands.append(
            {
                "axis": "y",
                "start": float(0.0 if one_sided else lsl),
                "end": float(usl),
                "color": SUMMARY_PLOT_PALETTE["sigma_band"],
                "alpha": 0.12,
            }
        )

    reference_lines = [
        _build_reference_line_mapping(
            axis="y",
            value=float(limit_value),
            color=SUMMARY_PLOT_PALETTE["spec_limit"],
            alpha=0.82,
            width=2.0,
            dash=(8, 5) if dashed else None,
        )
        for limit_value, dashed in (
            (lsl, False),
            (usl, False),
            (nominal if include_nominal else None, True),
        )
        if limit_value is not None
    ]

    axes = _build_axes_mapping(
        x_min=float(x_min),
        x_max=float(x_max),
        y_min=float(y_min),
        y_max=float(y_max),
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_label=str(payload.get("x_label") or "Group"),
        y_label=str(payload.get("y_label") or "Measurement"),
        grid_axis="y",
        rotation=int(axis_layout["rotation"]),
    )

    spec: dict[str, Any] = {
        "chart_type": "distribution",
        "canvas": {"width_px": width_px, "height_px": height_px, "dpi": dpi},
        "render_mode": render_mode,
        "title": _build_title_mapping(
            text=str(payload.get("title") or ""),
            x=float(plot_rect.x),
            y=0.972,
        ),
        "plot_area": _rect_mapping(plot_rect),
        "axes": axes,
        "x_ticks": [{"position": value, "label": label} for value, label in x_ticks],
        "y_ticks": [{"position": value, "label": label} for value, label in y_ticks],
        "x_label": axes["x_label"],
        "y_label": axes["y_label"],
        "grid_axis": axes["grid_axis"],
        "x_min": float(x_min),
        "x_max": float(x_max),
        "y_min": float(y_min),
        "y_max": float(y_max),
        "reference_bands": reference_bands,
        "reference_lines": reference_lines,
        "annotation_style": dict(payload.get("annotation_style") or {}) if isinstance(payload.get("annotation_style"), Mapping) else {},
        "violin_annotations": list(payload.get("violin_annotations") or []),
        "violin_groups": violin_groups,
        "scatter_points": scatter_points,
    }
    if legend_rect is not None or legend_items:
        spec["legend"] = {
            "rect": _rect_mapping(legend_rect),
            "items": legend_items,
        }
    return spec


def build_resolved_iqr_spec(payload: Mapping[str, Any]) -> dict[str, Any]:
    width_px, height_px, dpi = _canvas_size(payload)
    labels = [str(item) for item in payload.get("labels") or []]
    series_list = _coerce_finite_series_list(payload.get("series") or [])
    flat_values = _finite_array([item for series in series_list for item in series])
    if flat_values.size == 0:
        raise RuntimeError("iqr payload requires finite values")

    layout = payload.get("layout") if isinstance(payload.get("layout"), Mapping) else {}
    legend_items = list(((payload.get("legend") or {}) if isinstance(payload.get("legend"), Mapping) else {}).get("items") or [])
    plot_rect, legend_rect = _build_standard_chart_layout(
        bottom_margin=_as_float(layout.get("bottom_margin")),
        has_legend=bool(legend_items),
    )

    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), Mapping) else {}
    y_min = _as_float(y_limits.get("min"))
    y_max = _as_float(y_limits.get("max"))
    if y_min is None:
        y_min = float(np.min(flat_values))
    if y_max is None:
        y_max = float(np.max(flat_values))
    if math.isclose(y_min, y_max):
        y_min -= 0.5
        y_max += 0.5

    positions = list(range(1, len(series_list) + 1))
    axis_layout = _resolve_axis_layout(labels, positions=[float(item) for item in positions], layout=layout)
    x_min = 0.5
    x_max = max(float(len(series_list)) + 0.5, 1.5)
    x_ticks = list(zip(axis_layout["display_positions"], axis_layout["display_labels"]))
    y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(float(y_min), float(y_max), count=5)]

    one_sided = bool(payload.get("one_sided"))
    lsl = _as_float(payload.get("lsl"))
    usl = _as_float(payload.get("usl"))
    nominal = _as_float(payload.get("nominal"))
    reference_bands: list[dict[str, Any]] = []
    if usl is not None and (lsl is not None or one_sided):
        reference_bands.append(
            {
                "axis": "y",
                "start": float(0.0 if one_sided else lsl),
                "end": float(usl),
                "color": SUMMARY_PLOT_PALETTE["sigma_band"],
                "alpha": 0.12,
            }
        )
    reference_lines = [
        _build_reference_line_mapping(
            axis="y",
            value=float(limit_value),
            color=SUMMARY_PLOT_PALETTE["spec_limit"],
            alpha=0.82,
            width=2.0,
            dash=(8, 5) if dashed else None,
        )
        for limit_value, dashed in ((lsl, False), (usl, False), (nominal, True))
        if limit_value is not None
    ]

    boxes: list[dict[str, Any]] = []
    for index, series in enumerate(series_list, start=1):
        if not series:
            continue
        numeric = np.asarray(series, dtype=float)
        q1, median, q3 = np.percentile(numeric, [25, 50, 75])
        iqr = float(q3 - q1)
        lower_bound = float(q1 - (1.5 * iqr))
        upper_bound = float(q3 + (1.5 * iqr))
        whisker_low = float(np.min(numeric[numeric >= lower_bound])) if np.any(numeric >= lower_bound) else float(np.min(numeric))
        whisker_high = float(np.max(numeric[numeric <= upper_bound])) if np.any(numeric <= upper_bound) else float(np.max(numeric))
        outliers = numeric[(numeric < lower_bound) | (numeric > upper_bound)]
        boxes.append(
            {
                "position": float(index),
                "q1": float(q1),
                "median": float(median),
                "q3": float(q3),
                "whisker_low": float(whisker_low),
                "whisker_high": float(whisker_high),
                "outliers": [float(item) for item in outliers.tolist()],
            }
        )

    axes = _build_axes_mapping(
        x_min=float(x_min),
        x_max=float(x_max),
        y_min=float(y_min),
        y_max=float(y_max),
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_label=str(payload.get("x_label") or "Group"),
        y_label=str(payload.get("y_label") or "Measurement"),
        grid_axis="y",
        rotation=int(axis_layout["rotation"]),
    )

    spec: dict[str, Any] = {
        "chart_type": "iqr",
        "canvas": {"width_px": width_px, "height_px": height_px, "dpi": dpi},
        "title": _build_title_mapping(
            text=str(payload.get("title") or ""),
            x=float(plot_rect.x),
            y=0.972,
        ),
        "plot_area": _rect_mapping(plot_rect),
        "axes": axes,
        "x_ticks": [{"position": value, "label": label} for value, label in x_ticks],
        "y_ticks": [{"position": value, "label": label} for value, label in y_ticks],
        "x_label": axes["x_label"],
        "y_label": axes["y_label"],
        "grid_axis": axes["grid_axis"],
        "x_min": float(x_min),
        "x_max": float(x_max),
        "y_min": float(y_min),
        "y_max": float(y_max),
        "reference_bands": reference_bands,
        "reference_lines": reference_lines,
        "boxes": boxes,
        "boxplots": [dict(box) for box in boxes],
    }
    if legend_rect is not None or legend_items:
        spec["legend"] = {
            "rect": _rect_mapping(legend_rect),
            "items": legend_items,
        }
    return spec


def build_resolved_trend_spec(payload: Mapping[str, Any]) -> dict[str, Any]:
    width_px, height_px, dpi = _canvas_size(payload)
    x_values = _finite_array(payload.get("x_values") or [])
    y_values = _finite_array(payload.get("y_values") or [])
    if x_values.size == 0 or y_values.size == 0:
        raise RuntimeError("trend payload requires finite x/y values")

    labels = [str(item) for item in payload.get("labels") or []]
    layout = payload.get("layout") if isinstance(payload.get("layout"), Mapping) else {}
    plot_rect, _legend_rect = _build_standard_chart_layout(
        bottom_margin=_as_float(layout.get("bottom_margin")),
        has_legend=False,
    )

    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), Mapping) else {}
    y_min = _as_float(y_limits.get("min"))
    y_max = _as_float(y_limits.get("max"))
    if y_min is None:
        y_min = float(np.min(y_values))
    if y_max is None:
        y_max = float(np.max(y_values))
    if math.isclose(y_min, y_max):
        y_min -= 0.5
        y_max += 0.5

    x_min = float(np.min(x_values))
    x_max = float(np.max(x_values))
    if math.isclose(x_min, x_max):
        x_max += 1.0

    positions = list(layout.get("display_positions") or list(x_values.tolist()))
    axis_layout = _resolve_axis_layout(labels, positions=[float(item) for item in positions], layout=layout)
    x_ticks = list(zip(axis_layout["display_positions"], axis_layout["display_labels"]))
    y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(float(y_min), float(y_max), count=5)]
    reference_lines = [
        _build_reference_line_mapping(
            axis="y",
            value=float(limit_value),
            color=SUMMARY_PLOT_PALETTE["spec_limit"],
            alpha=0.82,
            width=2.0,
        )
        for limit_value in list(payload.get("horizontal_limits") or [])
        if _as_float(limit_value) is not None
    ]

    axes = _build_axes_mapping(
        x_min=float(x_min),
        x_max=float(x_max),
        y_min=float(y_min),
        y_max=float(y_max),
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_label=str(payload.get("x_label") or "Sample #"),
        y_label=str(payload.get("y_label") or "Measurement"),
        grid_axis="y",
        rotation=int(axis_layout["rotation"]),
    )

    return {
        "chart_type": "trend",
        "canvas": {"width_px": width_px, "height_px": height_px, "dpi": dpi},
        "title": _build_title_mapping(
            text=str(payload.get("title") or ""),
            x=float(plot_rect.x),
            y=0.972,
        ),
        "plot_area": _rect_mapping(plot_rect),
        "axes": axes,
        "x_ticks": [{"position": value, "label": label} for value, label in x_ticks],
        "y_ticks": [{"position": value, "label": label} for value, label in y_ticks],
        "x_label": axes["x_label"],
        "y_label": axes["y_label"],
        "grid_axis": axes["grid_axis"],
        "x_min": float(x_min),
        "x_max": float(x_max),
        "y_min": float(y_min),
        "y_max": float(y_max),
        "reference_lines": reference_lines,
        "points": [
            {
                "x": float(x_value),
                "y": float(y_value),
                "marker": "circle",
                "size": 6,
                "color": SUMMARY_PLOT_PALETTE["distribution_foreground"],
            }
            for x_value, y_value in zip(x_values.tolist(), y_values.tolist())
        ],
    }

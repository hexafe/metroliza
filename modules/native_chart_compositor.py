"""Payload-driven Pillow chart compositor used by the native chart extension."""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import math
import os
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

try:  # pragma: no cover - optional SciPy path
    from scipy.stats import gaussian_kde
except Exception:  # pragma: no cover - optional SciPy path
    gaussian_kde = None

from modules.export_summary_sheet_planner import (
    build_histogram_annotation_specs as _build_histogram_annotation_specs,
    compute_histogram_annotation_rows as _compute_histogram_annotation_rows,
)
from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE


DEFAULT_DPI = 150
DEFAULT_HEIGHT_PX = 600
DEFAULT_WIDTH_PX = 1320
WHITE = (255, 255, 255, 255)

_FONT_PATHS = {
    False: (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf",
    ),
    True: (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf",
    ),
}


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


def _hex_rgba(color: str | tuple[int, int, int] | tuple[int, int, int, int], alpha: float = 1.0) -> tuple[int, int, int, int]:
    if isinstance(color, tuple):
        if len(color) == 4:
            return color
        if len(color) == 3:
            return (int(color[0]), int(color[1]), int(color[2]), int(max(0.0, min(1.0, alpha)) * 255.0))
    rgb = ImageColor.getrgb(str(color))
    return (rgb[0], rgb[1], rgb[2], int(max(0.0, min(1.0, alpha)) * 255.0))


@lru_cache(maxsize=32)
def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    safe_size = max(8, int(size))
    for path in _FONT_PATHS[bool(bold)]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, safe_size)
            except Exception:
                continue
    return ImageFont.load_default()


def _multiline_text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, *, spacing: int = 2) -> tuple[int, int]:
    text_value = str(text or "")
    if not text_value:
        return 0, 0
    left, top, right, bottom = draw.multiline_textbbox((0, 0), text_value, font=font, spacing=spacing)
    return int(right - left), int(bottom - top)


def _draw_multiline_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    align: str = "left",
    spacing: int = 2,
) -> None:
    draw.multiline_text((float(xy[0]), float(xy[1])), str(text or ""), font=font, fill=fill, align=align, spacing=spacing)


def _paste_rotated_text(
    image: Image.Image,
    text: str,
    *,
    center: tuple[float, float],
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    angle: float,
) -> None:
    text_value = str(text or "")
    if not text_value:
        return
    draw = ImageDraw.Draw(image)
    width, height = _multiline_text_size(draw, text_value, font)
    width = max(width + 6, 8)
    height = max(height + 6, 8)
    overlay = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.multiline_text((3, 3), text_value, font=font, fill=fill, spacing=2)
    rotated = overlay.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    image.alpha_composite(rotated, dest=(int(center[0] - (rotated.width / 2)), int(center[1] - (rotated.height / 2))))


def _canvas_size(payload: dict[str, Any], *, default_width: int = DEFAULT_WIDTH_PX, default_height: int = DEFAULT_HEIGHT_PX) -> tuple[int, int]:
    canvas = payload.get("canvas")
    if isinstance(canvas, dict):
        width = int(canvas.get("width_px") or default_width)
        height = int(canvas.get("height_px") or default_height)
        return max(width, 400), max(height, 260)
    return default_width, default_height


def _encode_png(
    image: Image.Image,
    *,
    optimize: bool = True,
    compress_level: int | None = None,
) -> bytes:
    buffer = BytesIO()
    save_kwargs: dict[str, Any] = {
        "format": "PNG",
        "optimize": bool(optimize),
    }
    if compress_level is not None:
        save_kwargs["compress_level"] = max(0, min(9, int(compress_level)))
    image.save(buffer, **save_kwargs)
    return buffer.getvalue()


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


def _map_linear(value: float, src_min: float, src_max: float, dst_min: float, dst_max: float) -> float:
    if not math.isfinite(value):
        return dst_min
    if math.isclose(src_min, src_max):
        return (dst_min + dst_max) / 2.0
    ratio = (float(value) - src_min) / (src_max - src_min)
    return dst_min + (ratio * (dst_max - dst_min))


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    *,
    fill: tuple[int, int, int, int],
    width: int = 1,
    dash: tuple[int, int] = (6, 4),
) -> None:
    if len(points) < 2:
        return
    dash_on = max(int(dash[0]), 1)
    dash_off = max(int(dash[1]), 1)
    for left, right in zip(points, points[1:]):
        dx = right[0] - left[0]
        dy = right[1] - left[1]
        distance = math.hypot(dx, dy)
        if distance <= 0:
            continue
        step_x = dx / distance
        step_y = dy / distance
        cursor = 0.0
        while cursor < distance:
            start = cursor
            end = min(distance, cursor + dash_on)
            start_point = (left[0] + (step_x * start), left[1] + (step_y * start))
            end_point = (left[0] + (step_x * end), left[1] + (step_y * end))
            draw.line((start_point, end_point), fill=fill, width=width)
            cursor += dash_on + dash_off


def _draw_box(
    draw: ImageDraw.ImageDraw,
    rect: tuple[float, float, float, float],
    *,
    fill: tuple[int, int, int, int] | None = None,
    outline: tuple[int, int, int, int] | None = None,
    width: int = 1,
    radius: int = 6,
) -> None:
    x0, y0, x1, y1 = rect
    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=fill, outline=outline, width=width)


def _draw_marker(draw: ImageDraw.ImageDraw, *, kind: str, x: float, y: float, size: int, fill: tuple[int, int, int, int]) -> None:
    half = size / 2.0
    if kind == "circle":
        draw.ellipse((x - half, y - half, x + half, y + half), fill=fill)
        return
    if kind == "triangle_up":
        draw.polygon(((x, y - half), (x + half, y + half), (x - half, y + half)), fill=fill)
        return
    if kind == "triangle_down":
        draw.polygon(((x - half, y - half), (x + half, y - half), (x, y + half)), fill=fill)
        return
    draw.rectangle((x - half, y - half, x + half, y + half), fill=fill)


def _draw_annotation_box(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    anchor_x: float,
    base_y: float,
    color: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    plot_left: float,
    plot_right: float,
    leader_y: float | None = None,
    align: str = "center",
) -> None:
    text_width, text_height = _multiline_text_size(draw, text, font)
    pad_x = 6
    pad_y = 4
    total_width = text_width + (pad_x * 2)
    total_height = text_height + (pad_y * 2)
    if align == "right":
        box_left = anchor_x - total_width
    elif align == "left":
        box_left = anchor_x
    else:
        box_left = anchor_x - (total_width / 2.0)
    box_left = max(plot_left + 2.0, min(plot_right - total_width - 2.0, box_left))
    box_top = base_y
    box_rect = (box_left, box_top, box_left + total_width, box_top + total_height)
    _draw_box(
        draw,
        box_rect,
        fill=(255, 255, 255, 240),
        outline=_hex_rgba(SUMMARY_PLOT_PALETTE["annotation_box_edge"]),
        width=1,
        radius=5,
    )
    _draw_multiline_text(draw, (box_left + pad_x, box_top + pad_y), text, font=font, fill=color)
    if leader_y is not None:
        center_x = box_left + (total_width / 2.0)
        draw.line((anchor_x, leader_y, center_x, box_top + total_height), fill=color, width=1)


def _draw_axis_shell(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    rect: tuple[int, int, int, int],
    x_ticks: list[tuple[float, str]] | None,
    y_ticks: list[tuple[float, str]] | None,
    x_limits: tuple[float, float],
    y_limits: tuple[float, float],
    x_label: str,
    y_label: str,
    rotation: int = 0,
    grid_axis: str = "y",
) -> None:
    left, top, right, bottom = rect
    tick_font = _font(10)
    axis_color = _hex_rgba(SUMMARY_PLOT_PALETTE["axis_spine"])
    grid_color = _hex_rgba(SUMMARY_PLOT_PALETTE["grid"])
    tick_color = _hex_rgba(SUMMARY_PLOT_PALETTE["axis_text"])

    if grid_axis == "y" and y_ticks:
        for value, _label in y_ticks:
            y = _map_linear(value, y_limits[0], y_limits[1], bottom, top)
            draw.line((left, y, right, y), fill=grid_color, width=1)

    draw.line((left, top, left, bottom), fill=axis_color, width=2)
    draw.line((left, bottom, right, bottom), fill=axis_color, width=2)

    if y_ticks:
        for value, label in y_ticks:
            y = _map_linear(value, y_limits[0], y_limits[1], bottom, top)
            draw.line((left - 5, y, left, y), fill=axis_color, width=1)
            label_width, label_height = _multiline_text_size(draw, label, tick_font)
            _draw_multiline_text(
                draw,
                (left - label_width - 10, y - (label_height / 2.0)),
                label,
                font=tick_font,
                fill=tick_color,
            )

    if x_ticks:
        for position, label in x_ticks:
            x = _map_linear(position, x_limits[0], x_limits[1], left, right)
            draw.line((x, bottom, x, bottom + 5), fill=axis_color, width=1)
            if rotation == 0:
                label_width, _ = _multiline_text_size(draw, label, tick_font)
                _draw_multiline_text(draw, (x - (label_width / 2.0), bottom + 10), label, font=tick_font, fill=tick_color, align="center")
            else:
                _paste_rotated_text(
                    image,
                    label,
                    center=(x, bottom + 28),
                    font=tick_font,
                    fill=tick_color,
                    angle=rotation,
                )

    label_font = _font(12)
    label_width, _ = _multiline_text_size(draw, x_label, label_font)
    _draw_multiline_text(draw, ((left + right - label_width) / 2.0, bottom + 42), x_label, font=label_font, fill=tick_color)
    _paste_rotated_text(
        image,
        y_label,
        center=(left - 56, (top + bottom) / 2.0),
        font=label_font,
        fill=tick_color,
        angle=90,
    )


def _normalize_table_rows(rows: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, dict):
            normalized.append(dict(row))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            normalized.append({"label": str(row[0]), "value": str(row[1])})
    return normalized


def _draw_table(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    *,
    title: str,
    rows: list[dict[str, Any]],
) -> None:
    left, top, right, bottom = rect
    header_font = _font(12, bold=True)
    body_font = _font(10)
    muted_font = _font(9)
    header_bg = _hex_rgba(SUMMARY_PLOT_PALETTE["table_header_bg"])
    header_text = _hex_rgba(SUMMARY_PLOT_PALETTE["table_header_text"])
    border_color = _hex_rgba("#d5dbe3")
    default_text = _hex_rgba(SUMMARY_PLOT_PALETTE["annotation_text"])

    _draw_box(draw, (left, top, right, bottom), fill=WHITE, outline=border_color, width=1, radius=8)
    draw.rectangle((left, top, right, top + 28), fill=header_bg)
    _draw_multiline_text(draw, (left + 10, top + 7), title, font=header_font, fill=header_text)

    label_fraction = 0.44
    label_x = left + 10
    value_x = left + int((right - left) * label_fraction)
    cursor_y = top + 34
    for index, row in enumerate(rows):
        if cursor_y >= bottom - 10:
            break
        label = str(row.get("label", ""))
        value = str(row.get("value", ""))
        row_fill = None
        text_fill = default_text
        badge_palette = str(row.get("badge_palette") or "").strip()
        if badge_palette:
            row_fill = _hex_rgba(SUMMARY_PLOT_PALETTE.get(f"{badge_palette}_bg", SUMMARY_PLOT_PALETTE["quality_unknown_bg"]))
            text_fill = _hex_rgba(SUMMARY_PLOT_PALETTE.get(f"{badge_palette}_text", SUMMARY_PLOT_PALETTE["quality_unknown_text"]))
        elif label in {"Cp", "Cpk", "Normality"}:
            row_fill = _hex_rgba(SUMMARY_PLOT_PALETTE["table_emphasis_bg"])
            text_fill = _hex_rgba(SUMMARY_PLOT_PALETTE["table_emphasis_text"])

        line_count = max(label.count("\n") + 1, value.count("\n") + 1)
        row_height = (line_count * 14) + 8

        if row.get("section_break_before"):
            draw.line((left + 8, cursor_y - 4, right - 8, cursor_y - 4), fill=border_color, width=2)

        if row_fill is not None:
            draw.rounded_rectangle((left + 5, cursor_y - 1, right - 5, cursor_y + row_height - 1), radius=5, fill=row_fill)

        font = muted_font if row.get("row_kind") == "helper_note" else body_font
        _draw_multiline_text(draw, (label_x, cursor_y + 2), label, font=font, fill=text_fill)
        _draw_multiline_text(draw, (value_x, cursor_y + 2), value, font=font, fill=text_fill)
        if index < len(rows) - 1:
            draw.line((left + 8, cursor_y + row_height + 1, right - 8, cursor_y + row_height + 1), fill=_hex_rgba("#edf1f5"), width=1)
        cursor_y += row_height


def _points_to_pixels(size_pt: float, *, dpi: int = DEFAULT_DPI) -> int:
    return max(8, int(round(float(size_pt) * (max(int(dpi), 1) / 72.0))))


def _normalized_rect_to_pixels(
    rect: dict[str, Any] | None,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    if not isinstance(rect, dict):
        return None
    try:
        left = float(rect["x"]) * float(width)
        top = (1.0 - float(rect["y"]) - float(rect["height"])) * float(height)
        right = left + (float(rect["width"]) * float(width))
        bottom = top + (float(rect["height"]) * float(height))
    except (KeyError, TypeError, ValueError):
        return None
    return (
        int(round(left)),
        int(round(top)),
        int(round(right)),
        int(round(bottom)),
    )


def _resolved_plot_rect(
    resolved_render_spec: dict[str, Any],
    *,
    width: int,
    height: int,
    fallback_rect: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    resolved_plot_rect = _normalized_rect_to_pixels(
        (
            resolved_render_spec.get("plot_area")
            if isinstance(resolved_render_spec.get("plot_area"), dict)
            else resolved_render_spec.get("plot_rect")
        )
        if isinstance(resolved_render_spec, dict)
        else None,
        width=width,
        height=height,
    )
    return resolved_plot_rect or fallback_rect


def _resolved_ticks(axis_ticks: Any, fallback_ticks: list[tuple[float, str]]) -> list[tuple[float, str]]:
    if not isinstance(axis_ticks, list):
        return fallback_ticks
    resolved: list[tuple[float, str]] = []
    for item in axis_ticks:
        if not isinstance(item, dict):
            continue
        value = _as_float(item.get("value"))
        if value is None:
            value = _as_float(item.get("position"))
        if value is None:
            continue
        resolved.append((float(value), str(item.get("label") or "")))
    return resolved or fallback_ticks


def _draw_chart_title(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    width: int,
    height: int,
    dpi: int,
    title_spec: dict[str, Any],
    fallback_text: str,
    fallback_xy: tuple[float, float] = (54.0, 24.0),
    fallback_font_px: int = 14,
    fallback_color: str = SUMMARY_PLOT_PALETTE["distribution_foreground"],
) -> None:
    resolved_title_text = str(title_spec.get("text") or fallback_text or "")
    if not resolved_title_text:
        return
    title_anchor = title_spec.get("anchor") if isinstance(title_spec.get("anchor"), dict) else {}
    title_font_spec = title_spec.get("font") if isinstance(title_spec.get("font"), dict) else {}
    resolved_font_size = _as_float(title_font_spec.get("size"))
    if resolved_font_size is None:
        resolved_font_size = _as_float(title_spec.get("font_size"))
    title_font = _font(
        _points_to_pixels(float(resolved_font_size), dpi=dpi) if resolved_font_size is not None else int(fallback_font_px),
        bold=str(title_font_spec.get("weight") or "").lower() == "bold" or bool(title_spec.get("bold", False)),
    )
    title_rect = _normalized_rect_to_pixels(
        title_spec.get("rect") if isinstance(title_spec.get("rect"), dict) else None,
        width=width,
        height=height,
    )
    if title_rect is not None:
        title_x = float(title_rect[0])
        title_y = float(title_rect[1])
    else:
        title_x = float(title_anchor.get("x")) * float(width) if _as_float(title_anchor.get("x")) is not None else (
            float(title_spec.get("x")) * float(width) if _as_float(title_spec.get("x")) is not None else float(fallback_xy[0])
        )
        title_y = (1.0 - float(title_anchor.get("y"))) * float(height) if _as_float(title_anchor.get("y")) is not None else (
            (1.0 - float(title_spec.get("y"))) * float(height) if _as_float(title_spec.get("y")) is not None else float(fallback_xy[1])
        )
        text_width, text_height = _multiline_text_size(draw, resolved_title_text, title_font)
        title_ha = str(title_spec.get("ha") or "left").lower()
        title_va = str(title_spec.get("va") or "top").lower()
        if title_ha == "center":
            title_x -= text_width / 2.0
        elif title_ha == "right":
            title_x -= text_width
        if title_va in {"center", "center_baseline"}:
            title_y -= text_height / 2.0
        elif title_va in {"baseline", "bottom"}:
            title_y -= text_height
    _draw_multiline_text(
        draw,
        (title_x, title_y),
        resolved_title_text,
        font=title_font,
        fill=_hex_rgba(title_spec.get("color") or fallback_color),
    )


def _draw_reference_bands(
    draw: ImageDraw.ImageDraw,
    *,
    rect: tuple[int, int, int, int],
    bands: list[dict[str, Any]],
    x_limits: tuple[float, float],
    y_limits: tuple[float, float],
) -> None:
    left, top, right, bottom = rect
    for band in bands:
        if not isinstance(band, dict):
            continue
        axis = str(band.get("axis") or "y").lower()
        start = _as_float(band.get("start"))
        end = _as_float(band.get("end"))
        if start is None or end is None:
            continue
        fill = _hex_rgba(band.get("color") or SUMMARY_PLOT_PALETTE["sigma_band"], float(band.get("alpha") or 0.12))
        if axis == "x":
            x0 = _map_linear(float(start), x_limits[0], x_limits[1], left, right)
            x1 = _map_linear(float(end), x_limits[0], x_limits[1], left, right)
            draw.rectangle((min(x0, x1), top, max(x0, x1), bottom), fill=fill)
            continue
        y0 = _map_linear(float(start), y_limits[0], y_limits[1], bottom, top)
        y1 = _map_linear(float(end), y_limits[0], y_limits[1], bottom, top)
        draw.rectangle((left, min(y0, y1), right, max(y0, y1)), fill=fill)


def _draw_reference_lines(
    draw: ImageDraw.ImageDraw,
    *,
    rect: tuple[int, int, int, int],
    lines: list[dict[str, Any]],
    x_limits: tuple[float, float],
    y_limits: tuple[float, float],
) -> None:
    left, top, right, bottom = rect
    for line in lines:
        if not isinstance(line, dict):
            continue
        axis = str(line.get("axis") or "y").lower()
        value = _as_float(line.get("value"))
        if value is None:
            continue
        color = _hex_rgba(line.get("color") or SUMMARY_PLOT_PALETTE["spec_limit"], float(line.get("alpha") or 0.82))
        width = max(1, int(round(float(line.get("width") or 2.0))))
        dash = tuple(int(piece) for piece in line.get("dash")) if line.get("dash") else None
        span0 = max(0.0, min(1.0, float(line.get("span0_axes") or 0.0)))
        span1 = max(0.0, min(1.0, float(line.get("span1_axes") or 1.0)))
        if axis == "x":
            x = _map_linear(float(value), x_limits[0], x_limits[1], left, right)
            y0 = top + ((1.0 - span1) * (bottom - top))
            y1 = top + ((1.0 - span0) * (bottom - top))
            if dash:
                _draw_dashed_line(draw, [(x, y0), (x, y1)], fill=color, width=width, dash=dash)
            else:
                draw.line((x, y0, x, y1), fill=color, width=width)
            continue
        y = _map_linear(float(value), y_limits[0], y_limits[1], bottom, top)
        x0 = left + (span0 * (right - left))
        x1 = left + (span1 * (right - left))
        if dash:
            _draw_dashed_line(draw, [(x0, y), (x1, y)], fill=color, width=width, dash=dash)
        else:
            draw.line((x0, y, x1, y), fill=color, width=width)


def _draw_distribution_polygon_body(
    draw: ImageDraw.ImageDraw,
    *,
    body: dict[str, Any],
    rect: tuple[int, int, int, int],
    x_limits: tuple[float, float],
    y_limits: tuple[float, float],
) -> None:
    polygon_points = list(body.get("polygon_points") or [])
    if len(polygon_points) < 3:
        return
    left, top, right, bottom = rect
    mapped_points: list[tuple[float, float]] = []
    for point in polygon_points:
        if not isinstance(point, dict):
            continue
        x_value = _as_float(point.get("x"))
        y_value = _as_float(point.get("y"))
        if x_value is None or y_value is None:
            continue
        mapped_points.append(
            (
                _map_linear(float(x_value), x_limits[0], x_limits[1], left, right),
                _map_linear(float(y_value), y_limits[0], y_limits[1], bottom, top),
            )
        )
    if len(mapped_points) < 3:
        return
    fill = _hex_rgba(body.get("fill_color") or SUMMARY_PLOT_PALETTE["distribution_base"], float(body.get("fill_alpha") or 0.45))
    outline = _hex_rgba(body.get("edge_color") or SUMMARY_PLOT_PALETTE["distribution_foreground"], float(body.get("edge_alpha") or 0.85))
    draw.polygon(mapped_points, fill=fill, outline=outline)


def _draw_resolved_distribution_annotations(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    annotations: dict[str, Any],
    width: int,
    height: int,
    rect: tuple[int, int, int, int],
    x_limits: tuple[float, float],
    y_limits: tuple[float, float],
) -> None:
    left, top, right, bottom = rect
    for marker in list(annotations.get("markers") or []):
        if not isinstance(marker, dict):
            continue
        x_value = _as_float(marker.get("x"))
        y_value = _as_float(marker.get("y"))
        if x_value is None or y_value is None:
            continue
        _draw_marker(
            draw,
            kind=str(marker.get("kind") or "circle"),
            x=_map_linear(float(x_value), x_limits[0], x_limits[1], left, right),
            y=_map_linear(float(y_value), y_limits[0], y_limits[1], bottom, top),
            size=max(4, int(round(float(marker.get("size") or 6.0)))),
            fill=_hex_rgba(marker.get("color") or SUMMARY_PLOT_PALETTE["distribution_foreground"], float(marker.get("alpha") or 1.0)),
        )

    for segment in list(annotations.get("segments") or []):
        if not isinstance(segment, dict):
            continue
        x0 = _as_float(segment.get("x0"))
        y0 = _as_float(segment.get("y0"))
        x1 = _as_float(segment.get("x1"))
        y1 = _as_float(segment.get("y1"))
        if None in {x0, y0, x1, y1}:
            continue
        color = _hex_rgba(segment.get("color") or SUMMARY_PLOT_PALETTE["sigma_band"], float(segment.get("alpha") or 1.0))
        width_px = max(1, int(round(float(segment.get("width") or 1.0))))
        dash = tuple(int(piece) for piece in segment.get("dash")) if segment.get("dash") else None
        mapped_points = [
            (
                _map_linear(float(x0), x_limits[0], x_limits[1], left, right),
                _map_linear(float(y0), y_limits[0], y_limits[1], bottom, top),
            ),
            (
                _map_linear(float(x1), x_limits[0], x_limits[1], left, right),
                _map_linear(float(y1), y_limits[0], y_limits[1], bottom, top),
            ),
        ]
        if dash:
            _draw_dashed_line(draw, mapped_points, fill=color, width=width_px, dash=dash)
        else:
            draw.line((mapped_points[0], mapped_points[1]), fill=color, width=width_px)

    for text in list(annotations.get("texts") or []):
        if not isinstance(text, dict):
            continue
        text_rect = _normalized_rect_to_pixels(text.get("rect") if isinstance(text.get("rect"), dict) else None, width=width, height=height)
        if text_rect is None:
            continue
        box_left, box_top, box_right, box_bottom = text_rect
        _draw_box(
            draw,
            (box_left, box_top, box_right, box_bottom),
            fill=(255, 255, 255, 240),
            outline=_hex_rgba(SUMMARY_PLOT_PALETTE["annotation_box_edge"]),
            width=1,
            radius=5,
        )
        font = _font(max(8, int(round(float(text.get("font_size") or 8.0)))))
        _draw_multiline_text(
            draw,
            (box_left + 6, box_top + 4),
            str(text.get("text") or ""),
            font=font,
            fill=_hex_rgba(text.get("color") or SUMMARY_PLOT_PALETTE["annotation_text"], float(text.get("alpha") or 1.0)),
        )
        point_x = _as_float(text.get("point_x"))
        point_y = _as_float(text.get("point_y"))
        if point_x is not None and point_y is not None:
            anchor_x = _map_linear(float(point_x), x_limits[0], x_limits[1], left, right)
            anchor_y = _map_linear(float(point_y), y_limits[0], y_limits[1], bottom, top)
            draw.line(
                (
                    anchor_x,
                    anchor_y,
                    box_left + ((box_right - box_left) / 2.0),
                    box_top + ((box_bottom - box_top) / 2.0),
                ),
                fill=_hex_rgba(text.get("color") or SUMMARY_PLOT_PALETTE["annotation_text"], float(text.get("alpha") or 1.0)),
                width=1,
            )


def _format_histogram_stat_value(value: Any, *, decimals: int = 3) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "N/A"
    if math.isclose(numeric, round(numeric), abs_tol=1e-9):
        return f"{numeric:.0f}"
    return f"{numeric:.{decimals}f}"


def _fallback_histogram_specification_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
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
                "style_hint": {"orientation": "vertical", "line_role": role},
            }
        )
    return resolved


def _fallback_histogram_table_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
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


def _fallback_histogram_annotation_rows(
    payload: dict[str, Any],
    *,
    x_min: float,
    x_max: float,
) -> list[dict[str, Any]]:
    mean_value = _as_float(((payload.get("mean_line") or {}) if isinstance(payload.get("mean_line"), dict) else {}).get("value"))
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
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
    payload: dict[str, Any],
    *,
    x_min: float,
    x_max: float,
) -> tuple[dict[str, Any], bool]:
    visual_metadata = payload.get("visual_metadata") if isinstance(payload.get("visual_metadata"), dict) else {}
    nested_table = visual_metadata.get("summary_stats_table") if isinstance(visual_metadata.get("summary_stats_table"), dict) else {}
    nested_overlays = visual_metadata.get("modeled_overlays") if isinstance(visual_metadata.get("modeled_overlays"), dict) else {}

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


def _resolved_histogram_overlay_rows(
    resolved_render_spec: dict[str, Any],
    *,
    fallback_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(resolved_render_spec.get("overlay_curves"), list):
        return list(resolved_render_spec.get("overlay_curves") or [])
    if isinstance(resolved_render_spec.get("overlays"), list):
        return list(resolved_render_spec.get("overlays") or [])
    return list(fallback_rows)


def _resolved_histogram_mean_line(
    payload: dict[str, Any],
    *,
    resolved_render_spec: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(resolved_render_spec.get("mean_line"), dict):
        return dict(resolved_render_spec.get("mean_line") or {})
    line_spec = resolved_render_spec.get("lines") if isinstance(resolved_render_spec.get("lines"), dict) else {}
    if isinstance(line_spec.get("mean"), dict):
        return dict(line_spec.get("mean") or {})
    if isinstance(payload.get("mean_line"), dict):
        return dict(payload.get("mean_line") or {})
    return {}


def _resolved_histogram_specification_lines(
    resolved_render_spec: dict[str, Any],
    *,
    fallback_lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(resolved_render_spec.get("specification_lines"), list):
        return list(resolved_render_spec.get("specification_lines") or [])
    line_spec = resolved_render_spec.get("lines") if isinstance(resolved_render_spec.get("lines"), dict) else {}
    if isinstance(line_spec.get("specification"), list):
        return list(line_spec.get("specification") or [])
    return list(fallback_lines)


def _draw_histogram_bars(
    draw: ImageDraw.ImageDraw,
    *,
    bars: list[dict[str, Any]],
    rect: tuple[int, int, int, int],
    x_limits: tuple[float, float],
    y_limits: tuple[float, float],
) -> None:
    left, top, right, bottom = rect
    y_min, y_max = y_limits
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        left_edge = _as_float(bar.get("left_edge"))
        right_edge = _as_float(bar.get("right_edge"))
        count = _as_float(bar.get("count"))
        if None in {left_edge, right_edge, count}:
            continue
        x0 = _map_linear(float(left_edge), x_limits[0], x_limits[1], left, right)
        x1 = _map_linear(float(right_edge), x_limits[0], x_limits[1], left, right)
        y0 = _map_linear(float(count), y_min, y_max, bottom, top)
        fill = _hex_rgba(bar.get("fill_color") or SUMMARY_PLOT_PALETTE["distribution_base"], float(bar.get("fill_alpha") or 0.84))
        outline = _hex_rgba(bar.get("edge_color") or "#ffffff", float(bar.get("edge_alpha") or 0.72))
        edge_width = max(1, int(round(float(bar.get("edge_width") or 1.0))))
        draw.rectangle(
            (
                min(x0, x1),
                min(y0, bottom - 1),
                max(x0, x1),
                max(y0, bottom - 1),
            ),
            fill=fill,
            outline=outline,
            width=edge_width,
        )


def _map_horizontal_box_coordinate(
    value: float,
    *,
    position: float | None,
    left_bound: float | None,
    right_bound: float | None,
    x_limits: tuple[float, float],
    plot_left: int,
    plot_right: int,
) -> float:
    if (
        left_bound is not None
        and right_bound is not None
        and 0.0 <= float(left_bound) <= 1.0
        and 0.0 <= float(right_bound) <= 1.0
        and (
            position is None
            or not (float(left_bound) <= float(position) <= float(right_bound))
        )
    ):
        return plot_left + (float(value) * (plot_right - plot_left))
    return _map_linear(float(value), x_limits[0], x_limits[1], plot_left, plot_right)


def render_histogram_png(payload: dict[str, Any]) -> bytes:
    values = _finite_array(payload.get("values") or [])
    if values.size == 0:
        raise RuntimeError("histogram payload requires finite values")

    width, height = _canvas_size(payload)
    dpi = int(((payload.get("canvas") or {}) if isinstance(payload.get("canvas"), dict) else {}).get("dpi") or DEFAULT_DPI)
    image = Image.new("RGBA", (width, height), WHITE)
    draw = ImageDraw.Draw(image)

    resolved_render_spec = payload.get("resolved_render_spec") if isinstance(payload.get("resolved_render_spec"), dict) else {}
    axis_spec = resolved_render_spec.get("axes") if isinstance(resolved_render_spec.get("axes"), dict) else {}
    x_limits_spec = axis_spec.get("x_limits") if isinstance(axis_spec.get("x_limits"), dict) else {}
    x_view = payload.get("x_view") if isinstance(payload.get("x_view"), dict) else {}
    x_min = _as_float(x_limits_spec.get("min"))
    x_max = _as_float(x_limits_spec.get("max"))
    if x_min is None:
        x_min = _as_float(resolved_render_spec.get("x_min"))
    if x_max is None:
        x_max = _as_float(resolved_render_spec.get("x_max"))
    if x_min is None:
        x_min = _as_float(x_view.get("min"))
    if x_max is None:
        x_max = _as_float(x_view.get("max"))
    if x_min is None:
        x_min = float(np.min(values))
    if x_max is None:
        x_max = float(np.max(values))
    if math.isclose(x_min, x_max):
        x_min -= 0.5
        x_max += 0.5

    resolved_bars = list(resolved_render_spec.get("bars") or []) if isinstance(resolved_render_spec.get("bars"), list) else None
    counts = np.asarray([], dtype=float)
    edges = np.asarray([], dtype=float)
    max_count = 1.0
    if resolved_bars is None:
        bin_count = max(1, int(payload.get("bin_count") or 20))
        counts, edges = np.histogram(values, bins=bin_count, range=(x_min, x_max))
        max_count = float(max(1, int(np.max(counts)) if counts.size else 1))
    else:
        resolved_counts = [_as_float(item.get("count")) for item in resolved_bars if isinstance(item, dict)]
        resolved_counts = [float(item) for item in resolved_counts if item is not None]
        if resolved_counts:
            max_count = max(max_count, max(resolved_counts))

    visual_metadata, compact_mode = _resolve_histogram_visual_metadata(payload, x_min=x_min, x_max=x_max)
    overlays_meta = visual_metadata.get("modeled_overlays") if isinstance(visual_metadata.get("modeled_overlays"), dict) else {}
    title_spec = resolved_render_spec.get("title") if isinstance(resolved_render_spec.get("title"), dict) else {}
    side_panels_spec = resolved_render_spec.get("side_panels") if isinstance(resolved_render_spec.get("side_panels"), dict) else {}
    overlay_rows = _resolved_histogram_overlay_rows(
        resolved_render_spec,
        fallback_rows=list(overlays_meta.get("rows") or []),
    )
    note_spec = resolved_render_spec.get("note") if isinstance(resolved_render_spec.get("note"), dict) else None

    plot_left = 86
    plot_top = 72 if compact_mode else 104
    plot_bottom = height - 92
    table_width = 0 if compact_mode else int(width * 0.31)
    plot_right = width - table_width - 28
    plot_rect = (plot_left, plot_top, plot_right, plot_bottom)
    resolved_plot_rect = _normalized_rect_to_pixels(
        (
            resolved_render_spec.get("plot_area")
            if isinstance(resolved_render_spec.get("plot_area"), dict)
            else resolved_render_spec.get("plot_rect")
        ) if isinstance(resolved_render_spec, dict) else None,
        width=width,
        height=height,
    )
    if resolved_plot_rect is not None:
        plot_rect = resolved_plot_rect
        plot_left, plot_top, plot_right, plot_bottom = plot_rect

    y_limits_spec = axis_spec.get("y_limits") if isinstance(axis_spec.get("y_limits"), dict) else {}
    y_min = _as_float(y_limits_spec.get("min"))
    y_max = _as_float(y_limits_spec.get("max"))
    if y_min is None:
        y_min = _as_float(resolved_render_spec.get("y_min"))
    if y_max is None:
        y_max = _as_float(resolved_render_spec.get("y_max"))
    use_resolved_y_limits = y_min is not None and y_max is not None and y_max > y_min
    if use_resolved_y_limits:
        max_count = float(y_max)
    else:
        for overlay in overlay_rows:
            if str(overlay.get("kind")) == "curve":
                curve_y = _finite_array(overlay.get("y") or [])
                if curve_y.size:
                    max_count = max(max_count, float(np.max(curve_y)))
        max_count *= 1.08
        y_min = 0.0
        y_max = max_count

    x_ticks_spec = axis_spec.get("x_ticks") if isinstance(axis_spec.get("x_ticks"), list) else []
    if x_ticks_spec:
        x_ticks = [
            (float(item.get("value") if _as_float(item.get("value")) is not None else item.get("position")), str(item.get("label") or ""))
            for item in x_ticks_spec
            if isinstance(item, dict) and (
                _as_float(item.get("value")) is not None
                or _as_float(item.get("position")) is not None
            )
        ]
    else:
        fallback_x_ticks = resolved_render_spec.get("x_ticks") if isinstance(resolved_render_spec.get("x_ticks"), list) else []
        if fallback_x_ticks:
            x_ticks = [
                (float(item.get("position")), str(item.get("label") or ""))
                for item in fallback_x_ticks
                if isinstance(item, dict) and _as_float(item.get("position")) is not None
            ]
        else:
            x_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(x_min, x_max, count=6)]
    y_ticks_spec = axis_spec.get("y_ticks") if isinstance(axis_spec.get("y_ticks"), list) else []
    if y_ticks_spec:
        y_ticks = [
            (float(item.get("value") if _as_float(item.get("value")) is not None else item.get("position")), str(item.get("label") or ""))
            for item in y_ticks_spec
            if isinstance(item, dict) and (
                _as_float(item.get("value")) is not None
                or _as_float(item.get("position")) is not None
            )
        ]
    else:
        fallback_y_ticks = resolved_render_spec.get("y_ticks") if isinstance(resolved_render_spec.get("y_ticks"), list) else []
        if fallback_y_ticks:
            y_ticks = [
                (float(item.get("position")), str(item.get("label") or ""))
                for item in fallback_y_ticks
                if isinstance(item, dict) and _as_float(item.get("position")) is not None
            ]
        else:
            y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(float(y_min or 0.0), float(y_max), count=5)]
    _draw_axis_shell(
        image,
        draw,
        rect=plot_rect,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_limits=(x_min, x_max),
        y_limits=(float(y_min or 0.0), float(y_max)),
        x_label=str(axis_spec.get("x_label") or resolved_render_spec.get("x_label") or (payload.get("style") or {}).get("axis_label_x") or "Measurement"),
        y_label=str(axis_spec.get("y_label") or resolved_render_spec.get("y_label") or (payload.get("style") or {}).get("axis_label_y") or "Count"),
        rotation=0,
        grid_axis=str(axis_spec.get("grid_axis") or resolved_render_spec.get("grid_axis") or (payload.get("style") or {}).get("grid_axis") or "y"),
    )

    if resolved_bars is not None:
        _draw_histogram_bars(
            draw,
            bars=resolved_bars,
            rect=plot_rect,
            x_limits=(x_min, x_max),
            y_limits=(float(y_min or 0.0), float(y_max)),
        )
    else:
        bar_fill = _hex_rgba(SUMMARY_PLOT_PALETTE["distribution_base"], 0.84)
        bar_outline = _hex_rgba("#ffffff", 0.72)
        for left_edge, right_edge, count in zip(edges[:-1], edges[1:], counts):
            if count <= 0:
                continue
            x0 = _map_linear(left_edge, x_min, x_max, plot_left, plot_right)
            x1 = _map_linear(right_edge, x_min, x_max, plot_left, plot_right)
            y0 = _map_linear(float(count), 0.0, max_count, plot_bottom, plot_top)
            draw.rectangle((x0 + 1, y0, x1 - 1, plot_bottom - 1), fill=bar_fill, outline=bar_outline)

    for overlay in overlay_rows:
        kind = str(overlay.get("kind") or "").strip().lower()
        x_values = _finite_array(overlay.get("x_values") or overlay.get("x") or [])
        y_values = _finite_array(overlay.get("y_values") or overlay.get("y") or [])
        if x_values.size == 0 or y_values.size == 0 or x_values.size != y_values.size:
            continue
        points = [
            (
                _map_linear(float(x), x_min, x_max, plot_left, plot_right),
                _map_linear(float(y), float(y_min or 0.0), float(y_max), plot_bottom, plot_top),
            )
            for x, y in zip(x_values, y_values)
        ]
        color = _hex_rgba(overlay.get("color") or SUMMARY_PLOT_PALETTE["density_line"], float(overlay.get("alpha") or 1.0))
        width_px = max(1, int(round(float(overlay.get("width") or overlay.get("linewidth") or 1.0))))
        if bool(overlay.get("fill_to_baseline")):
            polygon = list(points)
            polygon.append((points[-1][0], plot_bottom))
            polygon.append((points[0][0], plot_bottom))
            draw.polygon(polygon, fill=_hex_rgba(overlay.get("fill_color") or overlay.get("color") or SUMMARY_PLOT_PALETTE["spec_limit"], float(overlay.get("fill_alpha") or 0.1)))
        if overlay.get("dash"):
            _draw_dashed_line(draw, points, fill=color, width=width_px, dash=tuple(int(item) for item in overlay.get("dash")))
        else:
            draw.line(points, fill=color, width=width_px)
    if note_spec is not None and str(note_spec.get("text") or "").strip():
        note_x = int(round(float(note_spec.get("x") or 0.0) * float(width)))
        note_y = int(round((1.0 - float(note_spec.get("y") or 0.0)) * float(height)))
        _draw_annotation_box(
            image,
            draw,
            text=str(note_spec.get("text") or ""),
            anchor_x=note_x,
            base_y=note_y,
            color=_hex_rgba(note_spec.get("color") or "#4d5968"),
            font=_font(_points_to_pixels(float(note_spec.get("font_size") or 9.0), dpi=dpi)),
            plot_left=plot_left,
            plot_right=plot_right,
            leader_y=None,
            align=str(note_spec.get("align") or "left"),
        )

    mean_line = _resolved_histogram_mean_line(payload, resolved_render_spec=resolved_render_spec)
    mean_value = _as_float(mean_line.get("value"))
    if mean_value is not None:
        mean_x = _map_linear(mean_value, x_min, x_max, plot_left, plot_right)
        _draw_dashed_line(
            draw,
            [(mean_x, plot_top), (mean_x, plot_bottom)],
            fill=_hex_rgba(SUMMARY_PLOT_PALETTE["central_tendency"], float(mean_line.get("alpha") or 0.48)),
            width=max(1, int(round(float(mean_line.get("width") or mean_line.get("linewidth") or 1.3)))),
            dash=(8, 5),
        )

    line_items = _resolved_histogram_specification_lines(
        resolved_render_spec,
        fallback_lines=list(visual_metadata.get("specification_lines") or []),
    )
    for line_meta in line_items:
        if not isinstance(line_meta, dict):
            continue
        if "enabled" in line_meta and not line_meta.get("enabled"):
            continue
        line_value = _as_float(line_meta.get("value"))
        if line_value is None:
            continue
        x = _map_linear(line_value, x_min, x_max, plot_left, plot_right)
        plot_height = max(float(plot_bottom - plot_top), 1.0)
        y0_axes = _as_float(line_meta.get("y0_axes"))
        y1_axes = _as_float(line_meta.get("y1_axes"))
        y0_px = plot_bottom if y0_axes is None else float(plot_bottom) - (float(y0_axes) * plot_height)
        y1_px = plot_top if y1_axes is None else float(plot_bottom) - (float(y1_axes) * plot_height)
        draw.line((x, y0_px, x, y1_px), fill=_hex_rgba(line_meta.get("color") or SUMMARY_PLOT_PALETTE["spec_limit"], float(line_meta.get("alpha") or 0.82)), width=max(1, int(round(float(line_meta.get("width") or 2)))))

    resolved_title_text = str(title_spec.get("text") or payload.get("title") or "")
    title_anchor = title_spec.get("anchor") if isinstance(title_spec.get("anchor"), dict) else {}
    title_font_spec = title_spec.get("font") if isinstance(title_spec.get("font"), dict) else {}
    title_x = float(title_anchor.get("x")) * float(width) if _as_float(title_anchor.get("x")) is not None else (
        float(title_spec.get("x")) * float(width) if _as_float(title_spec.get("x")) is not None else 54.0
    )
    title_y = (1.0 - float(title_anchor.get("y"))) * float(height) if _as_float(title_anchor.get("y")) is not None else (
        (1.0 - float(title_spec.get("y"))) * float(height) if _as_float(title_spec.get("y")) is not None else 22.0
    )
    title_font = _font(
        _points_to_pixels(float(title_font_spec.get("size") or title_spec.get("font_size") or 15.0), dpi=dpi),
        bold=(
            str(title_font_spec.get("weight") or "").lower() == "bold"
            or bool(title_spec.get("bold", False))
        ),
    )
    _draw_multiline_text(
        draw,
        (title_x, title_y),
        resolved_title_text,
        font=title_font,
        fill=_hex_rgba(title_spec.get("color") or SUMMARY_PLOT_PALETTE["distribution_foreground"]),
    )

    resolved_annotations = resolved_render_spec.get("annotations") if isinstance(resolved_render_spec.get("annotations"), list) else []
    annotation_rows = resolved_annotations or list(visual_metadata.get("annotation_rows") or [])
    for annotation in annotation_rows:
        if not isinstance(annotation, dict):
            continue
        label_text = str(annotation.get("text") or annotation.get("label") or "")
        x_value = _as_float(annotation.get("x")) if _as_float(annotation.get("x")) is not None else _as_float(annotation.get("x_value"))
        if not label_text or x_value is None:
            continue
        row_index = int(annotation.get("row_index") or 0)
        kind = str(annotation.get("kind") or "").strip().lower()
        align = str((annotation.get("placement_hint") or {}).get("ha") or "center")
        color = _hex_rgba(annotation.get("color") or (SUMMARY_PLOT_PALETTE["spec_limit"] if kind in {"lsl", "usl"} else SUMMARY_PLOT_PALETTE["annotation_text"]))
        leader_y = plot_top + 4
        text_y_axes = _as_float(annotation.get("text_y_axes"))
        box_y = _as_float(annotation.get("box_y"))
        if box_y is not None:
            base_y = (1.0 - float(box_y)) * float(height)
        elif text_y_axes is not None:
            plot_height = max(float(plot_bottom - plot_top), 1.0)
            base_y = float(plot_bottom) - (float(text_y_axes) * plot_height)
        else:
            base_y = 44 + (row_index * 26)
        _draw_annotation_box(
            image,
            draw,
            text=label_text,
            anchor_x=_map_linear(x_value, x_min, x_max, plot_left, plot_right),
            base_y=base_y,
            color=color,
            font=_font(10),
            plot_left=plot_left,
            plot_right=plot_right,
            leader_y=leader_y,
            align=align,
        )

    if not compact_mode:
        table_rect = (plot_right + 20, plot_top - 10, width - 18, height - 26)
        resolved_table_rect = _normalized_rect_to_pixels(
            (
                side_panels_spec.get("right_info")
                if isinstance(side_panels_spec.get("right_info"), dict)
                else resolved_render_spec.get("table_rect")
            ) if isinstance(resolved_render_spec, dict) else None,
            width=width,
            height=height,
        )
        if resolved_table_rect is not None:
            table_rect = resolved_table_rect
        table_meta = resolved_render_spec.get("table") if isinstance(resolved_render_spec.get("table"), dict) else {}
        if not table_meta:
            table_meta = visual_metadata.get("summary_stats_table") if isinstance(visual_metadata.get("summary_stats_table"), dict) else {}
        _draw_table(
            draw,
            table_rect,
            title=str(table_meta.get("title") or "Parameter"),
            rows=_normalize_table_rows(list(table_meta.get("rows") or [])),
        )

    if compact_mode:
        # Compact histogram payloads are used for stripped render-budget paths,
        # so lower PNG compression is worth the much faster export time.
        return _encode_png(image, optimize=False, compress_level=1)
    return _encode_png(image)


def _draw_legend(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], *, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    left, top, right, _bottom = rect
    cursor_x = right - 12
    font = _font(9)
    for item in reversed(items):
        label = str(item.get("label") or "")
        if not label:
            continue
        label_width, _ = _multiline_text_size(draw, label, font)
        box_width = label_width + 44
        box_left = cursor_x - box_width
        _draw_box(draw, (box_left, top, cursor_x, top + 22), fill=(255, 255, 255, 235), outline=_hex_rgba("#d5dbe3"), width=1, radius=5)
        marker_x = box_left + 12
        marker_y = top + 11
        color = _hex_rgba(item.get("color") or SUMMARY_PLOT_PALETTE["distribution_foreground"])
        kind = str(item.get("kind") or "line")
        if kind == "band":
            draw.rectangle((box_left + 6, top + 6, box_left + 18, top + 16), fill=_hex_rgba(item.get("fill_color") or SUMMARY_PLOT_PALETTE["sigma_band"], 0.18))
        elif kind == "marker":
            _draw_marker(draw, kind=item.get("marker") or "circle", x=marker_x, y=marker_y, size=8, fill=color)
        else:
            dash = tuple(int(piece) for piece in item.get("dash")) if item.get("dash") else None
            points = [(box_left + 6, marker_y), (box_left + 18, marker_y)]
            if dash:
                _draw_dashed_line(draw, points, fill=color, width=2, dash=dash)
            else:
                draw.line(points, fill=color, width=2)
        _draw_multiline_text(draw, (box_left + 24, top + 6), label, font=font, fill=_hex_rgba(SUMMARY_PLOT_PALETTE["annotation_text"]))
        cursor_x = box_left - 8


def _resolve_violin_points(series: np.ndarray, *, y_min: float, y_max: float, density_peak: float) -> tuple[np.ndarray, np.ndarray] | None:
    if series.size == 0:
        return None
    sample_y = np.linspace(y_min, y_max, 128)
    if gaussian_kde is not None and series.size >= 3 and np.std(series, ddof=1) > 0:
        try:
            density = gaussian_kde(series)(sample_y)
        except Exception:
            density = None
    else:
        density = None
    if density is None:
        hist, edges = np.histogram(series, bins=min(24, max(6, int(math.sqrt(series.size)))), range=(y_min, y_max), density=True)
        sample_y = (edges[:-1] + edges[1:]) / 2.0
        density = hist
    peak = float(np.max(density)) if len(density) else 0.0
    if peak <= 0 or not math.isfinite(peak):
        return None
    return sample_y, np.asarray(density, dtype=float) / max(density_peak, peak)


def render_distribution_png(payload: dict[str, Any]) -> bytes:
    width, height = _canvas_size(payload, default_width=1080, default_height=600)
    dpi = int(((payload.get("canvas") or {}) if isinstance(payload.get("canvas"), dict) else {}).get("dpi") or DEFAULT_DPI)
    image = Image.new("RGBA", (width, height), WHITE)
    draw = ImageDraw.Draw(image)

    resolved_render_spec = payload.get("resolved_render_spec") if isinstance(payload.get("resolved_render_spec"), dict) else {}
    axis_spec = resolved_render_spec.get("axes") if isinstance(resolved_render_spec.get("axes"), dict) else {}
    title_spec = resolved_render_spec.get("title") if isinstance(resolved_render_spec.get("title"), dict) else {}
    legend_spec = resolved_render_spec.get("legend") if isinstance(resolved_render_spec.get("legend"), dict) else {}
    legend_items = (
        list(legend_spec.get("items") or [])
        if isinstance(legend_spec.get("items"), list)
        else list((payload.get("legend") or {}).get("items") or [])
    )
    plot_rect = _resolved_plot_rect(
        resolved_render_spec,
        width=width,
        height=height,
        fallback_rect=(82, 88, width - 32, height - 92),
    )
    layout = payload.get("layout") if isinstance(payload.get("layout"), dict) else {}
    labels = [str(item) for item in payload.get("labels") or []]
    display_positions = list(layout.get("display_positions") or list(range(len(labels))))
    display_labels = list(layout.get("display_labels") or labels)
    render_mode = str(resolved_render_spec.get("render_mode") or payload.get("render_mode") or "violin")

    all_values = _finite_array([value for series in payload.get("series") or [] for value in series])
    if all_values.size == 0 and render_mode == "scatter":
        all_values = _finite_array(payload.get("y_values") or [])
    if all_values.size == 0:
        raise RuntimeError("distribution payload requires finite values")
    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), dict) else {}
    y_limits_spec = axis_spec.get("y_limits") if isinstance(axis_spec.get("y_limits"), dict) else {}
    y_min = _as_float(y_limits_spec.get("min"))
    y_max = _as_float(y_limits_spec.get("max"))
    if y_min is None:
        y_min = _as_float(resolved_render_spec.get("y_min"))
    if y_max is None:
        y_max = _as_float(resolved_render_spec.get("y_max"))
    if y_min is None:
        y_min = _as_float(y_limits.get("min"))
    if y_max is None:
        y_max = _as_float(y_limits.get("max"))
    if y_min is None:
        y_min = float(np.min(all_values))
    if y_max is None:
        y_max = float(np.max(all_values))
    if math.isclose(y_min, y_max):
        y_min -= 0.5
        y_max += 0.5

    x_domain = payload.get("x_domain") if isinstance(payload.get("x_domain"), dict) else {}
    x_limits_spec = axis_spec.get("x_limits") if isinstance(axis_spec.get("x_limits"), dict) else {}
    x_min = _as_float(x_limits_spec.get("min"))
    x_max = _as_float(x_limits_spec.get("max"))
    if x_min is None:
        x_min = _as_float(resolved_render_spec.get("x_min"))
    if x_max is None:
        x_max = _as_float(resolved_render_spec.get("x_max"))
    if x_min is None:
        x_min = _as_float(x_domain.get("min"))
    if x_max is None:
        x_max = _as_float(x_domain.get("max"))
    if x_min is None or x_max is None:
        if render_mode == "scatter":
            x_values = _finite_array(payload.get("x_values") or [])
            x_min = float(np.min(x_values)) if x_values.size else 0.0
            x_max = float(np.max(x_values)) if x_values.size else 1.0
        else:
            x_min = 0.0
            x_max = max(float(len(labels) - 1), 1.0)
    if math.isclose(x_min, x_max):
        x_max += 1.0

    fallback_x_ticks = list(zip(display_positions, display_labels))
    fallback_y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(y_min, y_max, count=5)]
    x_ticks = _resolved_ticks(axis_spec.get("x_ticks") or resolved_render_spec.get("x_ticks"), fallback_x_ticks)
    y_ticks = _resolved_ticks(axis_spec.get("y_ticks") or resolved_render_spec.get("y_ticks"), fallback_y_ticks)
    _draw_axis_shell(
        image,
        draw,
        rect=plot_rect,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
        x_label=str(axis_spec.get("x_label") or resolved_render_spec.get("x_label") or payload.get("x_label") or "Group"),
        y_label=str(axis_spec.get("y_label") or resolved_render_spec.get("y_label") or payload.get("y_label") or "Measurement"),
        rotation=int(axis_spec.get("rotation") or layout.get("rotation") or 0),
        grid_axis=str(axis_spec.get("grid_axis") or resolved_render_spec.get("grid_axis") or "y"),
    )
    _draw_chart_title(
        image,
        draw,
        width=width,
        height=height,
        dpi=dpi,
        title_spec=title_spec,
        fallback_text=str(payload.get("title") or ""),
    )
    legend_rect = _normalized_rect_to_pixels(
        legend_spec.get("rect") if isinstance(legend_spec.get("rect"), dict) else None,
        width=width,
        height=height,
    ) or (plot_rect[0], 24, plot_rect[2], 52)
    _draw_legend(draw, legend_rect, items=legend_items)

    reference_bands = resolved_render_spec.get("reference_bands") if isinstance(resolved_render_spec.get("reference_bands"), list) else None
    if reference_bands is None:
        one_sided = bool(payload.get("one_sided"))
        lsl = _as_float(payload.get("lsl"))
        usl = _as_float(payload.get("usl"))
        reference_bands = []
        if usl is not None and (lsl is not None or one_sided):
            reference_bands.append(
                {
                    "axis": "y",
                    "start": 0.0 if one_sided else lsl,
                    "end": usl,
                    "color": SUMMARY_PLOT_PALETTE["sigma_band"],
                    "alpha": 0.12,
                }
            )
    _draw_reference_bands(
        draw,
        rect=plot_rect,
        bands=list(reference_bands or []),
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
    )

    reference_lines = resolved_render_spec.get("reference_lines") if isinstance(resolved_render_spec.get("reference_lines"), list) else None
    if reference_lines is None:
        lsl = _as_float(payload.get("lsl"))
        usl = _as_float(payload.get("usl"))
        nominal = _as_float(payload.get("nominal"))
        reference_lines = [
            {
                "axis": "y",
                "value": line_value,
                "color": SUMMARY_PLOT_PALETTE["spec_limit"],
                "alpha": 0.82,
                "width": 2.0,
                "dash": [8, 5] if dashed else None,
            }
            for line_value, dashed in ((lsl, False), (usl, False), (nominal if payload.get("include_nominal") else None, True))
            if line_value is not None
        ]
    _draw_reference_lines(
        draw,
        rect=plot_rect,
        lines=list(reference_lines or []),
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
    )

    if render_mode == "scatter":
        scatter_points = resolved_render_spec.get("scatter_points") if isinstance(resolved_render_spec.get("scatter_points"), list) else None
        if scatter_points is None:
            x_values = _finite_array(payload.get("x_values") or [])
            y_values = _finite_array(payload.get("y_values") or [])
            scatter_points = [
                {
                    "x": float(x_value),
                    "y": float(y_value),
                    "marker": "circle",
                    "size": 6,
                    "color": SUMMARY_PLOT_PALETTE["distribution_foreground"],
                }
                for x_value, y_value in zip(x_values.tolist(), y_values.tolist())
            ]
        for point in scatter_points:
            x_value = _as_float(point.get("x"))
            y_value = _as_float(point.get("y"))
            if x_value is None or y_value is None:
                continue
            x = _map_linear(float(x_value), x_min, x_max, plot_rect[0], plot_rect[2])
            y = _map_linear(float(y_value), y_min, y_max, plot_rect[3], plot_rect[1])
            _draw_marker(
                draw,
                kind=str(point.get("marker") or "circle"),
                x=x,
                y=y,
                size=max(4, int(point.get("size") or 6)),
                fill=_hex_rgba(point.get("color") or SUMMARY_PLOT_PALETTE["distribution_foreground"], float(point.get("alpha") or 1.0)),
            )
        return _encode_png(image)

    resolved_violin_bodies = resolved_render_spec.get("violin_bodies") if isinstance(resolved_render_spec.get("violin_bodies"), list) else None
    resolved_annotation_geometry = resolved_render_spec.get("annotations") if isinstance(resolved_render_spec.get("annotations"), dict) else None
    if resolved_violin_bodies is not None:
        for body in resolved_violin_bodies:
            if isinstance(body, dict):
                _draw_distribution_polygon_body(
                    draw,
                    body=body,
                    rect=plot_rect,
                    x_limits=(x_min, x_max),
                    y_limits=(y_min, y_max),
                )
        if resolved_annotation_geometry is not None:
            _draw_resolved_distribution_annotations(
                image,
                draw,
                annotations=resolved_annotation_geometry,
                width=width,
                height=height,
                rect=plot_rect,
                x_limits=(x_min, x_max),
                y_limits=(y_min, y_max),
            )
        return _encode_png(image)

    violin_groups = resolved_render_spec.get("violin_groups") if isinstance(resolved_render_spec.get("violin_groups"), list) else None
    if violin_groups is None:
        positions = list(payload.get("positions") or list(range(len(payload.get("series") or []))))
        series_list = [_finite_array(series) for series in payload.get("series") or []]
        violin_groups = [
            {
                "position": float(position),
                "values": [float(item) for item in series.tolist()],
            }
            for position, series in zip(positions, series_list)
        ]
    else:
        series_list = [_finite_array(group.get("values") or []) for group in violin_groups if isinstance(group, dict)]

    density_peak = 0.0
    for series in series_list:
        if series.size >= 3 and gaussian_kde is not None and np.std(series, ddof=1) > 0:
            try:
                density_peak = max(density_peak, float(np.max(gaussian_kde(series)(np.linspace(y_min, y_max, 96)))))
            except Exception:
                continue
    density_peak = max(density_peak, 1.0)
    positions = [float(group.get("position") or 0.0) for group in violin_groups if isinstance(group, dict)]
    gap = (plot_rect[2] - plot_rect[0]) / max(2, len(positions) or len(series_list))
    violin_half_width = max(10.0, gap * 0.22)

    for group in violin_groups:
        if not isinstance(group, dict):
            continue
        series = _finite_array(group.get("values") or [])
        if series.size == 0:
            continue
        center_value = float(group.get("position") or 0.0)
        center_x = _map_linear(center_value, x_min, x_max, plot_rect[0], plot_rect[2])
        density_points = _resolve_violin_points(series, y_min=y_min, y_max=y_max, density_peak=density_peak)
        if density_points is not None:
            sample_y, density = density_points
            right_points = [
                (
                    center_x + (float(width_scale) * violin_half_width),
                    _map_linear(float(y_value), y_min, y_max, plot_rect[3], plot_rect[1]),
                )
                for y_value, width_scale in zip(sample_y, density)
            ]
            left_points = [
                (
                    center_x - (float(width_scale) * violin_half_width),
                    _map_linear(float(y_value), y_min, y_max, plot_rect[3], plot_rect[1]),
                )
                for y_value, width_scale in zip(sample_y[::-1], density[::-1])
            ]
            draw.polygon(right_points + left_points, fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_base"], 0.55), outline=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"], 0.85))

    annotation_style = (
        resolved_render_spec.get("annotation_style")
        if isinstance(resolved_render_spec.get("annotation_style"), dict)
        else payload.get("annotation_style")
    ) if isinstance(payload.get("annotation_style"), dict) or isinstance(resolved_render_spec.get("annotation_style"), dict) else {}
    violin_annotations = (
        list(resolved_render_spec.get("violin_annotations") or [])
        if isinstance(resolved_render_spec.get("violin_annotations"), list)
        else list(payload.get("violin_annotations") or [])
    )
    show_minmax = bool(annotation_style.get("show_minmax", True))
    show_sigma = bool(annotation_style.get("show_sigma", True))
    for item in violin_annotations:
        xpos = _as_float(item.get("position"))
        mean_value = _as_float(item.get("mean"))
        minimum_value = _as_float(item.get("minimum"))
        maximum_value = _as_float(item.get("maximum"))
        sigma_start_value = _as_float(item.get("sigma_start"))
        sigma_high_value = _as_float(item.get("sigma_high"))
        if xpos is None or mean_value is None:
            continue
        center_x = _map_linear(xpos, x_min, x_max, plot_rect[0], plot_rect[2])
        mean_y = _map_linear(float(mean_value), y_min, y_max, plot_rect[3], plot_rect[1])
        _draw_marker(draw, kind="circle", x=center_x, y=mean_y, size=max(8, int(annotation_style.get("mean_marker_size") or 14) // 2), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["central_tendency"]))
        _draw_annotation_box(
            image,
            draw,
            text=f"u={float(mean_value):.3f}",
            anchor_x=center_x + 6,
            base_y=mean_y - 20,
            color=_hex_rgba(SUMMARY_PLOT_PALETTE["annotation_text"]),
            font=_font(max(8, int(annotation_style.get("font_size") or 8))),
            plot_left=plot_rect[0],
            plot_right=plot_rect[2],
            leader_y=mean_y,
            align="left",
        )
        if show_minmax and minimum_value is not None and maximum_value is not None:
            minimum_y = _map_linear(float(minimum_value), y_min, y_max, plot_rect[3], plot_rect[1])
            maximum_y = _map_linear(float(maximum_value), y_min, y_max, plot_rect[3], plot_rect[1])
            _draw_marker(draw, kind="triangle_down", x=center_x, y=minimum_y, size=8, fill=_hex_rgba(SUMMARY_PLOT_PALETTE["annotation_text"]))
            _draw_marker(draw, kind="triangle_up", x=center_x, y=maximum_y, size=8, fill=_hex_rgba(SUMMARY_PLOT_PALETTE["annotation_text"]))
        if show_sigma and item.get("show_sigma_segment") and sigma_start_value is not None and sigma_high_value is not None:
            sigma_start = _map_linear(float(sigma_start_value), y_min, y_max, plot_rect[3], plot_rect[1])
            sigma_high = _map_linear(float(sigma_high_value), y_min, y_max, plot_rect[3], plot_rect[1])
            _draw_dashed_line(draw, [(center_x, sigma_start), (center_x, sigma_high)], fill=_hex_rgba(SUMMARY_PLOT_PALETTE["sigma_band"]), width=1, dash=(4, 4))

    return _encode_png(image)


def render_iqr_png(payload: dict[str, Any]) -> bytes:
    width, height = _canvas_size(payload, default_width=1080, default_height=600)
    dpi = int(((payload.get("canvas") or {}) if isinstance(payload.get("canvas"), dict) else {}).get("dpi") or DEFAULT_DPI)
    image = Image.new("RGBA", (width, height), WHITE)
    draw = ImageDraw.Draw(image)

    resolved_render_spec = payload.get("resolved_render_spec") if isinstance(payload.get("resolved_render_spec"), dict) else {}
    axis_spec = resolved_render_spec.get("axes") if isinstance(resolved_render_spec.get("axes"), dict) else {}
    title_spec = resolved_render_spec.get("title") if isinstance(resolved_render_spec.get("title"), dict) else {}
    legend_spec = resolved_render_spec.get("legend") if isinstance(resolved_render_spec.get("legend"), dict) else {}
    labels = [str(item) for item in payload.get("labels") or []]
    series_list = [_finite_array(series) for series in payload.get("series") or []]
    flat_values = _finite_array([item for series in series_list for item in series])
    if flat_values.size == 0:
        raise RuntimeError("iqr payload requires finite values")

    layout = payload.get("layout") if isinstance(payload.get("layout"), dict) else {}
    display_positions = list(layout.get("display_positions") or list(range(1, len(labels) + 1)))
    display_labels = list(layout.get("display_labels") or labels)
    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), dict) else {}
    y_limits_spec = axis_spec.get("y_limits") if isinstance(axis_spec.get("y_limits"), dict) else {}
    y_min = _as_float(y_limits_spec.get("min"))
    y_max = _as_float(y_limits_spec.get("max"))
    if y_min is None:
        y_min = _as_float(resolved_render_spec.get("y_min"))
    if y_max is None:
        y_max = _as_float(resolved_render_spec.get("y_max"))
    if y_min is None:
        y_min = _as_float(y_limits.get("min"))
    if y_max is None:
        y_max = _as_float(y_limits.get("max"))
    if y_min is None:
        y_min = float(np.min(flat_values))
    if y_max is None:
        y_max = float(np.max(flat_values))
    if math.isclose(y_min, y_max):
        y_min -= 0.5
        y_max += 0.5

    x_limits_spec = axis_spec.get("x_limits") if isinstance(axis_spec.get("x_limits"), dict) else {}
    x_min = _as_float(x_limits_spec.get("min"))
    x_max = _as_float(x_limits_spec.get("max"))
    if x_min is None:
        x_min = _as_float(resolved_render_spec.get("x_min"))
    if x_max is None:
        x_max = _as_float(resolved_render_spec.get("x_max"))
    if x_min is None:
        x_min = 0.5
    if x_max is None:
        x_max = max(float(len(series_list)) + 0.5, 1.5)
    plot_rect = _resolved_plot_rect(
        resolved_render_spec,
        width=width,
        height=height,
        fallback_rect=(82, 88, width - 32, height - 92),
    )
    fallback_x_ticks = list(zip(display_positions, display_labels))
    fallback_y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(y_min, y_max, count=5)]
    x_ticks = _resolved_ticks(axis_spec.get("x_ticks") or resolved_render_spec.get("x_ticks"), fallback_x_ticks)
    y_ticks = _resolved_ticks(axis_spec.get("y_ticks") or resolved_render_spec.get("y_ticks"), fallback_y_ticks)
    _draw_axis_shell(
        image,
        draw,
        rect=plot_rect,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
        x_label=str(axis_spec.get("x_label") or resolved_render_spec.get("x_label") or payload.get("x_label") or "Group"),
        y_label=str(axis_spec.get("y_label") or resolved_render_spec.get("y_label") or payload.get("y_label") or "Measurement"),
        rotation=int(axis_spec.get("rotation") or layout.get("rotation") or 0),
        grid_axis=str(axis_spec.get("grid_axis") or resolved_render_spec.get("grid_axis") or "y"),
    )
    _draw_chart_title(
        image,
        draw,
        width=width,
        height=height,
        dpi=dpi,
        title_spec=title_spec,
        fallback_text=str(payload.get("title") or ""),
    )
    legend_items = (
        list(legend_spec.get("items") or [])
        if isinstance(legend_spec.get("items"), list)
        else list((payload.get("legend") or {}).get("items") or [])
    )
    legend_rect = _normalized_rect_to_pixels(
        legend_spec.get("rect") if isinstance(legend_spec.get("rect"), dict) else None,
        width=width,
        height=height,
    ) or (plot_rect[0], 24, plot_rect[2], 52)
    _draw_legend(draw, legend_rect, items=legend_items)

    reference_bands = resolved_render_spec.get("reference_bands") if isinstance(resolved_render_spec.get("reference_bands"), list) else None
    if reference_bands is None:
        one_sided = bool(payload.get("one_sided"))
        lsl = _as_float(payload.get("lsl"))
        usl = _as_float(payload.get("usl"))
        reference_bands = []
        if usl is not None and (lsl is not None or one_sided):
            reference_bands.append(
                {
                    "axis": "y",
                    "start": 0.0 if one_sided else lsl,
                    "end": usl,
                    "color": SUMMARY_PLOT_PALETTE["sigma_band"],
                    "alpha": 0.12,
                }
            )
    _draw_reference_bands(
        draw,
        rect=plot_rect,
        bands=list(reference_bands or []),
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
    )

    reference_lines = resolved_render_spec.get("reference_lines") if isinstance(resolved_render_spec.get("reference_lines"), list) else None
    if reference_lines is None:
        lsl = _as_float(payload.get("lsl"))
        usl = _as_float(payload.get("usl"))
        nominal = _as_float(payload.get("nominal"))
        reference_lines = [
            {
                "axis": "y",
                "value": line_value,
                "color": SUMMARY_PLOT_PALETTE["spec_limit"],
                "alpha": 0.82,
                "width": 2.0,
                "dash": [8, 5] if dashed else None,
            }
            for line_value, dashed in ((lsl, False), (usl, False), (nominal, True))
            if line_value is not None
        ]
    _draw_reference_lines(
        draw,
        rect=plot_rect,
        lines=list(reference_lines or []),
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
    )

    boxes = resolved_render_spec.get("boxes") if isinstance(resolved_render_spec.get("boxes"), list) else None
    if boxes is None and isinstance(resolved_render_spec.get("boxplots"), list):
        boxes = list(resolved_render_spec.get("boxplots") or [])
    if boxes is None:
        boxes = []
        for idx, series in enumerate(series_list, start=1):
            if series.size == 0:
                continue
            q1, median, q3 = np.percentile(series, [25, 50, 75])
            iqr = float(q3 - q1)
            lower_bound = float(q1 - (1.5 * iqr))
            upper_bound = float(q3 + (1.5 * iqr))
            whisker_low = float(np.min(series[series >= lower_bound])) if np.any(series >= lower_bound) else float(np.min(series))
            whisker_high = float(np.max(series[series <= upper_bound])) if np.any(series <= upper_bound) else float(np.max(series))
            outliers = series[(series < lower_bound) | (series > upper_bound)]
            boxes.append(
                {
                    "position": float(idx),
                    "q1": float(q1),
                    "median": float(median),
                    "q3": float(q3),
                    "whisker_low": float(whisker_low),
                    "whisker_high": float(whisker_high),
                    "outliers": [float(item) for item in outliers.tolist()],
                }
            )

    for box in boxes:
        if not isinstance(box, dict):
            continue
        position = _as_float(box.get("position"))
        q1 = _as_float(box.get("q1"))
        median = _as_float(box.get("median"))
        q3 = _as_float(box.get("q3"))
        whisker_low = _as_float(box.get("whisker_low"))
        whisker_high = _as_float(box.get("whisker_high"))
        if None in {position, q1, median, q3, whisker_low, whisker_high}:
            continue
        box_left_value = _as_float(box.get("box_left"))
        box_right_value = _as_float(box.get("box_right"))
        if box_left_value is not None and box_right_value is not None:
            box_left = _map_horizontal_box_coordinate(
                float(box_left_value),
                position=position,
                left_bound=box_left_value,
                right_bound=box_right_value,
                x_limits=(x_min, x_max),
                plot_left=plot_rect[0],
                plot_right=plot_rect[2],
            )
            box_right = _map_horizontal_box_coordinate(
                float(box_right_value),
                position=position,
                left_bound=box_left_value,
                right_bound=box_right_value,
                x_limits=(x_min, x_max),
                plot_left=plot_rect[0],
                plot_right=plot_rect[2],
            )
            center_x = (box_left + box_right) / 2.0
        else:
            center_x = _map_linear(float(position), x_min, x_max, plot_rect[0], plot_rect[2])
            box_half_width = max(12.0, (plot_rect[2] - plot_rect[0]) / max(10, len(series_list) * 6))
            box_left = center_x - box_half_width
            box_right = center_x + box_half_width
        box_top = _map_linear(float(q3), y_min, y_max, plot_rect[3], plot_rect[1])
        box_bottom = _map_linear(float(q1), y_min, y_max, plot_rect[3], plot_rect[1])
        median_y = _map_linear(float(median), y_min, y_max, plot_rect[3], plot_rect[1])
        whisker_low_y = _map_linear(float(whisker_low), y_min, y_max, plot_rect[3], plot_rect[1])
        whisker_high_y = _map_linear(float(whisker_high), y_min, y_max, plot_rect[3], plot_rect[1])
        edge_color = _hex_rgba(box.get("edge_color") or SUMMARY_PLOT_PALETTE["distribution_foreground"])
        edge_width = max(1, int(round(float(box.get("edge_width") or 2.0))))
        median_color = _hex_rgba(box.get("median_color") or SUMMARY_PLOT_PALETTE["central_tendency"])
        fill_color = _hex_rgba(box.get("fill_color") or SUMMARY_PLOT_PALETTE["distribution_base"], float(box.get("fill_alpha") or 0.45))
        cap_left_value = _as_float(box.get("cap_left"))
        cap_right_value = _as_float(box.get("cap_right"))
        if cap_left_value is not None and cap_right_value is not None:
            cap_left = _map_horizontal_box_coordinate(
                float(cap_left_value),
                position=position,
                left_bound=cap_left_value,
                right_bound=cap_right_value,
                x_limits=(x_min, x_max),
                plot_left=plot_rect[0],
                plot_right=plot_rect[2],
            )
            cap_right = _map_horizontal_box_coordinate(
                float(cap_right_value),
                position=position,
                left_bound=cap_left_value,
                right_bound=cap_right_value,
                x_limits=(x_min, x_max),
                plot_left=plot_rect[0],
                plot_right=plot_rect[2],
            )
        else:
            cap_left = box_left
            cap_right = box_right

        draw.rectangle((box_left, box_top, box_right, box_bottom), fill=fill_color, outline=edge_color, width=edge_width)
        draw.line((box_left, median_y, box_right, median_y), fill=median_color, width=edge_width)
        draw.line((center_x, whisker_high_y, center_x, box_top), fill=edge_color, width=edge_width)
        draw.line((center_x, box_bottom, center_x, whisker_low_y), fill=edge_color, width=edge_width)
        draw.line((cap_left, whisker_high_y, cap_right, whisker_high_y), fill=edge_color, width=edge_width)
        draw.line((cap_left, whisker_low_y, cap_right, whisker_low_y), fill=edge_color, width=edge_width)
        for outlier in list(box.get("outliers") or []):
            outlier_value = _as_float(outlier)
            if outlier_value is None:
                continue
            outlier_y = _map_linear(float(outlier_value), y_min, y_max, plot_rect[3], plot_rect[1])
            _draw_marker(
                draw,
                kind=str(box.get("outlier_marker") or "circle"),
                x=center_x,
                y=outlier_y,
                size=max(4, int(round(float(box.get("outlier_size") or 6.0)))),
                fill=_hex_rgba(box.get("outlier_color") or SUMMARY_PLOT_PALETTE["outlier"], float(box.get("outlier_alpha") or 1.0)),
            )

    return _encode_png(image)


def render_trend_png(payload: dict[str, Any]) -> bytes:
    width, height = _canvas_size(payload, default_width=1020, default_height=600)
    dpi = int(((payload.get("canvas") or {}) if isinstance(payload.get("canvas"), dict) else {}).get("dpi") or DEFAULT_DPI)
    image = Image.new("RGBA", (width, height), WHITE)
    draw = ImageDraw.Draw(image)

    resolved_render_spec = payload.get("resolved_render_spec") if isinstance(payload.get("resolved_render_spec"), dict) else {}
    axis_spec = resolved_render_spec.get("axes") if isinstance(resolved_render_spec.get("axes"), dict) else {}
    title_spec = resolved_render_spec.get("title") if isinstance(resolved_render_spec.get("title"), dict) else {}
    x_values = _finite_array(payload.get("x_values") or [])
    y_values = _finite_array(payload.get("y_values") or [])
    if x_values.size == 0 or y_values.size == 0:
        raise RuntimeError("trend payload requires finite x/y values")

    layout = payload.get("layout") if isinstance(payload.get("layout"), dict) else {}
    display_positions = list(layout.get("display_positions") or list(x_values))
    display_labels = list(layout.get("display_labels") or list(payload.get("labels") or []))
    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), dict) else {}
    y_limits_spec = axis_spec.get("y_limits") if isinstance(axis_spec.get("y_limits"), dict) else {}
    y_min = _as_float(y_limits_spec.get("min"))
    y_max = _as_float(y_limits_spec.get("max"))
    if y_min is None:
        y_min = _as_float(resolved_render_spec.get("y_min"))
    if y_max is None:
        y_max = _as_float(resolved_render_spec.get("y_max"))
    if y_min is None:
        y_min = _as_float(y_limits.get("min"))
    if y_max is None:
        y_max = _as_float(y_limits.get("max"))
    if y_min is None:
        y_min = float(np.min(y_values))
    if y_max is None:
        y_max = float(np.max(y_values))
    if math.isclose(y_min, y_max):
        y_min -= 0.5
        y_max += 0.5

    x_limits_spec = axis_spec.get("x_limits") if isinstance(axis_spec.get("x_limits"), dict) else {}
    x_min = _as_float(x_limits_spec.get("min"))
    x_max = _as_float(x_limits_spec.get("max"))
    if x_min is None:
        x_min = _as_float(resolved_render_spec.get("x_min"))
    if x_max is None:
        x_max = _as_float(resolved_render_spec.get("x_max"))
    if x_min is None:
        x_min = float(np.min(x_values))
    if x_max is None:
        x_max = float(np.max(x_values))
    if math.isclose(x_min, x_max):
        x_max += 1.0

    plot_rect = _resolved_plot_rect(
        resolved_render_spec,
        width=width,
        height=height,
        fallback_rect=(82, 88, width - 32, height - 92),
    )
    fallback_x_ticks = list(zip(display_positions, display_labels))
    fallback_y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(y_min, y_max, count=5)]
    x_ticks = _resolved_ticks(axis_spec.get("x_ticks") or resolved_render_spec.get("x_ticks"), fallback_x_ticks)
    y_ticks = _resolved_ticks(axis_spec.get("y_ticks") or resolved_render_spec.get("y_ticks"), fallback_y_ticks)
    _draw_axis_shell(
        image,
        draw,
        rect=plot_rect,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
        x_label=str(axis_spec.get("x_label") or resolved_render_spec.get("x_label") or payload.get("x_label") or "Sample #"),
        y_label=str(axis_spec.get("y_label") or resolved_render_spec.get("y_label") or payload.get("y_label") or "Measurement"),
        rotation=int(axis_spec.get("rotation") or layout.get("rotation") or 0),
        grid_axis=str(axis_spec.get("grid_axis") or resolved_render_spec.get("grid_axis") or "y"),
    )
    _draw_chart_title(
        image,
        draw,
        width=width,
        height=height,
        dpi=dpi,
        title_spec=title_spec,
        fallback_text=str(payload.get("title") or ""),
    )

    reference_lines = resolved_render_spec.get("reference_lines") if isinstance(resolved_render_spec.get("reference_lines"), list) else None
    if reference_lines is None:
        reference_lines = [
            {
                "axis": "y",
                "value": numeric,
                "color": SUMMARY_PLOT_PALETTE["spec_limit"],
                "alpha": 0.82,
                "width": 2.0,
            }
            for limit_value in list(payload.get("horizontal_limits") or [])
            if (numeric := _as_float(limit_value)) is not None
        ]
    _draw_reference_lines(
        draw,
        rect=plot_rect,
        lines=list(reference_lines or []),
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
    )

    points = resolved_render_spec.get("points") if isinstance(resolved_render_spec.get("points"), list) else None
    if points is None:
        points = [
            {
                "x": float(x_value),
                "y": float(y_value),
                "marker": "circle",
                "size": 6,
                "color": SUMMARY_PLOT_PALETTE["distribution_foreground"],
            }
            for x_value, y_value in zip(x_values.tolist(), y_values.tolist())
        ]
    for point in points:
        if not isinstance(point, dict):
            continue
        x_value = _as_float(point.get("x"))
        y_value = _as_float(point.get("y"))
        if x_value is None or y_value is None:
            continue
        px = _map_linear(float(x_value), x_min, x_max, plot_rect[0], plot_rect[2])
        py = _map_linear(float(y_value), y_min, y_max, plot_rect[3], plot_rect[1])
        _draw_marker(
            draw,
            kind=str(point.get("marker") or "circle"),
            x=px,
            y=py,
            size=max(4, int(point.get("size") or 6)),
            fill=_hex_rgba(point.get("color") or SUMMARY_PLOT_PALETTE["distribution_foreground"], float(point.get("alpha") or 1.0)),
        )

    return _encode_png(image)

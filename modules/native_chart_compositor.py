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


def render_histogram_png(payload: dict[str, Any]) -> bytes:
    values = _finite_array(payload.get("values") or [])
    if values.size == 0:
        raise RuntimeError("histogram payload requires finite values")

    width, height = _canvas_size(payload)
    image = Image.new("RGBA", (width, height), WHITE)
    draw = ImageDraw.Draw(image)

    x_view = payload.get("x_view") if isinstance(payload.get("x_view"), dict) else {}
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
    max_count = float(max(1, int(np.max(counts)) if counts.size else 1))

    visual_metadata = payload.get("visual_metadata") if isinstance(payload.get("visual_metadata"), dict) else {}
    overlays_meta = visual_metadata.get("modeled_overlays") if isinstance(visual_metadata.get("modeled_overlays"), dict) else {}
    overlay_rows = list(overlays_meta.get("rows") or [])
    compact_mode = not bool(list((visual_metadata.get("summary_stats_table") or {}).get("rows") or [])) and not bool(list(visual_metadata.get("annotation_rows") or [])) and not bool(overlay_rows)
    plot_left = 86
    plot_top = 72 if compact_mode else 104
    plot_bottom = height - 92
    table_width = 0 if compact_mode else int(width * 0.31)
    plot_right = width - table_width - 28
    plot_rect = (plot_left, plot_top, plot_right, plot_bottom)
    for overlay in overlay_rows:
        if str(overlay.get("kind")) == "curve":
            curve_y = _finite_array(overlay.get("y") or [])
            if curve_y.size:
                max_count = max(max_count, float(np.max(curve_y)))
    max_count *= 1.08

    x_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(x_min, x_max, count=6)]
    y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(0.0, max_count, count=5)]
    _draw_axis_shell(
        image,
        draw,
        rect=plot_rect,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_limits=(x_min, x_max),
        y_limits=(0.0, max_count),
        x_label=str((payload.get("style") or {}).get("axis_label_x") or "Measurement"),
        y_label=str((payload.get("style") or {}).get("axis_label_y") or "Count"),
        rotation=0,
        grid_axis=str((payload.get("style") or {}).get("grid_axis") or "y"),
    )

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
        x_values = _finite_array(overlay.get("x") or [])
        y_values = _finite_array(overlay.get("y") or [])
        if x_values.size == 0 or y_values.size == 0 or x_values.size != y_values.size:
            continue
        points = [
            (
                _map_linear(float(x), x_min, x_max, plot_left, plot_right),
                _map_linear(float(y), 0.0, max_count, plot_bottom, plot_top),
            )
            for x, y in zip(x_values, y_values)
        ]
        color = _hex_rgba(overlay.get("color") or SUMMARY_PLOT_PALETTE["density_line"], float(overlay.get("alpha") or 1.0))
        width_px = max(1, int(round(float(overlay.get("linewidth") or 1.0))))
        if bool(overlay.get("fill_to_baseline")):
            polygon = list(points)
            polygon.append((points[-1][0], plot_bottom))
            polygon.append((points[0][0], plot_bottom))
            draw.polygon(polygon, fill=_hex_rgba(overlay.get("fill_color") or overlay.get("color") or SUMMARY_PLOT_PALETTE["spec_limit"], float(overlay.get("fill_alpha") or 0.1)))
        if overlay.get("dash"):
            _draw_dashed_line(draw, points, fill=color, width=width_px, dash=tuple(int(item) for item in overlay.get("dash")))
        else:
            draw.line(points, fill=color, width=width_px)
        if kind == "curve_note":
            _draw_annotation_box(
                image,
                draw,
                text=str(overlay.get("label") or ""),
                anchor_x=plot_left + 18,
                base_y=plot_bottom - 36,
                color=_hex_rgba("#4d5968"),
                font=_font(9),
                plot_left=plot_left,
                plot_right=plot_right,
                leader_y=None,
                align="left",
            )

    mean_line = payload.get("mean_line") if isinstance(payload.get("mean_line"), dict) else {}
    mean_value = _as_float(mean_line.get("value"))
    if mean_value is not None:
        mean_x = _map_linear(mean_value, x_min, x_max, plot_left, plot_right)
        _draw_dashed_line(
            draw,
            [(mean_x, plot_top), (mean_x, plot_bottom)],
            fill=_hex_rgba(SUMMARY_PLOT_PALETTE["central_tendency"], float(mean_line.get("alpha") or 0.48)),
            width=max(1, int(round(float(mean_line.get("linewidth") or 1.3)))),
            dash=(8, 5),
        )

    for line_meta in list(visual_metadata.get("specification_lines") or []):
        if not isinstance(line_meta, dict) or not line_meta.get("enabled"):
            continue
        line_value = _as_float(line_meta.get("value"))
        if line_value is None:
            continue
        x = _map_linear(line_value, x_min, x_max, plot_left, plot_right)
        draw.line((x, plot_top, x, plot_bottom - 26), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["spec_limit"], 0.82), width=2)

    title_font = _font(15, bold=True)
    _draw_multiline_text(draw, (54, 22), str(payload.get("title") or ""), font=title_font, fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]))

    for annotation in list(visual_metadata.get("annotation_rows") or []):
        if not isinstance(annotation, dict):
            continue
        label_text = str(annotation.get("text") or annotation.get("label") or "")
        x_value = _as_float(annotation.get("x"))
        if not label_text or x_value is None:
            continue
        row_index = int(annotation.get("row_index") or 0)
        kind = str(annotation.get("kind") or "").strip().lower()
        align = str((annotation.get("placement_hint") or {}).get("ha") or "center")
        color = _hex_rgba(annotation.get("color") or (SUMMARY_PLOT_PALETTE["spec_limit"] if kind in {"lsl", "usl"} else SUMMARY_PLOT_PALETTE["annotation_text"]))
        leader_y = plot_top + 4
        _draw_annotation_box(
            image,
            draw,
            text=label_text,
            anchor_x=_map_linear(x_value, x_min, x_max, plot_left, plot_right),
            base_y=44 + (row_index * 26),
            color=color,
            font=_font(10),
            plot_left=plot_left,
            plot_right=plot_right,
            leader_y=leader_y,
            align=align,
        )

    if not compact_mode:
        table_rect = (plot_right + 20, plot_top - 10, width - 18, height - 26)
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
    image = Image.new("RGBA", (width, height), WHITE)
    draw = ImageDraw.Draw(image)

    legend_items = list((payload.get("legend") or {}).get("items") or [])
    plot_rect = (82, 88, width - 32, height - 92)
    layout = payload.get("layout") if isinstance(payload.get("layout"), dict) else {}
    rotation = int(layout.get("rotation") or 0)
    labels = [str(item) for item in payload.get("labels") or []]
    display_positions = list(layout.get("display_positions") or list(range(len(labels))))
    display_labels = list(layout.get("display_labels") or labels)
    render_mode = str(payload.get("render_mode") or "violin")

    all_values = _finite_array([value for series in payload.get("series") or [] for value in series])
    if all_values.size == 0 and render_mode == "scatter":
        all_values = _finite_array(payload.get("y_values") or [])
    if all_values.size == 0:
        raise RuntimeError("distribution payload requires finite values")
    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), dict) else {}
    y_min = _as_float(y_limits.get("min"))
    y_max = _as_float(y_limits.get("max"))
    if y_min is None:
        y_min = float(np.min(all_values))
    if y_max is None:
        y_max = float(np.max(all_values))
    if math.isclose(y_min, y_max):
        y_min -= 0.5
        y_max += 0.5

    x_domain = payload.get("x_domain") if isinstance(payload.get("x_domain"), dict) else {}
    x_min = _as_float(x_domain.get("min"))
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

    x_ticks = list(zip(display_positions, display_labels))
    y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(y_min, y_max, count=5)]
    _draw_axis_shell(
        image,
        draw,
        rect=plot_rect,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
        x_label=str(payload.get("x_label") or "Group"),
        y_label=str(payload.get("y_label") or "Measurement"),
        rotation=rotation,
        grid_axis="y",
    )
    _draw_multiline_text(draw, (54, 24), str(payload.get("title") or ""), font=_font(14, bold=True), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]))
    _draw_legend(draw, (plot_rect[0], 24, plot_rect[2], 52), items=legend_items)

    one_sided = bool(payload.get("one_sided"))
    lsl = _as_float(payload.get("lsl"))
    usl = _as_float(payload.get("usl"))
    nominal = _as_float(payload.get("nominal"))
    if usl is not None and (lsl is not None or one_sided):
        band_bottom = _map_linear(0.0 if one_sided else lsl, y_min, y_max, plot_rect[3], plot_rect[1])
        band_top = _map_linear(usl, y_min, y_max, plot_rect[3], plot_rect[1])
        draw.rectangle((plot_rect[0], band_top, plot_rect[2], band_bottom), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["sigma_band"], 0.12))
    for line_value, dashed in ((lsl, False), (usl, False), (nominal if payload.get("include_nominal") else None, True)):
        if line_value is None:
            continue
        y = _map_linear(line_value, y_min, y_max, plot_rect[3], plot_rect[1])
        if dashed:
            _draw_dashed_line(draw, [(plot_rect[0], y), (plot_rect[2], y)], fill=_hex_rgba(SUMMARY_PLOT_PALETTE["spec_limit"], 0.82), width=2, dash=(8, 5))
        else:
            draw.line((plot_rect[0], y, plot_rect[2], y), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["spec_limit"], 0.82), width=2)

    if render_mode == "scatter":
        x_values = _finite_array(payload.get("x_values") or [])
        y_values = _finite_array(payload.get("y_values") or [])
        for x_value, y_value in zip(x_values, y_values):
            x = _map_linear(float(x_value), x_min, x_max, plot_rect[0], plot_rect[2])
            y = _map_linear(float(y_value), y_min, y_max, plot_rect[3], plot_rect[1])
            _draw_marker(draw, kind="circle", x=x, y=y, size=6, fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]))
        return _encode_png(image)

    series_list = [_finite_array(series) for series in payload.get("series") or []]
    density_peak = 0.0
    for series in series_list:
        if series.size >= 3 and gaussian_kde is not None and np.std(series, ddof=1) > 0:
            try:
                density_peak = max(density_peak, float(np.max(gaussian_kde(series)(np.linspace(y_min, y_max, 96)))))
            except Exception:
                continue
    density_peak = max(density_peak, 1.0)
    positions = list(payload.get("positions") or list(range(len(series_list))))
    gap = (plot_rect[2] - plot_rect[0]) / max(2, len(series_list))
    violin_half_width = max(10.0, gap * 0.22)

    for index, series in enumerate(series_list):
        if series.size == 0:
            continue
        center_value = float(positions[index]) if index < len(positions) else float(index)
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

    annotation_style = payload.get("annotation_style") if isinstance(payload.get("annotation_style"), dict) else {}
    violin_annotations = list(payload.get("violin_annotations") or [])
    show_minmax = bool(annotation_style.get("show_minmax", True))
    show_sigma = bool(annotation_style.get("show_sigma", True))
    for item in violin_annotations:
        xpos = float(item.get("position"))
        center_x = _map_linear(xpos, x_min, x_max, plot_rect[0], plot_rect[2])
        mean_y = _map_linear(float(item.get("mean")), y_min, y_max, plot_rect[3], plot_rect[1])
        _draw_marker(draw, kind="circle", x=center_x, y=mean_y, size=max(8, int(annotation_style.get("mean_marker_size") or 14) // 2), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["central_tendency"]))
        _draw_annotation_box(
            image,
            draw,
            text=f"u={float(item.get('mean')):.3f}",
            anchor_x=center_x + 6,
            base_y=mean_y - 20,
            color=_hex_rgba(SUMMARY_PLOT_PALETTE["annotation_text"]),
            font=_font(max(8, int(annotation_style.get("font_size") or 8))),
            plot_left=plot_rect[0],
            plot_right=plot_rect[2],
            leader_y=mean_y,
            align="left",
        )
        if show_minmax:
            minimum_y = _map_linear(float(item.get("minimum")), y_min, y_max, plot_rect[3], plot_rect[1])
            maximum_y = _map_linear(float(item.get("maximum")), y_min, y_max, plot_rect[3], plot_rect[1])
            _draw_marker(draw, kind="triangle_down", x=center_x, y=minimum_y, size=8, fill=_hex_rgba(SUMMARY_PLOT_PALETTE["annotation_text"]))
            _draw_marker(draw, kind="triangle_up", x=center_x, y=maximum_y, size=8, fill=_hex_rgba(SUMMARY_PLOT_PALETTE["annotation_text"]))
        if show_sigma and item.get("show_sigma_segment"):
            sigma_start = _map_linear(float(item.get("sigma_start")), y_min, y_max, plot_rect[3], plot_rect[1])
            sigma_high = _map_linear(float(item.get("sigma_high")), y_min, y_max, plot_rect[3], plot_rect[1])
            _draw_dashed_line(draw, [(center_x, sigma_start), (center_x, sigma_high)], fill=_hex_rgba(SUMMARY_PLOT_PALETTE["sigma_band"]), width=1, dash=(4, 4))

    return _encode_png(image)


def render_iqr_png(payload: dict[str, Any]) -> bytes:
    width, height = _canvas_size(payload, default_width=1080, default_height=600)
    image = Image.new("RGBA", (width, height), WHITE)
    draw = ImageDraw.Draw(image)

    labels = [str(item) for item in payload.get("labels") or []]
    series_list = [_finite_array(series) for series in payload.get("series") or []]
    flat_values = _finite_array([item for series in series_list for item in series])
    if flat_values.size == 0:
        raise RuntimeError("iqr payload requires finite values")

    layout = payload.get("layout") if isinstance(payload.get("layout"), dict) else {}
    rotation = int(layout.get("rotation") or 0)
    display_positions = list(layout.get("display_positions") or list(range(1, len(labels) + 1)))
    display_labels = list(layout.get("display_labels") or labels)
    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), dict) else {}
    y_min = _as_float(y_limits.get("min")) or float(np.min(flat_values))
    y_max = _as_float(y_limits.get("max")) or float(np.max(flat_values))
    if math.isclose(y_min, y_max):
        y_min -= 0.5
        y_max += 0.5

    x_min = 0.5
    x_max = max(float(len(series_list)) + 0.5, 1.5)
    plot_rect = (82, 88, width - 32, height - 92)
    x_ticks = list(zip(display_positions, display_labels))
    y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(y_min, y_max, count=5)]
    _draw_axis_shell(
        image,
        draw,
        rect=plot_rect,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
        x_label=str(payload.get("x_label") or "Group"),
        y_label=str(payload.get("y_label") or "Measurement"),
        rotation=rotation,
        grid_axis="y",
    )
    _draw_multiline_text(draw, (54, 24), str(payload.get("title") or ""), font=_font(14, bold=True), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]))
    _draw_legend(draw, (plot_rect[0], 24, plot_rect[2], 52), items=list((payload.get("legend") or {}).get("items") or []))

    one_sided = bool(payload.get("one_sided"))
    lsl = _as_float(payload.get("lsl"))
    usl = _as_float(payload.get("usl"))
    nominal = _as_float(payload.get("nominal"))
    if usl is not None and (lsl is not None or one_sided):
        band_bottom = _map_linear(0.0 if one_sided else lsl, y_min, y_max, plot_rect[3], plot_rect[1])
        band_top = _map_linear(usl, y_min, y_max, plot_rect[3], plot_rect[1])
        draw.rectangle((plot_rect[0], band_top, plot_rect[2], band_bottom), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["sigma_band"], 0.12))
    for line_value, dashed in ((lsl, False), (usl, False), (nominal, True)):
        if line_value is None:
            continue
        y = _map_linear(line_value, y_min, y_max, plot_rect[3], plot_rect[1])
        if dashed:
            _draw_dashed_line(draw, [(plot_rect[0], y), (plot_rect[2], y)], fill=_hex_rgba(SUMMARY_PLOT_PALETTE["spec_limit"], 0.82), width=2, dash=(8, 5))
        else:
            draw.line((plot_rect[0], y, plot_rect[2], y), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["spec_limit"], 0.82), width=2)

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

        center_x = _map_linear(float(idx), x_min, x_max, plot_rect[0], plot_rect[2])
        box_half_width = max(12.0, (plot_rect[2] - plot_rect[0]) / max(10, len(series_list) * 6))
        box_top = _map_linear(float(q3), y_min, y_max, plot_rect[3], plot_rect[1])
        box_bottom = _map_linear(float(q1), y_min, y_max, plot_rect[3], plot_rect[1])
        median_y = _map_linear(float(median), y_min, y_max, plot_rect[3], plot_rect[1])
        whisker_low_y = _map_linear(float(whisker_low), y_min, y_max, plot_rect[3], plot_rect[1])
        whisker_high_y = _map_linear(float(whisker_high), y_min, y_max, plot_rect[3], plot_rect[1])

        draw.rectangle((center_x - box_half_width, box_top, center_x + box_half_width, box_bottom), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_base"], 0.45), outline=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]), width=2)
        draw.line((center_x - box_half_width, median_y, center_x + box_half_width, median_y), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["central_tendency"]), width=2)
        draw.line((center_x, whisker_high_y, center_x, box_top), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]), width=2)
        draw.line((center_x, box_bottom, center_x, whisker_low_y), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]), width=2)
        draw.line((center_x - 8, whisker_high_y, center_x + 8, whisker_high_y), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]), width=2)
        draw.line((center_x - 8, whisker_low_y, center_x + 8, whisker_low_y), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]), width=2)
        for outlier in outliers:
            outlier_y = _map_linear(float(outlier), y_min, y_max, plot_rect[3], plot_rect[1])
            _draw_marker(draw, kind="circle", x=center_x, y=outlier_y, size=6, fill=_hex_rgba(SUMMARY_PLOT_PALETTE["outlier"]))

    return _encode_png(image)


def render_trend_png(payload: dict[str, Any]) -> bytes:
    width, height = _canvas_size(payload, default_width=1020, default_height=600)
    image = Image.new("RGBA", (width, height), WHITE)
    draw = ImageDraw.Draw(image)

    x_values = _finite_array(payload.get("x_values") or [])
    y_values = _finite_array(payload.get("y_values") or [])
    if x_values.size == 0 or y_values.size == 0:
        raise RuntimeError("trend payload requires finite x/y values")

    layout = payload.get("layout") if isinstance(payload.get("layout"), dict) else {}
    rotation = int(layout.get("rotation") or 0)
    display_positions = list(layout.get("display_positions") or list(x_values))
    display_labels = list(layout.get("display_labels") or list(payload.get("labels") or []))
    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), dict) else {}
    y_min = _as_float(y_limits.get("min")) or float(np.min(y_values))
    y_max = _as_float(y_limits.get("max")) or float(np.max(y_values))
    if math.isclose(y_min, y_max):
        y_min -= 0.5
        y_max += 0.5

    x_min = float(np.min(x_values))
    x_max = float(np.max(x_values))
    if math.isclose(x_min, x_max):
        x_max += 1.0

    plot_rect = (82, 88, width - 32, height - 92)
    x_ticks = list(zip(display_positions, display_labels))
    y_ticks = [(tick, _format_tick(tick)) for tick in _line_ticks(y_min, y_max, count=5)]
    _draw_axis_shell(
        image,
        draw,
        rect=plot_rect,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        x_limits=(x_min, x_max),
        y_limits=(y_min, y_max),
        x_label=str(payload.get("x_label") or "Sample #"),
        y_label=str(payload.get("y_label") or "Measurement"),
        rotation=rotation,
        grid_axis="y",
    )
    _draw_multiline_text(draw, (54, 24), str(payload.get("title") or ""), font=_font(14, bold=True), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]))

    for limit_value in list(payload.get("horizontal_limits") or []):
        numeric = _as_float(limit_value)
        if numeric is None:
            continue
        y = _map_linear(numeric, y_min, y_max, plot_rect[3], plot_rect[1])
        draw.line((plot_rect[0], y, plot_rect[2], y), fill=_hex_rgba(SUMMARY_PLOT_PALETTE["spec_limit"], 0.82), width=2)

    for x_value, y_value in zip(x_values, y_values):
        px = _map_linear(float(x_value), x_min, x_max, plot_rect[0], plot_rect[2])
        py = _map_linear(float(y_value), y_min, y_max, plot_rect[3], plot_rect[1])
        _draw_marker(draw, kind="circle", x=px, y=py, size=6, fill=_hex_rgba(SUMMARY_PLOT_PALETTE["distribution_foreground"]))

    return _encode_png(image)

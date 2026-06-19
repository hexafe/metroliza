"""Small helpers for native XlsxWriter chart creation and insertion."""

from __future__ import annotations

from io import BytesIO
from typing import Any


def create_workbook_chart(workbook: Any, chart_type: str, *, subtype: str | None = None) -> Any:
    """Create a workbook chart from a normalized type/subtype pair."""

    chart_spec: dict[str, str] = {"type": str(chart_type)}
    if subtype:
        chart_spec["subtype"] = str(subtype)
    return workbook.add_chart(chart_spec)


def apply_chart_options(
    chart: Any,
    *,
    title: dict[str, Any] | None = None,
    x_axis: dict[str, Any] | None = None,
    y_axis: dict[str, Any] | None = None,
    legend: dict[str, Any] | None = None,
    size: dict[str, Any] | None = None,
    style: int | None = None,
) -> None:
    """Apply common XlsxWriter chart options when provided."""

    if title is not None:
        chart.set_title(title)
    if x_axis is not None:
        chart.set_x_axis(x_axis)
    if y_axis is not None:
        chart.set_y_axis(y_axis)
    if legend is not None:
        chart.set_legend(legend)
    if size is not None:
        chart.set_size(size)
    if style is not None:
        chart.set_style(style)


def insert_chart(
    worksheet: Any,
    row: int,
    column: int,
    chart: Any,
    *,
    x_offset: int | None = None,
    y_offset: int | None = None,
    x_scale: float | None = None,
    y_scale: float | None = None,
) -> None:
    """Insert a chart with only explicitly requested placement options."""

    options: dict[str, Any] = {}
    if x_offset is not None:
        options["x_offset"] = x_offset
    if y_offset is not None:
        options["y_offset"] = y_offset
    if x_scale is not None:
        options["x_scale"] = x_scale
    if y_scale is not None:
        options["y_scale"] = y_scale
    worksheet.insert_chart(int(row), int(column), chart, options)


def compute_image_scale_to_fit(
    image_data: BytesIO,
    *,
    available_cols: int,
    available_rows: int,
    px_per_col: float = 64.0,
    px_per_row: float = 20.0,
    padding_ratio: float = 0.96,
) -> float:
    """Return a uniform image scale that keeps an inserted bitmap inside a slot."""

    try:
        from PIL import Image
    except Exception:  # pragma: no cover - Pillow is expected in runtime builds
        return 1.0

    cursor = image_data.tell()
    try:
        image_data.seek(0)
        with Image.open(image_data) as image:
            width_px, height_px = image.size
    finally:
        image_data.seek(cursor)

    if width_px <= 0 or height_px <= 0:
        return 1.0

    max_width_px = max(1.0, float(available_cols) * float(px_per_col) * float(padding_ratio))
    max_height_px = max(1.0, float(available_rows) * float(px_per_row) * float(padding_ratio))
    return min(1.0, max_width_px / float(width_px), max_height_px / float(height_px))


def insert_image_fit_to_slot(
    worksheet: Any,
    row: int,
    column: int,
    image_name: str,
    image_data: BytesIO,
    *,
    available_cols: int,
    available_rows: int,
    x_offset: int | None = None,
    y_offset: int | None = None,
) -> None:
    """Insert an image scaled to stay within a reserved worksheet slot."""

    scale = compute_image_scale_to_fit(
        image_data,
        available_cols=available_cols,
        available_rows=available_rows,
    )
    options: dict[str, Any] = {
        "image_data": image_data,
        "x_scale": scale,
        "y_scale": scale,
    }
    if x_offset is not None:
        options["x_offset"] = x_offset
    if y_offset is not None:
        options["y_offset"] = y_offset
    worksheet.insert_image(int(row), int(column), str(image_name), options)

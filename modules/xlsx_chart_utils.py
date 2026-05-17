"""Small helpers for native XlsxWriter chart creation and insertion."""

from __future__ import annotations

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

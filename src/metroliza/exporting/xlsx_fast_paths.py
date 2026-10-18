"""Faster, byte-identical replacements for hot XlsxWriter loops (#1124).

Every function here reproduces what the corresponding XlsxWriter code writes,
for the common cell and chart-cache shapes, and hands anything else back to the
original implementation.  They are only installed by
``xlsx_bulk_sheet.enable_bulk_rows`` for XlsxWriter series that were verified
against these internals.
"""

from __future__ import annotations

import math
import types
from typing import Any

from xlsxwriter.worksheet import CellNumberTuple, CellStringTuple, xl_rowcol_to_cell_fast

_STRING_CELL_LIMIT = 32767
_XLS_ROW_MAX = 1048576
_XLS_COL_MAX = 16384
_NUMBER_TYPES = frozenset({int, float})


def is_plain_xml_text(token: Any) -> bool:
    """Return whether ``token`` needs no XML or control-character escaping."""
    return (
        type(token) is str
        and token.isascii()
        and token.isprintable()
        and "&" not in token
        and "<" not in token
        and ">" not in token
        and "_x" not in token
    )


def _point_markup(chart: Any, index: int, token: Any) -> str:
    text = token if is_plain_xml_text(token) else chart._escape_control_characters(chart._escape_data(token))
    return f'<c:pt idx="{index}"><c:v>{text}</c:v></c:pt>'


def fast_write_num_cache(chart: Any, data: Any) -> None:
    """Write ``<c:numCache>`` exactly like ``Chart._write_num_cache``."""
    count = len(data) if data else 0
    parts = [f'<c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="{count}"/>']
    for index in range(count):
        token = data[index]
        if token is None:
            continue
        try:
            float(token)
        except ValueError:
            token = 0
        parts.append(_point_markup(chart, index, token))
    parts.append("</c:numCache>")
    chart.fh.write("".join(parts))


def fast_write_str_cache(chart: Any, data: Any) -> None:
    """Write ``<c:strCache>`` exactly like ``Chart._write_str_cache``."""
    count = len(data)
    parts = [f'<c:strCache><c:ptCount val="{count}"/>']
    for index in range(count):
        token = data[index]
        if token is not None:
            parts.append(_point_markup(chart, index, token))
    parts.append("</c:strCache>")
    chart.fh.write("".join(parts))


def accelerate_chart(chart: Any) -> Any:
    """Install the fast chart-cache writers on one XlsxWriter chart instance."""
    if hasattr(chart, "_write_num_cache") and hasattr(chart, "_write_str_cache"):
        chart._write_num_cache = types.MethodType(fast_write_num_cache, chart)
        chart._write_str_cache = types.MethodType(fast_write_str_cache, chart)
    return chart


def cell_style(worksheet: Any, row: int, col: int, cell: Any) -> str:
    """Return the ``s=`` attribute XlsxWriter would add to a ``<c>`` element."""
    if cell.format:
        return f' s="{cell.format._get_xf_index()}"'
    row_properties = worksheet.set_rows.get(row)
    if row_properties and row_properties[1]:
        return f' s="{row_properties[1]._get_xf_index()}"'
    column_info = worksheet.col_info.get(col)
    if column_info is not None and column_info[1] is not None:
        return f' s="{column_info[1]._get_xf_index()}"'
    return ""


def fast_cell_markup(worksheet: Any, row: int, col: int, cell: Any) -> str | None:
    """Return ``<c>`` markup for plain number/string cells, else ``None``."""
    kind = cell.__class__
    if kind is CellNumberTuple:
        reference = xl_rowcol_to_cell_fast(row, col)
        return f'<c r="{reference}"{cell_style(worksheet, row, col, cell)}><v>{cell.number:.16G}</v></c>'
    if kind is CellStringTuple and not worksheet.constant_memory:
        reference = xl_rowcol_to_cell_fast(row, col)
        return f'<c r="{reference}"{cell_style(worksheet, row, col, cell)} t="s"><v>{cell.string}</v></c>'
    return None


def _column_values_are_plain(worksheet: Any, values: list) -> bool:
    kinds = set(map(type, values))
    if kinds == {str}:
        if worksheet.strings_to_formulas or worksheet.strings_to_urls or worksheet.strings_to_numbers:
            return False
        return all(
            text and len(text) <= _STRING_CELL_LIMIT and not (text.startswith("{=") and text.endswith("}"))
            for text in values
        )
    if kinds <= _NUMBER_TYPES:
        try:
            return all(map(math.isfinite, values))
        except OverflowError:
            return False
    return False


def write_plain_column(worksheet: Any, row: int, col: int, values: list) -> bool:
    """Store a column of plain numbers/strings like ``write_column`` would.

    Returns ``False`` (nothing written) for anything ``write_column`` treats
    specially: blanks, formulas, NaN/inf, mixed types, out-of-range cells.
    """
    if not values or worksheet.constant_memory or worksheet.write_handlers:
        return False
    if not _column_values_are_plain(worksheet, values):
        return False
    last_row = row + len(values) - 1
    if row < 0 or col < 0 or last_row >= _XLS_ROW_MAX or col >= _XLS_COL_MAX:
        return False
    worksheet._check_dimensions(row, col)
    worksheet._check_dimensions(last_row, col)
    table = worksheet.table
    if type(values[0]) is str:
        shared_index = worksheet.str_table._get_shared_string_index
        for offset, text in enumerate(values, start=row):
            table[offset][col] = CellStringTuple(shared_index(text), None)
    else:
        for offset, number in enumerate(values, start=row):
            table[offset][col] = CellNumberTuple(number, None)
    return True

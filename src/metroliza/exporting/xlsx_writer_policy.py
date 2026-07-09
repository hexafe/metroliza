"""Shared safety policy for XlsxWriter-backed exports."""

from __future__ import annotations

from typing import Any


def xlsxwriter_workbook_options() -> dict[str, bool]:
    """Return safe defaults for workbooks containing imported source data."""

    return {
        "nan_inf_to_errors": True,
        "strings_to_formulas": False,
        "strings_to_urls": False,
    }


def pandas_xlsxwriter_engine_kwargs() -> dict[str, dict[str, bool]]:
    """Return the pandas ``ExcelWriter`` wrapper for the shared options."""

    return {"options": xlsxwriter_workbook_options()}


def write_untrusted_xlsx_cell(
    worksheet: Any,
    row: int,
    column: int,
    value: Any,
    cell_format: Any = None,
) -> None:
    """Write imported strings literally while preserving native scalar types."""

    if isinstance(value, str):
        worksheet.write_string(row, column, value, cell_format)
        return
    worksheet.write(row, column, value, cell_format)


__all__ = [
    "pandas_xlsxwriter_engine_kwargs",
    "write_untrusted_xlsx_cell",
    "xlsxwriter_workbook_options",
]

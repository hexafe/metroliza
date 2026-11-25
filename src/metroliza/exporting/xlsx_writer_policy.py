"""Shared safety policy for XlsxWriter-backed exports."""

from __future__ import annotations

from typing import Any

from xlsxwriter.worksheet import Worksheet


class LiteralSourceWorksheet(Worksheet):
    """Honor the workbook's disabled formula conversion for array-like text."""

    def _write_token_as_string(self, token, row, col, *args):
        # The regular strings_to_formulas option misses the brace syntax in
        # XlsxWriter. This also covers the scalar and column fallbacks.
        if not self.strings_to_formulas and str.startswith(token, "{=") and str.endswith(token, "}"):
            return self.write_string(row, col, *args)
        return super()._write_token_as_string(token, row, col, *args)


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
    "LiteralSourceWorksheet",
    "pandas_xlsxwriter_engine_kwargs",
    "write_untrusted_xlsx_cell",
    "xlsxwriter_workbook_options",
]

"""Bulk XLSX writes for flat tabular frames, preserving pandas export semantics."""

from __future__ import annotations

import numpy as np


def _column_kind(series):
    from pandas.api.types import infer_dtype, is_datetime64_dtype

    if is_datetime64_dtype(series.dtype):
        return "datetime"
    kind = infer_dtype(series, skipna=True)
    return "object-datetime" if kind == "datetime" else kind


def _column_values(series, kind):
    if kind == "boolean":
        from pandas import isna

        # Object arrays retain NumPy bool scalars, which XlsxWriter treats as
        # numbers. Match pandas' Python-bool conversion without filling blanks.
        return ["" if isna(value) else bool(value) for value in series]
    values = series.to_numpy(dtype=object, na_value="")
    if kind == "string":
        # write_column stops on truncation (-2); truncate first, like pandas'
        # individual cell writes, so subsequent rows are still exported.
        return [value[:32767] if isinstance(value, str) else value for value in values]
    if kind in {"floating", "mixed-integer-float"}:
        values = values.copy()
        values[series.eq(np.inf).fillna(False).to_numpy(dtype=bool)] = "inf"
        values[series.eq(-np.inf).fillna(False).to_numpy(dtype=bool)] = "-inf"
    return values


def _plain_string_dict(value):
    return type(value) is dict and all(type(key) is str for key in value)


def _bulk_workbook(writer):
    from pandas.io.excel._xlsxwriter import XlsxWriter
    from xlsxwriter import Workbook
    from xlsxwriter.worksheet import Worksheet

    if type(writer) is not XlsxWriter:
        return
    metadata = vars(writer)
    if not _plain_string_dict(metadata):
        return
    book = metadata.get('_book')
    if type(book) is not Workbook:
        return
    metadata = vars(book)
    if not _plain_string_dict(metadata):
        return
    if not _plain_string_dict(metadata.get('sheetnames')):
        return
    default_policy = vars(Workbook).get('worksheet_class')
    if metadata.get('constant_memory') is not False or metadata.get('worksheet_class', default_policy) is not Worksheet:
        return
    return book


def _prepare_bulk_worksheet(dataframe, writer, sheet_name):
    from pandas import DataFrame

    from metroliza.exporting.xlsx_bulk_sheet import BulkRowsWorksheet, bulk_write_enabled

    # Inspect only plain metadata before adding a sheet or a mapping lookup.
    if type(dataframe) is not DataFrame or type(sheet_name) is not str or not sheet_name:
        return
    book = _bulk_workbook(writer)
    if book is not None and bulk_write_enabled() and sheet_name not in book.sheetnames:
        book.add_worksheet(sheet_name, worksheet_class=BulkRowsWorksheet)


def write_tabular_dataframe(dataframe, writer, sheet_name):
    """Write ordinary scalar columns in bulk, retaining pandas for complex types.

    Column order intentionally matches pandas' column-major writer, including
    shared-string insertion order. The empty-frame header uses pandas' installed
    formatting policy. Workbook options still enforce literal strings/URLs.
    """
    import pandas as pd

    if not isinstance(dataframe, pd.DataFrame):
        dataframe.to_excel(writer, sheet_name=sheet_name, index=False)
        return
    kinds = [_column_kind(dataframe.iloc[:, index]) for index in range(len(dataframe.columns))]
    supported = {"string", "integer", "floating", "mixed-integer-float", "boolean", "empty", "datetime"}
    if isinstance(dataframe.columns, pd.MultiIndex) or any(kind not in supported for kind in kinds):
        dataframe.to_excel(writer, sheet_name=sheet_name, index=False)
        return
    # Keep pandas' size validation before writing any data.
    if len(dataframe.index) > 1_048_575 or len(dataframe.columns) > 16_384:
        dataframe.to_excel(writer, sheet_name=sheet_name, index=False)
        return
    # Preserve header metadata callbacks/errors before any worksheet mutation.
    header_frame = dataframe.iloc[:0]
    _prepare_bulk_worksheet(dataframe, writer, sheet_name)
    header_frame.to_excel(writer, sheet_name=sheet_name, index=False)
    del header_frame
    worksheet = writer.sheets[sheet_name]
    datetime_format = None
    for index, kind in enumerate(kinds):
        series = dataframe.iloc[:, index]
        if kind == "datetime":
            if datetime_format is None:
                datetime_format = writer.book.add_format({"num_format": writer.datetime_format})
            # Missing datetimes have no cell format in pandas' output.
            for row, value in enumerate(series, start=1):
                if not pd.isna(value):
                    worksheet.write_datetime(row, index, value, datetime_format)
        else:
            result = worksheet.write_column(1, index, _column_values(series, kind))
            if result != 0:
                raise ValueError(f"XLSX column {index} write failed with code {result}")

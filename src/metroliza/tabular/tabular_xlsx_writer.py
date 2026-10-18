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
    dataframe.iloc[:0].to_excel(writer, sheet_name=sheet_name, index=False)
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

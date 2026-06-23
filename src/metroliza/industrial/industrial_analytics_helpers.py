"""Shared formatting helpers for industrial and tabular analytics outputs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any


def diagnostics_rows(diagnostics: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Return the standard Diagnostics sheet rows without requiring pandas."""
    if not diagnostics:
        return [{"severity": "info", "code": "ok", "message": "No diagnostics."}]
    return [
        {
            "severity": diagnostic.severity,
            "code": diagnostic.code,
            "message": diagnostic.message,
            "context": diagnostic.context,
        }
        for diagnostic in diagnostics
    ]


@dataclass(frozen=True)
class DiagnosticsSheetPayload:
    """Minimal workbook sheet payload used by diagnostics writers."""

    rows: tuple[Mapping[str, Any], ...]

    @property
    def empty(self) -> bool:
        return not self.rows

    def to_excel(self, writer: Any, *, sheet_name: str, index: bool = False) -> None:
        headers = _diagnostics_headers(self.rows)
        if index:
            headers = ("index", *headers)
        worksheet = _create_writer_sheet(writer, sheet_name)
        for column_index, header in enumerate(headers):
            _write_worksheet_cell(worksheet, 0, column_index, header)
        for row_index, row in enumerate(self.rows, start=1):
            if index:
                _write_worksheet_cell(worksheet, row_index, 0, row_index - 1)
                column_offset = 1
            else:
                column_offset = 0
            for column_index, header in enumerate(headers[column_offset:], start=column_offset):
                _write_worksheet_cell(
                    worksheet,
                    row_index,
                    column_index,
                    _excel_cell_value(row.get(header)),
                )


def diagnostics_dataframe(diagnostics: tuple[Any, ...]) -> Any:
    """Return the standard Diagnostics workbook sheet payload."""
    return DiagnosticsSheetPayload(tuple(diagnostics_rows(diagnostics)))


def format_time_bucket_label(value: Any, time_bucket: str) -> str:
    """Return the display label used for grouped time-bucket analytics."""
    timestamp = _coerce_datetime(value)
    if time_bucket == "year":
        return timestamp.strftime("%Y")
    if time_bucket == "month":
        return timestamp.strftime("%Y-%m")
    if time_bucket == "day":
        return timestamp.strftime("%Y-%m-%d")
    if time_bucket == "week":
        return f"Week of {timestamp.strftime('%Y-%m-%d')}"
    if time_bucket == "hour":
        return timestamp.strftime("%Y-%m-%d %H:00")
    return timestamp.isoformat()


def _coerce_datetime(value: Any) -> datetime:
    to_pydatetime = getattr(value, "to_pydatetime", None)
    if callable(to_pydatetime):
        timestamp = to_pydatetime()
    elif isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, date):
        timestamp = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        timestamp = datetime.fromisoformat(text)
    else:
        item = getattr(value, "item", None)
        if callable(item):
            try:
                return _coerce_datetime(item())
            except (TypeError, ValueError):
                pass
        timestamp = datetime.fromisoformat(str(value))

    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
    return timestamp


def _diagnostics_headers(rows: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]:
    preferred = ("severity", "code", "message", "context")
    discovered: list[str] = []
    for header in preferred:
        if any(header in row for row in rows):
            discovered.append(header)
    for row in rows:
        for header in row:
            if header not in discovered:
                discovered.append(str(header))
    return tuple(discovered or preferred[:3])


def _create_writer_sheet(writer: Any, sheet_name: str) -> Any:
    book = writer.book
    if hasattr(book, "add_worksheet"):
        worksheet = book.add_worksheet(sheet_name)
    elif hasattr(book, "create_sheet"):
        worksheet = book.create_sheet(sheet_name)
    else:
        raise TypeError("Unsupported workbook writer for diagnostics output.")
    sheets = getattr(writer, "sheets", None)
    if isinstance(sheets, dict):
        sheets[sheet_name] = worksheet
    return worksheet


def _write_worksheet_cell(worksheet: Any, row: int, column: int, value: Any) -> None:
    write = getattr(worksheet, "write", None)
    if callable(write):
        write(row, column, value)
        return
    cell = getattr(worksheet, "cell", None)
    if callable(cell):
        cell(row=row + 1, column=column + 1, value=value)
        return
    raise TypeError("Unsupported worksheet object for diagnostics output.")


def _excel_cell_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool | int | float | str):
        return value
    return str(value)

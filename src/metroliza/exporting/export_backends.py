"""Define export backend contracts and xlsxwriter adapter implementations.

`ExportDataThread` uses these interfaces to write tabular data, charts, and
images without depending directly on a specific spreadsheet engine.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import time
import tempfile
from typing import Any, Protocol

import xlsxwriter

from metroliza.exporting.xlsx_writer_policy import (
    write_untrusted_xlsx_cell,
    xlsxwriter_workbook_options,
)
from metroliza.exporting.execution import (
    ExportExecutionContext,
    ExportStageOutcome,
    normalize_export_outcome,
)


class ChartContract(Protocol):
    """Protocol for chart operations used by export chart-writing helpers."""

    def add_series(self, series_spec: dict[str, Any]) -> None:
        """Add a chart series from an xlsxwriter-compatible specification."""

    def set_title(self, title_spec: dict[str, Any]) -> None:
        """Set chart title formatting and text."""

    def set_x_axis(self, axis_spec: dict[str, Any]) -> None:
        """Configure x-axis labels, ranges, and formatting options."""

    def set_y_axis(self, axis_spec: dict[str, Any]) -> None:
        """Configure y-axis labels, ranges, and formatting options."""

    def set_legend(self, legend_spec: dict[str, Any]) -> None:
        """Configure chart legend visibility and placement."""

    def set_size(self, size_spec: dict[str, Any]) -> None:
        """Set rendered chart width/height options."""


class WorksheetContract(Protocol):
    """Protocol for worksheet operations required by export sheet writers."""

    def write(self, row: int, col: int, value: Any, cell_format: Any = None) -> None:
        """Write a scalar value to a worksheet cell."""

    def write_formula(self, row: int, col: int, formula: str, cell_format: Any = None) -> None:
        """Write an Excel formula string to a worksheet cell."""

    def write_column(self, row: int, col: int, data: Any) -> None:
        """Write a vertical sequence starting at the given row/column."""

    def conditional_format(
        self,
        first_row: int,
        first_col: int,
        last_row: int,
        last_col: int,
        options: dict[str, Any],
    ) -> None:
        """Apply conditional formatting over a rectangular cell range."""

    def set_column(
        self,
        first_col: int,
        last_col: int,
        width: float | None = None,
        cell_format: Any = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Configure one or more worksheet columns."""

    def set_row(
        self,
        row: int,
        height: float | None = None,
        cell_format: Any = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Configure a worksheet row height and optional default format."""

    def insert_chart(self, row: int, col: int, chart: ChartContract, options: dict[str, Any] | None = None) -> None:
        """Insert a chart object anchored at the provided cell."""

    def insert_image(self, row: int, col: int, filename: str, options: dict[str, Any]) -> None:
        """Insert an image file into the worksheet."""

    def freeze_panes(self, row: int, col: int) -> None:
        """Freeze panes at the specified row/column split."""

    def autofilter(self, first_row: int, first_col: int, last_row: int, last_col: int) -> None:
        """Enable worksheet autofilter over a range."""

    def hide_gridlines(self, option: int = 2) -> None:
        """Hide worksheet gridlines for report-style sheets."""

    def set_landscape(self) -> None:
        """Set worksheet page orientation to landscape when supported."""

    def fit_to_pages(self, width: int, height: int) -> None:
        """Scale worksheet output to the given page width/height."""

    def set_paper(self, paper_type: int) -> None:
        """Set worksheet paper size using engine-specific numeric codes."""

    def repeat_rows(self, first_row: int, last_row: int) -> None:
        """Repeat rows at the top of each printed page."""

    def print_area(self, first_row: int, first_col: int, last_row: int, last_col: int) -> None:
        """Restrict the worksheet print area to the given range."""

    def set_footer(self, footer: str) -> None:
        """Set worksheet footer text for printed output."""


class WorkbookContract(Protocol):
    """Protocol for workbook-level writer interactions."""

    def add_worksheet(self, name: str) -> WorksheetContract:
        """Create and return a worksheet by name."""

    def add_format(self, properties: dict[str, Any]) -> Any:
        """Create a workbook format object from style properties."""

    def add_chart(self, chart_spec: dict[str, Any]) -> ChartContract:
        """Create a chart object with the given type/options."""


class ExportBackendContract(Protocol):
    """Backend contract used by `ExportDataThread` for export targets."""

    export_target: str

    def create_writer(self, excel_file: str) -> Any:
        """Create a writer/session object for the export target file."""

    def close_writer(self, writer: Any) -> None:
        """Flush and close a writer/session object."""

    def write_dataframe(self, writer: Any, table: Any, sheet_name: str) -> None:
        """Write a tabular object to the target writer and sheet name."""

    def list_sheet_names(self, writer: Any) -> set[str]:
        """Return currently known worksheet names in the writer."""

    def get_worksheet(self, writer: Any, sheet_name: str) -> WorksheetContract:
        """Return a worksheet adapter for an existing sheet."""

    def get_workbook(self, writer: Any) -> WorkbookContract:
        """Return a workbook adapter for low-level format/chart operations."""

    def run(self, thread: ExportExecutionContext) -> ExportStageOutcome:
        """Execute backend lifecycle around `thread.run_export_pipeline`."""


@dataclass
class XlsxChartAdapter:
    """Adapter that exposes xlsxwriter chart objects through `ChartContract`."""

    _chart: Any

    def add_series(self, series_spec: dict[str, Any]) -> None:
        """Delegate series insertion to the wrapped xlsxwriter chart."""
        self._chart.add_series(series_spec)

    def set_title(self, title_spec: dict[str, Any]) -> None:
        """Delegate title configuration to the wrapped chart."""
        self._chart.set_title(title_spec)

    def set_x_axis(self, axis_spec: dict[str, Any]) -> None:
        """Delegate x-axis configuration to the wrapped chart."""
        self._chart.set_x_axis(axis_spec)

    def set_y_axis(self, axis_spec: dict[str, Any]) -> None:
        """Delegate y-axis configuration to the wrapped chart."""
        self._chart.set_y_axis(axis_spec)

    def set_legend(self, legend_spec: dict[str, Any]) -> None:
        """Delegate legend configuration to the wrapped chart."""
        self._chart.set_legend(legend_spec)

    def set_size(self, size_spec: dict[str, Any]) -> None:
        """Delegate size configuration to the wrapped chart."""
        self._chart.set_size(size_spec)


@dataclass
class XlsxWorksheetAdapter:
    """Adapter that wraps xlsxwriter worksheets behind `WorksheetContract`."""

    _worksheet: Any

    @property
    def name(self) -> str:
        """Expose worksheet names for writers that build chart series ranges."""
        return getattr(self._worksheet, 'name', '')

    def write(self, row: int, col: int, value: Any, cell_format: Any = None) -> None:
        """Write a scalar value to a worksheet cell."""
        self._worksheet.write(row, col, value, cell_format)

    def write_formula(self, row: int, col: int, formula: str, cell_format: Any = None) -> None:
        """Write an Excel formula to a worksheet cell."""
        self._worksheet.write_formula(row, col, formula, cell_format)

    def write_url(
        self,
        row: int,
        col: int,
        url: str,
        cell_format: Any = None,
        string: str | None = None,
        tip: str | None = None,
    ) -> None:
        """Write a hyperlink cell when the wrapped worksheet supports it."""
        self._worksheet.write_url(row, col, url, cell_format, string, tip)

    def write_column(self, row: int, col: int, data: Any) -> None:
        """Write a vertical data sequence starting at the given position."""
        self._worksheet.write_column(row, col, data)

    def conditional_format(
        self,
        first_row: int,
        first_col: int,
        last_row: int,
        last_col: int,
        options: dict[str, Any],
    ) -> None:
        """Apply conditional formatting across a rectangular range."""
        self._worksheet.conditional_format(first_row, first_col, last_row, last_col, options)

    def set_column(
        self,
        first_col: int,
        last_col: int,
        width: float | None = None,
        cell_format: Any = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Set width and options for one or more columns."""
        self._worksheet.set_column(first_col, last_col, width, cell_format, options)

    def insert_chart(self, row: int, col: int, chart: XlsxChartAdapter, options: dict[str, Any] | None = None) -> None:
        """Insert a wrapped chart at the target row/column."""
        self._worksheet.insert_chart(row, col, chart._chart, options or {})

    def set_row(
        self,
        row: int,
        height: float | None = None,
        cell_format: Any = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Set height and options for a row."""
        self._worksheet.set_row(row, height, cell_format, options)

    def insert_image(self, row: int, col: int, filename: str, options: dict[str, Any]) -> None:
        """Insert an image file with worksheet-specific options."""
        self._worksheet.insert_image(row, col, filename, options)

    def freeze_panes(self, row: int, col: int) -> None:
        """Freeze worksheet panes at the given split location."""
        self._worksheet.freeze_panes(row, col)

    def autofilter(self, first_row: int, first_col: int, last_row: int, last_col: int) -> None:
        """Enable worksheet autofilters for the given range."""
        self._worksheet.autofilter(first_row, first_col, last_row, last_col)

    def hide_gridlines(self, option: int = 2) -> None:
        """Hide gridlines using the wrapped worksheet implementation."""
        self._worksheet.hide_gridlines(option)

    def merge_range(self, first_row: int, first_col: int, last_row: int, last_col: int, data: Any, cell_format: Any = None) -> None:
        """Merge a rectangular cell range and write the provided value."""
        self._worksheet.merge_range(first_row, first_col, last_row, last_col, data, cell_format)

    def set_landscape(self) -> None:
        """Set landscape page orientation for print/PDF export."""
        self._worksheet.set_landscape()

    def fit_to_pages(self, width: int, height: int) -> None:
        """Scale worksheet printing to the requested page count."""
        self._worksheet.fit_to_pages(width, height)

    def set_paper(self, paper_type: int) -> None:
        """Set paper size for print/PDF export."""
        self._worksheet.set_paper(paper_type)

    def repeat_rows(self, first_row: int, last_row: int) -> None:
        """Repeat rows at the top of each printed page."""
        self._worksheet.repeat_rows(first_row, last_row)

    def print_area(self, first_row: int, first_col: int, last_row: int, last_col: int) -> None:
        """Restrict the printed area to the specified rectangle."""
        self._worksheet.print_area(first_row, first_col, last_row, last_col)

    def set_footer(self, footer: str) -> None:
        """Set worksheet footer text for printed output."""
        self._worksheet.set_footer(footer)


@dataclass
class XlsxWorkbookAdapter:
    """Adapter that wraps xlsxwriter workbook operations."""

    _workbook: Any

    def add_worksheet(self, name: str) -> XlsxWorksheetAdapter:
        """Create and return a worksheet adapter for `name`."""
        worksheet = XlsxWorksheetAdapter(self._workbook.add_worksheet(name))
        setattr(worksheet, '_workbook', self)
        return worksheet

    def add_format(self, properties: dict[str, Any]) -> Any:
        """Create a workbook format using xlsxwriter property mappings."""
        return self._workbook.add_format(properties)

    def add_chart(self, chart_spec: dict[str, Any]) -> XlsxChartAdapter:
        """Create and return a chart adapter from chart settings."""
        return XlsxChartAdapter(self._workbook.add_chart(chart_spec))


@dataclass
class XlsxWorkbookWriter:
    """Direct xlsxwriter session used by the Excel export backend."""

    path: str
    book: Any
    sheets: dict[str, Any]


class _NullChartAdapter:
    """No-op chart adapter used when producing a dashboard without a workbook."""

    def add_series(self, series_spec: dict[str, Any]) -> None:
        return None

    def set_title(self, title_spec: dict[str, Any]) -> None:
        return None

    def set_x_axis(self, axis_spec: dict[str, Any]) -> None:
        return None

    def set_y_axis(self, axis_spec: dict[str, Any]) -> None:
        return None

    def set_legend(self, legend_spec: dict[str, Any]) -> None:
        return None

    def set_size(self, size_spec: dict[str, Any]) -> None:
        return None


@dataclass
class _NullWorksheetAdapter:
    """No-op worksheet adapter that preserves dashboard side effects only."""

    name: str

    def write(self, row: int, col: int, value: Any, cell_format: Any = None) -> None:
        return None

    def write_formula(self, row: int, col: int, formula: str, cell_format: Any = None) -> None:
        return None

    def write_url(
        self,
        row: int,
        col: int,
        url: str,
        cell_format: Any = None,
        string: str | None = None,
        tip: str | None = None,
    ) -> None:
        return None

    def write_column(self, row: int, col: int, data: Any) -> None:
        return None

    def conditional_format(
        self,
        first_row: int,
        first_col: int,
        last_row: int,
        last_col: int,
        options: dict[str, Any],
    ) -> None:
        return None

    def set_column(
        self,
        first_col: int,
        last_col: int,
        width: float | None = None,
        cell_format: Any = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        return None

    def set_row(
        self,
        row: int,
        height: float | None = None,
        cell_format: Any = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        return None

    def insert_chart(self, row: int, col: int, chart: ChartContract, options: dict[str, Any] | None = None) -> None:
        return None

    def insert_image(self, row: int, col: int, filename: str, options: dict[str, Any]) -> None:
        return None

    def freeze_panes(self, row: int, col: int) -> None:
        return None

    def autofilter(self, first_row: int, first_col: int, last_row: int, last_col: int) -> None:
        return None

    def hide_gridlines(self, option: int = 2) -> None:
        return None

    def merge_range(
        self,
        first_row: int,
        first_col: int,
        last_row: int,
        last_col: int,
        data: Any,
        cell_format: Any = None,
    ) -> None:
        return None

    def set_landscape(self) -> None:
        return None

    def fit_to_pages(self, width: int, height: int) -> None:
        return None

    def set_paper(self, paper_type: int) -> None:
        return None

    def repeat_rows(self, first_row: int, last_row: int) -> None:
        return None

    def print_area(self, first_row: int, first_col: int, last_row: int, last_col: int) -> None:
        return None

    def set_footer(self, footer: str) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop


@dataclass
class _NullWorkbookAdapter:
    """No-op workbook adapter for HTML-only exports."""

    sheets: dict[str, _NullWorksheetAdapter]

    def add_worksheet(self, name: str) -> _NullWorksheetAdapter:
        worksheet = _NullWorksheetAdapter(str(name or "Sheet"))
        self.sheets[worksheet.name] = worksheet
        return worksheet

    def add_format(self, properties: dict[str, Any]) -> dict[str, Any]:
        return dict(properties or {})

    def add_chart(self, chart_spec: dict[str, Any]) -> _NullChartAdapter:
        return _NullChartAdapter()


@dataclass
class _HtmlDashboardWriter:
    """Minimal writer surface used by dashboard-only export stages."""

    output_path: str
    workbook: _NullWorkbookAdapter
    sheets: dict[str, _NullWorksheetAdapter]


class HtmlDashboardExportBackend:
    """Backend that builds the HTML dashboard without creating a workbook."""

    export_target = "html_dashboard"

    def create_writer(self, excel_file: str) -> _HtmlDashboardWriter:
        """Create a no-op workbook writer surface for dashboard-only generation."""
        sheets: dict[str, _NullWorksheetAdapter] = {}
        return _HtmlDashboardWriter(
            output_path=str(excel_file or ""),
            workbook=_NullWorkbookAdapter(sheets),
            sheets=sheets,
        )

    def close_writer(self, writer: _HtmlDashboardWriter) -> None:
        """Close a dashboard-only writer; no filesystem handle is opened."""
        return None

    def write_dataframe(self, writer: _HtmlDashboardWriter, table: Any, sheet_name: str) -> None:
        """Record a logical sheet name without writing tabular workbook data."""
        writer.sheets[str(sheet_name)] = _NullWorksheetAdapter(str(sheet_name))

    def list_sheet_names(self, writer: _HtmlDashboardWriter) -> set[str]:
        """Return logical sheet names created during dashboard planning."""
        return set(writer.sheets.keys())

    def get_worksheet(self, writer: _HtmlDashboardWriter, sheet_name: str) -> _NullWorksheetAdapter:
        """Return a no-op worksheet adapter for the requested logical sheet."""
        name = str(sheet_name)
        if name not in writer.sheets:
            writer.sheets[name] = _NullWorksheetAdapter(name)
        return writer.sheets[name]

    def get_workbook(self, writer: _HtmlDashboardWriter) -> _NullWorkbookAdapter:
        """Return a no-op workbook adapter for chart and format calls."""
        return writer.workbook

    def run(self, thread: ExportExecutionContext) -> ExportStageOutcome:
        """Run the dashboard-producing export stages without touching an XLSX file."""
        writer = self.create_writer(thread.html_dashboard_file or "")
        try:
            return normalize_export_outcome(thread.run_html_dashboard_pipeline(writer))
        finally:
            self.close_writer(writer)


def _is_blank_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _extract_table_columns_and_rows(table: Any) -> tuple[list[str], list[tuple[Any, ...]]]:
    columns = [str(column) for column in getattr(table, "columns", ())]
    if hasattr(table, "iter_rows"):
        return columns, [tuple(row) for row in table.iter_rows()]

    if columns and hasattr(table, "itertuples"):
        return columns, [tuple(row) for row in table.itertuples(index=False, name=None)]

    if columns and hasattr(table, "rows"):
        return columns, [tuple(row) for row in table.rows]

    if isinstance(table, list) and table and isinstance(table[0], dict):
        columns = [str(column) for column in table[0].keys()]
        rows = [tuple(row.get(column) for column in columns) for row in table]
        return columns, rows

    if isinstance(table, tuple) and len(table) == 2:
        rows, raw_columns = table
        columns = [str(column) for column in raw_columns]
        return columns, [tuple(row) for row in rows]

    return columns, []


class ExcelExportBackend:
    """Excel backend that persists exports directly through xlsxwriter."""

    export_target = "excel_xlsx"

    def create_writer(self, excel_file: str) -> XlsxWorkbookWriter:
        """Create a direct xlsxwriter workbook session for `excel_file`."""
        return XlsxWorkbookWriter(
            path=excel_file,
            book=xlsxwriter.Workbook(excel_file, xlsxwriter_workbook_options()),
            sheets={},
        )

    def close_writer(self, writer: XlsxWorkbookWriter) -> None:
        """Close the active writer and flush workbook contents to disk."""
        writer.book.close()

    def write_dataframe(self, writer: XlsxWorkbookWriter, table: Any, sheet_name: str) -> None:
        """Write `table` to `sheet_name` without index columns."""
        columns, rows = _extract_table_columns_and_rows(table)
        worksheet = writer.book.add_worksheet(str(sheet_name))
        writer.sheets[str(sheet_name)] = worksheet

        for column_index, column_name in enumerate(columns):
            write_untrusted_xlsx_cell(worksheet, 0, column_index, column_name)

        for row_index, row in enumerate(rows, start=1):
            for column_index, value in enumerate(row):
                write_untrusted_xlsx_cell(
                    worksheet,
                    row_index,
                    column_index,
                    None if _is_blank_cell(value) else value,
                )

    def list_sheet_names(self, writer: XlsxWorkbookWriter) -> set[str]:
        """Return names of worksheets currently attached to `writer`."""
        return set(writer.sheets.keys())

    def get_worksheet(self, writer: XlsxWorkbookWriter, sheet_name: str) -> XlsxWorksheetAdapter:
        """Return an adapter over `sheet_name` in the active writer."""
        return XlsxWorksheetAdapter(writer.sheets[sheet_name])

    def get_workbook(self, writer: XlsxWorkbookWriter) -> XlsxWorkbookAdapter:
        """Return a workbook adapter for format and chart creation."""
        return XlsxWorkbookAdapter(writer.book)

    def create_temporary_workbook_path(self, excel_file: str) -> Path:
        """Reserve a same-directory temporary workbook path for atomic commit."""
        target_path = Path(excel_file)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target_path.stem}.tmp-",
            suffix=".xlsx",
            dir=str(target_path.parent),
        )
        os.close(fd)
        return Path(temp_name)

    def replace_workbook(self, temp_path: Path, target_path: Path) -> None:
        """Atomically replace the target workbook with the completed temp file."""
        os.replace(temp_path, target_path)

    def remove_temporary_workbook(self, temp_path: Path | None) -> None:
        """Delete a temporary workbook if it still exists."""
        if temp_path is None:
            return
        try:
            temp_path.unlink()
        except FileNotFoundError:
            return

    def run(self, thread: ExportExecutionContext) -> ExportStageOutcome:
        """Run export pipeline with writer lifecycle management.

        Args:
            thread (Any): `ExportDataThread`-like object exposing `excel_file`
                and `run_export_pipeline`.

        Returns:
            ExportStageOutcome: Structured success or cancellation result.
        """
        target_path = Path(thread.excel_file)
        temp_path = self.create_temporary_workbook_path(str(target_path))
        excel_writer = None
        outcome = ExportStageOutcome.canceled()
        try:
            excel_writer = self.create_writer(str(temp_path))
            try:
                outcome = normalize_export_outcome(thread.run_export_pipeline(excel_writer))
            finally:
                thread.begin_workbook_close()
                close_start = time.perf_counter()
                try:
                    self.close_writer(excel_writer)
                finally:
                    thread.complete_workbook_close(time.perf_counter() - close_start)
        except BaseException:
            self.remove_temporary_workbook(temp_path)
            raise

        if not outcome:
            self.remove_temporary_workbook(temp_path)
            return outcome

        try:
            self.replace_workbook(temp_path, target_path)
        except BaseException:
            self.remove_temporary_workbook(temp_path)
            raise

        return outcome

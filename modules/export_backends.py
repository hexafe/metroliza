from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd


class ChartContract(Protocol):
    def add_series(self, series_spec: dict[str, Any]) -> None: ...
    def set_title(self, title_spec: dict[str, Any]) -> None: ...
    def set_y_axis(self, axis_spec: dict[str, Any]) -> None: ...
    def set_legend(self, legend_spec: dict[str, Any]) -> None: ...
    def set_size(self, size_spec: dict[str, Any]) -> None: ...


class WorksheetContract(Protocol):
    def write(self, row: int, col: int, value: Any, cell_format: Any = None) -> None: ...
    def write_formula(self, row: int, col: int, formula: str, cell_format: Any = None) -> None: ...
    def write_column(self, row: int, col: int, data: Any) -> None: ...
    def conditional_format(self, first_row: int, first_col: int, last_row: int, last_col: int, options: dict[str, Any]) -> None: ...
    def set_column(self, first_col: int, last_col: int, width: float | None = None, cell_format: Any = None) -> None: ...
    def insert_chart(self, row: int, col: int, chart: ChartContract) -> None: ...
    def insert_image(self, row: int, col: int, filename: str, options: dict[str, Any]) -> None: ...
    def freeze_panes(self, row: int, col: int) -> None: ...
    def autofilter(self, first_row: int, first_col: int, last_row: int, last_col: int) -> None: ...


class WorkbookContract(Protocol):
    def add_worksheet(self, name: str) -> WorksheetContract: ...
    def add_format(self, properties: dict[str, Any]) -> Any: ...
    def add_chart(self, chart_spec: dict[str, Any]) -> ChartContract: ...


class ExportBackendContract(Protocol):
    export_target: str

    def create_writer(self, excel_file: str) -> Any: ...
    def close_writer(self, writer: Any) -> None: ...
    def write_dataframe(self, writer: Any, df: pd.DataFrame, sheet_name: str) -> None: ...
    def list_sheet_names(self, writer: Any) -> set[str]: ...
    def get_worksheet(self, writer: Any, sheet_name: str) -> WorksheetContract: ...
    def get_workbook(self, writer: Any) -> WorkbookContract: ...
    def run(self, thread: Any) -> bool: ...


@dataclass
class XlsxChartAdapter:
    _chart: Any

    def add_series(self, series_spec: dict[str, Any]) -> None:
        self._chart.add_series(series_spec)

    def set_title(self, title_spec: dict[str, Any]) -> None:
        self._chart.set_title(title_spec)

    def set_y_axis(self, axis_spec: dict[str, Any]) -> None:
        self._chart.set_y_axis(axis_spec)

    def set_legend(self, legend_spec: dict[str, Any]) -> None:
        self._chart.set_legend(legend_spec)

    def set_size(self, size_spec: dict[str, Any]) -> None:
        self._chart.set_size(size_spec)


@dataclass
class XlsxWorksheetAdapter:
    _worksheet: Any

    def write(self, row: int, col: int, value: Any, cell_format: Any = None) -> None:
        self._worksheet.write(row, col, value, cell_format)

    def write_formula(self, row: int, col: int, formula: str, cell_format: Any = None) -> None:
        self._worksheet.write_formula(row, col, formula, cell_format)

    def write_column(self, row: int, col: int, data: Any) -> None:
        self._worksheet.write_column(row, col, data)

    def conditional_format(self, first_row: int, first_col: int, last_row: int, last_col: int, options: dict[str, Any]) -> None:
        self._worksheet.conditional_format(first_row, first_col, last_row, last_col, options)

    def set_column(self, first_col: int, last_col: int, width: float | None = None, cell_format: Any = None) -> None:
        self._worksheet.set_column(first_col, last_col, width, cell_format)

    def insert_chart(self, row: int, col: int, chart: XlsxChartAdapter) -> None:
        self._worksheet.insert_chart(row, col, chart._chart)

    def insert_image(self, row: int, col: int, filename: str, options: dict[str, Any]) -> None:
        self._worksheet.insert_image(row, col, filename, options)

    def freeze_panes(self, row: int, col: int) -> None:
        self._worksheet.freeze_panes(row, col)

    def autofilter(self, first_row: int, first_col: int, last_row: int, last_col: int) -> None:
        self._worksheet.autofilter(first_row, first_col, last_row, last_col)


@dataclass
class XlsxWorkbookAdapter:
    _workbook: Any

    def add_worksheet(self, name: str) -> XlsxWorksheetAdapter:
        return XlsxWorksheetAdapter(self._workbook.add_worksheet(name))

    def add_format(self, properties: dict[str, Any]) -> Any:
        return self._workbook.add_format(properties)

    def add_chart(self, chart_spec: dict[str, Any]) -> XlsxChartAdapter:
        return XlsxChartAdapter(self._workbook.add_chart(chart_spec))


class ExcelExportBackend:
    export_target = "excel_xlsx"

    def create_writer(self, excel_file: str) -> Any:
        return pd.ExcelWriter(excel_file, engine="xlsxwriter")

    def close_writer(self, writer: Any) -> None:
        writer.close()

    def write_dataframe(self, writer: Any, df: pd.DataFrame, sheet_name: str) -> None:
        df.to_excel(writer, sheet_name=sheet_name, index=False)

    def list_sheet_names(self, writer: Any) -> set[str]:
        return set(writer.sheets.keys())

    def get_worksheet(self, writer: Any, sheet_name: str) -> XlsxWorksheetAdapter:
        return XlsxWorksheetAdapter(writer.sheets[sheet_name])

    def get_workbook(self, writer: Any) -> XlsxWorkbookAdapter:
        return XlsxWorkbookAdapter(writer.book)

    def run(self, thread: Any) -> bool:
        excel_writer = self.create_writer(thread.excel_file)
        try:
            completed = thread.run_export_pipeline(excel_writer)
            if not completed:
                return False
        finally:
            self.close_writer(excel_writer)

        return True

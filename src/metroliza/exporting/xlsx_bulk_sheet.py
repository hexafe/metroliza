"""Compact bulk-row storage for XlsxWriter worksheets (#1124).

The raw ``MEASUREMENTS`` sheet of a default export holds millions of cells.
XlsxWriter keeps every cell as a Python object until ``Workbook.close`` and then
renders them one by one, which dominates export time and memory.  This module
adds a worksheet subclass that stores a large DataFrame block column-wise in
numpy arrays and renders it to sheet XML in vectorised chunks at close time.

The produced workbook is byte-for-byte what the cell-by-cell
``write_untrusted_xlsx_cell`` loop produces (same shared-string order, same
``<row spans>`` and ``<c>`` markup).  Anything the fast path cannot reproduce
exactly -- unsupported value types, infinities, rows that other writes touch --
falls back to the classic per-cell behaviour, so correctness never depends on
the optimisation.  Set ``METROLIZA_EXPORT_BULK_WRITE=0`` to disable it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name
from xlsxwriter.worksheet import CellNumberTuple, CellStringTuple, Worksheet

from metroliza.shared.env_utils import env_bool

BULK_WRITE_ENV = "METROLIZA_EXPORT_BULK_WRITE"
# XlsxWriter internals are used for the fast path; only releases it was
# verified against enable it.  Other versions silently use the classic path.
_SUPPORTED_XLSXWRITER_SERIES = ((3, 2),)
_RENDER_CHUNK_ROWS = 4096
_ROW_SPAN_GROUP = 16
_STRING_CELL_LIMIT = 32767
_NUMERIC_TYPES = frozenset({int, float})
_REQUIRED_WORKSHEET_ATTRIBUTES = (
    "_write_rows",
    "_calculate_spans",
    "_get_range_data",
    "autofit",
    "_write_row",
    "_check_dimensions",
)


def bulk_write_enabled() -> bool:
    """Return whether the bulk worksheet path may be used in this process."""
    if not env_bool(BULK_WRITE_ENV, default=True):
        return False
    try:
        series = tuple(int(part) for part in xlsxwriter.__version__.split(".")[:2])
    except (AttributeError, ValueError):
        return False
    if series not in _SUPPORTED_XLSXWRITER_SERIES:
        return False
    return all(hasattr(Worksheet, name) for name in _REQUIRED_WORKSHEET_ATTRIBUTES)


@dataclass
class BulkColumn:
    """One worksheet column of a bulk block (numbers or shared-string ids)."""

    col: int
    numbers: Any = None  # float64 ndarray, NaN = no cell
    codes: Any = None  # int32 ndarray of unique-text ids, -1 = no cell
    texts: tuple = ()  # unique text per code, in first-appearance order
    first_rows: Any = None  # first row (block-relative) of each unique text
    string_ids: Any = None  # int32 shared-string ids, filled on registration

    def present(self) -> Any:
        """Return a boolean mask of rows that hold a cell."""
        if self.numbers is not None:
            return ~np.isnan(self.numbers)
        return (self.string_ids if self.string_ids is not None else self.codes) >= 0


@dataclass
class BulkPlan:
    """Column-wise, sanitised snapshot of a DataFrame ready for bulk writing."""

    column_names: list
    n_rows: int
    columns: list


def _numeric_column(values: tuple) -> Any:
    try:
        numbers = np.array(values, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        return None
    return None if np.isinf(numbers).any() else numbers


def _text_column(values: tuple) -> tuple:
    """Factorise a text column; ``None`` becomes code -1 (no cell)."""
    uniques = [value for value in dict.fromkeys(values) if value is not None]
    index = {value: code for code, value in enumerate(uniques)}
    index[None] = -1
    codes = np.fromiter(map(index.__getitem__, values), dtype=np.int32, count=len(values))
    valid = np.flatnonzero(codes >= 0)
    _, first = np.unique(codes[valid], return_index=True)
    texts = tuple(text if len(text) <= _STRING_CELL_LIMIT else text[:_STRING_CELL_LIMIT] for text in uniques)
    return codes, texts, valid[first]


def _plan_column(values: tuple, col: int) -> BulkColumn | None:
    kinds = set(map(type, values))
    kinds.discard(type(None))
    if not kinds:
        return BulkColumn(col=col, numbers=np.full(len(values), np.nan))
    if kinds == {str}:
        codes, texts, first_rows = _text_column(values)
        return BulkColumn(col=col, codes=codes, texts=texts, first_rows=first_rows)
    if kinds <= _NUMERIC_TYPES:
        numbers = _numeric_column(values)
        return None if numbers is None else BulkColumn(col=col, numbers=numbers)
    return None


def plan_bulk_rows(columns: list, rows: list) -> BulkPlan | None:
    """Return a bulk plan for ``rows`` of Python scalars, or ``None`` if unsupported.

    Only exact ``str``/``int``/``float``/``None`` values are accepted (``None``
    and NaN mean "no cell", infinities need XlsxWriter's error-formula
    handling); any other value type makes the caller use the per-cell path.
    """
    width = len(columns)
    if not rows or not width or set(map(len, rows)) != {width}:
        return None
    planned = []
    for col, values in enumerate(zip(*rows)):
        column = _plan_column(values, col)
        if column is None:
            return None
        planned.append(column)
    return BulkPlan(column_names=[str(name) for name in columns], n_rows=len(rows), columns=planned)


@dataclass
class BulkBlock:
    """A registered block of bulk rows inside one worksheet."""

    first_row: int
    n_rows: int
    columns: list  # non-empty BulkColumn objects, ascending by column

    @property
    def last_row(self) -> int:
        """Return the last absolute row index of the block."""
        return self.first_row + self.n_rows - 1


def _register_strings(worksheet: Worksheet, plan: BulkPlan) -> None:
    """Register block strings in row-major first-appearance order (classic order)."""
    candidates = []
    for column in plan.columns:
        if column.codes is None:
            continue
        for code, (text, first_row) in enumerate(zip(column.texts, column.first_rows.tolist())):
            candidates.append((first_row, column.col, code, text))
    candidates.sort(key=lambda item: (item[0], item[1]))
    shared = worksheet.str_table
    table = shared.string_table
    ids_by_column = {}
    for _, col, code, text in candidates:
        index = table.get(text)
        if index is None:
            index = shared.unique_count
            table[text] = index
            shared.unique_count += 1
        ids_by_column.setdefault(col, {})[code] = index
    for column in plan.columns:
        if column.codes is None:
            continue
        lookup = np.full(len(column.texts) + 1, -1, dtype=np.int32)
        for code, index in ids_by_column.get(column.col, {}).items():
            lookup[code] = index
        column.string_ids = lookup[column.codes]
        shared.count += int(np.count_nonzero(column.codes >= 0))
        column.codes = None


class BulkRowsWorksheet(Worksheet):
    """XlsxWriter worksheet that can hold large DataFrame blocks compactly."""

    def __init__(self) -> None:
        super().__init__()
        self._bulk_blocks: list[BulkBlock] = []
        self._bulk_spans_frozen = False

    # -- registration -----------------------------------------------------
    def write_bulk_block(self, first_row: int, plan: BulkPlan) -> bool:
        """Store ``plan`` as rows starting at ``first_row`` (column 0).

        Returns ``False`` without touching the worksheet when the block cannot
        be reproduced exactly (the caller then writes cell by cell).
        """
        last_row = first_row + plan.n_rows - 1
        last_col = len(plan.columns) - 1
        if self.constant_memory or last_row >= self.xls_rowmax or last_col >= self.xls_colmax:
            return False
        if self._range_is_busy(first_row, last_row):
            return False
        _register_strings(self, plan)
        columns = [column for column in plan.columns if self._column_has_cells(column)]
        if not columns:
            return True
        block = BulkBlock(first_row=first_row, n_rows=plan.n_rows, columns=columns)
        self._bulk_blocks.append(block)
        self._extend_dimensions(block)
        return True

    @staticmethod
    def _column_has_cells(column: BulkColumn) -> bool:
        return bool(column.present().any())

    def _range_is_busy(self, first_row: int, last_row: int, *, skip: BulkBlock | None = None) -> bool:
        if any(first_row <= row <= last_row for row, cells in self.table.items() if cells):
            return True
        if any(first_row <= row <= last_row for row in self.set_rows):
            return True
        if any(first_row <= row <= last_row for row in self.comments):
            return True
        return any(
            block.first_row <= last_row and first_row <= block.last_row
            for block in self._bulk_blocks
            if block is not skip
        )

    def _extend_dimensions(self, block: BulkBlock) -> None:
        rows = self._rows_with_cells(block)
        first = block.first_row + int(rows[0])
        last = block.first_row + int(rows[-1])
        cols = [column.col for column in block.columns]
        self._check_dimensions(first, min(cols))
        self._check_dimensions(last, max(cols))

    @staticmethod
    def _rows_with_cells(block: BulkBlock) -> Any:
        any_cell = np.zeros(block.n_rows, dtype=bool)
        for column in block.columns:
            any_cell |= column.present()
        return np.flatnonzero(any_cell)

    # -- conflicts with other writes -------------------------------------
    def _plain_row_markup(self) -> bool:
        return self.excel_version != 2010 and self.default_row_height == self.original_row_height

    def _block_conflicts(self, block: BulkBlock) -> bool:
        if not self._plain_row_markup():
            return True
        return self._range_is_busy(block.first_row, block.last_row, skip=block)

    def _materialise_block(self, block: BulkBlock) -> None:
        """Turn a block into ordinary table cells (cells written later win)."""
        for column in block.columns:
            present = column.present()
            rows = np.flatnonzero(present)
            if column.numbers is not None:
                values = column.numbers[rows].tolist()
                cells = [CellNumberTuple(value, None) for value in values]
            else:
                values = column.string_ids[rows].tolist()
                cells = [CellStringTuple(value, None) for value in values]
            for row, cell in zip(rows.tolist(), cells):
                self.table[block.first_row + row].setdefault(column.col, cell)
        self._bulk_blocks.remove(block)

    def _settle_blocks(self, *, only_conflicts: bool = False) -> None:
        for block in list(self._bulk_blocks):
            if not only_conflicts or self._block_conflicts(block):
                self._materialise_block(block)

    # -- XlsxWriter hooks -------------------------------------------------
    def _get_range_data(self, row_start, col_start, row_end, col_end):
        self._settle_blocks()
        return super()._get_range_data(row_start, col_start, row_end, col_end)

    def autofit(self, *args, **kwargs):
        """Materialise bulk blocks, then run XlsxWriter's autofit."""
        self._settle_blocks()
        return super().autofit(*args, **kwargs)

    def _calculate_spans(self) -> None:
        if self._bulk_spans_frozen:
            return
        super()._calculate_spans()
        for block in self._bulk_blocks:
            self._merge_block_spans(block)

    def _merge_block_spans(self, block: BulkBlock) -> None:
        lows, highs = self._row_column_extent(block)
        has_cells = lows < 10**9
        groups = (block.first_row + np.arange(block.n_rows)) // _ROW_SPAN_GROUP
        for group in np.unique(groups[has_cells]).tolist():
            selected = (groups == group) & has_cells
            low = int(lows[selected].min()) + 1
            high = int(highs[selected].max()) + 1
            existing = self.row_spans.get(group)
            if existing:
                old_low, old_high = (int(part) for part in existing.split(":"))
                low, high = min(low, old_low), max(high, old_high)
            self.row_spans[group] = f"{low}:{high}"

    @staticmethod
    def _row_column_extent(block: BulkBlock) -> tuple:
        lows = np.full(block.n_rows, 10**9, dtype=np.int64)
        highs = np.full(block.n_rows, -1, dtype=np.int64)
        for column in block.columns:
            present = column.present()
            lows = np.where(present & (column.col < lows), column.col, lows)
            highs = np.where(present & (column.col > highs), column.col, highs)
        return lows, highs

    def _write_rows(self) -> None:
        self._settle_blocks(only_conflicts=True)
        if not self._bulk_blocks:
            super()._write_rows()
            return
        self._calculate_spans()
        self._bulk_spans_frozen = True
        try:
            cursor = self.dim_rowmin
            for block in sorted(self._bulk_blocks, key=lambda item: item.first_row):
                self._write_table_rows(cursor, block.first_row - 1)
                self._write_block_rows(block)
                cursor = block.last_row + 1
            self._write_table_rows(cursor, self.dim_rowmax)
        finally:
            self._bulk_spans_frozen = False

    def _write_table_rows(self, first_row: int, last_row: int) -> None:
        if first_row > last_row:
            return
        saved = (self.dim_rowmin, self.dim_rowmax)
        self.dim_rowmin, self.dim_rowmax = first_row, last_row
        try:
            super()._write_rows()
        finally:
            self.dim_rowmin, self.dim_rowmax = saved

    # -- rendering --------------------------------------------------------
    def _column_markup(self, column: BulkColumn) -> tuple:
        letters = xl_col_to_name(column.col)
        column_format = self.col_info[column.col][1] if column.col in self.col_info else None
        style = f' s="{column_format._get_xf_index()}"' if column_format is not None else ""
        return f'<c r="{letters}', style

    def _write_block_rows(self, block: BulkBlock) -> None:
        markups = [self._column_markup(column) for column in block.columns]
        for start in range(0, block.n_rows, _RENDER_CHUNK_ROWS):
            stop = min(start + _RENDER_CHUNK_ROWS, block.n_rows)
            self.fh.write(self._render_rows(block, markups, start, stop))

    def _render_rows(self, block: BulkBlock, markups: list, start: int, stop: int) -> str:
        first_number = block.first_row + start + 1
        row_numbers = [str(number) for number in range(first_number, first_number + stop - start)]
        fragments = [
            _render_column(column, markup, row_numbers, start, stop)
            for column, markup in zip(block.columns, markups)
        ]
        parts = []
        for offset, cells in enumerate(zip(*fragments)):
            joined = "".join(cells)
            if not joined:
                continue
            row_number = block.first_row + start + offset
            spans = self.row_spans.get(row_number // _ROW_SPAN_GROUP)
            span_attribute = f' spans="{spans}"' if spans else ""
            parts.append(f'<row r="{row_numbers[offset]}"{span_attribute}>{joined}</row>')
        return "".join(parts)


def _render_column(column: BulkColumn, markup: tuple, row_numbers: list, start: int, stop: int) -> list:
    prefix, style = markup
    if column.numbers is not None:
        values = column.numbers[start:stop].tolist()
        return [
            f'{prefix}{row}"{style}><v>{value:.16G}</v></c>' if value == value else ""
            for row, value in zip(row_numbers, values)
        ]
    ids = column.string_ids[start:stop].tolist()
    return [
        f'{prefix}{row}"{style} t="s"><v>{index}</v></c>' if index >= 0 else ""
        for row, index in zip(row_numbers, ids)
    ]


def enable_bulk_rows(book: Any) -> bool:
    """Make ``book`` create :class:`BulkRowsWorksheet` sheets when supported."""
    if not bulk_write_enabled():
        return False
    book.worksheet_class = BulkRowsWorksheet
    return True


__all__ = [
    "BULK_WRITE_ENV",
    "BulkPlan",
    "BulkRowsWorksheet",
    "bulk_write_enabled",
    "enable_bulk_rows",
    "plan_bulk_rows",
]

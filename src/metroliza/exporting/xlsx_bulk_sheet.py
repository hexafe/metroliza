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
from xlsxwriter.worksheet import Worksheet

from metroliza.exporting.xlsx_fast_paths import (
    INTERNALS_AVAILABLE,
    CellNumberTuple,
    CellStringTuple,
    accelerate_chart,
    fast_cell_markup,
    write_plain_column,
)
from metroliza.shared.env_utils import env_bool

BULK_WRITE_ENV = "METROLIZA_EXPORT_BULK_WRITE"
# XlsxWriter internals are used for the fast path; only releases it was
# verified against enable it.  Other versions silently use the classic path.
_SUPPORTED_XLSXWRITER_SERIES = ((3, 2),)
_RENDER_CHUNK_ROWS = 4096
_ROW_SPAN_GROUP = 16
_STRING_CELL_LIMIT = 32767
_XLS_ROW_MAX = 1048576
_XLS_COL_MAX = 16384
_NUMERIC_TYPES = frozenset({int, float})
_REQUIRED_WORKSHEET_ATTRIBUTES = (
    "_write_rows",
    "_calculate_spans",
    "_get_range_data",
    "autofit",
    "_write_row",
    "_write_cell",
    "_check_dimensions",
    "write_column",
)


def bulk_write_enabled() -> bool:
    """Return whether the bulk worksheet path may be used in this process."""
    if not INTERNALS_AVAILABLE or not env_bool(BULK_WRITE_ENV, default=True):
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


class _ColumnAccumulator:
    """Build one bulk column incrementally from row chunks."""

    def __init__(self, col: int) -> None:
        self.col = col
        self.kind: str | None = None  # None until a value is seen, then "num" or "text"
        self.rows_seen = 0
        self.parts: list = []  # ndarray chunk, or an int for an all-missing chunk
        self.index: dict = {None: -1}
        self.uniques: list = []
        self.first_rows: list = []

    def add(self, values: tuple) -> bool:
        """Append one chunk of column values; ``False`` if unsupported."""
        kinds = set(map(type, values))
        kinds.discard(type(None))
        if not kinds:
            part: Any = len(values)
        elif kinds == {str}:
            part = self._text_part(values) if self._claim("text") else None
        elif kinds <= _NUMERIC_TYPES:
            part = self._numeric_part(values) if self._claim("num") else None
        else:
            part = None
        if part is None:
            return False
        self.parts.append(part)
        self.rows_seen += len(values)
        return True

    def _claim(self, kind: str) -> bool:
        if self.kind not in (None, kind):
            return False
        self.kind = kind
        return True

    @staticmethod
    def _numeric_part(values: tuple) -> Any:
        try:
            numbers = np.array(values, dtype=np.float64)
        except (TypeError, ValueError, OverflowError):
            return None
        return None if np.isinf(numbers).any() else numbers

    def _text_part(self, values: tuple) -> Any:
        """Factorise text; ``None`` becomes code -1 (no cell)."""
        before = len(self.uniques)
        for value in [value for value in dict.fromkeys(values) if value not in self.index]:
            self.index[value] = len(self.uniques)
            self.uniques.append(value)
        codes = np.fromiter(map(self.index.__getitem__, values), dtype=np.int32, count=len(values))
        if len(self.uniques) > before:
            new_positions = np.flatnonzero(codes >= before)
            _, first = np.unique(codes[new_positions], return_index=True)
            self.first_rows.append(self.rows_seen + new_positions[first])
        return codes

    def build(self) -> BulkColumn:
        """Return the finished :class:`BulkColumn`."""
        if self.kind == "text":
            codes = self._concatenate(-1, np.int32)
            texts = tuple(
                text if len(text) <= _STRING_CELL_LIMIT else text[:_STRING_CELL_LIMIT] for text in self.uniques
            )
            first_rows = np.concatenate(self.first_rows) if self.first_rows else np.empty(0, dtype=np.int64)
            return BulkColumn(col=self.col, codes=codes, texts=texts, first_rows=first_rows)
        return BulkColumn(col=self.col, numbers=self._concatenate(np.nan, np.float64))

    def _concatenate(self, missing: Any, dtype: Any) -> Any:
        chunks = [np.full(part, missing, dtype=dtype) if isinstance(part, int) else part for part in self.parts]
        return np.concatenate(chunks) if chunks else np.empty(0, dtype=dtype)


class BulkPlanBuilder:
    """Collect row chunks of Python scalars into a :class:`BulkPlan`.

    Only exact ``str``/``int``/``float``/``None`` values are accepted (``None``
    and NaN mean "no cell"; infinities need XlsxWriter's error-formula
    handling).  Any other value makes :meth:`add_rows` return ``False`` and the
    caller uses the per-cell path instead.
    """

    def __init__(self, column_names: list) -> None:
        self.column_names = [str(name) for name in column_names]
        self.n_rows = 0
        self.supported = bool(self.column_names)
        self._accumulators = [_ColumnAccumulator(col) for col in range(len(self.column_names))]

    def add_rows(self, rows: list) -> bool:
        """Append a chunk of row tuples; ``False`` once the table is unsupported."""
        if not self.supported:
            return False
        if not rows:
            return True
        if set(map(len, rows)) != {len(self._accumulators)}:
            self.supported = False
            return False
        for accumulator, values in zip(self._accumulators, zip(*rows)):
            if not accumulator.add(values):
                self.supported = False
                return False
        self.n_rows += len(rows)
        return True

    def build(self) -> BulkPlan | None:
        """Return the plan, or ``None`` when empty or unsupported."""
        if not self.supported or not self.n_rows:
            return None
        columns = [accumulator.build() for accumulator in self._accumulators]
        return BulkPlan(column_names=self.column_names, n_rows=self.n_rows, columns=columns)


def bulk_block_fits(plan: BulkPlan, *, first_row: int = 1) -> bool:
    """Return whether ``plan`` fits a worksheet starting at ``first_row``."""
    return first_row + plan.n_rows <= _XLS_ROW_MAX and len(plan.columns) <= _XLS_COL_MAX


def plan_bulk_rows(columns: list, rows: list) -> BulkPlan | None:
    """Return a bulk plan for ``rows`` of Python scalars, or ``None`` if unsupported."""
    builder = BulkPlanBuilder(columns)
    return builder.build() if builder.add_rows(rows) else None


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
    def _write_cell(self, row, col, cell):
        markup = fast_cell_markup(self, row, col, cell)
        if markup is None:
            super()._write_cell(row, col, cell)
        else:
            self.fh.write(markup)

    def write_column(self, *args, **kwargs):
        """Write a column of data; plain numbers/strings take a faster route."""
        if len(args) != 3 or kwargs or type(args[0]) is not int or type(args[1]) is not int:
            return super().write_column(*args, **kwargs)
        row, col, values = args[0], args[1], list(args[2])
        if not self._overlaps_bulk_block(row, row + len(values) - 1) and write_plain_column(self, row, col, values):
            return 0
        return super().write_column(row, col, values)

    def _overlaps_bulk_block(self, first_row: int, last_row: int) -> bool:
        return any(block.first_row <= last_row and first_row <= block.last_row for block in self._bulk_blocks)

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
        first_group = block.first_row // _ROW_SPAN_GROUP
        last_group = block.last_row // _ROW_SPAN_GROUP
        for group in range(first_group, last_group + 1):
            # Each absolute 16-row group intersects a contiguous block slice.
            start = max(0, group * _ROW_SPAN_GROUP - block.first_row)
            stop = min(block.n_rows, (group + 1) * _ROW_SPAN_GROUP - block.first_row)
            high = int(highs[start:stop].max())
            if high < 0:  # All rows in this group are blank.
                continue
            low = int(lows[start:stop].min()) + 1
            high += 1
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
    add_chart = book.add_chart

    def add_accelerated_chart(*args, **kwargs):
        return accelerate_chart(add_chart(*args, **kwargs))

    book.add_chart = add_accelerated_chart
    return True


__all__ = [
    "BULK_WRITE_ENV",
    "BulkPlan",
    "BulkPlanBuilder",
    "BulkRowsWorksheet",
    "bulk_block_fits",
    "bulk_write_enabled",
    "enable_bulk_rows",
    "plan_bulk_rows",
]

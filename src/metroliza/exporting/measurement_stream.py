"""Stream the raw MEASUREMENTS table from the export snapshot (#1124).

The default export only needs the full measurement table to write the raw
``MEASUREMENTS`` sheet.  Reading it through the snapshot cursor in chunks lets
the bulk worksheet path consume rows without first materialising a second,
38-column copy of the whole snapshot in Python.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from typing import Any

STREAM_CHUNK_ROWS = 4000
_MIN_COLUMN_WIDTH = 12
_MAX_COLUMN_WIDTH = 40


def column_width_for_values(values: Any) -> int:
    """Return the sheet column width used for a sample of cell values."""
    width = max((len(str(value)) for value in values), default=0)
    return max(min(width, _MAX_COLUMN_WIDTH), _MIN_COLUMN_WIDTH)


class ColumnWidthSample:
    """Keep the head/tail rows that column-width sizing inspects.

    Mirrors ``ExportDataThread._sample_column_for_width``: every row up to
    ``sample_limit`` rows, otherwise the first and last ``sample_limit // 2``.
    """

    def __init__(self, sample_limit: int) -> None:
        limit = max(1, int(sample_limit or 1))
        self.limit = limit
        self.head_count = limit // 2
        self.tail_count = limit - self.head_count
        self.head: list = []
        self.tail: deque = deque(maxlen=self.tail_count)
        self.row_count = 0

    def add(self, rows: list) -> None:
        """Record one chunk of rows."""
        missing_head = self.head_count - len(self.head)
        if missing_head > 0:
            self.head.extend(rows[:missing_head])
        self.tail.extend(rows[-self.tail_count :])
        self.row_count += len(rows)

    def sample_rows(self) -> list:
        """Return the rows the classic sampler would look at."""
        if self.row_count <= self.head_count:
            return list(self.head)
        if self.row_count <= self.limit:
            return list(self.head) + list(self.tail)[-(self.row_count - self.head_count) :]
        return list(self.head) + list(self.tail)

    def column_widths(self, column_count: int) -> list[int]:
        """Return one column width per column from the sampled rows."""
        rows = self.sample_rows()
        return [column_width_for_values(row[index] for row in rows) for index in range(column_count)]


def iter_row_chunks(
    cursor: Any,
    sample: ColumnWidthSample,
    should_stop: Callable[[], bool],
    chunk_rows: int = STREAM_CHUNK_ROWS,
) -> Iterator[list]:
    """Yield row chunks from ``cursor`` until it is exhausted or ``should_stop``."""
    while not should_stop():
        rows = cursor.fetchmany(chunk_rows)
        if not rows:
            return
        sample.add(rows)
        yield rows

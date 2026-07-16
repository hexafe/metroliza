"""Lightweight row-table primitives shared by analytics consumers.

The analytics package owns this pandas-free in-memory table boundary so analysis
services do not depend on export query implementation details.  Export callers
continue to receive these objects through compatibility re-exports from
``metroliza.exporting.export_query_service``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence


class RowMapping(dict):
    """Small row mapping with the pandas-compatible ``to_dict`` method."""

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


class RowStringMethods:
    """Minimal string accessor for :class:`RowColumn` compatibility."""

    def __init__(self, column: "RowColumn"):
        self._column = column

    def lower(self) -> "RowColumn":
        return RowColumn(str(value).lower() for value in self._column)

    def strip(self) -> "RowColumn":
        return RowColumn(str(value).strip() for value in self._column)

    def casefold(self) -> "RowColumn":
        return RowColumn(str(value).casefold() for value in self._column)


class RowColumn(Sequence[Any]):
    """Sequence wrapper for one named column in a :class:`RowTable`."""

    def __init__(self, values: Iterable[Any]):
        self._values = tuple(values)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, index: int | slice) -> Any:
        if isinstance(index, slice):
            return RowColumn(self._values[index])
        return self._values[index]

    @property
    def empty(self) -> bool:
        return len(self._values) == 0

    @property
    def iloc(self) -> "RowColumn":
        return self

    @property
    def str(self) -> RowStringMethods:
        return RowStringMethods(self)

    def tolist(self) -> list[Any]:
        return list(self._values)

    def astype(self, dtype: Any) -> "RowColumn":
        if dtype in (str, "str", "string"):
            converter = str
        elif dtype in (int, "int", "Int64"):
            converter = int
        elif dtype in (float, "float", "float64"):
            converter = float
        else:
            converter = dtype
        converted = []
        for value in self._values:
            try:
                converted.append(converter(value))
            except (TypeError, ValueError):
                converted.append(value)
        return RowColumn(converted)

    def to_numpy(self, dtype: Any = None, copy: bool = False) -> Any:
        import numpy as np

        return np.asarray(self._values, dtype=dtype)

    def unique(self) -> list[Any]:
        seen = set()
        values = []
        for value in self._values:
            marker = _hashable_marker(value)
            if marker in seen:
                continue
            seen.add(marker)
            values.append(value)
        return values

    def nunique(self, *, dropna: bool = True) -> int:
        values = self.unique()
        if dropna:
            values = [value for value in values if not _is_missing_value(value)]
        return len(values)

    def drop_duplicates(self) -> "RowColumn":
        return RowColumn(self.unique())

    def notna(self) -> list[bool]:
        return [not _is_missing_value(value) for value in self._values]

    def round(self, decimals: int = 0) -> "RowColumn":
        rounded = []
        for value in self._values:
            try:
                rounded.append(round(float(value), decimals))
            except (TypeError, ValueError):
                rounded.append(value)
        return RowColumn(rounded)


class RowGroupBy:
    """Minimal group-by iterator for row tables."""

    def __init__(
        self,
        table: "RowTable",
        column_names: str | Sequence[str],
        *,
        sort: bool = True,
    ):
        self._table = table
        self._column_names = (
            (column_names,) if isinstance(column_names, str) else tuple(column_names)
        )
        self._sort = sort

    def __iter__(self) -> Iterator[tuple[Any, "RowTable"]]:
        grouped: dict[Any, list[tuple[Any, ...]]] = {}
        keys_by_marker: dict[Any, Any] = {}
        column_indexes = [
            self._table.columns.index(column_name) for column_name in self._column_names
        ]
        for row in self._table.rows:
            if len(column_indexes) == 1:
                key = row[column_indexes[0]]
            else:
                key = tuple(row[column_index] for column_index in column_indexes)
            marker = _hashable_marker(key)
            keys_by_marker.setdefault(marker, key)
            grouped.setdefault(marker, []).append(row)

        markers = list(grouped)
        if self._sort:
            markers.sort(key=lambda marker: _sort_marker(keys_by_marker[marker]))

        for marker in markers:
            yield keys_by_marker[marker], RowTable(
                rows=tuple(grouped[marker]),
                columns=tuple(self._table.columns),
            )


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    return False


def _hashable_marker(value: Any) -> Any:
    if _is_missing_value(value):
        return ("__missing__",)
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def _sort_marker(value: Any) -> tuple[bool, str]:
    return _is_missing_value(value), str(value)


class _RowTableLoc:
    def __init__(self, table: "RowTable"):
        self._table = table

    def __getitem__(self, key: tuple[int, str]) -> Any:
        row_index, column_name = key
        return self._table.row_mapping(row_index)[column_name]


class _RowTableIloc:
    def __init__(self, table: "RowTable"):
        self._table = table

    def __getitem__(self, row_index: int | slice | Iterable[int]) -> RowMapping | "RowTable":
        if isinstance(row_index, slice):
            return RowTable(
                rows=tuple(self._table.rows[row_index]),
                columns=tuple(self._table.columns),
            )
        if not isinstance(row_index, (str, bytes)) and hasattr(row_index, "__iter__"):
            return RowTable(
                rows=tuple(self._table.rows[int(index)] for index in row_index),
                columns=tuple(self._table.columns),
            )
        return self._table.row_mapping(int(row_index))


class _IndexedRowTableLoc:
    def __init__(self, table: "RowTable", index_column: str):
        self._table = table
        self._index_column = index_column

    def __getitem__(self, key: tuple[Any, str]) -> Any:
        row_key, column_name = key
        index_column_position = self._table.columns.index(self._index_column)
        column_position = self._table.columns.index(column_name)
        for row in self._table.rows:
            if row[index_column_position] == row_key:
                return row[column_position]
        raise KeyError(row_key)


class _IndexedRowTable:
    def __init__(self, table: "RowTable", index_column: str):
        self._table = table
        self._index_column = index_column

    @property
    def loc(self) -> _IndexedRowTableLoc:
        return _IndexedRowTableLoc(self._table, self._index_column)


@dataclass
class RowTable:
    """Mutable row table for pandas-free analysis and export paths."""

    rows: tuple[tuple[Any, ...], ...]
    columns: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return len(self.rows) == 0

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.rows), len(self.columns)

    @property
    def index(self) -> tuple[int, ...]:
        return tuple(range(len(self.rows)))

    @property
    def loc(self) -> _RowTableLoc:
        return _RowTableLoc(self)

    @property
    def iloc(self) -> _RowTableIloc:
        return _RowTableIloc(self)

    def __len__(self) -> int:
        return len(self.rows)

    def __contains__(self, column_name: object) -> bool:
        """Return whether ``column_name`` is present in the table schema.

        Defining membership explicitly is important because Python otherwise
        falls back to integer ``__getitem__`` probes.  ``RowTable`` reserves
        ``__getitem__`` for column selection; positional row access belongs to
        :attr:`iloc`.
        """

        return column_name in self.columns

    def __getitem__(self, key: str | Sequence[str]) -> RowColumn | "RowTable":
        if isinstance(key, str):
            column_index = self.columns.index(key)
            return RowColumn(row[column_index] for row in self.rows)

        if not isinstance(key, Sequence) or isinstance(key, (bytes, bytearray)):
            raise TypeError(
                "RowTable column selection requires a column name or a sequence "
                "of column names; use .iloc for positional row access"
            )

        selected_columns = tuple(str(column) for column in key)
        column_indexes = [self.columns.index(column) for column in selected_columns]
        return RowTable(
            rows=tuple(tuple(row[index] for index in column_indexes) for row in self.rows),
            columns=selected_columns,
        )

    def __setitem__(self, column_name: str, values: Iterable[Any]) -> None:
        value_tuple = tuple(values)
        if len(value_tuple) != len(self.rows):
            raise ValueError("assigned column length must match row count")

        if column_name in self.columns:
            column_index = self.columns.index(column_name)
            self.rows = tuple(
                tuple(
                    value if index == column_index else current
                    for index, current in enumerate(row)
                )
                for row, value in zip(self.rows, value_tuple)
            )
            return

        self.columns = (*self.columns, str(column_name))
        self.rows = tuple((*row, value) for row, value in zip(self.rows, value_tuple))

    def copy(self) -> "RowTable":
        return RowTable(rows=tuple(tuple(row) for row in self.rows), columns=tuple(self.columns))

    def get(self, column_name: str, default: Any = None) -> RowColumn | Any:
        if column_name not in self.columns:
            return default
        return self[column_name]

    def assign(self, **columns: Iterable[Any]) -> "RowTable":
        table = self.copy()
        for column_name, values in columns.items():
            table[column_name] = values
        return table

    def drop(self, *, columns: Sequence[str] | str) -> "RowTable":
        drop_columns = {columns} if isinstance(columns, str) else set(columns)
        keep_columns = tuple(column for column in self.columns if column not in drop_columns)
        return self[keep_columns]

    def dropna(self, *, subset: Sequence[str] | None = None) -> "RowTable":
        subset_columns = tuple(subset or self.columns)
        column_indexes = [self.columns.index(column) for column in subset_columns]
        return RowTable(
            rows=tuple(
                row
                for row in self.rows
                if all(
                    not _is_missing_value(row[column_index])
                    for column_index in column_indexes
                )
            ),
            columns=tuple(self.columns),
        )

    def set_index(self, column_name: str) -> _IndexedRowTable:
        if column_name not in self.columns:
            raise KeyError(column_name)
        return _IndexedRowTable(self, column_name)

    def sort_values(
        self,
        by: Sequence[str] | str,
        *,
        kind: str | None = None,
        key: Callable[[RowColumn], Sequence[Any]] | None = None,
    ) -> "RowTable":
        sort_columns = (by,) if isinstance(by, str) else tuple(by)
        column_indexes = [self.columns.index(column) for column in sort_columns]
        sort_value_columns = []
        for column_index in column_indexes:
            column_values = RowColumn(row[column_index] for row in self.rows)
            transformed = key(column_values) if key is not None else column_values
            transformed_values = tuple(
                transformed.tolist() if hasattr(transformed, "tolist") else transformed
            )
            if len(transformed_values) != len(self.rows):
                raise ValueError("sort key must preserve row count")
            sort_value_columns.append(transformed_values)

        sorted_indexes = sorted(
            range(len(self.rows)),
            key=lambda row_index: tuple(
                _sort_marker(sort_values[row_index]) for sort_values in sort_value_columns
            ),
        )
        sorted_rows = tuple(self.rows[index] for index in sorted_indexes)
        return RowTable(rows=tuple(sorted_rows), columns=tuple(self.columns))

    def groupby(
        self,
        column_names: str | Sequence[str],
        *,
        as_index: bool = True,
        sort: bool = True,
    ) -> RowGroupBy:
        return RowGroupBy(self, column_names, sort=sort)

    def row_mapping(self, row_index: int) -> RowMapping:
        return RowMapping(zip(self.columns, self.rows[row_index]))

    def iter_rows(self, *, as_dict: bool = False) -> Iterator[tuple[Any, ...] | RowMapping]:
        for index, row in enumerate(self.rows):
            yield self.row_mapping(index) if as_dict else row

    def iterrows(self) -> Iterator[tuple[int, RowMapping]]:
        for index in range(len(self.rows)):
            yield index, self.row_mapping(index)


def coerce_to_row_table(data: Any, column_names: Sequence[str] | None = None) -> RowTable:
    """Coerce SQL, pandas-like, or mapping records to a :class:`RowTable`."""
    if isinstance(data, RowTable):
        return data.copy()

    if column_names is not None:
        return RowTable(
            rows=tuple(tuple(row) for row in data),
            columns=tuple(str(column) for column in column_names),
        )

    if isinstance(data, tuple) and len(data) == 2:
        rows, columns = data
        return coerce_to_row_table(rows, columns)

    columns = tuple(str(column) for column in getattr(data, "columns", ()))
    if columns and hasattr(data, "itertuples"):
        return RowTable(
            rows=tuple(tuple(row) for row in data.itertuples(index=False, name=None)),
            columns=columns,
        )

    if columns and hasattr(data, "rows"):
        return RowTable(
            rows=tuple(tuple(row) for row in data.rows),
            columns=columns,
        )

    if isinstance(data, Sequence) and data and isinstance(data[0], Mapping):
        columns = tuple(str(column) for column in data[0].keys())
        return RowTable(
            rows=tuple(tuple(row.get(column) for column in columns) for row in data),
            columns=columns,
        )

    return RowTable(rows=(), columns=columns)


# Private spelling retained for callers migrating from export_query_service.
_coerce_to_row_table = coerce_to_row_table

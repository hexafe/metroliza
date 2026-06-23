"""Convert SQL query results into export-ready row tables and partition summaries.

This module provides helpers that execute scoped SQL queries and transform their
results into lightweight row contracts used by export flows, including
partition-based value/header summaries and measurement-specific export shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from metroliza.reports.db import execute_select_with_columns


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

    def __init__(self, table: "RowTable", column_names: str | Sequence[str], *, sort: bool = True):
        self._table = table
        self._column_names = (column_names,) if isinstance(column_names, str) else tuple(column_names)
        self._sort = sort

    def __iter__(self) -> Iterator[tuple[Any, "RowTable"]]:
        grouped: dict[Any, list[tuple[Any, ...]]] = {}
        keys_by_marker: dict[Any, Any] = {}
        column_indexes = [self._table.columns.index(column_name) for column_name in self._column_names]
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
    """Immutable-ish table contract for export rows without pandas at runtime."""

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

    def __getitem__(self, key: str | Sequence[str]) -> RowColumn | "RowTable":
        if isinstance(key, str):
            column_index = self.columns.index(key)
            return RowColumn(row[column_index] for row in self.rows)

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
                tuple(value if index == column_index else current for index, current in enumerate(row))
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
                row for row in self.rows
                if all(not _is_missing_value(row[column_index]) for column_index in column_indexes)
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

    def groupby(self, column_names: str | Sequence[str], *, as_index: bool = True, sort: bool = True) -> RowGroupBy:
        return RowGroupBy(self, column_names, sort=sort)

    def row_mapping(self, row_index: int) -> RowMapping:
        return RowMapping(zip(self.columns, self.rows[row_index]))

    def iter_rows(self, *, as_dict: bool = False) -> Iterator[tuple[Any, ...] | RowMapping]:
        for index, row in enumerate(self.rows):
            yield self.row_mapping(index) if as_dict else row

    def iterrows(self) -> Iterator[tuple[int, RowMapping]]:
        for index in range(len(self.rows)):
            yield index, self.row_mapping(index)


def _coerce_to_row_table(data: Any, column_names: Sequence[str] | None = None) -> RowTable:
    if isinstance(data, RowTable):
        return data.copy()

    if column_names is not None:
        return RowTable(
            rows=tuple(tuple(row) for row in data),
            columns=tuple(str(column) for column in column_names),
        )

    if isinstance(data, tuple) and len(data) == 2:
        rows, columns = data
        return _coerce_to_row_table(rows, columns)

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


def build_export_dataframe(data, column_names):
    """Build an export row table from raw row data and ordered column names.

    Args:
        data: Iterable SQL result rows.
        column_names: Column names aligned with each row in ``data``.

    Returns:
        A newly created ``RowTable`` instance.
    """
    return _coerce_to_row_table(data, column_names)


def execute_export_query(db_file, export_query, select_reader=execute_select_with_columns):
    """Execute an export SQL query and return rows with column metadata.

    Args:
        db_file: Path to the SQLite database.
        export_query: SQL query string to execute.
        select_reader: Callable used to execute the query.

    Returns:
        The result from ``select_reader`` for ``export_query``.
    """
    return select_reader(db_file, export_query)


def ensure_sample_number_column(table):
    """Ensure a ``SAMPLE_NUMBER`` column exists for measurement exports.

    Args:
        table: Source row table or DataFrame-like object.

    Returns:
        A row table with ``SAMPLE_NUMBER`` populated as 1-based string indices
        when missing.
    """
    normalized_table = _coerce_to_row_table(table)
    if 'SAMPLE_NUMBER' in normalized_table.columns:
        return normalized_table

    normalized_table['SAMPLE_NUMBER'] = [str(index + 1) for index in range(len(normalized_table))]
    return normalized_table


def build_measurement_export_dataframe(table):
    """Build a measurement export row table with computed header key columns.

    Args:
        table: Source row table containing at least ``HEADER`` and ``AX`` columns.

    Returns:
        A row table that always includes ``SAMPLE_NUMBER`` (added when missing)
        and adds ``HEADER - AX`` as ``HEADER + " - " + AX``.
    """
    export_table = ensure_sample_number_column(table).copy()
    header_ax_values = [
        f"{row['HEADER']} - {row['AX']}"
        for row in export_table.iter_rows(as_dict=True)
    ]
    export_table['HEADER - AX'] = header_ax_values
    return export_table


def load_measurement_export_dataframe(db_file, filter_query, select_reader=execute_select_with_columns):
    """Load query results and convert them to measurement export format.

    Args:
        db_file: Path to the SQLite database.
        filter_query: SQL query that selects export rows.
        select_reader: Callable that returns ``(rows, columns)``.

    Returns:
        A measurement export row table.
    """
    return build_measurement_export_dataframe(select_reader(db_file, filter_query))


def _build_scoped_export_query(filter_query):
    # Wrap the caller-provided query so downstream SQL can safely scope aliases.
    return f"SELECT * FROM ({filter_query}) AS export_scope"


def _read_sql_query(db_file, query, *, params=(), connection: sqlite3.Connection | None = None):
    return _coerce_to_row_table(
        execute_select_with_columns(db_file, query, params=params, connection=connection)
    )


def fetch_partition_values(
    db_file,
    filter_query,
    *,
    partition_column='REFERENCE',
    connection: sqlite3.Connection | None = None,
):
    """Fetch distinct non-null partition values for a scoped export query.

    Args:
        db_file: Path to the SQLite database.
        filter_query: SQL query used as the scoped source.
        partition_column: Column name used to partition export rows.
        connection: Optional active SQLite connection to reuse.

    Returns:
        A list of distinct values from ``partition_column`` excluding ``NULL``.

    Notes:
        ``partition_column`` must exist in ``filter_query`` output.
    """
    scoped_query = _build_scoped_export_query(filter_query)
    query = (
        f'SELECT DISTINCT "{partition_column}" AS partition_value '
        f'FROM ({scoped_query}) AS partition_scope '
        f'WHERE "{partition_column}" IS NOT NULL'
    )
    partitions = _read_sql_query(db_file, query, connection=connection)
    return partitions['partition_value'].tolist()


def fetch_partition_header_counts(
    db_file,
    filter_query,
    *,
    partition_column='REFERENCE',
    header_expr="HEADER || ' - ' || AX",
    connection: sqlite3.Connection | None = None,
):
    """Count distinct headers per partition from a scoped export query.

    Args:
        db_file: Path to the SQLite database.
        filter_query: SQL query used as the scoped source.
        partition_column: Column name used to partition export rows.
        header_expr: SQL expression that defines a header identity for distinct
            counting (defaults to ``HEADER || ' - ' || AX``).
        connection: Optional active SQLite connection to reuse.

    Returns:
        A mapping of ``partition_value`` to integer distinct-header counts.

    Notes:
        ``partition_column`` and all columns referenced by ``header_expr`` must
        be available in ``filter_query`` output.
    """
    scoped_query = _build_scoped_export_query(filter_query)
    query = f'''
        SELECT
            "{partition_column}" AS partition_value,
            COUNT(DISTINCT ({header_expr})) AS header_count
        FROM ({scoped_query}) AS partition_scope
        WHERE "{partition_column}" IS NOT NULL
        GROUP BY "{partition_column}"
    '''
    counts_table = _coerce_to_row_table(_read_sql_query(db_file, query, connection=connection))
    return {
        row['partition_value']: int(row['header_count'])
        for row in counts_table.iter_rows(as_dict=True)
    }


def load_export_partition_dataframe(
    db_file,
    filter_query,
    partition_value,
    *,
    partition_column='REFERENCE',
    connection: sqlite3.Connection | None = None,
):
    """Load rows for a single partition value from a scoped export query.

    Args:
        db_file: Path to the SQLite database.
        filter_query: SQL query used as the scoped source.
        partition_value: Value matched against ``partition_column``.
        partition_column: Column name used to partition export rows.
        connection: Optional active SQLite connection to reuse.

    Returns:
        A row table whose rows have ``partition_column`` equal to
        ``partition_value``. If no rows match, returns an empty row table.

    Notes:
        ``partition_column`` must exist in ``filter_query`` output.
    """
    scoped_query = _build_scoped_export_query(filter_query)
    query = (
        f'SELECT * FROM ({scoped_query}) AS partition_scope '
        f'WHERE "{partition_column}" = ?'
    )
    return _coerce_to_row_table(
        _read_sql_query(db_file, query, params=(partition_value,), connection=connection)
    )


def load_measurement_export_partition_dataframe(
    db_file,
    filter_query,
    partition_value,
    *,
    partition_column='REFERENCE',
    connection: sqlite3.Connection | None = None,
):
    """Load partitioned rows and convert them to measurement export format.

    Args:
        db_file: Path to the SQLite database.
        filter_query: SQL query used as the scoped source.
        partition_value: Value matched against ``partition_column``.
        partition_column: Column name used to partition export rows.
        connection: Optional active SQLite connection to reuse.

    Returns:
        A measurement export row table for the requested partition.
    """
    partition_df = load_export_partition_dataframe(
        db_file,
        filter_query,
        partition_value,
        partition_column=partition_column,
        connection=connection,
    )
    return build_measurement_export_dataframe(partition_df)


def fetch_sql_measurement_summary(
    db_file,
    filter_query,
    *,
    reference,
    header,
    ax,
    usl,
    lsl,
    connection: sqlite3.Connection | None = None,
):
    """Compute summary statistics for one ``REFERENCE``/``HEADER``/``AX`` key.

    Args:
        db_file: Path to the SQLite database.
        filter_query: SQL query used as the scoped source.
        reference: ``REFERENCE`` value to filter.
        header: ``HEADER`` value to filter.
        ax: ``AX`` value to filter.
        usl: Upper specification limit used for NOK counting.
        lsl: Lower specification limit used for NOK counting.
        connection: Optional active SQLite connection to reuse.

    Returns:
        A dictionary containing aggregate fields (sample size, average, min,
        max, NOK count, sigma) for the selected measurement scope, or ``None``
        when no summary row is returned.

    Notes:
        The ``None`` path handles empty query-result cases defensively.
    """
    scoped_query = _build_scoped_export_query(filter_query)
    query = f'''
        SELECT
            COUNT(MEAS) AS sample_size,
            AVG(MEAS) AS average,
            MIN(MEAS) AS minimum,
            MAX(MEAS) AS maximum,
            SUM(CASE WHEN MEAS > ? OR MEAS < ? THEN 1 ELSE 0 END) AS nok_count,
            CASE WHEN COUNT(MEAS) > 1 THEN
                SQRT(
                    (SUM(MEAS * MEAS) - (SUM(MEAS) * SUM(MEAS) / COUNT(MEAS))) / (COUNT(MEAS) - 1)
                )
            ELSE 0 END AS sigma
        FROM ({scoped_query}) AS summary_scope
        WHERE REFERENCE = ? AND HEADER = ? AND AX = ?
    '''
    params = (usl, lsl, reference, header, ax)
    summary_table = _coerce_to_row_table(
        _read_sql_query(db_file, query, params=params, connection=connection)
    )
    if summary_table.empty:
        return None
    return summary_table.iloc[0].to_dict()


def fetch_sql_measurement_summaries(
    db_file,
    filter_query,
    *,
    reference=None,
    connection: sqlite3.Connection | None = None,
):
    """Compute grouped summary statistics for all measurement keys in scope.

    Args:
        db_file: Path to the SQLite database.
        filter_query: SQL query used as the scoped source.
        reference: Optional ``REFERENCE`` value to restrict grouped summaries.
        connection: Optional active SQLite connection to reuse.

    Returns:
        A mapping keyed by ``(REFERENCE, HEADER, AX)`` to aggregate summary
        dictionaries containing sample size, average, min, max, NOK count, and
        sigma values.
    """
    scoped_query = _build_scoped_export_query(filter_query)
    where_clause = 'WHERE REFERENCE = ?' if reference is not None else ''
    query = f'''
        SELECT
            REFERENCE,
            HEADER,
            AX,
            COUNT(MEAS) AS sample_size,
            AVG(MEAS) AS average,
            MIN(MEAS) AS minimum,
            MAX(MEAS) AS maximum,
            SUM(
                CASE
                    WHEN MEAS > (NOM + "+TOL") OR MEAS < (NOM + COALESCE("-TOL", 0))
                    THEN 1
                    ELSE 0
                END
            ) AS nok_count,
            CASE WHEN COUNT(MEAS) > 1 THEN
                SQRT(
                    (SUM(MEAS * MEAS) - (SUM(MEAS) * SUM(MEAS) / COUNT(MEAS))) / (COUNT(MEAS) - 1)
                )
            ELSE 0 END AS sigma
        FROM ({scoped_query}) AS summary_scope
        {where_clause}
        GROUP BY REFERENCE, HEADER, AX
    '''
    params = (reference,) if reference is not None else ()
    summary_table = _coerce_to_row_table(
        _read_sql_query(db_file, query, params=params, connection=connection)
    )
    if summary_table.empty:
        return {}

    summaries = {}
    for row in summary_table.iter_rows(as_dict=True):
        key = (row['REFERENCE'], row['HEADER'], row['AX'])
        summaries[key] = row.to_dict()
    return summaries

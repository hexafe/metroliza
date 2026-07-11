"""Convert SQL query results into export-ready row tables and partition summaries.

This module provides helpers that execute scoped SQL queries and transform their
results into lightweight row contracts used by export flows, including
partition-based value/header summaries and measurement-specific export shapes.
"""

from __future__ import annotations

import sqlite3

from metroliza.analytics.row_table import (
    RowColumn as RowColumn,
    RowGroupBy as RowGroupBy,
    RowMapping as RowMapping,
    RowStringMethods as RowStringMethods,
    RowTable as RowTable,
    coerce_to_row_table as _coerce_to_row_table,
)
from metroliza.reports.db import execute_select_with_columns, quote_identifier


_PARTITION_HEADER_EXPRESSIONS = frozenset({"HEADER || ' - ' || AX"})


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


def _validated_partition_header_expression(header_expr: str) -> str:
    normalized = " ".join(str(header_expr).split())
    if normalized not in _PARTITION_HEADER_EXPRESSIONS:
        raise ValueError("Unsupported partition header expression")
    return normalized


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
    quoted_partition = quote_identifier(partition_column)
    query = (
        f"SELECT DISTINCT {quoted_partition} AS partition_value "
        f'FROM ({scoped_query}) AS partition_scope '
        f"WHERE {quoted_partition} IS NOT NULL"
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
    quoted_partition = quote_identifier(partition_column)
    validated_header_expr = _validated_partition_header_expression(header_expr)
    query = f'''
        SELECT
            {quoted_partition} AS partition_value,
            COUNT(DISTINCT ({validated_header_expr})) AS header_count
        FROM ({scoped_query}) AS partition_scope
        WHERE {quoted_partition} IS NOT NULL
        GROUP BY {quoted_partition}
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
    quoted_partition = quote_identifier(partition_column)
    query = (
        f'SELECT * FROM ({scoped_query}) AS partition_scope '
        f"WHERE {quoted_partition} = ?"
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

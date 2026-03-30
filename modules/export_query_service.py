"""Convert SQL query results into export-ready DataFrames and partition summaries.

This module provides helpers that execute scoped SQL queries and transform their
results into pandas DataFrames used by export flows, including partition-based
value/header summaries and measurement-specific export shapes.
"""

import sqlite3

import pandas as pd

from modules.db import execute_select_with_columns, read_sql_dataframe, sqlite_connection_scope


def build_export_dataframe(data, column_names):
    """Build an export DataFrame from raw row data and ordered column names.

    Args:
        data: Iterable SQL result rows.
        column_names: Column names aligned with each row in ``data``.

    Returns:
        A newly created pandas ``DataFrame`` instance.
    """
    return pd.DataFrame(data, columns=column_names)


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


def ensure_sample_number_column(df):
    """Ensure a ``SAMPLE_NUMBER`` column exists for measurement exports.

    Args:
        df: Source DataFrame.

    Returns:
        The original DataFrame when ``SAMPLE_NUMBER`` already exists (reused,
        not copied). Otherwise, returns a copied DataFrame with
        ``SAMPLE_NUMBER`` populated as 1-based string indices.
    """
    if 'SAMPLE_NUMBER' in df.columns:
        return df

    normalized_df = df.copy()
    normalized_df['SAMPLE_NUMBER'] = [str(index + 1) for index in range(len(normalized_df))]
    return normalized_df


def build_measurement_export_dataframe(df):
    """Build a measurement export DataFrame with computed header key columns.

    Args:
        df: Source DataFrame containing at least ``HEADER`` and ``AX`` columns.

    Returns:
        A copied DataFrame that always includes ``SAMPLE_NUMBER`` (added when
        missing) and adds ``HEADER - AX`` as ``HEADER + " - " + AX``.

    Notes:
        ``ensure_sample_number_column`` may reuse ``df`` when
        ``SAMPLE_NUMBER`` already exists, but this function always returns a
        copy before adding ``HEADER - AX``.
    """
    normalized_df = ensure_sample_number_column(df)
    export_df = normalized_df.copy()
    export_df['HEADER - AX'] = export_df['HEADER'] + ' - ' + export_df['AX']
    return export_df


def load_measurement_export_dataframe(db_file, filter_query, dataframe_reader=read_sql_dataframe):
    """Load query results and convert them to measurement export format.

    Args:
        db_file: Path to the SQLite database.
        filter_query: SQL query that selects export rows.
        dataframe_reader: Callable that returns a pandas DataFrame.

    Returns:
        A measurement export DataFrame. Empty query results return an empty
        DataFrame transformed by ``build_measurement_export_dataframe``.
    """
    df = dataframe_reader(db_file, filter_query)
    return build_measurement_export_dataframe(df)


def _build_scoped_export_query(filter_query):
    # Wrap the caller-provided query so downstream SQL can safely scope aliases.
    return f"SELECT * FROM ({filter_query}) AS export_scope"


def _read_sql_query(db_file, query, *, params=(), connection: sqlite3.Connection | None = None):
    # Run SQL with either the provided connection or a scoped connection context.
    if connection is not None:
        return pd.read_sql_query(query, connection, params=params)
    with sqlite_connection_scope(db_file) as conn:
        return pd.read_sql_query(query, conn, params=params)


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
    partitions_df = _read_sql_query(db_file, query, connection=connection)
    return partitions_df['partition_value'].tolist()


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
    counts_df = _read_sql_query(db_file, query, connection=connection)
    return {
        row['partition_value']: int(row['header_count'])
        for _, row in counts_df.iterrows()
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
        A DataFrame of rows whose ``partition_column`` equals ``partition_value``.
        If no rows match, returns an empty DataFrame.

    Notes:
        ``partition_column`` must exist in ``filter_query`` output.
    """
    scoped_query = _build_scoped_export_query(filter_query)
    query = (
        f'SELECT * FROM ({scoped_query}) AS partition_scope '
        f'WHERE "{partition_column}" = ?'
    )
    return _read_sql_query(db_file, query, params=(partition_value,), connection=connection)


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
        A measurement export DataFrame for the requested partition. If the
        partition has no rows, returns an empty transformed DataFrame.
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
    summary_df = _read_sql_query(db_file, query, params=params, connection=connection)
    if summary_df.empty:
        return None
    return summary_df.iloc[0].to_dict()


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
    summary_df = _read_sql_query(db_file, query, params=params, connection=connection)
    if summary_df.empty:
        return {}

    summaries = {}
    for _, row in summary_df.iterrows():
        key = (row['REFERENCE'], row['HEADER'], row['AX'])
        summaries[key] = row.to_dict()
    return summaries

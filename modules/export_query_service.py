import sqlite3

import pandas as pd

from modules.db import execute_select_with_columns, read_sql_dataframe, sqlite_connection_scope


def build_export_dataframe(data, column_names):
    return pd.DataFrame(data, columns=column_names)


def execute_export_query(db_file, export_query, select_reader=execute_select_with_columns):
    return select_reader(db_file, export_query)


def ensure_sample_number_column(df):
    if 'SAMPLE_NUMBER' in df.columns:
        return df

    normalized_df = df.copy()
    normalized_df['SAMPLE_NUMBER'] = [str(index + 1) for index in range(len(normalized_df))]
    return normalized_df


def build_measurement_export_dataframe(df):
    normalized_df = ensure_sample_number_column(df)
    export_df = normalized_df.copy()
    export_df['HEADER - AX'] = export_df['HEADER'] + ' - ' + export_df['AX']
    return export_df


def load_measurement_export_dataframe(db_file, filter_query, dataframe_reader=read_sql_dataframe):
    df = dataframe_reader(db_file, filter_query)
    return build_measurement_export_dataframe(df)


def _build_scoped_export_query(filter_query):
    return f"SELECT * FROM ({filter_query}) AS export_scope"


def _read_sql_query(db_file, query, *, params=(), connection: sqlite3.Connection | None = None):
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
    header_expr='HEADER || " - " || AX',
    connection: sqlite3.Connection | None = None,
):
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

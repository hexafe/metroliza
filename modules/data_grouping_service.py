"""Database/query and dataframe mutation helpers for data-grouping UI."""

import hashlib


def build_grouping_query(filter_query):
    """Build the grouping dataset query, optionally wrapping a caller filter query."""
    default_query = "SELECT DISTINCT REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER FROM REPORTS"
    if not isinstance(filter_query, str) or not filter_query.strip():
        return default_query

    return f"""
            SELECT DISTINCT REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER
            FROM (
                {filter_query.strip()}
            ) AS FILTERED_DATA
        """


def load_grouping_dataframe(read_sql_dataframe, db_file, filter_query):
    """Read grouping rows from SQLite using a normalized grouping query."""
    query = build_grouping_query(filter_query)
    return read_sql_dataframe(db_file, query)


def compute_group_key_for_df(df):
    """Return a stable SHA1 key per row based on grouping identity columns."""
    key_columns = ['REFERENCE', 'FILELOC', 'FILENAME', 'DATE', 'SAMPLE_NUMBER']
    raw_key = df[key_columns].fillna('').astype(str).agg('|'.join, axis=1)
    return raw_key.apply(lambda value: hashlib.sha1(value.encode('utf-8')).hexdigest())


def reassign_group_keys_to_default(df, *, selected_part_keys, default_group, group_color_column, default_group_color):
    """Assign selected non-default group rows back to the default group/color."""
    if not selected_part_keys:
        return False

    rows_to_reassign = (
        (df['GROUP'] != default_group)
        & (df['GROUP_KEY'].isin(selected_part_keys))
    )
    df.loc[rows_to_reassign, 'GROUP'] = default_group
    df.loc[rows_to_reassign, group_color_column] = default_group_color
    return bool(rows_to_reassign.any())

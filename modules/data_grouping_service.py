"""Database/query and dataframe mutation helpers for data-grouping UI."""

import hashlib
import json

import pandas as pd

from modules.report_query_service import build_grouping_query as _build_grouping_query


def _normalize_filter_query(filter_query):
    """Return a subquery-safe filter query string or an empty string."""
    if not isinstance(filter_query, str):
        return ""

    normalized = filter_query.strip()
    return normalized.rstrip(';').rstrip()


def build_grouping_query(filter_query):
    """Build the grouping dataset query, optionally wrapping a caller filter query."""
    return _build_grouping_query(_normalize_filter_query(filter_query))


def load_grouping_dataframe(read_sql_dataframe, db_file, filter_query):
    """Read grouping rows from SQLite using a normalized grouping query."""
    query = build_grouping_query(filter_query)
    return read_sql_dataframe(db_file, query)


def compute_group_key_for_df(df):
    """Return a stable SHA1 key per row based on the canonical report identity."""
    if 'REPORT_ID' not in df.columns and 'report_id' not in df.columns:
        raise ValueError("REPORT_ID is required to compute a grouping key.")

    report_id_column = 'REPORT_ID' if 'REPORT_ID' in df.columns else 'report_id'
    normalized_values = df[[report_id_column]].fillna('').astype(str)
    raw_key = normalized_values.apply(
        lambda row: json.dumps(list(row), ensure_ascii=False, separators=(',', ':')),
        axis=1,
    )
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

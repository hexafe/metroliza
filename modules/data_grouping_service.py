"""Database/query and dataframe mutation helpers for data-grouping UI."""

import hashlib
import json

import pandas as pd

try:
    from modules.report_query_service import (
        build_grouping_query as _shared_build_grouping_query,
        build_grouping_scope_query_from_filter_state,
    )
except Exception:  # pragma: no cover - compatibility for test stubs/forked workspaces
    _shared_build_grouping_query = None

    def build_grouping_scope_query_from_filter_state(_filter_state=None):
        return None

try:
    from modules.grouping_filter_core import DataFrameGroupingIndex as _SharedDataFrameGroupingIndex
except Exception:  # pragma: no cover - optional shared core may not exist in forked workspaces
    _SharedDataFrameGroupingIndex = None


_GROUPING_SCOPE_SELECT = (
    "DISTINCT report_id AS REPORT_ID, reference AS REFERENCE, report_date AS DATE, "
    "sample_number AS SAMPLE_NUMBER, part_name AS PART_NAME, revision AS REVISION, "
    "template_variant AS TEMPLATE_VARIANT, has_nok AS HAS_NOK, nok_count AS NOK_COUNT, "
    "file_name AS FILENAME"
)

_GROUPING_INDEX_DISPLAY_COLUMNS = (
    "REFERENCE",
    "DATE",
    "SAMPLE_NUMBER",
    "PART_NAME",
    "REVISION",
    "TEMPLATE_VARIANT",
    "HAS_NOK",
    "NOK_COUNT",
    "STATUS_CODE",
    "OPERATOR_NAME",
    "FILENAME",
    "GROUP",
    "GROUP_COLOR",
)


def _normalize_filter_query(filter_query):
    """Return a subquery-safe filter query string or an empty string."""
    if not isinstance(filter_query, str):
        return ""

    normalized = filter_query.strip()
    return normalized.rstrip(';').rstrip()


def build_grouping_query(filter_query):
    """Build the grouping dataset query, optionally wrapping a caller filter query."""
    normalized_filter_query = _normalize_filter_query(filter_query)
    if _shared_build_grouping_query is not None:
        return _shared_build_grouping_query(normalized_filter_query)

    if normalized_filter_query:
        return f"""
        SELECT DISTINCT
            "REPORT_ID" AS REPORT_ID,
            "REFERENCE" AS REFERENCE,
            "DATE" AS DATE,
            "SAMPLE_NUMBER" AS SAMPLE_NUMBER,
            "PART_NAME" AS PART_NAME,
            "REVISION" AS REVISION,
            "TEMPLATE_VARIANT" AS TEMPLATE_VARIANT,
            "HAS_NOK" AS HAS_NOK,
            "NOK_COUNT" AS NOK_COUNT,
            "FILENAME" AS FILENAME
        FROM (
            {normalized_filter_query}
        ) AS filtered_data
    """

    return f"SELECT {_GROUPING_SCOPE_SELECT} FROM vw_grouping_reports"


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
    return raw_key.apply(
        lambda value: hashlib.sha1(value.encode('utf-8'), usedforsecurity=False).hexdigest()
    )


def build_grouping_row_index(df, *, group_color_column="GROUP_COLOR"):
    """Return one display row per grouping key with a raw-row count.

    The returned frame is for list rendering only. Callers should keep the
    original grouping DataFrame as the export contract object.
    """
    if df is None or df.empty:
        return df.copy() if df is not None else df
    if "GROUP_KEY" not in df.columns:
        raise ValueError("GROUP_KEY is required to build a grouping row index.")

    def _first_display_value(series):
        for value in series:
            if value is None:
                continue
            try:
                if value != value:
                    continue
            except TypeError:
                pass
            text = str(value).strip()
            if text and text not in {"None", "<NA>"}:
                return value
        return series.iloc[0] if len(series.index) else None

    aggregations = {}
    for column in _GROUPING_INDEX_DISPLAY_COLUMNS:
        if column in df.columns:
            aggregations[column] = _first_display_value
    if group_color_column in df.columns and group_color_column not in aggregations:
        aggregations[group_color_column] = _first_display_value

    indexed = (
        df.groupby("GROUP_KEY", sort=False, dropna=False)
        .agg(**{column: (column, aggregator) for column, aggregator in aggregations.items()})
        .reset_index()
    )
    counts = _grouping_key_counts(df)
    return indexed.merge(counts, on="GROUP_KEY", how="left")


def _grouping_key_counts(df):
    if _SharedDataFrameGroupingIndex is not None:
        grouping_index = _SharedDataFrameGroupingIndex(df, ["GROUP_KEY"], blank_value="")
        rows, _total = grouping_index.preview_rows()
        if rows:
            return pd.DataFrame(
                {
                    "GROUP_KEY": [row["key"][0] for row in rows],
                    "ROW_COUNT": [int(row["row_count"]) for row in rows],
                }
            )
    return df.groupby("GROUP_KEY", sort=False, dropna=False).size().reset_index(name="ROW_COUNT")


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

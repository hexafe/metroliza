"""Database/query and dataframe mutation helpers for data-grouping UI."""

import hashlib
import json

from metroliza.shared.lazy_modules import LazyPandas as _LazyPandas
from metroliza.shared.lazy_modules import LazyNumpy as _LazyNumpy

try:
    from metroliza.reports.report_query_service import (
        build_grouping_query as _shared_build_grouping_query,
        build_grouping_scope_query_from_filter_state,
    )
except Exception:  # pragma: no cover - compatibility for test stubs/forked workspaces
    _shared_build_grouping_query = None

    def build_grouping_scope_query_from_filter_state(_filter_state=None):
        return None

try:
    from metroliza.shared.grouping_filter_core import (
        DataFrameGroupingIndex as _SharedDataFrameGroupingIndex,
        normalize_grouping_key as _shared_normalize_grouping_key,
    )
except Exception:  # pragma: no cover - optional shared core may not exist in forked workspaces
    _SharedDataFrameGroupingIndex = None
    _shared_normalize_grouping_key = None


_GROUPING_SCOPE_SELECT = (
    "DISTINCT report_id AS REPORT_ID, reference AS REFERENCE, report_date AS DATE, "
    "sample_number AS SAMPLE_NUMBER, part_name AS PART_NAME, revision AS REVISION, "
    "template_variant AS TEMPLATE_VARIANT, has_nok AS HAS_NOK, nok_count AS NOK_COUNT, "
    "file_name AS FILENAME"
)

_GROUPING_INDEX_DISPLAY_COLUMNS = (
    "REPORT_ID",
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


pd = _LazyPandas()
np = _LazyNumpy()


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


def _report_id_texts(values):
    """Return the string form of a ``REPORT_ID`` series (row-wise reference normalisation)."""
    return values.to_frame(name='REPORT_ID').fillna('').astype(str)['REPORT_ID']


def _group_keys_for_texts(texts):
    """Return the SHA1 key of each report-id string."""
    return [
        hashlib.sha1(
            json.dumps([text], ensure_ascii=False, separators=(',', ':')).encode('utf-8'),
            usedforsecurity=False,
        ).hexdigest()
        for text in texts
    ]


def _group_key_for_report_values(values):
    """Return the SHA1 key for each value of a ``REPORT_ID`` series (row-wise reference semantics)."""
    return _group_keys_for_texts(_report_id_texts(values).tolist())


def _is_numpy_object_dtype(dtype):
    return isinstance(dtype, np.dtype) and dtype.kind == "O"


def _distinct_value_codes(values):
    """Return ``(codes, representatives)`` where equal-looking values share a code.

    Values that compare equal but print differently (``1`` and ``1.0`` in an object column,
    ``0.0`` and ``-0.0``) keep separate codes, so the string form of every row is preserved.
    """
    dtype = values.dtype
    if _is_numpy_object_dtype(dtype):
        seen = {}
        representatives = []
        codes = np.empty(len(values), dtype=np.int64)
        for position, value in enumerate(values.tolist()):
            try:
                identity = (type(value), value)
                code = seen.get(identity)
            except TypeError:
                identity = None
                code = None
            if code is None:
                code = len(representatives)
                representatives.append(value)
                if identity is not None:
                    seen[identity] = code
            codes[position] = code
        return codes, pd.Series(representatives, dtype=object)
    if dtype.kind == 'f':
        bits = np.ascontiguousarray(values.to_numpy(dtype=np.float64)).view(np.int64)
        codes, _uniques = pd.factorize(bits)
    else:
        codes, _uniques = pd.factorize(values, use_na_sentinel=False)
    codes = np.asarray(codes, dtype=np.int64)
    first_positions = np.full(int(codes.max()) + 1 if len(codes) else 0, -1, dtype=np.int64)
    first_positions[codes[::-1]] = np.arange(len(codes) - 1, -1, -1)
    return codes, values.iloc[first_positions].reset_index(drop=True)


def compute_group_key_for_df(df):
    """Return a stable SHA1 key per row based on the canonical report identity."""
    if 'REPORT_ID' not in df.columns and 'report_id' not in df.columns:
        raise ValueError("REPORT_ID is required to compute a grouping key.")

    report_id_column = 'REPORT_ID' if 'REPORT_ID' in df.columns else 'report_id'
    report_ids = df[report_id_column]
    if len(df.index) == 0 or not isinstance(report_ids, pd.Series):
        return _compute_group_key_row_wise(df, report_id_column)
    # The key depends only on the report id: hash every distinct value once and map it to the rows.
    if _is_numpy_object_dtype(report_ids.dtype):
        # Object values that compare equal can print differently (``0.0``/``-0.0``, ``Decimal('1')``/
        # ``Decimal('1.0')``, one instant in two time zones): identify them by the string form the
        # row-wise reference keys on, never by value equality.
        codes, distinct_texts = pd.factorize(_report_id_texts(report_ids))
        distinct_keys = np.asarray(_group_keys_for_texts(list(distinct_texts)), dtype=object)
    else:
        codes, representatives = _distinct_value_codes(report_ids)
        distinct_keys = np.asarray(_group_key_for_report_values(representatives), dtype=object)
    return pd.Series(distinct_keys[codes], index=df.index)


def _compute_group_key_row_wise(df, report_id_column):
    normalized_values = df[[report_id_column]].fillna('').astype(str)
    raw_key = normalized_values.apply(
        lambda row: json.dumps(list(row), ensure_ascii=False, separators=(',', ':')),
        axis=1,
    )
    return raw_key.apply(
        lambda value: hashlib.sha1(value.encode('utf-8'), usedforsecurity=False).hexdigest()
    )


def _is_display_value(value):
    if value is None:
        return False
    try:
        if value != value:
            return False
    except TypeError:
        pass
    text = str(value).strip()
    return bool(text) and text not in {"None", "<NA>"}


def _display_value_mask(series):
    """Boolean array: which values ``_first_display_value`` may choose."""
    dtype = series.dtype
    if isinstance(dtype, np.dtype):
        if dtype.kind in "iub":
            return np.ones(len(series), dtype=bool)
        if dtype.kind in "fcM":
            return ~np.asarray(series.isna(), dtype=bool)
    return np.fromiter((_is_display_value(value) for value in series.tolist()), dtype=bool, count=len(series))


def _first_display_positions(series, codes, group_count, first_positions):
    """Row position per group of the first displayable value, else the group's first row."""
    valid_positions = np.flatnonzero(_display_value_mask(series))
    chosen = first_positions.copy()
    if len(valid_positions):
        valid_codes = codes[valid_positions]
        found = np.full(group_count, -1, dtype=np.int64)
        found[valid_codes[::-1]] = valid_positions[::-1]
        has_value = found >= 0
        chosen[has_value] = found[has_value]
    return chosen


def build_grouping_row_index(df, *, group_color_column="GROUP_COLOR"):
    """Return one display row per grouping key with a raw-row count.

    The returned frame is for list rendering only. Callers should keep the
    original grouping DataFrame as the export contract object.
    """
    if df is None or df.empty:
        return df.copy() if df is not None else df
    if "GROUP_KEY" not in df.columns:
        raise ValueError("GROUP_KEY is required to build a grouping row index.")

    columns = [column for column in _GROUPING_INDEX_DISPLAY_COLUMNS if column in df.columns]
    if group_color_column in df.columns and group_color_column not in columns:
        columns.append(group_color_column)

    grouped = df.groupby("GROUP_KEY", sort=False, dropna=False)
    codes = np.asarray(grouped.ngroup(), dtype=np.int64)
    group_count = int(codes.max()) + 1
    first_positions = np.full(group_count, -1, dtype=np.int64)
    first_positions[codes[::-1]] = np.arange(len(codes) - 1, -1, -1)

    indexed = pd.DataFrame({"GROUP_KEY": grouped.size().index})
    for column in columns:
        series = df[column]
        positions = _first_display_positions(series, codes, group_count, first_positions)
        chosen = series.iloc[positions].reset_index(drop=True)
        if _is_numpy_object_dtype(chosen.dtype):
            # The reference aggregation infers the dtype of an object result (all ints -> int64, text -> string).
            chosen = pd.Series(chosen.tolist(), dtype=None)
        indexed[column] = chosen
    counts = _grouping_key_counts(df)
    return indexed.merge(counts, on="GROUP_KEY", how="left")


def _grouping_key_counts(df):
    if _SharedDataFrameGroupingIndex is not None and _shared_normalize_grouping_key is not None:
        # Same rows as ``DataFrameGroupingIndex(df, ["GROUP_KEY"], blank_value="").preview_rows()``:
        # keys are normalized once per distinct value instead of once per row.
        codes, representatives = _distinct_value_codes(df["GROUP_KEY"])
        normalized_keys = [
            _shared_normalize_grouping_key(["GROUP_KEY"], [value], blank_value="")[0]
            for value in representatives.tolist()
        ]
        normalized_order = {}
        for key in normalized_keys:
            normalized_order.setdefault(key, len(normalized_order))
        key_codes = np.asarray([normalized_order[key] for key in normalized_keys], dtype=np.int64)
        row_counts = np.bincount(key_codes[codes], minlength=len(normalized_order))
        return pd.DataFrame(
            {
                "GROUP_KEY": list(normalized_order),
                "ROW_COUNT": [int(count) for count in row_counts],
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


def _plain_grouping_state(value, allowed):
    state = vars(value)
    if type(state) is not dict or any(type(key) is not str or key not in allowed for key in state):
        return None
    return state


def _native_grouping_text_array(value):
    if type(value) is np.ndarray:
        return value
    if type(value) is pd.arrays.StringArray and not vars(value):
        array = value._ndarray
        if type(array) is np.ndarray:
            return array
    return None


def _native_grouping_axis(axis):
    from pandas._libs.index import ObjectEngine, StringObjectEngine

    if type(axis) not in (pd.Index, pd.RangeIndex):
        return False
    state = _plain_grouping_state(axis, {'_data', '_range', '_name', '_cache', '_id', '_references'})
    if state is None:
        return False
    cache = state.get('_cache', {})
    if type(cache) is not dict or any(type(key) is not str for key in cache):
        return False
    if any(key not in {'_engine', 'is_unique', 'dtype', 'inferred_type', '_is_multi'} for key in cache):
        return False
    if '_engine' in cache and type(cache['_engine']) not in (ObjectEngine, StringObjectEngine):
        return False
    native_cache_types = (bool, str, pd.StringDtype, type(np.dtype(object)), type(np.dtype('int64')))
    if any(type(value) not in native_cache_types for key, value in cache.items() if key != '_engine'):
        return False
    if type(axis) is pd.RangeIndex:
        return type(state.get('_range')) is range
    return _native_grouping_text_array(state.get('_data')) is not None


def _native_grouping_cache(cache):
    if type(cache) is not dict or any(type(key) is not str for key in cache):
        return False
    scalar_types = (bool, int, str, pd.StringDtype) + tuple(
        type(np.dtype(dtype)) for dtype in ('object', 'int64', 'float64', 'bool')
    )
    for value in cache.values():
        if type(value) in scalar_types:
            continue
        if type(value) is tuple and all(type(part) is int for part in value):
            continue
        if _native_grouping_text_array(value) is None:
            return False
    return True


def _native_grouping_frame_metadata(state):
    from pandas.core.flags import Flags

    if state is None:
        return False
    if any(type(state.get(key, {})) is not dict or state.get(key, {}) for key in ('_attrs', '_item_cache')):
        return False
    flags = state.get('_flags')
    if type(flags) is not Flags:
        return False
    flag_state = _plain_grouping_state(flags, {'_allows_duplicate_labels', '_obj'})
    return flag_state is not None and type(flag_state.get('_allows_duplicate_labels')) is bool


def _native_grouping_color_blocks(blocks):
    from pandas.core.internals.blocks import ExtensionBlock, NumpyBlock

    if type(blocks) is not tuple:
        return False
    for block in blocks:
        if type(block) not in (NumpyBlock, ExtensionBlock):
            return False
        if _plain_grouping_state(block, {'_cache'}) is None or not _native_grouping_cache(vars(block).get('_cache', {})):
            return False
        if _native_grouping_text_array(block.values) is None:
            return False
    return True


def _native_grouping_color_frame(df):
    """Decline overridden storage before reading pandas metadata or values."""
    from pandas.core.internals.managers import BlockManager

    if type(df) is not pd.DataFrame:
        return False
    state = _plain_grouping_state(df, {'_mgr', '_attrs', '_flags', '_item_cache', '_is_copy'})
    if not _native_grouping_frame_metadata(state):
        return False
    manager = state.get('_mgr')
    if type(manager) is not BlockManager:
        return False
    if _plain_grouping_state(manager, {'_known_consolidated', '_is_consolidated'}) is None:
        return False
    if type(manager.axes) is not list or len(manager.axes) != 2:
        return False
    if not all(_native_grouping_axis(axis) for axis in manager.axes):
        return False
    if not _native_grouping_color_blocks(manager.blocks):
        return False
    columns = _native_grouping_text_array(vars(manager.axes[0]).get('_data'))
    return columns is not None and all(type(value) is str for value in columns) and len(set(columns)) == len(columns)


def native_group_color_assignment(df, *, default_group, default_color, color_column):
    """Resolve existing native text colours in one pass; retain dynamic palette fallback."""
    if any(type(value) is not str for value in (default_group, default_color, color_column)):
        return None
    if not _native_grouping_color_frame(df):
        return None
    groups, colors = df['GROUP'], df[color_column]
    group_values, color_values = groups.tolist(), colors.tolist()
    if not all(type(value) is str for value in group_values + color_values):
        return None
    assigned = {default_group: default_color}
    for group, color in zip(group_values, color_values, strict=True):
        if color and color != default_color:
            assigned.setdefault(group, color)
    if any(group not in assigned for group in group_values):
        # _next_group_color is an extension hook and observes each preceding mutation.
        return None
    return groups.map(assigned).astype(colors.dtype)

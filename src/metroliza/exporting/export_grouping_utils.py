import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from metroliza.analytics.grouping_labels import (
    DEFAULT_GROUP_LABEL,
    normalize_default_group_label,
    normalize_group_labels,
)
from metroliza.exporting.export_query_service import RowTable


_GROUP_KEY_COMPONENTS = ['REPORT_ID']
_GROUPING_OPTIONAL_COLUMNS = ['REPORT_ID', 'GROUP_COLOR']
DEFAULT_GROUP_LABEL_ATTR = 'default_group_label'


def get_default_group_label(df, *, fallback=DEFAULT_GROUP_LABEL):
    """Read the per-run default group label stored on a grouping DataFrame."""
    attrs = getattr(df, 'attrs', {}) if df is not None else {}
    return normalize_default_group_label(attrs.get(DEFAULT_GROUP_LABEL_ATTR), fallback=fallback)


def set_default_group_label(df, label):
    """Attach a per-run default group label to a DataFrame when possible."""
    if df is not None and hasattr(df, 'attrs'):
        df.attrs[DEFAULT_GROUP_LABEL_ATTR] = normalize_default_group_label(label)
    return df


def _resolve_column_name(df, column_name):
    if column_name in df.columns:
        return column_name

    lowered = {str(column).lower(): column for column in df.columns}
    return lowered.get(column_name.lower())


def _normalize_grouping_columns(df):
    rename_map = {}
    for canonical_name in ('REPORT_ID', 'GROUP', 'GROUP_COLOR'):
        resolved_name = _resolve_column_name(df, canonical_name)
        if resolved_name is not None and resolved_name != canonical_name:
            rename_map[resolved_name] = canonical_name
    if not rename_map:
        return df
    rename = getattr(df, "rename", None)
    if callable(rename):
        return rename(columns=rename_map)
    return RowTable(
        rows=tuple(tuple(row) for row in getattr(df, "rows", ())),
        columns=tuple(rename_map.get(column, column) for column in getattr(df, "columns", ())),
    )


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        missing = value != value
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool):
        return missing
    module_name = type(value).__module__
    type_name = type(value).__name__
    return module_name.startswith(("pandas", "numpy")) and type_name in {"NAType", "NaTType"}


def _column_values(table: Any, column_name: str) -> list[Any]:
    getter = getattr(table, "get", None)
    if callable(getter):
        values = getter(column_name)
    elif column_name in getattr(table, "columns", ()):
        values = table[column_name]
    else:
        values = None
    if values is None:
        return []
    tolist = getattr(values, "tolist", None)
    if callable(tolist):
        return list(tolist())
    return list(values)


def _table_empty(table: Any) -> bool:
    if table is None:
        return True
    empty = getattr(table, "empty", None)
    if empty is not None:
        return bool(empty)
    try:
        return len(table) == 0
    except TypeError:
        return True


def _copy_table(table: Any) -> Any:
    copy = getattr(table, "copy", None)
    if callable(copy):
        return copy()
    columns = tuple(str(column) for column in getattr(table, "columns", ()))
    rows = tuple(tuple(row) for row in getattr(table, "rows", ()))
    return RowTable(rows=rows, columns=columns)


def _select_columns(table: Any, columns: Iterable[str]) -> Any:
    selected_columns = [str(column) for column in columns]
    if isinstance(table, RowTable):
        return table[selected_columns].copy()
    return table[selected_columns].copy()


def _set_column(table: Any, column_name: str, values: Iterable[Any]) -> Any:
    table[column_name] = list(values)
    return table


def _iter_row_mappings(table: Any) -> Iterable[Mapping[str, Any]]:
    if table is None:
        return ()
    iter_rows = getattr(table, "iter_rows", None)
    if callable(iter_rows):
        return iter_rows(as_dict=True)
    to_dict = getattr(table, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict("records")
        except TypeError:
            pass
    if isinstance(table, Iterable) and not isinstance(table, (str, bytes)):
        records: list[Mapping[str, Any]] = []
        for row in table:
            if hasattr(row, "__dataclass_fields__"):
                records.append(
                    {
                        "GROUP": getattr(row, "group", None),
                        "REPORT_ID": getattr(row, "report_id", None),
                        "REFERENCE": getattr(row, "reference", None),
                        "DATE": getattr(row, "date", None),
                        "SAMPLE_NUMBER": getattr(row, "sample_number", None),
                        "GROUP_COLOR": getattr(row, "group_color", None),
                    }
                )
            elif isinstance(row, Mapping):
                records.append(row)
        if records:
            return records
    columns = tuple(str(column) for column in getattr(table, "columns", ()))
    rows = getattr(table, "rows", ())
    return (dict(zip(columns, row)) for row in rows)


def _records_to_row_table(records: list[Mapping[str, Any]]) -> RowTable:
    columns: list[str] = []
    for row in records:
        for column in row:
            column_name = str(column)
            if column_name not in columns:
                columns.append(column_name)
    return RowTable(
        rows=tuple(tuple(row.get(column) for column in columns) for row in records),
        columns=tuple(columns),
    )


def add_group_key(df):
    """Return a copy of ``df`` with a deterministic ``GROUP_KEY`` report identity."""
    normalized_df = _normalize_grouping_columns(df)
    report_id_column = _resolve_column_name(normalized_df, 'REPORT_ID')
    if report_id_column is None:
        return df

    keyed_df = normalized_df.copy()
    raw_key = [
        _normalize_grouping_identity_component(value)
        for value in _column_values(keyed_df, report_id_column)
    ]
    keyed_df['GROUP_KEY'] = [
        hashlib.sha1(value.encode('utf-8'), usedforsecurity=False).hexdigest()
        for value in raw_key
    ]
    return keyed_df


def _normalize_grouping_identity_component(value):
    """Normalize report identity values before hashing them into grouping keys."""
    if _is_missing_value(value):
        return ''
    text = str(value).strip()
    if not text:
        return ''
    try:
        decimal_value = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    if not decimal_value.is_finite():
        return text
    integral_value = decimal_value.to_integral_value()
    if decimal_value == integral_value:
        return str(int(integral_value))
    normalized = format(decimal_value.normalize(), 'f')
    if '.' in normalized:
        normalized = normalized.rstrip('0').rstrip('.')
    return '0' if normalized in {'', '-0'} else normalized


def prepare_grouping_dataframe(grouping_df):
    """Build the canonical grouping assignment dataframe used by export merge logic."""
    if _table_empty(grouping_df):
        return None

    if not hasattr(grouping_df, "columns"):
        records = list(_iter_row_mappings(grouping_df))
        if not records:
            return None
        grouping_df = _records_to_row_table(records)

    normalized_df = _normalize_grouping_columns(grouping_df)
    if 'GROUP' not in normalized_df.columns:
        return None

    available_cols = [column for column in _GROUPING_OPTIONAL_COLUMNS if column in normalized_df.columns]
    prepared = _select_columns(normalized_df, available_cols + ['GROUP'])
    if hasattr(prepared, 'attrs'):
        prepared.attrs.update(getattr(grouping_df, 'attrs', {}))
    return add_group_key(prepared)


def keys_have_usable_values(df, keys):
    """Return True when each requested key column exists and at least one row has non-empty values."""
    if _table_empty(df):
        return False

    required = []
    for key in keys:
        resolved = _resolve_column_name(df, key)
        if resolved is None:
            return False
        required.append(resolved)

    if len(required) != len(keys):
        return False

    row_count = len(_column_values(df, required[0])) if required else 0
    columns_by_key = {key: _column_values(df, key) for key in required}
    for row_index in range(row_count):
        usable = True
        for key in required:
            value = columns_by_key[key][row_index]
            if _is_missing_value(value) or not str(value).strip():
                usable = False
                break
        if usable:
            return True
    return False


def resolve_group_merge_keys(header_group, grouping_df):
    """Resolve the highest-fidelity merge key shared by measurement rows and grouping rows."""
    if keys_have_usable_values(header_group, ['GROUP_KEY']) and keys_have_usable_values(grouping_df, ['GROUP_KEY']):
        return ['GROUP_KEY']

    if keys_have_usable_values(header_group, ['REPORT_ID']) and keys_have_usable_values(grouping_df, ['REPORT_ID']):
        return ['REPORT_ID']

    return None


def apply_group_assignments(header_group, grouping_df, *, group_analysis_mode=False, fallback_group_label=None):
    """Merge grouping assignments into measurement rows.

    Fallback behavior is legacy-compatible by default:
    - ``group_analysis_mode=False`` falls back to ``"UNGROUPED"``.
    - ``group_analysis_mode=True`` falls back to ``"POPULATION"``.

    Pass ``fallback_group_label`` to override the fallback label explicitly,
    such as Group Analysis paths that always require ``"POPULATION"``.

    Returns tuple: ``(merged_frame, grouping_applied, merge_keys, duplicate_count)``.
    """
    if grouping_df is None:
        return header_group, False, None, 0

    keyed_header = add_group_key(header_group)
    merge_keys = resolve_group_merge_keys(keyed_header, grouping_df)
    if merge_keys is None:
        return keyed_header, False, None, 0

    grouping_rows = list(_iter_row_mappings(grouping_df))
    key_counts: dict[tuple[str, ...], int] = {}
    assignment_by_key: dict[tuple[str, ...], Mapping[str, Any]] = {}
    for row in grouping_rows:
        marker = _merge_marker(row, merge_keys)
        key_counts[marker] = key_counts.get(marker, 0) + 1
        assignment_by_key[marker] = row
    duplicate_count = sum(count for count in key_counts.values() if count > 1)

    group_values: list[Any] = []
    group_color_values: list[Any] = []
    grouping_applied = False
    has_group_color = 'GROUP_COLOR' in getattr(grouping_df, "columns", ())
    missing_group_label = fallback_group_label
    if missing_group_label is None:
        missing_group_label = get_default_group_label(grouping_df) if group_analysis_mode else 'UNGROUPED'

    for row in _iter_row_mappings(keyed_header):
        assignment = assignment_by_key.get(_merge_marker(row, merge_keys))
        if assignment is not None:
            grouping_applied = True
            group_values.append(assignment.get('GROUP'))
            if has_group_color:
                group_color_values.append(assignment.get('GROUP_COLOR'))
        else:
            group_values.append(None)
            if has_group_color:
                group_color_values.append(None)

    merged_group = _copy_table(keyed_header)
    _set_column(
        merged_group,
        'GROUP',
        normalize_group_labels(
            group_values,
            missing_label=missing_group_label,
            normalize_blank=group_analysis_mode,
        ),
    )
    if has_group_color:
        _set_column(merged_group, 'GROUP_COLOR', group_color_values)
    return merged_group, grouping_applied, merge_keys, duplicate_count


def _merge_marker(row: Mapping[str, Any], merge_keys: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        _normalize_grouping_identity_component(row.get(key))
        for key in merge_keys
    )

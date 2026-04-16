import hashlib

import pandas as pd


_GROUP_KEY_COMPONENTS = ['REPORT_ID']
_GROUPING_OPTIONAL_COLUMNS = ['REPORT_ID', 'GROUP_COLOR']


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
    return df.rename(columns=rename_map)


def normalize_group_labels(series, *, missing_label='UNGROUPED', normalize_blank=False):
    """Return normalized group labels for export workflows.

    Args:
        series: Input group label series.
        missing_label: Label used to fill missing/invalid entries.
        normalize_blank: When True, blank/whitespace labels are treated as
            missing and replaced with ``missing_label``.
    """
    normalized = series.fillna(missing_label).astype(str)
    if not normalize_blank:
        return normalized

    cleaned = normalized.str.strip()
    return cleaned.mask(cleaned == '', missing_label)


def add_group_key(df):
    """Return a copy of ``df`` with a deterministic ``GROUP_KEY`` report identity."""
    normalized_df = _normalize_grouping_columns(df)
    report_id_column = _resolve_column_name(normalized_df, 'REPORT_ID')
    if report_id_column is None:
        return df

    keyed_df = normalized_df.copy()
    raw_key = keyed_df[[report_id_column]].fillna('').astype(str).agg('|'.join, axis=1)
    keyed_df['GROUP_KEY'] = raw_key.apply(lambda value: hashlib.sha1(value.encode('utf-8')).hexdigest())
    return keyed_df


def prepare_grouping_dataframe(grouping_df):
    """Build the canonical grouping assignment dataframe used by export merge logic."""
    if not isinstance(grouping_df, pd.DataFrame) or grouping_df.empty:
        return None

    normalized_df = _normalize_grouping_columns(grouping_df)
    if 'GROUP' not in normalized_df.columns:
        return None

    available_cols = [column for column in _GROUPING_OPTIONAL_COLUMNS if column in normalized_df.columns]
    prepared = normalized_df[available_cols + ['GROUP']].copy()
    return add_group_key(prepared)


def keys_have_usable_values(df, keys):
    """Return True when each requested key column exists and at least one row has non-empty values."""
    if df.empty:
        return False

    required = []
    for key in keys:
        resolved = _resolve_column_name(df, key)
        if resolved is None:
            return False
        required.append(resolved)

    if len(required) != len(keys):
        return False

    normalized = df[required].copy()
    for key in required:
        normalized[key] = normalized[key].apply(lambda value: str(value).strip() if pd.notna(value) else '')

    return (normalized != '').all(axis=1).any()


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

    duplicated_mask = grouping_df.duplicated(subset=merge_keys, keep=False)
    duplicate_count = int(duplicated_mask.sum())
    deduped_grouping_df = grouping_df.drop_duplicates(subset=merge_keys, keep='last')
    projected_columns = merge_keys + ['GROUP']
    if 'GROUP_COLOR' in deduped_grouping_df.columns:
        projected_columns.append('GROUP_COLOR')
    merge_projection = deduped_grouping_df[projected_columns]
    merged_group = pd.merge(keyed_header, merge_projection, on=merge_keys, how='left')
    missing_group_label = fallback_group_label
    if missing_group_label is None:
        missing_group_label = 'POPULATION' if group_analysis_mode else 'UNGROUPED'
    merged_group['GROUP'] = normalize_group_labels(
        merged_group['GROUP'],
        missing_label=missing_group_label,
        normalize_blank=group_analysis_mode,
    )
    return merged_group, True, merge_keys, duplicate_count

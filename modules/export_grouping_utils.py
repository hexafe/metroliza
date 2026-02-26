import hashlib

import pandas as pd


_GROUP_KEY_COMPONENTS = ['REFERENCE', 'FILELOC', 'FILENAME', 'DATE', 'SAMPLE_NUMBER']
_GROUPING_OPTIONAL_COLUMNS = ['REPORT_ID', 'REFERENCE', 'FILELOC', 'FILENAME', 'DATE', 'SAMPLE_NUMBER']


def add_group_key(df):
    """Return a copy of ``df`` with a deterministic ``GROUP_KEY`` identity column when possible."""
    if not all(column in df.columns for column in _GROUP_KEY_COMPONENTS):
        return df

    keyed_df = df.copy()
    raw_key = keyed_df[_GROUP_KEY_COMPONENTS].fillna('').astype(str).agg('|'.join, axis=1)
    keyed_df['GROUP_KEY'] = raw_key.apply(lambda value: hashlib.sha1(value.encode('utf-8')).hexdigest())
    return keyed_df


def prepare_grouping_dataframe(grouping_df):
    """Build the canonical grouping assignment dataframe used by export merge logic."""
    if not isinstance(grouping_df, pd.DataFrame) or grouping_df.empty:
        return None

    if 'GROUP' not in grouping_df.columns:
        return None

    available_cols = [column for column in _GROUPING_OPTIONAL_COLUMNS if column in grouping_df.columns]
    prepared = grouping_df[available_cols + ['GROUP']].copy()
    return add_group_key(prepared)


def keys_have_usable_values(df, keys):
    """Return True when each requested key column exists and at least one row has non-empty values."""
    if df.empty:
        return False

    required = [key for key in keys if key in df.columns]
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

    if keys_have_usable_values(header_group, _GROUP_KEY_COMPONENTS) and keys_have_usable_values(grouping_df, _GROUP_KEY_COMPONENTS):
        return list(_GROUP_KEY_COMPONENTS)

    fallback_key = ['REFERENCE', 'SAMPLE_NUMBER']
    if keys_have_usable_values(header_group, fallback_key) and keys_have_usable_values(grouping_df, fallback_key):
        return fallback_key

    return None


def apply_group_assignments(header_group, grouping_df):
    """Merge grouping assignments into measurement rows.

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
    merge_projection = deduped_grouping_df[merge_keys + ['GROUP']]
    merged_group = pd.merge(keyed_header, merge_projection, on=merge_keys, how='left')
    merged_group['GROUP'] = merged_group['GROUP'].fillna('UNGROUPED')
    return merged_group, True, merge_keys, duplicate_count

"""Resolve which CSV Summary settings still describe a refreshed source."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import replace

from metroliza.analytics.row_table import RowTable
from metroliza.exporting.export_grouping_utils import get_default_group_label, set_default_group_label
from metroliza.reports.db import chunked_values, quote_identifier, sqlite_readonly_connection_scope
from metroliza.shared.grouping_filter_core import parse_filter_expression


def _source_files(loaded):
    return loaded.source_files or (loaded.source_file,)


def same_tabular_source(previous, loaded):
    return (_source_files(previous), previous.sheet_name) == (_source_files(loaded), loaded.sheet_name)


def _column_identities(loaded):
    return loaded.source_column_identities or {(label, 1): field for label, field in loaded.column_mapping.items()}


def _columns(loaded):
    store = loaded.sqlite_store
    return store.columns if store else loaded.dataframe.columns


def compatible_columns(previous, loaded):
    old = _column_identities(previous)
    new = _column_identities(loaded)
    mapping = {name: new[key] for key, name in old.items() if key in new}
    generated = set(_columns(previous)) - set(old.values())
    for name in generated.intersection(_columns(loaded)) - set(new.values()):
        mapping[name] = name
    for name, old_role, new_role in (
        ("process_datetime", previous.timestamp_column, loaded.timestamp_column),
        ("reference", previous.reference_column, loaded.reference_column),
    ):
        if mapping.get(old_role) != new_role or (old_role is not None and old_role not in mapping):
            mapping.pop(name, None)
    return mapping


def _retained_expression(text, previous, loaded, mapping):
    if not text:
        return ""
    try:
        old = parse_filter_expression(text, _columns(previous), aliases=previous.column_mapping)
        new = parse_filter_expression(text, _columns(loaded), aliases=loaded.column_mapping)
    except ValueError:
        return ""
    return text if tuple(mapping.get(spec.column) for spec in old.specs) == tuple(
        spec.column for spec in new.specs) else ""


def compatible_filters(state, previous, loaded, mapping):
    legacy, keys, rules, expression = state
    lost = []
    if any(column not in mapping for column in legacy):
        lost.extend(column for column in legacy if column not in mapping)
        legacy, keys = (), ()
    filters = []
    for rule in rules:
        new_column = mapping.get(rule.column)
        store = loaded.sqlite_store
        if (not new_column or (rule.has_date_filter and store and new_column not in store.date_filter_columns
                               and new_column != "process_datetime") or
                (rule.has_numeric_filter and store and new_column not in store.numeric_filter_columns)):
            lost.append(rule.column)
        else:
            filters.append(replace(rule, column=new_column))
    retained = _retained_expression(expression, previous, loaded, mapping)
    if expression and not retained:
        lost.append("wyrażenie filtra")
    return (tuple(mapping[column] for column in legacy), keys, tuple(filters), retained), lost


def _row_query(store, columns):
    projection = ", ".join(quote_identifier(column) for column in ("source_row_number", *columns))
    return f"SELECT {projection} FROM {quote_identifier(store.table_name)} WHERE source_row_number"


def _unique_rows(rows, tokens, cancel_check):
    matches = {}
    for index, row in enumerate(rows):
        if index % 512 == 0 and cancel_check():
            raise InterruptedError("Porównywanie przypisań zostało anulowane.")
        token = tuple(row[1:])
        if token in tokens:
            matches[token] = None if token in matches else row[0]
    return matches


def _match_source_rows(old_store, new_store, columns, ids, old_range, new_range, cancel_check):
    old_columns, new_columns = zip(*columns)
    old_query = _row_query(old_store, old_columns)
    new_query = _row_query(new_store, new_columns)
    with sqlite_readonly_connection_scope(old_store.path) as old, sqlite_readonly_connection_scope(new_store.path) as new:
        tokens = set()
        for chunk in chunked_values(ids):
            if cancel_check():
                raise InterruptedError("Porównywanie przypisań zostało anulowane.")
            placeholders = ", ".join("?" for _ in chunk)
            tokens.update(tuple(row[1:]) for row in old.execute(f"{old_query} IN ({placeholders})", chunk))
        old_matches = _unique_rows(old.execute(f"{old_query} BETWEEN ? AND ?", old_range), tokens, cancel_check)
        new_matches = _unique_rows(new.execute(f"{new_query} BETWEEN ? AND ?", new_range), tokens, cancel_check)
    return {old_id: new_matches[token] for token, old_id in old_matches.items()
            if old_id is not None and new_matches.get(token) is not None}


def _retained_row_ids(previous, loaded, row_ids, cancel_check):
    old_snapshots, new_snapshots = previous.source_snapshots, loaded.source_snapshots
    if not old_snapshots or len(old_snapshots) != len(new_snapshots):
        return {}
    old_columns, new_columns = _column_identities(previous), _column_identities(loaded)
    common = tuple((name, new_columns[key]) for key, name in old_columns.items() if key in new_columns)
    # When columns went away, require the surviving row identity field. A
    # unique measurement alone cannot identify an old row after schema drift.
    if len(common) < len(old_columns) and previous.reference_column not in dict(common):
        common = ()
    retained = {}
    old_start = new_start = 1
    ids = sorted(set(row_ids))
    for old, new in zip(old_snapshots, new_snapshots):
        old_end, new_end = old_start + old.row_count - 1, new_start + new.row_count - 1
        selected = ids[bisect_left(ids, old_start):bisect_right(ids, old_end)]
        if selected and old == new:
            retained.update((row_id, row_id - old_start + new_start) for row_id in selected)
        elif selected and common and previous.sqlite_store and loaded.sqlite_store:
            retained.update(_match_source_rows(previous.sqlite_store, loaded.sqlite_store, common,
                                               selected, (old_start, old_end), (new_start, new_end), cancel_check))
        old_start, new_start = old_end + 1, new_end + 1
    return retained


def reconcile_reload_grouping(previous, loaded, grouping, *, cancel_check=lambda: False):
    """Match changed rows only when their shared raw values identify one row in each snapshot."""
    if grouping is None or grouping.empty or (
            previous.source_snapshots and previous.source_snapshots == loaded.source_snapshots):
        return grouping, ()
    row_ids = tuple(int(value) for value in grouping["REPORT_ID"])
    mapped = _retained_row_ids(previous, loaded, row_ids, cancel_check)
    positions = [index for index, old_id in enumerate(row_ids) if old_id in mapped]
    result = grouping.take_rows(positions) if isinstance(grouping, RowTable) else grouping.iloc[positions].copy()
    result["REPORT_ID"] = [mapped[row_ids[index]] for index in positions]
    if "SAMPLE_NUMBER" in result.columns:
        result["SAMPLE_NUMBER"] = [str(value) for value in result["REPORT_ID"]]
    set_default_group_label(result, get_default_group_label(grouping))
    lost_groups = tuple(dict.fromkeys(group for row_id, group in zip(row_ids, grouping["GROUP"]) if row_id not in mapped))
    return result, lost_groups

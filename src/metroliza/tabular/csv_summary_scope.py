"""Canonical filter comparisons and ID-only grouping reconciliation for CSV Summary."""

from __future__ import annotations

from contextlib import closing
from dataclasses import fields
import sqlite3

from metroliza.analytics.row_table import RowTable
from metroliza.exporting.export_grouping_utils import get_default_group_label, set_default_group_label
from metroliza.reports.db import sqlite_connection_scope
from metroliza.shared.grouping_filter_core import parse_filter_expression
from metroliza.tabular.tabular_analytics_service import (
    _normalized_tabular_column_filters_for_columns,
    TabularColumnFilter,
    TabularSqliteFilterExpression,
    apply_tabular_row_filter,
    count_tabular_materialized_rows,
)


def _expression_key(spec):
    children = getattr(spec, "children", None)
    if children is not None:
        return (spec.operator, tuple(sorted((_expression_key(child) for child in children), key=repr)))
    return (type(spec).__name__, tuple((field.name, getattr(spec, field.name)) for field in fields(spec)))


def canonical_filter_state(loaded, column_filters=(), expression="", legacy_columns=(), legacy_keys=()):
    columns = loaded.sqlite_store.columns if loaded.sqlite_store is not None else loaded.dataframe.columns
    normalized = _normalized_tabular_column_filters_for_columns(columns, column_filters)
    legacy = (tuple(legacy_columns), tuple(sorted(set(map(tuple, legacy_keys))))) if legacy_columns and legacy_keys else ()
    if not normalized and not expression.strip() and len(legacy_columns) == 1 and legacy_keys:
        normalized = _normalized_tabular_column_filters_for_columns(columns, (
            TabularColumnFilter(legacy_columns[0], selected_values=tuple(key[0] for key in legacy_keys)),
        ))
        legacy = ()
    # Legacy keys are ANDed with column rules and expressions by the query path.
    rules = tuple(sorted((
        item.column, tuple(sorted(set(item.selected_values))),
        (item.date_mode, item.date_from, item.date_to, item.date_operator, item.date_value) if item.has_date_filter else (),
        (item.numeric_operator, item.numeric_value) if item.has_numeric_filter else (),
    ) for item in normalized))
    parsed = parse_filter_expression(expression, columns, aliases=loaded.column_mapping)
    expression_key = _expression_key(parsed.expression) if parsed.expression is not None else ()
    return rules, expression_key, legacy


def _expression_columns(spec):
    if spec is None:
        return set()
    children = getattr(spec, "children", None)
    if children is None:
        return {spec.column}
    return set().union(*(_expression_columns(child) for child in children))


def _check_scope_interruption(cancel_check):
    if cancel_check is not None and cancel_check():
        raise InterruptedError("Scope query canceled")


def _read_matching_ids(connection, query, params, cancel_check):
    allowed = set()
    with closing(connection.execute(query, params)) as cursor:
        while True:
            _check_scope_interruption(cancel_check)
            rows = cursor.fetchmany(900)
            if not rows:
                return allowed
            allowed.update(int(row[0]) for row in rows)


def _matching_sqlite_assignment_ids(loaded, candidate_ids, column_filters, expression, cancel_check):
    store = loaded.sqlite_store
    # This relation belongs to a fresh private connection, so its name is fixed.
    # All source/filter SQL still uses the store's validated parameterized builder.
    predicate = TabularSqliteFilterExpression(
        clause='"source_row_number" IN (SELECT +row_id FROM temp.csv_summary_assignment_rows)',
        columns=("source_row_number",),
    )
    _check_scope_interruption(cancel_check)
    query, params = store.source_row_number_query(
        column_filters=column_filters, grouping_filter=predicate,
        grouping_filter_expression=expression, grouping_filter_aliases=loaded.column_mapping,
    )
    _check_scope_interruption(cancel_check)
    ids = sorted(candidate_ids)
    with sqlite_connection_scope(store.path) as connection:
        try:
            if cancel_check is not None:
                connection.set_progress_handler(lambda: int(cancel_check()), 1000)
            with connection:
                connection.execute("CREATE TEMP TABLE csv_summary_assignment_rows (row_id INTEGER PRIMARY KEY)")
                for start in range(0, len(ids), 900):
                    _check_scope_interruption(cancel_check)
                    connection.executemany("INSERT INTO temp.csv_summary_assignment_rows (row_id) VALUES (?)",
                                           ((row_id,) for row_id in ids[start:start + 900]))
                _check_scope_interruption(cancel_check)
                return _read_matching_ids(connection, query, params, cancel_check)
        except sqlite3.OperationalError:
            _check_scope_interruption(cancel_check)
            raise
        finally:
            # Cancellation must never interrupt transaction/temp-table cleanup.
            connection.set_progress_handler(None, 0)
            connection.execute("DROP TABLE IF EXISTS temp.csv_summary_assignment_rows")


def _matching_assignment_ids(loaded, candidate_ids, column_filters, expression, *, cancel_check=None):
    _check_scope_interruption(cancel_check)
    store = loaded.sqlite_store
    columns = store.columns if store is not None else loaded.dataframe.columns
    if not candidate_ids or "source_row_number" not in columns:
        return set()
    if store is not None:
        return _matching_sqlite_assignment_ids(loaded, candidate_ids, column_filters, expression, cancel_check)
    frame = loaded.dataframe
    parsed = parse_filter_expression(expression, frame.columns, aliases=loaded.column_mapping)
    needed = {"source_row_number", *(item.column for item in column_filters)} | _expression_columns(parsed.expression)
    narrow = frame.loc[:, [column for column in frame.columns if column in needed]]
    filtered = apply_tabular_row_filter(narrow, column_filters=column_filters, row_filter_expression=expression,
                                       row_filter_aliases=loaded.column_mapping, required_columns=("source_row_number",))
    return set(filtered.dataframe["source_row_number"]) & candidate_ids


def _assignment_id(value):
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return None


def reconcile_filter_grouping(loaded, grouping, column_filters, expression, *, cancel_check=None):
    """Retain custom memberships by source ID; never infer assignments for new rows."""
    if grouping is None or grouping.empty:
        return grouping, 0, 0
    default = get_default_group_label(grouping)
    rows = grouping.iter_rows(as_dict=True) if isinstance(grouping, RowTable) else grouping.to_dict("records")
    members = [(index, _assignment_id(row.get("REPORT_ID")), str(row["GROUP"])) for index, row in enumerate(rows)
               if str(row["GROUP"]) != default]
    allowed = _matching_assignment_ids(loaded, {row_id for _, row_id, _ in members if row_id is not None},
                                       column_filters, expression, cancel_check=cancel_check)
    retained = [index for index, row_id, _ in members if row_id in allowed]
    dropped = [(row_id, group) for _, row_id, group in members if row_id not in allowed]
    if isinstance(grouping, RowTable):
        result = grouping.take_rows(retained)
    else:
        result = grouping.iloc[retained].copy()
    set_default_group_label(result, default)
    return result, len(dropped), len({group for _, group in dropped})


def preview_filter_change(loaded, grouping, column_filters, expression, *, cancel_check=None):
    reconciled, rows, groups = reconcile_filter_grouping(loaded, grouping, column_filters, expression, cancel_check=cancel_check)
    _check_scope_interruption(cancel_check)
    total = count_tabular_materialized_rows(loaded, column_filters=column_filters, row_filter_expression=expression)
    _check_scope_interruption(cancel_check)
    assigned = set() if reconciled is None else set(reconciled["REPORT_ID"])
    return reconciled, rows, groups, total, len(assigned) < total

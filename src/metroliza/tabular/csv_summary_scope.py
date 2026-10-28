"""Canonical filter comparisons and ID-only grouping reconciliation for CSV Summary."""

from __future__ import annotations

from dataclasses import fields

from metroliza.analytics.row_table import RowTable
from metroliza.exporting.export_grouping_utils import get_default_group_label, set_default_group_label
from metroliza.shared.grouping_filter_core import parse_filter_expression
from metroliza.tabular.tabular_analytics_service import (
    _normalized_tabular_column_filters_for_columns,
    _SQLITE_DATE_OPERATOR_SQL,
    _SQLITE_NUMBER_OPERATOR_SQL,
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
    elif normalized or expression.strip():
        legacy = ()  # The query path prioritizes column rules/expressions over legacy keys.
    rules = tuple(sorted((
        item.column, tuple(sorted(set(item.selected_values))),
        (item.date_mode, item.date_from, item.date_to, _SQLITE_DATE_OPERATOR_SQL.get(item.date_operator), item.date_value) if item.has_date_filter else (),
        (_SQLITE_NUMBER_OPERATOR_SQL[item.numeric_operator], item.numeric_value) if item.has_numeric_filter else (),
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


def _matching_assignment_ids(loaded, candidate_ids, column_filters, expression):
    store = loaded.sqlite_store
    if store is not None:
        # Reuse the store's parameterized, owner-thread query path. Each read
        # returns at most 900 existing assignment IDs, never a wide source frame.
        ids = sorted(candidate_ids)
        allowed = set()
        for start in range(0, len(ids), 900):
            chunk = tuple(ids[start:start + 900])
            predicate = TabularSqliteFilterExpression(
                clause='"source_row_number" IN (' + ", ".join("?" for _ in chunk) + ")",
                params=chunk, columns=("source_row_number",),
            )
            allowed.update(store.row_ids(
                column_filters=column_filters, grouping_filter=predicate,
                grouping_filter_expression=expression, grouping_filter_aliases=loaded.column_mapping,
            ))
        return allowed
    frame = loaded.dataframe
    parsed = parse_filter_expression(expression, frame.columns, aliases=loaded.column_mapping)
    needed = {"source_row_number", *(item.column for item in column_filters)} | _expression_columns(parsed.expression)
    narrow = frame.loc[:, [column for column in frame.columns if column in needed]]
    filtered = apply_tabular_row_filter(narrow, column_filters=column_filters, row_filter_expression=expression,
                                       row_filter_aliases=loaded.column_mapping, required_columns=("source_row_number",))
    return set(filtered.dataframe["source_row_number"]) & candidate_ids


def reconcile_filter_grouping(loaded, grouping, column_filters, expression):
    """Retain custom memberships by source ID; never infer assignments for new rows."""
    if grouping is None or grouping.empty:
        return grouping, 0, 0
    default = get_default_group_label(grouping)
    rows = grouping.iter_rows(as_dict=True) if isinstance(grouping, RowTable) else grouping.to_dict("records")
    members = [(index, int(row["REPORT_ID"]), str(row["GROUP"])) for index, row in enumerate(rows)
               if str(row["GROUP"]) != default]
    allowed = _matching_assignment_ids(loaded, {row_id for _, row_id, _ in members}, column_filters, expression)
    retained = [index for index, row_id, _ in members if row_id in allowed]
    dropped = [(row_id, group) for _, row_id, group in members if row_id not in allowed]
    if isinstance(grouping, RowTable):
        result = grouping.take_rows(retained)
    else:
        result = grouping.iloc[retained].copy()
    set_default_group_label(result, default)
    return result, len(dropped), len({group for _, group in dropped})


def preview_filter_change(loaded, grouping, column_filters, expression):
    reconciled, rows, groups = reconcile_filter_grouping(loaded, grouping, column_filters, expression)
    total = count_tabular_materialized_rows(loaded, column_filters=column_filters, row_filter_expression=expression)
    assigned = set() if reconciled is None else set(reconciled["REPORT_ID"])
    return reconciled, rows, groups, total, len(assigned) < total

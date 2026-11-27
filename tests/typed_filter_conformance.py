"""Reusable source rows, independent expectations and assertions for filter adapters."""

from collections.abc import Sequence

from metroliza.shared.grouping_filter_core import DataFrameFilterSpec
from metroliza.shared.typed_filter import FilterAdapter, FilterField, FilterPreview, FilterRowId


FIELDS = (
    FilterField("n", "number", "Measurement", "reference"),
    FilterField("d", "date", "Recorded day", "reference"),
    FilterField("label", "text", "Label", "reference"),
)
ROWS = [
    (1, None, None, None),
    (2, "1x", "2026-02-30", "\t "),
    (3, "Inf", "bad", ""),
    (4, ".5", "2026-02-15", "Straße"),
    (5, "+1e2", "2026-02-16T23:55:00-08:00", "STRASSE"),
    (6, "0", "15.02.2026", "001"),
    (7, "18446744073709551615", "17/02/2026", "1"),
    (8, "18446744073709551614", "2026-02-17", "x?[]\nend"),
    (9, " \t", "\t", " 001 "),
    (10, "-4", "02/03/2026", "xZ[]end"),
    (11, "1e309", 20260215, "a%_b"),
]


def condition(field, kind, operator, *values, **options):
    return {
        "field": field, "kind": kind, "operator": operator, "values": list(values),
        "case_sensitive": False, "wildcards": False, "dayfirst": False, **options,
    }


def document(node):
    return {"version": 1, "expression": node}


OPERATOR_CASES = (
    ("n", "number", "equals", (0,), [6]),
    ("n", "number", "not_equals", (0,), [1, 2, 3, 4, 5, 7, 8, 9, 10, 11]),
    ("n", "number", "less_than", (0,), [10]),
    ("n", "number", "less_or_equal", (0,), [6, 10]),
    ("n", "number", "greater_than", (0,), [4, 5, 7, 8]),
    ("n", "number", "greater_or_equal", (0,), [4, 5, 6, 7, 8]),
    ("n", "number", "between", (".5", "-4"), [4, 6, 10]),
    ("n", "number", "in", (".5", "18446744073709551615"), [4, 7]),
    ("n", "number", "not_in", (".5", "18446744073709551615"), [1, 2, 3, 5, 6, 8, 9, 10, 11]),
    ("n", "number", "is_blank", (), [1, 2, 3, 9, 11]),
    ("n", "number", "is_not_blank", (), [4, 5, 6, 7, 8, 10]),
    ("d", "date", "equals", ("2026-02-15",), [4, 6]),
    ("d", "date", "not_equals", ("2026-02-15",), [1, 2, 3, 5, 7, 8, 9, 10, 11]),
    ("d", "date", "less_than", ("2026-02-16",), [4, 6, 10]),
    ("d", "date", "less_or_equal", ("2026-02-16",), [4, 5, 6, 10]),
    ("d", "date", "greater_than", ("2026-02-16",), [7, 8]),
    ("d", "date", "greater_or_equal", ("2026-02-16",), [5, 7, 8]),
    ("d", "date", "between", ("2026-02-16", "2026-02-15"), [4, 5, 6]),
    ("d", "date", "in", ("2026-02-15", "2026-02-17"), [4, 6, 7, 8]),
    ("d", "date", "not_in", ("2026-02-15", "2026-02-17"), [1, 2, 3, 5, 9, 10, 11]),
    ("d", "date", "is_blank", (), [1, 2, 3, 9, 11]),
    ("d", "date", "is_not_blank", (), [4, 5, 6, 7, 8, 10]),
    ("label", "text", "equals", ("strasse",), [4, 5]),
    ("label", "text", "not_equals", ("strasse",), [1, 2, 3, 6, 7, 8, 9, 10, 11]),
    ("label", "text", "contains", ("%_",), [11]),
    ("label", "text", "not_contains", ("ss",), [1, 2, 3, 6, 7, 8, 9, 10, 11]),
    ("label", "text", "starts_with", ("x?",), [8]),
    ("label", "text", "ends_with", ("end",), [8, 10]),
    ("label", "text", "in", ("001", ""), [3, 6]),
    ("label", "text", "not_in", ("001", ""), [1, 2, 4, 5, 7, 8, 9, 10, 11]),
    ("label", "text", "is_blank", (), [1, 2, 3]),
    ("label", "text", "is_not_blank", (), [4, 5, 6, 7, 8, 9, 10, 11]),
)


GROUPED_CASE = document({"operator": "and", "children": [
    {"operator": "or", "children": [
        {"operator": "and", "children": [
            condition("n", "number", "less_than", 1),
            condition("d", "date", "equals", "2026-02-15"),
        ]},
        condition("label", "text", "equals", "x?[]*", wildcards=True),
    ]},
    condition("n", "number", "is_not_blank"),
]}), (4, 6, 8)


def assert_selected_rows(
    adapter: FilterAdapter,
    expression: DataFrameFilterSpec | None,
    expected: Sequence[FilterRowId],
    *,
    sample_limit: int = 2,
) -> None:
    """Exercise preview and final execution against independent expected IDs."""
    prepared = adapter.prepare(expression)
    assert prepared.preview(sample_limit) == FilterPreview(len(expected), tuple(expected[:sample_limit]))
    assert tuple(prepared.iter_row_ids()) == tuple(expected)

from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3

import pandas as pd
import pytest

from metroliza.shared.grouping_filter_core import (
    FilterExpressionGroup,
    build_filter_mask,
    parse_filter_expression,
)
from metroliza.shared.typed_filter import (
    FilterField,
    FilterValidationError,
    compile_typed_filter_sqlite,
    dump_typed_filter,
    install_typed_filter_sqlite,
    load_typed_filter,
    parse_typed_filter,
)


FIELDS = (
    FilterField("n", "number", "Measurement", "reference"),
    FilterField("d", "date", "Recorded day", "reference"),
    FilterField("label", "text", "Label", "reference"),
)
COLUMNS = {"n": "number source", "d": "date source", "label": 'label "source"'}
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


@pytest.fixture
def selected_rows():
    data = pd.DataFrame(ROWS, columns=("id", "n", "d", "label"), dtype=object)
    # Equivalent wall-calendar datetime in a different backend representation.
    data.loc[data.id == 5, "d"] = datetime(2026, 2, 16, 23, 55, tzinfo=timezone.utc)
    data.loc[data.id == 1, "label"] = pd.NA
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute('CREATE TABLE sample(id, "number source", "date source", "label ""source""")')
        connection.executemany("INSERT INTO sample VALUES (?, ?, ?, ?)", ROWS)
        install_typed_filter_sqlite(connection)

        def select(expression, expected):
            mask = build_filter_mask(data, (expression,) if expression is not None else ())
            assert data.loc[mask, "id"].tolist() == expected
            compiled = compile_typed_filter_sqlite(expression, COLUMNS, table_alias="s")
            sql = f"SELECT id FROM sample AS s WHERE {compiled.sql} ORDER BY id"
            assert [row[0] for row in connection.execute(sql, compiled.parameters)] == expected
            assert connection.execute(
                f"SELECT count(*) FROM sample AS s WHERE {compiled.sql}", compiled.parameters,
            ).fetchone() == (len(expected),)

        yield select


@pytest.mark.parametrize(("field", "kind", "operator", "values", "expected"), [
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
])
def test_reference_operator_rows(selected_rows, field, kind, operator, values, expected):
    selected_rows(load_typed_filter(document(condition(field, kind, operator, *values)), FIELDS), expected)


def test_nested_magic_and_json_round_trip(selected_rows):
    expression = parse_typed_filter(
        '(Label IN ("001", " 001 ", "") OR Label = "x?[]*") AND Measurement < .6 AND >= 0',
        FIELDS,
    )
    encoded = dump_typed_filter(expression)
    restored = load_typed_filter(json.loads(json.dumps(encoded)), FIELDS)
    assert dump_typed_filter(restored) == encoded
    selected_rows(restored, [6])

    selected_rows(parse_typed_filter('Label IN ("001", " 001 ", "") OR Label = "x?[]*"', FIELDS),
                  [3, 6, 8, 9])
    selected_rows(parse_typed_filter('[Recorded day] >= "15.02.2026" AND < "17.02.2026"', FIELDS),
                  [4, 5, 6])
    selected_rows(parse_typed_filter('[Recorded day] = "02/03/2026"', FIELDS, dayfirst=True), [10])
    selected_rows(load_typed_filter(document(condition("label", "text", "equals", "STRASSE",
                                                       case_sensitive=True)), FIELDS), [5])
    selected_rows(load_typed_filter(document(None), FIELDS), list(range(1, 12)))


def test_legacy_magic_keeps_value_based_inference():
    data = pd.DataFrame({"Label": ["001", "1", " 001 "]})
    legacy = parse_filter_expression('Label = "001"', ["Label"])
    assert legacy.mask(data).tolist() == [True, True, True]
    typed = parse_typed_filter('Label = "001"', FIELDS)
    assert typed.mask(data.rename(columns={"Label": "label"})).tolist() == [True, False, False]


def test_numeric_document_retains_unsigned_integer_and_binary64(selected_rows):
    expression = parse_typed_filter("Measurement IN (18446744073709551615, .5)", FIELDS)
    encoded = dump_typed_filter(expression)
    assert encoded["expression"]["values"] == ["18446744073709551615", "0.5"]
    selected_rows(load_typed_filter(json.loads(json.dumps(encoded)), FIELDS), [4, 7])


@pytest.mark.parametrize(("text", "code", "field"), [
    ("Unknown = 1", "missing_field", "Unknown"),
    ("Label > 1", "unsupported_operator", "label"),
    ("Measurement IN (1, 2oops)", "invalid_value", "n"),
    ("Measurement = Inf", "invalid_value", "n"),
    ("[Recorded day] = 2026-02-30", "invalid_value", "d"),
])
def test_catalog_diagnostics(text, code, field):
    with pytest.raises(FilterValidationError) as failure:
        parse_typed_filter(text, FIELDS)
    assert (failure.value.code, failure.value.field) == (code, field)


def test_saved_filter_remap_checks_exact_id_type_and_operators():
    encoded = dump_typed_filter(parse_typed_filter("Measurement > 0", FIELDS))
    renamed = FilterField("width", "number", "Measurement", "new source")
    with pytest.raises(FilterValidationError, match="explicit remap"):
        load_typed_filter(encoded, [renamed])
    restored = load_typed_filter(encoded, [renamed], remap={"n": "width"})
    assert dump_typed_filter(restored)["expression"]["field"] == "width"

    wrong_type = FilterField("width", "text", "Measurement", "new source")
    limited_ops = FilterField("width", "number", "Measurement", "new source", {"equals"})
    for field, code in [(wrong_type, "incompatible_type"), (limited_ops, "unsupported_operator")]:
        with pytest.raises(FilterValidationError) as failure:
            load_typed_filter(encoded, [field], remap={"n": "width"})
        assert failure.value.code == code

    two_fields = document({"operator": "and", "children": [
        condition("n", "number", "equals", 0), condition("width", "number", "equals", 0),
    ]})
    with pytest.raises(FilterValidationError, match="already maps"):
        load_typed_filter(two_fields, [renamed], remap={"n": "width"})


def test_document_validation_rejects_wrong_version_shape_and_options():
    for raw in (
        {"version": True, "expression": None},
        {"version": 2, "expression": None},
        document({"operator": "and", "children": []}),
        document(condition("n", "number", "equals", 1, wildcards=True)),
        document(condition("n", "number", "equals", True)),
        document(condition("n", "number", "between", 1)),
    ):
        with pytest.raises(FilterValidationError):
            load_typed_filter(raw, FIELDS)


def _nested_condition(group_count):
    node = condition("n", "number", "equals", 0)
    for _ in range(group_count):
        node = {"operator": "and", "children": [node]}
    return node


def test_typed_depth_is_bounded_before_mask_and_compile(selected_rows):
    selected_rows(load_typed_filter(document(_nested_condition(31)), FIELDS), [6])
    selected_rows(parse_typed_filter("(" * 32 + "Measurement = 0" + ")" * 32, FIELDS), [6])
    quoted_parentheses = "(" * 33
    selected_rows(parse_typed_filter(f'Label = "{quoted_parentheses}"', FIELDS), [])
    for depth in (32, 400):
        with pytest.raises(FilterValidationError, match="32") as failure:
            load_typed_filter(document(_nested_condition(depth)), FIELDS)
        assert failure.value.code == "nested_expression"
    too_deep = "(" * 33 + "Measurement = 0" + ")" * 33
    with pytest.raises(FilterValidationError, match="32") as failure:
        parse_typed_filter(too_deep, FIELDS)
    assert failure.value.code == "nested_expression"
    assert parse_filter_expression(too_deep, ["Measurement"]).expression is not None


@pytest.mark.parametrize("operator", ["and", "or"])
def test_typed_node_count_includes_group_and_leaves(selected_rows, operator):
    def expression(count):
        return f" {operator} ".join(["Measurement = 0"] * count)

    leaf = condition("n", "number", "equals", 0)
    selected_rows(parse_typed_filter(expression(127), FIELDS), [6])
    selected_rows(load_typed_filter(document({"operator": operator, "children": [leaf] * 127}), FIELDS), [6])
    with pytest.raises(FilterValidationError, match="128") as parsed:
        parse_typed_filter(expression(128), FIELDS)
    with pytest.raises(FilterValidationError, match="128") as loaded:
        load_typed_filter(document({"operator": operator, "children": [leaf] * 128}), FIELDS)
    assert parsed.value.code == loaded.value.code == "too_many_nodes"


def test_typed_operand_count_is_aggregate(selected_rows):
    def expression(count):
        return "Measurement IN (" + ",".join(["0"] * count) + ")"

    selected_rows(parse_typed_filter(expression(1024), FIELDS), [6])
    selected_rows(load_typed_filter(document(condition("n", "number", "in", *([0] * 1024))), FIELDS), [6])
    with pytest.raises(FilterValidationError, match="1024") as parsed:
        parse_typed_filter(f"{expression(512)} OR {expression(513)}", FIELDS)
    node = {"operator": "or", "children": [
        condition("n", "number", "in", *([0] * count)) for count in (512, 513)
    ]}
    with pytest.raises(FilterValidationError, match="1024") as loaded:
        load_typed_filter(document(node), FIELDS)
    assert parsed.value.code == loaded.value.code == "too_many_operands"


def test_typed_dump_and_compile_reject_an_oversized_ast():
    leaf = parse_typed_filter("Measurement = 0", FIELDS)
    expression = FilterExpressionGroup("and", (leaf,) * 128)
    with pytest.raises(FilterValidationError, match="128") as dumped:
        dump_typed_filter(expression)
    with pytest.raises(FilterValidationError, match="128") as compiled:
        compile_typed_filter_sqlite(expression, COLUMNS, table_alias="s")
    assert dumped.value.code == compiled.value.code == "too_many_nodes"


def test_sql_binds_operands_and_requires_existing_qualified_column():
    operand = """' OR id > 0 -- " & %_"""
    expression = load_typed_filter(document(condition("label", "text", "equals", operand)), FIELDS)
    with pytest.raises(FilterValidationError, match="column mapping"):
        compile_typed_filter_sqlite(expression, {}, table_alias="s")

    compiled = compile_typed_filter_sqlite(expression, COLUMNS, table_alias="s")
    assert operand not in compiled.sql
    assert json.loads(compiled.parameters[0])["values"] == [operand]
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute('CREATE TABLE sample(id, "label ""source""")')
        connection.executemany("INSERT INTO sample VALUES (?, ?)", [(1, operand), (2, "different")])
        install_typed_filter_sqlite(connection)
        assert connection.execute(
            f"SELECT id FROM sample AS s WHERE {compiled.sql}", compiled.parameters,
        ).fetchall() == [(1,)]
        wrong = compile_typed_filter_sqlite(expression, {"label": "nonexistent"}, table_alias="s")
        with pytest.raises(sqlite3.OperationalError, match="no such column"):
            connection.execute(f"SELECT id FROM sample AS s WHERE {wrong.sql}", wrong.parameters)
    with closing(sqlite3.connect(":memory:")) as other:
        with pytest.raises(sqlite3.OperationalError, match="no such function"):
            other.execute("SELECT mz_reference_filter_match(NULL, ?)", compiled.parameters)

from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3

import pandas as pd
import pytest

from metroliza.shared.grouping_filter_core import (
    FilterExpressionGroup,
    parse_filter_expression,
)
from metroliza.shared.typed_filter import (
    FilterExecution,
    FilterField,
    FilterPreview,
    FilterValidationError,
    PandasFilterAdapter,
    SqliteFilterAdapter,
    compile_typed_filter_sqlite,
    dump_typed_filter,
    install_typed_filter_sqlite,
    load_typed_filter,
    parse_typed_filter,
)
from tests.typed_filter_conformance import (
    FIELDS,
    GROUPED_CASE,
    OPERATOR_CASES,
    ROWS,
    assert_selected_rows,
    condition,
    document,
)


COLUMNS = {"n": "number source", "d": "date source", "label": 'label "source"'}


@pytest.fixture
def reference_adapters():
    data = pd.DataFrame(ROWS[::-1], columns=("id", "n", "d", "label"), dtype=object)
    # Equivalent wall-calendar datetime in a different backend representation.
    data.loc[data.id == 5, "d"] = datetime(2026, 2, 16, 23, 55, tzinfo=timezone.utc)
    data.loc[data.id == 1, "label"] = pd.NA
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute('CREATE TABLE sample(id, "number source", "date source", "label ""source""")')
        connection.executemany("INSERT INTO sample VALUES (?, ?, ?, ?)", ROWS[::-1])
        yield PandasFilterAdapter(data, "id"), SqliteFilterAdapter(
            connection, "sample", row_id_column="id", columns=COLUMNS,
        )


@pytest.fixture
def selected_rows(reference_adapters):
    def select(expression, expected):
        for adapter in reference_adapters:
            assert_selected_rows(adapter, expression, expected)

    return select


@pytest.mark.parametrize(("field", "kind", "operator", "values", "expected"), OPERATOR_CASES)
def test_reference_operator_rows(selected_rows, field, kind, operator, values, expected):
    selected_rows(load_typed_filter(document(condition(field, kind, operator, *values)), FIELDS), expected)


def test_reference_conformance_covers_nested_mixed_types(selected_rows):
    encoded, expected = GROUPED_CASE
    selected_rows(load_typed_filter(encoded, FIELDS), expected)


def test_reference_previews_report_execution_and_support_count_only(reference_adapters):
    expression = parse_typed_filter("Measurement >= 0", FIELDS)
    for adapter, mode in zip(reference_adapters, ("in_memory", "sqlite_scan"), strict=True):
        prepared = adapter.prepare(expression)
        assert prepared.execution == FilterExecution(mode)
        assert prepared.preview(0) == FilterPreview(5, ())
        assert prepared.preview() == FilterPreview(5, (4, 5, 6, 7, 8))
        assert prepared.preview(1000) == prepared.preview()
        assert list(prepared.iter_row_ids()) == [4, 5, 6, 7, 8]
        for limit in (-1, True, 1001):
            with pytest.raises(ValueError, match="sample limit"):
                prepared.preview(limit)
        empty = adapter.prepare(parse_typed_filter("Measurement = 1234567", FIELDS))
        assert empty.preview(1) == empty.preview(0) == FilterPreview(0, ())


def test_reference_adapters_reject_value_inferred_legacy_conditions(reference_adapters):
    legacy = parse_filter_expression("n = 0", ["n"]).expression
    for adapter in reference_adapters:
        with pytest.raises(TypeError, match="Expected a typed filter"):
            adapter.prepare(legacy)


def test_post_filter_execution_requires_a_user_facing_reason():
    with pytest.raises(ValueError, match="post-filtering"):
        FilterExecution("post_filter")
    assert FilterExecution("post_filter", "Date values need source conversion.").reason


def test_explicit_remap_is_consumed_by_the_same_prepared_filter_contract(selected_rows):
    source = [FilterField("reference", "text", "Reference", "old source")]
    stored = dump_typed_filter(parse_typed_filter('Reference = "001"', source))
    expression = load_typed_filter(stored, FIELDS, remap={"reference": "label"})
    selected_rows(expression, [6])


def test_sqlite_reference_scans_even_with_a_value_index_and_releases_cursor():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute('CREATE TABLE "sample"" source"(id INTEGER PRIMARY KEY, n INTEGER)')
        connection.execute('CREATE INDEX value_index ON "sample"" source"(n)')
        connection.executemany('INSERT INTO "sample"" source" VALUES (?, ?)', [(1, 0), (2, 0)])
        adapter = SqliteFilterAdapter(connection, 'sample" source', row_id_column="id", columns={"n": "n"})
        expression = parse_typed_filter("Measurement = 0", FIELDS)
        compiled = compile_typed_filter_sqlite(expression, {"n": "n"}, table_alias="source")
        plan = connection.execute(
            f'EXPLAIN QUERY PLAN SELECT id FROM "sample"" source" AS source WHERE {compiled.sql} ORDER BY id',
            compiled.parameters,
        ).fetchall()
        assert any("SCAN" in row[3] for row in plan)
        connection.row_factory = sqlite3.Row
        prepared = adapter.prepare(expression)
        assert prepared.execution.mode == "sqlite_scan"
        assert prepared.preview(1) == FilterPreview(2, (1,))
        with closing(prepared.iter_row_ids()) as rows:
            assert next(rows) == 1
        assert connection.row_factory is sqlite3.Row
        connection.execute('DROP TABLE "sample"" source"')


def test_sqlite_preview_counts_and_samples_in_one_statement_without_a_window():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("CREATE TABLE preview_rows(id INTEGER PRIMARY KEY, n INTEGER)")
        connection.executemany("INSERT INTO preview_rows VALUES (?, ?)",
                               ((row_id, row_id % 2) for row_id in range(2501, 0, -1)))
        adapter = SqliteFilterAdapter(connection, "preview_rows", row_id_column="id", columns={"n": "n"})
        prepared = adapter.prepare(parse_typed_filter("Measurement = 0", FIELDS))
        statements = []
        connection.set_trace_callback(statements.append)
        try:
            assert prepared.preview(1000) == FilterPreview(1250, tuple(range(2, 2001, 2)))
        finally:
            connection.set_trace_callback(None)
        assert len(statements) == 1
        assert "COUNT(*) OVER" not in statements[0].upper()
        details = [row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + statements[0])]
        assert sum("SCAN source" in detail for detail in details) == 2
        assert any(detail.startswith("SCALAR SUBQUERY") for detail in details)
        assert all("MATERIALIZE" not in detail and "TEMP B-TREE" not in detail for detail in details)
        assert prepared.execution.mode == "sqlite_scan"


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
    selected_rows(load_typed_filter(document(_nested_condition(23)), FIELDS), [6])
    selected_rows(parse_typed_filter("(" * 24 + "Measurement = 0" + ")" * 24, FIELDS), [6])
    quoted_parentheses = "(" * 25
    selected_rows(parse_typed_filter(f'Label = "{quoted_parentheses}"', FIELDS), [])
    for depth in (24, 400):
        with pytest.raises(FilterValidationError, match="24") as failure:
            load_typed_filter(document(_nested_condition(depth)), FIELDS)
        assert failure.value.code == "nested_expression"
    too_deep = "(" * 25 + "Measurement = 0" + ")" * 25
    with pytest.raises(FilterValidationError, match="24") as failure:
        parse_typed_filter(too_deep, FIELDS)
    assert failure.value.code == "nested_expression"
    assert parse_filter_expression(too_deep, ["Measurement"]).expression is not None


def test_reference_adapters_agree_on_alternating_groups_at_depth_limit(selected_rows):
    leaf = condition("n", "number", "equals", 0)
    tree = leaf
    text = "Measurement = 0"
    for group_index in range(23):
        operator = "or" if group_index % 2 else "and"
        tree = {"operator": operator, "children": [leaf, tree]}
        text = f"Measurement = 0 {operator} ({text})"

    selected_rows(load_typed_filter(document(tree), FIELDS), [6])
    selected_rows(parse_typed_filter(text, FIELDS), [6])


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

from contextlib import closing
from dataclasses import replace
import sqlite3

import pandas as pd
import pytest

from metroliza.reports import report_query_service as canonical_query
from metroliza.shared.grouping_filter_core import MembershipFilterSpec, NumberFilterSpec
from tests.numeric_filter_cases import (
    ROUNDING_CASES, ROUNDING_VALUES,
    PRECISION_CASES, PRECISION_VALUES, PROBE_CASES, PROBE_VALUES, SOURCE_CASES,
)

from modules.report_schema import ensure_report_schema
from modules.industrial_join_service import set_manual_industrial_report_link
from modules.report_query_service import (
    _append_industrial_context_to_export_query,
    build_distinct_value_query,
    build_grouping_query,
    build_industrial_measurement_export_query,
    build_measurement_expression_clause,
    build_measurement_export_query,
    build_measurement_filter_query,
    build_report_overview_query,
)
from tests.industrial_analytics_fixtures import seed_production_analytics_cache


@pytest.mark.parametrize("spec, expected_ids", PROBE_CASES)
def test_finite_numeric_probe_executes_sql_expected_ids(spec, expected_ids):
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute('CREATE TABLE probe (row_id INTEGER PRIMARY KEY, reference TEXT)')
        conn.executemany("INSERT INTO probe VALUES (?, ?)", enumerate(PROBE_VALUES, start=1))
        before = conn.execute("SELECT * FROM probe ORDER BY row_id").fetchall()
        clause = canonical_query._filter_expression_spec_to_sql(spec)
        for _ in range(2):
            selected = conn.execute(f"SELECT row_id FROM probe WHERE {clause} ORDER BY row_id")
            assert [row[0] for row in selected] == expected_ids
        frame = pd.DataFrame({"reference": PROBE_VALUES}, index=range(1, 24))
        assert frame.index[spec.mask(frame)].tolist() == expected_ids
        assert conn.execute("SELECT * FROM probe ORDER BY row_id").fetchall() == before


@pytest.mark.parametrize("spec, expected_ids", PRECISION_CASES)
def test_finite_numeric_sql_precision_ids(spec, expected_ids):
    with closing(sqlite3.connect(":memory:")) as conn:
        # No affinity: native INTEGER/REAL and TEXT must remain distinguishable.
        conn.execute("CREATE TABLE probe (row_id INTEGER PRIMARY KEY, reference)")
        conn.executemany("INSERT INTO probe VALUES (?, ?)", enumerate(PRECISION_VALUES, start=1))
        clause = canonical_query._filter_expression_spec_to_sql(spec)
        rows = conn.execute(f"SELECT row_id FROM probe WHERE {clause} ORDER BY row_id")
        assert [row[0] for row in rows] == expected_ids


@pytest.mark.parametrize("source, expected", SOURCE_CASES)
def test_finite_numeric_sql_source_boundary(source, expected):
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE probe (reference)")
        conn.execute("INSERT INTO probe VALUES (?)", (source,))
        specs = [(NumberFilterSpec("reference", "is_blank"), expected is None)]
        if expected is not None:
            specs.extend([
                (NumberFilterSpec("reference", "eq", expected), True),
                (MembershipFilterSpec("reference", (expected,)), True),
            ])
        for spec, selected in specs:
            clause = canonical_query._filter_expression_spec_to_sql(spec)
            assert conn.execute(f"SELECT rowid FROM probe WHERE {clause}").fetchall() == (
                [(1,)] if selected else []
            )


@pytest.mark.parametrize("alias, case_index", [
    ("equals", 0), (" EQ ", 0), ("not_equals", 1), (" NE ", 1),
    ("greater_than", 2), (" GT ", 2), ("greater_or_equal", 3), (" GTE ", 3),
    ("less_than", 4), (" LT ", 4), ("less_or_equal", 5), (" LTE ", 5),
])
def test_finite_numeric_operator_aliases(alias, case_index):
    spec, expected_ids = PROBE_CASES[case_index]
    test_finite_numeric_probe_executes_sql_expected_ids(replace(spec, operator=alias), expected_ids)


def test_finite_numeric_not_in_operator_alias():
    spec, expected_ids = PROBE_CASES[-1]
    test_finite_numeric_probe_executes_sql_expected_ids(
        replace(spec, operator=" NOT_IN ", negate=False), expected_ids,
    )


@pytest.mark.parametrize("negate", [False, True])
def test_finite_numeric_large_membership_executes_public_query(negate):
    values = (*range(1100), 2**63)
    operator = "NOT IN" if negate else "IN"
    expression = "Measured " + operator + " (" + ",".join(map(str, values)) + ")"
    source = [499, 1200, "bad", None, "9223372036854775808", "9223372036854775809", "499.0", "1100.0"]
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE probe (meas)")
        conn.executemany("INSERT INTO probe VALUES (?)", [(value,) for value in source])
        clause = canonical_query.build_measurement_expression_clause(expression)
        rows = conn.execute(f"SELECT rowid FROM probe WHERE {clause} ORDER BY rowid").fetchall()
        assert rows == ([(2,), (3,), (4,), (6,), (8,)] if negate else [(1,), (5,), (7,)])


@pytest.mark.parametrize("values, expected_ids", [
    ([], []), ([None, "bad", "Inf"], []), (["1", 2, ".5"], [1, 2, 3]),
])
def test_finite_numeric_sql_empty_and_uniform_populations(values, expected_ids):
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE probe (row_id INTEGER PRIMARY KEY, reference)")
        conn.executemany("INSERT INTO probe VALUES (?, ?)", enumerate(values, start=1))
        clause = canonical_query._number_expression_clause(NumberFilterSpec("reference", "is_not_blank"))
        assert [row[0] for row in conn.execute(f"SELECT row_id FROM probe WHERE {clause}")] == expected_ids


@pytest.mark.parametrize("expression, expected_ids, expected_reports", [
    ("Measured = 0", [101], [10]),
    ("Measured != 0", [102, 201, 202, 301, 302, 401, 402], [10, 20, 30, 40]),
    ("Measured IN (0,.5)", [101, 202], [10, 20]),
    ("Measured NOT IN (0,.5)", [102, 201, 301, 302, 401, 402], [10, 20, 30, 40]),
    ("(Measured != 0 AND Measured < 1) OR (Measured IN (0) AND Reference = drop)",
     [202, 402], [20, 40]),
    ("(Measured NOT IN (0,.5) AND Reference = keep) OR Measured = 99",
     [102, 201, 301, 302, 401, 402], [10, 20, 30, 40]),
    ("Measured >= .5 AND Date >= 2026-01-01", [202, 302], [20, 30]),
])
def test_finite_numeric_public_query_grouping_export_scope(expression, expected_ids, expected_reports):
    records = (
        (10, 101, "keep", 0), (10, 102, "keep", "bad"),
        (20, 201, "keep", None), (20, 202, "keep", ".5"),
        (30, 301, "keep", "Inf"), (30, 302, "keep", 2.),
        (40, 401, "keep", "1e309"), (40, 402, "keep", -1), (50, 501, "drop", 0),
    )
    with closing(sqlite3.connect(":memory:")) as conn:
        definitions = [
            f'"{column}"' + (" INTEGER" if column in {"report_id", "measurement_id"}
                              else "" if column == "meas" else " TEXT")
            for column in _MEASUREMENT_EXPORT_TEST_COLUMNS
        ]
        conn.execute("CREATE TABLE vw_measurement_export (" + ", ".join(definitions) + ")")
        conn.executemany(
            "INSERT INTO vw_measurement_export VALUES ("
            + ",".join("?" for _ in _MEASUREMENT_EXPORT_TEST_COLUMNS) + ")",
            [_measurement_row(report_id=r, measurement_id=m, reference=ref, meas=value)
             for r, m, ref, value in records],
        )
        snapshot = conn.execute("SELECT *, typeof(meas) FROM vw_measurement_export").fetchall()
        query = canonical_query.build_measurement_filter_query(
            reference_values=["keep"], expression_text=expression,
        )
        grouping = canonical_query.build_grouping_query(query)
        export = canonical_query.build_measurement_export_query(query)
        expected_pairs = [(r, m) for r, m, _, _ in records if m in expected_ids]
        for _ in range(2):
            for selected_query in (query, export):
                actual = conn.execute(
                    f"SELECT report_id, measurement_id FROM ({selected_query}) ORDER BY measurement_id"
                ).fetchall()
                assert actual == expected_pairs
            reports = conn.execute(f"SELECT report_id FROM ({grouping}) ORDER BY report_id").fetchall()
            assert [row[0] for row in reports] == expected_reports
        assert conn.execute("SELECT *, typeof(meas) FROM vw_measurement_export").fetchall() == snapshot


@pytest.mark.parametrize("expression, error", [
    ("unknown_column = 0", KeyError), ("Measured > 1; DROP TABLE probe", ValueError),
    ("Measured IN (0); SELECT 1", ValueError),
])
def test_finite_numeric_public_query_rejects_unsafe_expression(expression, error):
    with pytest.raises(error):
        canonical_query.build_measurement_expression_clause(expression)


def test_finite_numeric_literal_language_is_preserved():
    # This untyped parser still treats Inf equality as text, per the authority.
    clause = canonical_query.build_measurement_expression_clause("Reference = Inf")
    assert "LOWER" in clause
    # Existing float-compatible numeric literals remain safe after normalization.
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE probe (meas INTEGER)")
        conn.execute("INSERT INTO probe VALUES (10)")
        clause = canonical_query.build_measurement_expression_clause("Measured = 1_0")
        assert conn.execute(f"SELECT rowid FROM probe WHERE {clause}").fetchall() == [(1,)]


_MEASUREMENT_EXPORT_TEST_COLUMNS = (
    "report_id",
    "measurement_id",
    "reference",
    "report_date",
    "report_time",
    "part_name",
    "revision",
    "sample_number",
    "sample_number_kind",
    "stats_count_raw",
    "stats_count_int",
    "operator_name",
    "directory_path",
    "file_name",
    "absolute_path",
    "parser_id",
    "template_family",
    "template_variant",
    "header",
    "section_name",
    "feature_label",
    "characteristic_name",
    "characteristic_family",
    "description",
    "ax",
    "nominal",
    "tol_plus",
    "tol_minus",
    "bonus",
    "meas",
    "dev",
    "outtol",
    "is_nok",
    "status_code",
    "page_number",
    "row_order",
    "has_nok",
    "nok_count",
)


def _create_measurement_export_table(conn):
    conn.execute(
        "CREATE TABLE vw_measurement_export ("
        + ", ".join(f"{column} TEXT" for column in _MEASUREMENT_EXPORT_TEST_COLUMNS)
        + ")"
    )


def _create_typed_membership_table(conn):
    conn.execute(
        "CREATE TABLE typed_membership ("
        "report_id INTEGER, meas REAL, report_date TEXT, reference TEXT)"
    )


def _measurement_row(**overrides):
    values = {column: "" for column in _MEASUREMENT_EXPORT_TEST_COLUMNS}
    values.update(
        {
            "report_date": "2026-01-01",
            "parser_id": "cmm",
            "template_family": "cmm_pdf",
            "status_code": "ok",
            "has_nok": "0",
            "nok_count": "0",
        }
    )
    values.update(overrides)
    return tuple(values[column] for column in _MEASUREMENT_EXPORT_TEST_COLUMNS)


def test_build_report_overview_query_uses_view():
    query = build_report_overview_query()

    assert "FROM vw_report_overview" in query
    assert "report_id" in query
    assert "source_file_id" in query


def test_build_grouping_query_defaults_to_report_id_first_view():
    query = build_grouping_query()

    assert "FROM vw_grouping_reports" in query
    assert "report_id AS REPORT_ID" in query
    assert "reference AS REFERENCE" in query
    assert "sample_number AS SAMPLE_NUMBER" in query


def test_build_grouping_query_wraps_filter_query():
    filter_query = build_measurement_filter_query(reference_values=["REF1"])

    query = build_grouping_query(filter_query)

    assert "FROM (" in query
    assert filter_query.rstrip(";") in query
    assert '"REPORT_ID" AS REPORT_ID' in query


def test_build_measurement_export_query_uses_denormalized_view():
    query = build_measurement_export_query()

    assert "FROM vw_measurement_export" in query
    assert "measurement_id AS MEASUREMENT_ID" in query
    assert "header AS HEADER" in query
    assert "ax AS AX" in query
    assert 'tol_plus AS "+TOL"' in query
    assert 'tol_minus AS "-TOL"' in query


def test_build_industrial_measurement_export_query_appends_cached_context(tmp_path):
    db_path = str(tmp_path / "reports.db")
    ensure_report_schema(db_path)

    query = build_industrial_measurement_export_query()

    assert "FROM vw_measurement_export" in query
    assert "industrial_link_candidates" in query
    assert "INDUSTRIAL_RECORD_ID" in query
    assert "INDUSTRIAL_STATION" in query
    assert "INDUSTRIAL_LINK_CONFIDENCE" in query
    with closing(sqlite3.connect(db_path)) as conn, conn:
        assert conn.execute(query).fetchall() == []


def test_build_measurement_export_query_can_include_industrial_context():
    query = build_measurement_export_query(include_industrial_context=True)

    assert "INDUSTRIAL_SOURCE_PROFILE" in query
    assert "base.*" in query


def test_industrial_context_export_uses_manual_accepted_link_before_auto_link(tmp_path):
    db_path = str(tmp_path / "reports.db")
    seed_production_analytics_cache(db_path, include_report_tables=True)

    with closing(sqlite3.connect(db_path)) as conn, conn:
        manual_record_id = conn.execute(
            "SELECT id FROM industrial_records WHERE reference = 'REF-200' ORDER BY id LIMIT 1"
        ).fetchone()[0]

    set_manual_industrial_report_link(
        db_path,
        report_id=1,
        industrial_record_id=int(manual_record_id),
    )

    query = _append_industrial_context_to_export_query(
        "SELECT 1 AS REPORT_ID, 'REF-100' AS REFERENCE"
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        row = conn.execute(query).fetchone()
        columns = [description[0] for description in conn.execute(query).description]

    result = dict(zip(columns, row, strict=True))
    assert result["INDUSTRIAL_RECORD_ID"] == manual_record_id
    assert result["INDUSTRIAL_LINK_RULE"] == "Manual user link"


def test_build_measurement_filter_query_includes_report_level_filters():
    query = build_measurement_filter_query(
        ax_values=["AX1"],
        header_values=["HEAD1"],
        reference_values=["REF1"],
        part_name_values=["Part A"],
        revision_values=["B"],
        template_variant_values=["variant_one"],
        sample_number_values=["7"],
        operator_name_values=["Jane Doe"],
        sample_number_kind_values=["stats_count"],
        status_code_values=["nok"],
        filename_values=["part.csv"],
        parser_id_values=["cmm"],
        template_family_values=["cmm_pdf_header_box"],
        has_nok_only=True,
        date_from="2024-01-01",
        date_to="2024-12-31",
    )

    assert "FROM vw_measurement_export" in query
    assert "measurement_id AS MEASUREMENT_ID" in query
    assert "ax IN ('AX1')" in query
    assert "header IN ('HEAD1')" in query
    assert "reference IN ('REF1')" in query
    assert "part_name IN ('Part A')" in query
    assert "revision IN ('B')" in query
    assert "template_variant IN ('variant_one')" in query
    assert "sample_number IN ('7')" in query
    assert "operator_name IN ('Jane Doe')" in query
    assert "sample_number_kind IN ('stats_count')" in query
    assert "status_code IN ('nok')" in query
    assert "file_name IN ('part.csv')" in query
    assert "parser_id IN ('cmm')" in query
    assert "template_family IN ('cmm_pdf_header_box')" in query
    assert "has_nok = 1" in query
    assert "report_date >= '2024-01-01'" in query
    assert "report_date <= '2024-12-31'" in query


def test_build_measurement_filter_query_combines_expression_with_list_filters():
    query = build_measurement_filter_query(
        reference_values=["REF1"],
        expression_text="Dimension=VAL1 AND Status=NOK",
    )

    assert "reference IN ('REF1')" in query
    assert 'LOWER(CAST("header" AS TEXT)) = LOWER(' in query
    assert 'LOWER(CAST("status_code" AS TEXT)) = LOWER(' in query
    assert "VAL1" in query
    assert "NOK" in query


def test_measurement_expression_filters_duplicate_dimension_by_reference(tmp_path):
    db_path = tmp_path / "measurements.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        _create_measurement_export_table(conn)
        placeholders = ", ".join("?" for _column in _MEASUREMENT_EXPORT_TEST_COLUMNS)
        conn.executemany(
            f"INSERT INTO vw_measurement_export VALUES ({placeholders})",
            [
                _measurement_row(report_id="1", measurement_id="1", reference="REF1", header="VAL1", ax="X"),
                _measurement_row(report_id="2", measurement_id="2", reference="REF2", header="VAL1", ax="X"),
                _measurement_row(report_id="3", measurement_id="3", reference="REF1", header="VAL2", ax="X"),
            ],
        )
        rows = conn.execute(
            build_measurement_filter_query(expression_text="Reference=REF1 AND Dimension=VAL1")
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "1"
    assert rows[0][2] == "REF1"
    assert rows[0][18] == "VAL1"


def test_measurement_expression_supports_case_insensitive_fields_operators_and_shorthand(
    tmp_path,
):
    db_path = tmp_path / "measurements.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        _create_measurement_export_table(conn)
        placeholders = ", ".join("?" for _column in _MEASUREMENT_EXPORT_TEST_COLUMNS)
        conn.executemany(
            f"INSERT INTO vw_measurement_export VALUES ({placeholders})",
            [
                _measurement_row(
                    report_id="1",
                    measurement_id="1",
                    reference="REF1",
                    header="VAL1",
                    meas="100",
                ),
                _measurement_row(
                    report_id="2",
                    measurement_id="2",
                    reference="REF2",
                    header="VAL2",
                    meas="250",
                ),
                _measurement_row(
                    report_id="3",
                    measurement_id="3",
                    reference="REF3",
                    header="VAL3",
                    meas="300",
                ),
            ],
        )
        contradiction = conn.execute(
            build_measurement_filter_query(expression_text="meas > 200 and < 150.2")
        ).fetchall()
        mixed_case = conn.execute(
            build_measurement_filter_query(
                expression_text="MEAS in (250, 300) oR reference=ref1"
            )
        ).fetchall()

    assert contradiction == []
    assert [row[0] for row in mixed_case] == ["1", "2", "3"]


def test_measurement_expression_rejects_unknown_source_columns():
    try:
        build_measurement_expression_clause("Param1 > 200 and < 150.2")
    except KeyError as exc:
        assert "Param1" in str(exc)
    else:
        raise AssertionError("Export filter expressions must reject unknown CMM fields")


def test_build_measurement_expression_clause_supports_boolean_wildcards_and_aliases():
    clause = build_measurement_expression_clause(
        "Reference=REF1 AND (Dimension=VAL1 OR Axis IN (X*, Y))"
    )

    assert 'LOWER(CAST("reference" AS TEXT)) = LOWER(' in clause
    assert 'LOWER(CAST("header" AS TEXT)) = LOWER(' in clause
    assert 'LOWER(CAST("ax" AS TEXT)) LIKE LOWER(' in clause
    assert 'LOWER(CAST("ax" AS TEXT)) IN (' in clause


def test_measurement_membership_matches_real_date_and_text_values(tmp_path):
    db_path = tmp_path / "typed-membership.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        _create_typed_membership_table(conn)
        conn.executemany(
            "INSERT INTO typed_membership VALUES (?, ?, ?, ?)",
            [
                (1, 250.0, "2026-05-01", "Ref-A"),
                (2, 300.0, "2026-05-02", "Ref-B"),
                (3, None, None, None),
                (4, "invalid", "not-a-date", "Ref-D"),
            ],
        )

        numeric = build_measurement_expression_clause("MEAS IN (250, 300)")
        dates = build_measurement_expression_clause(
            "REPORT_DATE IN (2026-05-01, 2026-05-03)"
        )
        text = build_measurement_expression_clause("REFERENCE IN (ref-a, ref-c)")
        assert conn.execute(
            f"SELECT report_id FROM typed_membership WHERE {numeric} ORDER BY report_id"
        ).fetchall() == [(1,), (2,)]
        assert conn.execute(
            f"SELECT report_id FROM typed_membership WHERE {dates} ORDER BY report_id"
        ).fetchall() == [(1,)]
        assert conn.execute(
            f"SELECT report_id FROM typed_membership WHERE {text} ORDER BY report_id"
        ).fetchall() == [(1,)]
        not_dates = build_measurement_expression_clause(
            "REPORT_DATE NOT IN (2026-05-01, 2026-05-03)"
        )
        assert conn.execute(
            f"SELECT report_id FROM typed_membership WHERE {not_dates} ORDER BY report_id"
        ).fetchall() == [(2,), (3,), (4,)]


def test_measurement_not_in_includes_missing_and_unparseable_values(tmp_path):
    db_path = tmp_path / "typed-membership.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("CREATE TABLE typed_membership (report_id INTEGER, meas)")
        conn.executemany(
            "INSERT INTO typed_membership VALUES (?, ?)",
            [(1, 250.0), (2, 100.0), (3, None), (4, "invalid")],
        )

        clause = build_measurement_expression_clause("MEAS NOT IN (0, 250, 300)")
        rows = conn.execute(
            f"SELECT report_id FROM typed_membership WHERE {clause} ORDER BY report_id"
        ).fetchall()

    assert rows == [(2,), (3,), (4,)]


def test_build_measurement_expression_clause_rejects_unknown_fields():
    try:
        build_measurement_expression_clause("Unknown=1")
    except KeyError as exc:
        assert "Unknown" in str(exc)
    else:
        raise AssertionError("Unknown expression fields must be rejected")


def test_build_distinct_value_query_targets_view_or_scoped_query():
    query = build_distinct_value_query("REFERENCE", source_view="vw_report_overview")
    assert 'FROM vw_report_overview' in query
    assert 'DISTINCT "REFERENCE" AS value' in query


def test_build_measurement_export_query_translates_report_scoped_filters(tmp_path):
    db_path = str(tmp_path / "reports.db")
    ensure_report_schema(db_path)
    report_scope_query = "SELECT report_id AS REPORT_ID, reference AS REFERENCE FROM vw_report_overview WHERE 1=1"

    query = build_measurement_export_query(report_scope_query)

    assert "FROM vw_measurement_export" in query
    assert "WHERE report_id IN" in query
    assert report_scope_query in query
    with closing(sqlite3.connect(db_path)) as conn, conn:
        assert conn.execute(query).fetchall() == []


def test_build_industrial_measurement_export_query_wraps_custom_filter_scope(tmp_path):
    db_path = str(tmp_path / "reports.db")
    ensure_report_schema(db_path)
    filter_query = build_measurement_filter_query(reference_values=["REF1"])

    query = build_industrial_measurement_export_query(filter_query)

    assert filter_query.rstrip(";") in query
    assert "INDUSTRIAL_RECORD_ID" in query
    with closing(sqlite3.connect(db_path)) as conn, conn:
        assert conn.execute(query).fetchall() == []


def test_build_distinct_value_query_translates_report_scope_for_measurement_values(tmp_path):
    db_path = str(tmp_path / "reports.db")
    ensure_report_schema(db_path)
    report_scope_query = "SELECT report_id AS REPORT_ID, reference AS REFERENCE FROM vw_report_overview WHERE 1=1"

    query = build_distinct_value_query("AX", filter_query=report_scope_query)

    assert "FROM vw_measurement_export" in query
    assert "WHERE report_id IN" in query
    with closing(sqlite3.connect(db_path)) as conn, conn:
        assert conn.execute(query).fetchall() == []


@pytest.mark.parametrize("spec, expected_ids", ROUNDING_CASES)
def test_finite_numeric_binary64_rounding_ids(spec, expected_ids):
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE probe (reference)")
        conn.executemany("INSERT INTO probe VALUES (?)", [(value,) for value in ROUNDING_VALUES])
        clause = canonical_query._filter_expression_spec_to_sql(spec)
        assert [row[0] for row in conn.execute(f"SELECT rowid FROM probe WHERE {clause} ORDER BY rowid")] == expected_ids

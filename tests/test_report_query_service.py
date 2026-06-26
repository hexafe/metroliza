import sqlite3

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
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(query).fetchall() == []


def test_build_measurement_export_query_can_include_industrial_context():
    query = build_measurement_export_query(include_industrial_context=True)

    assert "INDUSTRIAL_SOURCE_PROFILE" in query
    assert "base.*" in query


def test_industrial_context_export_uses_manual_accepted_link_before_auto_link(tmp_path):
    db_path = str(tmp_path / "reports.db")
    seed_production_analytics_cache(db_path, include_report_tables=True)

    with sqlite3.connect(db_path) as conn:
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
    with sqlite3.connect(db_path) as conn:
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
    with sqlite3.connect(db_path) as conn:
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
    with sqlite3.connect(db_path) as conn:
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
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(query).fetchall() == []


def test_build_industrial_measurement_export_query_wraps_custom_filter_scope(tmp_path):
    db_path = str(tmp_path / "reports.db")
    ensure_report_schema(db_path)
    filter_query = build_measurement_filter_query(reference_values=["REF1"])

    query = build_industrial_measurement_export_query(filter_query)

    assert filter_query.rstrip(";") in query
    assert "INDUSTRIAL_RECORD_ID" in query
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(query).fetchall() == []


def test_build_distinct_value_query_translates_report_scope_for_measurement_values(tmp_path):
    db_path = str(tmp_path / "reports.db")
    ensure_report_schema(db_path)
    report_scope_query = "SELECT report_id AS REPORT_ID, reference AS REFERENCE FROM vw_report_overview WHERE 1=1"

    query = build_distinct_value_query("AX", filter_query=report_scope_query)

    assert "FROM vw_measurement_export" in query
    assert "WHERE report_id IN" in query
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(query).fetchall() == []

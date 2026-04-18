import sqlite3

from modules.report_schema import ensure_report_schema
from modules.report_query_service import (
    build_distinct_value_query,
    build_grouping_query,
    build_measurement_export_query,
    build_measurement_filter_query,
    build_report_overview_query,
)


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


def test_build_distinct_value_query_translates_report_scope_for_measurement_values(tmp_path):
    db_path = str(tmp_path / "reports.db")
    ensure_report_schema(db_path)
    report_scope_query = "SELECT report_id AS REPORT_ID, reference AS REFERENCE FROM vw_report_overview WHERE 1=1"

    query = build_distinct_value_query("AX", filter_query=report_scope_query)

    assert "FROM vw_measurement_export" in query
    assert "WHERE report_id IN" in query
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(query).fetchall() == []

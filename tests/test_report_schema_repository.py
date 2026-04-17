import sqlite3

from modules.report_repository import ReportRepository, compute_sha256
from modules.report_schema import SCHEMA_VERSION, ensure_report_schema


def _columns(conn, table_name):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]


def test_report_schema_creates_storage_layers_and_views(tmp_path):
    db_path = str(tmp_path / "reports.db")

    ensure_report_schema(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        views = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
        }
        schema_version = conn.execute(
            "SELECT value FROM app_schema WHERE key = 'schema_version'"
        ).fetchone()[0]

    assert {
        "source_files",
        "source_file_locations",
        "parsed_reports",
        "report_metadata",
        "report_metadata_candidates",
        "report_metadata_warnings",
        "report_measurements",
        "app_schema",
    }.issubset(tables)
    assert {"vw_report_overview", "vw_measurement_export", "vw_grouping_reports"}.issubset(views)
    assert {
        "idx_source_files_sha256",
        "idx_report_metadata_reference",
        "idx_report_measurements_report",
        "idx_report_measurements_report_header_ax",
    }.issubset(indexes)
    assert schema_version == SCHEMA_VERSION


def test_report_schema_exposes_expected_view_columns(tmp_path):
    db_path = str(tmp_path / "reports.db")
    ensure_report_schema(db_path)

    with sqlite3.connect(db_path) as conn:
        overview_columns = _columns(conn, "vw_report_overview")
        export_columns = _columns(conn, "vw_measurement_export")
        grouping_columns = _columns(conn, "vw_grouping_reports")

    assert overview_columns[:6] == [
        "report_id",
        "source_file_id",
        "parser_id",
        "template_family",
        "template_variant",
        "parse_status",
    ]
    assert "sha256" in overview_columns
    assert export_columns[:11] == [
        "report_id",
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
    ]
    assert grouping_columns == [
        "report_id",
        "reference",
        "report_date",
        "sample_number",
        "part_name",
        "revision",
        "template_variant",
        "has_nok",
        "nok_count",
        "file_name",
    ]


def test_repository_dedupes_source_files_by_sha256_and_keeps_locations(tmp_path):
    db_path = str(tmp_path / "reports.db")
    first_path = tmp_path / "a" / "same.pdf"
    second_path = tmp_path / "b" / "same_copy.pdf"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    first_path.write_bytes(b"same-content")
    second_path.write_bytes(b"same-content")

    repository = ReportRepository(db_path)
    repository.ensure_schema()

    first_record = repository.upsert_source_file(first_path)
    second_record = repository.upsert_source_file(second_path)

    assert first_record.id == second_record.id
    assert first_record.sha256 == compute_sha256(first_path)

    with sqlite3.connect(db_path) as conn:
        source_count = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
        location_count = conn.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0]

    assert source_count == 1
    assert location_count == 2


def test_repository_persists_report_payload_and_views(tmp_path):
    db_path = str(tmp_path / "reports.db")
    source_path = tmp_path / "V1000_part_2024.01.02_03.pdf"
    source_path.write_bytes(b"report-content")
    repository = ReportRepository(db_path)

    report_id = repository.persist_parsed_report(
        source_path=source_path,
        parser_id="cmm",
        parser_version="1.0",
        template_family="cmm_pdf_header_box",
        template_variant="cmm_pdf_header_box_serial_variant",
        parse_status="parsed_with_warnings",
        metadata={
            "reference": "V1000",
            "reference_raw": "V1000",
            "report_date": "2024-01-02",
            "report_time": "08:09",
            "part_name": "Part",
            "revision": "A",
            "sample_number": "3",
            "sample_number_kind": "stats_count",
            "stats_count_raw": "3",
            "stats_count_int": 3,
            "operator_name": "Operator",
            "comment": None,
        },
        candidates=[
            {
                "field_name": "reference",
                "raw_value": "V1000",
                "normalized_value": "V1000",
                "source_type": "header",
                "source_detail": "label",
                "page_number": 1,
                "region_name": "page1_header_band",
                "label_text": "SER NUMBER",
                "rule_id": "header_exact_reference",
                "confidence": 0.95,
                "selected": True,
                "evidence_text": "SER NUMBER V1000",
            }
        ],
        warnings=[
            {
                "code": "sample_number_projected_from_stats_count",
                "field_name": "sample_number",
                "severity": "info",
                "message": "Sample number was projected from stats count.",
                "details": {"source": "stats_count"},
            }
        ],
        measurements=[
            {
                "page_number": 1,
                "row_order": 1,
                "header": "Feature 1",
                "section_name": "Feature 1",
                "feature_label": "Feature 1",
                "characteristic_name": "LOC",
                "characteristic_family": "LOC",
                "description": "Feature 1 LOC",
                "ax": "X",
                "nominal": 10.0,
                "tol_plus": 0.1,
                "tol_minus": -0.1,
                "bonus": 0.0,
                "meas": 10.2,
                "dev": 0.2,
                "outtol": 0.1,
            }
        ],
        metadata_version="report_metadata_v1",
        metadata_profile_id="cmm_pdf_header_box",
        metadata_profile_version="1",
        page_count=2,
        measurement_count=1,
        has_nok=True,
        nok_count=1,
        metadata_confidence=0.9,
        identity_hash="identity-1",
    )

    with sqlite3.connect(db_path) as conn:
        overview = conn.execute("SELECT * FROM vw_report_overview").fetchone()
        overview_columns = [description[0] for description in conn.execute("SELECT * FROM vw_report_overview").description]
        export = conn.execute("SELECT * FROM vw_measurement_export").fetchone()
        export_columns = [description[0] for description in conn.execute("SELECT * FROM vw_measurement_export").description]
        warning_count = conn.execute("SELECT COUNT(*) FROM report_metadata_warnings").fetchone()[0]
        candidate_count = conn.execute("SELECT COUNT(*) FROM report_metadata_candidates").fetchone()[0]

    overview_map = dict(zip(overview_columns, overview))
    export_map = dict(zip(export_columns, export))
    assert overview_map["report_id"] == report_id
    assert overview_map["reference"] == "V1000"
    assert overview_map["has_nok"] == 1
    assert export_map["status_code"] == "nok"
    assert export_map["is_nok"] == 1
    assert warning_count == 1
    assert candidate_count == 1

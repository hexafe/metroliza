import json
import sqlite3

from modules.report_identity import build_report_identity_hash
from modules.report_metadata_models import CanonicalReportMetadata
from modules.report_repository import ReportRepository, compute_sha256
from modules.report_schema import SCHEMA_VERSION, ensure_report_schema


def _columns(conn, table_name):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]


def _identity_hash(
    *,
    reference="REF-1",
    report_date="2024-01-01",
    report_time="08:00",
    part_name="Part",
    revision="A",
    sample_number="1",
    template_variant="variant",
    page_count=1,
):
    return build_report_identity_hash(
        CanonicalReportMetadata(
            parser_id="cmm",
            template_family="cmm_pdf_header_box",
            template_variant=template_variant,
            metadata_confidence=1.0,
            reference=reference,
            reference_raw=reference,
            report_date=report_date,
            report_time=report_time,
            part_name=part_name,
            revision=revision,
            sample_number=sample_number,
            sample_number_kind="explicit_sample_number",
            stats_count_raw=None,
            stats_count_int=None,
            operator_name="Operator",
            comment=None,
            page_count=page_count,
            metadata_json={"field_sources": {}},
            warnings=(),
        )
    )


def _persist_basic_report(
    tmp_path,
    repository,
    *,
    file_name="report.pdf",
    reference="REF-1",
    report_date="2024-01-01",
    report_time="08:00",
    part_name="Part",
    revision="A",
    sample_number="1",
    template_variant="variant",
    identity_hash=None,
    outtol=0.0,
):
    source_path = tmp_path / file_name
    source_path.write_bytes(f"{file_name}-content".encode("utf-8"))
    identity_hash = identity_hash or _identity_hash(
        reference=reference,
        report_date=report_date,
        report_time=report_time,
        part_name=part_name,
        revision=revision,
        sample_number=sample_number,
        template_variant=template_variant,
    )
    return repository.persist_parsed_report(
        source_path=source_path,
        parser_id="cmm",
        parser_version="1.0",
        template_family="cmm_pdf_header_box",
        template_variant=template_variant,
        parse_status="parsed",
        metadata={
            "reference": reference,
            "reference_raw": reference,
            "report_date": report_date,
            "report_time": report_time,
            "part_name": part_name,
            "revision": revision,
            "sample_number": sample_number,
            "sample_number_kind": "explicit_sample_number",
            "operator_name": "Operator",
            "metadata_json": {"field_sources": {"reference": "header_exact"}},
        },
        candidates=(),
        warnings=(),
        measurements=[
            {
                "page_number": 1,
                "row_order": 1,
                "header": "Feature 1",
                "section_name": "Feature 1",
                "feature_label": "Feature 1",
                "characteristic_name": "LOC",
                "characteristic_family": "LOC",
                "description": "Feature 1",
                "ax": "X",
                "nominal": 10.0,
                "tol_plus": 0.1,
                "tol_minus": -0.1,
                "bonus": 0.0,
                "meas": 10.0,
                "dev": 0.0,
                "outtol": outtol,
                "raw_measurement_json": {"tokens": ["X"], "header": "Feature 1"},
            }
        ],
        metadata_version="report_metadata_v1",
        page_count=1,
        measurement_count=1,
        has_nok=bool(outtol),
        nok_count=1 if outtol else 0,
        metadata_confidence=1.0,
        identity_hash=identity_hash,
    )


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
    assert export_columns[:12] == [
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
    ]
    assert "measurement_id" not in overview_columns
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


def test_report_schema_refreshes_stale_measurement_export_view(tmp_path):
    db_path = str(tmp_path / "reports.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE VIEW vw_measurement_export AS SELECT 1 AS report_id")

    ensure_report_schema(db_path)

    with sqlite3.connect(db_path) as conn:
        export_columns = _columns(conn, "vw_measurement_export")

    assert "measurement_id" in export_columns


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
    assert export_map["measurement_id"] is not None
    assert warning_count == 1
    assert candidate_count == 1


def test_update_report_metadata_identity_field_recomputes_hash_and_removes_stale_duplicate_warning(tmp_path):
    db_path = str(tmp_path / "reports.db")
    repository = ReportRepository(db_path)
    repository.ensure_schema()
    duplicate_hash = _identity_hash(reference="REF-1")
    first_report_id = _persist_basic_report(
        tmp_path,
        repository,
        file_name="first.pdf",
        reference="REF-1",
        identity_hash=duplicate_hash,
    )
    _persist_basic_report(
        tmp_path,
        repository,
        file_name="second.pdf",
        reference="REF-1",
        identity_hash=duplicate_hash,
    )
    repository.persist_semantic_duplicate_warnings(first_report_id, duplicate_hash)

    repository.update_report_metadata_fields(
        first_report_id,
        {"reference": "REF-2"},
        source="manual",
        reason="operator correction",
    )

    expected_hash = _identity_hash(reference="REF-2")
    with sqlite3.connect(db_path) as conn:
        identity_hash = conn.execute(
            "SELECT identity_hash FROM parsed_reports WHERE id = ?",
            (first_report_id,),
        ).fetchone()[0]
        warning_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM report_metadata_warnings
            WHERE report_id = ?
              AND code = 'semantic_duplicate_identity_hash_detected'
            """,
            (first_report_id,),
        ).fetchone()[0]
        metadata_json = json.loads(
            conn.execute(
                "SELECT metadata_json FROM report_metadata WHERE report_id = ?",
                (first_report_id,),
            ).fetchone()[0]
        )

    assert identity_hash == expected_hash
    assert warning_count == 0
    assert metadata_json["reference"] == "REF-2"
    assert metadata_json["field_sources"]["reference"] == "manual"
    assert metadata_json["manual_overrides"]["reference"]["reason"] == "operator correction"


def test_update_report_metadata_non_identity_field_keeps_hash(tmp_path):
    db_path = str(tmp_path / "reports.db")
    repository = ReportRepository(db_path)
    repository.ensure_schema()
    original_hash = _identity_hash(reference="REF-1")
    report_id = _persist_basic_report(
        tmp_path,
        repository,
        file_name="non_identity.pdf",
        reference="REF-1",
        identity_hash=original_hash,
    )

    repository.update_report_metadata_fields(report_id, {"operator_name": "New Operator"})

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT pr.identity_hash, rm.operator_name
            FROM parsed_reports pr
            JOIN report_metadata rm ON rm.report_id = pr.id
            WHERE pr.id = ?
            """,
            (report_id,),
        ).fetchone()

    assert row == (original_hash, "New Operator")


def test_replace_report_metadata_enrichment_preserves_measurement_rows(tmp_path):
    db_path = str(tmp_path / "reports.db")
    repository = ReportRepository(db_path)
    repository.ensure_schema()
    original_hash = _identity_hash(reference="REF-1")
    report_id = _persist_basic_report(
        tmp_path,
        repository,
        file_name="synthetic_source.pdf",
        reference="REF-1",
        identity_hash=original_hash,
    )

    repository.replace_report_metadata_enrichment(
        report_id,
        {
            "reference": "REF-2",
            "reference_raw": "REF-2",
            "report_date": "2024-01-03",
            "report_time": "09:10",
            "part_name": "Part",
            "revision": "B",
            "sample_number": "2",
            "sample_number_kind": "explicit_sample_number",
            "operator_name": "Operator",
            "metadata_json": {
                "field_sources": {"reference": "position_cell"},
                "header_extraction_mode": "ocr",
            },
        },
        candidates=[
            {
                "field_name": "reference",
                "raw_value": "REF-2",
                "normalized_value": "REF-2",
                "source_type": "header",
                "source_detail": "position_cell",
                "rule_id": "synthetic_reference_candidate",
                "confidence": 0.98,
                "selected": True,
            }
        ],
        warnings=[
            {
                "code": "synthetic_metadata_warning",
                "field_name": "reference",
                "severity": "info",
                "message": "Synthetic metadata warning.",
            }
        ],
        metadata_version="report_metadata_v1",
        metadata_profile_id="cmm_pdf_header_box",
        metadata_profile_version="1",
        parse_status="parsed_with_warnings",
        metadata_confidence=0.98,
        identity_hash="identity-2",
        raw_report_json={"parse_backend": "synthetic", "header_extraction_mode": "ocr"},
    )

    with sqlite3.connect(db_path) as conn:
        measurement_rows = conn.execute(
            """
            SELECT id, report_id, row_order, header, ax, meas, raw_measurement_json
            FROM report_measurements
            WHERE report_id = ?
            """,
            (report_id,),
        ).fetchall()
        parsed_row = conn.execute(
            """
            SELECT parse_status, metadata_confidence, identity_hash, measurement_count, has_nok, nok_count, raw_report_json
            FROM parsed_reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()
        metadata_row = conn.execute(
            "SELECT reference, revision, metadata_json FROM report_metadata WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        candidate_count = conn.execute(
            "SELECT COUNT(*) FROM report_metadata_candidates WHERE report_id = ?",
            (report_id,),
        ).fetchone()[0]
        warning_count = conn.execute(
            "SELECT COUNT(*) FROM report_metadata_warnings WHERE report_id = ?",
            (report_id,),
        ).fetchone()[0]

    assert len(measurement_rows) == 1
    assert measurement_rows[0][1:6] == (report_id, 1, "Feature 1", "X", 10.0)
    assert json.loads(measurement_rows[0][6]) == {"header": "Feature 1", "tokens": ["X"]}
    assert parsed_row[:6] == ("parsed_with_warnings", 0.98, "identity-2", 1, 0, 0)
    assert json.loads(parsed_row[6])["header_extraction_mode"] == "ocr"
    assert metadata_row[:2] == ("REF-2", "B")
    assert json.loads(metadata_row[2])["field_sources"]["reference"] == "position_cell"
    assert candidate_count == 1
    assert warning_count == 1


def test_replace_report_metadata_enrichment_rolls_back_as_one_transaction(tmp_path):
    db_path = str(tmp_path / "reports.db")
    repository = ReportRepository(db_path)
    repository.ensure_schema()
    report_id = _persist_basic_report(tmp_path, repository, file_name="rollback_source.pdf")
    repository.replace_metadata_candidates(
        report_id,
        [
            {
                "field_name": "reference",
                "raw_value": "REF-1",
                "normalized_value": "REF-1",
                "source_type": "header",
                "rule_id": "original_candidate",
                "confidence": 0.9,
                "selected": True,
            }
        ],
    )
    repository.replace_metadata_warnings(
        report_id,
        [
            {
                "code": "original_warning",
                "field_name": "reference",
                "severity": "info",
                "message": "Original synthetic warning.",
            }
        ],
    )

    with sqlite3.connect(db_path) as conn:
        original_measurements = conn.execute(
            "SELECT id, report_id, row_order, header, ax, meas FROM report_measurements WHERE report_id = ?",
            (report_id,),
        ).fetchall()

    try:
        repository.replace_report_metadata_enrichment(
            report_id,
            {
                "reference": "REF-ROLLBACK",
                "reference_raw": "REF-ROLLBACK",
                "report_date": "2024-01-04",
                "report_time": "10:11",
                "part_name": "Part",
                "revision": "C",
                "sample_number": "3",
                "sample_number_kind": "explicit_sample_number",
                "operator_name": "Operator",
                "metadata_json": {"field_sources": {"reference": "position_cell"}},
            },
            candidates=[
                {
                    "field_name": "reference",
                    "raw_value": "REF-ROLLBACK",
                    "normalized_value": "REF-ROLLBACK",
                    "source_type": "header",
                    "rule_id": "invalid_candidate",
                    "confidence": 1.5,
                    "selected": True,
                }
            ],
            warnings=[],
            metadata_version="report_metadata_v1",
            parse_status="parsed_with_warnings",
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("Expected metadata enrichment replacement to fail")

    with sqlite3.connect(db_path) as conn:
        metadata_reference = conn.execute(
            "SELECT reference FROM report_metadata WHERE report_id = ?",
            (report_id,),
        ).fetchone()[0]
        candidate_rules = [
            row[0]
            for row in conn.execute(
                "SELECT rule_id FROM report_metadata_candidates WHERE report_id = ?",
                (report_id,),
            ).fetchall()
        ]
        warning_codes = [
            row[0]
            for row in conn.execute(
                "SELECT code FROM report_metadata_warnings WHERE report_id = ?",
                (report_id,),
            ).fetchall()
        ]
        measurement_rows = conn.execute(
            "SELECT id, report_id, row_order, header, ax, meas FROM report_measurements WHERE report_id = ?",
            (report_id,),
        ).fetchall()
        parse_status = conn.execute(
            "SELECT parse_status FROM parsed_reports WHERE id = ?",
            (report_id,),
        ).fetchone()[0]

    assert metadata_reference == "REF-1"
    assert candidate_rules == ["original_candidate"]
    assert warning_codes == ["original_warning"]
    assert measurement_rows == original_measurements
    assert parse_status == "parsed"


def test_update_measurement_fields_keeps_status_aggregate_and_raw_json_coherent(tmp_path):
    db_path = str(tmp_path / "reports.db")
    repository = ReportRepository(db_path)
    repository.ensure_schema()
    report_id = _persist_basic_report(tmp_path, repository, file_name="measurement.pdf")

    with sqlite3.connect(db_path) as conn:
        measurement_id = conn.execute(
            "SELECT id FROM report_measurements WHERE report_id = ?",
            (report_id,),
        ).fetchone()[0]

    repository.update_measurement_fields(
        measurement_id,
        {"header": "Feature 2", "outtol": 0.25},
        source="manual",
    )

    with sqlite3.connect(db_path) as conn:
        measurement_row = conn.execute(
            """
            SELECT header, section_name, feature_label, description, outtol, is_nok, status_code, raw_measurement_json
            FROM report_measurements
            WHERE id = ?
            """,
            (measurement_id,),
        ).fetchone()
        report_row = conn.execute(
            "SELECT measurement_count, has_nok, nok_count FROM parsed_reports WHERE id = ?",
            (report_id,),
        ).fetchone()

    raw_json = json.loads(measurement_row[7])
    assert measurement_row[:7] == ("Feature 2", "Feature 2", "Feature 2", "Feature 2", 0.25, 1, "nok")
    assert raw_json["header"] == "Feature 2"
    assert raw_json["manual_overrides"]["outtol"]["source"] == "manual"
    assert report_row == (1, 1, 1)


def test_measurement_export_view_exposes_measurement_id(tmp_path):
    db_path = str(tmp_path / "reports.db")
    repository = ReportRepository(db_path)
    repository.ensure_schema()
    report_id = _persist_basic_report(tmp_path, repository, file_name="view_measurement.pdf")

    with sqlite3.connect(db_path) as conn:
        measurement_id = conn.execute(
            "SELECT id FROM report_measurements WHERE report_id = ?",
            (report_id,),
        ).fetchone()[0]
        export_measurement_id = conn.execute(
            "SELECT measurement_id FROM vw_measurement_export WHERE report_id = ?",
            (report_id,),
        ).fetchone()[0]

    assert export_measurement_id == measurement_id

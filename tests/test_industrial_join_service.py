import sqlite3

from modules.industrial_data_repository import IndustrialDataRepository
from modules.industrial_join_service import (
    IndustrialJoinRuleSpec,
    clear_manual_industrial_report_link,
    materialize_industrial_report_links,
    set_manual_industrial_report_link,
    validate_join_rule,
)
from modules.report_repository import ReportRepository
from modules.report_query_service import build_measurement_export_query


def _persist_report(tmp_path, repository, *, file_name, reference, report_date="2026-05-10", report_time="10:00:00"):
    source_path = tmp_path / file_name
    source_path.write_bytes(f"{file_name}-content".encode("utf-8"))
    return repository.persist_parsed_report(
        source_path=source_path,
        parser_id="cmm",
        parser_version="1.0",
        template_family="cmm_pdf_header_box",
        template_variant="variant",
        parse_status="parsed",
        metadata={
            "reference": reference,
            "reference_raw": reference,
            "report_date": report_date,
            "report_time": report_time,
            "part_name": "Housing",
            "revision": "A",
            "sample_number": "1",
            "sample_number_kind": "explicit_sample_number",
            "operator_name": "Operator",
            "metadata_json": {"field_sources": {"reference": "synthetic"}},
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
                "outtol": 0.0,
                "raw_measurement_json": {"tokens": ["X"]},
            }
        ],
        metadata_version="report_metadata_v1",
        page_count=1,
        measurement_count=1,
        has_nok=False,
        nok_count=0,
        metadata_confidence=1.0,
        identity_hash=f"identity-{reference}",
    )


def test_materialize_industrial_report_links_marks_exact_and_ambiguous(tmp_path):
    db_path = str(tmp_path / "reports.db")
    report_repository = ReportRepository(db_path)
    report_repository.ensure_schema()
    _persist_report(tmp_path, report_repository, file_name="ref-1.pdf", reference="REF-1")
    _persist_report(tmp_path, report_repository, file_name="ref-2.pdf", reference="REF-2")
    _persist_report(tmp_path, report_repository, file_name="missing.pdf", reference="REF-MISSING")

    industrial_repository = IndustrialDataRepository(db_path)
    profile = industrial_repository.upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="plant_a",
        database_type="mssql",
        source_object_name="assembly.events",
        allowed_columns=["reference", "station", "line"],
    )
    industrial_repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=[
            {"source_record_key": "A-1", "reference": "REF-1", "station": "S1"},
            {"source_record_key": "B-1", "reference": "REF-2", "station": "S2"},
            {"source_record_key": "B-2", "reference": "REF-2", "station": "S3"},
        ],
    )

    summary = materialize_industrial_report_links(db_path)

    assert summary.reports_seen == 3
    assert summary.records_seen == 3
    assert summary.accepted_links == 1
    assert summary.ambiguous_reports == 1
    assert summary.unmatched_reports == 1
    assert summary.candidates_inserted == 3

    with sqlite3.connect(db_path) as conn:
        statuses = {
            row[0]: row[1]
            for row in conn.execute(
                """
                SELECT report_metadata.reference, industrial_link_candidates.status
                FROM industrial_link_candidates
                JOIN parsed_reports ON parsed_reports.id = industrial_link_candidates.report_id
                JOIN report_metadata ON report_metadata.report_id = parsed_reports.id
                ORDER BY report_metadata.reference, industrial_link_candidates.id
                """
            ).fetchall()
        }

    assert statuses["REF-1"] == "accepted"
    assert statuses["REF-2"] == "candidate"


def test_materialize_time_window_join_uses_report_and_process_timestamps(tmp_path):
    db_path = str(tmp_path / "reports.db")
    report_repository = ReportRepository(db_path)
    report_repository.ensure_schema()
    _persist_report(
        tmp_path,
        report_repository,
        file_name="ref-1.pdf",
        reference="REF-1",
        report_date="2026-05-10",
        report_time="10:00:00",
    )

    industrial_repository = IndustrialDataRepository(db_path)
    profile = industrial_repository.upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="plant_a",
        database_type="mssql",
        source_object_name="assembly.events",
    )
    industrial_repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=[
            {
                "source_record_key": "A-1",
                "reference": "REF-1",
                "process_timestamp": "2026-05-10T10:04:00Z",
            },
            {
                "source_record_key": "A-2",
                "reference": "REF-1",
                "process_timestamp": "2026-05-10T10:20:00Z",
            },
        ],
    )

    summary = materialize_industrial_report_links(
        db_path,
        IndustrialJoinRuleSpec(
            rule_key="reference_time",
            rule_name="Reference within 5 minutes",
            match_mode="time_window",
            time_window_seconds=300,
        ),
    )

    assert summary.accepted_links == 1
    assert summary.candidates_inserted == 1


def test_join_rule_validator_rejects_unsupported_fuzzy_mode():
    try:
        validate_join_rule(IndustrialJoinRuleSpec(match_mode="fuzzy"))
    except ValueError as exc:
        assert "Unsupported industrial join mode" in str(exc)
    else:
        raise AssertionError("fuzzy join mode should not be accepted until implemented")


def test_manual_link_allows_different_report_and_production_references(tmp_path):
    db_path = str(tmp_path / "reports.db")
    report_repository = ReportRepository(db_path)
    report_repository.ensure_schema()
    _persist_report(tmp_path, report_repository, file_name="met-ref.pdf", reference="MET-123")

    industrial_repository = IndustrialDataRepository(db_path)
    profile = industrial_repository.upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="plant_a",
        database_type="mssql",
        source_object_name="assembly.events",
        allowed_columns=["reference", "station"],
    )
    industrial_repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=[
            {
                "source_record_key": "PROD-9",
                "reference": "PRODUCTION-999",
                "station": "S1",
            }
        ],
    )

    with sqlite3.connect(db_path) as conn:
        report_id = conn.execute("SELECT id FROM parsed_reports").fetchone()[0]
        production_record_id = conn.execute("SELECT id FROM industrial_records").fetchone()[0]

    link_id = set_manual_industrial_report_link(
        db_path,
        report_id=report_id,
        industrial_record_id=production_record_id,
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                industrial_link_candidates.id,
                industrial_link_candidates.status,
                industrial_link_candidates.confidence,
                industrial_join_rules.rule_key,
                industrial_join_rules.priority,
                report_metadata.reference,
                industrial_records.reference
            FROM industrial_link_candidates
            JOIN industrial_join_rules
                ON industrial_join_rules.id = industrial_link_candidates.join_rule_id
            JOIN parsed_reports ON parsed_reports.id = industrial_link_candidates.report_id
            JOIN report_metadata ON report_metadata.report_id = parsed_reports.id
            JOIN industrial_records
                ON industrial_records.id = industrial_link_candidates.industrial_record_id
            """
        ).fetchone()

    assert row == (link_id, "accepted", 1.0, "manual_user_link", 0, "MET-123", "PRODUCTION-999")

    export_query = build_measurement_export_query(include_industrial_context=True)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        export_row = conn.execute(export_query).fetchone()

    assert export_row["REFERENCE"] == "MET-123"
    assert export_row["INDUSTRIAL_RECORD_ID"] == production_record_id
    assert export_row["INDUSTRIAL_STATION"] == "S1"

    removed = clear_manual_industrial_report_link(db_path, report_id=report_id)
    with sqlite3.connect(db_path) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM industrial_link_candidates").fetchone()[0]

    assert removed == 1
    assert remaining == 0

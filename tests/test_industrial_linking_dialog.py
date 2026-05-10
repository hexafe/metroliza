from __future__ import annotations

import sqlite3

import pytest

try:
    from PyQt6.QtWidgets import QApplication

    from modules.industrial_linking_dialog import IndustrialLinkingDialog
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    IndustrialLinkingDialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

from modules.industrial_data_repository import IndustrialDataRepository
from modules.report_repository import ReportRepository


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial linking dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _persist_report(tmp_path, repository: ReportRepository, *, reference: str):
    source_path = tmp_path / f"{reference}.pdf"
    source_path.write_bytes(f"{reference}-content".encode("utf-8"))
    repository.persist_parsed_report(
        source_path=source_path,
        parser_id="cmm",
        parser_version="1.0",
        template_family="cmm_pdf_header_box",
        template_variant="variant",
        parse_status="parsed",
        metadata={
            "reference": reference,
            "reference_raw": reference,
            "report_date": "2026-05-10",
            "report_time": "10:00:00",
            "part_name": "Housing",
            "revision": "A",
            "sample_number": "1",
            "sample_number_kind": "explicit_sample_number",
            "operator_name": "Operator",
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


def _prepare_linking_db(tmp_path) -> str:
    db_path = str(tmp_path / "reports.db")
    report_repository = ReportRepository(db_path)
    report_repository.ensure_schema()
    _persist_report(tmp_path, report_repository, reference="MET-123")

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
    return db_path


def test_manual_linking_dialog_links_and_clears_different_references(tmp_path):
    _app()
    db_path = _prepare_linking_db(tmp_path)
    dialog = IndustrialLinkingDialog(db_file=db_path)

    dialog.report_table.selectRow(0)
    dialog.production_table.selectRow(0)
    dialog.link_selected_records()

    with sqlite3.connect(db_path) as conn:
        linked = conn.execute(
            """
            SELECT report_metadata.reference, industrial_records.reference
            FROM industrial_link_candidates
            JOIN parsed_reports ON parsed_reports.id = industrial_link_candidates.report_id
            JOIN report_metadata ON report_metadata.report_id = parsed_reports.id
            JOIN industrial_records
                ON industrial_records.id = industrial_link_candidates.industrial_record_id
            WHERE industrial_link_candidates.status = 'accepted'
            """
        ).fetchone()

    assert linked == ("MET-123", "PRODUCTION-999")

    dialog.report_table.selectRow(0)
    dialog.clear_selected_manual_link()
    with sqlite3.connect(db_path) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM industrial_link_candidates").fetchone()[0]

    assert remaining == 0
    dialog.close()

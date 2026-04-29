import json
import sqlite3

from modules.metadata_enrichment_thread import (
    MetadataEnrichmentWorkItem,
    discover_metadata_enrichment_work,
    enrich_existing_report_metadata,
)
from modules.report_metadata_models import CanonicalReportMetadata, MetadataCandidate, MetadataSelectionResult
from modules.report_repository import ReportRepository


def _persist_report(tmp_path, repository, *, name, metadata_json, revision=None, operator_name=None):
    source_path = tmp_path / name
    source_path.write_bytes(f"{name}-bytes".encode("utf-8"))
    report_id = repository.persist_parsed_report(
        source_path=source_path,
        parser_id="cmm_pdf_header_box",
        parser_version="1.1.0",
        template_family="cmm_pdf_header_box",
        template_variant="synthetic_variant",
        parse_status="parsed",
        metadata={
            "reference": "LIGHT-REF",
            "reference_raw": "LIGHT-REF",
            "report_date": "2024-01-01",
            "part_name": "Light Part",
            "revision": revision,
            "sample_number": "7",
            "sample_number_kind": "filename_tail",
            "stats_count_raw": "7",
            "stats_count_int": 7,
            "operator_name": operator_name,
            "metadata_json": metadata_json,
        },
        candidates=(),
        warnings=(),
        measurements=[
            {
                "row_order": 1,
                "header": "Feature 1",
                "ax": "X",
                "meas": 10.0,
                "status_code": "ok",
            }
        ],
        metadata_version="report_metadata_v1",
        raw_report_json={"parse_backend": "synthetic"},
    )
    return report_id, source_path


def _selection_result():
    metadata = CanonicalReportMetadata(
        parser_id="cmm_pdf_header_box",
        template_family="cmm_pdf_header_box",
        template_variant="synthetic_variant",
        metadata_confidence=0.99,
        reference="OCR-REF",
        reference_raw="OCR-REF",
        report_date="2024-01-02",
        report_time="12:34",
        part_name="OCR Part",
        revision="B",
        sample_number="8",
        sample_number_kind="explicit_sample_number",
        stats_count_raw="8",
        stats_count_int=8,
        operator_name="Synthetic Operator",
        comment="Synthetic comment",
        page_count=1,
        metadata_json={
            "field_sources": {
                "reference": "position_cell",
                "report_date": "position_cell",
                "report_time": "position_cell",
                "part_name": "position_cell",
                "revision": "position_cell",
                "sample_number": "explicit_sample_number",
                "stats_count_raw": "position_cell",
                "operator_name": "position_cell",
                "comment": "position_cell",
            }
        },
        warnings=(),
    )
    candidate = MetadataCandidate(
        field_name="revision",
        raw_value="B",
        normalized_value="B",
        source_type="position_cell",
        source_detail="synthetic_cell",
        page_number=1,
        region_name="header",
        label_text="REV",
        rule_id="synthetic_revision",
        confidence=0.99,
        evidence_text=None,
        selected=True,
    )
    return MetadataSelectionResult(metadata=metadata, candidates=(candidate,))


def test_discover_metadata_enrichment_work_finds_light_reports_and_skips_enriched(tmp_path):
    db_path = str(tmp_path / "reports.db")
    repository = ReportRepository(db_path)
    light_id, light_path = _persist_report(
        tmp_path,
        repository,
        name="light.pdf",
        metadata_json={
            "metadata_parsing_mode": "light",
            "header_ocr_skipped": "light_metadata_mode",
            "header_extraction_mode": "none",
        },
    )
    enriched_id, _ = _persist_report(
        tmp_path,
        repository,
        name="enriched.pdf",
        metadata_json={
            "metadata_enrichment": {"mode": "complete"},
            "header_extraction_mode": "ocr",
        },
        revision="B",
        operator_name="Synthetic Operator",
    )
    missing_ocr_id, missing_ocr_path = _persist_report(
        tmp_path,
        repository,
        name="missing-ocr-fields.pdf",
        metadata_json={"field_sources": {"reference": "filename_candidate"}},
    )
    false_positive_id, false_positive_path = _persist_report(
        tmp_path,
        repository,
        name="false-positive.pdf",
        metadata_json={"note": "metadata_enrichment appears here as ordinary text"},
        revision="C",
        operator_name="Synthetic Operator",
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE report_metadata SET report_time = '12:34', comment = 'Synthetic comment' WHERE report_id = ?",
            (enriched_id,),
        )
        connection.execute(
            "UPDATE report_metadata SET report_time = '12:34', comment = 'Synthetic comment' WHERE report_id = ?",
            (false_positive_id,),
        )
        connection.commit()

    work_items = discover_metadata_enrichment_work(db_path)

    assert work_items == [
        MetadataEnrichmentWorkItem(
            report_id=light_id,
            source_path=str(light_path.resolve()),
            sha256=work_items[0].sha256,
        ),
        MetadataEnrichmentWorkItem(
            report_id=missing_ocr_id,
            source_path=str(missing_ocr_path.resolve()),
            sha256=work_items[1].sha256,
        ),
        MetadataEnrichmentWorkItem(
            report_id=false_positive_id,
            source_path=str(false_positive_path.resolve()),
            sha256=work_items[2].sha256,
        ),
    ]


def test_enrich_existing_report_metadata_preserves_measurement_rows(tmp_path):
    db_path = str(tmp_path / "reports.db")
    repository = ReportRepository(db_path)
    report_id, report_path = _persist_report(
        tmp_path,
        repository,
        name="light.pdf",
        metadata_json={
            "field_sources": {
                "reference": "filename_candidate",
                "report_date": "filename_candidate",
            },
            "metadata_parsing_mode": "light",
        },
    )

    class _FakeParser:
        def __init__(self):
            self.metadata_parsing_mode = "light"
            self.open_modes = []
            self._metadata_selection_result = _selection_result()

        def open_report(self):
            self.open_modes.append(self.metadata_parsing_mode)

        def extract_metadata(self):
            return self._metadata_selection_result

    fake_parser = _FakeParser()

    def _parser_factory(_path, _db_file, connection=None):
        assert connection is not None
        return fake_parser

    with sqlite3.connect(db_path) as connection:
        enriched = enrich_existing_report_metadata(
            db_path,
            MetadataEnrichmentWorkItem(report_id=report_id, source_path=str(report_path), sha256="unused"),
            connection=connection,
            parser_factory=_parser_factory,
        )

    assert enriched is True
    assert fake_parser.open_modes == ["complete"]
    with sqlite3.connect(db_path) as connection:
        metadata_row = connection.execute(
            """
            SELECT reference, report_date, report_time, revision, operator_name, metadata_json
            FROM report_metadata
            WHERE report_id = ?
            """,
            (report_id,),
        ).fetchone()
        measurement_rows = connection.execute(
            "SELECT row_order, header, ax, meas FROM report_measurements WHERE report_id = ?",
            (report_id,),
        ).fetchall()
        raw_report_json = connection.execute(
            "SELECT raw_report_json FROM parsed_reports WHERE id = ?",
            (report_id,),
        ).fetchone()[0]

    assert metadata_row[:5] == ("LIGHT-REF", "2024-01-01", "12:34", "B", "Synthetic Operator")
    assert measurement_rows == [(1, "Feature 1", "X", 10.0)]
    metadata_json = json.loads(metadata_row[5])
    assert metadata_json["metadata_enrichment"]["mode"] == "complete"
    assert "reference" in metadata_json["metadata_enrichment"]["preserved_fields"]
    assert json.loads(raw_report_json)["metadata_enrichment"]["measurement_rows_preserved"] is True

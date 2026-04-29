import importlib.util
import json
import sqlite3
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script_module():
    script_path = REPO_ROOT / "scripts" / "diagnose_header_ocr_metadata.py"
    spec = importlib.util.spec_from_file_location("test_diagnose_header_ocr_metadata", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_classify_runtime_issue_reports_ocr_and_missing_model_modes():
    module = _load_script_module()

    assert (
        module._classify_runtime_issue(
            {"header_extraction_mode": "ocr"},
            {"reference": "position_cell"},
        )
        == "OCR ran in the app parser path."
    )
    assert "model files were missing" in module._classify_runtime_issue(
        {
            "header_extraction_mode": "none",
            "header_ocr_error": "header_ocr_models_missing:det.onnx",
        },
        {"reference": "filename_candidate"},
    )
    assert "disabled" in module._classify_runtime_issue(
        {
            "header_extraction_mode": "none",
            "header_ocr_error": "header_ocr_disabled",
        },
        {"reference": "filename_candidate"},
    )


def test_source_rows_for_sha_decodes_metadata_json(tmp_path):
    module = _load_script_module()
    db_path = tmp_path / "reports.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE source_files (
                id INTEGER PRIMARY KEY,
                absolute_path TEXT,
                sha256 TEXT,
                is_active INTEGER
            );
            CREATE TABLE parsed_reports (
                id INTEGER PRIMARY KEY,
                source_file_id INTEGER,
                parser_id TEXT,
                parser_version TEXT,
                template_family TEXT,
                template_variant TEXT,
                parse_status TEXT
            );
            CREATE TABLE report_metadata (
                report_id INTEGER,
                reference TEXT,
                report_date TEXT,
                sample_number TEXT,
                metadata_json TEXT
            );
            INSERT INTO source_files (id, absolute_path, sha256, is_active)
            VALUES (1, 'sample.pdf', 'abc123', 1);
            INSERT INTO parsed_reports (
                id, source_file_id, parser_id, parser_version, template_family,
                template_variant, parse_status
            )
            VALUES (
                2, 1, 'cmm_pdf_header_box', '1.1.0', 'cmm_pdf_header_box',
                'cmm_pdf_header_box_drawing_variant', 'parsed'
            );
            """
        )
        connection.execute(
            """
            INSERT INTO report_metadata (
                report_id, reference, report_date, sample_number, metadata_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                2,
                "VTST1001_001",
                "2020-01-28",
                "1",
                json.dumps({"header_extraction_mode": "ocr"}),
            ),
        )

    rows = module._source_rows_for_sha(db_path, "abc123")

    assert len(rows) == 1
    assert rows[0]["sha256"] == "abc123"
    assert rows[0]["metadata_json"] == {"header_extraction_mode": "ocr"}

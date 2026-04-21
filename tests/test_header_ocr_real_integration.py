from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


RUN_REAL_OCR_ENV = "METROLIZA_RUN_REAL_OCR"
SAMPLE_PDF_ENV = "METROLIZA_REAL_OCR_SAMPLE_PDF"
SAMPLE_DIR_ENV = "METROLIZA_REAL_OCR_REPORT_DIR"


def _missing_optional_dependencies() -> list[str]:
    required = ("rapidocr", "onnxruntime", "cv2", "pandas", "PyQt6")
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if importlib.util.find_spec("pymupdf") is None and importlib.util.find_spec("fitz") is None:
        missing.append("PyMuPDF")
    return missing


def _load_expected_headers() -> dict[str, dict[str, str]]:
    expected_path = Path("ocr_testing/expected_headers.json")
    with expected_path.open("r", encoding="utf-8") as handle:
        rows = json.load(handle)
    return {str(row["file"]): dict(row["expected"]) for row in rows}


def _resolve_sample_pdf(expected_by_file: dict[str, dict[str, str]]) -> Path:
    explicit_pdf = os.environ.get(SAMPLE_PDF_ENV)
    if explicit_pdf:
        return Path(explicit_pdf).expanduser().resolve()

    report_dir = Path(
        os.environ.get(
            SAMPLE_DIR_ENV,
            str(Path(__file__).resolve().parents[2] / "example_reports" / "extracted"),
        )
    ).expanduser()
    for file_name in expected_by_file:
        candidate = report_dir / file_name
        if candidate.is_file():
            return candidate.resolve()
    return report_dir / next(iter(expected_by_file))


@pytest.mark.integration
def test_real_rapidocr_extracts_expected_header_from_sample_pdf():
    if os.environ.get(RUN_REAL_OCR_ENV) != "1":
        pytest.skip(f"set {RUN_REAL_OCR_ENV}=1 to run real RapidOCR integration smoke")

    missing = _missing_optional_dependencies()
    if missing:
        pytest.skip(f"missing real OCR dependencies: {', '.join(missing)}")

    from modules.cmm_report_parser import CMMReportParser
    from scripts.validate_packaged_pdf_parser import validate_vendored_header_ocr_models

    validate_vendored_header_ocr_models()

    expected_by_file = _load_expected_headers()
    sample_pdf = _resolve_sample_pdf(expected_by_file)
    if not sample_pdf.is_file():
        pytest.skip(f"sample PDF not found: {sample_pdf}")

    expected = expected_by_file[sample_pdf.name]
    parser = CMMReportParser(str(sample_pdf), ":memory:")
    parser.open_report()
    metadata = parser.extract_metadata().metadata

    assert metadata.metadata_json.get("header_extraction_mode") == "ocr"
    assert metadata.metadata_json.get("header_ocr_error") is None
    assert metadata.reference == expected["reference"]
    assert metadata.report_date == expected["report_date"]
    assert metadata.report_time == expected["report_time"]
    assert metadata.operator_name == expected["operator_name"]

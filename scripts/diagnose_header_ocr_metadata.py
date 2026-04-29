"""Diagnose CMM header OCR metadata extraction for one PDF.

Usage:
  python scripts/diagnose_header_ocr_metadata.py <path-to-report.pdf>
  python scripts/diagnose_header_ocr_metadata.py <path-to-report.pdf> --db-file reports.sqlite
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the real CMMReportParser header OCR metadata path for one PDF and print "
            "the parser/module/model/database diagnostics needed to explain filename-only "
            "metadata extraction."
        )
    )
    parser.add_argument("pdf_path", help="PDF report to diagnose")
    parser.add_argument(
        "--db-file",
        help=(
            "Optional existing Metroliza SQLite database. When provided, the script also "
            "checks whether this PDF SHA already exists and shows stored metadata_json."
        ),
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of indented JSON.",
    )
    return parser


def _module_spec_summary(module_name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return {"available": False, "origin": None, "importable": False, "import_error": None}

    summary = {"available": True, "origin": spec.origin, "importable": True, "import_error": None}
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        summary["importable"] = False
        summary["import_error"] = f"{type(exc).__name__}: {exc}"
    return summary


def _json_loads_or_raw(value: str | None) -> Any:
    if value in (None, ""):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _source_rows_for_sha(db_file: Path, sha256_value: str) -> list[dict[str, Any]]:
    if not db_file.is_file():
        return []

    query = """
        SELECT
            sf.id AS source_file_id,
            sf.absolute_path,
            sf.sha256,
            sf.is_active,
            pr.id AS report_id,
            pr.parser_id,
            pr.parser_version,
            pr.template_family,
            pr.template_variant,
            pr.parse_status,
            rm.reference,
            rm.report_date,
            rm.sample_number,
            rm.metadata_json
        FROM source_files sf
        LEFT JOIN parsed_reports pr ON pr.source_file_id = sf.id
        LEFT JOIN report_metadata rm ON rm.report_id = pr.id
        WHERE sf.sha256 = ?
        ORDER BY pr.id DESC
    """
    with sqlite3.connect(db_file) as connection:
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(query, (sha256_value,)).fetchall()
        except sqlite3.Error as exc:
            return [{"error": f"{type(exc).__name__}: {exc}"}]

    return [
        {
            key: _json_loads_or_raw(row[key]) if key == "metadata_json" else row[key]
            for key in row.keys()
        }
        for row in rows
    ]


def _classify_runtime_issue(header_diagnostics: dict[str, Any], field_sources: dict[str, Any]) -> str:
    header_ocr_error = str(header_diagnostics.get("header_ocr_error") or "")
    extraction_mode = header_diagnostics.get("header_extraction_mode")
    source_values = {value for value in field_sources.values() if value}
    only_filename_or_empty = source_values.issubset({"filename_candidate"})

    if extraction_mode == "ocr":
        return "OCR ran in the app parser path."
    if "header_ocr_models_missing" in header_ocr_error:
        return "OCR did not run because one or more RapidOCR model files were missing."
    if "header_ocr_disabled" in header_ocr_error:
        return "OCR was disabled by METROLIZA_HEADER_OCR_BACKEND."
    if header_ocr_error:
        return f"OCR did not run or returned no items: {header_ocr_error}"
    if only_filename_or_empty:
        return "Only filename metadata was selected; header OCR/structured text did not contribute."
    return "Header metadata was selected without OCR mode; inspect field_sources and diagnostics."


def _run_parser_diagnostic(pdf_path: Path, db_file: str) -> dict[str, Any]:
    from modules.cmm_report_parser import CMMReportParser

    parser = CMMReportParser(str(pdf_path), db_file)
    parser.open_report()
    result = parser.extract_metadata()
    metadata = result.metadata
    field_sources = metadata.metadata_json.get("field_sources") or {}
    header_diagnostics = dict(parser._header_extraction_diagnostics or {})

    return {
        "verdict": _classify_runtime_issue(header_diagnostics, field_sources),
        "header_diagnostics": header_diagnostics,
        "header_items": [item.get("text") for item in parser._first_page_header_items],
        "metadata": {
            "reference": metadata.reference,
            "reference_raw": metadata.reference_raw,
            "part_name": metadata.part_name,
            "report_date": metadata.report_date,
            "report_time": metadata.report_time,
            "revision": metadata.revision,
            "stats_count_raw": metadata.stats_count_raw,
            "stats_count_int": metadata.stats_count_int,
            "sample_number": metadata.sample_number,
            "sample_number_kind": metadata.sample_number_kind,
            "operator_name": metadata.operator_name,
            "comment": metadata.comment,
            "template_family": metadata.template_family,
            "template_variant": metadata.template_variant,
            "metadata_confidence": metadata.metadata_confidence,
            "field_sources": field_sources,
            "warnings": [warning.code for warning in metadata.warnings],
        },
    }


def build_diagnostic_payload(pdf_path: Path, db_file: str | None = None) -> dict[str, Any]:
    from modules.header_ocr_backend import (
        default_rapidocr_latin_model_paths,
        default_rapidocr_model_dir,
        missing_rapidocr_latin_model_paths,
        rapidocr_latin_runtime_config_from_env,
    )
    from modules.report_repository import compute_sha256

    resolved_pdf = pdf_path.expanduser().resolve()
    if not resolved_pdf.is_file():
        raise FileNotFoundError(f"PDF not found: {resolved_pdf}")

    model_dir_override = os.getenv("METROLIZA_HEADER_OCR_MODEL_DIR") or None
    model_paths = default_rapidocr_latin_model_paths(model_dir_override)
    missing_models = missing_rapidocr_latin_model_paths(model_paths)
    try:
        runtime_config = rapidocr_latin_runtime_config_from_env()
        runtime_config_summary = {
            "engine": runtime_config.engine,
            "accelerator": runtime_config.accelerator,
            "params": runtime_config.params,
            "error": None,
        }
    except Exception as exc:
        runtime_config_summary = {
            "engine": None,
            "accelerator": None,
            "params": {},
            "error": f"{type(exc).__name__}: {exc}",
        }
    sha256_value = compute_sha256(resolved_pdf)

    db_rows: list[dict[str, Any]] = []
    resolved_db: str | None = None
    if db_file:
        db_path = Path(db_file).expanduser().resolve()
        resolved_db = str(db_path)
        db_rows = _source_rows_for_sha(db_path, sha256_value)

    parser_module = importlib.import_module("modules.cmm_report_parser")

    return {
        "environment": {
            "python_executable": sys.executable,
            "python_version": sys.version,
            "cwd": str(Path.cwd()),
            "repo_root": str(REPO_ROOT),
            "parser_module": getattr(parser_module, "__file__", None),
            "modules": {
                "rapidocr": _module_spec_summary("rapidocr"),
                "onnxruntime": _module_spec_summary("onnxruntime"),
                "cv2": _module_spec_summary("cv2"),
                "numpy": _module_spec_summary("numpy"),
                "fitz": _module_spec_summary("fitz"),
                "pymupdf": _module_spec_summary("pymupdf"),
            },
            "env": {
                "METROLIZA_HEADER_OCR_BACKEND": os.getenv("METROLIZA_HEADER_OCR_BACKEND"),
                "METROLIZA_HEADER_OCR_ENGINE": os.getenv("METROLIZA_HEADER_OCR_ENGINE"),
                "METROLIZA_HEADER_OCR_ACCELERATOR": os.getenv("METROLIZA_HEADER_OCR_ACCELERATOR"),
                "METROLIZA_HEADER_OCR_DEVICE_ID": os.getenv("METROLIZA_HEADER_OCR_DEVICE_ID"),
                "METROLIZA_HEADER_OCR_CACHE_DIR": os.getenv("METROLIZA_HEADER_OCR_CACHE_DIR"),
                "METROLIZA_HEADER_OCR_MODEL_DIR": os.getenv("METROLIZA_HEADER_OCR_MODEL_DIR"),
                "METROLIZA_HEADER_OCR_ZOOM": os.getenv("METROLIZA_HEADER_OCR_ZOOM"),
                "METROLIZA_HEADER_OCR_THREADS": os.getenv("METROLIZA_HEADER_OCR_THREADS"),
            },
            "header_ocr_runtime_config": runtime_config_summary,
            "default_rapidocr_model_dir": str(default_rapidocr_model_dir()),
            "missing_rapidocr_model_files": [str(path) for path in missing_models],
        },
        "input": {
            "pdf_path": str(resolved_pdf),
            "file_name": resolved_pdf.name,
            "sha256": sha256_value,
            "db_file": resolved_db,
        },
        "existing_database_rows": db_rows,
        "parser_run": _run_parser_diagnostic(resolved_pdf, db_file or ":memory:"),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_diagnostic_payload(Path(args.pdf_path), args.db_file)
    indent = None if args.compact else 2
    print(json.dumps(payload, ensure_ascii=False, indent=indent, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

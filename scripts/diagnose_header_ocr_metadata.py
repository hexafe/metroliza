"""Inspect one PDF and optional existing DB with safe OCR support JSON.

No document values, hashes, paths or database rows are published. Requested
inspection failure returns nonzero; absent optional metadata is an observation.
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import importlib
from pathlib import Path
import sqlite3
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

contract = importlib.import_module("scripts.ocr_diagnostic_contract")


def build_parser() -> contract.SafeArgumentParser:
    parser = contract.SafeArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", help="PDF to inspect without import or persistence")
    parser.add_argument(
        "--db-file", help="Optional existing SQLite DB; safe counts only, read-only"
    )
    parser.add_argument("--output", help="Optional atomic safe JSON file; cannot alias input")
    parser.add_argument("--compact", action="store_true", help="Write compact safe JSON")
    return parser


def _database_state(db_file: Path) -> tuple:
    # An immutable connection must never accept a concurrently changing source.
    if any(Path(str(db_file) + suffix).exists() for suffix in ("-wal", "-journal")):
        raise OSError("database_unreadable")
    state = db_file.stat()
    return (state.st_dev, state.st_ino, state.st_size, state.st_mtime_ns, state.st_ctime_ns)


def _source_rows_for_sha(db_file: Path, sha256_value: str | None) -> dict:
    if not db_file.is_file():
        return contract.row("database", "fail", "database_missing")
    try:
        db_file = db_file.resolve()
        # immutable prevents creation/mutation of WAL/SHM. A live WAL cannot be
        # safely interpreted this way, so refuse it instead of reporting stale rows.
        before = _database_state(db_file)
        uri = db_file.as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as connection:
            deadline = time.monotonic() + 5
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            try:
                connection.execute(
                    "SELECT sf.sha256, pr.source_file_id, rm.report_id, rm.metadata_json "
                    "FROM source_files sf LEFT JOIN parsed_reports pr ON pr.source_file_id=sf.id "
                    "LEFT JOIN report_metadata rm ON rm.report_id=pr.id LIMIT 0"
                )
            except sqlite3.Error:
                return contract.row("database", "fail", "schema_unsupported")
            count = 0
            if sha256_value is not None:
                count = connection.execute(
                    "SELECT count(*) FROM (SELECT 1 FROM source_files WHERE sha256=? LIMIT 1000000)",
                    (sha256_value,),
                ).fetchone()[0]
        if _database_state(db_file) != before:
            return contract.row("database", "fail", "database_unreadable")
        facts = {"matching_rows": count} if sha256_value is not None else {}
        return contract.row(
            "database",
            "pass",
            "no_matching_rows" if sha256_value is not None and count == 0 else "ok",
            **facts,
        )
    except (OSError, sqlite3.Error):
        return contract.row("database", "fail", "database_unreadable")


def _classify_runtime_issue(header_diagnostics: dict, field_sources: dict) -> str:
    error = header_diagnostics.get("header_ocr_error")
    if error == "header_ocr_disabled":
        return "ocr_disabled"
    if error in {"header_ocr_no_records", "header_ocr_no_header_items"}:
        return "ocr_no_records"
    if type(error) is str and error.startswith("DiagnosticAssetMissing:"):
        return "missing_models"
    if error:
        return "extraction_failed"
    return "ok" if any(field_sources.values()) else "metadata_absent"


def _run_parser_diagnostic(pdf_path: Path) -> dict:
    from metroliza.parsing.cmm_report_parser import CMMReportParser

    parser = CMMReportParser(str(pdf_path), ":memory:")
    parser.open_report()
    if not parser._page_count:
        return contract.row("pdf", "fail", "invalid_pdf")
    result = parser.extract_metadata()
    sources = result.metadata.metadata_json.get("field_sources") or {}
    diagnostics = parser._header_extraction_diagnostics or {}
    reason = _classify_runtime_issue(diagnostics, sources)
    mode = diagnostics.get("header_extraction_mode")
    if mode not in {"none", "words", "ocr"}:
        return contract.row("pdf", "fail", "protocol_error")
    selected = [value for value in sources.values() if value]
    filename = sum(value == "filename_candidate" for value in selected)
    header = sum(
        value in {"position_cell", "header_exact", "header_alias", "explicit_sample_number"}
        for value in selected
    )
    return contract.row(
        "pdf",
        "fail" if reason in {"extraction_failed", "missing_models"} else "pass",
        reason,
        extraction_mode=mode,
        metadata_fields=min(len(selected), 1000000),
        filename_fields=filename,
        header_fields=header,
        other_fields=len(selected) - filename - header,
        header_items=min(len(parser._first_page_header_items), 1000000),
        page_count=min(parser._page_count, 1000000),
    )


def _optional_pdf_digest(value: str | None) -> str | None:
    if value is not None:
        try:
            with Path(value).expanduser().resolve().open("rb") as stream:
                if stream.read(5) == b"%PDF-":
                    stream.seek(0)
                    return hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError:
            pass
    return None


def run_input_check(check_id: str, request: dict) -> dict:
    if check_id == "database":
        # The PDF worker owns source validity. An unavailable source hash must
        # not hide this separately requested database's existence/schema result.
        return _source_rows_for_sha(
            Path(request["database"]).expanduser().resolve(),
            _optional_pdf_digest(request.get("pdf")),
        )
    pdf = Path(request["pdf"]).expanduser().resolve() if request.get("pdf") is not None else None
    if pdf is not None:
        try:
            with pdf.open("rb") as stream:
                prefix = stream.read(5)
        except OSError:
            return contract.row(check_id, "fail", "input_unreadable")
        if prefix != b"%PDF-":
            return contract.row(check_id, "fail", "invalid_pdf")
    try:
        from metroliza.parsing.header_ocr_backend import rapidocr_latin_runtime_config_from_env

        contract.prevent_rapidocr_downloads(rapidocr_latin_runtime_config_from_env().engine)
        return _run_parser_diagnostic(pdf)
    except BaseException:
        return contract.row("pdf", "fail", "extraction_failed")


def build_diagnostic_payload(pdf_path: Path, db_file: str | None = None) -> dict:
    from scripts.windows_ocr_runtime_diagnostics import build_payload

    return build_payload(pdf_path, db_file)


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except ValueError:
        return contract.publish(
            contract.payload([contract.row("diagnostic", "fail", "invalid_arguments")]),
            None,
            True,
            [],
        )
    from scripts.windows_ocr_runtime_diagnostics import main as runtime_main

    runtime_args = ["--pdf", args.pdf_path]
    if args.db_file is not None:
        runtime_args += ["--db-file", args.db_file]
    if args.output is not None:
        runtime_args += ["--output", args.output]
    if args.compact:
        runtime_args += ["--compact"]
    return runtime_main(runtime_args)


if __name__ == "__main__":
    raise SystemExit(main())

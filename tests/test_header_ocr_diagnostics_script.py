from contextlib import closing
import importlib.util
import json
import sqlite3
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script_module():
    script_path = REPO_ROOT / "scripts" / "diagnose_header_ocr_metadata.py"
    spec = importlib.util.spec_from_file_location("test_diagnose_header_ocr_metadata", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_classify_runtime_issue_reports_controlled_observations():
    module = _load_script_module()
    assert (
        module._classify_runtime_issue(
            {"header_extraction_mode": "ocr"}, {"reference": "position_cell"}
        )
        == "ok"
    )
    assert (
        module._classify_runtime_issue(
            {"header_ocr_error": "header_ocr_models_missing:private.onnx"}, {}
        )
        == "extraction_failed"
    )
    assert (
        module._classify_runtime_issue({"header_ocr_error": "header_ocr_disabled"}, {})
        == "ocr_disabled"
    )
    assert module._classify_runtime_issue({}, {}) == "metadata_absent"


def test_source_rows_for_sha_returns_only_safe_count(tmp_path):
    module = _load_script_module()
    db_path = tmp_path / "reports.sqlite"
    with closing(sqlite3.connect(db_path)) as connection, connection:
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

    assert rows["status"] == "pass"
    assert rows["facts"] == {"matching_rows": 1}
    assert "abc123" not in json.dumps(rows)
    assert "VTST1001" not in json.dumps(rows)


def test_database_missing_schema_no_match_and_readonly(tmp_path):
    module = _load_script_module()
    database = tmp_path / ("synthetic # ź.sqlite" if os.name == "nt" else "synthetic ? # ź.sqlite")
    assert module._source_rows_for_sha(database, None)["reason"] == "database_missing"
    assert not database.exists()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE irrelevant(value TEXT)")
    before = database.read_bytes()
    assert module._source_rows_for_sha(database, None)["reason"] == "schema_unsupported"
    assert database.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [database.name]


def test_database_sidecar_is_not_created_modified_or_ignored(tmp_path):
    module = _load_script_module()
    database = tmp_path / "source.sqlite"
    database.write_bytes(b"synthetic")
    sidecar = Path(str(database) + "-wal")
    sidecar.write_bytes(b"synthetic WAL")
    assert module._source_rows_for_sha(database, None)["reason"] == "database_unreadable"
    assert database.read_bytes() == b"synthetic"
    assert sidecar.read_bytes() == b"synthetic WAL"


def test_metadata_sources_match_actual_selector_and_empty_is_absent(monkeypatch):
    from types import SimpleNamespace
    from metroliza.parsing import cmm_report_parser

    module = _load_script_module()
    sources = {
        "reference": "header_exact",
        "report_date": "header_alias",
        "sample_number": "explicit_sample_number",
    }

    class Parser:
        _page_count = 1
        _header_extraction_diagnostics = {"header_extraction_mode": "words"}
        _first_page_header_items = []

        def __init__(self, path, database):
            assert database == ":memory:"

        def open_report(self):
            pass

        def extract_metadata(self):
            return SimpleNamespace(
                metadata=SimpleNamespace(metadata_json={"field_sources": sources})
            )

    monkeypatch.setattr(cmm_report_parser, "CMMReportParser", Parser)
    result = module._run_parser_diagnostic(Path("synthetic.pdf"))
    assert result["facts"]["header_fields"] == 3
    sources.clear()
    sources.update({"reference": None, "report_date": None})
    result = module._run_parser_diagnostic(Path("synthetic.pdf"))
    assert result["reason"] == "metadata_absent"
    assert result["facts"]["metadata_fields"] == 0


def test_database_changes_during_open_cannot_pass(tmp_path, monkeypatch):
    module = _load_script_module()
    database = tmp_path / "source.sqlite"
    connect = sqlite3.connect
    with closing(connect(database)) as connection:
        connection.executescript("CREATE TABLE source_files(id INTEGER, sha256 TEXT);"
                                 "CREATE TABLE parsed_reports(id INTEGER, source_file_id INTEGER);"
                                 "CREATE TABLE report_metadata(report_id INTEGER, metadata_json TEXT);")
    for mode in ("wal", "main"):
        with closing(connect(database)) as writer:
            writer.execute("PRAGMA journal_mode=DELETE")

            def racing_connect(*args, **kwargs):
                if mode == "wal":
                    writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("INSERT INTO source_files VALUES(1, 'SYNTHETIC_DB_CHANGE')")
                writer.commit()
                return connect(*args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(module.sqlite3, "connect", racing_connect)
                result = module._source_rows_for_sha(database, "SYNTHETIC_DB_CHANGE")
            assert result["status"] == "fail", (mode, result)
            assert result["reason"] == "database_unreadable"
            assert "SYNTHETIC_DB_CHANGE" not in json.dumps(result)


def test_database_symlink_checks_target_sidecars(tmp_path):
    import pytest

    module = _load_script_module()
    target = tmp_path / "target.sqlite"
    alias = tmp_path / "alias.sqlite"
    with closing(sqlite3.connect(target)) as writer:
        writer.execute("CREATE TABLE source_files(id INTEGER, sha256 TEXT)")
        writer.commit()
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO source_files VALUES(1, 'SYNTHETIC_WAL')")
        writer.commit()
        try:
            alias.symlink_to(target)
        except OSError:
            pytest.skip("Disposable symlink requires platform permission")
        assert module._source_rows_for_sha(alias, None)["reason"] == "database_unreadable"

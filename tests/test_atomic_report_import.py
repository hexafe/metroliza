from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3
from threading import Event

import pytest

from metroliza.reports.db import connect_sqlite
from metroliza.reports.report_repository import (
    ReportImportDisposition,
    ReportImportPolicy,
    ReportRepository,
    compute_sha256,
)
from metroliza.reports.report_schema import ensure_report_schema


def _payload(marker: str) -> dict[str, object]:
    return {
        "parser_id": "synthetic-parser",
        "parser_version": "1",
        "template_family": "synthetic",
        "parse_status": "parsed_with_warnings",
        "metadata": {
            "reference": marker,
            "metadata_json": {
                "marker": marker,
                "metadata_parsing_mode": "complete",
                "header_extraction_mode": "embedded_text",
                "field_sources": {
                    "reference": marker,
                    "report_date": marker,
                    "stats_count_raw": marker,
                },
            },
        },
        "candidates": (
            {
                "field_name": "reference",
                "raw_value": marker,
                "normalized_value": marker,
                "source_type": "synthetic",
                "rule_id": marker,
                "confidence": 1.0,
                "selected": True,
            },
        ),
        "warnings": (
            {
                "code": marker,
                "severity": "warning",
                "message": marker,
                "details": {"marker": marker},
            },
        ),
        "measurements": (
            {
                "row_order": 1,
                "header": marker,
                "ax": "X",
                "nominal": 1.0,
                "meas": 1.0,
                "outtol": 0.0,
                "status_code": "ok",
                "raw_measurement_json": {"marker": marker},
            },
        ),
        "metadata_version": "synthetic-v1",
        "raw_report_json": {"writer": marker},
    }


def _normalized_snapshot(database) -> dict[str, list[tuple[object, ...]]]:
    table_columns = {
        "source_files": "id, sha256, file_size_bytes, source_format, is_active",
        "source_file_locations": (
            "id, source_file_id, absolute_path, directory_path, file_name, file_extension, "
            "file_modified_at, discovered_at, is_active"
        ),
        "parsed_reports": (
            "id, source_file_id, parser_id, parser_version, template_family, template_variant, "
            "parse_status, page_count, measurement_count, has_nok, nok_count, "
            "metadata_confidence, identity_hash, raw_report_json, created_at, updated_at"
        ),
        "report_metadata": "*",
        "report_metadata_candidates": "*",
        "report_metadata_warnings": "*",
        "report_measurements": "*",
        "report_parse_state": "*",
    }
    with closing(sqlite3.connect(database)) as connection:
        return {
            table: connection.execute(
                f"SELECT {columns} FROM {table} ORDER BY 1"
            ).fetchall()
            for table, columns in table_columns.items()
        }


def _run_ordered_race(database, source):
    digest = compute_sha256(source)
    writer_a_reserved = Event()
    release_writer_a = Event()
    writer_b_started = Event()

    class OrderedRepository(ReportRepository):
        def __init__(self, *args, marker: str, **kwargs):
            super().__init__(*args, **kwargs)
            self.marker = marker

        def ensure_schema(self) -> None:
            return None

        def _accepted_report_id(self, cursor, current_digest, policy):
            if self.marker == "A":
                writer_a_reserved.set()
                assert release_writer_a.wait(timeout=10)
            return super()._accepted_report_id(cursor, current_digest, policy)

    def import_marker(marker: str):
        if marker == "B":
            writer_b_started.set()
        with closing(connect_sqlite(str(database), timeout_s=10)) as connection:
            repository = OrderedRepository(
                str(database),
                connection=connection,
                marker=marker,
            )
            return repository.import_report_if_absent(
                source_path=source,
                source_sha256=digest,
                **_payload(marker),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(import_marker, "A")
        assert writer_a_reserved.wait(timeout=10)
        future_b = executor.submit(import_marker, "B")
        assert writer_b_started.wait(timeout=10)
        release_writer_a.set()
        return future_a.result(timeout=10), future_b.result(timeout=10)


def test_two_connection_import_race_has_one_import_and_one_noop(tmp_path):
    source = tmp_path / "synthetic.report"
    source.write_bytes(b"atomic-race")
    database = tmp_path / "reports.sqlite3"
    ensure_report_schema(str(database))

    outcomes = _run_ordered_race(database, source)

    assert outcomes == (
        ReportImportDisposition.IMPORTED,
        ReportImportDisposition.ALREADY_PRESENT,
    )
    snapshot = _normalized_snapshot(database)
    assert json.loads(snapshot["parsed_reports"][0][13]) == {"writer": "A"}
    assert snapshot["report_metadata"][0][1] == "A"
    assert snapshot["report_metadata_candidates"][0][10] == "A"
    assert snapshot["report_metadata_warnings"][0][2] == "A"
    assert snapshot["report_measurements"][0][4] == "A"
    assert snapshot["report_parse_state"][0][4:7] == ("A", "A", "A")


def test_existing_source_identity_without_report_is_completed_once(tmp_path):
    source = tmp_path / "synthetic.report"
    source.write_bytes(b"incomplete-source")
    database = tmp_path / "reports.sqlite3"
    ensure_report_schema(str(database))
    ReportRepository(str(database)).upsert_source_file(source)

    outcomes = _run_ordered_race(database, source)

    assert outcomes.count(ReportImportDisposition.IMPORTED) == 1
    assert outcomes.count(ReportImportDisposition.ALREADY_PRESENT) == 1
    snapshot = _normalized_snapshot(database)
    assert len(snapshot["source_files"]) == 1
    assert len(snapshot["parsed_reports"]) == 1


def test_duplicate_import_is_an_exact_noop_without_delete_or_update(tmp_path):
    source = tmp_path / "synthetic.report"
    source.write_bytes(b"no-clobber")
    database = tmp_path / "reports.sqlite3"
    repository = ReportRepository(str(database))
    assert repository.import_report_if_absent(
        source_path=source,
        **_payload("accepted"),
    ) is ReportImportDisposition.IMPORTED
    before = _normalized_snapshot(database)

    statements: list[str] = []
    with closing(connect_sqlite(str(database))) as connection:
        connection.set_trace_callback(statements.append)
        duplicate_repository = ReportRepository(str(database), connection=connection)
        outcome = duplicate_repository.import_report_if_absent(
            source_path=source,
            **_payload("duplicate"),
        )

    transaction_statements = statements[statements.index("BEGIN IMMEDIATE") :]
    mutations = [
        statement
        for statement in transaction_statements
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
    ]
    assert outcome is ReportImportDisposition.ALREADY_PRESENT
    assert mutations == []
    assert _normalized_snapshot(database) == before


@pytest.mark.parametrize("failure_stage", ["metadata", "candidates", "warnings", "measurements"])
def test_import_child_failure_rolls_back_new_source_and_complete_graph(
    tmp_path,
    failure_stage,
):
    source = tmp_path / f"{failure_stage}.report"
    source.write_bytes(failure_stage.encode())
    database = tmp_path / "reports.sqlite3"
    ensure_report_schema(str(database))

    class FailingRepository(ReportRepository):
        def ensure_schema(self) -> None:
            return None

        def _replace_report_metadata(self, cursor, *args, **kwargs):
            super()._replace_report_metadata(cursor, *args, **kwargs)
            if failure_stage == "metadata":
                raise RuntimeError("synthetic metadata failure")

        def _replace_metadata_candidates(self, cursor, *args, **kwargs):
            super()._replace_metadata_candidates(cursor, *args, **kwargs)
            if failure_stage == "candidates":
                raise RuntimeError("synthetic candidate failure")

        def _replace_metadata_warnings(self, cursor, *args, **kwargs):
            super()._replace_metadata_warnings(cursor, *args, **kwargs)
            if failure_stage == "warnings":
                raise RuntimeError("synthetic warning failure")

        def _replace_measurements(self, cursor, *args, **kwargs):
            super()._replace_measurements(cursor, *args, **kwargs)
            if failure_stage == "measurements":
                raise RuntimeError("synthetic measurement failure")

    with pytest.raises(RuntimeError, match=f"synthetic {failure_stage.rstrip('s')}.*failure"):
        FailingRepository(str(database)).import_report_if_absent(
            source_path=source,
            **_payload("failing"),
        )

    snapshot = _normalized_snapshot(database)
    assert all(rows == [] for rows in snapshot.values())


def test_deliberate_replacement_api_still_replaces_existing_graph(tmp_path):
    source = tmp_path / "synthetic.report"
    source.write_bytes(b"explicit-replacement")
    database = tmp_path / "reports.sqlite3"
    repository = ReportRepository(str(database))
    repository.import_report_if_absent(source_path=source, **_payload("before"))

    report_id = repository.replace_existing_report(source_path=source, **_payload("after"))

    snapshot = _normalized_snapshot(database)
    assert report_id == snapshot["parsed_reports"][0][0]
    assert json.loads(snapshot["parsed_reports"][0][13]) == {"writer": "after"}
    assert snapshot["report_measurements"][0][4] == "after"


def test_complete_mode_refreshes_incomplete_cmm_then_treats_it_as_present(tmp_path):
    source = tmp_path / "synthetic.report"
    source.write_bytes(b"mode-specific-refresh")
    database = tmp_path / "reports.sqlite3"
    repository = ReportRepository(str(database))
    incomplete = _payload("incomplete")
    incomplete["parser_id"] = "cmm_pdf_header_box"
    incomplete["parser_version"] = "1.1.0"
    incomplete["metadata"] = {
        "reference": "incomplete",
        "metadata_json": {
            "metadata_parsing_mode": "light",
            "header_extraction_mode": "none",
            "field_sources": {
                "reference": "filename_candidate",
                "report_date": "filename_candidate",
                "stats_count_raw": "filename_candidate",
            },
        },
    }
    repository.replace_existing_report(source_path=source, **incomplete)
    policy = ReportImportPolicy(
        metadata_parsing_mode="complete",
        refreshable_parser_id="cmm_pdf_header_box",
        refreshable_parser_version="1.1.0",
    )

    complete = _payload("complete")
    complete["parser_id"] = "cmm_pdf_header_box"
    complete["parser_version"] = "1.1.0"
    duplicate = _payload("duplicate")
    duplicate["parser_id"] = "cmm_pdf_header_box"
    duplicate["parser_version"] = "1.1.0"
    first = repository.import_report_if_absent(
        source_path=source,
        import_policy=policy,
        **complete,
    )
    second = repository.import_report_if_absent(
        source_path=source,
        import_policy=policy,
        **duplicate,
    )

    assert first is ReportImportDisposition.IMPORTED
    assert second is ReportImportDisposition.ALREADY_PRESENT
    assert json.loads(_normalized_snapshot(database)["parsed_reports"][0][13]) == {
        "writer": "complete"
    }


def test_final_digest_recheck_inside_transaction_rolls_back_report_graph(tmp_path):
    source = tmp_path / "synthetic.report"
    source.write_bytes(b"reviewed")
    database = tmp_path / "reports.sqlite3"
    original_digest = compute_sha256(source)

    class MutatingSchemaRepository(ReportRepository):
        def ensure_schema(self) -> None:
            super().ensure_schema()
            source.write_bytes(b"changed-after-precheck")

    with pytest.raises(ValueError, match="final source digest"):
        MutatingSchemaRepository(str(database)).import_report_if_absent(
            source_path=source,
            source_sha256=original_digest,
            **_payload("stale"),
        )

    snapshot = _normalized_snapshot(database)
    assert all(rows == [] for rows in snapshot.values())


def test_locked_import_retry_is_bounded(tmp_path, monkeypatch):
    source = tmp_path / "synthetic.report"
    source.write_bytes(b"bounded-lock")
    database = tmp_path / "reports.sqlite3"
    ensure_report_schema(str(database))
    retry_delays: list[float] = []
    monkeypatch.setattr("metroliza.reports.db.time.sleep", retry_delays.append)

    with closing(sqlite3.connect(database, timeout=0)) as lock_connection, closing(
        sqlite3.connect(database, timeout=0)
    ) as contender_connection:
        lock_connection.execute("BEGIN IMMEDIATE")
        repository = ReportRepository(str(database), connection=contender_connection)
        repository.ensure_schema = lambda: None
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            repository.import_report_if_absent(
                source_path=source,
                **_payload("contender"),
            )

    assert retry_delays == [0.05, 0.05]


def test_atomic_import_migrates_legacy_active_owners_before_duplicate_noop(tmp_path):
    source = tmp_path / "synthetic.report"
    source.write_bytes(b"legacy-owners")
    database = tmp_path / "reports.sqlite3"
    repository = ReportRepository(str(database))
    repository.import_report_if_absent(source_path=source, **_payload("accepted"))
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DROP INDEX idx_source_file_locations_active_path_unique")
        connection.execute("DELETE FROM app_schema WHERE key = 'source_location_ownership_version'")
        connection.execute(
            "INSERT INTO source_files (sha256, source_format, discovered_at) "
            "VALUES ('synthetic-old-owner', 'pdf', '2000-01-01')"
        )
        connection.execute(
            "INSERT INTO source_file_locations "
            "(source_file_id, absolute_path, directory_path, file_name, file_extension, "
            "discovered_at) SELECT last_insert_rowid(), absolute_path, directory_path, "
            "file_name, file_extension, '2000-01-01' FROM source_file_locations LIMIT 1"
        )
        connection.commit()
    before = _normalized_snapshot(database)
    for _ in range(2):
        assert repository.import_report_if_absent(
            source_path=source, **_payload("duplicate")
        ) is ReportImportDisposition.ALREADY_PRESENT
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute(
                "SELECT value FROM app_schema WHERE key = 'source_location_ownership_version'"
            ).fetchone() == ("1",)
            assert connection.execute(
                "SELECT COUNT(*) FROM source_file_locations WHERE is_active = 1"
            ).fetchone() == (1,)
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("UPDATE source_file_locations SET is_active = 1")
        after = _normalized_snapshot(database)
        assert {k: v for k, v in after.items() if k != "source_file_locations"} == {
            k: v for k, v in before.items() if k != "source_file_locations"
        }


@pytest.mark.parametrize("damage", [
    "current", "missing-marker", "stale-marker", "missing-index", "old-main-version",
    "wrong-nonunique", "wrong-column", "wrong-predicate",
])
@pytest.mark.parametrize("shared_connection", [False, True])
def test_schema_readiness_is_readonly_and_existing_migration_is_idempotent(
    tmp_path, monkeypatch, damage, shared_connection
):
    from metroliza.reports.report_schema import is_report_schema_ready

    source = tmp_path / "synthetic.report"
    source.write_bytes(b"schema-readiness")
    database = tmp_path / "reports.sqlite3"
    ReportRepository(str(database)).import_report_if_absent(source_path=source, **_payload("accepted"))
    with closing(connect_sqlite(str(database))) as connection:
        if damage == "missing-marker":
            connection.execute("DELETE FROM app_schema WHERE key = 'source_location_ownership_version'")
        elif damage in ("stale-marker", "old-main-version"):
            key = "schema_version" if damage == "old-main-version" else "source_location_ownership_version"
            connection.execute("UPDATE app_schema SET value = '0' WHERE key = ?", (key,))
        elif damage != "current":
            connection.execute("DROP INDEX idx_source_file_locations_active_path_unique")
            wrong_statements = {
                "wrong-nonunique": "CREATE INDEX idx_source_file_locations_active_path_unique "
                                   "ON source_file_locations(absolute_path) WHERE is_active = 1",
                "wrong-column": "CREATE UNIQUE INDEX idx_source_file_locations_active_path_unique "
                                "ON source_file_locations(file_name) WHERE is_active = 1",
                "wrong-predicate": "CREATE UNIQUE INDEX idx_source_file_locations_active_path_unique "
                                   "ON source_file_locations(absolute_path) WHERE is_active = 0",
            }
            if damage in wrong_statements:
                connection.execute(wrong_statements[damage])
        connection.commit()
        before = _normalized_snapshot(database)
        statements = []
        connection.set_trace_callback(statements.append)
        assert is_report_schema_ready(connection) is (damage == "current")
        assert not connection.in_transaction
        assert all(sql.startswith(("SELECT", "PRAGMA")) for sql in statements)
        repository = ReportRepository(str(database), connection=connection if shared_connection else None)
        ensure_calls = []
        original_ensure = repository.ensure_schema

        def record_ensure():
            ensure_calls.append(True)
            original_ensure()

        monkeypatch.setattr(repository, "ensure_schema", record_ensure)
        for _ in range(2):
            if damage.startswith("wrong-"):
                with pytest.raises(RuntimeError, match="schema is not ready"):
                    repository.import_report_if_absent(source_path=source, **_payload("duplicate"))
                assert not is_report_schema_ready(connection)
            else:
                assert repository.import_report_if_absent(
                    source_path=source, **_payload("duplicate")
                ) is ReportImportDisposition.ALREADY_PRESENT
                assert is_report_schema_ready(connection)
            assert _normalized_snapshot(database) == before
        assert len(ensure_calls) == (2 if damage.startswith("wrong-") else int(damage != "current"))


def test_digest_mismatch_precedes_schema_probe_and_database_creation(tmp_path, monkeypatch):
    source = tmp_path / "synthetic.report"
    source.write_bytes(b"current")
    database = tmp_path / "absent.sqlite3"
    repository = ReportRepository(str(database))

    def forbidden_schema_probe():
        raise AssertionError("digest rejection must precede all schema work")

    monkeypatch.setattr(repository, "_ensure_import_schema", forbidden_schema_probe)
    with pytest.raises(ValueError, match="digest"):
        repository.import_report_if_absent(
            source_path=source, source_sha256="0" * 64, **_payload("stale")
        )
    assert not database.exists()

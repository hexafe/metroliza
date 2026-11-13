"""The import's schema-readiness probe is reused only while its evidence is unchanged."""

from __future__ import annotations

from contextlib import closing
import sqlite3

import pytest

from metroliza.reports import report_schema
from metroliza.reports.db import connect_sqlite, lazy_sqlite_connection_scope
from metroliza.reports.report_repository import ReportImportDisposition, ReportRepository
from metroliza.reports.report_schema import (
    ensure_report_schema,
    is_report_schema_ready,
    is_report_schema_ready_cached,
)
from tests.test_atomic_report_import import _payload


def _count_full_checks(monkeypatch):
    calls = []
    original = report_schema.is_report_schema_ready

    def counted(connection):
        calls.append(True)
        return original(connection)

    monkeypatch.setattr(report_schema, "is_report_schema_ready", counted)
    return calls


def _make_source(tmp_path, name, content):
    source = tmp_path / name
    source.write_bytes(content)
    return source


def test_positive_verdict_is_reused_and_matches_the_full_check(tmp_path, monkeypatch):
    database = tmp_path / "reports.sqlite3"
    ensure_report_schema(str(database))
    calls = _count_full_checks(monkeypatch)
    with lazy_sqlite_connection_scope(str(database)) as connection:
        for _ in range(5):
            assert is_report_schema_ready_cached(connection) is True
            assert is_report_schema_ready(connection) is True
        assert len(calls) == 1  # only the first probe ran the full check


@pytest.mark.parametrize(
    "damage",
    ["app_marker_deleted", "app_marker_stale", "index_replaced", "view_dropped", "unrelated_ddl"],
)
def test_change_by_another_connection_is_detected_before_the_next_probe(
    tmp_path, monkeypatch, damage
):
    database = tmp_path / "reports.sqlite3"
    ensure_report_schema(str(database))
    calls = _count_full_checks(monkeypatch)
    with lazy_sqlite_connection_scope(str(database)) as connection:
        assert is_report_schema_ready_cached(connection) is True
        before = len(calls)
        with closing(connect_sqlite(str(database))) as other:
            if damage == "app_marker_deleted":
                other.execute("DELETE FROM app_schema WHERE key = 'source_location_ownership_version'")
            elif damage == "app_marker_stale":
                other.execute("UPDATE app_schema SET value = '0' WHERE key = 'schema_version'")
            elif damage == "index_replaced":
                other.execute("DROP INDEX idx_source_file_locations_active_path_unique")
                other.execute(
                    "CREATE UNIQUE INDEX idx_source_file_locations_active_path_unique "
                    "ON source_file_locations(file_name) WHERE is_active = 1"
                )
            elif damage == "view_dropped":
                name = other.execute("SELECT name FROM sqlite_master WHERE type = 'view'").fetchone()[0]
                other.execute(f"DROP VIEW {name}")
            else:
                other.execute("CREATE TABLE unrelated_probe (id INTEGER)")
            other.commit()
        expected = is_report_schema_ready(connection)
        assert expected is (damage == "unrelated_ddl")
        assert is_report_schema_ready_cached(connection) is expected
        assert len(calls) == before + 1, "the cached probe must run the full check again"


def test_negative_verdict_is_never_stored(tmp_path, monkeypatch):
    database = tmp_path / "reports.sqlite3"
    ensure_report_schema(str(database))
    with closing(connect_sqlite(str(database))) as other:
        other.execute("UPDATE app_schema SET value = '0' WHERE key = 'schema_version'")
        other.commit()
    calls = _count_full_checks(monkeypatch)
    with lazy_sqlite_connection_scope(str(database)) as connection:
        assert is_report_schema_ready_cached(connection) is False
        assert is_report_schema_ready_cached(connection) is False
        assert len(calls) == 2
        # Repair by a third party: the next probe must see it and may then store it.
        with closing(connect_sqlite(str(database))) as other:
            other.execute("UPDATE app_schema SET value = 'report_metadata_v1' WHERE key = 'schema_version'")
            other.commit()
        assert is_report_schema_ready_cached(connection) is True
        assert is_report_schema_ready_cached(connection) is True
        assert len(calls) == 3


def test_change_through_the_same_connection_is_detected(tmp_path, monkeypatch):
    database = tmp_path / "reports.sqlite3"
    ensure_report_schema(str(database))
    calls = _count_full_checks(monkeypatch)
    with lazy_sqlite_connection_scope(str(database)) as connection:
        assert is_report_schema_ready_cached(connection) is True
        connection.execute("UPDATE app_schema SET value = '0' WHERE key = 'schema_version'")
        connection.commit()
        assert is_report_schema_ready_cached(connection) is False
        connection.execute("UPDATE app_schema SET value = 'report_metadata_v1' WHERE key = 'schema_version'")
        connection.commit()
        assert is_report_schema_ready_cached(connection) is True
        assert len(calls) == 3


def test_ensure_schema_drops_the_stored_verdict(tmp_path, monkeypatch):
    database = tmp_path / "reports.sqlite3"
    ensure_report_schema(str(database))
    with lazy_sqlite_connection_scope(str(database)) as connection:
        assert is_report_schema_ready_cached(connection) is True
        calls = _count_full_checks(monkeypatch)
        ReportRepository(str(database), connection=connection).ensure_schema()
        assert is_report_schema_ready_cached(connection) is True
        assert len(calls) == 1


def test_plain_sqlite_connection_is_checked_in_full_every_time(tmp_path, monkeypatch):
    database = tmp_path / "reports.sqlite3"
    ensure_report_schema(str(database))
    calls = _count_full_checks(monkeypatch)
    with closing(sqlite3.connect(database)) as connection:
        for _ in range(3):
            assert is_report_schema_ready_cached(connection) is True
        assert len(calls) == 3


def test_schema_damaged_by_another_connection_mid_import_is_repaired_like_before(
    tmp_path, monkeypatch
):
    """Same outcome as the uncached probe: damage is seen before the next persist."""

    database = tmp_path / "reports.sqlite3"
    first = _make_source(tmp_path, "first.report", b"first")
    second = _make_source(tmp_path, "second.report", b"second")
    third = _make_source(tmp_path, "third.report", b"third")
    ensure_calls = []
    with lazy_sqlite_connection_scope(str(database)) as connection:
        repository = ReportRepository(str(database), connection=connection)
        original_ensure = repository.ensure_schema

        def recording_ensure():
            ensure_calls.append(True)
            original_ensure()

        monkeypatch.setattr(repository, "ensure_schema", recording_ensure)
        assert repository.import_report_if_absent(
            source_path=first, **_payload("first")
        ) is ReportImportDisposition.IMPORTED
        assert len(ensure_calls) == 1  # created the schema

        assert repository.import_report_if_absent(
            source_path=second, **_payload("second")
        ) is ReportImportDisposition.IMPORTED
        assert len(ensure_calls) == 1  # ready, no schema work

        with closing(connect_sqlite(str(database))) as other:
            other.execute("DELETE FROM app_schema WHERE key = 'source_location_ownership_version'")
            other.commit()
        assert repository._import_schema_is_ready() is False
        assert repository.import_report_if_absent(
            source_path=third, **_payload("third")
        ) is ReportImportDisposition.IMPORTED
        assert len(ensure_calls) == 2  # the existing migration repaired it first
        assert is_report_schema_ready(connection)
    with closing(sqlite3.connect(database)) as check:
        assert check.execute("SELECT COUNT(*) FROM parsed_reports").fetchone() == (3,)


def test_schema_dropped_by_another_connection_mid_import_fails_closed_like_before(tmp_path):
    database = tmp_path / "reports.sqlite3"
    first = _make_source(tmp_path, "first.report", b"first")
    second = _make_source(tmp_path, "second.report", b"second")
    with lazy_sqlite_connection_scope(str(database)) as connection:
        repository = ReportRepository(str(database), connection=connection)
        repository.import_report_if_absent(source_path=first, **_payload("first"))
        assert repository._import_schema_is_ready() is True
        with closing(connect_sqlite(str(database))) as other:
            other.execute("DROP INDEX idx_source_file_locations_active_path_unique")
            other.execute(
                "CREATE UNIQUE INDEX idx_source_file_locations_active_path_unique "
                "ON source_file_locations(file_name) WHERE is_active = 1"
            )
            other.commit()
        assert repository._import_schema_is_ready() is False
        with pytest.raises(RuntimeError, match="schema is not ready"):
            repository.import_report_if_absent(source_path=second, **_payload("second"))
    with closing(sqlite3.connect(database)) as check:
        assert check.execute("SELECT COUNT(*) FROM parsed_reports").fetchone() == (1,)

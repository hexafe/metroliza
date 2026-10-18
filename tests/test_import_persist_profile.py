"""Persistence qualification, connection lifetime and failure guarantees (#1136)."""

from contextlib import closing
import sqlite3

import pytest

from metroliza.reports.db import lazy_sqlite_connection_scope, run_transaction_with_retry
from metroliza.reports.import_persist_profile import ImportPersistProfile
from scripts import benchmark_import_persist as benchmark
from tests.test_import_single_verification import _write_reports


def test_lazy_scope_keeps_rejected_import_database_absent(tmp_path):
    database = tmp_path / "rejected.sqlite3"
    with lazy_sqlite_connection_scope(str(database)):
        assert not database.exists()
    assert not database.exists()


def test_scope_reuses_connection_and_closes_it_even_after_failure(tmp_path):
    database = tmp_path / "reports.sqlite3"
    profile = ImportPersistProfile()
    with pytest.raises(RuntimeError), profile.activate():
        with lazy_sqlite_connection_scope(str(database)) as connection:
            connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
            connection.commit()
            for value in (1, 2):
                run_transaction_with_retry(str(database), lambda cursor: cursor.execute(
                    "INSERT INTO sample VALUES (?)", (value,)
                ), connection=connection)
            assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
            assert connection.execute("PRAGMA synchronous").fetchone() == (1,)
            raise RuntimeError("synthetic cancellation after commits")
    assert profile.calls["connection_open"] == profile.calls["checkpoint_close"] == 1
    assert profile.calls["commit"] == 2
    assert profile.calls["checkpoint"] == 2
    assert all(busy == 0 and frames == written for busy, frames, written in profile.checkpoint_results)
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with closing(sqlite3.connect(database)) as reader:
        assert reader.execute("SELECT * FROM sample").fetchall() == [(1,), (2,)]


def test_failed_report_rolls_back_without_losing_prior_commit(tmp_path):
    database = str(tmp_path / "reports.sqlite3")
    profile = ImportPersistProfile()
    with profile.activate(), lazy_sqlite_connection_scope(database) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.commit()
        run_transaction_with_retry(database, lambda cursor: cursor.execute(
            "INSERT INTO sample VALUES (1)"
        ), connection=connection)

        def failed_report(cursor):
            cursor.execute("BEGIN IMMEDIATE")
            cursor.executemany("INSERT INTO sample VALUES (?)", [(2,), (1,)])

        with pytest.raises(sqlite3.IntegrityError):
            run_transaction_with_retry(database, failed_report, connection=connection)
        assert not connection.in_transaction
        assert connection.execute("SELECT * FROM sample").fetchall() == [(1,)]
    assert profile.calls["executemany"] == 1
    assert profile.calls["commit"] == 1
    assert profile.calls["checkpoint_close"] == 1


def test_profile_is_opt_in_and_restores_outer_context(tmp_path):
    database = str(tmp_path / "reports.sqlite3")
    outer, inner = ImportPersistProfile(), ImportPersistProfile()
    with outer.activate():
        with inner.activate(), lazy_sqlite_connection_scope(database) as connection:
            connection.execute("SELECT 1")
        with lazy_sqlite_connection_scope(database) as connection:
            connection.execute("SELECT 1")
    receipt = outer.receipt()
    with lazy_sqlite_connection_scope(database) as connection:
        connection.execute("SELECT 1")
    assert outer.receipt() == receipt
    assert outer.calls["connection_open"] == inner.calls["connection_open"] == 1


def test_post_commit_checkpoint_failure_never_retries_the_write(tmp_path, monkeypatch):
    database = str(tmp_path / "reports.sqlite3")
    attempts = []
    with lazy_sqlite_connection_scope(database) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.commit()

        def fail_checkpoint():
            raise sqlite3.OperationalError("database is locked")

        def write(cursor):
            attempts.append(1)
            cursor.execute("INSERT INTO sample VALUES (1)")

        monkeypatch.setattr(connection, "checkpoint_after_commit", fail_checkpoint)
        with pytest.raises(sqlite3.OperationalError):
            run_transaction_with_retry(database, write, connection=connection)
        assert len(attempts) == 1
        assert connection.execute("SELECT * FROM sample").fetchall() == [(1,)]


def test_real_pdf_qualification_compares_every_persisted_row(tmp_path):
    source = tmp_path / "synthetic"
    _write_reports(source, 3)
    receipt = benchmark.compare(source, tmp_path, 3, 1)
    assert receipt["all_rows_equal"]
    assert receipt["row_counts"]["source_files"] == 3
    assert receipt["row_counts"]["report_measurements"] > 0
    runs = receipt["runs"]
    assert runs["batch_connection"][0]["profile"]["calls"]["checkpoint_close"] == 1
    assert runs["per_report"][0]["profile"]["calls"]["checkpoint_close"] > 1


def test_qualification_rejects_row_divergence(tmp_path, monkeypatch):
    calls = []

    def fake_run(*args):
        calls.append(1)
        return {}, {"synthetic": [(len(calls),)]}

    monkeypatch.setattr(benchmark, "_run", fake_run)
    monkeypatch.setattr(benchmark, "_qualify_profile", lambda *_args: None)
    with pytest.raises(RuntimeError, match="persisted_rows_differ"):
        benchmark.compare(tmp_path, tmp_path, 1, 1)


@pytest.mark.parametrize("failure", ["stage", "settings", "hash_count"])
def test_qualification_rejects_incomplete_or_changed_measurements(failure):
    profile = {"calls": dict.fromkeys((
        "schema_probe", "hash", "row_building", "executemany", "commit", "checkpoint_close"
    ), 1), "sqlite_settings": [{"journal_mode": "wal", "synchronous": 1, "wal_autocheckpoint": 1000}]}
    if failure == "stage":
        del profile["calls"]["schema_probe"]
    elif failure == "settings":
        profile["sqlite_settings"][0]["synchronous"] = 0
    else:
        profile["calls"]["hash"] = 2
    with pytest.raises(RuntimeError):
        benchmark._qualify_profile({"profile": profile}, 1)

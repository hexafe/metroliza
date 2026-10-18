"""Persistence qualification, connection lifetime and failure guarantees (#1136)."""

from contextlib import closing
import sqlite3

import pytest

from metroliza.reports import db as db_module
from metroliza.reports.db import (
    checkpoint_pending_import_commits,
    lazy_sqlite_connection_scope,
    run_transaction_with_retry,
)
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
    # Two quick commits stay below the periodic cadence; closing the scope checkpoints them
    # explicitly, also after this cancellation.
    assert profile.calls["checkpoint"] == 1
    ((busy, frames, written), count), = profile.checkpoint_results.items()
    assert (busy, count) == (0, 1) and frames == written > 0
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


def test_import_connection_checkpoints_periodically_while_committing(tmp_path):
    database = str(tmp_path / "reports.sqlite3")
    profile = ImportPersistProfile()
    with profile.activate(), lazy_sqlite_connection_scope(database) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.commit()
        for value in range(db_module.IMPORT_CHECKPOINT_COMMITS):
            run_transaction_with_retry(database, lambda cursor, value=value: cursor.execute(
                "INSERT INTO sample VALUES (?)", (value,)
            ), connection=connection)
        # A real PASSIVE checkpoint ran before the scope closed and synced every frame.
        assert profile.calls["checkpoint"] >= 1
        assert all(busy == 0 and frames == written > 0
                   for busy, frames, written in profile.checkpoint_results)


def test_persistence_boundary_checkpoints_pending_commits_with_a_reader_open(tmp_path):
    database = str(tmp_path / "reports.sqlite3")
    profile = ImportPersistProfile()
    with profile.activate(), lazy_sqlite_connection_scope(database) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.commit()
        run_transaction_with_retry(database, lambda cursor: cursor.execute(
            "INSERT INTO sample VALUES (1)"), connection=connection)
        with closing(sqlite3.connect(database)) as reader:
            reader.execute("SELECT 1").fetchall()  # keeps the database open, no snapshot
            checkpoint_pending_import_commits(connection)
            assert profile.calls["checkpoint"] == 1
            checkpoint_pending_import_commits(connection)  # nothing new to sync
            assert profile.calls["checkpoint"] == 1
    checkpoint_pending_import_commits(object())  # non-import connections are ignored


def test_checkpoint_error_after_commit_keeps_the_committed_report(tmp_path, caplog):
    database = str(tmp_path / "reports.sqlite3")
    attempts = []
    with lazy_sqlite_connection_scope(database) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.commit()
        real = connection._connection

        class FailingCheckpoint:
            def __getattr__(self, name):
                return getattr(real, name)

            def execute(self, sql, *args):
                if sql.startswith("PRAGMA wal_checkpoint"):
                    raise sqlite3.OperationalError("disk I/O error")
                return real.execute(sql, *args)

        connection._connection = FailingCheckpoint()
        connection._commits_since_checkpoint = db_module.IMPORT_CHECKPOINT_COMMITS - 1

        def write(cursor):
            attempts.append(1)
            cursor.execute("INSERT INTO sample VALUES (1)")
            return "imported"

        assert run_transaction_with_retry(database, write, connection=connection) == "imported"
        assert len(attempts) == 1
        assert "checkpoint failed" in caplog.text
        assert real.execute("SELECT * FROM sample").fetchall() == [(1,)]


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
    profile["attribution"] = {"unattributed_s": 0.0}
    profile["sql"] = [{"calls": 1}]
    if failure == "stage":
        del profile["calls"]["schema_probe"]
    elif failure == "settings":
        profile["sqlite_settings"][0]["synchronous"] = 0
    else:
        profile["calls"]["hash"] = 2
    with pytest.raises(RuntimeError):
        benchmark._qualify_profile({"profile": profile}, 1)


def _assert_partition(profile):
    receipt = profile.receipt()
    attribution = receipt["attribution"]
    assert attribution["persist_s"] > 0
    assert sum(item["seconds"] for item in attribution["activities"]) == pytest.approx(
        attribution["persist_s"], abs=1e-9
    )
    assert abs(attribution["unattributed_s"]) < 1e-9
    return receipt


def test_sql_templates_cover_shortcuts_cursors_scripts_and_failed_calls(tmp_path):
    from metroliza.reports.db import connect_sqlite

    profile = ImportPersistProfile()
    with profile.activate(), profile.measure("persist"), closing(connect_sqlite(str(tmp_path / "sql.db"))) as conn:
        conn.executescript("CREATE TABLE sample(value TEXT); INSERT INTO sample VALUES ('private-one');")
        conn.execute("INSERT INTO sample VALUES ('private-two') -- hidden-comment")
        cursor = conn.cursor()
        assert cursor.execute("SELECT value FROM sample") is cursor
        assert cursor.fetchone() == ("private-one",)
        assert cursor.fetchmany(1) == [("private-two",)]
        assert cursor.fetchall() == []
        conn.executemany("INSERT INTO sample VALUES (?)", [("private-three",)])
        cursor.execute("SELECT value FROM sample")
        assert len(list(cursor)) == 3
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO absent VALUES ('private-four')")
        conn.rollback()
        cursor.close()
    receipt = _assert_partition(profile)
    assert {item["method"] for item in receipt["sql"]} == {"execute", "executemany", "executescript"}
    assert sum(item["errors"] for item in receipt["sql"]) == 1
    assert receipt["sqlite_errors"] == {"SQLITE_ERROR": 1}
    assert "private-" not in str(receipt)
    assert "hidden-comment" not in str(receipt)
    assert str(tmp_path) not in str(receipt)


def test_native_filesystem_python_gaps_and_sleep_are_exclusive(tmp_path):
    import hashlib
    import json
    import os
    import time

    path = tmp_path / "private-path"
    path.write_bytes(b"private-content")
    profile = ImportPersistProfile()
    with profile.activate(), profile.measure("persist"):
        path.resolve()
        os.stat(path)
        with profile.measure("hash"), path.open("rb") as stream:
            assert hashlib.sha256(stream.read()).hexdigest()
        json.dumps({"synthetic": [1, 2, 3]})
        time.sleep(0.001)
    receipt = _assert_partition(profile)
    activities = {(item["category"], item["operation"]): item for item in receipt["attribution"]["activities"]}
    for key in (("filesystem", "stat"), ("filesystem", "open"), ("filesystem", "file.read"),
                ("filesystem", "Path.resolve"), ("sleep", "time.sleep"), ("python", "json.dumps"),
                ("python", "between_operations")):
        assert activities[key]["calls"] > 0
        assert activities[key]["seconds"] > 0
    assert "private-" not in str(receipt)


def test_begin_wait_retry_sleep_and_rollback_are_attributed(tmp_path, monkeypatch):
    from metroliza.reports import db

    database = str(tmp_path / "locked.db")
    with closing(db.connect_sqlite(database)) as blocker:
        blocker.execute("CREATE TABLE sample(value INTEGER)")
        blocker.execute("BEGIN IMMEDIATE")
        profile = ImportPersistProfile()
        original_sleep = db.time.sleep

        def release_and_sleep(_delay):
            blocker.rollback()
            original_sleep(0.001)

        monkeypatch.setattr(db.time, "sleep", release_and_sleep)
        with profile.activate(), profile.measure("persist"), closing(db.connect_sqlite(database, timeout_s=0.01)) as writer:
            def write(cursor):
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("INSERT INTO sample VALUES (?)", (1,))

            db.run_transaction_with_retry(database, write, connection=writer, retries=1)
            assert writer.execute("SELECT * FROM sample").fetchall() == [(1,)]
    receipt = _assert_partition(profile)
    begin = next(item for item in receipt["sql"] if item["template"] == "BEGIN IMMEDIATE")
    assert (begin["calls"], begin["errors"]) == (2, 1)
    assert begin["seconds"] >= 0.005
    assert receipt["sqlite_errors"] == {"SQLITE_BUSY": 1}
    assert any(item["category"] == "begin_immediate" and item["calls"] == 2
               for item in receipt["attribution"]["activities"])
    assert any(item["category"] == "sleep" for item in receipt["attribution"]["activities"])
    assert any(item["operation"] == "rollback" for item in receipt["attribution"]["activities"])


def test_detailed_observer_restores_existing_sys_profiler_on_error():
    import sys

    previous = sys.getprofile()
    try:
        def observer(*_args):
            pass

        sys.setprofile(observer)
        profile = ImportPersistProfile()
        with pytest.raises(ValueError), profile.activate(), profile.measure("persist"):
            raise ValueError("synthetic")
        assert sys.getprofile() is observer
        _assert_partition(profile)
    finally:
        sys.setprofile(previous)


def test_qualification_rejects_nonzero_remainder(tmp_path):
    source = tmp_path / "synthetic"
    _write_reports(source, 1)
    run, _snapshot = benchmark._run(source, tmp_path / "reports.db", "batch_connection")
    benchmark._qualify_profile(run, 1, "batch_connection")
    run["profile"]["attribution"]["unattributed_s"] = 0.1
    with pytest.raises(RuntimeError, match="persist_time_unattributed"):
        benchmark._qualify_profile(run, 1, "batch_connection")


@pytest.mark.parametrize(("checkpoints", "results", "error"), [
    (0, [], "checkpoint_cadence_missing"),
    (8, [dict(busy=0, wal_frames=40, checkpointed_frames=40, calls=8)], None),
    (8, [dict(busy=1, wal_frames=40, checkpointed_frames=12, calls=8)], "checkpoint_incomplete"),
    (8, [dict(busy=0, wal_frames=40, checkpointed_frames=40, calls=7)], "checkpoint_incomplete"),
    (40, [dict(busy=0, wal_frames=40, checkpointed_frames=40, calls=40)], "checkpoint_cadence_exceeded"),
])
def test_checkpoint_cadence_qualification_has_both_bounds(checkpoints, results, error):
    calls = {"commit": 202, "checkpoint": checkpoints, "checkpoint_close": 1}
    run = {"import_s": 5.0, "profile": {"passive_checkpoints": results}}
    if error is None:
        benchmark._check_checkpoint_cadence(run, calls)
    else:
        with pytest.raises(RuntimeError, match=error):
            benchmark._check_checkpoint_cadence(run, calls)


def test_import_checkpoint_cadence_is_bounded_by_commits_and_time(tmp_path):
    from metroliza.reports import db as db_module

    now = [0.0]
    connection = db_module._LazySQLiteConnection(str(tmp_path / "cadence.sqlite3"), clock=lambda: now[0])
    checkpoints = []
    connection._connection = type("Conn", (), {
        "execute": lambda self, sql: checkpoints.append(sql) or type(
            "Cursor", (), {"fetchone": lambda self: (0, 0, 0)})(),
    })()
    for _ in range(db_module.IMPORT_CHECKPOINT_COMMITS - 1):
        connection.checkpoint_after_commit()
    assert checkpoints == []
    connection.checkpoint_after_commit()
    assert checkpoints == ["PRAGMA wal_checkpoint(PASSIVE)"]
    connection.checkpoint_after_commit()
    assert len(checkpoints) == 1
    now[0] += db_module.IMPORT_CHECKPOINT_SECONDS
    connection.checkpoint_after_commit()
    assert len(checkpoints) == 2

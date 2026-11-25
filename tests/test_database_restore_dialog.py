"""Synthetic tests of Reports database backup and restore."""

from contextlib import closing, nullcontext
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Event
from time import monotonic

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QFileDialog

from metroliza.industrial.industrial_cache_target import publish_verified_database_copy
from metroliza.reports import report_schema
from metroliza.reports.db import (
    SQLiteFileBinding,
    connect_sqlite,
    lazy_sqlite_connection_scope,
    selected_reports_worker_options,
    sqlite_report_schema_connection_scope,
)
from metroliza.reports.report_schema import SCHEMA_TABLE_STATEMENTS, SCHEMA_VERSION, ensure_report_schema
from metroliza.ui import database_restore_dialog
from metroliza.ui.database_restore_dialog import DatabaseRestoreDialog, _validate_report_snapshot
from metroliza.ui.main_window import MainWindow
from metroliza.ui.ui_preferences import UiPreferences


def _restore(source, destination, **kwargs):
    return publish_verified_database_copy(source, destination, validate=_validate_report_snapshot, **kwargs)


def _assert_no_staging(directory):
    assert not list(directory.glob(".metroliza-cache-*.saving"))
    assert not list(directory.glob("restored.sqlite-*"))


def test_current_table_names_alone_do_not_admit_an_unrelated_database(tmp_path):
    source = tmp_path / "lookalike.sqlite"
    destination = tmp_path / "restored.sqlite"
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.executescript("""
            CREATE TABLE parsed_reports (id INTEGER PRIMARY KEY);
            CREATE TABLE report_metadata (reference TEXT);
            CREATE TABLE report_measurements (meas REAL);
        """)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    original = source.read_bytes()
    with pytest.raises(ValueError, match="recognized Metroliza report database"):
        _restore(source, destination)
    assert source.read_bytes() == original
    assert not destination.exists()
    _assert_no_staging(tmp_path)


@pytest.mark.parametrize("key", ["schema_version", "source_location_ownership_version"])
def test_unknown_schema_version_cannot_fall_back_to_retained_legacy_tables(tmp_path, key):
    source = tmp_path / "future.sqlite"
    destination = tmp_path / "restored.sqlite"
    ensure_report_schema(str(source))
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute(
            "UPDATE app_schema SET value = 'future' WHERE key = ?", (key,),
        )
        connection.executescript("""
            CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT);
            CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY, REPORT_ID INTEGER, MEAS REAL);
        """)
    with pytest.raises(ValueError, match="Unsupported report database schema version"):
        _restore(source, destination)
    assert not destination.exists()
    _assert_no_staging(tmp_path)


def test_known_version_still_requires_physical_column_shape(tmp_path):
    source = tmp_path / "incomplete.sqlite"
    destination = tmp_path / "restored.sqlite"
    ensure_report_schema(str(source))
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.executescript("""
            DROP TABLE report_measurements;
            CREATE TABLE report_measurements (id INTEGER PRIMARY KEY, report_id INTEGER, meas REAL);
        """)
    with pytest.raises(ValueError, match="recognized Metroliza report database"):
        _restore(source, destination)
    assert not destination.exists()
    _assert_no_staging(tmp_path)


def test_known_schema_requires_source_content_uniqueness(tmp_path):
    source = tmp_path / "duplicate-content-possible.sqlite"
    destination = tmp_path / "restored.sqlite"
    ensure_report_schema(str(source))
    source_file_table = next(
        statement for statement in SCHEMA_TABLE_STATEMENTS
        if statement.startswith("CREATE TABLE IF NOT EXISTS source_files (")
    )
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("DROP TABLE source_files")
        connection.execute(source_file_table.replace("sha256 TEXT NOT NULL UNIQUE", "sha256 TEXT NOT NULL"))
    with pytest.raises(ValueError, match="recognized Metroliza report database"):
        _restore(source, destination)
    assert not destination.exists()
    _assert_no_staging(tmp_path)


@pytest.mark.parametrize("pre_ownership", [False, True])
def test_preserves_supported_normalized_snapshots_without_migrating(tmp_path, pre_ownership):
    source = tmp_path / "backup.sqlite"
    destination = tmp_path / "restored.sqlite"
    ensure_report_schema(str(source))
    with closing(sqlite3.connect(source)) as connection, connection:
        if pre_ownership:
            connection.executescript("""
                DROP TABLE report_parse_state;
                DROP INDEX idx_source_file_locations_active_path_unique;
                DELETE FROM app_schema WHERE key = 'source_location_ownership_version';
            """)
        connection.executescript("""
            INSERT INTO source_files (id, sha256, source_format, discovered_at)
                VALUES (1, 'synthetic-content-id', 'pdf', '2026-01-05');
            INSERT INTO parsed_reports (
                id, source_file_id, parser_id, template_family, parse_status, created_at, updated_at
            ) VALUES (2, 1, 'cmm', 'synthetic', 'parsed', '2026-01-05', '2026-01-05');
            INSERT INTO report_metadata (report_id, reference, metadata_version)
                VALUES (2, 'REF-SYNTHETIC', '1');
            INSERT INTO report_measurements (report_id, row_order, ax, meas, status_code)
                VALUES (2, 0, 'X', 10.25, 'ok');
        """)

    original = source.read_bytes()
    assert _restore(source, destination) == destination
    assert source.read_bytes() == original
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("""
            SELECT rm.reference, m.ax, m.meas
            FROM report_metadata AS rm JOIN report_measurements AS m USING (report_id)
        """).fetchall() == [("REF-SYNTHETIC", "X", 10.25)]
        assert connection.execute("""
            SELECT value FROM app_schema WHERE key = 'source_location_ownership_version'
        """).fetchall() == ([] if pre_ownership else [("1",)])
        assert connection.execute("""
            SELECT count(*) FROM sqlite_schema WHERE type = 'table' AND name = 'report_parse_state'
        """).fetchone() == (0 if pre_ownership else 1,)
    _assert_no_staging(tmp_path)


def _make_legacy_snapshot(source, measurement_report_id=7):
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.executescript("""
            CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT);
            CREATE TABLE MEASUREMENTS (REPORT_ID INTEGER, HEADER TEXT, MEAS REAL);
            INSERT INTO REPORTS VALUES (7, 'REF-LEGACY');
        """)
        connection.execute(
            "INSERT INTO MEASUREMENTS VALUES (?, 'WIDTH', 5.125)", (measurement_report_id,),
        )


def _migration_recoveries(directory):
    return list(directory.glob("metroliza-reports-pre-migration-*.sqlite"))


@pytest.mark.parametrize("scope", [None, sqlite_report_schema_connection_scope, lazy_sqlite_connection_scope])
@pytest.mark.parametrize("version", [None, "0"])
def test_upgrade_publishes_a_legacy_snapshot_usable_by_restore(tmp_path, scope, version):
    source = tmp_path / "legacy.sqlite"
    _make_legacy_snapshot(source)
    if version is not None:
        with closing(sqlite3.connect(source)) as connection, connection:
            connection.execute("CREATE TABLE app_schema (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO app_schema VALUES ('schema_version', ?)", (version,))

    with (scope(str(source)) if scope is not None else nullcontext()) as connection:
        ensure_report_schema(str(source), connection=connection)

    recovery, = _migration_recoveries(tmp_path)
    restored = tmp_path / "restored.sqlite"
    assert _restore(recovery, restored) == restored
    with closing(sqlite3.connect(restored)) as connection:
        assert connection.execute("SELECT ID, REFERENCE FROM REPORTS").fetchall() == [(7, "REF-LEGACY")]
        assert connection.execute("SELECT REPORT_ID, MEAS FROM MEASUREMENTS").fetchall() == [(7, 5.125)]
        assert connection.execute("SELECT 1 FROM sqlite_schema WHERE name='parsed_reports'").fetchone() is None
        if version is not None:
            assert connection.execute("SELECT value FROM app_schema").fetchone() == (version,)
    with closing(sqlite3.connect(source)) as connection:
        assert connection.execute("SELECT reference FROM vw_report_overview").fetchall() == [("REF-LEGACY",)]
    ensure_report_schema(str(source))
    assert _migration_recoveries(tmp_path) == [recovery]
    _assert_no_staging(tmp_path)


@pytest.mark.parametrize("schema, ownership, drop_parse_state", [
    (SCHEMA_VERSION, None, False),
    (SCHEMA_VERSION, "1", True),
    (SCHEMA_VERSION, "0", False),
    ("0", "1", False),
])
def test_upgrade_copies_supported_historical_normalized_shapes(tmp_path, schema, ownership, drop_parse_state):
    source = tmp_path / "historical.db"
    ensure_report_schema(str(source))
    assert _migration_recoveries(tmp_path) == []
    with closing(sqlite3.connect(source)) as connection, connection:
        assert connection.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",)
        connection.execute("UPDATE app_schema SET value = ? WHERE key='schema_version'", (schema,))
        if ownership is None:
            connection.execute("DELETE FROM app_schema WHERE key='source_location_ownership_version'")
        else:
            connection.execute(
                "UPDATE app_schema SET value = ? WHERE key='source_location_ownership_version'", (ownership,),
            )
        if ownership != "1":
            connection.execute("DROP INDEX idx_source_file_locations_active_path_unique")
        if drop_parse_state:
            connection.execute("DROP TABLE report_parse_state")
        connection.execute(
            "INSERT INTO source_files (sha256, source_format, discovered_at) "
            "VALUES ('historical-source', 'pdf', '2026-01-05')"
        )
    with closing(sqlite3.connect(source)) as connection:
        expected_history = list(connection.iterdump())

    ensure_report_schema(str(source))

    recovery, = _migration_recoveries(tmp_path)
    restored = tmp_path / "restored.sqlite"
    _restore(recovery, restored)
    with closing(sqlite3.connect(restored)) as connection:
        assert list(connection.iterdump()) == expected_history
    with closing(sqlite3.connect(source)) as connection:
        assert report_schema.is_report_schema_ready(connection)
    _assert_no_staging(tmp_path)


def test_historical_wal_source_requires_upgrade_as_copy_and_keeps_committed_wal(tmp_path):
    source = tmp_path / "legacy.sqlite"
    destination = tmp_path / "upgraded.sqlite"
    _make_legacy_snapshot(source)
    with closing(sqlite3.connect(source, timeout=0)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO REPORTS VALUES (8, 'WAL-COMMITTED')")
        writer.commit()
        wal = source.with_name(source.name + "-wal")
        assert wal.stat().st_size > 32
        original = source.read_bytes(), wal.read_bytes()
        with pytest.raises(report_schema.ReportUpgradeAsCopyRequired, match="Restore database copy"):
            ensure_report_schema(str(source))
        assert _migration_recoveries(tmp_path) == []
        assert report_schema.publish_upgraded_report_copy(source, destination) == destination
        assert (source.read_bytes(), wal.read_bytes()) == original
        assert writer.execute("SELECT 1 FROM sqlite_schema WHERE name='parsed_reports'").fetchone() is None

    with closing(sqlite3.connect(destination)) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert copy.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert copy.execute(
            "SELECT reference FROM vw_report_overview ORDER BY report_id"
        ).fetchall() == [("REF-LEGACY",), ("WAL-COMMITTED",)]
        assert copy.execute("SELECT report_id, meas FROM MEASUREMENTS").fetchall() == [(7, 5.125)]
        assert report_schema.is_report_schema_ready(copy)
    _assert_no_staging(tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="checks SQLite's process-exit WAL retention on POSIX")
def test_historical_wal_refusal_does_not_checkpoint_after_a_crashed_writer(tmp_path):
    source = tmp_path / "historical.sqlite"
    _make_legacy_snapshot(source)
    subprocess.run([
        sys.executable, "-c",
        "import os, sqlite3, sys; "
        "db = sqlite3.connect(sys.argv[1]); "
        "db.execute('PRAGMA journal_mode=WAL'); "
        "db.execute('INSERT INTO REPORTS VALUES (8, ?)', ('RECOVER-COMMIT',)); "
        "db.commit(); os._exit(0)",
        str(source),
    ], check=True)
    wal = source.with_name(source.name + "-wal")
    original = source.read_bytes(), wal.read_bytes()
    assert len(original[1]) > 32

    with pytest.raises(report_schema.ReportUpgradeAsCopyRequired):
        ensure_report_schema(str(source))
    assert (source.read_bytes(), wal.read_bytes()) == original
    assert _migration_recoveries(tmp_path) == []
    destination = tmp_path / "upgraded.sqlite"
    report_schema.publish_upgraded_report_copy(source, destination)
    assert (source.read_bytes(), wal.read_bytes()) == original
    with closing(sqlite3.connect(destination)) as copy:
        assert copy.execute("SELECT reference FROM REPORTS WHERE id=8").fetchone() == ("RECOVER-COMMIT",)


@pytest.mark.skipif(os.name != "posix", reason="replacing an open SQLite file requires POSIX semantics")
def test_upgrade_copy_rejects_a_source_replaced_after_staging(tmp_path, monkeypatch):
    source = tmp_path / "historical.sqlite"
    original = tmp_path / "original.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    destination = tmp_path / "upgraded.sqlite"
    _make_legacy_snapshot(source)
    _make_legacy_snapshot(replacement)
    with closing(sqlite3.connect(replacement)) as connection, connection:
        connection.execute("UPDATE REPORTS SET reference = 'REPLACEMENT-ONLY'")
    old_bytes, new_bytes = source.read_bytes(), replacement.read_bytes()
    prepare = report_schema._prepare_upgraded_snapshot

    def prepare_then_replace(*args):
        prepare(*args)
        source.replace(original)
        replacement.replace(source)

    monkeypatch.setattr(report_schema, "_prepare_upgraded_snapshot", prepare_then_replace)
    with pytest.raises(sqlite3.OperationalError, match="replaced or removed"):
        report_schema.publish_upgraded_report_copy(source, destination)
    assert source.read_bytes() == new_bytes and original.read_bytes() == old_bytes
    assert not destination.exists()
    _assert_no_staging(tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="replacing an open SQLite file requires POSIX semantics")
@pytest.mark.parametrize("before_industrial", [False, True])
def test_upgrade_refuses_a_replacement_during_the_paired_transaction(tmp_path, monkeypatch, before_industrial):
    source = tmp_path / "legacy.sqlite"
    original = tmp_path / "original.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    _make_legacy_snapshot(source)
    _make_legacy_snapshot(replacement)
    with closing(sqlite3.connect(replacement)) as connection, connection:
        connection.execute("UPDATE REPORTS SET reference = 'REPLACEMENT-ONLY'")
    replacement_bytes = replacement.read_bytes()
    original_bytes = source.read_bytes()
    function = "_apply_industrial_schema" if before_industrial else "_apply_report_schema"
    apply = getattr(report_schema, function)

    def replace_source(*args, **kwargs):
        source.replace(original)
        replacement.replace(source)
        return apply(*args, **kwargs)

    monkeypatch.setattr(report_schema, function, replace_source)
    with pytest.raises(sqlite3.OperationalError, match="readonly|replaced or removed"):
        ensure_report_schema(str(source), retries=0)
    assert source.read_bytes() == replacement_bytes
    assert original.read_bytes() == original_bytes
    recovery, = _migration_recoveries(tmp_path)
    with closing(sqlite3.connect(recovery)) as copy:
        assert copy.execute("SELECT reference FROM REPORTS").fetchall() == [("REF-LEGACY",)]
    _assert_no_staging(tmp_path)


def test_directory_sync_failure_preserves_recovery_and_blocks_upgrade(tmp_path, monkeypatch):
    source = tmp_path / "legacy.sqlite"
    _make_legacy_snapshot(source)
    original = source.read_bytes()

    def fail_sync(published):
        assert published.exists() and published.parent == source.parent
        raise OSError("directory sync failed")

    monkeypatch.setattr(report_schema, "sync_database_parent", fail_sync)
    with pytest.raises(OSError, match="directory sync failed"):
        ensure_report_schema(str(source))
    assert source.read_bytes() == original
    assert len(_migration_recoveries(tmp_path)) == 1


def test_industrial_reference_load_keeps_original_journal_if_backup_fails(tmp_path, monkeypatch):
    from metroliza.ui.industrial_filter_dialog import _read_database_reference_rows

    source = tmp_path / "legacy.sqlite"
    _make_legacy_snapshot(source)
    original = source.read_bytes()

    def fail_backup(*args, **kwargs):
        raise OSError("backup failed")

    monkeypatch.setattr(report_schema, "publish_database_snapshot", fail_backup)
    with pytest.raises(OSError, match="backup failed"):
        _read_database_reference_rows(str(source))
    assert source.read_bytes() == original
    assert _migration_recoveries(tmp_path) == []
    with closing(sqlite3.connect(source)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)


def test_recovery_collision_leaves_the_original_and_existing_sibling_intact(tmp_path, monkeypatch):
    from uuid import UUID

    source = tmp_path / "legacy.sqlite"
    _make_legacy_snapshot(source)
    before = source.read_bytes()
    token = UUID(int=0)
    occupied = tmp_path / f"metroliza-reports-pre-migration-{token.hex}.sqlite"
    occupied.write_bytes(b"another writer")
    monkeypatch.setattr(report_schema, "uuid4", lambda: token)

    with pytest.raises(FileExistsError, match="Destination already exists"):
        ensure_report_schema(str(source))
    assert source.read_bytes() == before
    assert occupied.read_bytes() == b"another writer"
    _assert_no_staging(tmp_path)


def test_malformed_history_is_neither_migrated_nor_published(tmp_path):
    source = tmp_path / "orphan.sqlite"
    _make_legacy_snapshot(source, measurement_report_id=999)
    before = source.read_bytes()

    with pytest.raises(ValueError, match="broken link between records"):
        ensure_report_schema(str(source))
    assert source.read_bytes() == before
    assert _migration_recoveries(tmp_path) == []
    _assert_no_staging(tmp_path)


def test_version_zero_alone_does_not_make_a_database_a_supported_snapshot(tmp_path):
    source = tmp_path / "lookalike.sqlite"
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.executescript("""
            CREATE TABLE app_schema (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO app_schema VALUES ('schema_version', '0');
            CREATE TABLE parsed_reports (id INTEGER PRIMARY KEY);
        """)
    before = source.read_bytes()
    with pytest.raises(ValueError, match="recognized Metroliza report database"):
        ensure_report_schema(str(source))
    with pytest.raises(ValueError, match="recognized Metroliza report database"):
        _restore(source, tmp_path / "restored.sqlite")
    assert source.read_bytes() == before
    assert list(tmp_path.iterdir()) == [source]


def test_borrowed_pending_transaction_is_left_to_its_owner(tmp_path):
    source = tmp_path / "legacy.sqlite"
    _make_legacy_snapshot(source)
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("INSERT INTO REPORTS VALUES (8, 'uncommitted')")
        with pytest.raises(ValueError, match="Finish the active transaction"):
            ensure_report_schema(str(source), connection=connection)
        assert connection.in_transaction
        assert connection.execute("SELECT reference FROM REPORTS WHERE id=8").fetchone() == ("uncommitted",)
        with closing(sqlite3.connect(source)) as observer:
            assert observer.execute("SELECT reference FROM REPORTS WHERE id=8").fetchone() is None
        connection.rollback()
    assert _migration_recoveries(tmp_path) == []


def test_failed_schema_bootstrap_rolls_back_its_savepoint_only(tmp_path, monkeypatch):
    source = tmp_path / "active.sqlite"

    def fail_industrial(*args):
        raise RuntimeError("industrial schema failed after Reports bootstrap")

    monkeypatch.setattr(report_schema, "_apply_industrial_schema", fail_industrial)
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE caller_owned (value)")
        connection.execute("INSERT INTO caller_owned VALUES ('pending')")
        with pytest.raises(RuntimeError, match="industrial schema failed"):
            ensure_report_schema(str(source), connection=connection)
        assert connection.in_transaction
        assert connection.execute("SELECT value FROM caller_owned").fetchone() == ("pending",)
        assert connection.execute("SELECT 1 FROM sqlite_schema WHERE name='parsed_reports'").fetchone() is None
        connection.commit()
    assert _migration_recoveries(tmp_path) == []


def test_borrowed_raw_connection_can_work_with_current_schema_but_cannot_upgrade(tmp_path):
    source = tmp_path / "legacy.sqlite"
    _make_legacy_snapshot(source)
    before = source.read_bytes()
    with closing(sqlite3.connect(source)) as raw:
        with pytest.raises(ValueError, match="Reopen the Reports database"):
            ensure_report_schema(str(source), connection=raw)
        assert not raw.in_transaction
    assert source.read_bytes() == before
    assert _migration_recoveries(tmp_path) == []

    current = tmp_path / "current.sqlite"
    ensure_report_schema(str(current))
    with closing(sqlite3.connect(current)) as raw:
        ensure_report_schema(str(current), connection=raw)
    assert _migration_recoveries(tmp_path) == []


@pytest.mark.skipif(os.name != "posix", reason="replacing an open SQLite file requires POSIX semantics")
def test_historical_managed_handle_refuses_a_replaced_path(tmp_path):
    source = tmp_path / "legacy.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    _make_legacy_snapshot(source)
    _make_legacy_snapshot(replacement)
    with closing(connect_sqlite(str(source), initialize_wal=False)) as connection:
        original_bytes = replacement.read_bytes()
        replacement.replace(source)
        with pytest.raises(sqlite3.OperationalError, match="replaced or removed"):
            ensure_report_schema(str(source), connection=connection)
    assert source.read_bytes() == original_bytes
    assert _migration_recoveries(tmp_path) == []
    _assert_no_staging(tmp_path)


def test_recovery_survives_a_failure_in_the_paired_industrial_upgrade(tmp_path, monkeypatch):
    source = tmp_path / "legacy.sqlite"
    _make_legacy_snapshot(source)

    def fail_industrial(*args, **kwargs):
        raise RuntimeError("industrial setup failed")

    monkeypatch.setattr(report_schema, "ensure_industrial_storage_schema", fail_industrial)
    with pytest.raises(RuntimeError, match="industrial setup failed"):
        ensure_report_schema(str(source))
    recovery, = _migration_recoveries(tmp_path)
    restored = tmp_path / "restored.sqlite"
    _restore(recovery, restored)
    with closing(sqlite3.connect(restored)) as connection:
        assert connection.execute("SELECT reference FROM REPORTS").fetchall() == [("REF-LEGACY",)]
        assert connection.execute("SELECT 1 FROM sqlite_schema WHERE name='parsed_reports'").fetchone() is None
    with closing(sqlite3.connect(source)) as connection:
        assert connection.execute("SELECT 1 FROM sqlite_schema WHERE name='parsed_reports'").fetchone() is None


def test_preserves_legacy_shape_and_payload(tmp_path):
    source = tmp_path / "legacy.sqlite"
    destination = tmp_path / "restored.sqlite"
    _make_legacy_snapshot(source)
    original = source.read_bytes()

    assert _restore(source, destination) == destination
    assert source.read_bytes() == original
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("SELECT ID, REFERENCE FROM REPORTS").fetchall() == [(7, "REF-LEGACY")]
        assert connection.execute("SELECT REPORT_ID, HEADER, MEAS FROM MEASUREMENTS").fetchall() == [
            (7, "WIDTH", 5.125),
        ]
        assert connection.execute("""
            SELECT count(*) FROM sqlite_schema WHERE type = 'table' AND name = 'parsed_reports'
        """).fetchone() == (0,)
    _assert_no_staging(tmp_path)


@pytest.mark.parametrize("legacy", [False, True])
def test_rejects_orphaned_records_and_removes_staging(tmp_path, legacy):
    source = tmp_path / "orphan.sqlite"
    destination = tmp_path / "restored.sqlite"
    if legacy:
        _make_legacy_snapshot(source, measurement_report_id=999)
    else:
        ensure_report_schema(str(source))
        with closing(sqlite3.connect(source)) as connection, connection:
            connection.execute("""
                INSERT INTO report_measurements (report_id, row_order, meas, status_code)
                VALUES (999, 0, 10.25, 'ok')
            """)
    original = source.read_bytes()
    with pytest.raises(ValueError, match="broken link between records"):
        _restore(source, destination)
    assert source.read_bytes() == original
    assert not destination.exists()
    _assert_no_staging(tmp_path)


def test_restore_rejects_the_active_destination_even_if_it_does_not_exist(tmp_path):
    source = tmp_path / "backup.sqlite"
    active = tmp_path / "restored.sqlite"
    _make_legacy_snapshot(source)

    with pytest.raises(ValueError, match="active Metroliza database cannot be replaced"):
        _restore(source, active, forbidden_destinations=(active,))
    assert not active.exists()
    _assert_no_staging(tmp_path)


def test_restore_leaves_late_destination_owner_intact(tmp_path):
    source = tmp_path / "backup.sqlite"
    destination = tmp_path / "restored.sqlite"
    _make_legacy_snapshot(source)

    def verify_then_create_destination(staging):
        _validate_report_snapshot(staging)
        destination.write_bytes(b"created by another writer")

    with pytest.raises(FileExistsError, match="Destination already exists"):
        publish_verified_database_copy(source, destination, validate=verify_then_create_destination)
    assert destination.read_bytes() == b"created by another writer"
    _assert_no_staging(tmp_path)


def test_cancelled_choosers_do_not_start_a_backup(monkeypatch, qapplication_session):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: ("", ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: ("", ""))
    dialog = DatabaseRestoreDialog(None, "")
    try:
        dialog.source_button.click()
        dialog.destination_button.click()
        assert (dialog.source, dialog.destination) == ("", "")
        assert not dialog.restore_button.isEnabled()
        assert dialog._worker is None
    finally:
        dialog.close()


@pytest.fixture
def backup_window(qapplication_session, tmp_path):
    preferences = UiPreferences(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    window = MainWindow(version_label="test", days_until_expiration=None, ui_preferences=preferences)
    try:
        yield window
    finally:
        window.close()
        qapplication_session.processEvents()


def _backup_action(window):
    return next(action for action in window.file_menu.actions() if action.text() == "Back up Reports database…")


def _wait_until(predicate):
    deadline = monotonic() + 8
    while not predicate() and monotonic() < deadline:
        QTest.qWait(5)
    assert predicate(), "Backup operation did not settle"


def _make_active_snapshot(source):
    ensure_report_schema(str(source))
    _make_legacy_snapshot(source)
    ensure_report_schema(str(source))


def test_file_backup_copies_committed_wal_and_keeps_active_database(tmp_path, monkeypatch, backup_window):
    source = tmp_path / "active.sqlite"
    destination = tmp_path / "backup.sqlite"
    action = _backup_action(backup_window)
    action.trigger()
    assert backup_window.window_coordinator.get("backup_database") is None
    _make_active_snapshot(source)
    assert backup_window.set_db_file(str(source))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(destination), ""))
    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        main_bytes = source.read_bytes()
        writer.execute("UPDATE REPORTS SET REFERENCE = 'WAL-COMMITTED'")
        writer.commit()
        assert source.read_bytes() == main_bytes and source.with_suffix(".sqlite-wal").stat().st_size > 0
        writer.execute("UPDATE REPORTS SET REFERENCE = 'UNCOMMITTED'")
        action.trigger()
        dialog = backup_window.window_coordinator.get("backup_database")
        assert dialog.source == str(source) and dialog.source_button is None
        assert dialog._worker is None and not destination.exists()
        assert not dialog.restore_button.isEnabled()
        dialog.destination_button.click()
        assert not destination.exists()
        dialog.restore_button.click()
        _wait_until(lambda: dialog._worker is None)
        assert dialog.status.text() == f"Backup created and verified: {destination}"
        assert backup_window.db_file == str(source) and source.read_bytes() == main_bytes
        with closing(sqlite3.connect(destination)) as copy:
            assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert copy.execute("SELECT REFERENCE FROM REPORTS").fetchall() == [("WAL-COMMITTED",)]
            assert copy.execute("SELECT MEAS FROM MEASUREMENTS").fetchall() == [(5.125,)]
        writer.rollback()
    restored = tmp_path / "restored.sqlite"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(destination), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(restored), ""))
    next(action for action in backup_window.file_menu.actions() if action.text() == "Restore database copy…").trigger()
    restore = backup_window.window_coordinator.get("restore_database")
    restore.source_button.click()
    restore.destination_button.click()
    restore.restore_button.click()
    _wait_until(lambda: restore._worker is None)
    assert restore.status.text() == f"Restored and verified: {restored}"
    with closing(sqlite3.connect(restored)) as copy:
        assert copy.execute("SELECT REFERENCE FROM REPORTS").fetchall() == [("WAL-COMMITTED",)]
    assert backup_window.db_file == str(source)
    _assert_no_staging(tmp_path)


@pytest.mark.parametrize("collision", ["source", "existing_file", "sqlite_sidecar"])
def test_file_backup_refuses_occupied_destination(tmp_path, monkeypatch, backup_window, collision):
    source = tmp_path / "active.sqlite"
    _make_active_snapshot(source)
    assert backup_window.set_db_file(str(source))
    source_bytes = source.read_bytes()
    destination = source if collision == "source" else tmp_path / "backup.sqlite"
    if collision == "existing_file":
        destination.write_bytes(b"existing database")
    if collision == "sqlite_sidecar":
        sidecar = destination.with_suffix(".sqlite-wal")
        sidecar.write_bytes(b"existing sidecar")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(destination), ""))
    _backup_action(backup_window).trigger()
    dialog = backup_window.window_coordinator.get("backup_database")
    dialog.destination_button.click()
    dialog.restore_button.click()
    _wait_until(lambda: dialog._worker is None)
    expected_error = {
        "source": "different from the source database",
        "existing_file": "Destination already exists",
        "sqlite_sidecar": "SQLite sidecar already exists",
    }
    assert expected_error[collision] in dialog.status.text()
    assert source.read_bytes() == source_bytes
    if collision == "existing_file":
        assert destination.read_bytes() == b"existing database"
    if collision == "sqlite_sidecar":
        assert sidecar.read_bytes() == b"existing sidecar" and not destination.exists()
    _assert_no_staging(tmp_path)


def test_active_backup_finishes_with_frozen_source_after_database_change(tmp_path, monkeypatch, backup_window):
    source, replacement = tmp_path / "active.sqlite", tmp_path / "other.sqlite"
    destination = tmp_path / "backup.sqlite"
    _make_active_snapshot(source)
    _make_active_snapshot(replacement)
    with closing(sqlite3.connect(replacement)) as connection, connection:
        connection.execute("UPDATE REPORTS SET REFERENCE = 'OTHER-DATABASE'")
    assert backup_window.set_db_file(str(source))
    entered, proceed = Event(), Event()

    def hold_copy(*args, **kwargs):
        entered.set()
        assert proceed.wait(5)
        return publish_verified_database_copy(*args, **kwargs)

    monkeypatch.setattr(database_restore_dialog, "publish_verified_database_copy", hold_copy)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(destination), ""))
    _backup_action(backup_window).trigger()
    coordinator = backup_window.window_coordinator
    dialog = coordinator.get("backup_database")
    dialog.destination_button.click()
    dialog.restore_button.click()
    try:
        _wait_until(entered.is_set)
        assert backup_window.set_db_file(str(replacement))
        assert dialog.is_close_deferred()
    finally:
        proceed.set()
        _wait_until(lambda: coordinator.get("backup_database") is None)
    with closing(sqlite3.connect(destination)) as copy:
        assert copy.execute("SELECT REFERENCE FROM REPORTS").fetchall() == [("REF-LEGACY",)]
    assert backup_window.db_file == str(replacement)


def _start_database_copy(window, monkeypatch, mode, source, destination, *, upgrade=False):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(destination), ""))
    if mode == "backup_database":
        _backup_action(window).trigger()
    else:
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(source), ""))
        next(action for action in window.file_menu.actions() if action.text() == "Restore database copy…").trigger()
    dialog = window.window_coordinator.get(mode)
    if dialog.source_button is not None:
        dialog.source_button.click()
    dialog.destination_button.click()
    if upgrade:
        dialog.upgrade_checkbox.click()
    dialog.restore_button.click()
    return dialog


def test_file_open_routes_historical_database_to_explicit_upgraded_copy(tmp_path, monkeypatch, backup_window):
    source = tmp_path / "historical.sqlite"
    destination = tmp_path / "upgraded.sqlite"
    _make_legacy_snapshot(source)
    warnings = []
    monkeypatch.setattr("metroliza.ui.main_window.QMessageBox.warning", lambda *args: warnings.append(args[2]))
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO REPORTS VALUES (8, 'WAL-COMMITTED')")
        writer.commit()
        wal = source.with_name(source.name + "-wal")
        before = source.read_bytes(), wal.read_bytes()
        assert backup_window.set_db_file(str(source)) is False
        assert not backup_window.db_file
        assert len(warnings) == 1 and "Upgrade to the current Reports schema" in warnings[0]

        dialog = _start_database_copy(
            backup_window, monkeypatch, "restore_database", source, destination, upgrade=True,
        )
        _wait_until(lambda: dialog._worker is None)
        assert "Upgraded copy created and verified" in dialog.status.text()
        assert (source.read_bytes(), wal.read_bytes()) == before

    assert backup_window.set_db_file(str(destination))
    with closing(sqlite3.connect(destination)) as upgraded:
        assert upgraded.execute("SELECT reference FROM vw_report_overview ORDER BY report_id").fetchall() == [
            ("REF-LEGACY",), ("WAL-COMMITTED",),
        ]


def test_industrial_picker_keeps_previous_target_when_reports_rejects_historical_wal(
    tmp_path, monkeypatch, backup_window,
):
    previous = tmp_path / "active.sqlite"
    source = tmp_path / "historical.sqlite"
    _make_active_snapshot(previous)
    _make_legacy_snapshot(source)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    warnings = []
    monkeypatch.setattr("metroliza.ui.main_window.QMessageBox.warning", lambda *args: warnings.append(args[2]))
    assert backup_window.set_db_file(str(previous))
    backup_window.launch_industrial_data_dialog()
    dialog = backup_window.industrial_data_dialog
    old_target = dialog.cache_target
    old_status = dialog.status_label.text()
    old_sync_filter, old_export_filter = dialog.sync_filter_state, dialog.export_filter_state
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))

    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("INSERT INTO REPORTS VALUES (8, 'COMMITTED')")
        writer.commit()
        wal = source.with_name(source.name + "-wal")
        before = source.read_bytes(), wal.read_bytes()

        dialog.select_database_file()

        assert writer.execute(
            "SELECT name FROM sqlite_schema WHERE name LIKE 'industrial_%'"
        ).fetchall() == []
        assert (source.read_bytes(), wal.read_bytes()) == before
    assert len(warnings) == 1 and "Upgrade to the current Reports schema" in warnings[0]
    assert backup_window.db_file == dialog.db_file == dialog.report_db_file == str(previous)
    assert dialog.cache_target is old_target
    assert dialog.status_label.text() == old_status
    assert dialog.sync_filter_state is old_sync_filter and dialog.export_filter_state is old_export_filter
    assert _migration_recoveries(tmp_path) == []


@pytest.mark.parametrize("upgrade", [False, True])
def test_restore_rejects_the_selected_source_replaced_before_dispatch(tmp_path, monkeypatch, backup_window, upgrade):
    source = tmp_path / "chosen.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    destination = tmp_path / "destination.sqlite"
    _make_legacy_snapshot(source)
    _make_legacy_snapshot(replacement)
    with closing(sqlite3.connect(replacement)) as connection, connection:
        connection.execute("UPDATE REPORTS SET REFERENCE='REPLACEMENT-ONLY'")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    backup_window._launch_database_restore()
    dialog = backup_window.window_coordinator.get("restore_database")
    dialog.source_button.click()
    dialog.destination_button.click()
    if upgrade:
        dialog.upgrade_checkbox.click()
    original = source.rename(tmp_path / "original.sqlite")
    replacement.replace(source)
    before = original.read_bytes(), source.read_bytes()

    dialog.restore_button.click()
    _wait_until(lambda: dialog._worker is None)

    assert not destination.exists()
    assert "replaced or removed" in dialog.status.text()
    assert (original.read_bytes(), source.read_bytes()) == before


def test_main_selection_does_not_recover_industrial_staging_in_a_replacement(
    tmp_path, monkeypatch, backup_window,
):
    previous = tmp_path / "active.sqlite"
    source = tmp_path / "chosen.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    _make_active_snapshot(previous)
    _make_active_snapshot(source)
    _make_legacy_snapshot(replacement)
    assert backup_window.set_db_file(str(previous))
    real_recovery = backup_window._recover_abandoned_realtime_staging
    before = source.read_bytes(), replacement.read_bytes()
    original = tmp_path / "original.sqlite"
    monkeypatch.setattr("metroliza.ui.main_window.QMessageBox.warning", lambda *args: None)

    def replace_before_recovery(*args, **kwargs):
        source.replace(original)
        replacement.replace(source)
        return real_recovery(*args, **kwargs)

    monkeypatch.setattr(backup_window, "_recover_abandoned_realtime_staging", replace_before_recovery)
    assert not backup_window.set_db_file(str(source))
    assert backup_window.db_file == str(previous)
    assert (original.read_bytes(), source.read_bytes()) == before


def test_cancelled_industrial_picker_keeps_its_temporary_cache_and_candidate_unchanged(
    tmp_path, monkeypatch, backup_window,
):
    candidate = tmp_path / "candidate.sqlite"
    _make_active_snapshot(candidate)
    before = candidate.read_bytes()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    backup_window.launch_industrial_data_dialog()
    dialog = backup_window.industrial_data_dialog
    prior_target = dialog.cache_target
    assert prior_target.is_temporary
    status = dialog.status_label.text()
    calls = []

    def cancel(target, **kwargs):
        calls.append(target)
        return False

    monkeypatch.setattr(dialog, "_resolve_temporary_cache_before_discard", cancel)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(candidate), ""))
    dialog.select_database_file()

    assert calls == [prior_target]
    assert not backup_window.db_file
    assert dialog.cache_target is prior_target and Path(dialog.db_file).is_file()
    assert dialog.report_db_file is None and dialog.status_label.text() == status
    assert candidate.read_bytes() == before


def test_realtime_rebind_does_not_adopt_replacement_during_session_resolution(
    tmp_path, monkeypatch, backup_window,
):
    candidate = tmp_path / "chosen.sqlite"
    original = tmp_path / "original.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    _make_active_snapshot(candidate)
    _make_legacy_snapshot(replacement)
    replacement_bytes = replacement.read_bytes()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    backup_window.launch_realtime_industrial_monitoring_dialog()
    monitor = backup_window.realtime_monitoring_dialog
    session = Path(monitor.db_file)
    assert monitor.temporary_session
    monkeypatch.setattr("metroliza.ui.main_window.QMessageBox.warning", lambda *args: None)
    moved_bytes = []

    def replace_during_resolution(**kwargs):
        moved_bytes.append(candidate.read_bytes())
        candidate.replace(original)
        replacement.replace(candidate)
        return True, None

    with monkeypatch.context() as selection:
        selection.setattr(backup_window, "_resolve_realtime_session_before_discard", replace_during_resolution)
        assert backup_window.set_db_file(str(candidate))

    assert str(session) == monitor.db_file and monitor.temporary_session and session.is_file()
    assert [original.read_bytes()] == moved_bytes
    assert candidate.read_bytes() == replacement_bytes
    assert not backup_window._export_ready
    assert not backup_window._report_export_start_allowed(str(candidate))


@pytest.mark.parametrize("refresh", ["automatic", "later"])
def test_realtime_event_refresh_keeps_selected_database_identity(tmp_path, monkeypatch, backup_window, refresh):
    from metroliza.ui.realtime_industrial_monitoring_dialog import RealtimeIndustrialMonitoringDialog

    chosen = tmp_path / "chosen.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    original = tmp_path / "original.sqlite"
    _make_active_snapshot(chosen)
    _make_legacy_snapshot(replacement)
    replacement_bytes = replacement.read_bytes()
    assert backup_window.set_db_file(str(chosen))
    real_apply = RealtimeIndustrialMonitoringDialog._apply_loaded_database_state
    before = []

    def replace_database():
        before.append(chosen.read_bytes())
        chosen.replace(original)
        replacement.replace(chosen)

    def replace_before_apply(dialog, state):
        replace_database()
        real_apply(dialog, state)

    with monkeypatch.context() as patch:
        if refresh == "automatic":
            patch.setattr(RealtimeIndustrialMonitoringDialog, "_apply_loaded_database_state", replace_before_apply)
        backup_window.launch_realtime_industrial_monitoring_dialog()
    monitor = backup_window.realtime_monitoring_dialog
    if refresh == "later":
        replace_database()
        monitor.refresh_event_review()

    assert chosen.read_bytes() == replacement_bytes
    assert [original.read_bytes()] == before
    assert "replaced or removed" in monitor.event_review_status_label.text()


@pytest.mark.parametrize("worker_kind", ["dashboard", "poll", "fetch", "export", "links"])
def test_industrial_workers_do_not_open_a_replacement(tmp_path, qapplication_session, worker_kind):
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.industrial.industrial_workers import (
        IndustrialExportThread,
        IndustrialLinkRefreshThread,
        IndustrialOznakSyncThread,
        RealtimeDashboardWriterThread,
        RealtimeMonitorPollThread,
    )
    from metroliza.industrial.industrial_workflow_state import IndustrialFilterState, IndustrialGroupingState

    chosen = tmp_path / "chosen.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    output = tmp_path / "output"
    _make_active_snapshot(chosen)
    _make_legacy_snapshot(replacement)
    binding = SQLiteFileBinding.capture(chosen)
    options = {"db_file": str(chosen), **selected_reports_worker_options(str(chosen), binding)}
    if worker_kind == "dashboard":
        worker = RealtimeDashboardWriterThread(output_file=str(output.with_suffix(".html")), **options)
    elif worker_kind == "poll":
        worker = RealtimeMonitorPollThread(configs=(), **options)
    elif worker_kind == "links":
        worker = IndustrialLinkRefreshThread(**options)
    elif worker_kind == "export":
        worker = IndustrialExportThread(
            output_file=str(output.with_suffix(".xlsx")), filter_state=IndustrialFilterState(),
            grouping_state=IndustrialGroupingState(), include_charts=False, **options,
        )
    else:
        profile = IndustrialDataRepository(str(chosen)).upsert_source_profile(
            profile_key="synthetic", profile_name="Synthetic", database_type="sqlite",
            source_db_alias="synthetic", source_object_name="events",
        )
        worker = IndustrialOznakSyncThread(
            profile=profile, username="", password="", limit=1, timeout_seconds=1,
            reference_filter_column=None, reference_values=(), test_only=False,
            report_db_file=str(chosen), **options,
        )
    original = chosen.rename(tmp_path / "original.sqlite")
    replacement.replace(chosen)
    before = original.read_bytes(), chosen.read_bytes()
    errors = []
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert len(errors) == 1 and "replaced or removed" in errors[0]
    assert (original.read_bytes(), chosen.read_bytes()) == before
    assert not list(tmp_path.glob("output.*"))
    assert _migration_recoveries(tmp_path) == []


def test_industrial_rejected_cache_cannot_initialize_or_configure(tmp_path, monkeypatch, backup_window):
    chosen = tmp_path / "chosen.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    _make_active_snapshot(chosen)
    _make_legacy_snapshot(replacement)
    assert backup_window.set_db_file(str(chosen))
    backup_window.launch_industrial_data_dialog()
    dialog = backup_window.industrial_data_dialog
    original = chosen.rename(tmp_path / "original.sqlite")
    replacement.replace(chosen)
    before = original.read_bytes(), chosen.read_bytes()
    monkeypatch.setattr("metroliza.ui.industrial_data_dialog.QMessageBox.warning", lambda *args: None)
    monkeypatch.setattr(
        "metroliza.ui.industrial_source_profiles_dialog.IndustrialSourceProfilesDialog.exec", lambda self: None,
    )

    dialog.refresh_status()
    enabled = dialog.initialize_cache_action.isEnabled(), dialog.sources_button.isEnabled()
    dialog.initialize_cache()
    dialog.open_sources_dialog()

    assert (original.read_bytes(), chosen.read_bytes()) == before
    assert enabled == (False, False)
    assert dialog.select_database_button.isEnabled()


@pytest.mark.parametrize(
    ("operation", "dialog_type"),
    [
        ("open_sync_dialog", "IndustrialSyncDialog"),
        ("open_export_dialog", "IndustrialExportDialog"),
        ("open_links_dialog", "IndustrialLinkingDialog"),
    ],
)
def test_industrial_children_do_not_initialize_a_replacement(
    tmp_path, monkeypatch, backup_window, operation, dialog_type,
):
    from metroliza.ui import industrial_data_dialog

    chosen = tmp_path / "chosen.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    _make_active_snapshot(chosen)
    _make_legacy_snapshot(replacement)
    assert backup_window.set_db_file(str(chosen))
    backup_window.launch_industrial_data_dialog()
    dialog = backup_window.industrial_data_dialog
    assert dialog.sync_button.isEnabled()
    original = chosen.rename(tmp_path / "original.sqlite")
    replacement.replace(chosen)
    before = original.read_bytes(), chosen.read_bytes()
    monkeypatch.setattr(getattr(industrial_data_dialog, dialog_type), "exec", lambda self: None)

    getattr(dialog, operation)()

    assert (original.read_bytes(), chosen.read_bytes()) == before
    assert _migration_recoveries(tmp_path) == []
    assert not dialog.sync_button.isEnabled()
    assert not dialog.export_button.isEnabled()
    assert not dialog.links_button.isEnabled()
    assert dialog.select_database_button.isEnabled()


def test_absent_reports_selection_cannot_open_a_borrowed_connection(tmp_path, monkeypatch):
    from metroliza.reports import db

    destination = tmp_path / "uncreated.sqlite"
    binding = SQLiteFileBinding.capture(destination)

    def unexpected_open(*args, **kwargs):
        pytest.fail("A borrowed SQLite connection was opened for an absent selection")

    monkeypatch.setattr(db.sqlite3, "connect", unexpected_open)
    with pytest.raises(db.DatabaseSourceChanged, match="has not been created"):
        with db.sqlite_selected_reports_connection_scope(str(destination), binding):
            pytest.fail("An absent selection was borrowed")
    assert not destination.exists()


def test_selected_reports_connection_commits_industrial_writes(tmp_path):
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.reports.db import sqlite_selected_reports_connection_scope

    destination = tmp_path / "selected.sqlite"
    ensure_report_schema(str(destination))
    binding = SQLiteFileBinding.capture(destination)

    with sqlite_selected_reports_connection_scope(str(destination), binding) as connection:
        IndustrialDataRepository(str(destination), connection=connection).upsert_source_profile(
            profile_key="synthetic", profile_name="Synthetic", database_type="sqlite",
            source_db_alias="synthetic", source_object_name="events",
        )

    with closing(sqlite3.connect(destination)) as reader:
        assert reader.execute("SELECT profile_key FROM industrial_source_profiles").fetchall() == [("synthetic",)]


def test_industrial_does_not_adopt_database_appearing_after_reports_save_selection(
    tmp_path, monkeypatch, backup_window,
):
    destination = tmp_path / "new-reports.sqlite"
    workspace = backup_window.launch_parsing_dialog()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))

    workspace.select_database()
    assert backup_window.db_file == str(destination) and not destination.exists()
    backup_window.launch_realtime_industrial_monitoring_dialog()
    monitor = backup_window.realtime_monitoring_dialog
    assert monitor.temporary_session and Path(monitor.db_file).is_file()
    assert not destination.exists()
    _make_legacy_snapshot(destination)
    with closing(sqlite3.connect(destination)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("INSERT INTO REPORTS VALUES (8, 'REPLACEMENT-ONLY')")
        writer.commit()
        wal = destination.with_name(destination.name + "-wal")
        before = destination.read_bytes(), wal.read_bytes()

        backup_window.launch_industrial_data_dialog()

        assert writer.execute(
            "SELECT name FROM sqlite_schema WHERE name LIKE 'industrial_%'"
        ).fetchall() == []
        assert (destination.read_bytes(), wal.read_bytes()) == before
    dialog = backup_window.industrial_data_dialog
    assert not dialog.initialize_cache_action.isEnabled()
    assert dialog.select_database_button.isEnabled()


@pytest.mark.parametrize("mode", ["backup_database", "restore_database"])
@pytest.mark.parametrize(
    "alias_kind", ["normalized_path", "same_parent_inode", "same_parent_mixed_case", "dangling_symlink"],
)
def test_copy_destination_cannot_be_adopted_until_publication_finishes(
    tmp_path, monkeypatch, backup_window, mode, alias_kind,
):
    source = tmp_path / "active.sqlite"
    chosen = tmp_path / "copy"
    destination = chosen.with_suffix(".db")
    alternate = tmp_path / "alternate"
    alternate.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    alias = alternate / ".." / destination.name
    if alias_kind != "normalized_path":
        alias = alternate / destination.name
        if alias_kind == "same_parent_mixed_case":
            alias = alias.with_name(alias.name.upper())
        elif alias_kind == "dangling_symlink":
            alias = tmp_path / "link.db"
            try:
                alias.symlink_to(alternate / destination.name)
            except OSError:
                pytest.skip("database symlink creation unavailable")
            assert alias.is_symlink() and not alias.exists()
        real_samefile = Path.samefile

        def samefile(path, other):
            if path == alternate and other == tmp_path:
                return True
            return real_samefile(path, other)

        monkeypatch.setattr(Path, "samefile", samefile)
    _make_active_snapshot(source)
    assert backup_window.set_db_file(str(source))
    entered, proceed = Event(), Event()

    def hold_copy(source, destination, *, validate, **kwargs):
        def hold_verified_snapshot(staging):
            validate(staging)
            entered.set()
            assert proceed.wait(5)

        return publish_verified_database_copy(source, destination, validate=hold_verified_snapshot, **kwargs)

    monkeypatch.setattr(database_restore_dialog, "publish_verified_database_copy", hold_copy)
    dialog = _start_database_copy(backup_window, monkeypatch, mode, source, chosen)
    try:
        _wait_until(entered.is_set)
        assert not destination.exists()
        assert backup_window.set_db_file(str(alias)) is False
        assert not dialog.owns_destination(alternate / "unrelated.db")
        assert not dialog.owns_destination(unrelated / destination.name.upper())
        assert backup_window.db_file == str(source)
        assert not dialog.is_close_deferred()
    finally:
        proceed.set()
        _wait_until(lambda: dialog._worker is None)
    with closing(sqlite3.connect(destination)) as copy:
        assert copy.execute("SELECT REFERENCE FROM REPORTS").fetchall() == [("REF-LEGACY",)]
    assert backup_window.set_db_file(str(destination))
    assert backup_window.db_file == str(destination)


@pytest.mark.parametrize("mode", ["backup_database", "restore_database"])
@pytest.mark.parametrize("departure", ["database_change", "application_close", "database_picker_after_failure"])
def test_deferred_copy_failure_notifies_main_window(tmp_path, monkeypatch, backup_window, mode, departure):
    source, replacement = tmp_path / "current.sqlite", tmp_path / "other.sqlite"
    destination = tmp_path / "private-synthetic-destination.sqlite"
    _make_active_snapshot(source)
    _make_active_snapshot(replacement)
    assert backup_window.set_db_file(str(source))
    backup_window.show()
    entered, proceed = Event(), Event()

    def late_conflict(source, destination, *, validate, **kwargs):
        def lose_publication_race(staging):
            validate(staging)
            entered.set()
            assert proceed.wait(5)
            Path(destination).write_bytes(b"another writer kept its output")

        return publish_verified_database_copy(source, destination, validate=lose_publication_race, **kwargs)

    monkeypatch.setattr(database_restore_dialog, "publish_verified_database_copy", late_conflict)
    dialog = _start_database_copy(backup_window, monkeypatch, mode, source, destination)
    failure_controls = []
    dialog.copy_failed_on_close.connect(lambda: failure_controls.append(dialog.restore_button.isEnabled()))
    try:
        _wait_until(entered.is_set)
        if departure == "database_change":
            assert backup_window.set_db_file(str(replacement))
            assert dialog.is_close_deferred()
        elif departure == "database_picker_after_failure":
            def finish_copy_and_pick_database(*_args):
                proceed.set()
                _wait_until(lambda: dialog._worker is None)
                assert "Destination already exists" in dialog.status.text()
                assert backup_window.window_coordinator.get(mode) is dialog
                assert failure_controls == []
                return str(replacement), ""

            monkeypatch.setattr(QFileDialog, "getOpenFileName", finish_copy_and_pick_database)
            backup_window.open_database_action.trigger()
        else:
            assert backup_window.close() is False
            assert dialog.is_close_deferred()
    finally:
        proceed.set()
        _wait_until(lambda: dialog._worker is None)
    notice = backup_window.workspace_notice_label
    assert "database copy failed" in notice.text().lower()
    assert not notice.isHidden() and notice.property("statusVariant") == "warning"
    assert failure_controls == [False]
    assert destination.name not in notice.text() and str(tmp_path) not in notice.text()
    _wait_until(lambda: backup_window.window_coordinator.get(mode) is None)
    assert backup_window.isVisible()
    active = source if departure == "application_close" else replacement
    assert backup_window.db_file == str(active)
    assert destination.read_bytes() == b"another writer kept its output"

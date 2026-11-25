"""Synthetic tests of the report restore admission and publication boundary."""

from contextlib import closing
import sqlite3

import pytest
from PyQt6.QtWidgets import QFileDialog

from metroliza.industrial.industrial_cache_target import publish_verified_database_copy
from metroliza.reports.report_schema import SCHEMA_TABLE_STATEMENTS, ensure_report_schema
from metroliza.ui.database_restore_dialog import DatabaseRestoreDialog, _validate_report_snapshot


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

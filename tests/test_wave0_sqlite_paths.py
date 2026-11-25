"""#1159: database browsing preserves the exact selected file."""

from contextlib import closing
import os
import sqlite3
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.skipif(not hasattr(os, "pathconf"), reason="requires a POSIX name-length limit")
@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
def test_long_database_name_preserves_existing_readable_and_wal_files(tmp_path, journal_mode):
    from metroliza.reports.db import (
        _is_transient_sqlite_error, sqlite_connection_scope, sqlite_readonly_connection_scope,
    )

    limit = os.pathconf(tmp_path, "PC_NAME_MAX")
    if limit <= 12:
        pytest.skip("filesystem does not have a usable component-length limit")
    short = tmp_path / "source.db"
    with closing(sqlite3.connect(short)) as connection:
        connection.execute("CREATE TABLE sample (value INTEGER)")
        connection.execute("INSERT INTO sample VALUES (7)")
        connection.commit()
        if journal_mode == "wal":
            assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)

    final = tmp_path / ("a" * (limit - 10) + ".db")
    short.rename(final)
    original = final.read_bytes()
    with sqlite_readonly_connection_scope(str(final)) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == (7,)
    if journal_mode == "delete":
        with pytest.raises(sqlite3.OperationalError, match="shorter database filename") as failure:
            with sqlite_connection_scope(str(final)):
                pytest.fail("SQLite must leave the old database unchanged")
        assert not _is_transient_sqlite_error(failure.value)
        assert isinstance(failure.value.__cause__, sqlite3.OperationalError)
        assert final.read_bytes() == original
    else:
        with sqlite_connection_scope(str(final)) as connection:
            connection.execute("UPDATE sample SET value = 8")
            connection.commit()
        with sqlite_connection_scope(str(final)) as connection:
            assert connection.execute("SELECT value FROM sample").fetchone() == (8,)
    assert list(tmp_path.iterdir()) == [final]


@pytest.mark.skipif(not hasattr(os, "pathconf"), reason="requires a POSIX name-length limit")
def test_new_database_reserves_journal_name_space_before_creating_the_file(tmp_path):
    from metroliza.reports.db import sqlite_connection_scope

    limit = os.pathconf(tmp_path, "PC_NAME_MAX")
    if limit <= 12:
        pytest.skip("filesystem does not have a usable component-length limit")
    final = tmp_path / ("a" * (limit - 10) + ".db")
    with pytest.raises(sqlite3.OperationalError, match="shorter database filename"):
        with sqlite_connection_scope(str(final)):
            pytest.fail("the path should be rejected before the database is created")
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(not hasattr(os, "pathconf"), reason="requires a POSIX name-length limit")
@pytest.mark.parametrize("nested", [False, True])
def test_snapshot_reports_long_destination_before_writing(tmp_path, nested):
    from metroliza.shared.sqlite_snapshot import publish_database_snapshot

    limit = os.pathconf(tmp_path, "PC_NAME_MAX")
    if limit <= 12:
        pytest.skip("filesystem does not have a usable component-length limit")
    source = tmp_path / "source.db"
    source.touch()
    target_dir = tmp_path / "new" if nested else tmp_path
    destination = target_dir / ("a" * (limit - 10) + ".db")
    with pytest.raises(ValueError, match="shorter database filename"):
        publish_database_snapshot(
            source, destination, write_snapshot=lambda _: pytest.fail("unexpected write"),
        )
    assert list(path for path in tmp_path.rglob("*") if path.is_file()) == [source]


@pytest.mark.parametrize("suffix", [".sqlite", ".sqlite3", ".DB", ".db", ""])
def test_existing_sqlite_path_is_exact_and_browsing_creates_nothing(tmp_path, suffix):
    from metroliza.shared.sqlite_paths import sqlite_database_path

    selected = tmp_path / f"quality{suffix}"
    selected.write_bytes(b"existing database")
    before = set(tmp_path.iterdir())
    assert sqlite_database_path(str(selected)) == str(selected)
    assert sqlite_database_path(str(selected), creating=True) == str(selected)
    assert set(tmp_path.iterdir()) == before


def test_new_extensionless_sqlite_name_only_gets_db_when_creating(tmp_path):
    from metroliza.shared.sqlite_paths import sqlite_database_path

    name = str(tmp_path / "new")
    assert sqlite_database_path(name) == name
    assert sqlite_database_path(name, creating=True) == f"{name}.db"
    assert sqlite_database_path(f"{name}.custom", creating=True) == f"{name}.custom.db"
    assert not list(tmp_path.iterdir())


def test_source_directory_default_can_propose_a_new_sibling_database(tmp_path):
    from metroliza.shared.sqlite_paths import sqlite_database_path

    source = tmp_path / "reports"
    source.mkdir()
    assert sqlite_database_path(str(source), creating=True) == f"{source}.db"
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("name", ["Line 1.2", "run.v2", "quality.custom", "RUN.SQLITE3", "line.DB"])
def test_new_sqlite_names_append_db_only_for_unrecognized_suffix(tmp_path, name):
    from metroliza.shared.sqlite_paths import SQLITE_SUFFIXES, sqlite_database_path
    from pathlib import Path

    selected = str(tmp_path / name)
    expected = selected if Path(name).suffix.lower() in SQLITE_SUFFIXES else f"{selected}.db"
    assert sqlite_database_path(selected, creating=True) == expected
    assert sqlite_database_path(selected) == selected
    assert not list(tmp_path.iterdir())
    Path(selected).write_bytes(b"existing NOK SQLite sentinel")
    assert sqlite_database_path(selected, creating=True) == selected


@pytest.mark.parametrize("caller", ["export", "parsing", "modify", "mapping"])
@pytest.mark.parametrize("suffix", [".sqlite", ".sqlite3", ".DB"])
def test_database_chooser_preserves_selected_existing_file(monkeypatch, tmp_path, caller, suffix):
    from metroliza.ui import characteristic_mapping_dialog, export_dialog, modify_db, parsing_dialog

    selected = tmp_path / f"quality{suffix}"
    selected.write_bytes(b"NOK database sentinel")
    seen = []
    fields = SimpleNamespace(setText=lambda value: seen.append(value))
    host = SimpleNamespace(
        db_file="", directory=str(tmp_path), database_change_allowed=None,
        _external_context=True, database_change_requested=SimpleNamespace(emit=seen.append),
        parent=lambda: None, log_and_exit=lambda error: pytest.fail(str(error)),
        _update_database_context=lambda path: seen.append(path) or True,
        has_pending_changes=lambda: False, apply_button=SimpleNamespace(setEnabled=lambda _: None),
        db_path_input=fields, load_aliases=lambda: None, load_source_options=lambda: None,
    )
    open_database = Mock(return_value=(str(selected), ""))
    monkeypatch.setattr(export_dialog.QFileDialog, "getOpenFileName", open_database)
    monkeypatch.setattr(export_dialog.QFileDialog, "getSaveFileName", lambda *a: (str(selected), ""))
    monkeypatch.setattr(modify_db.ModifyDB, "_refresh_tables_for_view", lambda instance: seen.append(instance.db_file))
    monkeypatch.setattr(characteristic_mapping_dialog, "_alias_csv_busy", lambda _: False)
    methods = {
        "export": export_dialog.ExportDialog.select_db_file,
        "parsing": parsing_dialog._ReportOperations.select_database,
        "modify": modify_db.ModifyDB.select_db_file,
        "mapping": characteristic_mapping_dialog.CharacteristicMappingDialog.select_db_file,
    }
    if caller == "export":
        host._settings_locked = MethodType(export_dialog.ExportDialog._settings_locked, host)
        host.is_export_active = MethodType(export_dialog.ExportDialog.is_export_active, host)
        host.export_thread = None
        host._export_starting = False
        host._report_workspace_busy = False
        for lock_flag in ("_export_starting", "_report_workspace_busy"):
            setattr(host, lock_flag, True)
            methods[caller](host)
            setattr(host, lock_flag, False)
        open_database.assert_not_called()

    methods[caller](host)
    assert str(selected) in seen
    assert set(tmp_path.iterdir()) == {selected}

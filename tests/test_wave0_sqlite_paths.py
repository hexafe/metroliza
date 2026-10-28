"""#1159: database browsing preserves the exact selected file."""

from types import SimpleNamespace

import pytest


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
    assert sqlite_database_path(f"{name}.custom", creating=True) == f"{name}.custom"
    assert not list(tmp_path.iterdir())


def test_source_directory_default_can_propose_a_new_sibling_database(tmp_path):
    from metroliza.shared.sqlite_paths import sqlite_database_path

    source = tmp_path / "reports"
    source.mkdir()
    assert sqlite_database_path(str(source), creating=True) == f"{source}.db"
    assert list(tmp_path.iterdir()) == [source]


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
    monkeypatch.setattr(export_dialog.QFileDialog, "getOpenFileName", lambda *a: (str(selected), ""))
    monkeypatch.setattr(export_dialog.QFileDialog, "getSaveFileName", lambda *a: (str(selected), ""))
    monkeypatch.setattr(modify_db.ModifyDB, "_refresh_tables_for_view", lambda instance: seen.append(instance.db_file))
    monkeypatch.setattr(characteristic_mapping_dialog, "_alias_csv_busy", lambda _: False)
    methods = {
        "export": export_dialog.ExportDialog.select_db_file,
        "parsing": parsing_dialog._ReportOperations.select_database,
        "modify": modify_db.ModifyDB.select_db_file,
        "mapping": characteristic_mapping_dialog.CharacteristicMappingDialog.select_db_file,
    }
    methods[caller](host)
    assert str(selected) in seen
    assert set(tmp_path.iterdir()) == {selected}

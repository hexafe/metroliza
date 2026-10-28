"""#1159: database browsing preserves the exact selected file."""

from types import SimpleNamespace

import pytest


from PyQt6 import QtCore as _REAL_QTCORE, QtGui as _REAL_QTGUI, QtWidgets as _REAL_QTWIDGETS  # noqa: E402

# Captured at collection time, before any isolated suite can replace them in sys.modules.
_REAL_QT_MODULES = {
    "PyQt6.QtCore": _REAL_QTCORE,
    "PyQt6.QtGui": _REAL_QTGUI,
    "PyQt6.QtWidgets": _REAL_QTWIDGETS,
}
_QT_NAMES = ("QDialog", "QFileDialog", "QWidget", "QObject", "QThread", "QMessageBox", "QTimer")


def _purge_stub_bound_modules():
    """Drop metroliza/legacy modules still bound to Qt stubs left by earlier isolated tests.

    Some suites import UI modules while PyQt6 is stubbed; if a stale module (or its
    parent-package binding) survives, ``from metroliza.ui import export_dialog`` would
    return classes such as ``QFileDialog = object``. These regressions need the real
    modules, so stale ones are removed and re-imported on demand.
    """
    import sys

    QtCore, QtWidgets = _REAL_QTCORE, _REAL_QTWIDGETS
    real = {name: getattr(QtWidgets, name, None) or getattr(QtCore, name, None) for name in _QT_NAMES}
    stale = [
        name for name, module in tuple(sys.modules.items())
        if module is not None and name.startswith(("metroliza.", "modules."))
        and any(name_ in vars(module) and vars(module)[name_] is not real[name_] for name_ in _QT_NAMES)
    ]
    for name in stale:
        sys.modules.pop(name, None)
        package_name, _, attr = name.rpartition(".")
        package = sys.modules.get(package_name)
        if package is not None and attr in vars(package):
            delattr(package, attr)


@pytest.fixture(autouse=True)
def _real_qt_bound_modules(monkeypatch):
    import sys

    for name, module in _REAL_QT_MODULES.items():
        if sys.modules.get(name) is not module:
            monkeypatch.setitem(sys.modules, name, module)
    _purge_stub_bound_modules()
    yield
    _purge_stub_bound_modules()


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

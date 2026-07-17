from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from metroliza.industrial.industrial_cache_target import (
    IndustrialCacheTarget,
    cleanup_temporary_industrial_cache,
    create_temporary_industrial_cache_target,
    disposable_cache_counts,
    persist_temporary_industrial_cache,
    temporary_cache_has_data,
)
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_source_config import (
    build_source_profile,
    upsert_source_profile_in_config,
)


_QT_APP = None


def _qapplication():
    global _QT_APP
    from PyQt6.QtWidgets import QApplication

    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _populate_cache(database: str) -> None:
    repository = IndustrialDataRepository(database)
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="line_a",
        database_type="sqlite",
        source_object_name="events",
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=({"source_record_key": "row-1", "measurement": 12.5},),
    )


def test_failed_snapshot_does_not_replace_existing_destination(tmp_path):
    source = tmp_path / "invalid-source.sqlite"
    source.write_bytes(b"not a sqlite database")
    destination = tmp_path / "existing.sqlite"
    original = b"existing cache must survive"
    destination.write_bytes(original)
    target = IndustrialCacheTarget(
        mode="temporary",
        cache_db_file=str(source),
        is_temporary=True,
    )

    with pytest.raises(Exception):
        persist_temporary_industrial_cache(target, destination)

    assert destination.read_bytes() == original
    assert list(tmp_path.glob(".existing.sqlite.*.saving")) == []


def test_snapshot_refuses_to_replace_reserved_workspace_database(tmp_path):
    target = create_temporary_industrial_cache_target()
    workspace_db = tmp_path / "reports.db"
    try:
        _populate_cache(target.cache_db_file)
        with closing(sqlite3.connect(workspace_db)) as connection, connection:
            connection.execute("CREATE TABLE report_marker (value TEXT NOT NULL)")
            connection.execute("INSERT INTO report_marker VALUES ('keep-me')")

        with pytest.raises(ValueError, match="active Metroliza database"):
            persist_temporary_industrial_cache(
                target,
                workspace_db,
                forbidden_destinations=(workspace_db,),
            )

        with closing(sqlite3.connect(workspace_db)) as connection:
            marker = connection.execute("SELECT value FROM report_marker").fetchone()[0]
            cache_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'industrial_records'"
            ).fetchone()
        assert marker == "keep-me"
        assert cache_table is None
    finally:
        cleanup_temporary_industrial_cache(target)


def test_temporary_cache_snapshot_preserves_operator_data(tmp_path):
    target = create_temporary_industrial_cache_target()
    source_path = Path(target.cache_db_file)
    destination = tmp_path / "saved-cache.sqlite"
    try:
        assert not temporary_cache_has_data(target)
        _populate_cache(target.cache_db_file)

        assert temporary_cache_has_data(target)
        assert disposable_cache_counts(target.cache_db_file)["industrial_records"] == 1

        persisted = persist_temporary_industrial_cache(target, destination)

        assert persisted.is_temporary is False
        assert persisted.cache_db_file == str(destination.resolve())
        assert IndustrialDataRepository(str(destination)).summarize_counts().records == 1
    finally:
        cleanup_temporary_industrial_cache(target)
    assert not source_path.exists()


def test_profile_and_sync_metadata_are_treated_as_disposable_operator_data():
    target = create_temporary_industrial_cache_target()
    try:
        repository = IndustrialDataRepository(target.cache_db_file)
        profile = repository.upsert_source_profile(
            profile_key="line_a",
            profile_name="Line A",
            source_db_alias="line_a",
            database_type="sqlite",
            source_object_name="events",
        )
        repository.create_sync_run(source_profile_id=profile.id)

        counts = disposable_cache_counts(target.cache_db_file)

        assert counts["industrial_source_profiles"] == 1
        assert counts["industrial_sync_runs"] == 1
        assert counts["industrial_sync_staging_records"] == 0
        assert temporary_cache_has_data(target)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_exact_yaml_profile_copy_does_not_trigger_temporary_data_prompt(
    tmp_path,
    monkeypatch,
):
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QMessageBox

    import metroliza.ui.industrial_data_dialog as dialog_module

    config_path = tmp_path / "industrial_sources.yaml"
    upsert_source_profile_in_config(
        config_path,
        build_source_profile(
            profile_key="line_a",
            profile_name="Line A",
            source_db_alias="line_a",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
        ),
    )
    monkeypatch.setattr(
        dialog_module,
        "default_industrial_source_config_path",
        lambda: config_path,
    )
    _qapplication()
    dialog = dialog_module.IndustrialDataDialog(db_file=None)
    cache_path = Path(dialog.db_file)
    try:
        assert disposable_cache_counts(dialog.db_file)["industrial_source_profiles"] == 1
        assert not any(dialog._temporary_cache_lifecycle_counts(dialog.cache_target).values())
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("derived YAML profile must not prompt")
            ),
        )

        assert dialog.close()
        assert not cache_path.exists()
    finally:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
        )
        dialog.close()


def test_populated_temporary_cache_requires_explicit_close_decision(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QMessageBox

    from metroliza.ui.industrial_data_dialog import IndustrialDataDialog

    _qapplication()
    dialog = IndustrialDataDialog(db_file=None)
    _populate_cache(dialog.db_file)
    dialog.refresh_status()
    try:
        assert "will be deleted" in dialog.storage_lifecycle_label.text()
        assert dialog.storage_lifecycle_label.property("statusVariant") == "danger"

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
        )
        assert dialog._resolve_temporary_cache_before_discard(dialog.cache_target) is False
        assert Path(dialog.db_file).exists()

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
        )
        assert dialog._resolve_temporary_cache_before_discard(dialog.cache_target) is True
    finally:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
        )
        dialog.close()


def test_unreadable_temporary_cache_requires_explicit_discard(monkeypatch):
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QMessageBox

    from metroliza.ui.industrial_data_dialog import IndustrialDataDialog

    _qapplication()
    dialog = IndustrialDataDialog(db_file=None)
    cache_path = Path(dialog.db_file)
    cache_path.write_bytes(b"not a sqlite database")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
    )

    assert dialog.close() is False
    assert cache_path.exists()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    assert dialog.close() is True
    assert not cache_path.exists()


def test_save_cache_as_keeps_temporary_rows(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QFileDialog

    from metroliza.ui.industrial_data_dialog import IndustrialDataDialog

    _qapplication()
    destination = tmp_path / "saved-cache.db"
    dialog = IndustrialDataDialog(db_file=None)
    source_path = Path(dialog.db_file)
    _populate_cache(dialog.db_file)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(destination), "SQLite database"),
    )
    try:
        dialog.create_database_file()

        assert dialog.cache_target.is_temporary is False
        assert dialog.db_file == str(destination.resolve())
        assert not source_path.exists()
        assert IndustrialDataRepository(dialog.db_file).summarize_counts().records == 1
        assert "Durable storage" in dialog.storage_lifecycle_label.text()
    finally:
        dialog.close()


def test_dialog_save_paths_cannot_replace_active_workspace_database(
    tmp_path,
    monkeypatch,
):
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    from metroliza.ui.industrial_data_dialog import IndustrialDataDialog

    _qapplication()
    workspace_db = tmp_path / "reports.db"
    with closing(sqlite3.connect(workspace_db)) as connection, connection:
        connection.execute("CREATE TABLE report_marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO report_marker VALUES ('keep-me')")
    dialog = IndustrialDataDialog(db_file=str(workspace_db))
    dialog.use_temporary_cache()
    _populate_cache(dialog.db_file)
    warnings: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(workspace_db), "SQLite database"),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    try:
        temporary_db = dialog.db_file

        dialog.create_database_file()

        assert dialog.db_file == temporary_db
        assert Path(temporary_db).exists()
        assert warnings
        with closing(sqlite3.connect(workspace_db)) as connection:
            assert connection.execute("SELECT value FROM report_marker").fetchone()[0] == "keep-me"

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Save,
        )
        assert dialog._resolve_temporary_cache_before_discard(dialog.cache_target) is False
        with closing(sqlite3.connect(workspace_db)) as connection:
            assert connection.execute("SELECT value FROM report_marker").fetchone()[0] == "keep-me"

        incoming_db = tmp_path / "incoming.db"
        with closing(sqlite3.connect(incoming_db)) as connection, connection:
            connection.execute("CREATE TABLE incoming_marker (value TEXT NOT NULL)")
            connection.execute("INSERT INTO incoming_marker VALUES ('keep-incoming')")
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *_args, **_kwargs: (str(incoming_db), "SQLite database"),
        )

        assert dialog.update_db_file(str(incoming_db)) is False
        assert dialog.db_file == temporary_db
        with closing(sqlite3.connect(incoming_db)) as connection:
            marker = connection.execute("SELECT value FROM incoming_marker").fetchone()[0]
        assert marker == "keep-incoming"
    finally:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
        )
        dialog.close()

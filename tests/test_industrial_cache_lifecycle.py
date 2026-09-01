from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace

import pytest

import metroliza.industrial.industrial_cache_target as cache_target_module
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


def _write_marker_database(path: Path) -> bytes:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES ('preserve-me')")
    return path.read_bytes()


def _assert_no_staging_artifacts(destination: Path) -> None:
    assert list(destination.parent.glob(f".{destination.name}.*.saving")) == []


def test_failed_snapshot_does_not_create_destination(tmp_path):
    source = tmp_path / "invalid-source.sqlite"
    source.write_bytes(b"not a sqlite database")
    destination = tmp_path / "new.sqlite"
    target = IndustrialCacheTarget(
        mode="temporary",
        cache_db_file=str(source),
        is_temporary=True,
    )

    with pytest.raises(Exception):
        persist_temporary_industrial_cache(target, destination)

    assert not destination.exists()
    _assert_no_staging_artifacts(destination)


def test_snapshot_preserves_existing_sqlite_destination_by_default(tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "existing.sqlite"
    try:
        _populate_cache(target.cache_db_file)
        original = _write_marker_database(destination)

        with pytest.raises(FileExistsError, match="already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert destination.read_bytes() == original
        _assert_no_staging_artifacts(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_snapshot_preserves_existing_non_sqlite_destination_by_default(tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "existing.sqlite"
    original = b"unrelated industrial measurements\x00\xff"
    destination.write_bytes(original)
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(FileExistsError, match="already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert destination.read_bytes() == original
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_artifacts(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_extension_normalization_cannot_bypass_existing_destination(tmp_path):
    target = create_temporary_industrial_cache_target()
    selected = tmp_path / "existing-cache"
    destination = Path(f"{selected}.db")
    original = b"do not replace after extension normalization"
    destination.write_bytes(original)
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(FileExistsError, match="already exists"):
            persist_temporary_industrial_cache(target, selected)

        assert destination.read_bytes() == original
        assert not selected.exists()
    finally:
        cleanup_temporary_industrial_cache(target)


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


def test_snapshot_refuses_source_and_hard_link_alias_destinations(tmp_path):
    target = create_temporary_industrial_cache_target()
    source = Path(target.cache_db_file)
    hard_link = tmp_path / "source-alias.sqlite"
    try:
        _populate_cache(target.cache_db_file)
        original = source.read_bytes()
        with pytest.raises(ValueError, match="outside the temporary cache"):
            persist_temporary_industrial_cache(target, source)
        try:
            os.link(source, hard_link)
        except OSError as exc:
            pytest.skip(f"hard links are unavailable: {exc}")

        with pytest.raises(ValueError, match="outside the temporary cache"):
            persist_temporary_industrial_cache(target, hard_link)

        assert source.read_bytes() == original
        assert hard_link.read_bytes() == original
    finally:
        cleanup_temporary_industrial_cache(target)


def test_snapshot_refuses_forbidden_hard_link_alias(tmp_path):
    target = create_temporary_industrial_cache_target()
    forbidden = tmp_path / "active.db"
    alias = tmp_path / "active-alias.db"
    original = _write_marker_database(forbidden)
    try:
        _populate_cache(target.cache_db_file)
        try:
            os.link(forbidden, alias)
        except OSError as exc:
            pytest.skip(f"hard links are unavailable: {exc}")

        with pytest.raises(ValueError, match="active Metroliza database"):
            persist_temporary_industrial_cache(
                target,
                alias,
                forbidden_destinations=(forbidden,),
            )

        assert forbidden.read_bytes() == original
        assert alias.read_bytes() == original
    finally:
        cleanup_temporary_industrial_cache(target)


def test_snapshot_refuses_symlink_and_non_regular_destinations(tmp_path):
    target = create_temporary_industrial_cache_target()
    symlink = tmp_path / "destination.sqlite"
    symlink_target = tmp_path / "symlink-target.sqlite"
    directory = tmp_path / "cache-directory.sqlite"
    directory.mkdir()
    try:
        _populate_cache(target.cache_db_file)
        try:
            symlink.symlink_to(symlink_target)
        except OSError as exc:
            pytest.skip(f"symbolic links are unavailable: {exc}")

        with pytest.raises(ValueError, match="symbolic link|reparse point"):
            persist_temporary_industrial_cache(target, symlink)
        with pytest.raises(ValueError, match="regular file"):
            persist_temporary_industrial_cache(target, directory)

        assert symlink.is_symlink()
        assert not symlink_target.exists()
        assert directory.is_dir()
    finally:
        cleanup_temporary_industrial_cache(target)


def test_reparse_point_detection_is_platform_bounded(monkeypatch):
    reparse_flag = 0x400
    monkeypatch.setattr(
        cache_target_module.stat,
        "FILE_ATTRIBUTE_REPARSE_POINT",
        reparse_flag,
        raising=False,
    )
    status = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=reparse_flag)

    assert cache_target_module._is_symlink_or_reparse(status)


@pytest.mark.parametrize("suffix", ("-wal", "-shm", "-journal"))
def test_existing_destination_sidecars_block_publication(tmp_path, suffix):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "new.sqlite"
    sidecar = Path(f"{destination}{suffix}")
    original = b"foreign SQLite sidecar"
    sidecar.write_bytes(original)
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(FileExistsError, match="sidecar already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert not destination.exists()
        assert sidecar.read_bytes() == original
        assert Path(target.cache_db_file).exists()
    finally:
        cleanup_temporary_industrial_cache(target)


def test_destination_created_during_backup_blocks_publication(monkeypatch, tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "raced.sqlite"
    raced_bytes = b"destination created during backup"
    real_backup = cache_target_module.backup_sqlite_database

    def backup_with_race(source, staging):
        real_backup(source, staging)
        destination.write_bytes(raced_bytes)

    monkeypatch.setattr(cache_target_module, "backup_sqlite_database", backup_with_race)
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(FileExistsError, match="already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert destination.read_bytes() == raced_bytes
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_artifacts(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


@pytest.mark.parametrize("suffix", ("-wal", "-shm", "-journal"))
def test_sidecar_created_during_backup_blocks_publication(
    monkeypatch,
    tmp_path,
    suffix,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "raced.sqlite"
    sidecar = Path(f"{destination}{suffix}")
    raced_bytes = b"sidecar created during backup"
    real_backup = cache_target_module.backup_sqlite_database

    def backup_with_race(source, staging):
        real_backup(source, staging)
        sidecar.write_bytes(raced_bytes)

    monkeypatch.setattr(cache_target_module, "backup_sqlite_database", backup_with_race)
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(FileExistsError, match="sidecar already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert not destination.exists()
        assert sidecar.read_bytes() == raced_bytes
        _assert_no_staging_artifacts(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes are unavailable")
def test_posix_staging_directory_and_database_are_private_without_umask(
    monkeypatch,
    tmp_path,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "private.sqlite"
    real_backup = cache_target_module.backup_sqlite_database
    real_publish = cache_target_module._atomic_publish_no_replace
    observed: dict[str, int] = {}

    def backup_with_permissive_mode(source, staging):
        observed["directory"] = stat.S_IMODE(Path(staging).parent.stat().st_mode)
        real_backup(source, staging)
        os.chmod(staging, 0o644)

    def observe_staging(staging, final_destination):
        observed["staging"] = stat.S_IMODE(Path(staging).stat().st_mode)
        real_publish(staging, final_destination)

    monkeypatch.setattr(cache_target_module, "backup_sqlite_database", backup_with_permissive_mode)
    monkeypatch.setattr(cache_target_module, "_atomic_publish_no_replace", observe_staging)
    monkeypatch.setattr(
        cache_target_module.os,
        "umask",
        lambda _mode: (_ for _ in ()).throw(AssertionError("must not change process umask")),
    )
    try:
        _populate_cache(target.cache_db_file)

        persist_temporary_industrial_cache(target, destination)

        assert observed == {"directory": 0o700, "staging": 0o600}
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    finally:
        cleanup_temporary_industrial_cache(target)


def test_posix_publication_uses_atomic_hard_link(monkeypatch, tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "posix.sqlite"
    real_link = os.link
    calls = []

    def observed_link(source, final_destination):
        calls.append((Path(source), Path(final_destination)))
        real_link(source, final_destination)

    monkeypatch.setattr(cache_target_module, "_PUBLICATION_PLATFORM", "posix")
    monkeypatch.setattr(cache_target_module.os, "link", observed_link)
    try:
        _populate_cache(target.cache_db_file)

        persist_temporary_industrial_cache(target, destination)

        assert len(calls) == 1
        assert calls[0][1] == destination
    finally:
        cleanup_temporary_industrial_cache(target)


def test_windows_publication_uses_atomic_no_replace_rename(monkeypatch, tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "windows.sqlite"
    real_link = os.link
    calls = []

    def fake_windows_rename(source, final_destination):
        source_path = Path(source)
        final_path = Path(final_destination)
        calls.append((source_path, final_path))
        if final_path.exists():
            raise FileExistsError(final_path)
        real_link(source_path, final_path)
        source_path.unlink()

    monkeypatch.setattr(cache_target_module, "_PUBLICATION_PLATFORM", "nt")
    monkeypatch.setattr(cache_target_module.os, "rename", fake_windows_rename)
    try:
        _populate_cache(target.cache_db_file)

        persist_temporary_industrial_cache(target, destination)

        assert len(calls) == 1
        assert calls[0][1] == destination
    finally:
        cleanup_temporary_industrial_cache(target)


def test_unsupported_publication_primitive_fails_closed(monkeypatch, tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "unsupported.sqlite"
    monkeypatch.setattr(cache_target_module, "_PUBLICATION_PLATFORM", "posix")
    monkeypatch.setattr(
        cache_target_module.os,
        "link",
        lambda *_args: (_ for _ in ()).throw(OSError("hard links unsupported")),
    )
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(RuntimeError, match="atomic no-replace"):
            persist_temporary_industrial_cache(target, destination)

        assert not destination.exists()
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_artifacts(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_successful_commit_has_no_post_publication_rollback(monkeypatch, tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "committed.sqlite"
    sidecar = Path(f"{destination}-wal")
    real_publish = cache_target_module._atomic_publish_no_replace

    def publish_then_external_sidecar(staging, final_destination):
        real_publish(staging, final_destination)
        sidecar.write_bytes(b"external actor after commit")

    monkeypatch.setattr(
        cache_target_module,
        "_atomic_publish_no_replace",
        publish_then_external_sidecar,
    )
    try:
        _populate_cache(target.cache_db_file)

        persisted = persist_temporary_industrial_cache(target, destination)

        assert persisted.cache_db_file == str(destination.resolve())
        assert destination.exists()
        assert sidecar.read_bytes() == b"external actor after commit"
    finally:
        cleanup_temporary_industrial_cache(target)


def test_permission_failure_cleans_only_staging_and_preserves_source(monkeypatch, tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX permissions are unavailable")
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "permission-failure.sqlite"
    monkeypatch.setattr(
        cache_target_module.os,
        "fchmod",
        lambda *_args: (_ for _ in ()).throw(PermissionError("permission denied")),
    )
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(RuntimeError, match="private staging permissions"):
            persist_temporary_industrial_cache(target, destination)

        assert not destination.exists()
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_artifacts(destination)
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

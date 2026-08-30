from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

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


def _write_marker_database(path: Path, value: str = "preserve-me") -> bytes:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE unrelated_marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated_marker VALUES (?)", (value,))
    return path.read_bytes()


def _assert_no_staging_files(destination: Path) -> None:
    assert list(destination.parent.glob(f".{destination.name}.*.saving*")) == []


def test_failed_snapshot_does_not_create_destination(tmp_path):
    source = tmp_path / "invalid-source.sqlite"
    source.write_bytes(b"not a sqlite database")
    destination = tmp_path / "new.sqlite"
    target = IndustrialCacheTarget(
        mode="temporary",
        cache_db_file=str(source),
        is_temporary=True,
    )

    with pytest.raises(sqlite3.DatabaseError):
        persist_temporary_industrial_cache(target, destination)

    assert not destination.exists()
    assert list(tmp_path.glob(".new.sqlite.*.saving")) == []


def test_snapshot_refuses_unrelated_existing_database_by_default(tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "unrelated-existing.sqlite"
    try:
        _populate_cache(target.cache_db_file)
        original = _write_marker_database(destination)

        with pytest.raises(FileExistsError, match="already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert destination.read_bytes() == original
        with closing(sqlite3.connect(destination)) as connection:
            marker = connection.execute(
                "SELECT value FROM unrelated_marker"
            ).fetchone()[0]
            cache_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'industrial_records'"
            ).fetchone()
        assert marker == "preserve-me"
        assert cache_table is None
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_snapshot_refuses_unrelated_existing_non_sqlite_bytes_by_default(tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "unrelated.bin"
    original = b"unrelated non-SQLite measurements\x00\xff"
    destination.write_bytes(original)
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(FileExistsError, match="already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert destination.read_bytes() == original
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
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


def test_snapshot_refuses_source_path_and_hard_link_alias(tmp_path):
    target = create_temporary_industrial_cache_target()
    source_path = Path(target.cache_db_file)
    hard_link = tmp_path / "source-hard-link.sqlite"
    try:
        _populate_cache(target.cache_db_file)
        original = source_path.read_bytes()
        with pytest.raises(ValueError, match="outside the temporary cache"):
            persist_temporary_industrial_cache(target, source_path)
        try:
            os.link(source_path, hard_link)
        except OSError as exc:
            pytest.skip(f"hard links are unavailable on this filesystem: {exc}")
        with pytest.raises(ValueError, match="outside the temporary cache"):
            persist_temporary_industrial_cache(target, hard_link)
        assert source_path.read_bytes() == original
        assert hard_link.read_bytes() == original
    finally:
        cleanup_temporary_industrial_cache(target)


@pytest.mark.parametrize("dangling", [False, True])
def test_snapshot_refuses_destination_symlinks_without_touching_the_entry(
    tmp_path,
    dangling,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "destination.sqlite"
    symlink_target = tmp_path / "symlink-target.sqlite"
    if not dangling:
        symlink_target.write_bytes(b"preserve symlink target")
    try:
        try:
            destination.symlink_to(symlink_target)
        except OSError as exc:
            pytest.skip(f"symbolic links are unavailable on this filesystem: {exc}")
        _populate_cache(target.cache_db_file)

        with pytest.raises(ValueError, match="symbolic link|reparse point"):
            persist_temporary_industrial_cache(target, destination)

        assert destination.is_symlink()
        if dangling:
            assert not symlink_target.exists()
        else:
            assert symlink_target.read_bytes() == b"preserve symlink target"
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_snapshot_refuses_symlink_and_hard_link_aliases_of_forbidden_database(tmp_path):
    target = create_temporary_industrial_cache_target()
    forbidden = tmp_path / "active.db"
    symlink_destination = tmp_path / "active-symlink.db"
    hard_link_destination = tmp_path / "active-hard-link.db"
    original = _write_marker_database(forbidden, "active")
    try:
        _populate_cache(target.cache_db_file)
        try:
            symlink_destination.symlink_to(forbidden)
            os.link(forbidden, hard_link_destination)
        except OSError as exc:
            pytest.skip(f"filesystem aliases are unavailable: {exc}")

        with pytest.raises(ValueError, match="symbolic link|reparse point"):
            persist_temporary_industrial_cache(
                target,
                symlink_destination,
                forbidden_destinations=(forbidden,),
            )
        with pytest.raises(ValueError, match="active Metroliza database"):
            persist_temporary_industrial_cache(
                target,
                hard_link_destination,
                forbidden_destinations=(forbidden,),
            )

        assert symlink_destination.is_symlink()
        assert forbidden.read_bytes() == original
        assert hard_link_destination.read_bytes() == original
    finally:
        cleanup_temporary_industrial_cache(target)


def test_snapshot_refuses_directory_and_fifo_destinations(tmp_path):
    target = create_temporary_industrial_cache_target()
    directory = tmp_path / "cache-directory"
    directory.mkdir()
    fifo = tmp_path / "cache-fifo"
    try:
        _populate_cache(target.cache_db_file)
        with pytest.raises(ValueError, match="regular file"):
            persist_temporary_industrial_cache(target, directory)
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO creation is not supported on this platform")
        os.mkfifo(fifo)
        with pytest.raises(ValueError, match="regular file"):
            persist_temporary_industrial_cache(target, fifo)
        assert directory.is_dir()
        assert fifo.exists()
    finally:
        cleanup_temporary_industrial_cache(target)


def test_new_destination_race_is_preserved_by_atomic_no_clobber(
    monkeypatch,
    tmp_path,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "raced.sqlite"
    raced_bytes = b"destination created during backup"
    real_backup = cache_target_module._backup_sqlite_database_to_staging

    def race_backup(*args):
        staged_identity = real_backup(*args)
        destination.write_bytes(raced_bytes)
        return staged_identity

    monkeypatch.setattr(
        cache_target_module,
        "_backup_sqlite_database_to_staging",
        race_backup,
    )
    try:
        _populate_cache(target.cache_db_file)
        with pytest.raises(FileExistsError, match="already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert destination.read_bytes() == raced_bytes
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


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
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


@pytest.mark.parametrize("suffix", ("-wal", "-shm", "-journal"))
def test_destination_sidecar_created_during_backup_blocks_publication(
    monkeypatch,
    tmp_path,
    suffix,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "raced.sqlite"
    sidecar = Path(f"{destination}{suffix}")
    raced_bytes = b"sidecar created during backup"
    real_backup = cache_target_module._backup_sqlite_database_to_staging

    def race_backup(*args):
        staged_identity = real_backup(*args)
        sidecar.write_bytes(raced_bytes)
        return staged_identity

    monkeypatch.setattr(
        cache_target_module,
        "_backup_sqlite_database_to_staging",
        race_backup,
    )
    try:
        _populate_cache(target.cache_db_file)
        with pytest.raises(FileExistsError, match="sidecar already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert not destination.exists()
        assert sidecar.read_bytes() == raced_bytes
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_destination_sidecar_created_during_publication_rolls_back_owned_main(
    monkeypatch,
    tmp_path,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "publication-race.sqlite"
    sidecar = Path(f"{destination}-wal")
    raced_bytes = b"sidecar created as the main database was published"
    real_publish = cache_target_module._atomic_publish_no_replace

    def publish_with_sidecar(staging, final_destination):
        real_publish(staging, final_destination)
        sidecar.write_bytes(raced_bytes)

    monkeypatch.setattr(
        cache_target_module,
        "_atomic_publish_no_replace",
        publish_with_sidecar,
    )
    try:
        _populate_cache(target.cache_db_file)
        with pytest.raises(FileExistsError, match="sidecar already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert not destination.exists()
        assert sidecar.read_bytes() == raced_bytes
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


@pytest.mark.parametrize("failure_kind", ["backup", "validation", "sidecar-cleanup"])
def test_prepublication_failures_leave_destination_absent(
    monkeypatch,
    tmp_path,
    failure_kind,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / f"{failure_kind}.sqlite"
    real_backup = cache_target_module._backup_sqlite_database_to_staging
    failure_calls = []

    if failure_kind == "backup":

        def failing_backup(_source, staging, *_guard):
            failure_calls.append(failure_kind)
            Path(staging).write_bytes(b"partial backup")
            raise sqlite3.OperationalError("backup failed")

        expected_exception = sqlite3.OperationalError
        expected_message = "backup failed"
        monkeypatch.setattr(
            cache_target_module,
            "_backup_sqlite_database_to_staging",
            failing_backup,
        )
    elif failure_kind == "validation":

        def failing_validation(_source, staging, *_guard):
            failure_calls.append(failure_kind)
            Path(staging).write_bytes(b"invalid completed snapshot")
            raise RuntimeError("SQLite backup failed integrity validation")

        expected_exception = RuntimeError
        expected_message = "integrity validation"
        monkeypatch.setattr(
            cache_target_module,
            "_backup_sqlite_database_to_staging",
            failing_validation,
        )
    else:

        def backup_with_sidecars(*args):
            failure_calls.append(failure_kind)
            staged_identity = real_backup(*args)
            staging = args[1]
            Path(f"{staging}-wal").write_bytes(b"wal")
            Path(f"{staging}-shm").write_bytes(b"shm")
            Path(f"{staging}-journal").write_bytes(b"journal")
            return staged_identity

        def failing_cleanup(_staging):
            raise PermissionError("cleanup failed")

        expected_exception = PermissionError
        expected_message = "cleanup failed"
        monkeypatch.setattr(
            cache_target_module,
            "_backup_sqlite_database_to_staging",
            backup_with_sidecars,
        )
        monkeypatch.setattr(
            cache_target_module,
            "_cleanup_staging_sidecars_before_publication",
            failing_cleanup,
        )
    try:
        _populate_cache(target.cache_db_file)
        with pytest.raises(expected_exception, match=expected_message):
            persist_temporary_industrial_cache(target, destination)

        assert failure_calls == [failure_kind]
        assert not destination.exists()
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_publication_failure_preserves_destination_and_cleans_staging(
    monkeypatch,
    tmp_path,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "locked.sqlite"
    monkeypatch.setattr(
        cache_target_module,
        "_publish_snapshot_no_clobber",
        lambda *_args: (_ for _ in ()).throw(PermissionError("publication locked")),
    )
    try:
        _populate_cache(target.cache_db_file)
        with pytest.raises(PermissionError, match="publication locked"):
            persist_temporary_industrial_cache(target, destination)

        assert not destination.exists()
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_non_windows_publication_uses_atomic_hard_link(monkeypatch, tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "posix.sqlite"
    real_link = os.link
    calls = []

    def observed_link(source, final_destination):
        calls.append((Path(source), Path(final_destination)))
        real_link(source, final_destination)

    monkeypatch.setattr(cache_target_module, "_WINDOWS_ATOMIC_RENAME_NO_REPLACE", False)
    monkeypatch.setattr(cache_target_module.os, "link", observed_link)
    try:
        _populate_cache(target.cache_db_file)

        persist_temporary_industrial_cache(target, destination)

        assert len(calls) == 1
        assert calls[0][1] == destination
        assert disposable_cache_counts(destination)["industrial_records"] == 1
    finally:
        cleanup_temporary_industrial_cache(target)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are unavailable")
def test_private_staging_mode_is_published_through_atomic_hard_link(monkeypatch, tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "private.sqlite"
    real_backup = cache_target_module.backup_sqlite_database
    real_publish = cache_target_module._atomic_publish_no_replace
    staging_modes = []
    published_modes = []

    def backup_with_permissive_mode(source, staging):
        real_backup(source, staging)
        os.chmod(staging, 0o644)

    def observe_private_staging(staging, final_destination):
        staging_modes.append(stat.S_IMODE(Path(staging).stat().st_mode))
        real_publish(staging, final_destination)
        published_modes.append(stat.S_IMODE(Path(final_destination).stat().st_mode))

    monkeypatch.setattr(
        cache_target_module,
        "backup_sqlite_database",
        backup_with_permissive_mode,
    )
    monkeypatch.setattr(
        cache_target_module,
        "_atomic_publish_no_replace",
        observe_private_staging,
    )
    try:
        _populate_cache(target.cache_db_file)

        persist_temporary_industrial_cache(target, destination)

        assert staging_modes == [0o600]
        assert published_modes == [0o600]
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    finally:
        cleanup_temporary_industrial_cache(target)


@pytest.mark.skipif(os.name != "posix", reason="POSIX fchmod is unavailable")
def test_private_staging_permission_application_failure_preserves_source(
    monkeypatch,
    tmp_path,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "permission-failure.sqlite"

    def fail_fchmod(_fd, _mode):
        raise PermissionError("permission denied")

    monkeypatch.setattr(cache_target_module.os, "fchmod", fail_fchmod)
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(RuntimeError, match="private staging permissions"):
            persist_temporary_industrial_cache(target, destination)

        assert not destination.exists()
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_permission_verification_failure_removes_owned_publication(monkeypatch, tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "verification-failure.sqlite"

    def fail_permission_verification(*_args):
        raise RuntimeError("published permission verification failed")

    monkeypatch.setattr(
        cache_target_module,
        "_verify_published_destination",
        fail_permission_verification,
    )
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(RuntimeError, match="permission verification failed"):
            persist_temporary_industrial_cache(target, destination)

        assert not destination.exists()
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_permission_verification_failure_never_removes_raced_destination(
    monkeypatch,
    tmp_path,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "raced-verification.sqlite"
    raced_bytes = b"unrelated destination after publication"

    def replace_then_fail(final_destination, _expected_identity):
        final_destination.unlink()
        final_destination.write_bytes(raced_bytes)
        raise RuntimeError("published permission verification failed")

    monkeypatch.setattr(
        cache_target_module,
        "_verify_published_destination",
        replace_then_fail,
    )
    try:
        _populate_cache(target.cache_db_file)

        with pytest.raises(RuntimeError, match="permission verification failed"):
            persist_temporary_industrial_cache(target, destination)

        assert destination.read_bytes() == raced_bytes
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_windows_publication_uses_no_replace_rename_contract(monkeypatch, tmp_path):
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

    monkeypatch.setattr(cache_target_module, "_WINDOWS_ATOMIC_RENAME_NO_REPLACE", True)
    monkeypatch.setattr(cache_target_module.os, "rename", fake_windows_rename)
    try:
        _populate_cache(target.cache_db_file)

        persist_temporary_industrial_cache(target, destination)

        assert len(calls) == 1
        assert calls[0][1] == destination
        assert disposable_cache_counts(destination)["industrial_records"] == 1
    finally:
        cleanup_temporary_industrial_cache(target)


def test_windows_no_replace_race_preserves_newly_created_destination(
    monkeypatch,
    tmp_path,
):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "windows-race.sqlite"
    raced_bytes = b"created while Windows rename began"

    def fake_windows_rename(_source, final_destination):
        Path(final_destination).write_bytes(raced_bytes)
        raise FileExistsError(final_destination)

    monkeypatch.setattr(cache_target_module, "_WINDOWS_ATOMIC_RENAME_NO_REPLACE", True)
    monkeypatch.setattr(cache_target_module.os, "rename", fake_windows_rename)
    try:
        _populate_cache(target.cache_db_file)
        with pytest.raises(FileExistsError, match="already exists"):
            persist_temporary_industrial_cache(target, destination)

        assert destination.read_bytes() == raced_bytes
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
    finally:
        cleanup_temporary_industrial_cache(target)


def test_unsupported_no_replace_primitive_fails_closed(monkeypatch, tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "unsupported.sqlite"
    monkeypatch.setattr(cache_target_module, "_WINDOWS_ATOMIC_RENAME_NO_REPLACE", False)
    monkeypatch.setattr(
        cache_target_module.os,
        "link",
        lambda *_args: (_ for _ in ()).throw(OSError("hard links unsupported")),
    )
    try:
        _populate_cache(target.cache_db_file)
        with pytest.raises(RuntimeError, match="required atomic no-replace"):
            persist_temporary_industrial_cache(target, destination)

        assert not destination.exists()
        assert Path(target.cache_db_file).exists()
        _assert_no_staging_files(destination)
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


def test_temporary_cache_snapshot_includes_committed_wal_rows(tmp_path):
    target = create_temporary_industrial_cache_target()
    destination = tmp_path / "wal-snapshot.sqlite"
    try:
        with closing(sqlite3.connect(target.cache_db_file)) as writer:
            assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
            with writer:
                writer.execute("CREATE TABLE wal_probe (marker TEXT NOT NULL)")
                writer.execute("INSERT INTO wal_probe VALUES ('committed-row')")
            assert Path(f"{target.cache_db_file}-wal").exists()

            persist_temporary_industrial_cache(target, destination)

        with closing(sqlite3.connect(destination)) as persisted:
            assert persisted.execute("SELECT marker FROM wal_probe").fetchone() == (
                "committed-row",
            )
    finally:
        cleanup_temporary_industrial_cache(target)


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
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    try:
        temporary_db = dialog.db_file

        dialog.create_database_file()

        assert dialog.db_file == temporary_db
        assert Path(temporary_db).exists()
        assert warnings
        with closing(sqlite3.connect(workspace_db)) as connection:
            assert connection.execute("SELECT value FROM report_marker").fetchone()[0] == "keep-me"

        answers = iter(
            (QMessageBox.StandardButton.Save, QMessageBox.StandardButton.Yes)
        )
        monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: next(answers))
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
        answers = iter(
            (QMessageBox.StandardButton.Save, QMessageBox.StandardButton.Yes)
        )
        monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: next(answers))

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

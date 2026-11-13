"""Real SQLite publication regressions for temporary industrial archives."""

from __future__ import annotations

from contextlib import closing
import errno
import json
import os
from pathlib import Path
import sqlite3
import stat

import pytest

import metroliza.industrial.industrial_cache_target as cache_target


@pytest.fixture
def temporary_cache(tmp_path):
    source = tmp_path / "źródło cache.sqlite"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute(
            "CREATE TABLE samples (id INTEGER PRIMARY KEY, label TEXT NOT NULL, payload BLOB)"
        )
        connection.executemany(
            "INSERT INTO samples (id, label, payload) VALUES (?, ?, ?)",
            ((1, "line A", b"\x00source"), (2, "µnicode space ", b"\xffarchive")),
        )
        connection.commit()
    return cache_target.IndustrialCacheTarget(
        mode="temporary", cache_db_file=str(source), is_temporary=True
    )


def _database_snapshot(database: Path):
    with closing(sqlite3.connect(database)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'samples'"
        ).fetchone()[0]
        rows = connection.execute("SELECT id, label, payload FROM samples ORDER BY id").fetchall()
    return database.read_bytes(), integrity, schema, rows


def _exception_receipt(stage: str, exc: OSError) -> dict[str, int | str | None]:
    return {
        "stage": stage,
        "status": "error",
        "class": type(exc).__name__,
        "errno": exc.errno,
        "winerror": getattr(exc, "winerror", None),
    }


def _assert_no_staging(destination: Path) -> None:
    assert not list(destination.parent.glob(f".{destination.name}.*.saving"))


def test_real_backup_fsyncs_and_fstats_same_closed_descriptor_before_publish(
    monkeypatch, temporary_cache, tmp_path
):
    source = Path(temporary_cache.cache_db_file)
    destination = tmp_path / "archive µ.sqlite"
    source_snapshot = _database_snapshot(source)
    real_fsync, real_fstat = os.fsync, os.fstat
    real_publish = cache_target._atomic_publish_no_replace
    observed: dict[str, object] = {"fsync": [], "fstat": []}

    def fsync_observed(descriptor):
        try:
            real_fsync(descriptor)
        except OSError as exc:
            observed["native_failure"] = _exception_receipt("flush", exc)
            raise
        observed["fsync"].append(descriptor)

    def fstat_observed(descriptor):
        status = real_fstat(descriptor)
        observed["fstat"].append(descriptor)
        return status

    def publish_observed(staging, final):
        assert observed["fsync"] == observed["fstat"]
        descriptor = observed["fsync"][0]
        with pytest.raises(OSError) as closed:
            real_fstat(descriptor)
        observed["closed"] = _exception_receipt("descriptor", closed.value)
        real_publish(staging, final)

    monkeypatch.setattr(cache_target.os, "fsync", fsync_observed)
    monkeypatch.setattr(cache_target.os, "fstat", fstat_observed)
    monkeypatch.setattr(cache_target, "_atomic_publish_no_replace", publish_observed)

    try:
        persisted = cache_target.persist_temporary_industrial_cache(temporary_cache, destination)
    except RuntimeError:
        assert _database_snapshot(source) == source_snapshot
        assert not destination.exists()
        _assert_no_staging(destination)
        receipt = observed.get("native_failure")
        if receipt is None:
            raise
        print(json.dumps({**receipt, "source_preserved": True,
                          "destination_absent": True, "staging_removed": True}, sort_keys=True))
        pytest.fail("required native archive flush failed", pytrace=False)

    assert persisted.cache_db_file == str(destination.resolve())
    assert observed["closed"]["class"] == "OSError"
    assert _database_snapshot(source) == source_snapshot
    assert _database_snapshot(destination)[1:] == source_snapshot[1:]
    _assert_no_staging(destination)
    print(json.dumps({"stage": "publication", "status": "success",
                      "source_preserved": True, "archive_valid": True,
                      "descriptor_closed": True, "staging_removed": True}, sort_keys=True))


def test_completed_backup_handle_modes_preserve_content_and_writable_flush_succeeds(
    temporary_cache, tmp_path
):
    source = Path(temporary_cache.cache_db_file)
    completed = tmp_path / "completed.sqlite"
    source_snapshot = _database_snapshot(source)
    cache_target.backup_sqlite_database(str(source), str(completed))
    completed_bytes = completed.read_bytes()
    results = {}

    for mode in ("rb", "r+b"):
        with closing(completed.open(mode)) as handle:
            descriptor = handle.fileno()
            try:
                os.fsync(descriptor)
            except OSError as exc:
                result = _exception_receipt("handle_control", exc)
            else:
                result = {"stage": "handle_control", "status": "success",
                          "class": None, "errno": None, "winerror": None}
            assert stat.S_ISREG(os.fstat(descriptor).st_mode)
        with pytest.raises(OSError) as closed:
            os.fstat(descriptor)
        assert closed.value.errno == errno.EBADF
        assert completed.read_bytes() == completed_bytes
        results[mode] = result
        print(json.dumps({**result, "mode": mode, "fstat_regular": True,
                          "content_unchanged": True, "descriptor_closed": True}, sort_keys=True))

    assert results["r+b"]["status"] == "success"
    assert _database_snapshot(source) == source_snapshot
    assert _database_snapshot(completed)[1:] == source_snapshot[1:]


@pytest.mark.parametrize(
    ("raised", "expected_class", "expected_errno"),
    (
        (OSError(errno.EBADF, "flush failed"), "OSError", errno.EBADF),
        (OSError(errno.EIO, "flush failed"), "OSError", errno.EIO),
        (PermissionError(errno.EACCES, "flush denied"), "PermissionError", errno.EACCES),
    ),
)
def test_required_flush_failure_is_private_and_never_publishes(
    monkeypatch, temporary_cache, tmp_path, raised, expected_class, expected_errno
):
    source = Path(temporary_cache.cache_db_file)
    destination, unrelated = tmp_path / "archive.sqlite", tmp_path / "unrelated.sqlite"
    source_snapshot = _database_snapshot(source)
    unrelated_bytes = b"unrelated destination"
    unrelated.write_bytes(unrelated_bytes)
    real_fsync = os.fsync
    observed_native_error: dict[str, int | str | None] | None = None

    def fsync_transparent(descriptor):
        nonlocal observed_native_error
        try:
            real_fsync(descriptor)
        except OSError as exc:
            observed_native_error = _exception_receipt("flush", exc)
            raise
        raise raised

    monkeypatch.setattr(cache_target.os, "fsync", fsync_transparent)
    try:
        cache_target.persist_temporary_industrial_cache(temporary_cache, destination)
    except RuntimeError as public_error:
        if observed_native_error is not None:
            pytest.fail(json.dumps(observed_native_error, sort_keys=True), pytrace=False)
        cause = public_error.__cause__
    else:
        pytest.fail(
            json.dumps({"stage": "flush", "status": "unexpected-success"}), pytrace=False
        )

    assert _exception_receipt("flush", cause) == {
        "stage": "flush",
        "status": "error",
        "class": expected_class,
        "errno": expected_errno,
        "winerror": None,
    }
    assert _database_snapshot(source) == source_snapshot
    assert unrelated.read_bytes() == unrelated_bytes
    assert not destination.exists()
    _assert_no_staging(destination)


@pytest.mark.parametrize("stage", ("backup", "publish"))
def test_backup_or_publish_error_preserves_source_and_unrelated_destination(
    monkeypatch, temporary_cache, tmp_path, stage
):
    source = Path(temporary_cache.cache_db_file)
    destination, unrelated = tmp_path / "archive.sqlite", tmp_path / "unrelated.db"
    source_snapshot = _database_snapshot(source)
    unrelated_bytes = b"do not change"
    unrelated.write_bytes(unrelated_bytes)
    attribute = "backup_sqlite_database" if stage == "backup" else "_atomic_publish_no_replace"
    monkeypatch.setattr(
        cache_target,
        attribute,
        lambda *_args: (_ for _ in ()).throw(PermissionError(errno.EACCES, "denied")),
    )

    with pytest.raises(PermissionError):
        cache_target.persist_temporary_industrial_cache(temporary_cache, destination)

    assert _database_snapshot(source) == source_snapshot
    assert unrelated.read_bytes() == unrelated_bytes
    assert not destination.exists()
    _assert_no_staging(destination)


def test_commit_point_race_keeps_marker_and_source_without_replacement(
    monkeypatch, temporary_cache, tmp_path
):
    source = Path(temporary_cache.cache_db_file)
    destination = tmp_path / "raced.sqlite"
    source_snapshot, marker = _database_snapshot(source), b"final-name marker"
    platform = "nt" if os.name == "nt" else "posix"
    primitive_name = "rename" if platform == "nt" else "link"
    real_primitive = getattr(os, primitive_name)

    def race_at_commit(staging, final):
        Path(final).write_bytes(marker)
        return real_primitive(staging, final)

    monkeypatch.setattr(cache_target, "_PUBLICATION_PLATFORM", platform)
    monkeypatch.setattr(cache_target.os, primitive_name, race_at_commit)
    with pytest.raises(FileExistsError):
        cache_target.persist_temporary_industrial_cache(temporary_cache, destination)

    assert destination.read_bytes() == marker
    assert _database_snapshot(source) == source_snapshot
    _assert_no_staging(destination)


def test_cleanup_error_after_commit_keeps_correct_archive_and_reports_success(
    monkeypatch, temporary_cache, tmp_path
):
    source = Path(temporary_cache.cache_db_file)
    destination = tmp_path / "committed.sqlite"
    source_snapshot = _database_snapshot(source)
    real_unlink = Path.unlink
    real_publish = cache_target._atomic_publish_no_replace
    staging_paths: set[Path] = set()
    cleanup_denials: list[Path] = []

    def remember_publish(staging, final):
        staging_paths.add(Path(staging))
        real_publish(staging, final)

    def fail_only_staging_cleanup(path, *args, **kwargs):
        if Path(path) in staging_paths:
            cleanup_denials.append(Path(path))
            raise PermissionError(errno.EACCES, "cleanup denied")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(cache_target, "_atomic_publish_no_replace", remember_publish)
    monkeypatch.setattr(cache_target.Path, "unlink", fail_only_staging_cleanup)
    persisted = cache_target.persist_temporary_industrial_cache(temporary_cache, destination)

    assert persisted.cache_db_file == str(destination.resolve())
    assert _database_snapshot(source) == source_snapshot
    assert _database_snapshot(destination)[1:] == source_snapshot[1:]
    assert destination.exists()
    assert len(cleanup_denials) == 1
    assert set(cleanup_denials) == staging_paths
    assert all(path.exists() == (os.name != "nt") for path in staging_paths)

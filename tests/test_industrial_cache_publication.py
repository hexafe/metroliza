"""Real SQLite publication regressions for temporary industrial archives.

For issue #1006, set METROLIZA_CACHE_FS_NTFS, METROLIZA_CACHE_FS_FAT,
METROLIZA_CACHE_FS_EXFAT and METROLIZA_CACHE_FS_SMB on Windows to existing
writable, isolated scratch directories on the corresponding storage. The FAT
case records FAT or FAT32 as actually observed. Supply an explicit UNC for SMB
and use a session able to read its own connection with Get-SmbConnection.

From the clean checkout, record `git rev-parse HEAD 'HEAD^{tree}'` and run
`python -m pytest -v -s tests/test_industrial_cache_publication.py -k native_windows_cache_filesystem`.
Retain the pytest result and the cache_storage_qualification JSON line for each
storage class. For SMB, record the server implementation and whether the share
was loopback or on a separate host. A missing, skipped or failing row leaves
that class unqualified. A safe refusal qualifies only refusal on that setup.
"""

from __future__ import annotations

from contextlib import closing
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import sqlite3
import stat
import sys
from tempfile import TemporaryDirectory

import pytest

import metroliza.industrial.industrial_cache_target as cache_target
from metroliza.shared.sqlite_snapshot import SQLiteSnapshotPublicationError, atomic_publish_no_replace
from metroliza.reports import db
from tests.industrial_cache_windows_storage import windows_scratch_root, windows_storage_identity


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
    assert not list(destination.parent.glob(".metroliza-cache-*.saving"))
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


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux renameat2")
@pytest.mark.parametrize("collision", [False, True])
def test_hardlink_free_publication_uses_native_no_replace(monkeypatch, temporary_cache, tmp_path, collision):
    from metroliza.shared import sqlite_snapshot
    from metroliza.shared.atomic_file import rename_noreplace

    probe = tmp_path / "probe"
    probe.touch()
    renamed = tmp_path / "renamed"
    if not rename_noreplace(probe, renamed):
        pytest.skip("filesystem does not support renameat2 no-replace")
    renamed.unlink()

    source = Path(temporary_cache.cache_db_file)
    destination = tmp_path / "archive.sqlite"
    source_snapshot = _database_snapshot(source)
    marker = b"other writer"

    def unavailable_link(_staging, final):
        if collision:
            Path(final).write_bytes(marker)
        raise OSError(errno.EOPNOTSUPP, "hard links unavailable")

    monkeypatch.setattr(sqlite_snapshot.os, "link", unavailable_link)
    if collision:
        with pytest.raises(FileExistsError):
            cache_target.persist_temporary_industrial_cache(temporary_cache, destination)
        assert destination.read_bytes() == marker
    else:
        cache_target.persist_temporary_industrial_cache(temporary_cache, destination)
        assert _database_snapshot(destination)[1] == source_snapshot[1]
        with closing(sqlite3.connect(destination)) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
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


@pytest.mark.parametrize('stem', ['c' * 237, '測' * 78 + 'abc'], ids=['ascii-bytes', 'unicode-bytes'])
@pytest.mark.parametrize('fail', [False, True])
def test_long_cache_destination_keeps_source_and_cleans_owned_staging(temporary_cache, tmp_path, monkeypatch, stem, fail):
    destination = tmp_path / (stem + '.db')
    destination.write_bytes(b'valid directly creatable destination')
    destination.unlink()
    source = Path(temporary_cache.cache_db_file)
    before = _database_snapshot(source)
    entries = set(tmp_path.iterdir())
    if fail:
        def failed(*_args):
            raise PermissionError('cannot publish')
        monkeypatch.setattr(cache_target, '_atomic_publish_no_replace', failed)
        with pytest.raises(PermissionError):
            cache_target.persist_temporary_industrial_cache(temporary_cache, destination)
        assert not destination.exists()
        assert set(tmp_path.iterdir()) == entries
    else:
        persisted = cache_target.persist_temporary_industrial_cache(temporary_cache, destination)
        assert Path(persisted.cache_db_file) == destination
        assert _database_snapshot(destination)[1:] == before[1:]
        assert set(tmp_path.iterdir()) == entries | {destination}
        with pytest.raises(FileExistsError):
            cache_target.persist_temporary_industrial_cache(temporary_cache, destination)
        assert _database_snapshot(destination)[1:] == before[1:]
    assert _database_snapshot(source) == before


def _native_refusal(exc: RuntimeError) -> dict[str, object]:
    cause = exc.__cause__
    if not isinstance(cause, OSError):
        raise exc
    if isinstance(exc, SQLiteSnapshotPublicationError):
        stage = "rename"
    elif str(exc) == "Could not apply private staging permissions":
        stage = "flush"
    else:
        raise exc
    winerror = getattr(cause, "winerror", None)
    if winerror in {1, 17, 50, 120} or cause.errno in {errno.ENOSYS, errno.EOPNOTSUPP, errno.EXDEV}:
        reason = "unsupported_operation"
    elif winerror == 5 or (winerror is None and isinstance(cause, PermissionError)):
        reason = "permission_denied"
    else:
        raise exc
    if stage == "rename":
        assert exc.reason == reason
    return {**_exception_receipt(stage, cause), "status": "refused_safely", "reason": reason}


@pytest.mark.parametrize(("error", "reason", "message"), [
    (PermissionError(errno.EACCES, "blocked"), "permission_denied", "Permission denied"),
    (OSError(errno.EOPNOTSUPP, "unavailable"), "unsupported_operation", "does not support"),
    (OSError(errno.EIO, "failure"), "io_failed", "Could not publish"),
])
def test_publish_distinguishes_native_refusal(monkeypatch, tmp_path, error, reason, message):
    stage = tmp_path / "stage.sqlite"
    destination = tmp_path / "archive.sqlite"
    stage.write_bytes(b"untouched")

    def refuse(_stage, _destination):
        raise error

    monkeypatch.setattr(os, "rename", refuse)
    with pytest.raises(SQLiteSnapshotPublicationError, match=message) as failure:
        atomic_publish_no_replace(stage, destination, platform="nt")
    assert failure.value.reason == reason
    assert failure.value.__cause__ is error
    assert stage.read_bytes() == b"untouched"
    assert not destination.exists()


def _qualify_unused_destination(monkeypatch, target, destination, source_snapshot, storage):
    captured_staging = None
    primitive = "rename" if os.name == "nt" else "link"
    real_primitive = getattr(os, primitive)

    def observe_publication(staging, final):
        nonlocal captured_staging
        captured_staging = staging.read_bytes()
        real_primitive(staging, final)

    with monkeypatch.context() as patch:
        patch.setattr(os, primitive, observe_publication)
        try:
            archive = cache_target.persist_temporary_industrial_cache(target, destination)
        except RuntimeError as exc:
            assert not list(destination.parent.iterdir())
            if storage not in {"FAT", "EXFAT", "SMB"}:
                raise
            refusal = _native_refusal(exc)
            assert (captured_staging is not None) == (refusal["stage"] == "rename")
            return refusal
    assert archive.mode == "persistent"
    assert Path(archive.cache_db_file) == destination
    archive_bytes, *archive_contents = _database_snapshot(destination)
    assert archive_contents == list(source_snapshot[1:])
    assert captured_staging is not None and archive_bytes == captured_staging
    assert set(destination.parent.iterdir()) == {destination}
    return {"status": "published", "archive_sha256": sha256(archive_bytes).hexdigest()}


def _qualify_destination_rejections(monkeypatch, target, directory, unused_result):
    originals = {}
    precommit = {}
    marker = b"foreign destination entry"
    real_backup = cache_target.backup_sqlite_database
    for phase in ("existing", "after-backup"):
        for suffix in ("", "-wal", "-shm", "-journal"):
            destination = directory / f"{phase}{suffix}.sqlite"
            conflict = Path(f"{destination}{suffix}")

            def introduce_conflict(conflict=conflict):
                with conflict.open("xb") as handle:
                    handle.write(marker)
                originals[conflict] = marker

            def backup_with_conflict(source, staged):
                real_backup(source, staged)
                introduce_conflict()

            with monkeypatch.context() as patch:
                if phase == "existing":
                    introduce_conflict()
                else:
                    patch.setattr(cache_target, "backup_sqlite_database", backup_with_conflict)
                detail = "sidecar already exists" if suffix else "Destination already exists"
                try:
                    cache_target.persist_temporary_industrial_cache(target, destination)
                except FileExistsError as exc:
                    assert detail in str(exc)
                    result = "rejected_existing"
                except RuntimeError as exc:
                    if phase != "after-backup" or unused_result.get("stage") != "flush":
                        raise
                    if _native_refusal(exc) != unused_result:
                        raise
                    result = "not_reached"
                else:
                    pytest.fail(f"Expected the {phase} conflict for {conflict.name} to block publication")
            assert conflict in originals
            assert not suffix or not destination.exists()
            if phase == "after-backup":
                precommit[suffix or "main"] = result

    destination = directory / "at-rename.sqlite"
    primitive = "rename" if os.name == "nt" else "link"
    real_primitive = getattr(os, primitive)

    def publish_with_conflict(staged, final):
        with final.open("xb") as handle:
            handle.write(marker)
        originals[final] = marker
        real_primitive(staged, final)

    with monkeypatch.context() as patch:
        patch.setattr(os, primitive, publish_with_conflict)
        try:
            cache_target.persist_temporary_industrial_cache(target, destination)
        except FileExistsError as exc:
            assert isinstance(exc.__cause__, FileExistsError)
            late_result = {**_exception_receipt("rename", exc.__cause__), "status": "rejected_existing"}
        except RuntimeError as exc:
            late_result = _native_refusal(exc)
            if late_result["stage"] == "flush" and late_result == unused_result:
                late_result["status"] = "not_reached"
            else:
                assert late_result["stage"] == unused_result.get("stage") == "rename"
                assert late_result["reason"] == unused_result["reason"]
        else:
            pytest.fail("Publication succeeded over a filename created at the commit point")
    assert (destination in originals) == (late_result["status"] != "not_reached")
    assert set(directory.iterdir()) == set(originals)
    assert all(path.read_bytes() == original for path, original in originals.items())
    return {"precommit_collisions": precommit, "commit_point_collision": late_result}


@pytest.mark.skipif(os.name != "posix", reason="requires the native POSIX publication primitive")
def test_posix_cache_filesystem_contract(monkeypatch, temporary_cache, tmp_path):
    source = Path(temporary_cache.cache_db_file)
    source_snapshot = _database_snapshot(source)
    unused, collisions = tmp_path / "unused", tmp_path / "collisions"
    unused.mkdir()
    collisions.mkdir()
    published = _qualify_unused_destination(
        monkeypatch, temporary_cache, unused / "archive µ.sqlite", source_snapshot, "POSIX",
    )
    rejection = _qualify_destination_rejections(monkeypatch, temporary_cache, collisions, published)
    assert published["status"] == "published"
    assert rejection["precommit_collisions"] == dict.fromkeys(
        ("main", "-wal", "-shm", "-journal"), "rejected_existing",
    )
    assert rejection["commit_point_collision"]["status"] == "rejected_existing"
    assert _database_snapshot(source) == source_snapshot


@pytest.mark.parametrize(
    "later_errno",
    [errno.EOPNOTSUPP, None, errno.EACCES],
    ids=["persistent", "first-attempt-only", "different-error"],
)
def test_cache_filesystem_flush_refusal_receipt(monkeypatch, temporary_cache, tmp_path, later_errno):
    source = Path(temporary_cache.cache_db_file)
    source_snapshot = _database_snapshot(source)
    unused, collisions = tmp_path / "unused", tmp_path / "collisions"
    unused.mkdir()
    collisions.mkdir()
    real_fsync = os.fsync
    flushes = []

    def refuse_flush(descriptor):
        flushes.append(descriptor)
        error = errno.EOPNOTSUPP if len(flushes) == 1 else later_errno
        if error is not None:
            raise OSError(error, "synthetic flush refusal")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", refuse_flush)
    published = _qualify_unused_destination(
        monkeypatch, temporary_cache, unused / "archive.sqlite", source_snapshot, "FAT",
    )
    assert published == {
        "stage": "flush",
        "status": "refused_safely",
        "class": "OSError",
        "errno": errno.EOPNOTSUPP,
        "winerror": None,
        "reason": "unsupported_operation",
    }
    if later_errno == errno.EACCES:
        with pytest.raises(RuntimeError, match="Could not apply private staging permissions") as failure:
            _qualify_destination_rejections(monkeypatch, temporary_cache, collisions, published)
        assert failure.value.__cause__.errno == errno.EACCES
        _assert_no_staging(collisions / "after-backup.sqlite")
        assert _database_snapshot(source) == source_snapshot
        return

    collisions_result = _qualify_destination_rejections(
        monkeypatch, temporary_cache, collisions, published,
    )
    expected = "not_reached" if later_errno is not None else "rejected_existing"
    assert collisions_result["precommit_collisions"] == dict.fromkeys(
        ("main", "-wal", "-shm", "-journal"), expected,
    )
    commit = collisions_result["commit_point_collision"]
    assert commit["status"] == expected
    if later_errno is not None:
        assert commit == {**published, "status": "not_reached"}
    assert len(flushes) == 6  # One empty target, four late precommit markers, one commit probe.
    assert _database_snapshot(source) == source_snapshot


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows storage")
@pytest.mark.parametrize("storage", ("NTFS", "FAT", "EXFAT", "SMB"))
def test_native_windows_cache_filesystem(monkeypatch, temporary_cache, storage):
    option = f"METROLIZA_CACHE_FS_{storage}"
    if not (configured := os.environ.get(option)):
        pytest.skip(f"{option} must name an existing synthetic scratch directory")
    root = windows_scratch_root(configured, storage)
    source = Path(temporary_cache.cache_db_file)
    source_snapshot = _database_snapshot(source)
    with TemporaryDirectory(prefix="mz-cache-fs-", dir=root) as scratch:
        trial = Path(scratch).resolve(strict=True)
        identity = windows_storage_identity(trial, storage)
        print(json.dumps({"probe": "cache_storage_identity", "requested": storage, **identity}))
        unused, collisions = trial / "unused", trial / "collisions"
        unused.mkdir()
        collisions.mkdir()
        try:
            published = _qualify_unused_destination(
                monkeypatch, temporary_cache, unused / "archive µ.sqlite", source_snapshot, storage,
            )
            assert _database_snapshot(source) == source_snapshot
            print(json.dumps({
                "probe": "cache_storage_unused_destination",
                "requested": storage,
                **published,
                "source_preserved": True,
            }, sort_keys=True))
            rejection = _qualify_destination_rejections(
                monkeypatch, temporary_cache, collisions, published,
            )
        finally:
            assert _database_snapshot(source) == source_snapshot
            assert sorted(path.name for path in source.parent.iterdir()) == [source.name]
    assert not trial.exists()
    print(json.dumps({
        "probe": "cache_storage_qualification",
        "requested": storage,
        **identity,
        "windows": platform.version(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "source_sha256": sha256(source_snapshot[0]).hexdigest(),
        "unused_destination": published,
        "existing_entries_preserved": True,
        "precommit_sidecar_suffixes": [
            suffix for suffix in ("-wal", "-shm", "-journal")
            if rejection["precommit_collisions"][suffix] == "rejected_existing"
        ],
        **rejection,
        "source_preserved": True,
        "staging_removed": True,
        "scratch_removed": True,
    }, sort_keys=True))


def test_failed_backup_verification_preserves_cache_and_cleans_staging(
    monkeypatch, temporary_cache, tmp_path,
):
    source = Path(temporary_cache.cache_db_file)
    source_snapshot = _database_snapshot(source)
    destination = tmp_path / "verification-failed.sqlite"
    real_check = db.check_sqlite_integrity

    def reject_completed_backup(connection):
        real_check(connection)
        raise RuntimeError("SQLite backup failed integrity validation")

    monkeypatch.setattr(db, "check_sqlite_integrity", reject_completed_backup)
    with pytest.raises(RuntimeError, match="SQLite backup failed integrity validation"):
        cache_target.persist_temporary_industrial_cache(temporary_cache, destination)
    assert _database_snapshot(source) == source_snapshot
    assert set(tmp_path.iterdir()) == {source}

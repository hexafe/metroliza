"""Storage target helpers for industrial cache workflows."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from metroliza.reports.db import backup_sqlite_database, sqlite_connection_scope


_DISPOSABLE_COUNT_QUERIES = {
    "industrial_source_profiles": "SELECT COUNT(*) FROM industrial_source_profiles",
    "industrial_sync_runs": "SELECT COUNT(*) FROM industrial_sync_runs",
    "industrial_sync_staging_records": "SELECT COUNT(*) FROM industrial_sync_staging_records",
    "industrial_records": "SELECT COUNT(*) FROM industrial_records",
    "industrial_record_values": "SELECT COUNT(*) FROM industrial_record_values",
    "industrial_join_rules": "SELECT COUNT(*) FROM industrial_join_rules",
    "industrial_link_candidates": "SELECT COUNT(*) FROM industrial_link_candidates",
    "industrial_stream_offsets": "SELECT COUNT(*) FROM industrial_stream_offsets",
    "industrial_realtime_monitor_configs": (
        "SELECT COUNT(*) FROM industrial_realtime_monitor_configs"
    ),
    "industrial_signal_definitions": "SELECT COUNT(*) FROM industrial_signal_definitions",
    "industrial_samples": "SELECT COUNT(*) FROM industrial_samples",
    "industrial_detector_configs": "SELECT COUNT(*) FROM industrial_detector_configs",
    "industrial_baselines": "SELECT COUNT(*) FROM industrial_baselines",
    "industrial_anomaly_events": "SELECT COUNT(*) FROM industrial_anomaly_events",
    "industrial_realtime_stream_events": (
        "SELECT COUNT(*) FROM industrial_realtime_stream_events"
    ),
    "industrial_realtime_consumer_offsets": (
        "SELECT COUNT(*) FROM industrial_realtime_consumer_offsets"
    ),
    "industrial_realtime_dead_letters": (
        "SELECT COUNT(*) FROM industrial_realtime_dead_letters"
    ),
    "industrial_realtime_source_health": (
        "SELECT COUNT(*) FROM industrial_realtime_source_health"
    ),
    "industrial_model_artifacts": "SELECT COUNT(*) FROM industrial_model_artifacts",
}
_DISPOSABLE_DATA_TABLES = tuple(_DISPOSABLE_COUNT_QUERIES)


@dataclass(frozen=True)
class _FilesystemObjectIdentity:
    device: int
    inode: int
    mode: int


@dataclass(frozen=True)
class IndustrialCacheTarget:
    """Resolved SQLite target for cached industrial rows."""

    mode: str
    cache_db_file: str
    report_db_file: str | None = None
    is_temporary: bool = False

    @property
    def is_report_database(self) -> bool:
        return bool(self.report_db_file)

    @property
    def storage_label(self) -> str:
        if self.mode == "temporary":
            return "Temporary cache"
        if self.mode == "persistent":
            return "Industrial cache DB"
        return "Metroliza DB"

    @property
    def status_prefix(self) -> str:
        if self.mode == "temporary":
            return "Temporary industrial cache"
        if self.mode == "persistent":
            return "Industrial cache database"
        return "Metroliza database industrial cache"


def create_temporary_industrial_cache_target() -> IndustrialCacheTarget:
    """Create a session-scoped SQLite cache file for industrial rows."""

    temp = tempfile.NamedTemporaryFile(
        prefix="metroliza-industrial-cache-",
        suffix=".sqlite",
        delete=False,
    )
    temp.close()
    return IndustrialCacheTarget(
        mode="temporary",
        cache_db_file=temp.name,
        report_db_file=None,
        is_temporary=True,
    )


def existing_metroliza_cache_target(db_file: str | Path) -> IndustrialCacheTarget:
    path = str(db_file)
    return IndustrialCacheTarget(
        mode="existing_metroliza",
        cache_db_file=path,
        report_db_file=path,
        is_temporary=False,
    )


def persistent_industrial_cache_target(db_file: str | Path) -> IndustrialCacheTarget:
    """Return a persistent industrial cache target without report-link context."""

    path = str(db_file)
    return IndustrialCacheTarget(
        mode="persistent",
        cache_db_file=path,
        report_db_file=None,
        is_temporary=False,
    )


def cleanup_temporary_industrial_cache(target: IndustrialCacheTarget | None) -> None:
    """Remove temp SQLite cache files owned by the industrial dialog."""

    if target is None or not target.is_temporary:
        return
    for candidate in (
        Path(target.cache_db_file),
        Path(f"{target.cache_db_file}-wal"),
        Path(f"{target.cache_db_file}-shm"),
        Path(f"{target.cache_db_file}-journal"),
    ):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def disposable_cache_counts(database: str | Path) -> dict[str, int]:
    """Return persisted operator-data counts without creating or migrating a database."""

    path = Path(database)
    if not path.is_file():
        return {table: 0 for table in _DISPOSABLE_DATA_TABLES}

    counts = {table: 0 for table in _DISPOSABLE_DATA_TABLES}
    with sqlite_connection_scope(str(path)) as connection:
        with closing(connection.cursor()) as cursor:
            cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            available_tables = {str(row[0]) for row in cursor.fetchall()}
            for table in _DISPOSABLE_DATA_TABLES:
                if table not in available_tables:
                    continue
                cursor.execute(_DISPOSABLE_COUNT_QUERIES[table])
                counts[table] = int(cursor.fetchone()[0])
    return counts


def temporary_cache_has_data(target: IndustrialCacheTarget | None) -> bool:
    """Return whether a temporary target contains user-relevant persisted rows."""

    if target is None or not target.is_temporary:
        return False
    return any(disposable_cache_counts(target.cache_db_file).values())


def _destination_path(candidate: str | Path) -> Path:
    """Resolve the parent while preserving the final entry for an lstat check."""

    expanded = Path(candidate).expanduser()
    return expanded.parent.resolve(strict=False) / expanded.name


def _destination_identity(path: Path) -> _FilesystemObjectIdentity | None:
    """Return a regular destination's identity without following its final entry."""

    try:
        status = path.lstat()
    except FileNotFoundError:
        return None
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(status, "st_file_attributes", 0)
    if stat.S_ISLNK(status.st_mode) or (reparse_flag and file_attributes & reparse_flag):
        raise ValueError("Choose a destination that is not a symbolic link or reparse point")
    if not stat.S_ISREG(status.st_mode):
        raise ValueError("Choose a regular file destination")
    return _filesystem_object_identity_from_status(status)


def _filesystem_object_identity_from_status(
    status: os.stat_result,
) -> _FilesystemObjectIdentity:
    return _FilesystemObjectIdentity(status.st_dev, status.st_ino, status.st_mode)


def _directory_identity(path: Path) -> _FilesystemObjectIdentity:
    status = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(status, "st_file_attributes", 0)
    if stat.S_ISLNK(status.st_mode) or (reparse_flag and file_attributes & reparse_flag):
        raise RuntimeError("Staging directory changed before publication")
    if not stat.S_ISDIR(status.st_mode):
        raise RuntimeError("Staging directory changed before publication")
    return _filesystem_object_identity_from_status(status)


def _same_existing_file(first: Path, second: Path) -> bool:
    """Compare existing entries by filesystem identity where supported."""

    try:
        return os.path.samefile(first, second)
    except FileNotFoundError:
        return False


def _validate_destination_boundaries(
    destination_path: Path,
    source_path: Path,
    forbidden_paths: tuple[Path, ...],
) -> _FilesystemObjectIdentity | None:
    destination_identity = _destination_identity(destination_path)
    if destination_path == source_path or (
        destination_identity is not None
        and _same_existing_file(destination_path, source_path)
    ):
        raise ValueError("Choose a destination outside the temporary cache")
    for forbidden_path in forbidden_paths:
        if destination_path == forbidden_path or (
            destination_identity is not None
            and _same_existing_file(destination_path, forbidden_path)
        ):
            raise ValueError(
                "Choose a separate cache archive; an active Metroliza database cannot be replaced"
            )
    return destination_identity


_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_WINDOWS_ATOMIC_RENAME_NO_REPLACE = os.name == "nt"
_POSIX_PRIVATE_MODE_ENFORCEMENT = os.name == "posix"
_PRIVATE_STAGING_MODE = 0o600
_GROUP_OR_OTHER_PERMISSION_BITS = stat.S_IRWXG | stat.S_IRWXO


def _destination_sidecars(destination_path: Path) -> tuple[Path, ...]:
    return tuple(Path(f"{destination_path}{suffix}") for suffix in _SQLITE_SIDECAR_SUFFIXES)


def _reject_existing_destination_sidecars(destination_path: Path) -> None:
    for sidecar_path in _destination_sidecars(destination_path):
        try:
            sidecar_path.lstat()
        except FileNotFoundError:
            continue
        raise FileExistsError(f"SQLite sidecar already exists: {sidecar_path}")


def _cleanup_staging_sidecars_before_publication(staging_path: Path) -> None:
    for candidate in _destination_sidecars(staging_path):
        candidate.unlink(missing_ok=True)


def _cleanup_staging_files(staging_path: Path) -> None:
    for candidate in (
        staging_path,
        *_destination_sidecars(staging_path),
    ):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        staging_path.parent.rmdir()
    except OSError:
        pass


def _validate_staging_identity(
    staging_path: Path,
    expected_file_identity: _FilesystemObjectIdentity,
    expected_directory_identity: _FilesystemObjectIdentity,
) -> None:
    if _directory_identity(staging_path.parent) != expected_directory_identity:
        raise RuntimeError("Staging directory changed before publication")
    try:
        current_file_identity = _destination_identity(staging_path)
    except ValueError as exc:
        raise RuntimeError("Staging database changed before publication") from exc
    if current_file_identity is None or _FilesystemObjectIdentity(
        current_file_identity.device,
        current_file_identity.inode,
        current_file_identity.mode,
    ) != expected_file_identity:
        raise RuntimeError("Staging database changed before publication")


def _backup_sqlite_database_to_staging(
    source_path: Path,
    staging_path: Path,
) -> _FilesystemObjectIdentity:
    """Create, validate, and flush a bounded SQLite backup in private staging."""

    backup_sqlite_database(str(source_path), str(staging_path))
    try:
        staged_identity = _destination_identity(staging_path)
    except ValueError as exc:
        raise RuntimeError("Staging database changed during backup") from exc
    if staged_identity is None:
        raise RuntimeError("SQLite backup did not create a staging database")
    with staging_path.open("r+b") as staging_handle:
        try:
            opened_identity = _filesystem_object_identity_from_status(
                os.fstat(staging_handle.fileno())
            )
        except OSError as exc:
            raise RuntimeError("Staging database could not be verified after backup") from exc
        if opened_identity != staged_identity:
            raise RuntimeError("Staging database changed after backup")
        if _POSIX_PRIVATE_MODE_ENFORCEMENT:
            try:
                os.fchmod(staging_handle.fileno(), _PRIVATE_STAGING_MODE)
                hardened_status = os.fstat(staging_handle.fileno())
            except OSError as exc:
                raise RuntimeError("Could not apply private staging permissions") from exc
            if stat.S_IMODE(hardened_status.st_mode) != _PRIVATE_STAGING_MODE:
                raise RuntimeError("Private staging permissions could not be verified")
        else:
            try:
                hardened_status = os.fstat(staging_handle.fileno())
            except OSError as exc:
                raise RuntimeError("Staging database could not be verified after backup") from exc
        expected_identity = _filesystem_object_identity_from_status(hardened_status)
        staging_handle.flush()
        os.fsync(staging_handle.fileno())
    return expected_identity


def _published_identity(path: Path) -> _FilesystemObjectIdentity | None:
    return _destination_identity(path)


def _verify_published_destination(
    destination_path: Path,
    expected_staging_identity: _FilesystemObjectIdentity,
) -> None:
    published_identity = _published_identity(destination_path)
    if published_identity != expected_staging_identity:
        raise RuntimeError("Published destination identity could not be verified")
    if (
        _POSIX_PRIVATE_MODE_ENFORCEMENT
        and published_identity.mode & _GROUP_OR_OTHER_PERMISSION_BITS
    ):
        raise RuntimeError("Published destination must not grant group or other permissions")


def _remove_published_destination_if_owned(
    destination_path: Path,
    expected_staging_identity: _FilesystemObjectIdentity,
) -> None:
    """Remove a failed publication only while it remains our exact object."""

    try:
        is_owned_publication = (
            _published_identity(destination_path) == expected_staging_identity
        )
    except (OSError, ValueError):
        return
    if not is_owned_publication:
        return
    try:
        destination_path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RuntimeError("Could not remove failed cache publication") from exc


def _atomic_publish_no_replace(staging_path: Path, destination_path: Path) -> None:
    """Atomically publish only when the platform primitive cannot replace a target."""

    if _WINDOWS_ATOMIC_RENAME_NO_REPLACE:
        # On Windows os.rename fails when dst exists.  Sibling staging keeps this
        # same-volume, so a successful rename is atomic and no-replace.
        os.rename(staging_path, destination_path)
        return
    os.link(staging_path, destination_path)


def _publish_snapshot_no_clobber(
    staging_path: Path,
    destination_path: Path,
    expected_staging_identity: _FilesystemObjectIdentity,
) -> None:
    try:
        _atomic_publish_no_replace(staging_path, destination_path)
    except FileExistsError as exc:
        raise FileExistsError(f"Destination already exists: {destination_path}") from exc
    except OSError as exc:
        # A successful primitive followed by an interrupted return is ambiguous.
        # Treat only an identity match as committed; otherwise fail closed.
        if _published_identity(destination_path) != expected_staging_identity:
            raise RuntimeError(
                "The destination filesystem does not support the required atomic "
                f"no-replace publication: {destination_path}"
            ) from exc


def _publish_validated_snapshot(
    staging_path: Path,
    destination_path: Path,
    source_path: Path,
    forbidden_paths: tuple[Path, ...],
    expected_staging_identity: _FilesystemObjectIdentity,
    expected_directory_identity: _FilesystemObjectIdentity,
) -> None:
    _validate_staging_identity(
        staging_path,
        expected_staging_identity,
        expected_directory_identity,
    )
    if _validate_destination_boundaries(
        destination_path,
        source_path,
        forbidden_paths,
    ) is not None:
        raise FileExistsError(f"Destination already exists: {destination_path}")
    if _destination_path(destination_path) != destination_path:
        raise RuntimeError("Destination path changed before publication")
    _reject_existing_destination_sidecars(destination_path)
    try:
        _publish_snapshot_no_clobber(
            staging_path,
            destination_path,
            expected_staging_identity,
        )
        _verify_published_destination(destination_path, expected_staging_identity)
        _reject_existing_destination_sidecars(destination_path)
    except (FileExistsError, RuntimeError):
        _remove_published_destination_if_owned(
            destination_path,
            expected_staging_identity,
        )
        raise


def persist_temporary_industrial_cache(
    target: IndustrialCacheTarget,
    destination: str | Path,
    *,
    forbidden_destinations: Iterable[str | Path] = (),
) -> IndustrialCacheTarget:
    """Copy a consistent temporary SQLite snapshot into a durable target using backup."""

    if not target.is_temporary:
        raise ValueError("Only a temporary industrial cache can be saved as a durable cache")
    source_path = Path(target.cache_db_file).expanduser().resolve()
    destination_path = _destination_path(destination)
    forbidden_paths = tuple(
        _destination_path(candidate)
        for candidate in forbidden_destinations
        if str(candidate or "").strip()
    )
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    if _validate_destination_boundaries(
        destination_path,
        source_path,
        forbidden_paths,
    ) is not None:
        raise FileExistsError(f"Destination already exists: {destination_path}")
    _reject_existing_destination_sidecars(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    # Build and validate a sibling snapshot first.  A failed backup or
    # validation must never leave a partial durable cache at the final path.
    staging_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.",
            suffix=".saving",
            dir=destination_path.parent,
        )
    )
    staging_path = staging_directory / "snapshot.sqlite"
    try:
        staging_directory.chmod(0o700)
        expected_directory_identity = _directory_identity(staging_directory)
        expected_file_identity = _backup_sqlite_database_to_staging(
            source_path,
            staging_path,
        )
        _cleanup_staging_sidecars_before_publication(staging_path)
        _publish_validated_snapshot(
            staging_path,
            destination_path,
            source_path,
            forbidden_paths,
            expected_file_identity,
            expected_directory_identity,
        )
    finally:
        _cleanup_staging_files(staging_path)

    return persistent_industrial_cache_target(destination_path)


__all__ = [
    "IndustrialCacheTarget",
    "cleanup_temporary_industrial_cache",
    "create_temporary_industrial_cache_target",
    "disposable_cache_counts",
    "existing_metroliza_cache_target",
    "persist_temporary_industrial_cache",
    "persistent_industrial_cache_target",
    "temporary_cache_has_data",
]

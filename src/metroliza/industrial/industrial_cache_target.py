"""Storage target helpers for industrial cache workflows."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile

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
_SQLITE_DESTINATION_SUFFIXES = (".db", ".sqlite", ".sqlite3")
_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_DATABASE_MODE = 0o600
_PUBLICATION_PLATFORM = os.name


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


def _resolved_leaf_path(candidate: str | Path) -> Path:
    """Resolve a path's parent without following its final filesystem entry."""

    expanded = Path(candidate).expanduser()
    return expanded.parent.resolve(strict=False) / expanded.name


def resolve_industrial_cache_destination(destination: str | Path) -> Path:
    """Return the absolute, extension-normalized final cache path."""

    candidate = Path(destination).expanduser()
    if not candidate.name.lower().endswith(_SQLITE_DESTINATION_SUFFIXES):
        candidate = Path(f"{candidate}.db")
    return _resolved_leaf_path(candidate)


def _is_symlink_or_reparse(status: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(
        reparse_flag and file_attributes & reparse_flag
    )


def _existing_regular_entry(path: Path) -> bool:
    """Validate an existing entry without following its final path component."""

    try:
        status = path.lstat()
    except FileNotFoundError:
        return False
    if _is_symlink_or_reparse(status):
        raise ValueError("Choose a destination that is not a symbolic link or reparse point")
    if not stat.S_ISREG(status.st_mode):
        raise ValueError("Choose a regular file destination")
    return True


def _same_existing_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _validate_destination_absent(
    destination_path: Path,
    source_path: Path,
    forbidden_paths: tuple[Path, ...],
) -> None:
    destination_exists = _existing_regular_entry(destination_path)
    if destination_path == source_path or (
        destination_exists and _same_existing_file(destination_path, source_path)
    ):
        raise ValueError("Choose a destination outside the temporary cache")
    for forbidden_path in forbidden_paths:
        if destination_path == forbidden_path or (
            destination_exists and _same_existing_file(destination_path, forbidden_path)
        ):
            raise ValueError(
                "Choose a separate cache archive; an active Metroliza database cannot be replaced"
            )
    if destination_exists:
        raise FileExistsError(f"Destination already exists: {destination_path}")


def _sidecar_paths(database_path: Path) -> tuple[Path, ...]:
    return tuple(Path(f"{database_path}{suffix}") for suffix in _SQLITE_SIDECAR_SUFFIXES)


def _reject_existing_sidecars(destination_path: Path) -> None:
    for sidecar_path in _sidecar_paths(destination_path):
        try:
            sidecar_path.lstat()
        except FileNotFoundError:
            continue
        raise FileExistsError(f"SQLite sidecar already exists: {sidecar_path}")


def _prepare_private_staging_database(source_path: Path, staging_path: Path) -> None:
    backup_sqlite_database(str(source_path), str(staging_path))
    for sidecar_path in _sidecar_paths(staging_path):
        sidecar_path.unlink(missing_ok=True)

    try:
        with staging_path.open("rb") as staging_file:
            if _PUBLICATION_PLATFORM == "posix":
                os.fchmod(staging_file.fileno(), _PRIVATE_DATABASE_MODE)
            os.fsync(staging_file.fileno())
            opened_status = os.fstat(staging_file.fileno())
    except OSError as exc:
        raise RuntimeError("Could not apply private staging permissions") from exc
    if not stat.S_ISREG(opened_status.st_mode):
        raise RuntimeError("SQLite backup did not create a regular staging database")
    if (
        _PUBLICATION_PLATFORM == "posix"
        and stat.S_IMODE(opened_status.st_mode) != _PRIVATE_DATABASE_MODE
    ):
        raise RuntimeError("Private staging permissions could not be verified")


def _cleanup_staging_artifacts(staging_directory: Path, staging_path: Path) -> None:
    for candidate in (staging_path, *_sidecar_paths(staging_path)):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        staging_directory.rmdir()
    except OSError:
        pass


def _atomic_publish_no_replace(staging_path: Path, destination_path: Path) -> None:
    """Publish once using a platform primitive that cannot replace a destination."""

    try:
        if _PUBLICATION_PLATFORM == "nt":
            # Sibling staging keeps this same-volume. Windows os.rename rejects
            # an existing destination instead of replacing it.
            os.rename(staging_path, destination_path)
        elif _PUBLICATION_PLATFORM == "posix":
            # A hard link creates the final name only when it is still absent.
            os.link(staging_path, destination_path)
        else:
            raise RuntimeError("No supported atomic no-replace publication primitive")
    except FileExistsError as exc:
        raise FileExistsError(f"Destination already exists: {destination_path}") from exc
    except OSError as exc:
        raise RuntimeError(
            "The destination filesystem does not support the required atomic no-replace "
            f"publication: {destination_path}"
        ) from exc


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
    destination_path = resolve_industrial_cache_destination(destination)
    forbidden_paths = tuple(
        _resolved_leaf_path(candidate)
        for candidate in forbidden_destinations
        if str(candidate or "").strip()
    )
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    _validate_destination_absent(destination_path, source_path, forbidden_paths)
    _reject_existing_sidecars(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    staging_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.",
            suffix=".saving",
            dir=destination_path.parent,
        )
    )
    staging_path = staging_directory / "snapshot.sqlite"
    persistent_target = persistent_industrial_cache_target(destination_path)
    try:
        if _PUBLICATION_PLATFORM == "posix":
            staging_directory.chmod(_PRIVATE_DIRECTORY_MODE)
            if stat.S_IMODE(staging_directory.stat().st_mode) != _PRIVATE_DIRECTORY_MODE:
                raise RuntimeError("Private staging directory permissions could not be verified")
        _prepare_private_staging_database(source_path, staging_path)

        # Recheck every fallible destination condition immediately before the
        # single commit point. Nothing after a successful primitive may reject
        # or remove the published destination.
        if resolve_industrial_cache_destination(destination_path) != destination_path:
            raise RuntimeError("Destination path changed before publication")
        _validate_destination_absent(destination_path, source_path, forbidden_paths)
        _reject_existing_sidecars(destination_path)
        _atomic_publish_no_replace(staging_path, destination_path)
        return persistent_target
    finally:
        _cleanup_staging_artifacts(staging_directory, staging_path)


__all__ = [
    "IndustrialCacheTarget",
    "cleanup_temporary_industrial_cache",
    "create_temporary_industrial_cache_target",
    "disposable_cache_counts",
    "existing_metroliza_cache_target",
    "persist_temporary_industrial_cache",
    "persistent_industrial_cache_target",
    "resolve_industrial_cache_destination",
    "temporary_cache_has_data",
]

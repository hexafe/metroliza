"""Private staging and no-replace publication for verified SQLite snapshots."""

from __future__ import annotations

from collections.abc import Callable
import errno
import os
from pathlib import Path
import stat
import tempfile

from metroliza.shared.atomic_file import rename_noreplace

_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_DATABASE_MODE = 0o600


def resolved_database_leaf(candidate: str | Path) -> Path:
    """Resolve a path's parent without following its final filesystem entry."""

    expanded = Path(candidate).expanduser()
    return expanded.parent.resolve(strict=False) / expanded.name


def is_symlink_or_reparse(status: os.stat_result) -> bool:
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
    if is_symlink_or_reparse(status):
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


def _prepare_private_staging_database(staging_path, write_snapshot, platform) -> None:
    write_snapshot(staging_path)
    for sidecar_path in _sidecar_paths(staging_path):
        sidecar_path.unlink(missing_ok=True)

    try:
        # Windows requires a writable descriptor for fsync; r+b preserves the
        # completed backup without truncating it before the required flush.
        with staging_path.open("r+b") as staging_file:
            if platform == "posix":
                os.fchmod(staging_file.fileno(), _PRIVATE_DATABASE_MODE)
            os.fsync(staging_file.fileno())
            opened_status = os.fstat(staging_file.fileno())
    except OSError as exc:
        raise RuntimeError("Could not apply private staging permissions") from exc
    if not stat.S_ISREG(opened_status.st_mode):
        raise RuntimeError("SQLite backup did not create a regular staging database")
    if (
        platform == "posix"
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


def atomic_publish_no_replace(staging_path: Path, destination_path: Path, *, platform: str) -> None:
    """Publish once using a platform primitive that cannot replace a destination."""

    try:
        if platform == "nt":
            # Sibling staging keeps this same-volume. Windows os.rename rejects
            # an existing destination instead of replacing it.
            os.rename(staging_path, destination_path)
        elif platform == "posix":
            # A hard link creates the final name only when it is still absent.
            try:
                os.link(staging_path, destination_path)
            except OSError as exc:
                if exc.errno not in {errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP, errno.EMLINK}:
                    raise
                if not rename_noreplace(staging_path, destination_path):
                    raise
        else:
            raise RuntimeError("No supported atomic no-replace publication primitive")
    except FileExistsError as exc:
        raise FileExistsError(f"Destination already exists: {destination_path}") from exc
    except OSError as exc:
        raise RuntimeError(
            "The destination filesystem does not support the required atomic no-replace "
            f"publication: {destination_path}"
        ) from exc


def sync_database_parent(path: Path) -> None:
    """Flush a published filename before a dependent update on POSIX."""
    if os.name != "posix":
        return
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_database_snapshot(
    source_path: Path,
    destination_path: Path,
    *,
    write_snapshot: Callable[[Path], None],
    validate: Callable[[Path], None] | None = None,
    forbidden_paths: tuple[Path, ...] = (),
    platform: str = os.name,
    publish: Callable[[Path, Path], None] | None = None,
) -> Path:
    """Stage a verified snapshot privately and publish it at an unused filename."""
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    _validate_destination_absent(destination_path, source_path, forbidden_paths)
    _reject_existing_sidecars(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    staging_directory = Path(
        tempfile.mkdtemp(
            prefix=".metroliza-cache-",
            suffix=".saving",
            dir=destination_path.parent,
        )
    )
    staging_path = staging_directory / "snapshot.sqlite"
    try:
        if platform == "posix":
            staging_directory.chmod(_PRIVATE_DIRECTORY_MODE)
            if stat.S_IMODE(staging_directory.stat().st_mode) != _PRIVATE_DIRECTORY_MODE:
                raise RuntimeError("Private staging directory permissions could not be verified")
        _prepare_private_staging_database(staging_path, write_snapshot, platform)
        if validate is not None:
            validate(staging_path)

        # Recheck every fallible destination condition immediately before the
        # single commit point. Nothing after a successful primitive may reject
        # or remove the published destination.
        if resolved_database_leaf(destination_path) != destination_path:
            raise RuntimeError("Destination path changed before publication")
        _validate_destination_absent(destination_path, source_path, forbidden_paths)
        _reject_existing_sidecars(destination_path)
        if publish is None:
            atomic_publish_no_replace(staging_path, destination_path, platform=platform)
        else:
            publish(staging_path, destination_path)
        return destination_path
    finally:
        _cleanup_staging_artifacts(staging_directory, staging_path)

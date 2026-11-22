"""Save Reports locations and the selected page, with checked relinking."""

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import tempfile

from metroliza.exporting.output_publication import publish_output


WORKSPACE_FILTER = "Metroliza workspace (*.metroliza-workspace)"
_MAX_WORKSPACE_BYTES = 64 * 1024


@dataclass(frozen=True)
class WorkspaceLocation:
    path: str
    directory: bool
    device: int
    inode: int
    digest: str

    @classmethod
    def capture(cls, value):
        if not value:
            return None
        path = Path(value).resolve(strict=True)
        info = path.stat()
        directory = path.is_dir()
        return cls(str(path), directory, info.st_dev, info.st_ino, _fingerprint(path, directory))

    def matches(self, path):
        try:
            candidate = Path(path).resolve(strict=True)
            if self.directory != candidate.is_dir():
                return False
            info = candidate.stat()
            if info.st_ino and (self.device, self.inode) == (info.st_dev, info.st_ino):
                return True
            return self.digest == _fingerprint(candidate, self.directory)
        except (OSError, ValueError):
            return False


@dataclass(frozen=True)
class SavedWorkspace:
    page: str
    source: WorkspaceLocation | None
    database: WorkspaceLocation | None


def _file_digest(path):
    before = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("A source changed while it was being checked. Try again after the operation finishes.")
    return digest


def _fingerprint(path, directory):
    if not directory:
        # An active database may hold committed changes in its write-ahead log.
        wal = path.with_name(path.name + "-wal")
        return f"{_file_digest(path)}/{_file_digest(wal) if wal.is_file() and wal.stat().st_size else ''}"
    from metroliza.parsing.preflight import supported_report_file_extensions

    extensions = supported_report_file_extensions()
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.suffix.lower() in extensions and child.is_file() and not child.is_symlink():
            name_and_content = (child.relative_to(path).as_posix(), _file_digest(child))
            digest.update(json.dumps(name_and_content).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def write_workspace(path, snapshot, page, consents=()):
    state = SavedWorkspace(page, WorkspaceLocation.capture(snapshot.source_directory),
                           WorkspaceLocation.capture(snapshot.database_file))
    target = Path(path)
    payload = json.dumps({"version": 1, "state": asdict(state)}, ensure_ascii=False)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, mode="w", encoding="utf-8") as stream:
        staged = Path(stream.name)
    try:
        staged.write_text(payload, encoding="utf-8")
        publish_output(staged, target, consents=consents)
    finally:
        staged.unlink(missing_ok=True)
    return target


def _read_location(value):
    if value is None:
        return None
    location = WorkspaceLocation(**value)
    if not Path(location.path).is_absolute() or type(location.directory) is not bool:
        raise ValueError("The saved workspace contains an invalid location.")
    if not isinstance(location.digest, str) or not all(
        type(number) is int for number in (location.device, location.inode)
    ):
        raise ValueError("The saved workspace contains an invalid location.")
    return location


def read_workspace(filename):
    try:
        with Path(filename).open("rb") as stream:
            content = stream.read(_MAX_WORKSPACE_BYTES + 1)
        if len(content) > _MAX_WORKSPACE_BYTES:
            raise ValueError
        payload = json.loads(content)
        if payload["version"] != 1:
            raise ValueError
        state = payload["state"]
        if not isinstance(state["page"], str):
            raise ValueError
        source = _read_location(state["source"])
        database = _read_location(state["database"])
        if database is not None and database.directory:
            raise ValueError
        return SavedWorkspace(state["page"], source, database)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("This file is not a supported Metroliza workspace.") from exc

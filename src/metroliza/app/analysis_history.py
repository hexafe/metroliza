"""Private successful-run receipts and portable bundles of generated outputs."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from metroliza.exporting.output_publication import publish_output
from metroliza.shared.local_app_paths import local_metroliza_directory


_OUTPUT_SUFFIXES = {".xlsx", ".html", ".htm"}
_ASSET_SUFFIXES = {".css", ".js", ".json", ".png", ".svg", ".webp", ".jpg", ".jpeg", ".woff2"}
_MAX_RECEIPT_BYTES = 2_000_000


def _history_directory():
    return local_metroliza_directory() / "analysis-history"


def _file_stamp(path):
    entry = Path(path).stat()
    return [entry.st_dev, entry.st_ino, entry.st_size, entry.st_mtime_ns]


def _source_stamp(source):
    try:
        path = Path(source)
        wal = path.with_name(path.name + "-wal")
        live = _file_stamp(wal) if wal.is_file() and wal.stat().st_size else None
        return [_file_stamp(path), live]
    except (TypeError, OSError):
        return None


def _asset_files(directory, outputs):
    if not any(path.parent == directory.parent and path.suffix.lower() in {".htm", ".html"}
               for path in outputs):
        raise ValueError("Dashboard resources must be next to the dashboard.")
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("A dashboard resource points outside the result. Run the analysis again.")
        if path.is_file() and path.suffix.lower() in _ASSET_SUFFIXES:
            yield path.relative_to(directory.parent).as_posix(), str(path), _file_stamp(path)


def _output_entries(paths):
    values = tuple(dict.fromkeys(Path(path).absolute() for path in paths if path))
    if any(path.is_symlink() for path in values):
        raise ValueError("The result contains a shortcut instead of a published file.")
    files = [path for path in values if path.is_file() and path.suffix.lower() in _OUTPUT_SUFFIXES]
    entries = [(path.name, str(path), _file_stamp(path)) for path in files]
    for directory in (path for path in values if path.is_dir()):
        entries.extend(_asset_files(directory, files))
    return files, entries


def record_analysis(receipt, *, directory=None):
    files, entries = _output_entries(receipt["artifacts"])
    if not files:
        return None
    source = str(Path(receipt["source"]).absolute()) if receipt.get("source") else None
    timestamp = datetime.now(timezone.utc)
    name = f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex}.json"
    entry = {
        "version": 1,
        "at": timestamp.isoformat(),
        "kind": str(receipt["kind"]),
        "source": source,
        "source_stamp": receipt.get("source_stamp", _source_stamp(source)),
        "settings": receipt.get("settings", {}),
        "files": [str(path) for path in files],
        "entries": entries,
    }
    root = Path(directory) if directory is not None else _history_directory()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / name
    content = json.dumps(entry, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(content) > _MAX_RECEIPT_BYTES:
        raise ValueError("The result has too many entries to record in analysis history.")
    try:
        with tempfile.NamedTemporaryFile(dir=root, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if "temporary" in locals():
            temporary.unlink(missing_ok=True)
    return entry


def recent_analyses(*, directory=None):
    root = Path(directory) if directory is not None else _history_directory()
    for path in sorted(root.glob("*.json"), reverse=True)[:100]:
        try:
            if path.is_symlink() or path.stat().st_size > _MAX_RECEIPT_BYTES:
                continue
            with path.open("rb") as stream:
                content = stream.read(_MAX_RECEIPT_BYTES + 1)
            receipt = json.loads(content) if len(content) <= _MAX_RECEIPT_BYTES else {}
            if _readable_receipt(receipt):
                yield receipt
        except (OSError, ValueError, KeyError, TypeError):
            continue


def _readable_receipt(receipt):
    datetime.fromisoformat(receipt["at"])
    return (
        receipt["version"] == 1
        and isinstance(receipt["kind"], str)
        and isinstance(receipt["entries"], list)
        and isinstance(receipt["settings"], dict)
        and isinstance(receipt["files"], list)
        and bool(receipt["files"])
        and all(isinstance(path, str) for path in receipt["files"])
    )


def analysis_is_stale(receipt):
    source = receipt.get("source")
    stored = receipt.get("source_stamp")
    return bool(source and stored and stored != _source_stamp(source))


def _archive_member(name, raw_path, stamp):
    path = Path(raw_path)
    parts = name.split("/")
    if (not all(part and part not in {".", ".."} and "\\" not in part and ":" not in part for part in parts)
            or path.is_symlink() or not path.is_file() or _file_stamp(path) != stamp):
        raise ValueError("A result or its resources changed after export. Run the analysis again to package it.")
    return path


def _copy_to_archive(archive, name, path):
    digest = hashlib.sha256()
    with path.open("rb") as data, archive.open(name, "w", force_zip64=True) as member:
        for block in iter(lambda: data.read(1024 * 1024), b""):
            digest.update(block)
            member.write(block)
    return digest.hexdigest()


def _write_bundle(staged, entries):
    manifest = {}
    with ZipFile(staged, "w", compression=ZIP_DEFLATED, compresslevel=3) as archive:
        names = {"metroliza-results.json"}
        for name, raw_path, stamp in entries:
            if name.casefold() in names:
                raise ValueError("Two results have the same name. Save them with different names before packaging.")
            path = _archive_member(name, raw_path, stamp)
            manifest[name] = _copy_to_archive(archive, name, path)
            _archive_member(name, raw_path, stamp)
            names.add(name.casefold())
        archive.writestr("metroliza-results.json", json.dumps({"version": 1, "sha256": manifest}, indent=2))
    with ZipFile(staged) as archive:
        if archive.testzip() is not None:
            raise ValueError("The packaged outputs could not be verified.")


def bundle_analysis(receipt, destination, consents=()):
    target = Path(destination)
    entries = receipt["entries"]
    if not entries:
        raise ValueError("No published outputs are available for this analysis.")
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        staged = Path(stream.name)
    try:
        _write_bundle(staged, entries)
        publish_output(staged, target, consents=consents)
    finally:
        staged.unlink(missing_ok=True)
    return target

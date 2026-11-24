"""Bounded, local-only evidence for the report set offered to a folder recipe."""

import hashlib
import json
import os
from pathlib import Path
import stat
from time import monotonic

from metroliza.parsing.preflight import supported_report_file_extensions


_MAX_ENTRIES = 20_000
_MAX_BYTES = 2 * 1024**3
_MAX_SECONDS = 10
_CHUNK_BYTES = 1024 * 1024


def _revision(fingerprints):
    digest = hashlib.sha256()
    for name, fingerprint in sorted(fingerprints.items()):
        digest.update(json.dumps(name, ensure_ascii=True).encode("ascii"))
        digest.update(fingerprint)
    return digest.hexdigest()


def _output_paths(outputs):
    return {path.parent.resolve(strict=False) / path.name for path in map(Path, outputs)}


def revision_from_preflight(files, outputs=()):
    """Reuse the approved scan's source scope, including held and duplicate files."""
    if len(files) > _MAX_ENTRIES:
        return None
    try:
        outputs = _output_paths(outputs)
    except (OSError, RuntimeError, ValueError):
        return None
    fingerprints = {}
    for report in files:
        if Path(report.source_path) in outputs:
            return None
        value = report.fingerprint
        if not value or not value.startswith("sha256:"):
            return None
        try:
            fingerprint = bytes.fromhex(value.removeprefix("sha256:"))
        except ValueError:
            return None
        name = report.stable_occurrence_id
        if len(fingerprint) != 32 or name in fingerprints:
            return None
        fingerprints[name] = fingerprint
    return _revision(fingerprints)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _fingerprint(path, byte_budget, interrupted):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > byte_budget:
            return None
        digest = hashlib.sha256()
        remaining = before.st_size
        while remaining and not interrupted():
            block = stream.read(min(remaining, _CHUNK_BYTES))
            if not block:
                return None
            remaining -= len(block)
            digest.update(block)
        if interrupted() or _identity(before) != _identity(path.stat()):
            return None
        return digest.digest(), _identity(before)


def _report_paths(source, observed, interrupted):
    """Match preflight's recursive supported-file discovery without following directory links."""
    extensions = supported_report_file_extensions()
    remaining = _MAX_ENTRIES
    pending = [source]
    while pending:
        directory = pending.pop()
        observed[directory] = _identity(directory.stat())
        with os.scandir(directory) as entries:
            for entry in entries:
                remaining -= 1
                if remaining < 0 or interrupted():
                    raise OSError("Report source check exceeded its budget or was interrupted")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif Path(entry.name).suffix.lower() in extensions and entry.is_file():
                    yield Path(entry.path)


def revision_from_folder(source, *, outputs=(), cancelled=lambda: False):
    """Hash current bytes on demand. Missing evidence never means unchanged."""
    deadline = monotonic() + _MAX_SECONDS

    def interrupted():
        return cancelled() or monotonic() >= deadline

    source = Path(source)
    remaining = _MAX_BYTES
    fingerprints, observed = {}, {}
    try:
        source = source.resolve(strict=True)
        excluded = _output_paths(outputs)
        for path in _report_paths(source, observed, interrupted):
            if path in excluded:
                continue
            result = _fingerprint(path, remaining, interrupted)
            if result is None:
                return None
            digest, stamp = result
            fingerprints[path.relative_to(source).as_posix()] = digest
            observed[path] = stamp
            remaining -= stamp[2]
        if all(not interrupted() and stamp == _identity(path.stat()) for path, stamp in observed.items()):
            return _revision(fingerprints)
    except (OSError, RuntimeError, ValueError):
        return None
    return None

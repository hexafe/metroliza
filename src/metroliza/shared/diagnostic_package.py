"""Fixed component identity for the qualified Windows PyInstaller onedir route."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

MANIFEST_NAME = "supervision_manifest.json"
COMPONENTS = (
    "metroliza_application.exe",
    "metroliza_ocr_worker.exe",
    "_internal/python311.dll",
    "_internal/base_library.zip",
    "_internal/metroliza/app/build_provenance.json",
)
MAX_COMPONENT_BYTES = 512 * 1024 * 1024
_HEX = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class PackageIdentity:
    valid: bool
    reason: str
    git_sha: str = "unknown"


def _regular(path: Path) -> bool:
    info = path.lstat()
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not getattr(info, "st_file_attributes", 0) & 0x400)


def _safe_parents(root: Path, path: Path) -> bool:
    current = path.parent
    while True:
        info = current.lstat()
        if (not stat.S_ISDIR(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400):
            return False
        if current == root:
            return True
        if current == current.parent:
            return False
        current = current.parent


def component_hash(root: Path, name: str) -> str:
    if name not in COMPONENTS:
        raise ValueError("invalid_component")
    path = root / name
    if not _safe_parents(root, path) or not _regular(path):
        raise ValueError("unsafe_component")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (before.st_size > MAX_COMPONENT_BYTES or before.st_nlink != 1
                or not stat.S_ISREG(before.st_mode)):
            raise ValueError("invalid_component")
        digest = hashlib.sha256()
        remaining = MAX_COMPONENT_BYTES + 1
        while remaining:
            block = stream.read(min(65536, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
        after = os.fstat(stream.fileno())
        if not remaining or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("component_changed")
        return digest.hexdigest()


def _validate_manifest(manifest: object) -> tuple[str, dict]:
    expected = {"schema_version", "packager", "layout", "git_sha", "components"}
    if type(manifest) is not dict or set(manifest) != expected:
        raise ValueError("invalid_manifest")
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["packager"] != "pyinstaller" or manifest["layout"] != "onedir"):
        raise ValueError("invalid_manifest")
    sha = manifest["git_sha"]
    if type(sha) is not str or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("invalid_manifest")
    components = manifest["components"]
    if type(components) is not dict or set(components) != set(COMPONENTS):
        raise ValueError("invalid_manifest")
    return sha, components


def inspect_package(root: Path) -> PackageIdentity:
    try:
        path = root / MANIFEST_NAME
        if not _regular(path) or path.stat().st_size > 4096:
            return PackageIdentity(False, "manifest_unavailable")
        with path.open("rb") as stream:
            payload = stream.read(4097)
        if len(payload) > 4096:
            return PackageIdentity(False, "manifest_unavailable")
        from metroliza.shared.diagnostic_transport import _unique_fields

        manifest = json.loads(payload, object_pairs_hook=_unique_fields)
        sha, components = _validate_manifest(manifest)
        for name in COMPONENTS:
            digest = components[name]
            if type(digest) is not str or _HEX.fullmatch(digest) is None:
                raise ValueError("invalid_manifest")
            if component_hash(root, name) != digest:
                return PackageIdentity(False, "component_mismatch", sha)
        with (root / COMPONENTS[-1]).open("rb") as stream:
            provenance_bytes = stream.read(4097)
        if len(provenance_bytes) > 4096:
            raise ValueError("invalid_provenance")
        provenance = json.loads(provenance_bytes, object_pairs_hook=_unique_fields)
        if type(provenance) is not dict or provenance.get("git_sha") != sha:
            return PackageIdentity(False, "provenance_mismatch")
        return PackageIdentity(True, "verified", sha)
    except (OSError, ValueError, TypeError, RecursionError):
        return PackageIdentity(False, "package_unavailable")

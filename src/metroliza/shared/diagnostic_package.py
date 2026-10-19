"""Fixed component identity for the qualified Windows PyInstaller onedir route.

``inspect_package`` returns one specific, stable reason (and the affected fixed
file name) for every way the package can be unusable, so the supervisor, the OCR
worker launch and the portable envelope report the same cause. The path policy
(regular single-link files, no reparse points on the component or on any
directory up to the package root) is unchanged; a rejection by that policy is
``component_unsafe``.
"""

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
    "metroliza_compute_worker.exe",
    "_internal/metroliza/app/build_provenance.json",
)
MAX_COMPONENT_BYTES = 512 * 1024 * 1024
_HEX = re.compile(r"[0-9a-f]{64}\Z")


REASON_VERIFIED = "verified"
REASON_MANIFEST_MISSING = "manifest_missing"
REASON_MANIFEST_INVALID = "manifest_invalid"
REASON_COMPONENT_MISSING = "component_missing"
REASON_COMPONENT_MODIFIED = "component_modified"
REASON_COMPONENT_UNSAFE = "component_unsafe"
REASON_COMPONENT_UNREADABLE = "component_unreadable"
REASON_PROVENANCE_MISMATCH = "provenance_mismatch"
# Only for failures that none of the specific reasons describes.
REASON_UNAVAILABLE = "package_unavailable"
REASONS = frozenset({
    REASON_VERIFIED, REASON_MANIFEST_MISSING, REASON_MANIFEST_INVALID,
    REASON_COMPONENT_MISSING, REASON_COMPONENT_MODIFIED, REASON_COMPONENT_UNSAFE,
    REASON_COMPONENT_UNREADABLE, REASON_PROVENANCE_MISMATCH, REASON_UNAVAILABLE,
})
_MAX_MANIFEST_BYTES = 4096


@dataclass(frozen=True)
class PackageIdentity:
    valid: bool
    reason: str
    git_sha: str = "unknown"
    # One of COMPONENTS or MANIFEST_NAME when the reason concerns a single file.
    component: str | None = None


class PackageFileError(ValueError):
    """A fixed package file cannot be verified; ``reason`` is a stable identity code."""

    def __init__(self, reason: str, component: str):
        super().__init__(reason)
        self.reason = reason
        self.component = component


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
    """SHA-256 of a manifest component.

    Raises ``ValueError("invalid_component")`` for an unlisted name and
    ``PackageFileError`` (a ``ValueError``) carrying the identity reason for a
    file that is missing, unsafe, unreadable, oversized or changing while read.
    """
    if name not in COMPONENTS:
        raise ValueError("invalid_component")
    try:
        return _hash_component(root, name)
    except PackageFileError:
        raise
    except (FileNotFoundError, NotADirectoryError):
        raise PackageFileError(REASON_COMPONENT_MISSING, name) from None
    except OSError:
        raise PackageFileError(REASON_COMPONENT_UNREADABLE, name) from None


def _hash_component(root: Path, name: str) -> str:
    path = root / name
    if not _safe_parents(root, path) or not _regular(path):
        raise PackageFileError(REASON_COMPONENT_UNSAFE, name)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_nlink != 1 or not stat.S_ISREG(before.st_mode):
            raise PackageFileError(REASON_COMPONENT_UNSAFE, name)
        if before.st_size > MAX_COMPONENT_BYTES:
            raise PackageFileError(REASON_COMPONENT_MODIFIED, name)
        digest = hashlib.sha256()
        remaining = MAX_COMPONENT_BYTES + 1
        while remaining:
            block = stream.read(min(65536, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
        after = os.fstat(stream.fileno())
        if not remaining:
            raise PackageFileError(REASON_COMPONENT_MODIFIED, name)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise PackageFileError(REASON_COMPONENT_UNREADABLE, name)
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
    for digest in components.values():
        if type(digest) is not str or _HEX.fullmatch(digest) is None:
            raise ValueError("invalid_manifest")
    return sha, components


def _read_manifest(root: Path) -> tuple[str, dict]:
    from metroliza.shared.diagnostic_transport import _unique_fields

    path = root / MANIFEST_NAME
    try:
        usable = _regular(path) and path.stat().st_size <= _MAX_MANIFEST_BYTES
    except (FileNotFoundError, NotADirectoryError):
        raise PackageFileError(REASON_MANIFEST_MISSING, MANIFEST_NAME) from None
    except OSError:
        raise PackageFileError(REASON_MANIFEST_INVALID, MANIFEST_NAME) from None
    try:
        if not usable:
            raise ValueError("invalid_manifest")
        with path.open("rb") as stream:
            payload = stream.read(_MAX_MANIFEST_BYTES + 1)
        if len(payload) > _MAX_MANIFEST_BYTES:
            raise ValueError("invalid_manifest")
        return _validate_manifest(json.loads(payload, object_pairs_hook=_unique_fields))
    except (OSError, ValueError, TypeError, RecursionError):
        raise PackageFileError(REASON_MANIFEST_INVALID, MANIFEST_NAME) from None


def _provenance_git_sha(root: Path) -> object:
    from metroliza.shared.diagnostic_transport import _unique_fields

    try:
        with (root / COMPONENTS[-1]).open("rb") as stream:
            payload = stream.read(_MAX_MANIFEST_BYTES + 1)
    except (FileNotFoundError, NotADirectoryError):
        raise PackageFileError(REASON_COMPONENT_MISSING, COMPONENTS[-1]) from None
    except OSError:
        raise PackageFileError(REASON_COMPONENT_UNREADABLE, COMPONENTS[-1]) from None
    try:
        if len(payload) > _MAX_MANIFEST_BYTES:
            return None
        provenance = json.loads(payload, object_pairs_hook=_unique_fields)
    except (ValueError, TypeError, RecursionError):
        return None
    return provenance.get("git_sha") if type(provenance) is dict else None


def inspect_package(root: Path) -> PackageIdentity:
    """Verify the onedir at ``root``; a damaged package is reported, never raised."""
    try:
        sha, digests = _read_manifest(root)
        for name in COMPONENTS:
            if component_hash(root, name) != digests[name]:
                return PackageIdentity(False, REASON_COMPONENT_MODIFIED, sha, name)
        if _provenance_git_sha(root) != sha:
            return PackageIdentity(False, REASON_PROVENANCE_MISMATCH, component=COMPONENTS[-1])
        return PackageIdentity(True, REASON_VERIFIED, sha)
    except PackageFileError as error:
        return PackageIdentity(False, error.reason, component=error.component)
    except (OSError, ValueError, TypeError, RecursionError):
        return PackageIdentity(False, REASON_UNAVAILABLE)


# --- reporting ---------------------------------------------------------------

NOTICE_ACTION = "Pobierz Metroliza ponownie i uruchom pobrany plik."
_NOTICE_PREFIX = "Nie można uruchomić aplikacji: "
_NOTICE_GENERIC = "brak lub niezgodność składników pakietu"


def _file_label(component: object) -> str | None:
    """Short name of a fixed package file; anything else is never echoed."""
    if type(component) is str and (component == MANIFEST_NAME or component in COMPONENTS):
        return component.rsplit("/", 1)[-1]
    return None


def identity_code(identity: PackageIdentity) -> str:
    """Path-free machine code: the reason, plus the fixed file name when it has one."""
    reason = identity.reason if identity.reason in REASONS else REASON_UNAVAILABLE
    label = _file_label(identity.component)
    return reason if label is None else f"{reason}:{label}"


def package_notice(identity: PackageIdentity) -> str:
    """Fixed Polish user notice for a rejected package, with the action to take.

    Built only from the reason and a fixed file name; no path, exception or
    manifest content can reach the text.
    """
    name = _file_label(identity.component)
    reason = identity.reason
    if reason == REASON_COMPONENT_MISSING and name:
        detail = (f"brakuje pliku {name} (mógł go usunąć program antywirusowy albo "
                  "kopiowanie zostało przerwane)")
    elif reason == REASON_COMPONENT_MODIFIED and name:
        detail = f"plik {name} jest zmieniony lub uszkodzony"
    elif reason == REASON_COMPONENT_UNSAFE and name:
        detail = (f"plik {name} jest dowiązaniem symbolicznym lub twardym albo leży "
                  "w folderze będącym dowiązaniem")
    elif reason == REASON_COMPONENT_UNREADABLE and name:
        detail = (f"nie można odczytać pliku {name} (sprawdź uprawnienia i program "
                  "antywirusowy)")
    elif reason == REASON_PROVENANCE_MISMATCH:
        detail = "pliki pochodzą z różnych wersji Metroliza"
    elif reason == REASON_MANIFEST_MISSING:
        detail = f"brakuje opisu pakietu ({MANIFEST_NAME})"
    elif reason == REASON_MANIFEST_INVALID:
        detail = f"opis pakietu ({MANIFEST_NAME}) jest uszkodzony lub nieczytelny"
    else:
        detail = _NOTICE_GENERIC
    return f"{_NOTICE_PREFIX}{detail}. {NOTICE_ACTION}"

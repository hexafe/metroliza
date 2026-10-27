"""Single-file delivery envelope for the already supervised Windows onedir.

PyInstaller extracts the complete onedir into its private temporary directory.
Keep this process alive until the real supervisor exits so the bootloader does
not remove the application runtime while it is in use.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from metroliza.app.version import VERSION_LABEL
from metroliza.shared.diagnostic_package import PackageIdentity, inspect_package, package_notice

PAYLOAD_DIRECTORY = "metroliza_payload"
LAUNCHER_NAME = "metroliza.exe"
SIDECAR_NAME = LAUNCHER_NAME + ".provenance.json"


def _regular_file(path: Path, limit: int) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not getattr(info, "st_file_attributes", 0) & 0x400
            and 0 < info.st_size <= limit)


def _verify_payload(root: Path) -> tuple[Path | None, PackageIdentity]:
    """Check the complete child identity and the exact executable sidecar.

    Returns the launcher (or None) with the package identity, so a caller can
    tell a rejected package (specific reason) from a failed launcher/sidecar check.
    """
    identity = inspect_package(root)
    if not identity.valid:
        return None, identity
    launcher = root / LAUNCHER_NAME
    sidecar = root / SIDECAR_NAME
    if not _regular_file(launcher, 64 * 1024 * 1024) or not _regular_file(sidecar, 16 * 1024):
        return None, identity
    try:
        with sidecar.open("rb") as stream:
            provenance = json.loads(stream.read(16 * 1024 + 1))
        artifact = provenance["artifact"]
        if (provenance["git_sha"] != identity.git_sha
                or provenance["release_label"] != VERSION_LABEL
                or provenance["dirty"] is not False
                or artifact["name"] != LAUNCHER_NAME
                or artifact["size_bytes"] != launcher.stat().st_size):
            return None, identity
        digest = hashlib.sha256()
        with launcher.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != artifact["sha256"]:
            return None, identity
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return None, identity
    return launcher, identity


def _verified_launcher(root: Path) -> Path | None:
    return _verify_payload(root)[0]


def _child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    # The nested PyInstaller launcher is a fresh application, with its own
    # bootloader parent and private extraction lifetime.
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def _launch(root: Path, arguments: list[str],
            rejected: list[PackageIdentity] | None = None) -> int | None:
    """Verify and run the payload; None means it was not started.

    When ``rejected`` is given, the package identity that failed verification is
    appended to it so the caller can name the reason.
    """
    launcher, identity = _verify_payload(root)
    if launcher is None:
        if rejected is not None and not identity.valid:
            rejected.append(identity)
        return None
    if os.name == "nt" and not ctypes.windll.kernel32.SetDllDirectoryW(None):
        return None
    try:
        process = subprocess.Popen(
            [str(launcher), *arguments], env=_child_environment(),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
        return process.wait()
    except (OSError, ValueError):
        return None


def main() -> int:
    if not getattr(sys, "frozen", False) or os.name != "nt":
        return 1
    extracted = getattr(sys, "_MEIPASS", None)
    rejected: list[PackageIdentity] = []
    result = (
        _launch(Path(extracted) / PAYLOAD_DIRECTORY, sys.argv[1:], rejected)
        if isinstance(extracted, str) else None
    )
    if result is None:
        # Fixed text only: no raw exception, native stack, path, or data. A rejected
        # package names its reason and file from fixed allowlists.
        message = (package_notice(rejected[0]) if rejected
                   else "Nie można uruchomić Metrolizy lub sprawdzić jej składników.")
        synthetic = (os.getenv("METROLIZA_STARTUP_SMOKE") == "1"
                     and os.getenv("METROLIZA_DIAGNOSTIC_QUALIFICATION") in
                     {"normal", "hard_exit", "preview"})
        if not synthetic:
            ctypes.windll.user32.MessageBoxW(None, message, "Metroliza", 0x10)
        return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())

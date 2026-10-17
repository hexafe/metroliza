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
from metroliza.shared.diagnostic_package import inspect_package

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


def _verified_launcher(root: Path) -> Path | None:
    """Check the complete child identity and the exact executable sidecar."""
    identity = inspect_package(root)
    if not identity.valid:
        return None
    launcher = root / LAUNCHER_NAME
    sidecar = root / SIDECAR_NAME
    if not _regular_file(launcher, 64 * 1024 * 1024) or not _regular_file(sidecar, 16 * 1024):
        return None
    try:
        with sidecar.open("rb") as stream:
            provenance = json.loads(stream.read(16 * 1024 + 1))
        artifact = provenance["artifact"]
        if (provenance["git_sha"] != identity.git_sha
                or provenance["release_label"] != VERSION_LABEL
                or provenance["dirty"] is not False
                or artifact["name"] != LAUNCHER_NAME
                or artifact["size_bytes"] != launcher.stat().st_size):
            return None
        digest = hashlib.sha256()
        with launcher.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != artifact["sha256"]:
            return None
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return None
    return launcher


def _child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    # The nested PyInstaller launcher is a fresh application, with its own
    # bootloader parent and private extraction lifetime.
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def _launch(root: Path, arguments: list[str]) -> int | None:
    launcher = _verified_launcher(root)
    if launcher is None:
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
    result = (
        _launch(Path(extracted) / PAYLOAD_DIRECTORY, sys.argv[1:])
        if isinstance(extracted, str) else None
    )
    if result is None:
        # Fixed text only: no raw exception, native stack, path, or data.
        synthetic = (os.getenv("METROLIZA_STARTUP_SMOKE") == "1"
                     and os.getenv("METROLIZA_DIAGNOSTIC_QUALIFICATION") in
                     {"normal", "hard_exit", "preview"})
        if not synthetic:
            ctypes.windll.user32.MessageBoxW(
                None, "Nie można uruchomić Metrolizy lub sprawdzić jej składników.",
                "Metroliza", 0x10,
            )
        return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())

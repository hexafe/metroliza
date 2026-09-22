"""Opt-in synthetic startup markers; no logs, exception text or runtime data.

Presence proves only that a marker was created. Absence does not prove the stage
did not run. Filesystem calls perturb startup timing, so this is a discriminator,
not a transparent observer or an ordinary-user diagnostic sink.
"""

import os
from pathlib import Path
import stat

PHASES = (
    "launcher_entry", "launcher_imported", "launcher_import_failed",
    "launcher_main_failed", "store_constructed", "package_inspection",
    "package_verified", "package_rejected", "supervision_entered",
    "spawn_entered", "spawn_returned", "supervision_failed",
    "supervision_returned", "child_entry", "child_attach_returned", "child_bootstrap_imported",
    "error_import", "error_os", "error_runtime", "error_other",
)
PROBE_DIRECTORY = "startup-phases"


def mark(phase: str) -> None:
    if (type(phase) is not str or phase not in PHASES
            or os.getenv("METROLIZA_STARTUP_SMOKE") != "1"
            or os.getenv("METROLIZA_DIAGNOSTIC_QUALIFICATION") != "normal"
            or os.getenv("METROLIZA_DIAGNOSTIC_STARTUP_PROBE") != "1"):
        return
    try:
        root = Path(os.environ["METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT"])
        target = root / PROBE_DIRECTORY
        if not root.is_absolute():
            return
        for path in (root, target):
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return
        # Never overwrite or follow an existing marker, even on Windows. The
        # qualifier creates and owns the parent in its private synthetic root.
        with (target / phase).open("xb"):
            pass
    except (OSError, ValueError, KeyError):
        pass


def mark_error(error: Exception) -> None:
    # No str/repr/args/attributes or subclass callbacks are consulted.
    kind = type(error)
    phase = (
        "error_import" if kind in (ImportError, ModuleNotFoundError)
        else "error_os" if kind in (OSError, PermissionError, FileNotFoundError)
        else "error_runtime" if kind is RuntimeError
        else "error_other"
    )
    mark(phase)

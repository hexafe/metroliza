"""File chooser policy for existing and new SQLite database paths."""

import errno
import os
from pathlib import Path

SQLITE_SUFFIXES = (".db", ".sqlite", ".sqlite3")
SQLITE_FILE_FILTER = "SQLite database (" + " ".join(
    f"*{suffix} *{suffix.upper()}" for suffix in SQLITE_SUFFIXES
) + ");;All files (*)"


class SQLiteSnapshotNameError(ValueError):
    """The destination lacks room for required SQLite sidecars."""


def sqlite_database_path(selected: str, *, creating: bool = False) -> str:
    """Keep opened paths exact; append .db to new names without a SQLite suffix.

    The chooser may return an existing extensionless database even in Save mode.
    Resolving a path here must never create storage or rewrite that selection.
    """
    if selected and creating and Path(selected).suffix.lower() not in SQLITE_SUFFIXES and not Path(selected).is_file():
        return f"{selected}.db"
    return selected


def _windows_component_limit(directory: Path) -> int | None:
    """Measure the volume containing the selected directory, including mount points."""
    from ctypes import WinDLL, byref, create_unicode_buffer, wintypes

    kernel = WinDLL("kernel32", use_last_error=True)
    volume_path = kernel.GetVolumePathNameW
    volume_path.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    volume_path.restype = wintypes.BOOL
    volume_information = kernel.GetVolumeInformationW
    volume_information.argtypes = (
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, wintypes.LPDWORD,
        wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPWSTR, wintypes.DWORD,
    )
    volume_information.restype = wintypes.BOOL
    root = create_unicode_buffer(32768)
    if not volume_path(str(directory.absolute()), root, len(root)):
        return None
    limit = wintypes.DWORD()
    if not volume_information(root.value, None, 0, None, byref(limit), None, None, 0):
        return None
    return limit.value or None


def _journal_component_too_long(journal: Path) -> bool:
    if os.name == "nt":
        limit = _windows_component_limit(journal.parent)
        return limit is not None and len(journal.name.encode("utf-16-le", "surrogatepass")) // 2 > limit
    pathconf = getattr(os, "pathconf", None)
    if pathconf is None:
        return False
    try:
        limit = pathconf(journal.parent, "PC_NAME_MAX")
    except (OSError, ValueError):
        return False
    return limit > 0 and len(os.fsencode(journal.name)) > limit


def sqlite_sidecar_path_problem(database: Path) -> str | None:
    """Check room for the longest SQLite sidecar without creating a file."""
    if not database.name:
        return None
    journal = database.with_name(database.name + "-journal")
    if _journal_component_too_long(journal):
        return "Choose a shorter database filename. SQLite needs room for its journal files."
    try:
        journal.lstat()
    except OSError as exc:
        if exc.errno == errno.ENAMETOOLONG or getattr(exc, "winerror", None) == 206:
            return "Choose a shorter database filename or folder path. SQLite needs room for its journal files."
    return None

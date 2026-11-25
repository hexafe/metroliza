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


def sqlite_sidecar_path_problem(database: Path) -> str | None:
    """Check room for the longest SQLite sidecar without creating a file."""
    if not database.name:
        return None
    journal = database.with_name(database.name + "-journal")
    pathconf = getattr(os, "pathconf", None)
    if pathconf is not None:
        try:
            limit = pathconf(database.parent, "PC_NAME_MAX")
        except (OSError, ValueError):
            pass
        else:
            if limit > 0 and len(os.fsencode(journal.name)) > limit:
                return "Choose a shorter database filename. SQLite needs room for its journal files."
    try:
        journal.lstat()
    except OSError as exc:
        if exc.errno == errno.ENAMETOOLONG or getattr(exc, "winerror", None) == 206:
            return "Choose a shorter database filename or folder path. SQLite needs room for its journal files."
    return None

"""File chooser policy for existing and new SQLite database paths."""

from pathlib import Path

SQLITE_SUFFIXES = (".db", ".sqlite", ".sqlite3")
SQLITE_FILE_FILTER = "SQLite database (" + " ".join(
    f"*{suffix} *{suffix.upper()}" for suffix in SQLITE_SUFFIXES
) + ");;All files (*)"


def sqlite_database_path(selected: str, *, creating: bool = False) -> str:
    """Keep opened paths exact; add .db only to a new extensionless name.

    The chooser may return an existing extensionless database even in Save mode.
    Resolving a path here must never create storage or rewrite that selection.
    """
    if selected and creating and not Path(selected).suffix and not Path(selected).is_file():
        return f"{selected}.db"
    return selected

"""Shared path helpers for external parser plugin discovery and installation."""

from __future__ import annotations

import os
from pathlib import Path


PARSER_EXTERNAL_PLUGIN_PATHS_ENV = "PARSER_EXTERNAL_PLUGIN_PATHS"
DEFAULT_PARSER_PLUGIN_HOME_SUBDIR = Path(".metroliza") / "parser_plugins"


def default_external_plugin_dir(*, home: Path | None = None) -> Path:
    """Return the default end-user drop-in directory for parser plugins."""

    return (home or Path.home()) / DEFAULT_PARSER_PLUGIN_HOME_SUBDIR


def default_external_plugin_dir_display() -> str:
    """Return the user-facing display path for parser plugin installation."""

    return str(Path("~") / DEFAULT_PARSER_PLUGIN_HOME_SUBDIR)


def split_external_plugin_paths(raw_paths: str | None) -> tuple[str, ...]:
    """Split a PATH-style parser-plugin path string into normalized entries."""

    if raw_paths is None:
        raw_paths = ""
    return tuple(entry.strip() for entry in str(raw_paths).split(os.pathsep) if entry.strip())


def configured_external_plugin_path_entries(
    raw_paths: str | None = None,
    *,
    include_default_dir: bool = True,
    home: Path | None = None,
) -> tuple[str, ...]:
    """Return ordered external-plugin path entries for runtime discovery.

    The default drop-in directory is listed first, then any explicitly configured
    env-var entries. Later entries can override earlier ones by re-registering the
    same plugin id.
    """

    entries: list[str] = []

    if include_default_dir:
        entries.append(str(default_external_plugin_dir(home=home)))

    env_entries = split_external_plugin_paths(
        raw_paths if raw_paths is not None else os.getenv(PARSER_EXTERNAL_PLUGIN_PATHS_ENV, "")
    )
    entries.extend(env_entries)

    deduped: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        deduped.append(entry)
    return tuple(deduped)

"""Shared path helpers for external parser plugin discovery and installation."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sys
from threading import local, RLock
from typing import Iterator


PARSER_EXTERNAL_PLUGIN_PATHS_ENV = "PARSER_EXTERNAL_PLUGIN_PATHS"
PARSER_DISABLED_PLUGIN_IDS_ENV = "PARSER_DISABLED_PLUGIN_IDS"
DEFAULT_PARSER_PLUGIN_HOME_SUBDIR = Path(".metroliza") / "parser_plugins"
PARSER_PROFILE_STORE_LOCK_FILE = ".profile-store.lock"
_PROFILE_STORE_THREAD_LOCK = RLock()
_PROFILE_STORE_LOCK_STATE = local()


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


def disabled_plugin_ids(raw_ids: str | None = None) -> frozenset[str]:
    """Return parser plugin ids disabled by runtime configuration."""

    value = raw_ids if raw_ids is not None else os.getenv(PARSER_DISABLED_PLUGIN_IDS_ENV, "")
    ids = {
        item.strip()
        for item in str(value).replace(";", ",").split(",")
        if item.strip()
    }
    return frozenset(ids)


def _lock_profile_store_file(handle) -> None:
    if os.name == "nt":  # pragma: no cover - exercised by Windows release smoke.
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_profile_store_file(handle) -> None:
    if os.name == "nt":  # pragma: no cover - exercised by Windows release smoke.
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def parser_profile_store_lock(*, home: Path | None = None) -> Iterator[None]:
    """Serialize profile generation reads and promotions across threads and processes."""

    lock_root = default_external_plugin_dir(home=home)
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / PARSER_PROFILE_STORE_LOCK_FILE
    with _PROFILE_STORE_THREAD_LOCK:
        held_paths = getattr(_PROFILE_STORE_LOCK_STATE, "held_paths", [])
        if lock_path in held_paths:
            held_paths.append(lock_path)
            try:
                yield
            finally:
                held_paths.pop()
            return

        with lock_path.open("a+b") as handle:
            _lock_profile_store_file(handle)
            held_paths.append(lock_path)
            _PROFILE_STORE_LOCK_STATE.held_paths = held_paths
            try:
                yield
            finally:
                held_paths.pop()
                _unlock_profile_store_file(handle)


def invalidate_parser_plugin_runtime() -> None:
    """Invalidate already-imported parser registry state after a profile lifecycle change."""

    factory = sys.modules.get("metroliza.parsing.report_parser_factory")
    if factory is None:
        return

    reset_loader = getattr(factory, "reset_external_plugin_loader_state", None)
    if callable(reset_loader):
        reset_loader()
    reset_probe_cache = getattr(factory, "reset_probe_cache", None)
    if callable(reset_probe_cache):
        reset_probe_cache()

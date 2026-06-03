"""Shared matplotlib runtime configuration for headless export paths."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _default_cache_dir(cache_dir_name: str) -> Path:
    """Return a stable writable cache path to avoid repeated font-cache rebuilds."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Metroliza" / cache_dir_name

    return Path(os.environ.get("USERPROFILE") or Path.home()) / ".metroliza" / cache_dir_name


def _is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_path = path / ".metroliza-write-probe"
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _fallback_cache_dir(cache_dir_name: str) -> Path:
    return Path(tempfile.gettempdir()) / "metroliza" / cache_dir_name


def configure_headless_matplotlib(*, cache_dir_name: str = "metroliza-mpl") -> None:
    """Configure a deterministic, writable headless matplotlib runtime.

    The export and benchmark paths are strictly PNG-generation workloads, so
    they should never depend on an interactive backend or on a user-specific
    config directory being writable.
    """

    os.environ.setdefault("MPLBACKEND", "Agg")
    if not os.environ.get("MPLCONFIGDIR"):
        cache_dir = _default_cache_dir(cache_dir_name)
        if _is_writable_directory(cache_dir):
            os.environ["MPLCONFIGDIR"] = str(cache_dir)
        else:
            fallback_dir = _fallback_cache_dir(cache_dir_name)
            if _is_writable_directory(fallback_dir):
                os.environ["MPLCONFIGDIR"] = str(fallback_dir)

    try:
        import matplotlib

        matplotlib.use(os.environ.get("MPLBACKEND", "Agg"), force=True)
    except Exception:
        pass

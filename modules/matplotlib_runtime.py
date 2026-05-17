"""Shared matplotlib runtime configuration for headless export paths."""

from __future__ import annotations

import os
from pathlib import Path


def _default_cache_dir(cache_dir_name: str) -> Path:
    """Return a stable writable cache path to avoid repeated font-cache rebuilds."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Metroliza" / cache_dir_name

    return Path(os.environ.get("USERPROFILE") or Path.home()) / ".metroliza" / cache_dir_name


def configure_headless_matplotlib(*, cache_dir_name: str = "metroliza-mpl") -> None:
    """Configure a deterministic, writable headless matplotlib runtime.

    The export and benchmark paths are strictly PNG-generation workloads, so
    they should never depend on an interactive backend or on a user-specific
    config directory being writable.
    """

    os.environ.setdefault("MPLBACKEND", "Agg")
    if not os.environ.get("MPLCONFIGDIR"):
        cache_dir = _default_cache_dir(cache_dir_name)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        else:
            os.environ["MPLCONFIGDIR"] = str(cache_dir)

    try:
        import matplotlib

        matplotlib.use(os.environ.get("MPLBACKEND", "Agg"), force=True)
    except Exception:
        pass

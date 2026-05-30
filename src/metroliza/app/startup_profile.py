"""Lightweight startup timing markers for packaged-artifact diagnostics."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from metroliza.shared.env_utils import parse_bool

STARTUP_PROFILE_ENV = "METROLIZA_STARTUP_PROFILE"
STARTUP_PROFILE_PATH_ENV = "METROLIZA_STARTUP_PROFILE_PATH"
STARTUP_UI_SMOKE_ENV = "METROLIZA_STARTUP_UI_SMOKE"

_START_NS = time.perf_counter_ns()
_PROFILE_PATH: Path | None = None


def parse_env_flag(value: str | None, default: bool = False) -> bool:
    """Parse common truthy/falsy environment values."""
    return parse_bool(value, default=default)


def profiling_enabled() -> bool:
    """Return whether startup profile markers should be persisted."""
    return parse_env_flag(os.getenv(STARTUP_PROFILE_ENV), default=False)


def ui_smoke_enabled() -> bool:
    """Return whether startup should exit after first UI event-loop tick."""
    return parse_env_flag(os.getenv(STARTUP_UI_SMOKE_ENV), default=False)


def get_profile_path() -> Path:
    """Resolve the JSONL profile output path."""
    global _PROFILE_PATH
    if _PROFILE_PATH is not None:
        return _PROFILE_PATH

    explicit_path = os.getenv(STARTUP_PROFILE_PATH_ENV)
    if explicit_path:
        _PROFILE_PATH = Path(explicit_path).expanduser()
        return _PROFILE_PATH

    home = Path(os.getenv("USERPROFILE") or Path.home())
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    _PROFILE_PATH = home / ".metroliza" / f"startup_profile_{os.getpid()}_{timestamp}.jsonl"
    return _PROFILE_PATH


def record_event(name: str, **extra: Any) -> None:
    """Append a startup profile event when profiling is enabled."""
    if not profiling_enabled():
        return

    elapsed_ms = (time.perf_counter_ns() - _START_NS) / 1_000_000
    payload: dict[str, Any] = {
        "name": name,
        "elapsed_ms": round(elapsed_ms, 3),
        "pid": os.getpid(),
        "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "meipass": str(getattr(sys, "_MEIPASS", "")),
    }
    payload.update(extra)

    try:
        profile_path = get_profile_path()
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        with profile_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        return

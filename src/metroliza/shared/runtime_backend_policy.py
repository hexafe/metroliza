"""Runtime policy helpers for optional native backend selection.

These helpers let the app prefer pure-Python implementations in frozen
executables (PyInstaller/Nuitka), where ABI/runtime mismatches can terminate
the process before Python-level exception handlers or log flushing run.
"""

from __future__ import annotations

import sys

from metroliza.shared.env_utils import env_bool


def is_frozen_runtime() -> bool:
    """Return True when running from a frozen executable bundle."""

    return bool(getattr(sys, "frozen", False))


def should_prefer_python_backend_in_auto_mode() -> bool:
    """Return whether `auto` backend selection should default to Python.

    In frozen builds we default `auto` to Python for stability. Operators can
    opt back into native defaults by setting
    `METROLIZA_ENABLE_NATIVE_IN_FROZEN=1|true|yes|on`.
    """

    if not is_frozen_runtime():
        return False
    return not env_bool("METROLIZA_ENABLE_NATIVE_IN_FROZEN", default=False)

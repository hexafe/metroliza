"""Select the immutable supervised compute image without relaunching the UI."""

from __future__ import annotations

import multiprocessing
from pathlib import Path
import sys


def frozen_windows() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def is_compute_worker() -> bool:
    return bool(getattr(sys, "frozen", False)) and Path(sys.executable).name.lower() == "metroliza_compute_worker.exe"


def worker_executable() -> Path:
    from metroliza.shared.diagnostic_package import identity_code, inspect_package

    application = Path(sys.executable)
    if application.name.lower() != "metroliza_application.exe":
        raise RuntimeError("compute_package_identity_failed")
    identity = inspect_package(application.parent)
    if not identity.valid:
        raise RuntimeError(f"compute_package_identity_failed:{identity_code(identity)}")
    return application.with_name("metroliza_compute_worker.exe")


def spawn_context():
    context = multiprocessing.get_context("spawn")
    if frozen_windows():
        # CPython's executable setting is process-wide. All frozen compute pools
        # deliberately use the same immutable sibling; never toggle it per task.
        context.set_executable(str(worker_executable()))
    elif getattr(sys, "frozen", False):
        raise RuntimeError("compute_frozen_platform_unqualified")
    return context


def initialize_compute_runtime():
    if is_compute_worker():
        from metroliza.parsing.frozen_ocr_worker import _use_native_windows_version

        _use_native_windows_version()

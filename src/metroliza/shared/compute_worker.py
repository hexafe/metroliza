"""Select the immutable supervised compute image without relaunching the UI."""

from __future__ import annotations

import multiprocessing
import os
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


def compute_workers_available() -> bool:
    """Keep unsupported or damaged frozen packages serial, including explicit counts."""
    if not getattr(sys, "frozen", False):
        return True
    if not frozen_windows():
        return False
    try:
        worker_executable()
    except (OSError, RuntimeError):
        return False
    return True


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
        use_native_windows_version()


def use_native_windows_version(*, runtime_sys=sys, runtime_os=os) -> None:
    """Keep the isolated worker's version fallback inside the owned process."""
    if runtime_os.name != "nt" or not getattr(runtime_sys, "frozen", False):
        return
    import platform

    native = runtime_sys.getwindowsversion().platform_version
    if (type(native) is not tuple or len(native) != 3
            or any(type(part) is not int or part < 0 for part in native)
            or native[0] == 0):
        raise RuntimeError("windows_version_unavailable")
    native_version = ".".join(str(part) for part in native)

    def from_native(system="", release="", version="", supported_platforms=("win32", "win16", "dos")):
        if runtime_sys.platform not in supported_platforms:
            return system, release, version
        return system, release, native_version

    # CPython's win32_ver() uses this private fallback after WMI fails. Its
    # stock implementation shells out, although it falls back to the same
    # platform_version tuple when that command cannot provide a version.
    if not callable(getattr(platform, "_syscmd_ver", None)):
        raise RuntimeError("windows_version_unavailable")
    platform._syscmd_ver = from_native

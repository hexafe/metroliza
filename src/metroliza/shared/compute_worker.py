"""Select the immutable supervised compute image without relaunching the UI."""

from __future__ import annotations

import contextlib
import multiprocessing
import multiprocessing.context
import os
from pathlib import Path
import sys
import threading


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


# Math libraries read these once, when NumPy/SciPy load. A compute worker is already one
# of several parallel processes, so each keeps a single math thread (they would otherwise
# each start one thread per core). A value the user set always wins.
WORKER_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
_SPAWN_ENVIRONMENT_LOCK = threading.Lock()


@contextlib.contextmanager
def worker_thread_environment(environ=None):
    """Temporarily add the one-thread limits that the environment does not already set.

    Only variables that are absent are added, and exactly those are removed again, so
    nothing the user (or another thread) set is ever changed. The lock serialises
    concurrent worker starts; the parent's own libraries never see the values because
    they were loaded earlier and read their configuration only once.
    """

    environ = os.environ if environ is None else environ
    with _SPAWN_ENVIRONMENT_LOCK:
        added = [name for name in WORKER_THREAD_VARIABLES if name not in environ]
        for name in added:
            environ[name] = "1"
        try:
            yield tuple(added)
        finally:
            for name in added:
                if environ.get(name) == "1":
                    del environ[name]


class _ThreadLimitedSpawnProcess(multiprocessing.context.SpawnProcess):
    """Spawn process whose child inherits one-thread math libraries before NumPy loads.

    The child environment is fixed at process creation, which is the only point that is
    early enough for a spawned interpreter: NumPy may already be imported while the
    worker unpickles its entry point.
    """

    def start(self):
        with worker_thread_environment():
            super().start()


class _ThreadLimitedContext:
    """Spawn context facade whose processes start with ``worker_thread_environment``."""

    def __init__(self, context):
        self._context = context

    @property
    def Process(self):  # noqa: N802 - multiprocessing context API
        return _ThreadLimitedSpawnProcess

    def __getattr__(self, name):
        return getattr(self._context, name)


def spawn_context():
    context = multiprocessing.get_context("spawn")
    if frozen_windows():
        # CPython's executable setting is process-wide. All frozen compute pools
        # deliberately use the same immutable sibling; never toggle it per task.
        context.set_executable(str(worker_executable()))
    elif getattr(sys, "frozen", False):
        raise RuntimeError("compute_frozen_platform_unqualified")
    return _ThreadLimitedContext(context)


def initialize_compute_runtime():
    if is_compute_worker():
        use_native_windows_version()


def use_native_windows_version(*, runtime_sys=sys, runtime_os=os) -> None:
    """Use the native version fallback in frozen Windows parents and workers."""
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

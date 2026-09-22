"""Synthetic native roles; no command/path/exception output."""
import os
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import runpy
import subprocess
import sys
import time


def _wait_for_marker(name):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if (Path.cwd() / name).is_file():
            return True
        time.sleep(0.005)
    return False


def _exercise_subprocess(mode):
    if mode == "late_numpy":
        import numpy

        # A source import alone need not query Windows. This public operation
        # calls platform.uname -> win32_ver using real NumPy frames. Its system
        # details stay in memory and never enter CI output or audit receipts.
        with redirect_stdout(StringIO()):
            numpy.show_runtime()
    if mode in {"ver", "deep_ver", "late_ver", "hard", "write_failure"}:
        import platform

        def version_at_depth(remaining):
            if remaining:
                return version_at_depth(remaining - 1)
            return platform.win32_ver()

        version_at_depth(80 if mode == "deep_ver" else 0)
    elif mode in {"other", "late_other"}:
        subprocess.check_output("echo synthetic", shell=True)


def main():
    mode = sys.argv[1]
    if mode in {"outer", "supervisor"}:
        executable = Path(sys.executable).with_name(
            "control-launcher.exe" if mode == "outer" else "control-application.exe"
        )
        next_mode = "supervisor" if mode == "outer" else "ver"
        return subprocess.call([str(executable), __file__, next_mode], creationflags=0x08000000)
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "src"))
    if mode == "write_failure":
        (Path(os.environ["METROLIZA_WINDOWS_RUNTIME_AUDIT_ROOT"]) / "event-01.json").touch()
    if mode == "blocked_install":
        def block_registration(event, _arguments):
            if event == "sys.addaudithook":
                raise RuntimeError("synthetic")
        sys.addaudithook(block_registration)
    runpy.run_path(str(root / "packaging/hooks/windows/rthooks/metroliza_rth_runtime_audit.py"))
    if mode.startswith("late_"):
        (Path.cwd() / "control-ready").touch()
        if not _wait_for_marker("control-start"):
            return 98
    _exercise_subprocess(mode)
    if mode == "hard":
        os._exit(9)
    (Path.cwd() / "control-ready").touch()
    return 0 if _wait_for_marker("control-finish") else 98


if __name__ == "__main__":
    raise SystemExit(main())

"""Synthetic native roles; no command/path/exception output."""
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time


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
    if mode in {"ver", "deep_ver", "hard", "write_failure"}:
        import platform

        def version_at_depth(remaining):
            if remaining:
                return version_at_depth(remaining - 1)
            return platform.win32_ver()

        version_at_depth(80 if mode == "deep_ver" else 0)
    elif mode == "other":
        subprocess.check_output("echo synthetic", shell=True)
    if mode == "hard":
        os._exit(9)
    (Path.cwd() / "control-ready").touch()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if (Path.cwd() / "control-finish").is_file():
            return 0
        time.sleep(0.005)
    return 98


if __name__ == "__main__":
    raise SystemExit(main())

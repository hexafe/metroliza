"""Fixed native console/stdio facts from a test-owned GUI Python child."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from metroliza.shared.diagnostic_transport import attach_child_recorder  # noqa: E402
from metroliza.app.diagnostic_qualification import _console_absent  # noqa: E402


def _stdio_kind(kernel, identifier):
    handle = kernel.GetStdHandle(identifier)
    if not handle:
        return "none"
    if handle == ctypes.c_void_p(-1).value:
        return "invalid"
    if kernel.GetConsoleMode(handle, ctypes.byref(wintypes.DWORD())):
        return "console"
    return {1: "disk_nonconsole", 2: "character_nonconsole", 3: "pipe_nonconsole"}.get(
        kernel.GetFileType(handle), "unavailable")


def main():
    if os.name != "nt":
        return 20
    if sys.argv[2] == "supervised":
        from metroliza.app.diagnostic_supervisor import launch_supervised
        result = launch_supervised([sys.executable, __file__, sys.argv[1], "child"], cwd=Path(sys.argv[1]).parent)
        return 0 if result.exit_code == 0 and result.handshake == "accepted" else 22
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleWindow.argtypes = []
    kernel.GetConsoleWindow.restype = wintypes.HWND
    kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    kernel.GetConsoleProcessList.restype = wintypes.DWORD
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetConsoleMode.restype = wintypes.BOOL
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.AllocConsole.argtypes = []
    kernel.AllocConsole.restype = wintypes.BOOL
    kernel.FreeConsole.argtypes = []
    kernel.FreeConsole.restype = wintypes.BOOL
    recorder = attach_child_recorder()
    allocated = False
    try:
        if sys.argv[2] == "attached":
            if not kernel.AllocConsole():
                return 21
            allocated = True
        count = wintypes.DWORD()
        ctypes.set_last_error(0)
        attached = kernel.GetConsoleProcessList(ctypes.byref(count), 1)
        error = ctypes.get_last_error()
        state = "attached" if attached else "absent" if error == 6 else "unavailable"
        facts = {"schema_version": 1, "console_state": state,
                 "console_window": bool(kernel.GetConsoleWindow()),
                 "qualification_console_absent": _console_absent(),
                 "stdout_none": sys.stdout is None, "stderr_none": sys.stderr is None}
        for name, identifier in (("stdout_handle", -11), ("stderr_handle", -12)):
            facts[name] = _stdio_kind(kernel, identifier)
        with Path(sys.argv[1]).open("x", encoding="ascii") as stream:
            json.dump(facts, stream, sort_keys=True)
        return 0
    finally:
        if allocated:
            kernel.FreeConsole()
        if recorder is not None:
            recorder.close()


if __name__ == "__main__":
    raise SystemExit(main())

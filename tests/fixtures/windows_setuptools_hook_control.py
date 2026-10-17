"""Closed causal control; no argv, environment, paths or traceback are saved."""
from __future__ import annotations

import ctypes
from importlib.metadata import version
import json
import os
from pathlib import Path
import runpy
import sys

counts = {"cmd_ver": 0, "platform_ver": 0, "setuptools_windows_support": 0, "other": 0}


def observe(event, arguments):
    if event != "subprocess.Popen":
        return
    executable, command = arguments[:2]
    buffer = ctypes.create_unicode_buffer(32768)
    copied = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < copied < len(buffer):
        counts["other"] += 1
        return
    expected = str(Path(buffer.value) / "cmd.exe")
    if (type(executable) is not str or type(command) is not str
            or os.path.normcase(executable) != os.path.normcase(expected)
            or command.casefold() != (expected + ' /c "ver"').casefold()):
        counts["other"] += 1
        return
    counts["cmd_ver"] += 1
    frame = sys._getframe(1)
    for _ in range(64):
        if frame is None:
            break
        pair = (frame.f_globals.get("__name__"), frame.f_code.co_name)
        if pair == ("platform", "_syscmd_ver"):
            counts["platform_ver"] += 1
        if pair == ("setuptools.windows_support", "windows_only"):
            counts["setuptools_windows_support"] += 1
        frame = frame.f_back


def main():
    root = Path(__file__).resolve().parents[2]
    hooks = {
        "original": root / "tests/fixtures/packaging/pyi_rth_setuptools_6_22_3.py",
        "corrected": root / "packaging/hooks/windows/rthooks/metroliza_rth_setuptools.py",
    }
    hook = hooks[os.environ["METROLIZA_TEST_SETUPTOOLS_HOOK"]]
    result = {"status": "failed", "audit": counts, "shim": False,
              "setuptools_65_5": version("setuptools") == "65.5.0"}
    sys.addaudithook(observe)
    try:
        runpy.run_path(str(hook))
        import _distutils_hack

        result["shim"] = _distutils_hack.DISTUTILS_FINDER in sys.meta_path
        result["status"] = "passed"
    except Exception:
        pass
    with (Path.cwd() / "hook-control.json").open("x", encoding="ascii") as stream:
        json.dump(result, stream, sort_keys=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

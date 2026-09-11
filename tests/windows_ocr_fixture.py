"""Static synthetic subprocess roles for the native Windows wrapper discriminator."""

from __future__ import annotations

import ctypes
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from ctypes import wintypes


WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
SYNCHRONIZE = 0x100000
EVENT_MODIFY_STATE = 0x0002


def _append(path: str | Path, value: dict) -> None:
    with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, separators=(",", ":")) + "\n")


def _kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.IsProcessInJob.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)
    ]
    kernel.IsProcessInJob.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.SetEvent.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _preflight(state: Path) -> int:
    kernel = _kernel()
    owned = wintypes.BOOL()
    assigned_before_code = bool(
        kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, ctypes.byref(owned)) and owned.value
    )
    marker = Path(str(state) + ".child")
    child = subprocess.Popen(
        [sys.executable, "-I", "-S", __file__, "sleeper", str(marker)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    del child  # The enclosing Job Object owns and accounts for this descendant.
    deadline = time.monotonic() + 5
    descendant = {}
    while time.monotonic() < deadline:
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            time.sleep(0.01)
            continue
        if value == {"schema_version": 1, "stage": "blocked", "child_in_job": True}:
            descendant = value
            break
        time.sleep(0.01)
    descendant_ready = descendant.get("stage") == "blocked"
    descendant_in_job = descendant.get("child_in_job") is True
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assigned_before_code": assigned_before_code,
                "descendant_ready": descendant_ready,
                "descendant_in_job": descendant_in_job,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return 0 if assigned_before_code and descendant_ready and descendant_in_job else 24


def _sleeper(marker: Path) -> int:
    kernel = _kernel()
    owned = wintypes.BOOL()
    child_in_job = bool(
        kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, ctypes.byref(owned)) and owned.value
    )
    marker.write_text(
        json.dumps(
            {"schema_version": 1, "stage": "blocked", "child_in_job": child_in_job},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    threading.Event().wait()
    return 0


def _child(config_path: Path) -> int:
    import msvcrt

    config = json.loads(config_path.read_text(encoding="utf-8"))
    kernel = _kernel()
    handles = [
        kernel.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, config[name])
        for name in ("ready", "release", "exited", "hold")
    ]
    parent = kernel.OpenProcess(SYNCHRONIZE, False, config["parent_pid"])
    try:
        file_types = [
            kernel.GetFileType(wintypes.HANDLE(msvcrt.get_osfhandle(descriptor)))
            for descriptor in (1, 2)
        ]
        stdout_type, stderr_type = file_types
        stdout_pipe, stderr_pipe = stdout_type == 3, stderr_type == 3
        parent_live = bool(parent) and kernel.WaitForSingleObject(parent, 0) == WAIT_TIMEOUT
        expected_type = config["expected_type"]
        if expected_type not in {1, 3}:
            expected_type = 0
        ready = all(handles) and parent_live and (stdout_type, stderr_type) == (
            expected_type, expected_type
        )
        _append(
            config["state"],
            {
                "schema_version": 1,
                "stage": "child_ready" if ready else "fixture_mismatch",
                "stdout_pipe": stdout_pipe,
                "stderr_pipe": stderr_pipe,
                "stdout_type": stdout_type,
                "stderr_type": stderr_type,
                "parent_live": parent_live,
            },
        )
        ready_signalled = bool(handles[0]) and bool(kernel.SetEvent(handles[0]))
        if not ready or not ready_signalled:
            return 24
        released = kernel.WaitForSingleObject(handles[1], 10000) == WAIT_OBJECT_0
        parent_exited = kernel.WaitForSingleObject(parent, 10000) == WAIT_OBJECT_0
        _append(
            config["state"],
            {
                "schema_version": 1,
                "stage": "parent_exited" if released and parent_exited else "fixture_mismatch",
                "release_observed": released,
                "parent_exited": parent_exited,
                "stdout_pipe": stdout_pipe,
                "stderr_pipe": stderr_pipe,
                "stdout_type": stdout_type,
                "stderr_type": stderr_type,
            },
        )
        if not released or not parent_exited or not kernel.SetEvent(handles[2]):
            return 24
        return 0 if kernel.WaitForSingleObject(handles[3], 0xFFFFFFFF) == WAIT_OBJECT_0 else 24
    finally:
        for handle in handles:
            if handle:
                kernel.CloseHandle(handle)
        if parent:
            kernel.CloseHandle(parent)


def _driver(
    repo: Path,
    shell: str,
    script: Path,
    config_path: Path,
    probe: Path,
    outcome: Path,
) -> int:
    sys.path.insert(0, str(repo))
    from tests import test_windows_ocr_powershell as harness

    config = json.loads(config_path.read_text(encoding="utf-8"))
    kernel = _kernel()
    events = {}
    for name in ("ready", "release", "exited", "hold"):
        handle = kernel.CreateEventW(None, True, False, config[name])
        if not handle:
            for created in events.values():
                kernel.CloseHandle(created)
            return 25
        events[name] = handle

    try:
        original_communicate = harness.subprocess.Popen._communicate
        first_timed_communicate = True

        def observed(process, input_data, endtime, original_timeout):
            nonlocal first_timed_communicate
            if first_timed_communicate and original_timeout is not None:
                first_timed_communicate = False
                ready_seen = kernel.WaitForSingleObject(events["ready"], 10000) == WAIT_OBJECT_0
                _append(
                    probe,
                    {"schema_version": 1, "stage": "communicate_entered", "ready_seen": ready_seen},
                )
            try:
                return original_communicate(process, input_data, endtime, original_timeout)
            except subprocess.TimeoutExpired:
                shell_wait = kernel.WaitForSingleObject(int(process._handle), 0)
                shell_state = {WAIT_OBJECT_0: "exited", WAIT_TIMEOUT: "live"}.get(
                    shell_wait, "wait_failed"
                )
                exited_seen = kernel.WaitForSingleObject(events["exited"], 0) == WAIT_OBJECT_0
                _append(
                    probe,
                    {
                        "schema_version": 1,
                        "stage": "timeout_before_kill",
                        "shell_state": shell_state,
                        "exited_seen": exited_seen,
                    },
                )
                raise

        harness.subprocess.Popen._communicate = observed
        try:
            result = harness.invoke(
                shell,
                script.parent,
                script.name,
                "-ConfigPath",
                str(config_path),
                timeout_s=15,
            )
            _append(
                outcome,
                {
                    "schema_version": 1,
                    "stage": "invoke_returned",
                    "returncode": result.returncode,
                },
            )
            return 0
        except subprocess.TimeoutExpired:
            _append(outcome, {"schema_version": 1, "stage": "timeout_returned"})
            return 0
        except (OSError, subprocess.SubprocessError):
            _append(outcome, {"schema_version": 1, "stage": "invoke_failed"})
            return 24
        finally:
            harness.subprocess.Popen._communicate = original_communicate
    finally:
        for event in events.values():
            kernel.CloseHandle(event)


def main() -> int:
    role = sys.argv[1]
    if role == "preflight":
        return _preflight(Path(sys.argv[2]))
    if role == "sleeper":
        return _sleeper(Path(sys.argv[2]))
    if role == "child":
        return _child(Path(sys.argv[2]))
    if role == "driver":
        return _driver(
            Path(sys.argv[2]),
            sys.argv[3],
            Path(sys.argv[4]),
            Path(sys.argv[5]),
            Path(sys.argv[6]),
            Path(sys.argv[7]),
        )
    return 24


if __name__ == "__main__":
    raise SystemExit(main())

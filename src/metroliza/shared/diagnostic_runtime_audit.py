"""Opt-in, bounded subprocess evidence for the synthetic Windows qualifier.

This is not an application log. Arguments and frame data are inspected in memory
and never serialized. Each immutable event is closed before Popen may execute;
the host must independently prove the exact owned process chain and drain it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

GATE = "METROLIZA_WINDOWS_RUNTIME_AUDIT"
ROOT = "METROLIZA_WINDOWS_RUNTIME_AUDIT_ROOT"
NONCE = "METROLIZA_WINDOWS_RUNTIME_AUDIT_NONCE"
MAX_EVENTS = 16
FAILURE_EXIT = 97
CALLERS = frozenset({"setuptools", "numpy", "matplotlib", "platformdirs", "other"})
KINDS = frozenset({
    "platform_ver", "other", "other_arguments", "other_executable",
    "other_command", "other_frames", "other_depth",
})


def _plain_directory(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400


def _write(root: Path, name: str, value: dict) -> None:
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(data) > 1024:
        raise ValueError("runtime_audit_invalid")
    with (root / name).open("xb") as stream:
        stream.write(data)


def classify_call(arguments, frame, expected_cmd: str) -> tuple[str, str]:
    import ntpath

    if len(arguments) < 2:
        return "other_arguments", "other"
    executable, command = arguments[:2]
    if type(executable) is not str or type(command) is not str:
        return "other_arguments", "other"
    if ntpath.normcase(executable) != ntpath.normcase(expected_cmd):
        return "other_executable", "other"
    if command.casefold() != (expected_cmd + ' /c "ver"').casefold():
        return "other_command", "other"
    required = set()
    caller = "other"
    for _ in range(64):
        if frame is None:
            break
        module = frame.f_globals.get("__name__")
        name = frame.f_code.co_name
        if module == "platform" and name in {"_syscmd_ver", "win32_ver"}:
            required.add(name)
        if type(module) is str and module.split(".", 1)[0] in CALLERS - {"other"}:
            caller = module.split(".", 1)[0]
        frame = frame.f_back
    else:
        # The bound limits observation, not the caller's total stack depth.
        # Retain a complete signature already proved inside that window.
        if required != {"_syscmd_ver", "win32_ver"}:
            return ("other_depth" if frame is not None else "other_frames"), "other"
    return ("platform_ver" if required == {"_syscmd_ver", "win32_ver"} else "other_frames"), caller


def install() -> None:
    # Ordinary product execution performs only this fixed opt-in check.
    if os.environ.get(GATE) != "1":
        return
    try:
        _install()
    except BaseException:
        # Optional upstream hooks can catch Exception. A failed journal must
        # never be mistaken for zero calls, even if the fixture uses os._exit.
        os._exit(FAILURE_EXIT)


def _install() -> None:
    import _thread
    import ctypes

    root = Path(os.environ[ROOT])
    nonce = os.environ[NONCE]
    if (
        os.name != "nt"
        or not root.is_absolute()
        or not _plain_directory(root)
        or len(nonce) != 32
        or any(char not in "0123456789abcdef" for char in nonce)
    ):
        raise ValueError("runtime_audit_invalid")
    buffer = ctypes.create_unicode_buffer(32768)
    copied = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < copied < len(buffer) or not Path(buffer.value).is_absolute():
        raise ValueError("runtime_audit_invalid")
    expected_cmd = str(Path(buffer.value) / "cmd.exe")
    lock = _thread.allocate_lock()
    count = 0
    installed_seen = False

    def observe(event, arguments):
        nonlocal count, installed_seen
        if event == "metroliza.qualifier.audit_installed" and arguments == (nonce,):
            installed_seen = True
            return
        if event != "subprocess.Popen":
            return
        acquired = False
        try:
            acquired = lock.acquire(timeout=1.0)
            if not acquired or count >= MAX_EVENTS:
                raise ValueError("runtime_audit_invalid")
            count += 1
            kind, caller = classify_call(arguments, sys._getframe(1), expected_cmd)
            phase = "after_ready" if (root / "ready").exists() else "startup"
            _write(
                root,
                f"event-{count:02}.json",
                {
                    "schema_version": 1,
                    "nonce": nonce,
                    "ordinal": count,
                    "kind": kind,
                    "caller": caller,
                    "phase": phase,
                },
            )
        except BaseException:
            os._exit(FAILURE_EXIT)
        finally:
            if acquired:
                lock.release()

    sys.addaudithook(observe)
    # CPython can silently decline registration if an earlier hook rejects it.
    sys.audit("metroliza.qualifier.audit_installed", nonce)
    if not installed_seen:
        raise ValueError("runtime_audit_invalid")
    _write(root, "installed.json", {"schema_version": 1, "nonce": nonce, "installed": True})


def read_evidence(root: Path, nonce: str) -> list[dict]:
    """Read only a drained Job's private journal; omit its nonce from output."""
    if not _plain_directory(root):
        raise ValueError("runtime_audit_invalid")
    names = []
    with os.scandir(root) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > MAX_EVENTS + 2:
                raise ValueError("runtime_audit_invalid")
    _remove_ready_name(root, names)
    if "installed.json" not in names:
        raise ValueError("runtime_audit_invalid")
    names.remove("installed.json")
    if len(names) > MAX_EVENTS:
        raise ValueError("runtime_audit_invalid")
    if sorted(names) != [f"event-{index:02}.json" for index in range(1, len(names) + 1)]:
        raise ValueError("runtime_audit_invalid")
    installed = _read(root / "installed.json")
    if (installed != {"schema_version": 1, "nonce": nonce, "installed": True}
            or type(installed.get("schema_version")) is not int
            or installed.get("installed") is not True):
        raise ValueError("runtime_audit_invalid")
    result = []
    for ordinal, name in enumerate(sorted(names), 1):
        event = _read(root / name)
        if (
            set(event) != {"schema_version", "nonce", "ordinal", "kind", "caller", "phase"}
            or type(event["schema_version"]) is not int
            or event["schema_version"] != 1
            or event["nonce"] != nonce
            or type(event["ordinal"]) is not int
            or event["ordinal"] != ordinal
            or event["kind"] not in KINDS
            or event["caller"] not in CALLERS
            or event["phase"] not in {"startup", "after_ready"}
        ):
            raise ValueError("runtime_audit_invalid")
        result.append({key: event[key] for key in ("kind", "caller", "phase")})
    return result


def _remove_ready_name(root: Path, names: list[str]) -> None:
    if "ready" not in names:
        return
    info = (root / "ready").lstat()
    if not _plain_file(info) or info.st_size != 0:
        raise ValueError("runtime_audit_invalid")
    names.remove("ready")


def _plain_file(info) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and not getattr(info, "st_file_attributes", 0) & 0x400
    )


def _read(path: Path) -> dict:
    info = path.lstat()
    if not _plain_file(info) or not 0 < info.st_size <= 1024:
        raise ValueError("runtime_audit_invalid")
    with path.open("rb") as stream:
        data = stream.read(1025)
    if len(data) != info.st_size:
        raise ValueError("runtime_audit_invalid")
    value = json.loads(data)
    if type(value) is not dict:
        raise ValueError("runtime_audit_invalid")
    return value

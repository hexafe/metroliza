"""Closed post-run fatal observation, stripped of paths, lines and raw text."""
from __future__ import annotations

import re
import json
import os
import stat
from pathlib import Path, PureWindowsPath

from metroliza.shared.diagnostic_fatal_probe import FATAL_FILE

EXIT_CLASSES = {
    0xC0000005: "access_violation", 0xC0000409: "stack_buffer_overrun",
    0xC0000374: "heap_corruption", 0xC00000FD: "stack_overflow",
    0xC000001D: "illegal_instruction", 0xC0000008: "invalid_handle",
    0xC0000142: "dll_init_failed", 0xC000013A: "control_c_exit",
    0xE06D7363: "cpp_exception", 3: "abort_3", 0xFFFFFFFF: "all_ones",
}
MAX_FATAL_BYTES = 64 * 1024
FRAME = re.compile(r"[A-Za-z0-9_.]{1,64}:[A-Za-z0-9_<>]{1,64}")
KINDS = frozenset({"access_violation", "stack_overflow", "fatal_python_error", "other"})


def exit_class(code: int) -> str:
    return EXIT_CLASSES.get(code, "other_ntstatus_error" if 0xC0000000 <= code <= 0xFFFFFFFE else "other_nonzero")


def absent_fatal_observation() -> dict:
    return {"present": False, "kind": "other", "frames": [], "truncated": False}


def valid_fatal_observation(value: object) -> bool:
    if type(value) is not dict or set(value) != {"present", "kind", "frames", "truncated"}:
        return False
    kind, frames = value["kind"], value["frames"]
    return (type(value["present"]) is bool and type(value["truncated"]) is bool
            and type(kind) is str and (kind in KINDS or re.fullmatch(r"code_0x[0-9a-f]{8}", kind) is not None)
            and type(frames) is list and len(frames) <= 12
            and all(type(frame) is str and FRAME.fullmatch(frame) is not None for frame in frames)
            and (value["present"] or value == absent_fatal_observation()))


def valid_exit_evidence(payload: dict) -> bool:
    code = payload.get("observed_exit_code")
    if code is not None and (type(code) is not int or not 0 <= code <= 0xFFFFFFFF):
        return False
    expected = exit_class(code) if type(code) is int and 0 < code <= 0xFFFFFFFF else None
    return (payload.get("observed_exit_class") == expected
            and (expected is None or type(payload.get("observed_exit_class")) is str)
            and (expected is not None or "observed_exit_class" not in payload)
            and valid_fatal_observation(payload.get("child_fatal_observation")))


def retain_fatal_observation(observation: dict, root: Path) -> None:
    # A failed Job cleanup does not establish that the writer has exited.
    observation["child_fatal_observation"] = (
        read_fatal_observation(root) if observation.get("owned_cleanup") == "complete"
        else absent_fatal_observation()
    )


def bound_fatal_frames(payload: dict, limit: int) -> dict:
    """Reserve the existing failure/phase evidence before retaining stack frames."""
    fatal = dict(payload["child_fatal_observation"])
    fatal["frames"] = list(fatal["frames"])
    payload["child_fatal_observation"] = fatal
    while fatal["frames"] and len(json.dumps(payload, separators=(",", ":"), ensure_ascii=True)) + 1 > limit:
        fatal["frames"].pop()
        fatal["truncated"] = True
    return payload


def _fatal_kind(first: str) -> str:
    fixed = {"Windows fatal exception: access violation": "access_violation",
             "Windows fatal exception: stack overflow": "stack_overflow"}
    if first in fixed:
        return fixed[first]
    code = re.fullmatch(r"Windows fatal exception: code 0x([0-9a-fA-F]{8})", first)
    if code is not None:
        return "code_0x" + code[1].lower()
    return "fatal_python_error" if first.startswith("Fatal Python error:") else "other"


def _current_frames(lines: list[str]) -> tuple[list[str], bool]:
    frames, active, truncated = [], False, False
    for line in lines:
        if not active:
            active = re.fullmatch(r"Current thread 0x[0-9a-fA-F]+ \(most recent call first\):", line) is not None
            continue
        if not line.startswith("  "):
            break
        match = re.fullmatch(r'  File "([^"\r\n]+)", line [0-9]+ in (.+)', line)
        if match is None:
            truncated = True
            continue
        frame = PureWindowsPath(match[1]).stem + ":" + match[2]
        if FRAME.fullmatch(frame) is None or len(frames) == 12:
            truncated = True
        else:
            frames.append(frame)
    return frames, truncated


def read_fatal_observation(root: Path) -> dict:
    """Called after the owned Job is closed, before private-root cleanup.

    Read at most 64 KiB from a regular, single-link, non-reparse file. Raw bytes
    stay inside this function and are never copied into public artifacts.
    """
    try:
        target = root / FATAL_FILE
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_size == 0):
            return absent_fatal_observation()
        def no_follow(path, flags):
            return os.open(path, flags | getattr(os, "O_NOFOLLOW", 0))

        with open(target, "rb", opener=no_follow) as stream:
            opened = os.fstat(stream.fileno())
            if ((opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                    or opened.st_nlink != 1 or not stat.S_ISREG(opened.st_mode)):
                return absent_fatal_observation()
            data = stream.read(MAX_FATAL_BYTES + 1)
    except OSError:
        return absent_fatal_observation()
    return _parse_fatal_bytes(data)


def _parse_fatal_bytes(data: bytes) -> dict:
    lines = data[:MAX_FATAL_BYTES].decode("ascii", errors="replace").splitlines()
    if len(data) > MAX_FATAL_BYTES and data[MAX_FATAL_BYTES - 1:MAX_FATAL_BYTES] != b"\n":
        # Never turn a byte-cut function name into an invented valid frame.
        lines = lines[:-1]
    frames, truncated = _current_frames(lines[1:])
    return {"present": True, "kind": _fatal_kind(lines[0]) if lines else "other",
            "frames": frames, "truncated": truncated or len(data) > MAX_FATAL_BYTES}

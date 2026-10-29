"""Closed post-run evidence, stripped of paths, thread ids, lines and raw text."""
from __future__ import annotations

import re
import json
import os
import stat
from pathlib import Path, PureWindowsPath

from metroliza.shared.diagnostic_fatal_probe import FATAL_FILE, INVENTORY_FILE, MAIN_THREAD_FILE

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
THREAD = re.compile(r"(Current thread|Thread) 0x([0-9a-fA-F]{1,16}) \(most recent call first\):")


def exit_class(code: int) -> str:
    return EXIT_CLASSES.get(code, "other_ntstatus_error" if 0xC0000000 <= code <= 0xFFFFFFFE else "other_nonzero")


def absent_fatal_observation() -> dict:
    return {"present": False, "kind": "other", "frames": [], "truncated": False, "multiple_blocks": False,
            "current_thread_marked": False, "faulting_is_main": "unknown", "python_threads": 0, "main_frames": []}


def _valid_frames(frames, limit: int) -> bool:
    return (type(frames) is list and len(frames) <= limit
            and all(type(frame) is str and FRAME.fullmatch(frame) is not None for frame in frames))


def _valid_thread_fields(value: dict) -> bool:
    marked, is_main, count = value["current_thread_marked"], value["faulting_is_main"], value["python_threads"]
    return (type(marked) is bool and (type(is_main) is bool or type(is_main) is str and is_main == "unknown")
            and type(count) is int and 0 <= count <= 32 and (not marked or count > 0)
            and (marked or is_main == "unknown" and value["frames"] == [])
            and (not value["main_frames"] or count > 0 and (not marked or is_main is False and count > 1))
            and _valid_frames(value["main_frames"], 6))


def valid_fatal_observation(value: object) -> bool:
    if type(value) is not dict or set(value) != set(absent_fatal_observation()):
        return False
    kind = value["kind"]
    return (type(value["present"]) is bool and type(value["truncated"]) is bool
            and type(value["multiple_blocks"]) is bool
            and type(kind) is str and (kind in KINDS or re.fullmatch(r"code_0x[0-9a-f]{8}", kind) is not None)
            and _valid_frames(value["frames"], 12) and _valid_thread_fields(value)
            and (value["present"] or value == absent_fatal_observation()))


def valid_exit_evidence(payload: dict) -> bool:
    code = payload.get("observed_exit_code")
    if code is not None and (type(code) is not int or not 0 <= code <= 0xFFFFFFFF):
        return False
    expected = exit_class(code) if type(code) is int and 0 < code <= 0xFFFFFFFF else None
    return (payload.get("observed_exit_class") == expected
            and (expected is None or type(payload.get("observed_exit_class")) is str)
            and (expected is not None or "observed_exit_class" not in payload)
            and valid_fatal_observation(payload.get("child_fatal_observation"))
            and "exit_inventory" in payload and valid_exit_inventory(payload["exit_inventory"]))


def valid_exit_inventory(value: object) -> bool:
    # None means absent, unreadable or invalid; never a zero-object census.
    if value is None:
        return True
    wrapper_counts = {"deleted_wrappers", "cpp_created_wrappers", "py_owned_wrappers"}
    counters = {"qt_wrappers", "threads_alive", "daemon_threads"} | wrapper_counts
    if type(value) is not dict or set(value) != counters | {"qapp_alive", "qt_classes"}:
        return False
    if type(value["qapp_alive"]) is not bool or any(type(value[k]) is not int or not 0 <= value[k] <= 10**6 for k in counters):
        return False
    classes = value["qt_classes"]
    if type(classes) is not list or len(classes) > 12 or not all(_valid_class(pair) for pair in classes):
        return False
    return (len({pair[0] for pair in classes}) == len(classes)
            and classes == sorted(classes, key=lambda pair: (-pair[1], pair[0]))
            and sum(pair[1] for pair in classes) <= value["qt_wrappers"]
            and all(value[key] <= value["qt_wrappers"] for key in wrapper_counts)
            and value["daemon_threads"] <= value["threads_alive"])


def _valid_class(pair: object) -> bool:
    return (type(pair) is list and len(pair) == 2 and type(pair[0]) is str
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,48}", pair[0]) is not None
            and type(pair[1]) is int and 1 <= pair[1] <= 10**6)


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_field")
        result[key] = value
    return result


def read_exit_inventory(root: Path) -> dict | None:
    raw = _read_private_bytes(root / INVENTORY_FILE, 4096)
    if raw is None or raw[1]:
        return None
    try:
        value = json.loads(raw[0], object_pairs_hook=_unique_json)
    except (ValueError, UnicodeError, RecursionError):
        return None
    return value if type(value) is dict and valid_exit_inventory(value) else None


def retain_fatal_observation(observation: dict, root: Path) -> None:
    # A failed Job cleanup does not establish that the writer has exited.
    observation["child_fatal_observation"] = (
        read_fatal_observation(root) if observation.get("owned_cleanup") == "complete"
        else absent_fatal_observation()
    )


def retain_exit_inventory(observation: dict, root: Path, *, scenario: str) -> None:
    inventory = read_exit_inventory(root) if observation.get("owned_cleanup") == "complete" else None
    observation["exit_inventory"] = inventory
    print(scenario + "_exit_inventory=" + json.dumps(inventory, separators=(",", ":"), ensure_ascii=True), flush=True)


def bound_fatal_frames(payload: dict, limit: int) -> dict:
    """Trim classes first, preserving existing failures and phases within 4096 B."""
    fatal = dict(payload["child_fatal_observation"])
    fatal["frames"] = list(fatal["frames"])
    fatal["main_frames"] = list(fatal["main_frames"])
    payload["child_fatal_observation"] = fatal
    inventory = payload.get("exit_inventory")
    if inventory is not None:
        inventory = dict(inventory, qt_classes=list(inventory["qt_classes"]))
        payload["exit_inventory"] = inventory
    for frames in ([inventory["qt_classes"]] if inventory is not None else []) + [fatal["main_frames"], fatal["frames"]]:
        while frames and len(json.dumps(payload, separators=(",", ":"), ensure_ascii=True)) + 1 > limit:
            frames.pop()
            if inventory is None or frames is not inventory["qt_classes"]:
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


def _stack_frames(lines: list[str], limit: int) -> tuple[list[str], bool]:
    frames, truncated = [], False
    for line in lines:
        if not line.startswith("  "):
            break
        if line == "  <no Python frame>":
            break
        match = re.fullmatch(r'  File "([^"\r\n]+)", line [0-9]+ in (.+)', line)
        if match is None:
            truncated = True
            continue
        frame = PureWindowsPath(match[1]).stem + ":" + match[2]
        if FRAME.fullmatch(frame) is None or len(frames) == limit:
            truncated = True
        else:
            frames.append(frame)
    return frames, truncated


def read_fatal_observation(root: Path) -> dict:
    """Read only after owned cleanup; private bytes never leave this reducer."""
    raw = _read_private_bytes(root / FATAL_FILE, MAX_FATAL_BYTES, tail=True)
    if raw is None or not raw[0]:
        return absent_fatal_observation()
    ident = _read_private_bytes(root / MAIN_THREAD_FILE, 32)
    match = re.fullmatch(rb"main_thread=0x([0-9a-f]{16})\r?\n", ident[0]) if ident is not None and not ident[1] else None
    main_ident = int(match[1], 16) if match is not None else None
    return _parse_fatal_bytes(raw[0], tail_cut=raw[1], main_ident=main_ident)


def _read_private_bytes(target: Path, limit: int, *, tail: bool = False) -> tuple[bytes, bool] | None:
    try:
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_size == 0):
            return None
        def no_follow(path, flags):
            return os.open(path, flags | getattr(os, "O_NOFOLLOW", 0))

        with open(target, "rb", opener=no_follow) as stream:
            opened = os.fstat(stream.fileno())
            if ((opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                    or opened.st_nlink != 1 or not stat.S_ISREG(opened.st_mode)
                    or getattr(opened, "st_file_attributes", 0) & 0x400):
                return None
            offset = max(0, opened.st_size - limit) if tail else 0
            stream.seek(offset)
            data = stream.read(limit)
    except OSError:
        return None
    return data, opened.st_size > limit


def _parse_fatal_bytes(data: bytes, *, tail_cut: bool = False, main_ident: int | None = None) -> dict:
    lines = data.decode("ascii", errors="replace").splitlines()
    headers = [index for index, line in enumerate(lines)
               if line.startswith(("Windows fatal exception:", "Fatal Python error:"))]
    # A leading fragment cannot supply identity or frames to a later block.
    block = lines[headers[-1]:] if headers else []
    threads = [(index, THREAD.fullmatch(line)) for index, line in enumerate(block) if THREAD.fullmatch(line)]
    current = next(((index, match) for index, match in threads if match[1] == "Current thread"), None)
    main = next(((index, match) for index, match in threads if int(match[2], 16) == main_ident), None)
    is_main = int(current[1][2], 16) == main_ident if current is not None and main_ident is not None else "unknown"
    frames, truncated = _stack_frames(block[current[0]+1:], 12) if current is not None else ([], False)
    main_frames, main_cut = (_stack_frames(block[main[0]+1:], 6)
                            if main is not None and is_main is not True else ([], False))
    return {"present": True, "kind": _fatal_kind(block[0]) if block else "other",
            "frames": frames, "truncated": truncated or tail_cut or main_cut,
            "multiple_blocks": len(headers) > 1, "current_thread_marked": current is not None,
            "faulting_is_main": is_main, "python_threads": min(len(threads), 32), "main_frames": main_frames}

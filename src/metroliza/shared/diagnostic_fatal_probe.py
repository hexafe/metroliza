"""Private qualification-only faulthandler sink; never a public raw artifact."""
from __future__ import annotations

import os
from pathlib import Path
import stat

from metroliza.shared.diagnostic_startup_probe import enabled

FATAL_FILE = "child-fatal-private.txt"
MAIN_THREAD_FILE = "child-main-thread-private.txt"
INVENTORY_FILE = "child-exit-inventory-private.json"
_fatal_stream: int | None = None


def _private_root() -> Path | None:
    if (not enabled() or os.getenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION") != "1"
            or not os.getenv("METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT")):
        return None
    root = Path(os.environ["METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT"])
    info = root.lstat()
    if (not root.is_absolute() or not stat.S_ISDIR(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400):
        return None
    return root


def _write_private(root: Path, name: str, data: bytes) -> None:
    descriptor = os.open(root / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def _wrapper_inventory(objects, sip) -> dict:
    import re

    wrappers, deleted, cpp_created, py_owned, classes = 0, 0, 0, 0, {}
    wrapper_type = getattr(sip, "simplewrapper", ())
    for obj in objects:
        if not isinstance(obj, wrapper_type):
            continue
        wrappers += 1
        name = type(obj).__name__
        name = name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,48}", name) else "other"
        classes[name] = classes.get(name, 0) + 1
        try:
            # These SIP queries read wrapper flags, never the wrapped C++ object.
            deleted += bool(sip.isdeleted(obj))
            cpp_created += not sip.ispycreated(obj)
            py_owned += bool(sip.ispyowned(obj))
        except Exception:
            # Optional observation can be partial if a flag query fails.
            pass
        if wrappers == 10**6:
            break
    return {"qt_wrappers": wrappers, "deleted_wrappers": deleted,
            "cpp_created_wrappers": cpp_created, "py_owned_wrappers": py_owned,
            "qt_classes": [[name, count] for name, count in sorted(classes.items(), key=lambda pair: (-pair[1], pair[0]))[:12]]}


def _write_exit_inventory(root: Path) -> None:
    """Read wrapper flags with automatic GC suspended; never call object methods."""
    try:
        import gc

        was_enabled = gc.isenabled()
        gc.disable()
        try:
            import json
            import sys
            import threading

            qtcore, sip = sys.modules.get("PyQt6.QtCore"), sys.modules.get("PyQt6.sip")
            inventory = _wrapper_inventory(gc.get_objects(), sip)
            # Static lookup only: do not dereference the returned application.
            inventory["qapp_alive"] = qtcore is not None and qtcore.QCoreApplication.instance() is not None
            threads = threading.enumerate()
            inventory.update(threads_alive=min(len(threads), 10**6),
                             daemon_threads=min(sum(thread.daemon for thread in threads), 10**6))
            _write_private(root, INVENTORY_FILE, json.dumps(inventory, separators=(",", ":")).encode("ascii"))
        finally:
            if was_enabled:
                gc.enable()
    except BaseException:
        # Python callback errors do not escape; native faults cannot be caught here.
        pass


def register_private_exit_inventory() -> None:
    try:
        root = _private_root()
        if root is not None:
            import atexit

            atexit.register(_write_exit_inventory, root)
    except BaseException:
        pass


def enable_private_fatal_probe() -> None:
    """Keep the sink alive through atexit; the host owns post-run removal."""
    global _fatal_stream
    if _fatal_stream is not None:
        return
    stream = None
    try:
        root = _private_root()
        if root is None:
            return
        # Exclusive creation, restricted mode on POSIX, inherited private-root
        # ACL on Windows. Do not truncate or follow any pre-existing sink.
        stream = os.open(root / FATAL_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.set_inheritable(stream, False)
        import faulthandler
        import threading

        ident = threading.main_thread().ident
        if type(ident) is int and 0 < ident <= 0xFFFFFFFFFFFFFFFF:
            _write_private(root, MAIN_THREAD_FILE, f"main_thread=0x{ident:016x}\n".encode("ascii"))
        faulthandler.enable(file=stream, all_threads=True)
        _fatal_stream = stream
    except (OSError, ValueError, RuntimeError):
        if stream is not None:
            os.close(stream)

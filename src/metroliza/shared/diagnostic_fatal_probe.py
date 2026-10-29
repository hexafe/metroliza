"""Private qualification-only faulthandler sink; never a public raw artifact."""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import BinaryIO

from metroliza.shared.diagnostic_startup_probe import enabled

FATAL_FILE = "child-fatal-private.txt"
_fatal_stream: BinaryIO | None = None


def enable_private_fatal_probe() -> None:
    """Keep the sink alive through atexit; the host owns post-run removal."""
    global _fatal_stream
    if not enabled() or not os.getenv("METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT") or _fatal_stream is not None:
        return
    stream = None
    try:
        root = Path(os.environ["METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT"])
        info = root.lstat()
        if (not root.is_absolute() or not stat.S_ISDIR(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400):
            return
        # Exclusive creation, restricted mode on POSIX, inherited private-root
        # ACL on Windows. Do not truncate or follow any pre-existing sink.
        def private_open(path, flags):
            return os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)

        stream = open(root / FATAL_FILE, "xb", opener=private_open)
        import faulthandler

        faulthandler.enable(file=stream, all_threads=True)
        _fatal_stream = stream
    except (OSError, ValueError, RuntimeError):
        if stream is not None:
            stream.close()

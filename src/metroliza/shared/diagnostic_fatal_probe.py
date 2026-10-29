"""Private qualification-only faulthandler sink; never a public raw artifact."""
from __future__ import annotations

import os
from pathlib import Path
import stat

from metroliza.shared.diagnostic_startup_probe import enabled

FATAL_FILE = "child-fatal-private.txt"
_fatal_stream: int | None = None


def enable_private_fatal_probe() -> None:
    """Keep the sink alive through atexit; the host owns post-run removal."""
    global _fatal_stream
    if (not enabled() or os.getenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION") != "1"
            or not os.getenv("METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT") or _fatal_stream is not None):
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
        stream = os.open(root / FATAL_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.set_inheritable(stream, False)
        import faulthandler

        faulthandler.enable(file=stream, all_threads=True)
        _fatal_stream = stream
    except (OSError, ValueError, RuntimeError):
        if stream is not None:
            os.close(stream)

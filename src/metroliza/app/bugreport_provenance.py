"""Closed technical build facts for a manually copied diagnostic report.

Never inspect user files, host names, environment contents or installed package
paths here. Unknown facts stay unknown instead of being inferred from the host.
"""

from __future__ import annotations

import platform
import sys


def collect_bugreport_build_facts() -> dict[str, object]:
    facts: dict[str, object] = {
        "platform": {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(
            sys.platform, "unknown"
        ),
        "arch": "unknown",
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "qt": "unknown",
        "pyqt": "unknown",
        "runtime": "unknown",
        "packager": "unknown",
        "git_sha": "unknown",
        "dirty": None,
    }
    try:
        architecture = platform.machine()
        facts["arch"] = {
            "AMD64": "x86_64", "amd64": "x86_64", "x86_64": "x86_64",
            "aarch64": "arm64", "arm64": "arm64",
        }.get(architecture, "unknown") if type(architecture) is str else "unknown"
    except Exception:
        pass
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

        facts["qt"], facts["pyqt"] = QT_VERSION_STR, PYQT_VERSION_STR
    except (ImportError, RuntimeError):
        pass
    try:
        from metroliza.app.bootstrap import _project_build_identity

        runtime, packager, sha, dirty = _project_build_identity()
        facts.update(runtime=runtime.value, packager=packager.value, git_sha=sha, dirty=dirty)
    except Exception:
        pass
    return facts

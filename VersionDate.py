"""Compatibility module for release metadata.

Canonical release metadata lives in ``metroliza.app.version``.
"""

from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_ROOT = _Path(globals().get("__file__", _Path.cwd() / "VersionDate.py")).resolve().parent
_SRC = _ROOT / "src"
if _SRC.exists():
    _src_text = str(_SRC)
    if _src_text not in _sys.path:
        _sys.path.insert(0, _src_text)

from metroliza.app.version import *  # noqa: E402,F403

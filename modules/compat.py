"""Compatibility helpers for the legacy ``modules.*`` namespace."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import sys
from types import ModuleType


def _ensure_src_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    src_text = str(src_dir)
    if not src_dir.exists():
        return
    if src_text in sys.path:
        sys.path.remove(src_text)
    sys.path.insert(0, src_text)


def alias_module(legacy_name: str, canonical_name: str) -> ModuleType:
    """Return the canonical module and bind the legacy name to the same object."""
    _ensure_src_on_path()
    module = import_module(canonical_name)
    sys.modules[legacy_name] = module
    return module

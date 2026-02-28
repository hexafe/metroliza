"""Native parsing bridge for CMM block tokenization prototype."""

from __future__ import annotations

import os
from typing import Any, Literal

from modules.cmm_parsing import parse_raw_lines_to_blocks

try:
    from _metroliza_cmm_native import parse_blocks as _native_parse_blocks  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_parse_blocks = None

BackendChoice = Literal["auto", "native", "python"]


def _runtime_backend_choice() -> BackendChoice:
    choice = os.getenv("METROLIZA_CMM_PARSER_BACKEND", "auto").strip().lower()
    if choice in {"auto", "native", "python"}:
        return choice
    return "auto"


def parse_blocks_with_backend(raw_lines: list[str], use_native: bool = False) -> list[list[Any]]:
    """Parse blocks with a selectable backend.

    Native backend is prototype-only and disabled by default.
    """
    backend = _runtime_backend_choice()
    should_use_native = use_native or backend == "native" or (
        backend == "auto" and _native_parse_blocks is not None
    )

    if should_use_native:
        if _native_parse_blocks is None:
            if backend == "native":
                raise RuntimeError("Native CMM parser backend requested but unavailable")
            return parse_raw_lines_to_blocks(raw_lines)

        try:
            return _native_parse_blocks(raw_lines)
        except Exception:  # pragma: no cover - safety fallback
            if backend == "native":
                raise
    return parse_raw_lines_to_blocks(raw_lines)


def native_backend_available() -> bool:
    return _native_parse_blocks is not None

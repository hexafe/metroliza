"""Native parsing bridge for CMM block tokenization prototype."""

from __future__ import annotations

from typing import Any

from modules.cmm_parsing import parse_raw_lines_to_blocks

try:
    from _metroliza_cmm_native import parse_blocks as _native_parse_blocks  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_parse_blocks = None


def parse_blocks_with_backend(raw_lines: list[str], use_native: bool = False) -> list[list[Any]]:
    """Parse blocks with a selectable backend.

    Native backend is prototype-only and disabled by default.
    """
    if use_native and _native_parse_blocks is not None:
        return _native_parse_blocks(raw_lines)
    return parse_raw_lines_to_blocks(raw_lines)


def native_backend_available() -> bool:
    return _native_parse_blocks is not None

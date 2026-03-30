"""Native parsing bridge for CMM block tokenization."""

from __future__ import annotations

import os
from typing import Any, Literal, NamedTuple

from modules.cmm_parsing import parse_raw_lines_to_blocks

try:
    from _metroliza_cmm_native import parse_blocks as _native_parse_blocks  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_parse_blocks = None

BackendChoice = Literal["auto", "native", "python"]
ResolvedBackend = Literal["native", "python"]


class ParseBackendResult(NamedTuple):
    blocks: list[list[Any]]
    backend: ResolvedBackend


def _runtime_backend_choice() -> BackendChoice:
    choice = os.getenv("METROLIZA_CMM_PARSER_BACKEND", "auto").strip().lower()
    if choice in {"auto", "native", "python"}:
        return choice
    return "auto"


def resolve_cmm_parser_backend(use_native: bool = False) -> ResolvedBackend:
    """Resolve which parser backend should be used for the current runtime."""
    backend = _runtime_backend_choice()

    if backend == "python":
        return "python"

    if backend == "native" or use_native:
        if _native_parse_blocks is None:
            raise RuntimeError("Native CMM parser backend requested but unavailable")
        return "native"

    if _native_parse_blocks is not None:
        return "native"
    return "python"


def parse_blocks_with_backend_and_telemetry(
    raw_lines: list[str],
    use_native: bool = False,
) -> ParseBackendResult:
    """Parse blocks and return both output and backend used."""
    resolved_backend = resolve_cmm_parser_backend(use_native=use_native)
    if resolved_backend == "native":
        if _native_parse_blocks is None:
            raise RuntimeError("Native CMM parser backend requested but unavailable")
        return ParseBackendResult(blocks=_native_parse_blocks(raw_lines), backend="native")

    return ParseBackendResult(blocks=parse_raw_lines_to_blocks(raw_lines), backend="python")


def parse_blocks_with_backend(raw_lines: list[str], use_native: bool = False) -> list[list[Any]]:
    """Parse blocks with explicit backend selection policy."""
    return parse_blocks_with_backend_and_telemetry(raw_lines, use_native=use_native).blocks


def native_backend_available() -> bool:
    return _native_parse_blocks is not None

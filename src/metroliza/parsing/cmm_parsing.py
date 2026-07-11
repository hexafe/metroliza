"""Compatibility facade for the dependency-neutral CMM block parser.

New backend code should import :mod:`metroliza.cmm.block_parser` directly.  This
module remains the canonical parsing-facing path, and ``modules.cmm_parsing``
continues to alias this module for legacy callers.
"""

from metroliza.cmm.block_parser import (
    MEASUREMENT_LINE_MAP,
    MEASUREMENT_STATUS_TOKENS,
    add_tolerances_to_blocks,
    parse_raw_lines_to_blocks,
)

__all__ = [
    "MEASUREMENT_LINE_MAP",
    "MEASUREMENT_STATUS_TOKENS",
    "add_tolerances_to_blocks",
    "parse_raw_lines_to_blocks",
]

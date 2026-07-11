"""Registry and validation for built-in realtime industrial detectors."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


SUPPORTED_REALTIME_DETECTORS = frozenset(
    {"spec_limits", "iqr", "mad_zscore", "rolling_zscore", "stale_source"}
)


class UnsupportedRealtimeDetectorError(ValueError):
    """Raised when a detector key cannot be executed by the realtime service."""


def normalize_detector_keys(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalize, deduplicate, and validate configured detector keys."""

    normalized = tuple(
        dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip())
    )
    unsupported = tuple(key for key in normalized if key not in SUPPORTED_REALTIME_DETECTORS)
    if unsupported:
        supported = ", ".join(sorted(SUPPORTED_REALTIME_DETECTORS))
        raise UnsupportedRealtimeDetectorError(
            f"Unsupported realtime detector(s): {', '.join(unsupported)}. Supported: {supported}."
        )
    return normalized

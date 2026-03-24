"""Helpers for fast group-stats numeric coercion with optional native acceleration."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

try:
    from _metroliza_group_stats_native import coerce_sequence_to_float64 as _native_coerce_sequence_to_float64  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_coerce_sequence_to_float64 = None


def _coerce_sequence_to_float64_python(values: Sequence[Any]) -> np.ndarray:
    object_values = np.asarray(values, dtype=object)
    coerced = np.empty(object_values.size, dtype=np.float64)
    for idx, value in enumerate(object_values):
        try:
            coerced[idx] = float(value)
        except (TypeError, ValueError):
            coerced[idx] = np.nan
    return np.ascontiguousarray(coerced, dtype=np.float64)


def coerce_sequence_to_float64(values: Sequence[Any]) -> np.ndarray:
    """Return contiguous float64 values with NaN placeholders for failed coercions."""

    if _native_coerce_sequence_to_float64 is not None:
        coerced = _native_coerce_sequence_to_float64(values)
        return np.ascontiguousarray(coerced, dtype=np.float64)

    return _coerce_sequence_to_float64_python(values)


def native_backend_available() -> bool:
    return _native_coerce_sequence_to_float64 is not None

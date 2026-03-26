"""Helpers for fast group-stats numeric coercion with optional native acceleration."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import numpy as np

try:
    from _metroliza_group_stats_native import coerce_sequence_to_float64 as _native_coerce_sequence_to_float64  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_coerce_sequence_to_float64 = None


def _runtime_backend_choice() -> str:
    choice = os.getenv("METROLIZA_GROUP_STATS_BACKEND", "auto").strip().lower()
    if choice in {"auto", "native", "python"}:
        return choice
    return "python"


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

    selected_backend = _runtime_backend_choice()
    if selected_backend == "python":
        return _coerce_sequence_to_float64_python(values)

    if _native_coerce_sequence_to_float64 is not None:
        native_input: Sequence[Any] = values
        if isinstance(values, np.ndarray):
            if values.dtype == np.float64 and values.flags.c_contiguous:
                native_input = values
            elif values.dtype != object:
                native_input = np.ascontiguousarray(values, dtype=np.float64)

        coerced = _native_coerce_sequence_to_float64(native_input)
        return np.ascontiguousarray(coerced, dtype=np.float64)

    if selected_backend == "native":
        raise RuntimeError("Native group-stats backend requested but unavailable")

    return _coerce_sequence_to_float64_python(values)


def native_backend_available() -> bool:
    return _native_coerce_sequence_to_float64 is not None

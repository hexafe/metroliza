"""Shared array preparation helpers for optional native bridges."""

from __future__ import annotations

from typing import Sequence

import numpy as np


def as_float64_1d_contiguous(values: Sequence[float] | np.ndarray) -> np.ndarray:
    """Return a contiguous float64 1D array, rejecting non-1D inputs."""
    if isinstance(values, np.ndarray) and values.dtype == np.float64 and values.flags["C_CONTIGUOUS"]:
        array = values
    else:
        array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError("Expected 1D numeric input")
    if array.flags["C_CONTIGUOUS"]:
        return array
    return np.ascontiguousarray(array)

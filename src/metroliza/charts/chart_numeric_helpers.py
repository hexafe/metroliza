"""Small numeric helpers shared by chart spec builders and renderers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
import math

import numpy as np

from metroliza.shared.numeric_coercion import coerce_finite_float


def as_finite_float(value: Any) -> float | None:
    return coerce_finite_float(value)


def finite_array(values: Iterable[Any]) -> np.ndarray:
    arr = np.asarray(list(values), dtype=float)
    return arr[np.isfinite(arr)]


def line_ticks(min_value: float, max_value: float, *, count: int = 5) -> list[float]:
    if not math.isfinite(min_value) or not math.isfinite(max_value):
        return [0.0, 1.0]
    if math.isclose(min_value, max_value):
        return [min_value]
    return [min_value + ((max_value - min_value) * idx / max(1, count - 1)) for idx in range(count)]


def format_tick(value: float) -> str:
    numeric = float(value)
    if abs(numeric) >= 100 or math.isclose(numeric, round(numeric), abs_tol=1e-9):
        return f"{numeric:.0f}"
    if abs(numeric) >= 10:
        return f"{numeric:.1f}"
    return f"{numeric:.3f}".rstrip("0").rstrip(".")


def format_histogram_stat_value(value: Any, *, decimals: int = 3) -> str:
    numeric = as_finite_float(value)
    if numeric is None:
        return "N/A"
    if math.isclose(numeric, round(numeric), abs_tol=1e-9):
        return f"{numeric:.0f}"
    return f"{numeric:.{decimals}f}"

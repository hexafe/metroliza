"""Shared numeric coercion helpers."""

from __future__ import annotations

from typing import Any
import math


def coerce_finite_float(value: Any) -> float | None:
    """Return ``value`` as a finite float, or ``None`` when coercion fails."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric

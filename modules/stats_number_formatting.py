"""Shared number-formatting helpers for stats and distribution-fit displays."""

from __future__ import annotations

import math

PROBABILITY_DISPLAY_FLOOR = 0.001


def _to_finite_float(value):
    if isinstance(value, str):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def format_capability_index(value, *, na='N/A'):
    """Format Cp/Cpk/Cpu/Cpl values with fixed two decimals."""
    numeric = _to_finite_float(value)
    if numeric is None:
        return na
    return f"{numeric:.2f}"


def format_measurement_value(value, *, na='N/A'):
    """Format raw measurement summary values with fixed three decimals."""
    numeric = _to_finite_float(value)
    if numeric is None:
        return na
    return f"{numeric:.3f}"


def format_percent_from_ratio(value, *, decimals=2, na='N/A'):
    """Format ratio values (0..1) as percentages with fixed decimals."""
    numeric = _to_finite_float(value)
    if numeric is None:
        return na
    return f"{numeric * 100.0:.{int(decimals)}f}%"


def format_probability(value, *, decimals=3, threshold=PROBABILITY_DISPLAY_FLOOR, na='N/A'):
    """Format 0..1 probabilities with tiny-value notation (e.g. '<0.001')."""
    numeric = _to_finite_float(value)
    if numeric is None:
        return na
    bounded = max(0.0, min(1.0, numeric))
    if 0.0 < bounded < threshold:
        return f"<{threshold:.{int(decimals)}f}"
    return f"{bounded:.{int(decimals)}f}"


def format_probability_percent(value, *, decimals=3, threshold_percent=0.001, na='N/A'):
    """Format 0..1 probabilities as percents with tiny-value notation."""
    numeric = _to_finite_float(value)
    if numeric is None:
        return na
    bounded = max(0.0, min(1.0, numeric))
    as_percent = bounded * 100.0
    if 0.0 < as_percent < threshold_percent:
        return f"<{threshold_percent:.{int(decimals)}f}%"
    return f"{as_percent:.{int(decimals)}f}%"


def format_ppm(value, *, na='N/A'):
    """Format parts-per-million values with grouping and no decimals."""
    numeric = _to_finite_float(value)
    if numeric is None:
        return na
    return f"{numeric:,.0f}"

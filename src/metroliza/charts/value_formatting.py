"""Shared value formatting for chart labels and legends."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Any

_REFERENCE_LABELS = {"lsl", "nom", "nominal", "usl"}


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _clamped_precision(value: int | None, *, default: int) -> int:
    precision = default if value is None else int(value)
    return max(0, min(precision, 8))


def _half_up_decimal(value: float, precision: int) -> Decimal:
    quantizer = Decimal("1").scaleb(-precision)
    return Decimal(str(round(float(value), 12))).quantize(quantizer, rounding=ROUND_HALF_UP)


def format_compact_decimal(value: Any, *, precision: int = 3) -> str:
    """Round half-up and strip non-significant trailing zeros."""

    numeric = _finite_float(value)
    if numeric is None:
        return ""
    precision = _clamped_precision(precision, default=3)
    rounded = _half_up_decimal(numeric, precision)
    text = f"{rounded:.{precision}f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def format_fixed_decimal(value: Any, *, precision: int = 3) -> str:
    """Round half-up and keep the requested number of decimals."""

    numeric = _finite_float(value)
    if numeric is None:
        return ""
    precision = _clamped_precision(precision, default=3)
    rounded = _half_up_decimal(numeric, precision)
    return f"{rounded:.{precision}f}"


def format_metrology_legend_value(
    label: str,
    value: Any,
    *,
    mean_precision: int | None = None,
    mean_default_precision: int = 4,
    reference_precision: int = 3,
) -> str:
    """Format a chart stat/reference value without duplicate-looking zeros."""

    normalized = str(label or "").strip().casefold()
    if normalized == "mean":
        return format_fixed_decimal(
            value,
            precision=_clamped_precision(mean_precision, default=mean_default_precision),
        )
    if normalized in _REFERENCE_LABELS:
        return format_compact_decimal(value, precision=reference_precision)
    return format_fixed_decimal(value, precision=3)


def format_metrology_label_text(
    label: str,
    value: Any,
    *,
    mean_precision: int | None = None,
    mean_default_precision: int = 3,
    mean_separator: str = "=",
    reference_precision: int = 3,
) -> str:
    """Return ``Label=value`` text for visible chart annotations."""

    display_label = str(label or "").strip() or "Value"
    formatted = format_metrology_legend_value(
        display_label,
        value,
        mean_precision=mean_precision,
        mean_default_precision=mean_default_precision,
        reference_precision=reference_precision,
    )
    if display_label.casefold() == "mean":
        return f"Mean{mean_separator}{formatted}"
    return f"{display_label}={formatted}"

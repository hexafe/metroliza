"""Exact numeric validation shared by realtime industrial contracts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

SQLITE_SIGNED_INT64_MAX = 2**63 - 1


def exact_integral(
    value: Any,
    *,
    field_name: str,
    minimum: int = 0,
    maximum: int = SQLITE_SIGNED_INT64_MAX,
) -> int:
    """Return an exact bounded integer, rejecting bools and fractional values."""

    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be an exact integer")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an exact integer") from exc
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        raise ValueError(f"{field_name} must be an exact integer")
    integer = int(parsed)
    if integer < minimum or integer > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return integer


def finite_number(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    """Return a finite float satisfying an optional lower bound."""

    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number") from exc
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        raise ValueError(f"{field_name} must be a finite number")
    if minimum is not None:
        below = parsed < minimum if minimum_inclusive else parsed <= minimum
        if below:
            comparator = "at least" if minimum_inclusive else "greater than"
            raise ValueError(f"{field_name} must be {comparator} {minimum}")
    return parsed

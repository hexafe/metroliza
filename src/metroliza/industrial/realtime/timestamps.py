"""Canonical timestamp handling for realtime industrial data."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class IndustrialTimestampError(ValueError):
    """Raised when an industrial timestamp or source timezone is invalid."""


def validate_source_timezone(value: Any) -> str:
    """Return a normalized IANA timezone name that can be loaded by ``zoneinfo``."""

    name = str(value or "UTC").strip() or "UTC"
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise IndustrialTimestampError(f"Unknown source timezone: {name}") from exc
    return name


def parse_utc_timestamp(value: Any, *, source_timezone: str = "UTC") -> datetime:
    """Parse a timestamp and return an aware UTC datetime.

    Offset-aware inputs retain their explicit offset. Naive inputs are interpreted in the
    configured source timezone, so source database timestamps are never silently tied to the
    workstation timezone.
    """

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        text = str(value or "").strip()
        if not text:
            raise IndustrialTimestampError("timestamp is required")
        if text.endswith(("Z", "z")):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise IndustrialTimestampError(f"Invalid ISO-8601 timestamp: {value!r}") from exc

    if parsed.tzinfo is None:
        timezone_name = validate_source_timezone(source_timezone)
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def canonical_utc_timestamp(value: Any, *, source_timezone: str = "UTC") -> str:
    """Return a lexicographically sortable ISO-8601 UTC timestamp."""

    return parse_utc_timestamp(value, source_timezone=source_timezone).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def utc_now_text() -> str:
    """Return the current time in canonical UTC form."""

    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

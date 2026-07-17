"""Dependency-free parsing for user-entered tabular date and datetime literals."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from typing import Any


_TIME_SUFFIXES = (
    "",
    " %H:%M",
    " %H:%M:%S",
    " %I:%M %p",
    " %I:%M:%S %p",
)
_YEAR_FIRST_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d")
_DAY_FIRST_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%d-%m-%Y",
    "%d/%m/%y",
    "%d.%m.%y",
    "%d-%m-%y",
)
_MONTH_FIRST_DATE_FORMATS = (
    "%m/%d/%Y",
    "%m.%d.%Y",
    "%m-%d-%Y",
    "%m/%d/%y",
    "%m.%d.%y",
    "%m-%d-%y",
)
_MONTH_NAME_DATE_FORMATS = (
    "%b %d %Y",
    "%B %d %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%b-%d-%Y",
    "%B-%d-%Y",
    "%d-%b-%y",
    "%d-%B-%y",
    "%b-%d-%y",
    "%B-%d-%y",
)


def parse_datetime_literal(value: Any, *, dayfirst: bool = False) -> datetime | None:
    """Parse the stable date surface historically accepted by tabular filters.

    A timezone on an input literal is intentionally discarded without converting the
    clock.  Filter comparisons operate on the source's wall-calendar date.
    """

    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    for format_string in _datetime_formats(bool(dayfirst)):
        try:
            return datetime.strptime(text, format_string)
        except ValueError:
            continue
    return None


@lru_cache(maxsize=2)
def _datetime_formats(dayfirst: bool) -> tuple[str, ...]:
    ambiguous_formats = (
        _DAY_FIRST_DATE_FORMATS + _MONTH_FIRST_DATE_FORMATS
        if dayfirst
        else _MONTH_FIRST_DATE_FORMATS + _DAY_FIRST_DATE_FORMATS
    )
    date_formats = (
        *_YEAR_FIRST_DATE_FORMATS,
        *ambiguous_formats,
        *_MONTH_NAME_DATE_FORMATS,
    )
    return tuple(
        f"{date_format}{time_suffix}"
        for date_format in date_formats
        for time_suffix in _TIME_SUFFIXES
    )

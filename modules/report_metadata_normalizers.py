"""Pure normalization helpers for report metadata fields."""

from __future__ import annotations

from datetime import date as date_type
from datetime import time as time_type
import re


_SPACE_RE = re.compile(r"\s+")
_NUMERIC_DATE_RE = re.compile(
    r"(?P<year>\d{4})[.\-/_\s]+(?P<month>\d{1,2})[.\-/_\s]+(?P<day>\d{1,2})"
)
_REVERSED_NUMERIC_DATE_RE = re.compile(
    r"(?P<day>\d{1,2})[.\-/_\s]+(?P<month>\d{1,2})[.\-/_\s]+(?P<year>\d{4})"
)
_POLISH_MONTH_RE = re.compile(
    r"(?P<day>\d{1,2})[.\-/_\s]+(?P<month>stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|wrzesnia|września|pazdziernika|października|listopada|grudnia)"
    r"[.\-/_\s]+(?P<year>\d{4})",
    re.IGNORECASE,
)
_TIME_RE = re.compile(
    r"^(?P<hour>\d{1,2})[.:/\-\s]+(?P<minute>\d{1,2})(?:[.:/\-\s]+(?P<second>\d{1,2}))?$"
)

_POLISH_MONTHS = {
    "stycznia": "01",
    "lutego": "02",
    "marca": "03",
    "kwietnia": "04",
    "maja": "05",
    "czerwca": "06",
    "lipca": "07",
    "sierpnia": "08",
    "września": "09",
    "wrzesnia": "09",
    "października": "10",
    "pazdziernika": "10",
    "listopada": "11",
    "grudnia": "12",
}


def _stringify(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _collapse_spaces(value: str | None) -> str | None:
    text = _stringify(value)
    if text is None:
        return None
    return _SPACE_RE.sub(" ", text)


def normalize_reference(value) -> str | None:
    return _collapse_spaces(value)


def _build_date(year: int, month: int, day: int) -> str | None:
    try:
        return date_type(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_report_date(value) -> str | None:
    text = _collapse_spaces(value)
    if text is None:
        return None

    match = _NUMERIC_DATE_RE.search(text)
    if match:
        return _build_date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )

    match = _REVERSED_NUMERIC_DATE_RE.search(text)
    if match:
        return _build_date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )

    match = _POLISH_MONTH_RE.search(text)
    if match:
        month_text = match.group("month").lower()
        month = int(_POLISH_MONTHS[month_text])
        return _build_date(
            int(match.group("year")),
            month,
            int(match.group("day")),
        )

    return None


def normalize_report_time(value) -> str | None:
    text = _collapse_spaces(value)
    if text is None:
        return None

    match = _TIME_RE.match(text)
    if not match:
        return None

    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    second_text = match.group("second")
    second = int(second_text) if second_text is not None else None

    try:
        if second is None:
            time_type(hour, minute)
            return f"{hour:02d}:{minute:02d}"
        time_type(hour, minute, second)
        return f"{hour:02d}:{minute:02d}:{second:02d}"
    except ValueError:
        return None


def normalize_part_name(value, *, from_filename: bool = False) -> str | None:
    text = _stringify(value)
    if text is None:
        return None

    if from_filename:
        text = text.replace("_", " ")
    return _collapse_spaces(text)


def normalize_revision(value) -> str | None:
    return _collapse_spaces(value)


def normalize_stats_count(value) -> tuple[str | None, int | None]:
    text = _collapse_spaces(value)
    if text is None:
        return None, None

    cleaned = text.replace(",", "")
    if re.fullmatch(r"\d+", cleaned):
        return cleaned, int(cleaned)
    return text, None


def normalize_sample_number(value) -> str | None:
    return _collapse_spaces(value)


def normalize_operator_name(value) -> str | None:
    return _collapse_spaces(value)


def normalize_comment(value) -> str | None:
    text = _collapse_spaces(value)
    return text if text else None

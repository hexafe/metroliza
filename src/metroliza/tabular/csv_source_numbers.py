"""Infer CSV field boundaries and interpret numbers without guessing magnitudes."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from itertools import islice
import math
from pathlib import Path
import re


_DOT = 1
_COMMA = 2
_SAMPLE_ROWS = 200
_DELIMITERS = (",", ";", "\t", "|")
_EXPONENT = r"(?:[eE][+-]?\d+)?"
_GROUPED_COMMA = re.compile(rf"[+-]?[1-9]\d{{0,2}}(?:,\d{{3}})+(?:\.\d+)?{_EXPONENT}")
_GROUPED_DOT = re.compile(rf"[+-]?[1-9]\d{{0,2}}(?:\.\d{{3}})+(?:,\d+)?{_EXPONENT}")
_IDENTIFIER = re.compile(r"[+-]?\d+")
_IDENTIFIER_HEADERS = frozenset(
    {"batch code", "id", "lot", "part", "part id", "part number", "ref", "reference",
     "reference id", "row id", "serial", "serial number"}
)
_AMBIGUOUS_NUMBER_MESSAGE = (
    "Ambiguous CSV number separators. Use one decimal convention per numeric column, "
    "remove thousands separators, and use an extra trailing decimal zero for ambiguous values, "
    "or load an Excel worksheet with numeric cells."
)


def is_csv_identifier_header(header: str) -> bool:
    return " ".join(header.casefold().replace("_", " ").replace("-", " ").split()) in _IDENTIFIER_HEADERS


def csv_value_looks_like_identifier(text: str) -> bool:
    digits = text.lstrip("+-")
    return (
        (len(digits) > 15 or (len(digits) > 1 and digits.startswith("0")))
        and _IDENTIFIER.fullmatch(text) is not None
    )


def _source_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _number_options(text: str | None) -> tuple[float | None, float | None]:
    """Return syntactically valid values under dot and comma conventions.

    An overflow keeps its separator evidence, but is never stored as a number.
    """
    if not text or "_" in text:
        return None, None
    has_dot = "." in text
    has_comma = "," in text
    if has_dot and has_comma:
        if text.rfind(".") > text.rfind(",") and _GROUPED_COMMA.fullmatch(text):
            return _source_float(text.replace(",", "")), None
        if _GROUPED_DOT.fullmatch(text):
            return None, _source_float(text.replace(".", "").replace(",", "."))
        return None, None
    if has_dot:
        grouped = None
        if (text[-4:-3] == "." or "e" in text or "E" in text) and _GROUPED_DOT.fullmatch(text):
            grouped = _source_float(text.replace(".", ""))
        return _source_float(text), grouped
    if has_comma:
        grouped = None
        if (text[-4:-3] == "," or "e" in text or "E" in text) and _GROUPED_COMMA.fullmatch(text):
            grouped = _source_float(text.replace(",", ""))
        return grouped, _source_float(text.replace(",", "."))
    number = _source_float(text)
    return number, number


def _number_evidence(dot: float | None, comma: float | None) -> int:
    if comma is None:
        return _DOT if dot is not None else 0
    return _COMMA if dot is None else 0


def validate_csv_width(row: list[str] | tuple[str, ...], width: int) -> None:
    if len(row) > width and any(cell.strip() for cell in row[width:]):
        raise ValueError(
            "A CSV row has more fields than the header. Check the delimiter and quote fields that contain it."
        )


@dataclass(frozen=True)
class CsvSourceSample:
    delimiter: str
    header: tuple[str, ...]
    rows: list[tuple[str, ...]]

    def evidence(self, text_fields: frozenset[int]) -> tuple[tuple[int, ...], tuple[int, ...]]:
        conventions: list[int] = []
        numeric_counts: list[int] = []
        for index in range(len(self.header)):
            observed = count = 0
            if index not in text_fields:
                for row in self.rows:
                    if index < len(row):
                        dot, comma = _number_options(row[index].strip())
                        observed |= _number_evidence(dot, comma)
                        count += dot is not None or comma is not None
            conventions.append(observed)
            numeric_counts.append(count)
        return tuple(conventions), tuple(numeric_counts)

    def config(self, conventions: tuple[int, ...], *, preferred_decimal: str | None = None) -> dict[str, str]:
        observed = 0
        for convention in conventions:
            observed |= convention
        decimal = "," if self.delimiter == ";" else "."
        if observed == _DOT:
            decimal = "."
        elif observed == _COMMA:
            decimal = ","
        elif observed == 0 and preferred_decimal in (".", ","):
            decimal = preferred_decimal
        return {"delimiter": self.delimiter, "decimal": decimal}


def sample_csv_sources(path: Path, *, preferred_delimiter: str | None = None) -> list[CsvSourceSample]:
    """Rank bounded samples by structural evidence before inspecting numeric cells."""
    ranked: list[tuple[tuple[bool, int, int, bool], CsvSourceSample]] = []
    for delimiter in _DELIMITERS:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle, delimiter=delimiter)
                header = tuple(next(reader, ()))
                rows = [tuple(row) for row in islice(reader, _SAMPLE_ROWS)]
        except (OSError, UnicodeError, csv.Error):
            continue
        width = len(header)
        complete_rows = sum(len(row) == width for row in rows if row)
        rank = (width > 1, complete_rows, width, delimiter == preferred_delimiter)
        ranked.append((rank, CsvSourceSample(delimiter, header, rows)))
    if not ranked:
        raise ValueError("Unable to read the CSV file. Check that it is a UTF-8 CSV.")
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [sample for _rank, sample in ranked]


class CsvSourceNumbers:
    """Track separator evidence by physical column during a streaming read."""

    def __init__(self, conventions: tuple[int, ...], text_fields: frozenset[int]):
        self._conventions = list(conventions)
        self._text_fields = text_fields
        self._used_ambiguous_separator = [False] * len(conventions)
        self.ambiguous_text_fields: set[int] = set()

    def parse_column(self, index: int, values: list[str | None]) -> list[float | None]:
        text_field = index in self._text_fields
        conventions = self._conventions[index]
        used_ambiguous = self._used_ambiguous_separator[index]
        parsed: list[float | None] = []
        for value in values:
            dot, comma = _number_options(value)
            if dot is None:
                number = comma
                if comma is not None:
                    conventions |= _COMMA
            elif comma is None:
                number = dot
                conventions |= _DOT
            elif dot is comma or dot == comma:
                number = dot
            elif text_field:
                self.ambiguous_text_fields.add(index)
                number = None
            else:
                if conventions not in (_DOT, _COMMA):
                    raise ValueError(_AMBIGUOUS_NUMBER_MESSAGE)
                number = dot if conventions == _DOT else comma
                used_ambiguous = True
            if used_ambiguous and conventions == (_DOT | _COMMA):
                raise ValueError(_AMBIGUOUS_NUMBER_MESSAGE)
            parsed.append(number if number is not None and math.isfinite(number) else None)
        self._conventions[index] = conventions
        self._used_ambiguous_separator[index] = used_ambiguous
        return parsed

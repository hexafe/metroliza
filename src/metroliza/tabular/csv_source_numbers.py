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
_AMBIGUOUS_DELIMITER_MESSAGE = (
    "Ambiguous CSV delimiter. Remove commas embedded in headings or remove spaces around "
    "delimiters between columns. To keep the headings, quote every field on re-export "
    "or load an Excel worksheet."
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


def _has_extra_csv_values(row: list[str] | tuple[str, ...], width: int) -> bool:
    return len(row) > width and any(cell.strip() for cell in row[width:])


def validate_csv_width(row: list[str] | tuple[str, ...], width: int) -> None:
    if _has_extra_csv_values(row, width):
        raise ValueError(
            "A CSV row has more fields than the header. Check the delimiter and quote fields that contain it."
        )


def _combined_conventions(conventions: tuple[int, ...]) -> int:
    combined = 0
    for convention in conventions:
        combined |= convention
    return combined


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
        observed = _combined_conventions(conventions)
        decimal = "," if self.delimiter == ";" else "."
        if observed == _DOT:
            decimal = "."
        elif observed == _COMMA:
            decimal = ","
        elif observed == 0 and preferred_decimal in (".", ","):
            decimal = preferred_decimal
        return {"delimiter": self.delimiter, "decimal": decimal}


def _read_csv_source_sample(path: Path, delimiter: str, *, strict: bool) -> CsvSourceSample:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, strict=strict)
        header = tuple(next(reader, ()))
        rows = [tuple(row) for row in islice(reader, _SAMPLE_ROWS)]
    return CsvSourceSample(delimiter, header, rows)


def _has_fully_quoted_header(path: Path, sample: CsvSourceSample) -> bool:
    expected = sample.delimiter.join('"' + field.replace('"', '""') + '"' for field in sample.header)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return handle.read(len(expected)) == expected and handle.read(1) in ("", "\r", "\n")
    except (OSError, UnicodeError):
        return False


def sample_csv_sources(path: Path, *, preferred_delimiter: str | None = None) -> list[CsvSourceSample]:
    """Rank strict CSV samples, with malformed interpretations used only as a veto."""
    ranked: list[tuple[tuple[bool, int, int, bool], CsvSourceSample, bool]] = []
    for delimiter in _DELIMITERS:
        strict = True
        try:
            try:
                sample = _read_csv_source_sample(path, delimiter, strict=True)
            except csv.Error:
                strict = False
                sample = _read_csv_source_sample(path, delimiter, strict=False)
        except (OSError, UnicodeError, csv.Error):
            continue
        width = len(sample.header)
        complete_rows = sum(
            len(row) >= width and not _has_extra_csv_values(row, width) for row in sample.rows if row
        )
        rank = (width > 1, complete_rows, width, delimiter == preferred_delimiter)
        ranked.append((rank, sample, strict))
    if not ranked:
        raise ValueError("Unable to read the CSV file. Check that it is a UTF-8 CSV.")
    ranked.sort(key=lambda item: item[0], reverse=True)
    strict_samples = [(rank, sample) for rank, sample, strict in ranked if strict]
    if not strict_samples:
        raise ValueError(_AMBIGUOUS_DELIMITER_MESSAGE)
    best_rank, best = strict_samples[0]
    for rank, sample, strict in ranked:
        if sample is best:
            continue
        if sample.header != best.header:
            if strict and best_rank[0] and rank[:2] == best_rank[:2]:
                raise ValueError(_AMBIGUOUS_DELIMITER_MESSAGE)
            # Explicit quote boundaries in the actual header disambiguate a
            # falsely competitive shape produced by a permissive reader.
            if not strict and rank[:2] >= best_rank[:2] and not _has_fully_quoted_header(path, best):
                raise ValueError(_AMBIGUOUS_DELIMITER_MESSAGE)
        if _could_be_comma_decimal_column(best, sample):
            raise ValueError(_AMBIGUOUS_DELIMITER_MESSAGE)
    return [sample for _rank, sample in strict_samples]


def _could_be_comma_decimal_column(table: CsvSourceSample, scalar: CsvSourceSample) -> bool:
    if table.delimiter != "," or len(table.header) != 2 or len(scalar.header) != 1:
        return False
    first, second = table.header
    # A header like "Length, mm" can be a single label with an embedded comma.
    if (first == first.rstrip() and second == second.lstrip()) or scalar.header[0] != f"{first},{second}":
        return False
    if '"' in scalar.header[0] or any(_has_extra_csv_values(row, 1) for row in scalar.rows):
        return False
    values = [row[0].strip() for row in scalar.rows if row and row[0].strip()]
    return any("," in value for value in values) and all(
        any(number is not None for number in _number_options(value)) for value in values
    )


class CsvSourceNumbers:
    """Track separator evidence by physical column during a streaming read."""

    def __init__(self, conventions: tuple[int, ...], text_fields: frozenset[int]):
        self._conventions = list(conventions)
        self._text_fields = text_fields
        self._sample_conventions = _combined_conventions(conventions)
        self._file_conventions = self._sample_conventions
        self._used_file_convention = False
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
                if conventions == 0:
                    if self._file_conventions != self._sample_conventions:
                        raise ValueError(_AMBIGUOUS_NUMBER_MESSAGE)
                    self._used_file_convention = True
                convention = conventions or self._sample_conventions
                if convention not in (_DOT, _COMMA):
                    raise ValueError(_AMBIGUOUS_NUMBER_MESSAGE)
                number = dot if convention == _DOT else comma
                used_ambiguous = True
            if used_ambiguous and conventions == (_DOT | _COMMA):
                raise ValueError(_AMBIGUOUS_NUMBER_MESSAGE)
            parsed.append(number if number is not None and math.isfinite(number) else None)
        self._conventions[index] = conventions
        self._used_ambiguous_separator[index] = used_ambiguous
        if not text_field:
            self._file_conventions |= conventions
            if self._used_file_convention and self._file_conventions != self._sample_conventions:
                raise ValueError(_AMBIGUOUS_NUMBER_MESSAGE)
        return parsed

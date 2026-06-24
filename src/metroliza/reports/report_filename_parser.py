"""Filename parsing shared by report metadata extraction and parser probing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Sequence

from metroliza.reports.report_metadata_normalizers import (
    normalize_part_name,
    normalize_report_date,
)


_REFERENCE_RE = re.compile(
    r"^(?P<reference>([A-Z][A-Za-z0-9]{4,}\d{1,5}(?:_\d{3})?)|"
    r"(\d{2}[A-Za-z][._-]?\d{3}[._-]?\d{3})|(216\d{5}))"
)


@dataclass(frozen=True)
class ParsedReportFilename:
    reference: str | None
    report_date: str | None
    part_name: str | None
    sample_tail: str | None
    raw_date_candidate: str | None = None


def split_filename_tokens(file_name: str) -> tuple[str, ...]:
    name = Path(str(file_name or "")).name
    stem = re.sub(r"\.(?:pdf|csv|xlsx?|xls)$", "", name, flags=re.IGNORECASE)
    return tuple(token for token in stem.split("_") if token)


def _is_filename_date_candidate(value: str) -> bool:
    return re.fullmatch(r"\d{4}[._-]\d{1,2}[._-]\d{1,2}", value) is not None


def find_filename_date(tokens: Sequence[str]) -> tuple[int | None, int, str | None]:
    for index in range(len(tokens)):
        for token_count in (1, 2, 3):
            raw_tokens = tokens[index : index + token_count]
            if len(raw_tokens) != token_count:
                continue
            raw_date = ".".join(raw_tokens)
            if re.search(r"[A-Za-z]", raw_date):
                continue
            normalized_date = normalize_report_date(raw_date)
            if normalized_date:
                return index, token_count, normalized_date
    return None, 0, None


def find_filename_date_candidate(tokens: Sequence[str]) -> tuple[int | None, int, str | None]:
    for index in range(len(tokens)):
        for token_count in (1, 2, 3):
            raw_tokens = tokens[index : index + token_count]
            if len(raw_tokens) != token_count:
                continue
            raw_date = ".".join(raw_tokens)
            if _is_filename_date_candidate(raw_date):
                return index, token_count, raw_date
    return None, 0, None


def parse_report_filename(file_name: str) -> ParsedReportFilename:
    tokens = split_filename_tokens(file_name)
    date_index, date_token_count, date_value = find_filename_date(tokens)
    candidate_index, candidate_token_count, raw_date_candidate = find_filename_date_candidate(tokens)
    if date_index is None:
        date_index = candidate_index
        date_token_count = candidate_token_count
    sample_value = None

    prefix_tokens = tokens[:date_index] if date_index is not None else tokens
    prefix_text = "_".join(prefix_tokens)
    reference_match = _REFERENCE_RE.match(prefix_text)
    reference = reference_match.group("reference") if reference_match else None

    remainder = prefix_text[len(reference) :].lstrip("_") if reference else prefix_text
    part_tokens = [token for token in remainder.split("_") if token]

    if date_index is not None:
        tail_tokens = tokens[date_index + date_token_count :]
        if tail_tokens:
            sample_value = tail_tokens[-1]
    elif len(tokens) > 1:
        sample_value = tokens[-1]
        part_tokens = list(tokens[:-1])

    part_name = normalize_part_name("_".join(part_tokens), from_filename=True) if part_tokens else None
    return ParsedReportFilename(
        reference=reference,
        report_date=date_value,
        raw_date_candidate=raw_date_candidate,
        part_name=part_name,
        sample_tail=sample_value,
    )

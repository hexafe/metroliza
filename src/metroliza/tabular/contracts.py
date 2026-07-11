"""Immutable tabular grouping contracts and validation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class GroupingAssignment:
    """Logical grouping assignment keyed by canonical report identity."""

    group: str
    report_id: int | None = None
    reference: str | None = None
    fileloc: str | None = None
    filename: str | None = None
    date: str | None = None
    sample_number: str | None = None
    group_color: str | None = None


GroupingAssignments = tuple[GroupingAssignment, ...]


def validate_grouping_df(df: object | None) -> GroupingAssignments | None:
    """Backward-compatible alias for ``validate_grouping_assignments``."""

    return validate_grouping_assignments(df)


def validate_grouping_assignments(value: object | None) -> GroupingAssignments | None:
    """Validate optional grouping assignments without pandas runtime coupling."""

    if value is None:
        return None

    records = _grouping_records(value)
    assignments: list[GroupingAssignment] = []
    for record in records:
        group = _optional_text(_record_value(record, "GROUP", "group")) or "POPULATION"
        report_id = _optional_int(_record_value(record, "REPORT_ID", "report_id"))
        if report_id is None:
            raise ValueError("Grouping assignments must include REPORT_ID.")
        assignments.append(
            GroupingAssignment(
                group=group,
                report_id=report_id,
                reference=_optional_text(_record_value(record, "REFERENCE", "reference")),
                fileloc=_optional_text(_record_value(record, "FILELOC", "fileloc")),
                filename=_optional_text(_record_value(record, "FILENAME", "filename")),
                date=_optional_text(_record_value(record, "DATE", "date")),
                sample_number=_optional_text(
                    _record_value(record, "SAMPLE_NUMBER", "sample_number")
                ),
                group_color=_optional_text(
                    _record_value(record, "GROUP_COLOR", "group_color")
                ),
            )
        )
    return tuple(assignments)


def _grouping_records(value: object) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, GroupingAssignment):
        return (_assignment_record(value),)
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, tuple) and all(
        isinstance(item, GroupingAssignment) for item in value
    ):
        return tuple(_assignment_record(item) for item in value)
    if hasattr(value, "to_dict"):
        try:
            records = value.to_dict("records")
        except TypeError:
            records = value.to_dict()
        if isinstance(records, Mapping):
            records = [records]
        return _mapping_tuple(records)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return _mapping_tuple(value)
    raise ValueError("Grouping assignments must be mapping rows or GroupingAssignment records.")


def _assignment_record(assignment: GroupingAssignment) -> Mapping[str, Any]:
    return {
        "GROUP": assignment.group,
        "REPORT_ID": assignment.report_id,
        "REFERENCE": assignment.reference,
        "FILELOC": assignment.fileloc,
        "FILENAME": assignment.filename,
        "DATE": assignment.date,
        "SAMPLE_NUMBER": assignment.sample_number,
        "GROUP_COLOR": assignment.group_color,
    }


def _mapping_tuple(records: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(records, Iterable) or isinstance(records, (str, bytes)):
        raise ValueError("Grouping assignments must be an iterable of mapping rows.")
    normalized: list[Mapping[str, Any]] = []
    for row in records:
        if isinstance(row, GroupingAssignment):
            normalized.append(_assignment_record(row))
        elif isinstance(row, Mapping):
            normalized.append(row)
        else:
            raise ValueError("Grouping assignment rows must be mappings.")
    return tuple(normalized)


def _record_value(record: Mapping[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        if key in record:
            return record[key]
        lowered_value = lowered.get(key.lower())
        if lowered_value is not None:
            return lowered_value
    return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "<na>"}:
        return None
    return text


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).strip()
        if not text or text.lower() in {"nan", "nat", "none", "<na>"}:
            return None
        decimal_value = Decimal(text)
        if not decimal_value.is_finite() or decimal_value != decimal_value.to_integral_value():
            return None
        integer_value = int(decimal_value)
        if integer_value <= 0 or integer_value > 2**63 - 1:
            return None
        return integer_value
    except (InvalidOperation, TypeError, ValueError):
        return None


__all__ = [
    "GroupingAssignment",
    "GroupingAssignments",
    "validate_grouping_assignments",
    "validate_grouping_df",
]

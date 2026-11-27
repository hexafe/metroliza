"""Immutable report grouping assignments shared by feature packages."""

from __future__ import annotations

from dataclasses import dataclass


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

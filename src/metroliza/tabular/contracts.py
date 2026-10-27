"""Immutable tabular grouping contracts and validation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import sys
from typing import Any

from metroliza.analytics.row_table import RowMapping, RowTable


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
_PLAIN_GROUPING_VALUE_TYPES = (str, int, float, bool, Decimal, type(None))


@dataclass(frozen=True, slots=True)
class _ValidatedGroupingSnapshot:
    """Normalized values issued for one owner-managed grouping revision."""

    assignments: GroupingAssignments | None
    default_group_label: str
    revision: int
    source_id: int
    _owner: _GroupingSnapshotOwner

    def resolve(self, value: object) -> GroupingAssignments | None:
        owner = self._owner
        if (
            type(owner) is not _GroupingSnapshotOwner
            or owner.snapshot is not self
            or owner.revision != self.revision
            or owner.source_id != self.source_id
            or value is not self.assignments
        ):
            raise ValueError("Grouping snapshot is stale or does not match its source.")
        return self.assignments


class _GroupingSnapshotOwner:
    """Own a bounded handoff; retain no mutable grouping data or Qt objects."""

    def __init__(self) -> None:
        self.revision = 0
        self.source_id: int | None = None
        self.snapshot: _ValidatedGroupingSnapshot | None = None
        self.default_group_label = "POPULATION"

    def invalidate(self) -> None:
        self.revision += 1
        self.source_id = None
        self.snapshot = None

    def capture(self, value: object) -> tuple[GroupingAssignments | None, _ValidatedGroupingSnapshot | None]:
        from metroliza.exporting.export_grouping_utils import get_default_group_label

        self.invalidate()
        provenance = [_raw_grouping_source(value)]
        assignments = _validate_grouping_assignments(value, provenance)
        label = get_default_group_label(value)
        self.default_group_label = label
        if not provenance[0] or type(label) is not str:
            return assignments, None
        snapshot = _ValidatedGroupingSnapshot(
            assignments, label, self.revision, id(value), self
        )
        self.source_id = id(value)
        self.snapshot = snapshot
        return assignments, snapshot


def validate_grouping_df(df: object | None) -> GroupingAssignments | None:
    """Backward-compatible alias for ``validate_grouping_assignments``."""

    return validate_grouping_assignments(df)


def validate_grouping_assignments(value: object | None) -> GroupingAssignments | None:
    """Validate optional grouping assignments without pandas runtime coupling."""

    return _validate_grouping_assignments(value)


def _validate_grouping_assignments(
    value: object | None, provenance: list[bool] | None = None,
) -> GroupingAssignments | None:

    if value is None:
        return None

    records = _grouping_records(value, provenance)
    assignments: list[GroupingAssignment] = []
    for record in records:
        # Only exact dictionaries/string keys have callback-free lookup semantics.
        # Custom mappings and key subclasses retain the original lookup sequence.
        values = _plain_record_values(record)
        if provenance is not None and values is None:
            provenance[0] = False
        group = _optional_text(values[0] if values is not None else _record_value(record, "GROUP", "group")) or "POPULATION"
        report_id = _optional_int(values[1] if values is not None else _record_value(record, "REPORT_ID", "report_id"))
        if report_id is None:
            raise ValueError("Grouping assignments must include REPORT_ID.")
        assignments.append(
            GroupingAssignment(
                group=group,
                report_id=report_id,
                reference=_optional_text(values[2] if values is not None else _record_value(record, "REFERENCE", "reference")),
                fileloc=_optional_text(values[3] if values is not None else _record_value(record, "FILELOC", "fileloc")),
                filename=_optional_text(values[4] if values is not None else _record_value(record, "FILENAME", "filename")),
                date=_optional_text(values[5] if values is not None else _record_value(record, "DATE", "date")),
                sample_number=_optional_text(
                    values[6] if values is not None else _record_value(record, "SAMPLE_NUMBER", "sample_number")
                ),
                group_color=_optional_text(
                    values[7] if values is not None else _record_value(record, "GROUP_COLOR", "group_color")
                ),
            )
        )
    return tuple(assignments)


def _grouping_records(value: object, provenance: list[bool] | None = None) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, RowTable):
        storage = value.rows if provenance is not None and provenance[0] else None
        return _mapping_tuple(value.iter_rows(as_dict=True), provenance, storage)
    if isinstance(value, GroupingAssignment):
        return (_assignment_record(value, provenance),)
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, tuple) and all(
        isinstance(item, GroupingAssignment) for item in value
    ):
        return tuple(_assignment_record(item, provenance) for item in value)
    if hasattr(value, "to_dict"):
        try:
            records = value.to_dict("records")
        except TypeError:
            records = value.to_dict()
        if provenance is not None and provenance[0]:
            # The original pandas conversion already computed this verdict.
            # Duplicates emit a warning on every conversion and must fall back.
            provenance[0] = _raw_grouping_source(value) and _grouping_columns_unique(value)
        if isinstance(records, Mapping):
            records = [records]
        return _mapping_tuple(records, provenance)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return _mapping_tuple(value, provenance)
    raise ValueError("Grouping assignments must be mapping rows or GroupingAssignment records.")


def _assignment_record(assignment: GroupingAssignment, provenance: list[bool] | None = None) -> Mapping[str, Any]:
    if provenance is not None and type(assignment) is not GroupingAssignment:
        provenance[0] = False
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


def _mapping_tuple(records: object, provenance: list[bool] | None = None, storage: tuple[tuple[Any, ...], ...] | None = None) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(records, Iterable) or isinstance(records, (str, bytes)):
        raise ValueError("Grouping assignments must be an iterable of mapping rows.")
    normalized: list[Mapping[str, Any]] = []
    for index, row in enumerate(records):
        if provenance is not None and (
            type(row) not in (dict, RowMapping, GroupingAssignment)
            or (storage is not None and type(storage[index]) is not tuple)
        ):
            provenance[0] = False
        if isinstance(row, GroupingAssignment):
            normalized.append(_assignment_record(row, provenance))
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


def _plain_record_values(record: Mapping[str, Any]) -> tuple[Any, ...] | None:
    if (
        (type(record) is not dict and not (type(record) is RowMapping and _plain_metadata(vars(record), set())))
        or any(type(key) is not str for key in record)
        or any(type(value) not in _PLAIN_GROUPING_VALUE_TYPES
               for value in record.values())
    ):
        return None
    lowered = {key.lower(): value for key, value in record.items()}
    # The first alias's fallback precedes an exact match on the second alias.
    # In particular, exact uppercase None must never fall through.
    values = []
    for canonical in (
        "GROUP", "REPORT_ID", "REFERENCE", "FILELOC", "FILENAME", "DATE",
        "SAMPLE_NUMBER", "GROUP_COLOR",
    ):
        for key in (canonical, canonical.lower()):
            if key in record:
                values.append(record[key])
                break
            lowered_value = lowered.get(key.lower())
            if lowered_value is not None:
                values.append(lowered_value)
                break
        else:
            values.append(None)
    return tuple(values)


def _loaded_type(value: object, module: str, name: str) -> bool:
    loaded = sys.modules.get(module)
    return loaded is not None and type(value) is vars(loaded).get(name)


def _plain_metadata(state: Any, allowed: set[str] | None = None) -> bool:
    return (type(state) is dict and all(type(key) is str for key in state)
            and (allowed is None or state.keys() <= allowed))


def _grouping_columns_unique(value: object) -> bool:
    # Rechecked after conversion: even its axis/cache must still be native.
    cache = vars(vars(value)["_mgr"].axes[0]).get("_cache", {})
    return _plain_metadata(cache) and cache.get("is_unique") is True


def _raw_grouping_source(value: object) -> bool:
    """Inspect known source metadata only; consumed cells are checked inline."""
    if value is None or type(value) in (dict, list, tuple):
        return True
    if type(value) not in (RowTable, GroupingAssignment) and not _loaded_type(value, "pandas.core.frame", "DataFrame"):
        return False
    state = vars(value)
    if not _plain_metadata(state):
        return False
    attrs = state.get("attrs", state.get("_attrs", {}))
    if (not _plain_metadata(attrs) or len(attrs) > 1
        or any(type(key) is not str or type(item) not in _PLAIN_GROUPING_VALUE_TYPES for key, item in attrs.items())
        or type(state.get("default_group_label")) not in _PLAIN_GROUPING_VALUE_TYPES):
        return False
    if type(value) is GroupingAssignment:
        return True
    if type(value) is RowTable:
        return (state.keys() <= {"rows", "columns", "attrs", "default_group_label"}
                and type(value.rows) is tuple and type(value.columns) is tuple
                and all(type(column) is str for column in value.columns))
    if not state.keys() <= {"_mgr", "_attrs", "_flags", "_item_cache", "_is_copy", "default_group_label"}:
        return False
    manager: Any = state.get("_mgr")
    if not _loaded_type(manager, "pandas.core.internals.managers", "BlockManager"):
        return False
    return _raw_pandas_storage(manager)


def _raw_pandas_storage(manager: Any) -> bool:
    if not _plain_metadata(vars(manager), {"_known_consolidated", "_is_consolidated"}):
        return False
    axes, blocks = manager.axes, manager.blocks
    return (type(axes) is list and type(blocks) is tuple
            and all(_raw_grouping_axis(axis) for axis in axes)
            and all(_raw_grouping_block(block) for block in blocks))


def _raw_grouping_axis(axis: Any) -> bool:
    if not (_loaded_type(axis, "pandas.core.indexes.base", "Index") or _loaded_type(axis, "pandas.core.indexes.range", "RangeIndex")):
        return False
    state = vars(axis)
    if not _plain_metadata(state, {"_data", "_range", "_name", "_cache", "_id", "_references"}):
        return False
    return (_plain_metadata(state.get("_cache", {})) and ("_data" not in state
            or _loaded_type(state["_data"], "numpy", "ndarray")
            or _raw_grouping_strings(state["_data"])))


def _raw_grouping_strings(values: Any) -> bool:
    return (_loaded_type(values, "pandas.core.arrays.string_", "StringArray")
            and _plain_metadata(vars(values), set()))


def _raw_grouping_block(block: Any) -> bool:
    if not (_loaded_type(block, "pandas.core.internals.blocks", "NumpyBlock")
            or _loaded_type(block, "pandas.core.internals.blocks", "ExtensionBlock")):
        return False
    state = vars(block)
    if not _plain_metadata(state, {"_cache"}) or not _plain_metadata(state.get("_cache", {})):
        return False
    values = block.values
    if _loaded_type(block, "pandas.core.internals.blocks", "NumpyBlock"):
        return _loaded_type(values, "numpy", "ndarray") and values.dtype.kind in "iub"
    # Native StringArray storage excludes object-cell coercion callbacks.
    return _raw_grouping_strings(values)


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

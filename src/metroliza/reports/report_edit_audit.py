"""Bounded receipt samples for an owned report edit transaction."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Literal

from metroliza.reports.db import quote_identifier
from metroliza.reports.report_repository import (
    MEASUREMENT_EDITABLE_FIELDS,
    REPORT_METADATA_EDITABLE_FIELDS,
)


AUDIT_SAMPLE_LIMIT = 12
_AUDIT_VALUE_BYTES = 512
_RETAINED_RECEIPTS = 100
_RECEIPT_COLUMNS = (
    ("receipt_id", "INTEGER", 0, 1),
    ("schema_version", "INTEGER", 1, 0),
    ("recorded_at_utc", "TEXT", 1, 0),
    ("payload_json", "TEXT", 1, 0),
)


class OmittedEditValue(Enum):
    PREVIEW_LIMIT = "preview_limit"
    UNAVAILABLE = "unavailable"


EditValue = str | int | float | None | OmittedEditValue


@dataclass(frozen=True, slots=True)
class RecordEditSample:
    entity: Literal["report", "measurement"]
    record_id: int
    field_name: str
    before: EditValue = field(repr=False)
    after: EditValue = field(repr=False)


@dataclass(frozen=True, slots=True)
class NormalizationEditSample:
    field_name: str
    matched_rows: int
    requested_old: EditValue = field(repr=False)
    requested_new: EditValue = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class ReportEditReceipt:
    """Local samples of requested fields, excluding derived JSON and summary fields.

    Normalization counts are matched rows per operation. One row may contribute
    to more than one operation. The unavailable count covers sampled fields with
    missing or unverified readback. Truncation covers the sample cap separately.
    Keep values out of logs and diagnostics.
    """

    storage_flavor: str
    normalization_operation_count: int
    normalization_samples: tuple[NormalizationEditSample, ...]
    record_samples: tuple[RecordEditSample, ...]
    unavailable_record_sample_count: int
    samples_truncated: bool


@dataclass(frozen=True, slots=True)
class _RecordTarget:
    entity: Literal["report", "measurement"]
    record_id: int
    field_name: str
    table: str
    key: str
    column: str


def _encode_unavailable_value(value):
    if isinstance(value, OmittedEditValue):
        return {"omitted": value.value}
    raise TypeError(f"Unsupported audit value type: {type(value).__name__}")


def persist_confirmed_receipt(cursor, receipt: ReportEditReceipt) -> None:
    """Keep the bounded record in the edited database under the caller's transaction."""
    payload = json.dumps(asdict(receipt), default=_encode_unavailable_value, ensure_ascii=False, allow_nan=False)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS main.metroliza_report_edit_receipts (
            receipt_id INTEGER PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            recorded_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            payload_json TEXT NOT NULL
        )
        """
    )
    columns = cursor.execute("PRAGMA main.table_info(metroliza_report_edit_receipts)")
    if tuple((name, kind, required, key) for _, name, kind, required, _, key in columns) != _RECEIPT_COLUMNS:
        raise sqlite3.DatabaseError("The local Metroliza edit receipt table has an incompatible layout.")
    cursor.execute(
        "INSERT INTO main.metroliza_report_edit_receipts (schema_version, payload_json) VALUES (1, ?)",
        (payload,),
    )
    cursor.execute(
        """
        DELETE FROM main.metroliza_report_edit_receipts WHERE receipt_id < (
            SELECT receipt_id FROM main.metroliza_report_edit_receipts
            ORDER BY receipt_id DESC LIMIT 1 OFFSET ?
        )
        """,
        (_RETAINED_RECEIPTS - 1,),
    )


def _bounded_requested_text(value: str) -> EditValue:
    if len(value) > _AUDIT_VALUE_BYTES or len(value.encode("utf-8")) > _AUDIT_VALUE_BYTES:
        return OmittedEditValue.PREVIEW_LIMIT
    return value


def normalization_sample(field_name, params, matched_rows) -> NormalizationEditSample:
    new, old = params
    return NormalizationEditSample(
        field_name, matched_rows, _bounded_requested_text(old), _bounded_requested_text(new),
    )


def record_sample_targets(flavor, reports, measurements, remaining, legacy_report, legacy_measurement):
    targets = []
    seen = set()
    for entity, updates, table, key, columns in (
        ("report", reports, "REPORTS" if flavor == "legacy" else "report_metadata",
         "ID" if flavor == "legacy" else "report_id",
         legacy_report if flavor == "legacy" else {name: name for name in REPORT_METADATA_EDITABLE_FIELDS}),
        ("measurement", measurements, "MEASUREMENTS" if flavor == "legacy" else "report_measurements",
         "ID" if flavor == "legacy" else "id",
         legacy_measurement if flavor == "legacy" else {
             name: name for name in MEASUREMENT_EDITABLE_FIELDS if name != "raw_measurement_json"
         }),
    ):
        for record_id, fields in updates:
            for field_name in fields:
                column = columns.get(field_name)
                identity = entity, record_id, field_name
                if column is None or identity in seen:
                    continue
                if len(targets) >= remaining:
                    return targets, True
                seen.add(identity)
                targets.append(_RecordTarget(entity, record_id, field_name, table, key, column))
    return targets, False


def unobservable_legacy_tables(cursor, targets):
    """Exclude legacy keys that could require a table scan for observation."""
    rowid_key = """
        SELECT EXISTS (
            SELECT 1 FROM pragma_table_info(?, 'main') WHERE name = 'ID' COLLATE NOCASE
                AND type = 'INTEGER' COLLATE NOCASE AND pk = 1
        ) AND NOT EXISTS (
            SELECT 1 FROM pragma_index_list(?, 'main') WHERE origin = 'pk'
        )
    """
    unobservable = set()
    for table in {target.table for target in targets}:
        try:
            # A separate PK index also identifies composite, WITHOUT ROWID and DESC keys.
            if cursor.execute(rowid_key, (table, table)).fetchone() != (1,):
                unobservable.add(table)
        except sqlite3.OperationalError:
            unobservable.add(table)
    return frozenset(unobservable)


def read_sample_values(cursor, targets, unavailable_tables):
    return [
        OmittedEditValue.UNAVAILABLE if target.table in unavailable_tables else _read_record_value(cursor, target)
        for target in targets
    ]


def _read_record_value(cursor, target):
    # Identifiers come only from the fixed table/key and editable-field allowlists.
    column = quote_identifier(target.column)
    table = quote_identifier(target.table)
    key = quote_identifier(target.key)
    query = f"""
        WITH edited(value) AS (
            SELECT source.{column} FROM {table} AS source WHERE source.{key} = ? LIMIT 2
        ), bounded AS (
            SELECT value, CASE
                WHEN typeof(value) = 'blob' THEN 1
                WHEN typeof(value) = 'text' AND length(CAST(value AS BLOB)) > ? THEN 1
                ELSE 0
            END AS omitted
            FROM edited
        )
        SELECT omitted, CASE WHEN omitted THEN NULL ELSE value END FROM bounded
    """
    try:
        rows = cursor.execute(query, (target.record_id, _AUDIT_VALUE_BYTES)).fetchmany(2)
    except (sqlite3.OperationalError, OverflowError):
        # Legacy compatibility may lack optional columns. Observation is not a write prerequisite.
        return OmittedEditValue.UNAVAILABLE
    if len(rows) != 1:
        return OmittedEditValue.UNAVAILABLE
    omitted, value = rows[0]
    if isinstance(value, float) and not math.isfinite(value):
        return OmittedEditValue.UNAVAILABLE
    return OmittedEditValue.PREVIEW_LIMIT if omitted else value


def sampled_record_edits(cursor, targets, before, unavailable_tables):
    after = read_sample_values(cursor, targets, unavailable_tables)
    samples = tuple(
        RecordEditSample(target.entity, target.record_id, target.field_name, old, new)
        for target, old, new in zip(targets, before, after)
    )
    unavailable_count = sum(
        old is OmittedEditValue.UNAVAILABLE or new is OmittedEditValue.UNAVAILABLE
        for old, new in zip(before, after)
    )
    return samples, unavailable_count

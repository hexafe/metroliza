"""Read-only review context for an imported report in Modify database."""

from dataclasses import dataclass
import json
import sqlite3

from metroliza.reports.db import quote_identifier, sqlite_readonly_connection_scope
from metroliza.reports.report_metadata_review import OCR_DEFERRED, OCR_REJECTED, REVIEW_FIELDS


DETAIL_ROW_LIMIT = 25
_METADATA_JSON_BYTE_LIMIT = 256 * 1024
_DECISION_TEXT_LIMIT = 120
_REPORT_FIELDS = (
    "absolute_path", "file_name", "sha256", "parser_id", "template_family",
    "template_variant", "parse_status", "measurement_count", "nok_count",
)


def report_context_projections(metadata_columns: set[str], warning_columns: set[str]) -> dict[str, str]:
    """Optional projections keyed by field, for the report-overview alias ``report``."""
    projections = {}
    if {"report_id", "metadata_profile_id"} <= metadata_columns:
        if "metadata_profile_version" in metadata_columns:
            projections["metadata_profile"] = (
                "(SELECT metadata_profile_id || COALESCE(' / ' || NULLIF(metadata_profile_version, ''), '') "
                "FROM report_metadata WHERE report_id = report.report_id)"
            )
        else:
            projections["metadata_profile"] = (
                "(SELECT metadata_profile_id FROM report_metadata WHERE report_id = report.report_id)"
            )
    if {"report_id", "severity"} <= warning_columns:
        projections["review_warning_count"] = (
            "(SELECT COUNT(*) FROM report_metadata_warnings "
            "WHERE report_id = report.report_id AND severity IN ('warning', 'error'))"
        )
    return projections


@dataclass(frozen=True)
class StoredOcrDecision:
    field_name: str
    decision: str
    value: str
    source_type: str
    region_name: str | None
    page_number: int | None
    confidence: float | None


@dataclass(frozen=True)
class StoredReportContext:
    report: dict[str, str | int | None]
    warnings: tuple[tuple[str, str, str | None, str], ...]
    selected_fields: tuple[tuple[str, str, str | None, str | None], ...]
    ocr_decisions: tuple[StoredOcrDecision, ...] = ()


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1].lower() for row in connection.execute(f"PRAGMA table_info({quote_identifier(table)})")}


def load_stored_report_context(database: str, report_id: int) -> StoredReportContext | None:
    """Read one report and capped review evidence in a consistent, read-only snapshot."""
    with sqlite_readonly_connection_scope(database, timeout_s=0.2) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        available = _table_columns(connection, "vw_report_overview")
        if "report_id" not in available:
            return None
        metadata = _table_columns(connection, "report_metadata")
        warnings = _table_columns(connection, "report_metadata_warnings")
        projections = report_context_projections(metadata, warnings)
        if {"id", "parser_version"} <= _table_columns(connection, "parsed_reports"):
            projections["parser_version"] = "(SELECT parser_version FROM parsed_reports WHERE id = report.report_id)"
        fields = [quote_identifier(field) for field in ("report_id", *_REPORT_FIELDS) if field in available]
        fields.extend(f"{expression} AS {quote_identifier(field)}" for field, expression in projections.items())
        report = connection.execute(
            f"SELECT {', '.join(fields)} FROM vw_report_overview AS report WHERE report.report_id = ?",
            (report_id,),
        ).fetchone()
        if report is None:
            return None
        return StoredReportContext(
            dict(report), _review_warnings(connection, report_id, warnings), _selected_fields(connection, report_id),
            _stored_ocr_decisions(connection, report_id, metadata),
        )


def _review_warnings(connection: sqlite3.Connection, report_id: int, available: set[str]) -> tuple:
    if not {"id", "report_id", "severity", "code", "field_name", "message"} <= available:
        return ()
    rows = connection.execute(
        """SELECT severity, substr(code, 1, 121), substr(field_name, 1, 121), substr(message, 1, 601)
            FROM report_metadata_warnings WHERE report_id = ? AND severity IN ('warning', 'error')
            ORDER BY id LIMIT ?""",
        (report_id, DETAIL_ROW_LIMIT),
    )
    return tuple(tuple(row) for row in rows)


def _selected_fields(connection: sqlite3.Connection, report_id: int) -> tuple:
    required = {"report_id", "field_name", "normalized_value", "source_type", "source_detail", "is_selected"}
    if not required <= _table_columns(connection, "report_metadata_candidates"):
        return ()
    rows = connection.execute(
        """SELECT substr(field_name, 1, 121), substr(source_type, 1, 121),
                  substr(source_detail, 1, 121), substr(normalized_value, 1, 121)
            FROM report_metadata_candidates WHERE report_id = ? AND is_selected = 1
            ORDER BY field_name LIMIT ?""",
        (report_id, DETAIL_ROW_LIMIT + 1),
    )
    return tuple(tuple(row) for row in rows)


def _stored_ocr_decisions(
    connection: sqlite3.Connection, report_id: int, columns: set[str],
) -> tuple[StoredOcrDecision, ...]:
    if not {"report_id", "metadata_json"} <= columns:
        return ()
    # Bound the transferred bytes before parsing and let json.loads handle invalid encodings.
    row = connection.execute(
        """SELECT substr(CAST(metadata_json AS BLOB), 1, ?) FROM report_metadata
           WHERE report_id = ? AND typeof(metadata_json) = 'text' LIMIT 1""",
        (_METADATA_JSON_BYTE_LIMIT + 1, report_id),
    ).fetchone()
    if row is None or not row[0] or len(row[0]) > _METADATA_JSON_BYTE_LIMIT:
        return ()
    try:
        payload = json.loads(row[0])
    except (ValueError, RecursionError):
        return ()
    review = payload.get("metadata_review") if isinstance(payload, dict) else None
    if not isinstance(review, dict) or type(review.get("version")) is not int or review["version"] != 1:
        return ()
    records = review.get("ocr_decisions")
    if not isinstance(records, dict):
        return ()
    return tuple(
        decision for name in REVIEW_FIELDS
        if (decision := _stored_ocr_decision(name, records.get(name))) is not None
    )


def _stored_ocr_decision(field_name: str, record) -> StoredOcrDecision | None:
    if not isinstance(record, dict) or record.get("decision") not in (OCR_DEFERRED, OCR_REJECTED):
        return None
    value = _bounded_decision_text(record.get("value"))
    source_type = _bounded_decision_text(record.get("source_type"))
    if value is None or source_type is None:
        return None
    page_number = record.get("page_number")
    confidence = record.get("confidence")
    return StoredOcrDecision(
        field_name=field_name, decision=record["decision"], value=value, source_type=source_type,
        region_name=_bounded_decision_text(record.get("region_name")),
        page_number=page_number if type(page_number) is int and 1 <= page_number <= 2**31 - 1 else None,
        confidence=float(confidence) if type(confidence) in (int, float) and 0 <= confidence <= 1 else None,
    )


def _bounded_decision_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    prefix = value[:_DECISION_TEXT_LIMIT]
    text = "".join(character if character.isprintable() else " " for character in prefix).strip()
    if not text:
        return None
    return text + ("…" if len(value) > _DECISION_TEXT_LIMIT else "")

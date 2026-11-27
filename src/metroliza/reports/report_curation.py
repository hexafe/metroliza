"""Read-only review context for an imported report in Modify database."""

from dataclasses import dataclass, field, replace
import hashlib
import json
import sqlite3

from metroliza.reports.db import SQLiteFileBinding, quote_identifier, sqlite_readonly_connection_scope
from metroliza.reports.report_metadata_models import USER_SOURCE_TYPE
from metroliza.reports.report_metadata_review import OCR_ACCEPTED, OCR_DEFERRED, OCR_REJECTED, REVIEW_FIELDS


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


@dataclass(frozen=True, repr=False)
class StoredOcrApproval:
    database: SQLiteFileBinding
    report_id: int
    field_name: str
    candidate_id: int
    evidence_digest: str
    normalized_value: str
    source_type: str


@dataclass(frozen=True)
class StoredOcrDecision:
    field_name: str
    decision: str
    value: str
    source_type: str
    region_name: str | None
    page_number: int | None
    confidence: float | None
    approval: StoredOcrApproval | None = field(default=None, repr=False)


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
    binding = SQLiteFileBinding.capture(database)
    with sqlite_readonly_connection_scope(database, timeout_s=0.2) as connection:
        binding.require(database)
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
        context = StoredReportContext(
            dict(report), _review_warnings(connection, report_id, warnings), _selected_fields(connection, report_id),
            _stored_ocr_decisions(connection, report_id, metadata, binding),
        )
        binding.require(database)
        return context


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
    connection: sqlite3.Connection, report_id: int, columns: set[str], binding: SQLiteFileBinding,
) -> tuple[StoredOcrDecision, ...]:
    if not {"report_id", "metadata_json"} <= columns:
        return ()
    receipt = read_stored_ocr_receipt(connection, report_id)
    if receipt is None:
        return ()
    _payload, records = receipt
    decisions = []
    for name in REVIEW_FIELDS:
        record = records.get(name)
        decision = _stored_ocr_decision(name, record)
        if decision is not None:
            if decision.decision == OCR_DEFERRED:
                try:
                    approval = read_deferred_ocr_approval(connection, binding, report_id, name, record)
                except sqlite3.OperationalError:
                    # Older layouts still expose their historical receipt as read-only context.
                    approval = None
                decision = replace(decision, approval=approval)
            decisions.append(decision)
    return tuple(decisions)


def read_stored_ocr_receipt(connection, report_id: int) -> tuple[dict, dict] | None:
    # Bound the transferred bytes before parsing and let json.loads handle invalid encodings.
    row = connection.execute(
        """SELECT substr(CAST(metadata_json AS BLOB), 1, ?) FROM report_metadata
           WHERE report_id = ? AND typeof(metadata_json) = 'text' LIMIT 1""",
        (_METADATA_JSON_BYTE_LIMIT + 1, report_id),
    ).fetchone()
    if row is None or not row[0] or len(row[0]) > _METADATA_JSON_BYTE_LIMIT:
        return None
    try:
        payload = json.loads(row[0])
    except (ValueError, RecursionError):
        return None
    review = payload.get("metadata_review") if isinstance(payload, dict) else None
    if not isinstance(review, dict) or type(review.get("version")) is not int or review["version"] != 1:
        return None
    records = review.get("ocr_decisions")
    return (payload, records) if isinstance(records, dict) else None


def _deferred_evidence(record) -> tuple | None:
    if not isinstance(record, dict) or record.get("decision") != OCR_DEFERRED:
        return None
    if not {"value", "source_type", "rule_id", "page_number", "region_name", "confidence"} <= record.keys():
        return None
    value, source, rule = (record.get(name) for name in ("value", "source_type", "rule_id"))
    if not all(isinstance(text, str) and text.strip() and text.isprintable() for text in (value, source, rule)):
        return None
    if source in ("filename_candidate", USER_SOURCE_TYPE):
        return None
    page, region, confidence = (record.get(name) for name in ("page_number", "region_name", "confidence"))
    if page is not None and (type(page) is not int or not 1 <= page <= 2**31 - 1):
        return None
    if region is not None and not isinstance(region, str):
        return None
    if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
        return None
    return value, source, page, region, rule, confidence


def read_deferred_ocr_approval(connection, binding, report_id, field_name, record) -> StoredOcrApproval | None:
    """Bind a deferred receipt to the one matching original candidate in this snapshot."""
    if binding.identity is None or field_name not in REVIEW_FIELDS or (evidence := _deferred_evidence(record)) is None:
        return None
    rows = connection.execute(
        """SELECT id, is_selected FROM report_metadata_candidates
           WHERE report_id = ? AND field_name = ? AND normalized_value = ? AND source_type = ?
             AND page_number IS ? AND region_name IS ? AND rule_id = ? AND confidence = ? LIMIT 2""",
        (report_id, field_name, *evidence),
    ).fetchall()
    if len(rows) != 1 or rows[0][1] != 0:
        return None
    candidate = connection.execute(
        """SELECT id, raw_value, normalized_value, source_type, source_detail, page_number, region_name,
                  label_text, rule_id, confidence, evidence_text, created_at, is_selected
           FROM report_metadata_candidates WHERE id = ?
             AND COALESCE(length(CAST(raw_value AS BLOB)), 0) + COALESCE(length(CAST(source_detail AS BLOB)), 0)
                 + COALESCE(length(CAST(label_text AS BLOB)), 0) + COALESCE(length(CAST(evidence_text AS BLOB)), 0)
                 + length(CAST(created_at AS BLOB)) <= ?""",
        (rows[0][0], _METADATA_JSON_BYTE_LIMIT),
    ).fetchone()
    if candidate is None:
        return None
    report = connection.execute(
        """SELECT pr.source_file_id, sf.sha256, pr.parser_id, pr.parser_version, pr.created_at,
                  pr.updated_at, pr.identity_hash, rm.*
           FROM parsed_reports pr JOIN source_files sf ON pr.source_file_id = sf.id
           JOIN report_metadata rm ON pr.id = rm.report_id WHERE pr.id = ?""",
        (report_id,),
    ).fetchone()
    if report is None:
        return None
    snapshot = repr((tuple(report), tuple(candidate))).encode("utf-8", errors="backslashreplace")
    return StoredOcrApproval(binding, report_id, field_name, candidate[0], hashlib.sha256(snapshot).hexdigest(),
                             evidence[0], evidence[1])


def _stored_ocr_decision(field_name: str, record) -> StoredOcrDecision | None:
    if not isinstance(record, dict) or record.get("decision") not in (OCR_ACCEPTED, OCR_DEFERRED, OCR_REJECTED):
        return None
    if record["decision"] == OCR_ACCEPTED:
        candidate_id = record.get("candidate_id")
        accepted_at = _bounded_decision_text(record.get("accepted_at"))
        if type(candidate_id) is not int or candidate_id <= 0 or accepted_at is None:
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

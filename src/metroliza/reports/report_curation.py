"""Read-only review context for an imported report in Modify database."""

from dataclasses import dataclass
import sqlite3

from metroliza.reports.db import quote_identifier, sqlite_readonly_connection_scope


DETAIL_ROW_LIMIT = 25
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
class StoredReportContext:
    report: dict[str, str | int | None]
    warnings: tuple[tuple[str, str, str | None, str], ...]
    selected_fields: tuple[tuple[str, str, str | None, str | None], ...]


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

"""Join cached industrial records to parsed Metroliza reports."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from metroliza.reports.db import connect_sqlite
from metroliza.industrial.industrial_data_repository import utc_timestamp
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.reports.report_schema import ensure_report_schema


REPORT_FIELD_SQL = {
    "reference": "rm.reference",
    "part_name": "rm.part_name",
    "revision": "rm.revision",
    "sample_number": "rm.sample_number",
    "operator_name": "rm.operator_name",
    "report_date": "rm.report_date",
    "report_time": "rm.report_time",
}

INDUSTRIAL_FIELD_SQL = {
    "reference": "ir.reference",
    "part_number": "ir.part_number",
    "part_name": "ir.part_name",
    "revision": "ir.revision",
    "serial": "ir.serial",
    "batch_lot": "ir.batch_lot",
    "work_order": "ir.work_order",
    "station": "ir.station",
    "line": "ir.line",
    "operator_name": "ir.operator_name",
    "process_status": "ir.process_status",
    "process_timestamp": "ir.process_timestamp",
}

JOIN_MATCH_MODES = {"exact", "time_window"}
MANUAL_LINK_RULE_KEY = "manual_user_link"


@dataclass(frozen=True)
class IndustrialJoinRuleSpec:
    """Configuration for one report-to-industrial-record join pass."""

    rule_key: str = "reference_exact"
    rule_name: str = "Reference exact"
    report_field: str = "reference"
    industrial_field: str = "reference"
    match_mode: str = "exact"
    time_window_seconds: int | None = None
    priority: int = 100
    is_enabled: bool = True


@dataclass(frozen=True)
class IndustrialJoinSummary:
    """Result metrics for a materialized industrial join pass."""

    rule_id: int
    reports_seen: int
    records_seen: int
    candidates_inserted: int
    accepted_links: int
    ambiguous_reports: int
    unmatched_reports: int


def validate_join_rule(rule: IndustrialJoinRuleSpec) -> IndustrialJoinRuleSpec:
    """Validate allowed fields and join mode for SQL-safe materialization."""

    if rule.report_field not in REPORT_FIELD_SQL:
        raise ValueError(f"Unsupported report join field: {rule.report_field}")
    if rule.industrial_field not in INDUSTRIAL_FIELD_SQL:
        raise ValueError(f"Unsupported industrial join field: {rule.industrial_field}")
    if rule.match_mode not in JOIN_MATCH_MODES:
        raise ValueError(f"Unsupported industrial join mode: {rule.match_mode}")
    if rule.match_mode == "time_window":
        if rule.time_window_seconds is None or rule.time_window_seconds <= 0:
            raise ValueError("time_window joins require a positive time_window_seconds value")
    return rule


def _report_timestamp_sql() -> str:
    return "rm.report_date || 'T' || COALESCE(NULLIF(rm.report_time, ''), '00:00:00')"


def _time_window_clause(rule: IndustrialJoinRuleSpec) -> tuple[str, tuple[int, ...]]:
    if rule.match_mode != "time_window":
        return "", ()
    report_timestamp_sql = _report_timestamp_sql()
    return (
        f"""
          AND ir.process_timestamp IS NOT NULL
          AND rm.report_date IS NOT NULL
          AND strftime('%s', ir.process_timestamp) IS NOT NULL
          AND strftime('%s', {report_timestamp_sql}) IS NOT NULL
          AND ABS(
                CAST(strftime('%s', ir.process_timestamp) AS INTEGER)
                - CAST(strftime('%s', {report_timestamp_sql}) AS INTEGER)
              ) <= ?
        """,
        (int(rule.time_window_seconds or 0),),
    )


def ensure_industrial_join_rule(
    database: str,
    rule: IndustrialJoinRuleSpec,
    *,
    connection: sqlite3.Connection | None = None,
) -> int:
    """Insert or update one join rule and return its local id."""

    rule = validate_join_rule(rule)
    ensure_industrial_data_schema(database, connection=connection)
    now = utc_timestamp()
    owns_connection = connection is None
    conn = connection or connect_sqlite(database)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO industrial_join_rules (
                    rule_key,
                    rule_name,
                    report_field,
                    industrial_field,
                    match_mode,
                    time_window_seconds,
                    priority,
                    is_enabled,
                    settings_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(rule_key) DO UPDATE SET
                    rule_name = excluded.rule_name,
                    report_field = excluded.report_field,
                    industrial_field = excluded.industrial_field,
                    match_mode = excluded.match_mode,
                    time_window_seconds = excluded.time_window_seconds,
                    priority = excluded.priority,
                    is_enabled = excluded.is_enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    rule.rule_key,
                    rule.rule_name,
                    rule.report_field,
                    rule.industrial_field,
                    rule.match_mode,
                    rule.time_window_seconds,
                    int(rule.priority),
                    int(rule.is_enabled),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM industrial_join_rules WHERE rule_key = ?",
                (rule.rule_key,),
            ).fetchone()
            if row is None:
                raise ValueError(f"join rule was not persisted: {rule.rule_key}")
            return int(row[0])
    finally:
        if owns_connection:
            conn.close()


def ensure_manual_industrial_join_rule(
    database: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> int:
    """Ensure the high-priority user-managed link rule exists."""

    return ensure_industrial_join_rule(
        database,
        IndustrialJoinRuleSpec(
            rule_key=MANUAL_LINK_RULE_KEY,
            rule_name="Manual user link",
            report_field="reference",
            industrial_field="reference",
            match_mode="exact",
            priority=0,
            is_enabled=True,
        ),
        connection=connection,
    )


def set_manual_industrial_report_link(
    database: str,
    *,
    report_id: int,
    industrial_record_id: int,
    connection: sqlite3.Connection | None = None,
) -> int:
    """Accept one explicit user-managed link between a report and a cached production row."""

    ensure_industrial_data_schema(database, connection=connection)
    owns_connection = connection is None
    conn = connection or connect_sqlite(database)
    try:
        rule_id = ensure_manual_industrial_join_rule(database, connection=conn)
        now = utc_timestamp()
        with conn:
            report_exists = conn.execute(
                "SELECT 1 FROM parsed_reports WHERE id = ?",
                (int(report_id),),
            ).fetchone()
            if report_exists is None:
                raise ValueError(f"Metroliza report not found: {report_id}")
            record_exists = conn.execute(
                "SELECT 1 FROM industrial_records WHERE id = ?",
                (int(industrial_record_id),),
            ).fetchone()
            if record_exists is None:
                raise ValueError(f"Cached production row not found: {industrial_record_id}")
            conn.execute(
                """
                DELETE FROM industrial_link_candidates
                WHERE report_id = ?
                  AND measurement_id IS NULL
                  AND join_rule_id = ?
                """,
                (int(report_id), rule_id),
            )
            conn.execute(
                """
                INSERT INTO industrial_link_candidates (
                    report_id,
                    measurement_id,
                    industrial_record_id,
                    join_rule_id,
                    confidence,
                    status,
                    explanation,
                    created_at,
                    updated_at
                )
                VALUES (?, NULL, ?, ?, 1.0, 'accepted', 'Manual user link', ?, ?)
                """,
                (int(report_id), int(industrial_record_id), rule_id, now, now),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    finally:
        if owns_connection:
            conn.close()


def clear_manual_industrial_report_link(
    database: str,
    *,
    report_id: int,
    connection: sqlite3.Connection | None = None,
) -> int:
    """Remove the user-managed link for one report, leaving automatic candidates intact."""

    ensure_industrial_data_schema(database, connection=connection)
    owns_connection = connection is None
    conn = connection or connect_sqlite(database)
    try:
        rule_id = ensure_manual_industrial_join_rule(database, connection=conn)
        with conn:
            cursor = conn.execute(
                """
                DELETE FROM industrial_link_candidates
                WHERE report_id = ?
                  AND measurement_id IS NULL
                  AND join_rule_id = ?
                """,
                (int(report_id), rule_id),
            )
            return int(cursor.rowcount)
    finally:
        if owns_connection:
            conn.close()


def materialize_industrial_report_links(
    database: str,
    rule: IndustrialJoinRuleSpec | None = None,
    *,
    connection: sqlite3.Connection | None = None,
) -> IndustrialJoinSummary:
    """Materialize report-level industrial link candidates for one rule."""

    rule = validate_join_rule(rule or IndustrialJoinRuleSpec())
    ensure_report_schema(database, connection=connection)
    owns_connection = connection is None
    conn = connection or connect_sqlite(database)
    try:
        rule_id = ensure_industrial_join_rule(database, rule, connection=conn)
        now = utc_timestamp()
        report_expr = REPORT_FIELD_SQL[rule.report_field]
        industrial_expr = INDUSTRIAL_FIELD_SQL[rule.industrial_field]
        time_clause, time_params = _time_window_clause(rule)
        with conn:
            conn.execute("DELETE FROM industrial_link_candidates WHERE join_rule_id = ?", (rule_id,))
            conn.execute(
                f"""
                WITH candidate_matches AS (
                    SELECT
                        pr.id AS report_id,
                        ir.id AS industrial_record_id
                    FROM parsed_reports pr
                    LEFT JOIN report_metadata rm ON rm.report_id = pr.id
                    JOIN industrial_records ir
                      ON LOWER(TRIM(CAST({report_expr} AS TEXT))) = LOWER(TRIM(CAST({industrial_expr} AS TEXT)))
                    WHERE TRIM(COALESCE(CAST({report_expr} AS TEXT), '')) <> ''
                      AND TRIM(COALESCE(CAST({industrial_expr} AS TEXT), '')) <> ''
                      {time_clause}
                ),
                candidate_counts AS (
                    SELECT report_id, COUNT(*) AS candidate_count
                    FROM candidate_matches
                    GROUP BY report_id
                )
                INSERT INTO industrial_link_candidates (
                    report_id,
                    measurement_id,
                    industrial_record_id,
                    join_rule_id,
                    confidence,
                    status,
                    explanation,
                    created_at,
                    updated_at
                )
                SELECT
                    candidate_matches.report_id,
                    NULL,
                    candidate_matches.industrial_record_id,
                    ?,
                    CASE WHEN candidate_counts.candidate_count = 1 THEN 1.0 ELSE 0.5 END,
                    CASE WHEN candidate_counts.candidate_count = 1 THEN 'accepted' ELSE 'candidate' END,
                    ? || ' match on ' || ? || ' -> ' || ? || '; '
                        || candidate_counts.candidate_count || ' candidate(s)',
                    ?,
                    ?
                FROM candidate_matches
                JOIN candidate_counts ON candidate_counts.report_id = candidate_matches.report_id
                """,
                (*time_params, rule_id, rule.match_mode, rule.report_field, rule.industrial_field, now, now),
            )

        reports_seen = int(conn.execute("SELECT COUNT(*) FROM parsed_reports").fetchone()[0])
        records_seen = int(conn.execute("SELECT COUNT(*) FROM industrial_records").fetchone()[0])
        candidates_inserted = int(
            conn.execute(
                "SELECT COUNT(*) FROM industrial_link_candidates WHERE join_rule_id = ?",
                (rule_id,),
            ).fetchone()[0]
        )
        accepted_links = int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT report_id)
                FROM industrial_link_candidates
                WHERE join_rule_id = ? AND status = 'accepted'
                """,
                (rule_id,),
            ).fetchone()[0]
        )
        ambiguous_reports = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT report_id
                    FROM industrial_link_candidates
                    WHERE join_rule_id = ?
                    GROUP BY report_id
                    HAVING COUNT(*) > 1
                ) AS ambiguous
                """,
                (rule_id,),
            ).fetchone()[0]
        )
        matched_reports = int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT report_id)
                FROM industrial_link_candidates
                WHERE join_rule_id = ?
                """,
                (rule_id,),
            ).fetchone()[0]
        )
        unmatched_reports = reports_seen - matched_reports
        return IndustrialJoinSummary(
            rule_id=rule_id,
            reports_seen=reports_seen,
            records_seen=records_seen,
            candidates_inserted=candidates_inserted,
            accepted_links=accepted_links,
            ambiguous_reports=ambiguous_reports,
            unmatched_reports=unmatched_reports,
        )
    finally:
        if owns_connection:
            conn.close()

"""Discovery helpers for characteristic name matching UI workflows."""

from __future__ import annotations

import sqlite3

from metroliza.reports.characteristic_alias_service import normalize_alias_scope
from metroliza.reports.db import execute_with_retry


_METRIC_IDENTITY_SQL = """
    CASE
        WHEN TRIM(COALESCE(CAST(header AS TEXT), '')) <> ''
          AND TRIM(COALESCE(CAST(ax AS TEXT), '')) <> ''
        THEN TRIM(CAST(header AS TEXT)) || ' - ' || TRIM(CAST(ax AS TEXT))
        WHEN TRIM(COALESCE(CAST(header AS TEXT), '')) <> ''
        THEN TRIM(CAST(header AS TEXT))
        ELSE ''
    END
"""

_REFERENCE_SQL = "NULLIF(TRIM(COALESCE(CAST(reference AS TEXT), '')), '')"


def _sqlite_object_exists(
    db_path: str,
    object_name: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> bool:
    rows = execute_with_retry(
        db_path,
        """
        SELECT 1
        FROM sqlite_master
        WHERE LOWER(name) = LOWER(?)
          AND type IN ('table', 'view')
        LIMIT 1
        """,
        params=(object_name,),
        connection=connection,
    )
    return bool(rows)


def _legacy_measurement_tables_exist(
    db_path: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> bool:
    return (
        _sqlite_object_exists(db_path, 'MEASUREMENTS', connection=connection)
        and _sqlite_object_exists(db_path, 'REPORTS', connection=connection)
    )


def _measurement_source_sql(
    db_path: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> str | None:
    if _legacy_measurement_tables_exist(db_path, connection=connection):
        from metroliza.reports.report_schema import ensure_report_schema

        ensure_report_schema(db_path, connection=connection)

    if _sqlite_object_exists(db_path, 'vw_measurement_export', connection=connection):
        return """
            SELECT
                report_id AS report_id,
                measurement_id AS measurement_id,
                reference AS reference,
                header AS header,
                ax AS ax
            FROM vw_measurement_export
        """

    if (
        _sqlite_object_exists(db_path, 'report_measurements', connection=connection)
        and _sqlite_object_exists(db_path, 'parsed_reports', connection=connection)
        and _sqlite_object_exists(db_path, 'report_metadata', connection=connection)
    ):
        return """
            SELECT
                pr.id AS report_id,
                meas.id AS measurement_id,
                rm.reference AS reference,
                meas.header AS header,
                meas.ax AS ax
            FROM report_measurements meas
            JOIN parsed_reports pr ON pr.id = meas.report_id
            LEFT JOIN report_metadata rm ON rm.report_id = pr.id
        """

    if _legacy_measurement_tables_exist(db_path, connection=connection):
        return """
            SELECT
                REPORTS.ID AS report_id,
                MEASUREMENTS.ID AS measurement_id,
                REPORTS.REFERENCE AS reference,
                MEASUREMENTS.HEADER AS header,
                MEASUREMENTS.AX AS ax
            FROM MEASUREMENTS
            JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
        """

    return None


def _is_missing_measurement_source_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return 'no such table' in message or 'no such column' in message


def _metric_source_cte(source_sql: str) -> str:
    return f"""
        WITH measurement_source AS (
            {source_sql}
        ),
        metric_source AS (
            SELECT
                {_METRIC_IDENTITY_SQL} AS metric_name,
                {_REFERENCE_SQL} AS reference,
                report_id,
                measurement_id
            FROM measurement_source
        )
    """


def _fetch_sample_references(
    db_path: str,
    source_sql: str,
    metric_name: str,
    *,
    sample_reference_limit: int,
    connection: sqlite3.Connection | None = None,
) -> list[str]:
    limit = max(0, int(sample_reference_limit or 0))
    if limit == 0:
        return []

    try:
        rows = execute_with_retry(
            db_path,
            f"""
            {_metric_source_cte(source_sql)}
            SELECT reference
            FROM metric_source
            WHERE metric_name = ?
              AND reference IS NOT NULL
            GROUP BY reference
            ORDER BY LOWER(reference), reference
            LIMIT ?
            """,
            params=(metric_name, limit),
            connection=connection,
        )
    except sqlite3.OperationalError as exc:
        if _is_missing_measurement_source_error(exc):
            return []
        raise
    return [str(row[0]) for row in rows]


def fetch_distinct_report_metric_names(
    db_path: str,
    *,
    sample_reference_limit: int = 3,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, object]]:
    """Return distinct report metric names with impact counts and reference samples.

    Metric identity follows export/group-analysis behavior: ``HEADER - AX`` when
    both ``HEADER`` and ``AX`` are non-empty after trimming, otherwise ``HEADER``.
    Blank metric identities are excluded from the result.
    """
    source_sql = _measurement_source_sql(db_path, connection=connection)
    if source_sql is None:
        return []

    try:
        rows = execute_with_retry(
            db_path,
            f"""
            {_metric_source_cte(source_sql)}
            SELECT
                metric_name,
                COUNT(*) AS measurement_count,
                COUNT(DISTINCT report_id) AS report_count,
                COUNT(DISTINCT reference) AS reference_count
            FROM metric_source
            WHERE metric_name <> ''
            GROUP BY metric_name
            ORDER BY LOWER(metric_name), metric_name
            """,
            connection=connection,
        )
    except sqlite3.OperationalError as exc:
        if _is_missing_measurement_source_error(exc):
            return []
        raise

    return [
        {
            'metric_name': str(metric_name),
            'measurement_count': int(measurement_count or 0),
            'report_count': int(report_count or 0),
            'reference_count': int(reference_count or 0),
            'sample_references': _fetch_sample_references(
                db_path,
                source_sql,
                str(metric_name),
                sample_reference_limit=sample_reference_limit,
                connection=connection,
            ),
        }
        for metric_name, measurement_count, report_count, reference_count in rows
    ]


def fetch_distinct_references(
    db_path: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, object]]:
    """Return distinct non-empty references with measurement and report counts."""
    source_sql = _measurement_source_sql(db_path, connection=connection)
    if source_sql is None:
        return []

    try:
        rows = execute_with_retry(
            db_path,
            f"""
            WITH measurement_source AS (
                {source_sql}
            ),
            reference_source AS (
                SELECT
                    {_REFERENCE_SQL} AS reference,
                    report_id,
                    measurement_id
                FROM measurement_source
            )
            SELECT
                reference,
                COUNT(*) AS measurement_count,
                COUNT(DISTINCT report_id) AS report_count
            FROM reference_source
            WHERE reference IS NOT NULL
            GROUP BY reference
            ORDER BY LOWER(reference), reference
            """,
            connection=connection,
        )
    except sqlite3.OperationalError as exc:
        if _is_missing_measurement_source_error(exc):
            return []
        raise
    return [
        {
            'reference': str(reference),
            'measurement_count': int(measurement_count or 0),
            'report_count': int(report_count or 0),
        }
        for reference, measurement_count, report_count in rows
    ]


def fetch_mapping_impact_counts(
    db_path: str,
    *,
    alias_name: str,
    scope_type: str,
    scope_value: str | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, int]:
    """Return counts for measurements that a proposed alias mapping would affect."""
    normalized_alias_name = str(alias_name or '').strip()
    if not normalized_alias_name:
        raise ValueError('alias_name is required')

    normalized_scope_type, normalized_scope_value = normalize_alias_scope(scope_type, scope_value)
    source_sql = _measurement_source_sql(db_path, connection=connection)
    if source_sql is None:
        return {'measurement_count': 0, 'report_count': 0, 'reference_count': 0}

    where_clause = 'metric_name = ?'
    params: list[str] = [normalized_alias_name]
    if normalized_scope_type == 'reference':
        where_clause += ' AND reference = ?'
        params.append(str(normalized_scope_value))

    try:
        rows = execute_with_retry(
            db_path,
            f"""
            {_metric_source_cte(source_sql)}
            SELECT
                COUNT(*) AS measurement_count,
                COUNT(DISTINCT report_id) AS report_count,
                COUNT(DISTINCT reference) AS reference_count
            FROM metric_source
            WHERE {where_clause}
            """,
            params=tuple(params),
            connection=connection,
        )
    except sqlite3.OperationalError as exc:
        if _is_missing_measurement_source_error(exc):
            return {'measurement_count': 0, 'report_count': 0, 'reference_count': 0}
        raise
    measurement_count, report_count, reference_count = rows[0] if rows else (0, 0, 0)
    return {
        'measurement_count': int(measurement_count or 0),
        'report_count': int(report_count or 0),
        'reference_count': int(reference_count or 0),
    }

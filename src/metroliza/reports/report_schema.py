"""SQLite schema bootstrap for report ingestion storage and read views."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import PurePath

from metroliza.reports.characteristic_alias_service import ensure_characteristic_alias_table
from metroliza.reports.db import run_transaction_with_retry
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema


SCHEMA_VERSION = "report_metadata_v1"

PARSE_STATUSES = ("parsed", "parsed_with_warnings", "failed", "unsupported")
SAMPLE_NUMBER_KINDS = (
    "explicit_sample_number",
    "stats_count",
    "filename_tail",
    "derived_counter",
    "unknown",
)
WARNING_SEVERITIES = ("info", "warning", "error")
MEASUREMENT_STATUS_CODES = ("ok", "nok", "unknown")


def _quoted_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


SCHEMA_TABLE_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS app_schema (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS source_files (
        id INTEGER PRIMARY KEY,
        sha256 TEXT NOT NULL UNIQUE,
        file_size_bytes INTEGER,
        source_format TEXT NOT NULL,
        discovered_at TEXT NOT NULL,
        ingested_at TEXT,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
    )""",
    """CREATE TABLE IF NOT EXISTS source_file_locations (
        id INTEGER PRIMARY KEY,
        source_file_id INTEGER NOT NULL,
        absolute_path TEXT NOT NULL,
        directory_path TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_extension TEXT NOT NULL,
        file_modified_at TEXT,
        discovered_at TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        FOREIGN KEY (source_file_id) REFERENCES source_files(id) ON DELETE CASCADE,
        UNIQUE(source_file_id, absolute_path)
    )""",
    f"""CREATE TABLE IF NOT EXISTS parsed_reports (
        id INTEGER PRIMARY KEY,
        source_file_id INTEGER NOT NULL,
        parser_id TEXT NOT NULL,
        parser_version TEXT,
        template_family TEXT NOT NULL,
        template_variant TEXT,
        parse_status TEXT NOT NULL CHECK (parse_status IN ({_quoted_values(PARSE_STATUSES)})),
        parse_started_at TEXT,
        parse_finished_at TEXT,
        parse_duration_ms INTEGER,
        page_count INTEGER,
        measurement_count INTEGER NOT NULL DEFAULT 0,
        has_nok INTEGER NOT NULL DEFAULT 0 CHECK (has_nok IN (0, 1)),
        nok_count INTEGER NOT NULL DEFAULT 0,
        metadata_confidence REAL CHECK (metadata_confidence IS NULL OR (metadata_confidence >= 0 AND metadata_confidence <= 1)),
        identity_hash TEXT,
        raw_report_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (source_file_id) REFERENCES source_files(id),
        UNIQUE(source_file_id)
    )""",
    f"""CREATE TABLE IF NOT EXISTS report_metadata (
        report_id INTEGER PRIMARY KEY,
        reference TEXT,
        reference_raw TEXT,
        report_date TEXT,
        report_time TEXT,
        part_name TEXT,
        revision TEXT,
        sample_number TEXT,
        sample_number_kind TEXT CHECK (sample_number_kind IS NULL OR sample_number_kind IN ({_quoted_values(SAMPLE_NUMBER_KINDS)})),
        stats_count_raw TEXT,
        stats_count_int INTEGER,
        operator_name TEXT,
        comment TEXT,
        metadata_version TEXT NOT NULL,
        metadata_profile_id TEXT,
        metadata_profile_version TEXT,
        metadata_json TEXT,
        FOREIGN KEY (report_id) REFERENCES parsed_reports(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS report_metadata_candidates (
        id INTEGER PRIMARY KEY,
        report_id INTEGER NOT NULL,
        field_name TEXT NOT NULL,
        raw_value TEXT,
        normalized_value TEXT,
        source_type TEXT NOT NULL,
        source_detail TEXT,
        page_number INTEGER,
        region_name TEXT,
        label_text TEXT,
        rule_id TEXT NOT NULL,
        confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
        is_selected INTEGER NOT NULL DEFAULT 0 CHECK (is_selected IN (0, 1)),
        evidence_text TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (report_id) REFERENCES parsed_reports(id) ON DELETE CASCADE
    )""",
    f"""CREATE TABLE IF NOT EXISTS report_metadata_warnings (
        id INTEGER PRIMARY KEY,
        report_id INTEGER NOT NULL,
        code TEXT NOT NULL,
        field_name TEXT,
        severity TEXT NOT NULL CHECK (severity IN ({_quoted_values(WARNING_SEVERITIES)})),
        message TEXT NOT NULL,
        details_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (report_id) REFERENCES parsed_reports(id) ON DELETE CASCADE
    )""",
    f"""CREATE TABLE IF NOT EXISTS report_measurements (
        id INTEGER PRIMARY KEY,
        report_id INTEGER NOT NULL,
        page_number INTEGER,
        row_order INTEGER NOT NULL,
        header TEXT,
        section_name TEXT,
        feature_label TEXT,
        characteristic_name TEXT,
        characteristic_family TEXT,
        description TEXT,
        ax TEXT,
        nominal REAL,
        tol_plus REAL,
        tol_minus REAL,
        bonus REAL,
        meas REAL,
        dev REAL,
        outtol REAL,
        is_nok INTEGER NOT NULL DEFAULT 0 CHECK (is_nok IN (0, 1)),
        status_code TEXT NOT NULL CHECK (status_code IN ({_quoted_values(MEASUREMENT_STATUS_CODES)})),
        raw_measurement_json TEXT,
        FOREIGN KEY (report_id) REFERENCES parsed_reports(id) ON DELETE CASCADE
    )""",
)

SCHEMA_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_source_files_sha256 ON source_files(sha256)",
    "CREATE INDEX IF NOT EXISTS idx_source_file_locations_name ON source_file_locations(file_name)",
    "CREATE INDEX IF NOT EXISTS idx_source_file_locations_directory ON source_file_locations(directory_path)",
    "CREATE INDEX IF NOT EXISTS idx_source_file_locations_source_active ON source_file_locations(source_file_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_source_file_locations_latest_active ON source_file_locations(source_file_id, is_active, discovered_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_parsed_reports_parser_template ON parsed_reports(parser_id, template_family, template_variant)",
    "CREATE INDEX IF NOT EXISTS idx_parsed_reports_identity_hash ON parsed_reports(identity_hash)",
    "CREATE INDEX IF NOT EXISTS idx_parsed_reports_status ON parsed_reports(parse_status)",
    "CREATE INDEX IF NOT EXISTS idx_report_metadata_reference ON report_metadata(reference)",
    "CREATE INDEX IF NOT EXISTS idx_report_metadata_report_date ON report_metadata(report_date)",
    "CREATE INDEX IF NOT EXISTS idx_report_metadata_sample_number ON report_metadata(sample_number)",
    "CREATE INDEX IF NOT EXISTS idx_report_metadata_part_name ON report_metadata(part_name)",
    "CREATE INDEX IF NOT EXISTS idx_report_metadata_revision ON report_metadata(revision)",
    "CREATE INDEX IF NOT EXISTS idx_report_metadata_stats_count_int ON report_metadata(stats_count_int)",
    "CREATE INDEX IF NOT EXISTS idx_report_metadata_candidates_report_field ON report_metadata_candidates(report_id, field_name, is_selected)",
    "CREATE INDEX IF NOT EXISTS idx_report_metadata_candidates_rule ON report_metadata_candidates(rule_id)",
    "CREATE INDEX IF NOT EXISTS idx_report_metadata_warnings_report ON report_metadata_warnings(report_id)",
    "CREATE INDEX IF NOT EXISTS idx_report_metadata_warnings_code ON report_metadata_warnings(code)",
    "CREATE INDEX IF NOT EXISTS idx_report_measurements_report ON report_measurements(report_id)",
    "CREATE INDEX IF NOT EXISTS idx_report_measurements_header ON report_measurements(header)",
    "CREATE INDEX IF NOT EXISTS idx_report_measurements_ax ON report_measurements(ax)",
    "CREATE INDEX IF NOT EXISTS idx_report_measurements_report_header_ax ON report_measurements(report_id, header, ax)",
    "CREATE INDEX IF NOT EXISTS idx_report_measurements_status ON report_measurements(status_code)",
    "CREATE INDEX IF NOT EXISTS idx_report_measurements_family ON report_measurements(characteristic_family)",
)

SCHEMA_VIEW_STATEMENTS = (
    """CREATE VIEW IF NOT EXISTS vw_report_overview AS
        SELECT
            pr.id AS report_id,
            pr.source_file_id AS source_file_id,
            pr.parser_id AS parser_id,
            pr.template_family AS template_family,
            pr.template_variant AS template_variant,
            pr.parse_status AS parse_status,
            pr.metadata_confidence AS metadata_confidence,
            rm.reference AS reference,
            rm.report_date AS report_date,
            rm.report_time AS report_time,
            rm.part_name AS part_name,
            rm.revision AS revision,
            rm.sample_number AS sample_number,
            rm.sample_number_kind AS sample_number_kind,
            rm.stats_count_raw AS stats_count_raw,
            rm.stats_count_int AS stats_count_int,
            rm.operator_name AS operator_name,
            rm.comment AS comment,
            pr.page_count AS page_count,
            pr.measurement_count AS measurement_count,
            pr.has_nok AS has_nok,
            pr.nok_count AS nok_count,
            sfl.file_name AS file_name,
            sfl.directory_path AS directory_path,
            sfl.absolute_path AS absolute_path,
            sf.sha256 AS sha256
        FROM parsed_reports pr
        JOIN source_files sf ON sf.id = pr.source_file_id
        LEFT JOIN report_metadata rm ON rm.report_id = pr.id
        LEFT JOIN source_file_locations sfl ON sfl.id = (
            SELECT selected_location.id
            FROM source_file_locations selected_location
            WHERE selected_location.source_file_id = sf.id
              AND selected_location.is_active = 1
            ORDER BY selected_location.discovered_at DESC, selected_location.id DESC
            LIMIT 1
        )""",
    """CREATE VIEW IF NOT EXISTS vw_measurement_export AS
        SELECT
            pr.id AS report_id,
            meas.id AS measurement_id,
            rm.reference AS reference,
            rm.report_date AS report_date,
            rm.report_time AS report_time,
            rm.part_name AS part_name,
            rm.revision AS revision,
            rm.sample_number AS sample_number,
            rm.sample_number_kind AS sample_number_kind,
            rm.stats_count_raw AS stats_count_raw,
            rm.stats_count_int AS stats_count_int,
            rm.operator_name AS operator_name,
            sfl.file_name AS file_name,
            sfl.directory_path AS directory_path,
            sfl.absolute_path AS absolute_path,
            pr.parser_id AS parser_id,
            pr.template_family AS template_family,
            pr.template_variant AS template_variant,
            meas.header AS header,
            meas.section_name AS section_name,
            meas.feature_label AS feature_label,
            meas.characteristic_name AS characteristic_name,
            meas.characteristic_family AS characteristic_family,
            meas.description AS description,
            meas.ax AS ax,
            meas.nominal AS nominal,
            meas.tol_plus AS tol_plus,
            meas.tol_minus AS tol_minus,
            meas.bonus AS bonus,
            meas.meas AS meas,
            meas.dev AS dev,
            meas.outtol AS outtol,
            meas.is_nok AS is_nok,
            meas.status_code AS status_code,
            meas.page_number AS page_number,
            meas.row_order AS row_order,
            pr.has_nok AS has_nok,
            pr.nok_count AS nok_count
        FROM report_measurements meas
        JOIN parsed_reports pr ON pr.id = meas.report_id
        LEFT JOIN report_metadata rm ON rm.report_id = pr.id
        JOIN source_files sf ON sf.id = pr.source_file_id
        LEFT JOIN source_file_locations sfl ON sfl.id = (
            SELECT selected_location.id
            FROM source_file_locations selected_location
            WHERE selected_location.source_file_id = sf.id
              AND selected_location.is_active = 1
            ORDER BY selected_location.discovered_at DESC, selected_location.id DESC
            LIMIT 1
        )""",
    """CREATE VIEW IF NOT EXISTS vw_grouping_reports AS
        SELECT
            pr.id AS report_id,
            rm.reference AS reference,
            rm.report_date AS report_date,
            rm.sample_number AS sample_number,
            rm.part_name AS part_name,
            rm.revision AS revision,
            pr.template_variant AS template_variant,
            pr.has_nok AS has_nok,
            pr.nok_count AS nok_count,
            sfl.file_name AS file_name
        FROM parsed_reports pr
        LEFT JOIN report_metadata rm ON rm.report_id = pr.id
        JOIN source_files sf ON sf.id = pr.source_file_id
        LEFT JOIN source_file_locations sfl ON sfl.id = (
            SELECT selected_location.id
            FROM source_file_locations selected_location
            WHERE selected_location.source_file_id = sf.id
              AND selected_location.is_active = 1
            ORDER BY selected_location.discovered_at DESC, selected_location.id DESC
            LIMIT 1
        )""",
)

SCHEMA_VIEW_NAMES = ("vw_report_overview", "vw_measurement_export", "vw_grouping_reports")


def _normalize_column_map(description) -> dict[str, int]:
    return {column[0].lower(): index for index, column in enumerate(description or [])}


def _row_value(row, columns: dict[str, int], column_name: str, default=None):
    index = columns.get(column_name.lower())
    if index is None:
        return default
    return row[index]


def _text_value(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_value(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _legacy_file_parts(legacy_report_id: int, report_row, report_columns: dict[str, int]) -> tuple[str, str, str, str]:
    directory_path = _text_value(_row_value(report_row, report_columns, "FILELOC")) or ""
    file_name = _text_value(_row_value(report_row, report_columns, "FILENAME")) or f"legacy-report-{legacy_report_id}.pdf"
    separator = "\\" if "\\" in directory_path and "/" not in directory_path else "/"
    normalized_directory = directory_path.rstrip("/\\")
    absolute_path = (
        f"{normalized_directory}{separator}{file_name}"
        if directory_path
        else file_name
    )
    file_extension = PurePath(file_name).suffix.lower()
    return absolute_path, directory_path, file_name, file_extension


def _legacy_source_sha(legacy_report_id: int) -> str:
    return hashlib.sha256(f"metroliza:legacy-report:{legacy_report_id}".encode("utf-8")).hexdigest()


def _legacy_measurement_status(outtol) -> tuple[int, str]:
    numeric_outtol = _float_value(outtol)
    is_nok = int(bool(numeric_outtol is not None and numeric_outtol > 0))
    return is_nok, "nok" if is_nok else "ok"


def _fetch_table_rows(cursor, table_name: str) -> tuple[list[tuple], dict[str, int]]:
    try:
        cursor.execute(f'SELECT * FROM "{table_name}"')
    except sqlite3.Error:
        return [], {}
    rows = cursor.fetchall()
    return rows, _normalize_column_map(cursor.description)


def _migrate_legacy_report_tables(cursor) -> None:
    """Copy legacy REPORTS/MEASUREMENTS rows into the current schema once.

    Legacy tables are left intact. The copied rows make old databases readable
    through the current views used by export, filtering, grouping, and industrial
    linking. Existing current rows are not overwritten so user edits made after
    an upgrade remain authoritative.
    """

    report_rows, report_columns = _fetch_table_rows(cursor, "REPORTS")
    measurement_rows, measurement_columns = _fetch_table_rows(cursor, "MEASUREMENTS")
    if not report_rows or "id" not in report_columns or "report_id" not in measurement_columns:
        return

    measurements_by_report: dict[int, list[tuple]] = defaultdict(list)
    for measurement_row in measurement_rows:
        legacy_report_id = _row_value(measurement_row, measurement_columns, "REPORT_ID")
        if legacy_report_id is None:
            continue
        try:
            measurements_by_report[int(legacy_report_id)].append(measurement_row)
        except (TypeError, ValueError):
            continue

    for report_row in report_rows:
        legacy_report_id = _row_value(report_row, report_columns, "ID")
        try:
            legacy_report_id = int(legacy_report_id)
        except (TypeError, ValueError):
            continue

        report_measurements = measurements_by_report.get(legacy_report_id, [])
        nok_count = sum(
            _legacy_measurement_status(_row_value(row, measurement_columns, "OUTTOL"))[0]
            for row in report_measurements
        )
        absolute_path, directory_path, file_name, file_extension = _legacy_file_parts(
            legacy_report_id,
            report_row,
            report_columns,
        )
        sha256 = _legacy_source_sha(legacy_report_id)
        now_sql = "CURRENT_TIMESTAMP"

        cursor.execute(
            f"""
            INSERT OR IGNORE INTO source_files (
                sha256,
                file_size_bytes,
                source_format,
                discovered_at,
                ingested_at,
                is_active
            )
            VALUES (?, NULL, 'legacy_sqlite', {now_sql}, {now_sql}, 1)
            """,
            (sha256,),
        )
        cursor.execute("SELECT id FROM source_files WHERE sha256 = ?", (sha256,))
        source_file_id = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            INSERT OR IGNORE INTO source_file_locations (
                source_file_id,
                absolute_path,
                directory_path,
                file_name,
                file_extension,
                file_modified_at,
                discovered_at,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, NULL, {now_sql}, 1)
            """,
            (source_file_id, absolute_path, directory_path, file_name, file_extension),
        )

        cursor.execute("SELECT id FROM parsed_reports WHERE source_file_id = ?", (source_file_id,))
        parsed_report_row = cursor.fetchone()
        if parsed_report_row is None:
            cursor.execute(
                f"""
                INSERT INTO parsed_reports (
                    source_file_id,
                    parser_id,
                    parser_version,
                    template_family,
                    template_variant,
                    parse_status,
                    measurement_count,
                    has_nok,
                    nok_count,
                    identity_hash,
                    raw_report_json,
                    created_at,
                    updated_at
                )
                VALUES (?, 'legacy_sqlite', NULL, 'legacy_sqlite', NULL, 'parsed', ?, ?, ?, ?, ?, {now_sql}, {now_sql})
                """,
                (
                    source_file_id,
                    len(report_measurements),
                    int(nok_count > 0),
                    nok_count,
                    f"legacy-report:{legacy_report_id}",
                    json.dumps(
                        {
                            "legacy_report_id": legacy_report_id,
                            "legacy_source": "REPORTS/MEASUREMENTS",
                        },
                        sort_keys=True,
                    ),
                ),
            )
            report_id = int(cursor.lastrowid)
        else:
            report_id = int(parsed_report_row[0])

        reference = _text_value(_row_value(report_row, report_columns, "REFERENCE"))
        sample_number = _text_value(_row_value(report_row, report_columns, "SAMPLE_NUMBER"))
        report_date = _text_value(_row_value(report_row, report_columns, "DATE"))
        cursor.execute(
            """
            INSERT OR IGNORE INTO report_metadata (
                report_id,
                reference,
                reference_raw,
                report_date,
                sample_number,
                sample_number_kind,
                metadata_version,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                reference,
                reference,
                report_date,
                sample_number,
                "explicit_sample_number" if sample_number else None,
                SCHEMA_VERSION,
                json.dumps(
                    {
                        "legacy_report_id": legacy_report_id,
                        "field_sources": {
                            "reference": "legacy_reports",
                            "report_date": "legacy_reports",
                            "sample_number": "legacy_reports",
                        },
                    },
                    sort_keys=True,
                ),
            ),
        )

        cursor.execute("SELECT 1 FROM report_measurements WHERE report_id = ? LIMIT 1", (report_id,))
        if cursor.fetchone() is not None:
            continue

        measurement_payloads = []
        for row_order, measurement_row in enumerate(report_measurements, start=1):
            header = _text_value(_row_value(measurement_row, measurement_columns, "HEADER"))
            outtol = _row_value(measurement_row, measurement_columns, "OUTTOL")
            is_nok, status_code = _legacy_measurement_status(outtol)
            measurement_payloads.append(
                (
                    report_id,
                    row_order,
                    header,
                    header,
                    header,
                    header,
                    header,
                    _text_value(_row_value(measurement_row, measurement_columns, "AX")),
                    _float_value(_row_value(measurement_row, measurement_columns, "NOM")),
                    _float_value(_row_value(measurement_row, measurement_columns, "+TOL")),
                    _float_value(_row_value(measurement_row, measurement_columns, "-TOL")),
                    _float_value(_row_value(measurement_row, measurement_columns, "BONUS")),
                    _float_value(_row_value(measurement_row, measurement_columns, "MEAS")),
                    _float_value(_row_value(measurement_row, measurement_columns, "DEV")),
                    _float_value(outtol),
                    is_nok,
                    status_code,
                    json.dumps(
                        {
                            "legacy_measurement_id": _row_value(measurement_row, measurement_columns, "ID"),
                            "legacy_report_id": legacy_report_id,
                        },
                        sort_keys=True,
                    ),
                )
            )
        cursor.executemany(
            """
            INSERT INTO report_measurements (
                report_id,
                row_order,
                header,
                section_name,
                feature_label,
                characteristic_name,
                description,
                ax,
                nominal,
                tol_plus,
                tol_minus,
                bonus,
                meas,
                dev,
                outtol,
                is_nok,
                status_code,
                raw_measurement_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            measurement_payloads,
        )


def ensure_report_schema(database: str, *, connection=None, retries: int = 4, retry_delay_s: float = 1) -> None:
    """Ensure report ingestion tables, indexes, views, and schema metadata exist."""

    def _ensure_schema(cursor):
        for statement in SCHEMA_TABLE_STATEMENTS:
            cursor.execute(statement)
        _migrate_legacy_report_tables(cursor)
        ensure_characteristic_alias_table(cursor)
        for statement in SCHEMA_INDEX_STATEMENTS:
            cursor.execute(statement)
        for view_name in SCHEMA_VIEW_NAMES:
            cursor.execute(f"DROP VIEW IF EXISTS {view_name}")
        for statement in SCHEMA_VIEW_STATEMENTS:
            cursor.execute(statement)
        cursor.execute(
            "INSERT OR REPLACE INTO app_schema (key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )

    run_transaction_with_retry(
        database,
        _ensure_schema,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )
    ensure_industrial_data_schema(
        database,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )


def ensure_schema_indexes(cursor) -> None:
    """Create report storage indexes on an existing transaction cursor."""

    for statement in SCHEMA_INDEX_STATEMENTS:
        cursor.execute(statement)

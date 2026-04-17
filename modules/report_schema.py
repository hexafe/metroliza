"""SQLite schema bootstrap for report ingestion storage and read views."""

from __future__ import annotations

from modules.characteristic_alias_service import ensure_characteristic_alias_table
from modules.db import run_transaction_with_retry


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


def ensure_report_schema(database: str, *, connection=None, retries: int = 4, retry_delay_s: float = 1) -> None:
    """Ensure report ingestion tables, indexes, views, and schema metadata exist."""

    def _ensure_schema(cursor):
        for statement in SCHEMA_TABLE_STATEMENTS:
            cursor.execute(statement)
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


def ensure_schema_indexes(cursor) -> None:
    """Create report storage indexes on an existing transaction cursor."""

    for statement in SCHEMA_INDEX_STATEMENTS:
        cursor.execute(statement)

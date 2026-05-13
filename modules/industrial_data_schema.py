"""SQLite schema bootstrap for industrial cache storage used by Oznak integration."""

from __future__ import annotations

from modules.db import run_transaction_with_retry


SCHEMA_VERSION = "industrial_data_v2"

SYNC_RUN_STATUSES = ("running", "succeeded", "completed_with_warnings", "failed", "cancelled")
JOIN_MATCH_MODES = ("exact", "time_window")
LINK_CANDIDATE_STATUSES = ("candidate", "accepted", "rejected")


def _quoted_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _industrial_sync_runs_table_statement(table_name: str = "industrial_sync_runs") -> str:
    return f"""CREATE TABLE IF NOT EXISTS {table_name} (
        id INTEGER PRIMARY KEY,
        source_profile_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL CHECK (status IN ({_quoted_values(SYNC_RUN_STATUSES)})),
        row_count INTEGER NOT NULL DEFAULT 0,
        error_summary TEXT,
        filters_json TEXT,
        oznak_version TEXT,
        oznak_commit TEXT,
        diagnostics_json TEXT,
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE
    )"""


SCHEMA_TABLE_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS app_schema (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_source_profiles (
        id INTEGER PRIMARY KEY,
        profile_key TEXT NOT NULL UNIQUE,
        profile_name TEXT NOT NULL,
        source_db_alias TEXT NOT NULL,
        database_type TEXT NOT NULL,
        host TEXT,
        port INTEGER,
        database_name TEXT,
        source_object_name TEXT NOT NULL,
        allowed_columns_json TEXT NOT NULL,
        timestamp_column TEXT,
        default_pagination_column TEXT,
        is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    _industrial_sync_runs_table_statement(),
    """CREATE TABLE IF NOT EXISTS industrial_records (
        id INTEGER PRIMARY KEY,
        source_profile_id INTEGER NOT NULL,
        sync_run_id INTEGER,
        source_db_alias TEXT NOT NULL,
        source_record_key TEXT NOT NULL,
        process_timestamp TEXT,
        reference TEXT,
        part_number TEXT,
        part_name TEXT,
        revision TEXT,
        serial TEXT,
        batch_lot TEXT,
        work_order TEXT,
        station TEXT,
        line TEXT,
        operator_name TEXT,
        process_status TEXT,
        raw_record_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE,
        FOREIGN KEY (sync_run_id) REFERENCES industrial_sync_runs(id) ON DELETE SET NULL,
        UNIQUE(source_profile_id, source_db_alias, source_record_key)
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_record_values (
        id INTEGER PRIMARY KEY,
        record_id INTEGER NOT NULL,
        field_name TEXT NOT NULL,
        field_value_text TEXT,
        field_value_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (record_id) REFERENCES industrial_records(id) ON DELETE CASCADE,
        UNIQUE(record_id, field_name)
    )""",
    f"""CREATE TABLE IF NOT EXISTS industrial_join_rules (
        id INTEGER PRIMARY KEY,
        rule_key TEXT NOT NULL UNIQUE,
        rule_name TEXT NOT NULL,
        report_field TEXT NOT NULL,
        industrial_field TEXT NOT NULL,
        match_mode TEXT NOT NULL CHECK (match_mode IN ({_quoted_values(JOIN_MATCH_MODES)})),
        time_window_seconds INTEGER,
        priority INTEGER NOT NULL DEFAULT 100,
        is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
        settings_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    f"""CREATE TABLE IF NOT EXISTS industrial_link_candidates (
        id INTEGER PRIMARY KEY,
        report_id INTEGER,
        measurement_id INTEGER,
        industrial_record_id INTEGER NOT NULL,
        join_rule_id INTEGER,
        confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
        status TEXT NOT NULL CHECK (status IN ({_quoted_values(LINK_CANDIDATE_STATUSES)})),
        explanation TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (industrial_record_id) REFERENCES industrial_records(id) ON DELETE CASCADE,
        FOREIGN KEY (join_rule_id) REFERENCES industrial_join_rules(id) ON DELETE SET NULL,
        UNIQUE(report_id, measurement_id, industrial_record_id, join_rule_id)
    )""",
)

SCHEMA_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_industrial_source_profiles_enabled ON industrial_source_profiles(is_enabled)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_source_profiles_alias ON industrial_source_profiles(source_db_alias)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_sync_runs_profile_started ON industrial_sync_runs(source_profile_id, started_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_sync_runs_status ON industrial_sync_runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_profile_timestamp ON industrial_records(source_profile_id, process_timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_reference ON industrial_records(reference)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_part_revision ON industrial_records(part_number, revision)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_serial ON industrial_records(serial)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_batch_lot ON industrial_records(batch_lot)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_record_values_record_field ON industrial_record_values(record_id, field_name)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_join_rules_enabled_priority ON industrial_join_rules(is_enabled, priority)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_link_candidates_record_status ON industrial_link_candidates(industrial_record_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_link_candidates_report_measurement ON industrial_link_candidates(report_id, measurement_id)",
)


def ensure_industrial_data_schema(
    database: str, *, connection=None, retries: int = 4, retry_delay_s: float = 1
) -> None:
    """Ensure industrial cache tables, indexes, and schema metadata exist."""

    def _ensure_schema(cursor) -> None:
        for statement in SCHEMA_TABLE_STATEMENTS:
            cursor.execute(statement)
        _ensure_source_profile_columns(cursor)
        _ensure_sync_run_status_constraint(cursor)
        for statement in SCHEMA_INDEX_STATEMENTS:
            cursor.execute(statement)
        cursor.execute(
            "INSERT OR REPLACE INTO app_schema (key, value) VALUES (?, ?)",
            ("industrial_schema_version", SCHEMA_VERSION),
        )

    run_transaction_with_retry(
        database,
        _ensure_schema,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )
    if connection is not None:
        connection.execute("PRAGMA foreign_keys=ON")


def _ensure_source_profile_columns(cursor) -> None:
    """Apply additive migrations for existing industrial source-profile tables."""

    cursor.execute("PRAGMA table_info(industrial_source_profiles)")
    existing_columns = {str(row[1]) for row in cursor.fetchall()}
    migrations = {
        "host": "ALTER TABLE industrial_source_profiles ADD COLUMN host TEXT",
        "port": "ALTER TABLE industrial_source_profiles ADD COLUMN port INTEGER",
        "database_name": "ALTER TABLE industrial_source_profiles ADD COLUMN database_name TEXT",
    }
    for column_name, statement in migrations.items():
        if column_name not in existing_columns:
            cursor.execute(statement)


def _ensure_sync_run_status_constraint(cursor) -> None:
    """Rebuild legacy sync-run tables whose CHECK constraint lacks warning status."""

    cursor.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'industrial_sync_runs'
        """
    )
    row = cursor.fetchone()
    create_sql = str(row[0] or "") if row else ""
    if not create_sql or "completed_with_warnings" in create_sql:
        return

    columns = (
        "id",
        "source_profile_id",
        "started_at",
        "finished_at",
        "status",
        "row_count",
        "error_summary",
        "filters_json",
        "oznak_version",
        "oznak_commit",
        "diagnostics_json",
    )
    column_list = ", ".join(columns)
    cursor.execute("PRAGMA foreign_keys=OFF")
    cursor.execute("DROP TABLE IF EXISTS industrial_sync_runs_new")
    cursor.execute(_industrial_sync_runs_table_statement("industrial_sync_runs_new"))
    cursor.execute(
        f"""
        INSERT INTO industrial_sync_runs_new ({column_list})
        SELECT {column_list}
        FROM industrial_sync_runs
        """
    )
    cursor.execute("DROP TABLE industrial_sync_runs")
    cursor.execute("ALTER TABLE industrial_sync_runs_new RENAME TO industrial_sync_runs")

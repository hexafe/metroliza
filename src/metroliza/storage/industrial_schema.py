"""SQLite schema bootstrap for industrial cache storage used by Oznak integration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any


SCHEMA_VERSION = "industrial_data_v7"

SYNC_RUN_STATUSES = ("running", "succeeded", "completed_with_warnings", "failed", "cancelled")
JOIN_MATCH_MODES = ("exact", "time_window")
LINK_CANDIDATE_STATUSES = ("candidate", "accepted", "rejected")
TIMESTAMP_STORAGE_FORMAT = "utc_iso8601_microseconds_v1"
_SCHEMA_READY_LOCK = Lock()
_SCHEMA_READY_VERSIONS: dict[str, int] = {}

_CANONICAL_TIMESTAMP_COLUMNS = {
    "industrial_source_profiles": ("created_at", "updated_at"),
    "industrial_sync_runs": ("started_at", "finished_at", "heartbeat_at"),
    "industrial_sync_staging_records": ("created_at",),
    "industrial_records": ("created_at", "updated_at"),
    "industrial_record_values": ("created_at",),
    "industrial_join_rules": ("created_at", "updated_at"),
    "industrial_link_candidates": ("created_at", "updated_at"),
    "industrial_stream_offsets": ("event_time_watermark", "last_success_at"),
    "industrial_realtime_monitor_configs": ("created_at", "updated_at"),
    "industrial_signal_definitions": ("created_at", "updated_at"),
    "industrial_samples": ("event_time", "ingest_time"),
    "industrial_detector_configs": ("created_at", "updated_at"),
    "industrial_baselines": ("window_start", "window_end", "created_at"),
    "industrial_anomaly_events": ("event_time", "ack_at", "created_at"),
    "industrial_realtime_stream_events": ("event_time", "created_at"),
    "industrial_realtime_consumer_offsets": ("last_success_at", "updated_at"),
    "industrial_realtime_dead_letters": ("failed_at",),
    "industrial_realtime_source_health": ("evaluated_at", "latest_event_time"),
    "industrial_model_artifacts": (
        "training_window_start",
        "training_window_end",
        "created_at",
        "updated_at",
    ),
}

TransactionRunner = Callable[..., Any]
ConnectionScopeFactory = Callable[..., Any]
TimestampCanonicalizer = Callable[[object], str]


def _canonical_utc_timestamp(value: object) -> str:
    """Normalize a persisted timestamp using the industrial schema's UTC policy."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("timestamp is required")
        if text.endswith(("Z", "z")):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _quoted_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _industrial_sync_runs_table_statement(table_name: str = "industrial_sync_runs") -> str:
    return f"""CREATE TABLE IF NOT EXISTS {table_name} (
        id INTEGER PRIMARY KEY,
        source_profile_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        heartbeat_at TEXT,
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
        order_by_enabled INTEGER NOT NULL DEFAULT 1 CHECK (order_by_enabled IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    _industrial_sync_runs_table_statement(),
    """CREATE TABLE IF NOT EXISTS industrial_sync_staging_records (
        id INTEGER PRIMARY KEY,
        sync_run_id INTEGER NOT NULL,
        source_profile_id INTEGER NOT NULL,
        source_db_alias TEXT NOT NULL,
        source_record_key TEXT NOT NULL,
        row_json TEXT NOT NULL,
        sequence_number INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (sync_run_id) REFERENCES industrial_sync_runs(id) ON DELETE CASCADE,
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE,
        UNIQUE(sync_run_id, source_profile_id, source_db_alias, source_record_key)
    )""",
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
    """CREATE TABLE IF NOT EXISTS industrial_stream_offsets (
        id INTEGER PRIMARY KEY,
        source_profile_id INTEGER NOT NULL,
        stream_key TEXT NOT NULL,
        cursor_column TEXT NOT NULL,
        cursor_value TEXT,
        cursor_tie_breaker_column TEXT,
        cursor_tie_breaker_value TEXT,
        event_time_watermark TEXT,
        last_success_at TEXT,
        last_error TEXT,
        lag_seconds REAL,
        status TEXT NOT NULL DEFAULT 'idle',
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE,
        UNIQUE(source_profile_id, stream_key)
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_realtime_monitor_configs (
        id INTEGER PRIMARY KEY,
        source_profile_id INTEGER NOT NULL,
        stream_key TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        cursor_column TEXT NOT NULL,
        event_time_column TEXT NOT NULL,
        record_key_column TEXT NOT NULL,
        signal_keys_json TEXT NOT NULL DEFAULT '[]',
        signal_columns_json TEXT NOT NULL DEFAULT '{}',
        polling_interval_seconds REAL NOT NULL DEFAULT 60,
        timeout_seconds REAL NOT NULL DEFAULT 30,
        chunk_size INTEGER NOT NULL DEFAULT 500,
        max_catchup_rows_per_cycle INTEGER NOT NULL DEFAULT 5000,
        allowed_lateness_seconds REAL NOT NULL DEFAULT 0,
        source_timezone TEXT NOT NULL DEFAULT 'UTC',
        segment_fields_json TEXT NOT NULL DEFAULT '[]',
        context_fields_json TEXT NOT NULL DEFAULT '[]',
        detectors_json TEXT NOT NULL DEFAULT '[]',
        display_mode TEXT NOT NULL DEFAULT 'raw' CHECK (display_mode IN ('raw', 'aggregated')),
        aggregation_time_bucket TEXT NOT NULL DEFAULT 'none',
        aggregation_methods_json TEXT NOT NULL DEFAULT '[]',
        aggregation_group_fields_json TEXT NOT NULL DEFAULT '[]',
        dashboard_output_path TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE,
        UNIQUE(source_profile_id, stream_key)
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_signal_definitions (
        id INTEGER PRIMARY KEY,
        source_profile_id INTEGER NOT NULL,
        signal_key TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        unit TEXT,
        nominal REAL,
        lsl REAL,
        usl REAL,
        lower_warning REAL,
        upper_warning REAL,
        segment_fields_json TEXT NOT NULL DEFAULT '[]',
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE,
        UNIQUE(source_profile_id, signal_key)
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_samples (
        id INTEGER PRIMARY KEY,
        source_profile_id INTEGER NOT NULL,
        signal_id INTEGER NOT NULL,
        source_record_key TEXT NOT NULL,
        event_time TEXT NOT NULL,
        ingest_time TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        value REAL NOT NULL,
        reference TEXT,
        part_number TEXT,
        revision TEXT,
        station TEXT,
        line TEXT,
        work_order TEXT,
        batch_lot TEXT,
        segment_key_json TEXT NOT NULL DEFAULT '{}',
        quality_flags_json TEXT NOT NULL DEFAULT '[]',
        raw_record_json TEXT,
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE,
        FOREIGN KEY (signal_id) REFERENCES industrial_signal_definitions(id) ON DELETE CASCADE,
        UNIQUE(source_profile_id, signal_id, source_record_key)
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_detector_configs (
        id INTEGER PRIMARY KEY,
        detector_key TEXT NOT NULL UNIQUE,
        detector_type TEXT NOT NULL,
        parameters_json TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        severity_map_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_baselines (
        id INTEGER PRIMARY KEY,
        signal_id INTEGER NOT NULL,
        segment_key_json TEXT NOT NULL DEFAULT '{}',
        baseline_version TEXT NOT NULL,
        window_start TEXT,
        window_end TEXT,
        n INTEGER NOT NULL,
        mean REAL,
        std REAL,
        median REAL,
        mad REAL,
        q1 REAL,
        q3 REAL,
        iqr REAL,
        p01 REAL,
        p99 REAL,
        model_artifact_id INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY (signal_id) REFERENCES industrial_signal_definitions(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_anomaly_events (
        id INTEGER PRIMARY KEY,
        sample_id INTEGER NOT NULL,
        signal_id INTEGER NOT NULL,
        event_time TEXT NOT NULL,
        detector_key TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'major', 'critical')),
        score REAL NOT NULL,
        observed_value REAL NOT NULL,
        expected_value REAL,
        threshold_json TEXT NOT NULL DEFAULT '{}',
        explanation TEXT NOT NULL DEFAULT '',
        context_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved', 'false_positive')),
        ack_by TEXT,
        ack_at TEXT,
        comment TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (sample_id) REFERENCES industrial_samples(id) ON DELETE CASCADE,
        FOREIGN KEY (signal_id) REFERENCES industrial_signal_definitions(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_realtime_stream_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_profile_id INTEGER NOT NULL,
        stream_key TEXT NOT NULL,
        event_type TEXT NOT NULL,
        aggregate_type TEXT NOT NULL,
        aggregate_id INTEGER,
        sample_id INTEGER,
        anomaly_event_id INTEGER,
        idempotency_key TEXT NOT NULL,
        event_time TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_realtime_consumer_offsets (
        id INTEGER PRIMARY KEY,
        consumer_key TEXT NOT NULL,
        source_profile_id INTEGER NOT NULL,
        stream_key TEXT NOT NULL,
        last_event_id INTEGER NOT NULL DEFAULT 0 CHECK (last_event_id >= 0),
        last_success_at TEXT,
        last_error TEXT,
        failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
        status TEXT NOT NULL DEFAULT 'idle' CHECK (status IN ('idle', 'failed')),
        updated_at TEXT NOT NULL,
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_realtime_dead_letters (
        id INTEGER PRIMARY KEY,
        consumer_key TEXT NOT NULL,
        source_profile_id INTEGER NOT NULL,
        stream_key TEXT NOT NULL,
        event_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        error_summary TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        failed_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'quarantined'
            CHECK (status IN ('quarantined', 'resolved')),
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE,
        FOREIGN KEY (event_id) REFERENCES industrial_realtime_stream_events(event_id) ON DELETE CASCADE,
        UNIQUE(consumer_key, event_id)
    )""",
    """CREATE TABLE IF NOT EXISTS industrial_realtime_source_health (
        id INTEGER PRIMARY KEY,
        source_profile_id INTEGER NOT NULL,
        stream_key TEXT NOT NULL,
        evaluated_at TEXT NOT NULL,
        latest_event_time TEXT,
        last_sample_id INTEGER,
        lag_seconds REAL,
        status TEXT NOT NULL CHECK (status IN ('healthy', 'warning', 'major', 'no_data')),
        details_json TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (source_profile_id) REFERENCES industrial_source_profiles(id) ON DELETE CASCADE,
        FOREIGN KEY (last_sample_id) REFERENCES industrial_samples(id) ON DELETE SET NULL,
        UNIQUE(source_profile_id, stream_key)
    )""",
)

SCHEMA_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_industrial_source_profiles_enabled ON industrial_source_profiles(is_enabled)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_source_profiles_alias ON industrial_source_profiles(source_db_alias)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_sync_runs_profile_started ON industrial_sync_runs(source_profile_id, started_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_sync_runs_status ON industrial_sync_runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_sync_staging_run_sequence ON industrial_sync_staging_records(sync_run_id, sequence_number, id)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_profile_timestamp ON industrial_records(source_profile_id, process_timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_reference ON industrial_records(reference)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_reference_time_id ON industrial_records(reference COLLATE NOCASE, process_timestamp, id)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_part_revision ON industrial_records(part_number, revision)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_serial ON industrial_records(serial)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_records_batch_lot ON industrial_records(batch_lot)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_record_values_record_field ON industrial_record_values(record_id, field_name)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_record_values_field_text_record ON industrial_record_values(field_name, field_value_text, record_id)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_join_rules_enabled_priority ON industrial_join_rules(is_enabled, priority)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_link_candidates_record_status ON industrial_link_candidates(industrial_record_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_link_candidates_report_measurement ON industrial_link_candidates(report_id, measurement_id)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_stream_offsets_profile_stream ON industrial_stream_offsets(source_profile_id, stream_key)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_realtime_monitor_configs_enabled ON industrial_realtime_monitor_configs(enabled, source_profile_id)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_signal_definitions_profile_enabled ON industrial_signal_definitions(source_profile_id, enabled)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_samples_signal_time ON industrial_samples(signal_id, event_time)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_samples_signal_time_desc_value ON industrial_samples(signal_id, event_time DESC, id DESC, value)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_samples_profile_time ON industrial_samples(source_profile_id, event_time)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_samples_profile_signal_time ON industrial_samples(source_profile_id, signal_id, event_time)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_detector_configs_enabled ON industrial_detector_configs(enabled)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_baselines_signal_segment_created ON industrial_baselines(signal_id, segment_key_json, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_anomaly_events_signal_time ON industrial_anomaly_events(signal_id, event_time)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_anomaly_events_severity_status_time ON industrial_anomaly_events(severity, status, event_time)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_anomaly_events_detector_time ON industrial_anomaly_events(detector_key, event_time)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_anomaly_events_status_time_desc ON industrial_anomaly_events(status, event_time DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_anomaly_events_signal_status_time_desc ON industrial_anomaly_events(signal_id, status, event_time DESC, id DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_industrial_anomaly_events_sample_detector_unique ON industrial_anomaly_events(sample_id, detector_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_industrial_realtime_stream_events_source_stream_idempotency_key ON industrial_realtime_stream_events(source_profile_id, stream_key, idempotency_key)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_realtime_stream_events_source_stream_id ON industrial_realtime_stream_events(source_profile_id, stream_key, event_id)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_realtime_stream_events_type_time ON industrial_realtime_stream_events(event_type, event_time, event_id)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_realtime_stream_events_sample ON industrial_realtime_stream_events(sample_id)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_realtime_stream_events_anomaly ON industrial_realtime_stream_events(anomaly_event_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_industrial_realtime_consumer_offsets_unique ON industrial_realtime_consumer_offsets(consumer_key, source_profile_id, stream_key)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_realtime_consumer_offsets_stream ON industrial_realtime_consumer_offsets(source_profile_id, stream_key, last_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_realtime_consumer_offsets_status ON industrial_realtime_consumer_offsets(status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_realtime_dead_letters_stream ON industrial_realtime_dead_letters(source_profile_id, stream_key, event_id)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_realtime_dead_letters_status ON industrial_realtime_dead_letters(status, failed_at)",
    "CREATE INDEX IF NOT EXISTS idx_industrial_realtime_source_health_status ON industrial_realtime_source_health(status, evaluated_at)",
)


def ensure_industrial_data_schema(
    database: str,
    *,
    transaction_runner: TransactionRunner,
    connection_scope: ConnectionScopeFactory,
    canonical_timestamp: TimestampCanonicalizer = _canonical_utc_timestamp,
    connection=None,
    retries: int = 4,
    retry_delay_s: float = 1,
) -> None:
    """Ensure industrial tables using persistence callbacks supplied by the caller."""

    cache_key = _schema_cache_key(database) if connection is None else None
    if cache_key is not None and _cached_schema_is_current(
        database,
        cache_key,
        connection_scope=connection_scope,
    ):
        return

    def _ensure_schema(cursor) -> None:
        for statement in SCHEMA_TABLE_STATEMENTS:
            cursor.execute(statement)
        _ensure_source_profile_columns(cursor)
        _ensure_sync_run_columns(cursor)
        _ensure_stream_offset_columns(cursor)
        _ensure_monitor_config_columns(cursor)
        _ensure_canonical_timestamp_storage(
            cursor,
            canonical_timestamp=canonical_timestamp,
        )
        _ensure_sync_run_status_constraint(cursor)
        _ensure_realtime_stream_event_idempotency_scope(cursor)
        for statement in SCHEMA_INDEX_STATEMENTS:
            cursor.execute(statement)
        cursor.execute(
            "INSERT OR REPLACE INTO app_schema (key, value) VALUES (?, ?)",
            ("industrial_schema_version", SCHEMA_VERSION),
        )

    transaction_runner(
        database,
        _ensure_schema,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )
    if connection is not None:
        connection.execute("PRAGMA foreign_keys=ON")
    elif cache_key is not None:
        _remember_schema_version(
            database,
            cache_key,
            connection_scope=connection_scope,
        )


def _schema_cache_key(database: str) -> str | None:
    if str(database) == ":memory:":
        return None
    return str(Path(database).expanduser().resolve(strict=False))


def _cached_schema_is_current(
    database: str,
    cache_key: str,
    *,
    connection_scope: ConnectionScopeFactory,
) -> bool:
    with _SCHEMA_READY_LOCK:
        expected_schema_version = _SCHEMA_READY_VERSIONS.get(cache_key)
    if expected_schema_version is None:
        return False
    try:
        with connection_scope(database) as conn:
            schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
            row = conn.execute(
                "SELECT value FROM app_schema WHERE key = 'industrial_schema_version'"
            ).fetchone()
    except Exception:
        return False
    return (
        schema_version == expected_schema_version
        and row is not None
        and str(row[0]) == SCHEMA_VERSION
    )


def _remember_schema_version(
    database: str,
    cache_key: str,
    *,
    connection_scope: ConnectionScopeFactory,
) -> None:
    try:
        with connection_scope(database) as conn:
            schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
    except Exception:
        return
    with _SCHEMA_READY_LOCK:
        _SCHEMA_READY_VERSIONS[cache_key] = schema_version


def _ensure_realtime_stream_event_idempotency_scope(cursor) -> None:
    """Migrate the stream idempotency key from global uniqueness to per-stream uniqueness."""

    cursor.execute("DROP INDEX IF EXISTS idx_industrial_realtime_stream_events_idempotency_key")


def _ensure_source_profile_columns(cursor) -> None:
    """Apply additive migrations for existing industrial source-profile tables."""

    cursor.execute("PRAGMA table_info(industrial_source_profiles)")
    existing_columns = {str(row[1]) for row in cursor.fetchall()}
    migrations = {
        "host": "ALTER TABLE industrial_source_profiles ADD COLUMN host TEXT",
        "port": "ALTER TABLE industrial_source_profiles ADD COLUMN port INTEGER",
        "database_name": "ALTER TABLE industrial_source_profiles ADD COLUMN database_name TEXT",
        "order_by_enabled": (
            "ALTER TABLE industrial_source_profiles "
            "ADD COLUMN order_by_enabled INTEGER NOT NULL DEFAULT 1 CHECK (order_by_enabled IN (0, 1))"
        ),
    }
    for column_name, statement in migrations.items():
        if column_name not in existing_columns:
            cursor.execute(statement)


def _ensure_sync_run_columns(cursor) -> None:
    """Add the streamed-sync heartbeat without invalidating existing databases."""

    cursor.execute("PRAGMA table_info(industrial_sync_runs)")
    existing_columns = {str(row[1]) for row in cursor.fetchall()}
    if "heartbeat_at" not in existing_columns:
        cursor.execute("ALTER TABLE industrial_sync_runs ADD COLUMN heartbeat_at TEXT")
    cursor.execute(
        """
        UPDATE industrial_sync_runs
        SET heartbeat_at = started_at
        WHERE heartbeat_at IS NULL OR TRIM(heartbeat_at) = ''
        """
    )


def _ensure_stream_offset_columns(cursor) -> None:
    """Apply additive migrations for composite realtime stream cursors."""

    cursor.execute("PRAGMA table_info(industrial_stream_offsets)")
    existing_columns = {str(row[1]) for row in cursor.fetchall()}
    migrations = {
        "cursor_tie_breaker_column": (
            "ALTER TABLE industrial_stream_offsets ADD COLUMN cursor_tie_breaker_column TEXT"
        ),
        "cursor_tie_breaker_value": (
            "ALTER TABLE industrial_stream_offsets ADD COLUMN cursor_tie_breaker_value TEXT"
        ),
    }
    for column_name, statement in migrations.items():
        if column_name not in existing_columns:
            cursor.execute(statement)


def _ensure_monitor_config_columns(cursor) -> None:
    """Apply additive migrations for realtime source timestamp semantics."""

    cursor.execute("PRAGMA table_info(industrial_realtime_monitor_configs)")
    existing_columns = {str(row[1]) for row in cursor.fetchall()}
    if "source_timezone" not in existing_columns:
        cursor.execute(
            "ALTER TABLE industrial_realtime_monitor_configs "
            "ADD COLUMN source_timezone TEXT NOT NULL DEFAULT 'UTC'"
        )


def _ensure_canonical_timestamp_storage(
    cursor,
    *,
    canonical_timestamp: TimestampCanonicalizer,
) -> None:
    """One-time migration to fixed-width UTC text so indexed ordering is chronological."""

    cursor.execute(
        "SELECT value FROM app_schema WHERE key = 'industrial_timestamp_storage_format'"
    )
    row = cursor.fetchone()
    if row is not None and str(row[0]) == TIMESTAMP_STORAGE_FORMAT:
        return

    converted = 0
    invalid_skipped = 0
    for table_name, requested_columns in _CANONICAL_TIMESTAMP_COLUMNS.items():
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        if cursor.fetchone() is None:
            continue
        quoted_table = _quote_identifier(table_name)
        cursor.execute(f"PRAGMA table_info({quoted_table})")
        existing_columns = {str(column[1]) for column in cursor.fetchall()}
        for column_name in requested_columns:
            if column_name not in existing_columns:
                continue
            quoted_column = _quote_identifier(column_name)
            cursor.execute(
                f"SELECT rowid, {quoted_column} FROM {quoted_table} "
                f"WHERE {quoted_column} IS NOT NULL AND TRIM({quoted_column}) != ''"
            )
            updates: list[tuple[str, int]] = []
            for row_id, raw_value in cursor.fetchall():
                try:
                    canonical = canonical_timestamp(raw_value)
                except ValueError:
                    invalid_skipped += 1
                    continue
                if canonical != str(raw_value):
                    updates.append((canonical, int(row_id)))
            if updates:
                cursor.executemany(
                    f"UPDATE {quoted_table} SET {quoted_column} = ? WHERE rowid = ?",
                    updates,
                )
                converted += len(updates)

    diagnostics = json.dumps(
        {
            "converted": converted,
            "invalid_skipped": invalid_skipped,
            "legacy_naive_policy": "assume_utc",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    cursor.executemany(
        "INSERT OR REPLACE INTO app_schema (key, value) VALUES (?, ?)",
        (
            ("industrial_timestamp_storage_format", TIMESTAMP_STORAGE_FORMAT),
            ("industrial_timestamp_migration_diagnostics", diagnostics),
        ),
    )


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
        "heartbeat_at",
        "finished_at",
        "status",
        "row_count",
        "error_summary",
        "filters_json",
        "oznak_version",
        "oznak_commit",
        "diagnostics_json",
    )
    column_list = ", ".join(_quote_identifier(column) for column in columns)
    cursor.execute("DROP TABLE IF EXISTS temp._metroliza_sync_run_links")
    cursor.execute(
        """
        CREATE TEMP TABLE _metroliza_sync_run_links (
            record_id INTEGER PRIMARY KEY,
            sync_run_id INTEGER NOT NULL
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO _metroliza_sync_run_links (record_id, sync_run_id)
        SELECT records.id, records.sync_run_id
        FROM industrial_records AS records
        JOIN industrial_sync_runs AS runs ON runs.id = records.sync_run_id
        WHERE records.sync_run_id IS NOT NULL
        """
    )
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
    cursor.execute(
        """
        UPDATE industrial_records
        SET sync_run_id = (
            SELECT links.sync_run_id
            FROM _metroliza_sync_run_links AS links
            WHERE links.record_id = industrial_records.id
        )
        WHERE sync_run_id IS NULL
          AND id IN (SELECT record_id FROM _metroliza_sync_run_links)
          AND EXISTS (
              SELECT 1
              FROM industrial_sync_runs AS runs
              JOIN _metroliza_sync_run_links AS links ON links.sync_run_id = runs.id
              WHERE links.record_id = industrial_records.id
          )
        """
    )
    cursor.execute("DROP TABLE IF EXISTS temp._metroliza_sync_run_links")

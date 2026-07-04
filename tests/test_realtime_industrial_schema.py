import sqlite3

from metroliza.reports.db import sqlite_connection_scope
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_data_schema import SCHEMA_VERSION, ensure_industrial_data_schema
from metroliza.industrial.realtime.offset_store import StreamOffsetStore


def test_realtime_schema_creates_v6_tables_and_indexes_idempotently(tmp_path):
    db_path = str(tmp_path / "realtime.db")
    ensure_industrial_data_schema(db_path)
    ensure_industrial_data_schema(db_path)

    with sqlite_connection_scope(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_industrial_%'"
            ).fetchall()
        }
        schema_version_rows = conn.execute(
            "SELECT value FROM app_schema WHERE key = 'industrial_schema_version'"
        ).fetchall()

    assert len(schema_version_rows) == 1
    assert schema_version_rows[0][0] == SCHEMA_VERSION == "industrial_data_v6"
    assert {
        "industrial_realtime_monitor_configs",
        "industrial_stream_offsets",
        "industrial_signal_definitions",
        "industrial_samples",
        "industrial_detector_configs",
        "industrial_baselines",
        "industrial_anomaly_events",
        "industrial_realtime_stream_events",
        "industrial_realtime_consumer_offsets",
    }.issubset(tables)
    assert {
        "idx_industrial_realtime_monitor_configs_enabled",
        "idx_industrial_samples_signal_time",
        "idx_industrial_samples_profile_time",
        "idx_industrial_samples_profile_signal_time",
        "idx_industrial_baselines_signal_segment_created",
        "idx_industrial_anomaly_events_signal_time",
        "idx_industrial_anomaly_events_severity_status_time",
        "idx_industrial_anomaly_events_detector_time",
        "idx_industrial_realtime_stream_events_source_stream_idempotency_key",
        "idx_industrial_realtime_stream_events_source_stream_id",
        "idx_industrial_realtime_consumer_offsets_unique",
        "idx_industrial_realtime_consumer_offsets_stream",
    }.issubset(indexes)
    assert "idx_industrial_realtime_stream_events_idempotency_key" not in indexes


def test_realtime_schema_preserves_existing_industrial_cache_tables(tmp_path):
    db_path = str(tmp_path / "compat.db")
    repository = IndustrialDataRepository(db_path)

    profile = repository.upsert_source_profile(
        profile_key="line-a",
        profile_name="Line A",
        source_db_alias="plant_a",
        database_type="mssql",
        source_object_name="dbo.events",
    )
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)
    insert_result = repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        sync_run_id=sync_run_id,
        rows=[{"source_record_key": "ROW-1", "reference": "REF-1", "raw_record": {"id": 1}}],
    )
    repository.finish_sync_run(sync_run_id=sync_run_id, status="succeeded", row_count=1)

    ensure_industrial_data_schema(db_path)

    assert insert_result["inserted"] == 1
    assert repository.summarize_counts().records == 1


def test_realtime_schema_migrates_legacy_stream_offsets(tmp_path):
    db_path = str(tmp_path / "legacy-offsets.db")
    with sqlite_connection_scope(db_path) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE industrial_stream_offsets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_profile_id INTEGER NOT NULL,
                    stream_key TEXT NOT NULL,
                    cursor_column TEXT NOT NULL,
                    cursor_value TEXT,
                    event_time_watermark TEXT,
                    last_success_at TEXT,
                    last_error TEXT,
                    lag_seconds REAL,
                    status TEXT NOT NULL DEFAULT 'idle',
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_profile_id, stream_key)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO industrial_stream_offsets (
                    source_profile_id,
                    stream_key,
                    cursor_column,
                    cursor_value,
                    event_time_watermark,
                    last_success_at,
                    status,
                    updated_at
                )
                VALUES (1, 'cycle_time', 'event_id', '500', '2026-06-13T10:00:00Z',
                        '2026-06-13T10:00:05Z', 'idle', '2026-06-13T10:00:05Z')
                """
            )

    ensure_industrial_data_schema(db_path)
    offset = StreamOffsetStore(db_path).get_offset(source_profile_id=1, stream_key="cycle_time")

    with sqlite_connection_scope(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(industrial_stream_offsets)")}

    assert "cursor_tie_breaker_column" in columns
    assert "cursor_tie_breaker_value" in columns
    assert offset.cursor_value == "500"
    assert offset.cursor_tie_breaker_column is None
    assert offset.cursor_tie_breaker_value is None
    assert offset.event_time_watermark == "2026-06-13T10:00:00Z"


def test_realtime_anomaly_event_requires_sample_id(tmp_path):
    db_path = str(tmp_path / "constraints.db")
    ensure_industrial_data_schema(db_path)

    with sqlite_connection_scope(db_path) as conn:
        with conn:
            try:
                conn.execute(
                    """
                    INSERT INTO industrial_anomaly_events (
                        sample_id,
                        signal_id,
                        event_time,
                        detector_key,
                        severity,
                        score,
                        observed_value
                    )
                    VALUES (NULL, 1, '2026-06-13T10:00:00Z', 'stale_source', 'warning', 1, 1)
                    """
                )
            except sqlite3.IntegrityError as exc:
                assert "NOT NULL" in str(exc)
            else:  # pragma: no cover - constraint regression guard
                raise AssertionError("industrial_anomaly_events.sample_id must be NOT NULL")

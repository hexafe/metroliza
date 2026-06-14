import json
import sqlite3

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_data_schema import SCHEMA_VERSION


def _load_json(value):
    assert value
    return json.loads(value)


def test_repository_ensure_schema_is_idempotent_for_temp_sqlite(tmp_path):
    db_path = str(tmp_path / "industrial-cache.db")
    repository = IndustrialDataRepository(db_path)

    repository.ensure_schema()
    with sqlite3.connect(db_path) as conn:
        first_objects = conn.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE name LIKE 'industrial_%' OR name = 'app_schema'
            ORDER BY type, name
            """
        ).fetchall()
        first_version = conn.execute(
            "SELECT value FROM app_schema WHERE key = 'industrial_schema_version'"
        ).fetchone()[0]

    repository.ensure_schema()
    with sqlite3.connect(db_path) as conn:
        second_objects = conn.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE name LIKE 'industrial_%' OR name = 'app_schema'
            ORDER BY type, name
            """
        ).fetchall()
        second_version = conn.execute(
            "SELECT value FROM app_schema WHERE key = 'industrial_schema_version'"
        ).fetchone()[0]
        profile_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(industrial_source_profiles)")
        }

    assert first_version == SCHEMA_VERSION
    assert second_version == SCHEMA_VERSION
    assert second_objects == first_objects
    assert {"host", "port", "database_name", "order_by_enabled"}.issubset(profile_columns)
    assert {"password", "token", "credentials_json"}.isdisjoint(profile_columns)


def test_repository_profile_and_sync_run_lifecycle_redacts_sensitive_payloads(tmp_path):
    db_path = str(tmp_path / "industrial-cache.db")
    repository = IndustrialDataRepository(db_path)

    profile = repository.upsert_source_profile(
        profile_key="press-line",
        profile_name="Press Line",
        source_db_alias="plant_press",
        database_type="sqlite",
        host="localhost",
        port=0,
        database_name="press",
        source_object_name="events",
        allowed_columns=["reference", "serial", "reference", ""],
        timestamp_column="event_at",
        default_pagination_column="event_id",
        is_enabled=True,
        order_by_enabled=True,
    )
    updated = repository.upsert_source_profile(
        profile_key="press-line",
        profile_name="Press Line Updated",
        source_db_alias="plant_press_2",
        database_type="sqlite",
        host="localhost",
        port=1,
        database_name="press2",
        source_object_name="events_v2",
        allowed_columns=["serial", "station"],
        timestamp_column="created_at",
        default_pagination_column="id",
        is_enabled=False,
        order_by_enabled=False,
    )

    enabled_profiles = repository.list_source_profiles()
    all_profiles = repository.list_source_profiles(include_disabled=True)

    assert updated.id == profile.id
    assert enabled_profiles == []
    assert len(all_profiles) == 1
    assert all_profiles[0].profile_name == "Press Line Updated"
    assert all_profiles[0].source_db_alias == "plant_press_2"
    assert all_profiles[0].allowed_columns == ("serial", "station")
    assert all_profiles[0].is_enabled is False
    assert all_profiles[0].order_by_enabled is False

    sync_run_id = repository.create_sync_run(
        source_profile_id=profile.id,
        filters={
            "line": "L1",
            "password": "filter-secret",
            "nested": {"clientSecret": "nested-filter-secret"},
            "headers": [{"apiKey": "filter-api-key"}],
        },
        diagnostics={
            "phase": "fetch",
            "token": "diagnostic-token",
            "trace": [{"accessToken": "diagnostic-access-token"}],
        },
        started_at="2026-06-14T10:00:00Z",
    )
    repository.finish_sync_run(
        sync_run_id=sync_run_id,
        status="completed_with_warnings",
        row_count=2,
        error_summary="retry succeeded after password=finish-secret",
        diagnostics={
            "rows": 2,
            "refreshToken": "finish-refresh-token",
            "message": (
                "connect failed "
                "postgresql://operator:uri-secret@db.internal/plant "
                "token=diagnostic-message-token sql='SELECT * FROM raw_events'"
            ),
            "warnings": [{"credential": "finish-credential"}],
        },
        finished_at="2026-06-14T10:01:00Z",
    )

    latest = repository.latest_sync_run(source_profile_id=profile.id)
    assert latest is not None
    assert latest.id == sync_run_id
    assert latest.status == "completed_with_warnings"
    assert latest.row_count == 2
    assert latest.error_summary == "retry succeeded after password=<redacted>"
    assert latest.diagnostics["refreshToken"] == "<redacted>"
    assert latest.diagnostics["warnings"][0]["credential"] == "<redacted>"
    assert "<redacted>" in latest.diagnostics["message"]
    assert "uri-secret" not in latest.diagnostics["message"]
    assert "diagnostic-message-token" not in latest.diagnostics["message"]
    assert "raw_events" not in latest.diagnostics["message"]

    with sqlite3.connect(db_path) as conn:
        filters_json, diagnostics_json = conn.execute(
            """
            SELECT filters_json, diagnostics_json
            FROM industrial_sync_runs
            WHERE id = ?
            """,
            (sync_run_id,),
        ).fetchone()

    persisted_payload = f"{filters_json} {diagnostics_json}"
    assert "filter-secret" not in persisted_payload
    assert "nested-filter-secret" not in persisted_payload
    assert "filter-api-key" not in persisted_payload
    assert "diagnostic-token" not in persisted_payload
    assert "uri-secret" not in persisted_payload
    assert "diagnostic-message-token" not in persisted_payload
    assert "raw_events" not in persisted_payload
    assert "diagnostic-access-token" not in persisted_payload
    assert "finish-refresh-token" not in persisted_payload
    assert _load_json(filters_json)["password"] == "<redacted>"
    assert _load_json(filters_json)["nested"]["clientSecret"] == "<redacted>"
    assert _load_json(filters_json)["headers"][0]["apiKey"] == "<redacted>"
    assert _load_json(diagnostics_json)["refreshToken"] == "<redacted>"


def test_repository_record_upsert_replaces_dynamic_values_and_summarizes_counts(tmp_path):
    db_path = str(tmp_path / "industrial-cache.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly-line",
        profile_name="Assembly Line",
        source_db_alias="plant_assembly",
        database_type="sqlite",
        source_object_name="events",
    )
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)

    first_result = repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        sync_run_id=sync_run_id,
        rows=[
            {
                "source_record_key": "ROW-1",
                "process_timestamp": "2026-06-14T10:00:00Z",
                "reference": "REF-1",
                "station": "S1",
                "temperature_c": 22.5,
                "measurements": {"force_n": 120, "apiKey": "dynamic-api-key"},
                "password": "dynamic-password",
                "raw_record": {
                    "event_id": "ROW-1",
                    "nested": {"clientSecret": "raw-client-secret"},
                },
            },
            {
                "record_key": "ROW-2",
                "timestamp": "2026-06-14T10:01:00Z",
                "operator": "Operator A",
                "status": "pass",
                "custom_code": "A-2",
                "operator_note": (
                    "password=scalar-secret token=scalar-token "
                    "sql=SELECT * FROM raw_events WHERE token=sql-token"
                ),
                "payload": [{"accessToken": "payload-token", "value": 7}],
            },
        ],
    )
    second_result = repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        sync_run_id=sync_run_id,
        rows=[
            {
                "source_record_key": "ROW-1",
                "process_timestamp": "2026-06-14T10:05:00Z",
                "reference": "REF-1-UPDATED",
                "station": "S2",
                "temperature_c": 23.0,
            }
        ],
    )
    repository.finish_sync_run(sync_run_id=sync_run_id, status="succeeded", row_count=2)

    counts = repository.summarize_counts(source_profile_id=profile.id)

    assert first_result == {"processed": 2, "inserted": 2, "updated": 0, "value_rows": 5}
    assert second_result == {"processed": 1, "inserted": 0, "updated": 1, "value_rows": 1}
    assert counts.as_dict() == {
        "source_profiles": 1,
        "sync_runs": 1,
        "records": 2,
        "record_values": 4,
        "join_rules": 0,
        "link_candidates": 0,
    }

    with sqlite3.connect(db_path) as conn:
        row1 = conn.execute(
            """
            SELECT id, reference, station, raw_record_json
            FROM industrial_records
            WHERE source_profile_id = ? AND source_record_key = 'ROW-1'
            """,
            (profile.id,),
        ).fetchone()
        assert row1 is not None
        row1_id, reference, station, raw_record_json = row1
        row1_values = conn.execute(
            """
            SELECT field_name, field_value_text, field_value_json
            FROM industrial_record_values
            WHERE record_id = ?
            ORDER BY field_name
            """,
            (row1_id,),
        ).fetchall()
        row2_payload_json = conn.execute(
            """
            SELECT values_row.field_value_json
            FROM industrial_record_values values_row
            JOIN industrial_records records_row ON records_row.id = values_row.record_id
            WHERE records_row.source_profile_id = ?
              AND records_row.source_record_key = 'ROW-2'
              AND values_row.field_name = 'payload'
            """,
            (profile.id,),
        ).fetchone()[0]
        row2_operator_note = conn.execute(
            """
            SELECT values_row.field_value_text
            FROM industrial_record_values values_row
            JOIN industrial_records records_row ON records_row.id = values_row.record_id
            WHERE records_row.source_profile_id = ?
              AND records_row.source_record_key = 'ROW-2'
              AND values_row.field_name = 'operator_note'
            """,
            (profile.id,),
        ).fetchone()[0]
        row2_raw_record_json = conn.execute(
            """
            SELECT raw_record_json
            FROM industrial_records
            WHERE source_profile_id = ? AND source_record_key = 'ROW-2'
            """,
            (profile.id,),
        ).fetchone()[0]
        sensitive_dynamic_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM industrial_record_values values_row
            JOIN industrial_records records_row ON records_row.id = values_row.record_id
            WHERE records_row.source_profile_id = ?
              AND values_row.field_name IN ('password', 'token', 'clientSecret', 'apiKey')
            """,
            (profile.id,),
        ).fetchone()[0]

    assert reference == "REF-1-UPDATED"
    assert station == "S2"
    assert row1_values == [("temperature_c", "23.0", None)]
    assert "raw-client-secret" not in raw_record_json
    assert "payload-token" not in row2_payload_json
    assert "payload-token" not in row2_raw_record_json
    assert "scalar-secret" not in row2_operator_note
    assert "scalar-token" not in row2_operator_note
    assert "raw_events" not in row2_operator_note
    assert "sql-token" not in row2_operator_note
    assert "password=<redacted>" in row2_operator_note
    assert "token=<redacted>" in row2_operator_note
    assert "sql=<redacted>" in row2_operator_note
    assert _load_json(row2_raw_record_json)["payload"][0]["accessToken"] == "<redacted>"
    assert _load_json(row2_payload_json)[0]["accessToken"] == "<redacted>"
    assert sensitive_dynamic_count == 0

import json

import pytest

from modules.db import sqlite_connection_scope
from modules.industrial_data_repository import IndustrialDataRepository
from modules.industrial_data_schema import SCHEMA_VERSION, ensure_industrial_data_schema


def test_industrial_schema_creates_expected_tables_and_indexes(tmp_path):
    db_path = str(tmp_path / "industrial.db")
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
        schema_version = conn.execute(
            "SELECT value FROM app_schema WHERE key = 'industrial_schema_version'"
        ).fetchone()[0]
        profile_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(industrial_source_profiles)").fetchall()
        }

    assert {
        "app_schema",
        "industrial_source_profiles",
        "industrial_sync_runs",
        "industrial_records",
        "industrial_record_values",
        "industrial_join_rules",
        "industrial_link_candidates",
    }.issubset(tables)
    assert {
        "idx_industrial_source_profiles_enabled",
        "idx_industrial_sync_runs_profile_started",
        "idx_industrial_records_profile_timestamp",
        "idx_industrial_record_values_record_field",
    }.issubset(indexes)
    assert schema_version == SCHEMA_VERSION
    assert {"host", "port", "database_name", "order_by_enabled"}.issubset(profile_columns)
    assert "password" not in profile_columns
    assert "token" not in profile_columns
    assert "credentials_json" not in profile_columns


def test_source_profile_upsert_list_and_sync_run_lifecycle(tmp_path):
    db_path = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(db_path)

    profile = repository.upsert_source_profile(
        profile_key="line-a",
        profile_name="Line A",
        source_db_alias="plant_a",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="dbo.events",
        allowed_columns=["reference", "serial", "reference"],
        timestamp_column="event_at",
        default_pagination_column="event_id",
        is_enabled=True,
        order_by_enabled=False,
    )
    updated_profile = repository.upsert_source_profile(
        profile_key="line-a",
        profile_name="Line A Updated",
        source_db_alias="plant_a",
        database_type="mssql",
        host="mes2.example.invalid",
        port=1444,
        database_name="plantdb2",
        source_object_name="dbo.events",
        allowed_columns=["serial", "station"],
        timestamp_column="event_at",
        default_pagination_column="event_id",
        is_enabled=False,
        order_by_enabled=False,
    )

    profiles = repository.list_source_profiles(include_disabled=True)

    assert profile.id == updated_profile.id
    assert len(profiles) == 1
    assert profiles[0].profile_name == "Line A Updated"
    assert profiles[0].host == "mes2.example.invalid"
    assert profiles[0].port == 1444
    assert profiles[0].database_name == "plantdb2"
    assert profiles[0].allowed_columns == ("serial", "station")
    assert profiles[0].is_enabled is False
    assert profiles[0].order_by_enabled is False

    sync_run_id = repository.create_sync_run(
        source_profile_id=profile.id,
        filters={
            "station": "A1",
            "password": "super-secret",
            "nested": {
                "clientSecret": "nested-client-secret",
                "headers": [{"apiKey": "nested-api-key"}],
            },
        },
        oznak_version="0.2.0",
        oznak_commit="abc123",
        diagnostics={"token": "very-secret", "phase": "fetch"},
    )
    repository.finish_sync_run(
        sync_run_id=sync_run_id,
        status="completed_with_warnings",
        row_count=2,
        error_summary="secondary source timed out password=super-secret",
        diagnostics={
            "refreshToken": "another-secret",
            "rows": 2,
            "trace": [{"accessToken": "nested-access-token"}],
        },
    )

    with sqlite_connection_scope(db_path) as conn:
        row = conn.execute(
            """
            SELECT status, row_count, error_summary, filters_json, diagnostics_json
            FROM industrial_sync_runs
            WHERE id = ?
            """,
            (sync_run_id,),
        ).fetchone()

    assert row is not None
    status, row_count, error_summary, filters_json, diagnostics_json = row
    assert status == "completed_with_warnings"
    assert row_count == 2
    assert error_summary == "secondary source timed out password=<redacted>"
    assert "super-secret" not in (filters_json or "")
    assert "nested-client-secret" not in (filters_json or "")
    assert "nested-api-key" not in (filters_json or "")
    assert "very-secret" not in (diagnostics_json or "")
    assert "another-secret" not in (diagnostics_json or "")
    assert "nested-access-token" not in (diagnostics_json or "")
    assert json.loads(filters_json)["password"] == "<redacted>"
    assert json.loads(filters_json)["nested"]["clientSecret"] == "<redacted>"
    assert json.loads(filters_json)["nested"]["headers"][0]["apiKey"] == "<redacted>"
    assert json.loads(diagnostics_json)["refreshToken"] == "<redacted>"
    assert json.loads(diagnostics_json)["trace"][0]["accessToken"] == "<redacted>"


def test_finish_sync_run_rejects_non_terminal_running_status(tmp_path):
    db_path = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="line-running",
        profile_name="Line Running",
        source_db_alias="plant_running",
        database_type="mssql",
        source_object_name="dbo.events",
    )
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)

    with pytest.raises(ValueError, match="succeeded, completed_with_warnings, failed, cancelled"):
        repository.finish_sync_run(sync_run_id=sync_run_id, status="running", row_count=0)


def test_latest_sync_run_orders_filters_and_ignores_bad_diagnostics_json(tmp_path):
    db_path = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(db_path)
    line_a = repository.upsert_source_profile(
        profile_key="line-a",
        profile_name="Line A",
        source_db_alias="plant_a",
        database_type="mssql",
        source_object_name="dbo.events",
    )
    line_b = repository.upsert_source_profile(
        profile_key="line-b",
        profile_name="Line B",
        source_db_alias="plant_b",
        database_type="mssql",
        source_object_name="dbo.events",
    )
    older_run_id = repository.create_sync_run(source_profile_id=line_a.id)
    newer_run_id = repository.create_sync_run(source_profile_id=line_b.id)
    repository.finish_sync_run(
        sync_run_id=older_run_id,
        status="succeeded",
        row_count=3,
        diagnostics={"rows": 3},
    )
    repository.finish_sync_run(
        sync_run_id=newer_run_id,
        status="failed",
        row_count=0,
        error_summary="fetch failed password=secret",
        diagnostics={"warnings": ["timeout"]},
    )

    with sqlite_connection_scope(db_path) as conn:
        conn.execute(
            """
            UPDATE industrial_sync_runs
            SET finished_at = ?, diagnostics_json = ?
            WHERE id = ?
            """,
            ("2026-06-10T10:00:00Z", "{bad json", older_run_id),
        )
        conn.execute(
            """
            UPDATE industrial_sync_runs
            SET finished_at = ?
            WHERE id = ?
            """,
            ("2026-06-11T10:00:00Z", newer_run_id),
        )
        conn.commit()

    latest_any = repository.latest_sync_run()
    latest_line_a = repository.latest_sync_run(source_profile_id=line_a.id)

    assert latest_any is not None
    assert latest_any.id == newer_run_id
    assert latest_any.profile_key == "line-b"
    assert latest_any.error_summary == "fetch failed password=<redacted>"
    assert latest_line_a is not None
    assert latest_line_a.id == older_run_id
    assert latest_line_a.profile_key == "line-a"
    assert latest_line_a.diagnostics == {}
    assert repository.latest_sync_run(source_profile_id=999_999) is None


def test_schema_migrates_legacy_sync_run_status_constraint(tmp_path):
    db_path = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="line-legacy",
        profile_name="Line Legacy",
        source_db_alias="plant_legacy",
        database_type="mssql",
        source_object_name="dbo.events",
    )
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias="plant_legacy",
        sync_run_id=sync_run_id,
        rows=[
            {
                "source_record_key": "legacy-row",
                "raw_record": {"line": "legacy"},
                "values": {"length_mm": 10.5},
            }
        ],
    )
    repository.finish_sync_run(sync_run_id=sync_run_id, status="succeeded", row_count=1)

    with sqlite_connection_scope(db_path) as conn:
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'industrial_sync_runs'"
        ).fetchone()[0]
        legacy_table_sql = table_sql.replace("industrial_sync_runs", "industrial_sync_runs_legacy", 1)
        legacy_table_sql = legacy_table_sql.replace("'completed_with_warnings', ", "")
        assert legacy_table_sql != table_sql
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
        conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        conn.execute("DROP TABLE IF EXISTS industrial_sync_runs_legacy")
        conn.execute(legacy_table_sql)
        conn.execute(
            f"""
            INSERT INTO industrial_sync_runs_legacy ({column_list})
            SELECT {column_list}
            FROM industrial_sync_runs
            """
        )
        conn.execute("DROP TABLE industrial_sync_runs")
        conn.execute("ALTER TABLE industrial_sync_runs_legacy RENAME TO industrial_sync_runs")
        conn.commit()
        legacy_link = conn.execute(
            "SELECT sync_run_id FROM industrial_records WHERE source_record_key = 'legacy-row'"
        ).fetchone()[0]

    assert legacy_link == sync_run_id

    with sqlite_connection_scope(db_path) as conn:
        conn.execute("UPDATE app_schema SET value = value WHERE key = 'industrial_schema_version'")
        ensure_industrial_data_schema(db_path, connection=conn)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    warning_run_id = repository.create_sync_run(source_profile_id=profile.id)
    repository.finish_sync_run(
        sync_run_id=warning_run_id,
        status="completed_with_warnings",
        row_count=2,
    )

    with sqlite_connection_scope(db_path) as conn:
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'industrial_sync_runs'"
        ).fetchone()[0]
        warning_status = conn.execute(
            "SELECT status FROM industrial_sync_runs WHERE id = ?",
            (warning_run_id,),
        ).fetchone()[0]
        linked_sync_run_id = conn.execute(
            "SELECT sync_run_id FROM industrial_records WHERE source_record_key = 'legacy-row'"
        ).fetchone()[0]
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()

    assert "completed_with_warnings" in table_sql
    assert warning_status == "completed_with_warnings"
    assert linked_sync_run_id == sync_run_id
    assert foreign_key_errors == []


def test_upsert_records_and_summarize_counts_from_synthetic_rows(tmp_path):
    db_path = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="line-b",
        profile_name="Line B",
        source_db_alias="plant_b",
        database_type="mysql",
        source_object_name="factory.events",
        allowed_columns=["reference", "serial", "station"],
    )
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id, filters={"line": "L1"})

    first_pass = repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        sync_run_id=sync_run_id,
        rows=[
            {
                "source_record_key": "ROW-1",
                "process_timestamp": "2026-05-01T10:00:00Z",
                "reference": "REF-1",
                "part_name": "Housing",
                "serial": "SN-1",
                "station": "S1",
                "temperature_c": 22.5,
                "measurements": {"force": 8.4},
            },
            {
                "record_key": "ROW-2",
                "timestamp": "2026-05-01T10:01:00Z",
                "reference": "REF-2",
                "part_number": "PN-2",
                "operator": "Op-B",
                "batch": "LOT-9",
                "status": "pass",
                "custom_code": "X2",
                "quality_payload": {"apiKey": "dynamic-secret"},
                "token": "should-not-persist",
                "raw_record": {"event_id": "ROW-2", "nested": {"clientSecret": "raw-secret"}},
            },
        ],
    )
    second_pass = repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        sync_run_id=sync_run_id,
        rows=[
            {
                "source_record_key": "ROW-1",
                "process_timestamp": "2026-05-01T10:05:00Z",
                "reference": "REF-1-UPDATED",
                "station": "S2",
                "temperature_c": 23.0,
            }
        ],
    )
    repository.finish_sync_run(sync_run_id=sync_run_id, status="succeeded", row_count=2)

    counts = repository.summarize_counts(source_profile_id=profile.id)

    assert first_pass == {"processed": 2, "inserted": 2, "updated": 0, "value_rows": 4}
    assert second_pass == {"processed": 1, "inserted": 0, "updated": 1, "value_rows": 1}
    assert counts.source_profiles == 1
    assert counts.sync_runs == 1
    assert counts.records == 2
    assert counts.record_values == 3
    assert counts.join_rules == 0
    assert counts.link_candidates == 0

    with sqlite_connection_scope(db_path) as conn:
        updated_record = conn.execute(
            """
            SELECT reference, station, raw_record_json
            FROM industrial_records
            WHERE source_profile_id = ? AND source_record_key = 'ROW-1'
            """,
            (profile.id,),
        ).fetchone()
        token_values = conn.execute(
            """
            SELECT COUNT(*)
            FROM industrial_record_values values_row
            JOIN industrial_records records_row ON records_row.id = values_row.record_id
            WHERE records_row.source_profile_id = ? AND values_row.field_name = 'token'
            """,
            (profile.id,),
        ).fetchone()[0]
        quality_payload = conn.execute(
            """
            SELECT values_row.field_value_json
            FROM industrial_record_values values_row
            JOIN industrial_records records_row ON records_row.id = values_row.record_id
            WHERE records_row.source_profile_id = ?
              AND records_row.source_record_key = 'ROW-2'
              AND values_row.field_name = 'quality_payload'
            """,
            (profile.id,),
        ).fetchone()[0]
        stale_measurements = conn.execute(
            """
            SELECT COUNT(*)
            FROM industrial_record_values values_row
            JOIN industrial_records records_row ON records_row.id = values_row.record_id
            WHERE records_row.source_profile_id = ?
              AND records_row.source_record_key = 'ROW-1'
              AND values_row.field_name = 'measurements'
            """,
            (profile.id,),
        ).fetchone()[0]
        row1_dynamic_fields = {
            row[0]
            for row in conn.execute(
                """
                SELECT values_row.field_name
                FROM industrial_record_values values_row
                JOIN industrial_records records_row ON records_row.id = values_row.record_id
                WHERE records_row.source_profile_id = ?
                  AND records_row.source_record_key = 'ROW-1'
                """,
                (profile.id,),
            ).fetchall()
        }
        row2_raw_record_json = conn.execute(
            """
            SELECT raw_record_json
            FROM industrial_records
            WHERE source_profile_id = ? AND source_record_key = 'ROW-2'
            """,
            (profile.id,),
        ).fetchone()[0]

    assert updated_record is not None
    reference, station, raw_record_json = updated_record
    assert reference == "REF-1-UPDATED"
    assert station == "S2"
    assert "should-not-persist" not in (raw_record_json or "")
    assert "raw-secret" not in (row2_raw_record_json or "")
    assert json.loads(row2_raw_record_json)["nested"]["clientSecret"] == "<redacted>"
    assert "dynamic-secret" not in (quality_payload or "")
    assert json.loads(quality_payload)["apiKey"] == "<redacted>"
    assert token_values == 0
    assert stale_measurements == 0
    assert row1_dynamic_fields == {"temperature_c"}

import json
import sqlite3

import pytest

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.reports.db import sqlite_connection_scope


def _profile(repository: IndustrialDataRepository):
    return repository.upsert_source_profile(
        profile_key="line-a",
        profile_name="Line A",
        source_db_alias="plant_a",
        database_type="mssql",
        source_object_name="dbo.events",
    )


def _stage(repository, profile, sync_run_id, *, key="ROW-1"):
    return repository.stage_industrial_records_from_rows(
        sync_run_id=sync_run_id,
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=(
            {
                "source_record_key": key,
                "reference": "REF-1",
                "password": "raw-secret",
                "raw_record": {"record_id": key, "token": "raw-token"},
            },
        ),
    )


def test_streamed_sync_stays_invisible_until_atomic_terminal_promotion(tmp_path):
    db_path = str(tmp_path / "staging.db")
    repository = IndustrialDataRepository(db_path)
    profile = _profile(repository)
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)

    staged = _stage(repository, profile, sync_run_id)

    assert staged == {"processed": 1, "staged": 1}
    assert repository.summarize_counts(source_profile_id=profile.id).records == 0
    with sqlite_connection_scope(db_path) as connection:
        staged_payload = connection.execute(
            "SELECT row_json FROM industrial_sync_staging_records"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT status FROM industrial_sync_runs WHERE id = ?", (sync_run_id,)
        ).fetchone()[0] == "running"
    assert "raw-secret" not in staged_payload
    assert "raw-token" not in staged_payload

    summary = repository.promote_staged_industrial_records(
        sync_run_id=sync_run_id,
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        status="succeeded",
        row_count=1,
        diagnostics={"password": "raw-secret", "stage": "mapped"},
        finished_at="2026-07-09T10:00:00Z",
    )

    assert summary["inserted"] == 1
    assert repository.summarize_counts(source_profile_id=profile.id).records == 1
    with sqlite_connection_scope(db_path) as connection:
        run = connection.execute(
            """
            SELECT status, row_count, finished_at, diagnostics_json
            FROM industrial_sync_runs WHERE id = ?
            """,
            (sync_run_id,),
        ).fetchone()
        staging_count = connection.execute(
            "SELECT COUNT(*) FROM industrial_sync_staging_records"
        ).fetchone()[0]
    assert run[:3] == ("succeeded", 1, "2026-07-09T10:00:00.000000Z")
    assert json.loads(run[3]) == {"password": "<redacted>", "stage": "mapped"}
    assert staging_count == 0


def test_terminal_status_failure_rolls_back_promoted_rows_and_staging_delete(tmp_path):
    db_path = str(tmp_path / "promotion-rollback.db")
    repository = IndustrialDataRepository(db_path)
    profile = _profile(repository)
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)
    _stage(repository, profile, sync_run_id)
    with sqlite_connection_scope(db_path) as connection:
        with connection:
            connection.execute(
                f"""
                CREATE TRIGGER fail_streamed_terminal_status
                BEFORE UPDATE OF status ON industrial_sync_runs
                WHEN NEW.id = {int(sync_run_id)} AND NEW.status = 'succeeded'
                BEGIN
                    SELECT RAISE(ABORT, 'injected terminal status failure');
                END
                """
            )

    with pytest.raises(sqlite3.IntegrityError, match="injected terminal status failure"):
        repository.promote_staged_industrial_records(
            sync_run_id=sync_run_id,
            source_profile_id=profile.id,
            source_db_alias=profile.source_db_alias,
            status="succeeded",
            row_count=1,
        )

    with sqlite_connection_scope(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM industrial_records").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM industrial_sync_staging_records"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT status FROM industrial_sync_runs WHERE id = ?", (sync_run_id,)
        ).fetchone()[0] == "running"


def test_direct_sync_terminal_failure_rolls_back_upserted_rows(tmp_path):
    db_path = str(tmp_path / "direct-rollback.db")
    repository = IndustrialDataRepository(db_path)
    profile = _profile(repository)
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)
    with sqlite_connection_scope(db_path) as connection:
        with connection:
            connection.execute(
                f"""
                CREATE TRIGGER fail_direct_terminal_status
                BEFORE UPDATE OF status ON industrial_sync_runs
                WHEN NEW.id = {int(sync_run_id)} AND NEW.status = 'succeeded'
                BEGIN
                    SELECT RAISE(ABORT, 'injected direct terminal status failure');
                END
                """
            )

    with pytest.raises(sqlite3.IntegrityError, match="injected direct terminal status failure"):
        repository.commit_direct_industrial_sync(
            sync_run_id=sync_run_id,
            source_profile_id=profile.id,
            source_db_alias=profile.source_db_alias,
            rows=({"source_record_key": "ROW-1", "reference": "REF-1"},),
            status="succeeded",
            row_count=1,
        )

    with sqlite_connection_scope(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM industrial_records").fetchone()[0] == 0
        assert connection.execute(
            "SELECT status FROM industrial_sync_runs WHERE id = ?", (sync_run_id,)
        ).fetchone()[0] == "running"


def test_explicit_startup_recovery_preserves_recent_staging_from_another_process(tmp_path):
    db_path = str(tmp_path / "startup-recovery.db")
    repository = IndustrialDataRepository(db_path)
    profile = _profile(repository)
    orphaned_run_id = repository.create_sync_run(
        source_profile_id=profile.id,
        started_at="2026-07-09T08:00:00Z",
    )
    live_run_id = repository.create_sync_run(
        source_profile_id=profile.id,
        started_at="2026-07-09T09:59:00Z",
    )
    unstaged_run_id = repository.create_sync_run(
        source_profile_id=profile.id,
        started_at="2026-07-09T08:00:00Z",
    )
    _stage(repository, profile, orphaned_run_id)
    _stage(repository, profile, live_run_id, key="ROW-LIVE")

    with sqlite_connection_scope(db_path) as connection:
        with connection:
            connection.executemany(
                "UPDATE industrial_sync_runs SET heartbeat_at = ? WHERE id = ?",
                (
                    ("2026-07-09T08:00:00.000000Z", orphaned_run_id),
                    ("2026-07-09T09:59:30.000000Z", live_run_id),
                ),
            )

    startup_repository = IndustrialDataRepository(db_path)
    recovered = startup_repository.recover_abandoned_sync_staging_at_startup(
        recovered_at="2026-07-09T10:00:00Z",
        stale_after_seconds=300,
    )

    assert recovered == {"runs_failed": 1, "rows_discarded": 1}
    with sqlite_connection_scope(db_path) as connection:
        statuses = dict(connection.execute("SELECT id, status FROM industrial_sync_runs"))
        error_summary = connection.execute(
            "SELECT error_summary FROM industrial_sync_runs WHERE id = ?", (orphaned_run_id,)
        ).fetchone()[0]
        staged_run_ids = [
            row[0]
            for row in connection.execute(
                "SELECT sync_run_id FROM industrial_sync_staging_records ORDER BY sync_run_id"
            )
        ]
    assert statuses[orphaned_run_id] == "failed"
    assert statuses[live_run_id] == "running"
    assert statuses[unstaged_run_id] == "running"
    assert error_summary == "Recovered abandoned streamed sync during startup."
    assert staged_run_ids == [live_run_id]


def test_sync_run_heartbeat_migration_is_idempotent_for_existing_databases(tmp_path):
    db_path = str(tmp_path / "legacy-sync-run.db")
    with sqlite_connection_scope(db_path) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE industrial_sync_runs (
                    id INTEGER PRIMARY KEY,
                    source_profile_id INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'running', 'succeeded', 'completed_with_warnings',
                            'failed', 'cancelled'
                        )
                    ),
                    row_count INTEGER NOT NULL DEFAULT 0,
                    error_summary TEXT,
                    filters_json TEXT,
                    oznak_version TEXT,
                    oznak_commit TEXT,
                    diagnostics_json TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO industrial_sync_runs (
                    source_profile_id, started_at, status
                )
                VALUES (1, '2026-07-09T08:00:00Z', 'running')
                """
            )

        ensure_industrial_data_schema(db_path, connection=connection)
        ensure_industrial_data_schema(db_path, connection=connection)
        heartbeat_columns = [
            row[1]
            for row in connection.execute("PRAGMA table_info(industrial_sync_runs)")
            if row[1] == "heartbeat_at"
        ]
        heartbeat_at = connection.execute(
            "SELECT heartbeat_at FROM industrial_sync_runs WHERE id = 1"
        ).fetchone()[0]

    assert heartbeat_columns == ["heartbeat_at"]
    assert heartbeat_at == "2026-07-09T08:00:00.000000Z"

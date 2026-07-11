"""Reusable cached-production fixtures for industrial analytics tests."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import sqlite3
from pathlib import Path

from modules.industrial_data_repository import IndustrialDataRepository


def seed_production_analytics_cache(
    db_path: str | Path,
    *,
    include_report_tables: bool = False,
) -> dict[str, object]:
    """Seed a representative Oznak cache without requiring CMM measurement tables."""

    database = str(db_path)
    repository = IndustrialDataRepository(database)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.production_events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        allowed_columns=(
            "event_id",
            "event_at",
            "reference",
            "station",
            "line",
            "process_status",
            "cycle_time_s",
            "temperature_c",
            "force_n",
            "pressure_bar",
            "cavity",
            "defect_count",
        ),
        timestamp_column="event_at",
        default_pagination_column="event_id",
    )
    sync_run_id = repository.create_sync_run(
        source_profile_id=profile.id,
        filters={"fixture": "production_analytics"},
        oznak_version="fixture",
    )

    start = datetime(2026, 5, 10, 6, 0, tzinfo=timezone.utc)
    rows = []
    references = ("REF-100", "REF-200", "REF-300", "REF-400")
    for index in range(16):
        timestamp = start + timedelta(hours=index * 7)
        reference = references[index % len(references)]
        rows.append(
            {
                "source_record_key": f"EVT-{index + 1:03d}",
                "process_timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                "reference": reference,
                "part_number": "PN-10" if index < 8 else "PN-20",
                "part_name": "Housing" if index < 8 else "Cover",
                "revision": "A" if index % 2 == 0 else "B",
                "serial": f"SN-{index + 1:03d}",
                "batch_lot": f"LOT-{1 + index // 4}",
                "work_order": f"WO-{1 + index // 8}",
                "station": "S1" if index % 2 == 0 else "S2",
                "line": "L1" if index % 3 else "L2",
                "operator_name": "Operator A" if index % 2 == 0 else "Operator B",
                "process_status": "OK" if index % 5 else "NOK",
                "cycle_time_s": 35.0 + index * 0.75,
                "temperature_c": 22.0 + index * 0.2,
                "force_n": 1000.0 + index * 8.5,
                "pressure_bar": 4.0 + (index % 4) * 0.15,
                "cavity": 1 + (index % 4),
                "defect_count": 1 if index % 5 == 0 else 0,
                "fixture_text_code": "alpha" if index % 2 == 0 else "beta",
                "mostly_numeric_value": "not-a-number" if index == 3 else str(50 + index),
                "raw_record": {"event_id": f"EVT-{index + 1:03d}", "reference": reference},
            }
        )

    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        sync_run_id=sync_run_id,
        rows=rows,
    )
    repository.finish_sync_run(sync_run_id=sync_run_id, status="succeeded", row_count=len(rows))

    if include_report_tables:
        _seed_minimal_report_tables(database, profile_id=profile.id)

    return {
        "profile": profile,
        "sync_run_id": sync_run_id,
        "row_count": len(rows),
        "references": references,
    }


def _seed_minimal_report_tables(database: str, *, profile_id: int) -> None:
    """Create minimal report/link tables for optional linked-production tests."""

    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS parsed_reports (
                id INTEGER PRIMARY KEY,
                file_name TEXT,
                reference TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_metadata (
                report_id INTEGER PRIMARY KEY,
                reference TEXT,
                part_number TEXT,
                revision TEXT
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO parsed_reports(id, file_name, reference) VALUES (1, ?, ?)",
            ("fixture.pdf", "REF-100"),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO report_metadata(report_id, reference, part_number, revision)
            VALUES (1, ?, ?, ?)
            """,
            ("REF-100", "PN-10", "A"),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO industrial_join_rules (
                rule_key,
                rule_name,
                report_field,
                industrial_field,
                match_mode,
                priority,
                is_enabled,
                created_at,
                updated_at
            )
            VALUES (
                'fixture_reference',
                'Fixture reference',
                'reference',
                'reference',
                'exact',
                1,
                1,
                '2026-05-10T00:00:00Z',
                '2026-05-10T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO industrial_link_candidates (
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
                1,
                NULL,
                records.id,
                rules.id,
                1.0,
                'accepted',
                'fixture link',
                '2026-05-10T00:00:00Z',
                '2026-05-10T00:00:00Z'
            FROM industrial_records records
            CROSS JOIN industrial_join_rules rules
            WHERE records.source_profile_id = ?
              AND records.reference = 'REF-100'
            LIMIT 1
            """,
            (profile_id,),
        )

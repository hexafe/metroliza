from __future__ import annotations

import json
from types import SimpleNamespace

from modules import industrial_workers
from modules.db import sqlite_connection_scope
from modules.industrial_data_repository import IndustrialDataRepository
from modules.industrial_source_config import build_source_profile
from modules.industrial_workers import IndustrialOznakAccessCheckThread, IndustrialOznakSyncThread
from modules.industrial_workflow_state import IndustrialFetchState, IndustrialQueryFilter
from modules.oznak_adapter import OznakAdapterFetchResult, OznakAdapterStatus


def _capture_signal(signal, values: list[object]) -> None:
    if hasattr(signal, "connect"):
        signal.connect(values.append)
    else:
        signal.emit = values.append


def test_access_check_thread_uses_bounded_fetch_without_local_repository(monkeypatch):
    profile = build_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "reference"),
        default_pagination_column="event_id",
    )
    status = OznakAdapterStatus(available=True, version="0.1.0", fetch_available=True)
    result = OznakAdapterFetchResult(
        status=status,
        records=({"source_primary_key": "ROW-1", "raw_record": {"event_id": "ROW-1"}},),
        row_count=1,
        implemented=True,
        diagnostics={"stage": "mapped"},
    )
    fetch_kwargs = {}

    monkeypatch.setattr(industrial_workers, "get_oznak_adapter_status", lambda: status)
    monkeypatch.setattr(
        industrial_workers,
        "create_oznak_cancellation_token",
        lambda: SimpleNamespace(cancel=lambda: None),
    )

    def fake_fetch(*args, **kwargs):
        fetch_kwargs.update(kwargs)
        return result

    monkeypatch.setattr(industrial_workers, "fetch_oznak_records_for_source_profile", fake_fetch)
    monkeypatch.setattr(
        industrial_workers,
        "IndustrialDataRepository",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("repository must not be created")),
    )

    thread = IndustrialOznakAccessCheckThread(
        profile=profile,
        username="operator",
        password="secret-password",
        timeout_seconds=30,
    )
    emitted = []
    _capture_signal(thread.result_ready, emitted)

    thread.run()

    assert emitted
    assert emitted[0]["test_only"] is True
    assert emitted[0]["access_check_method"] == "bounded_fetch"
    assert emitted[0]["status"] == "succeeded"
    assert emitted[0]["row_count"] == 1
    assert emitted[0]["upsert_summary"] == {}
    assert emitted[0]["link_summary"] is None
    assert fetch_kwargs["limit"] == 1
    assert fetch_kwargs["reference_filter_column"] is None
    assert fetch_kwargs["reference_values"] == ()


def test_access_check_thread_forwards_explicit_reference_filter(monkeypatch):
    profile = build_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "serial_number"),
        default_pagination_column="event_id",
    )
    status = OznakAdapterStatus(available=True, version="0.1.0", fetch_available=True)
    result = OznakAdapterFetchResult(
        status=status,
        records=({"source_primary_key": "ROW-1", "raw_record": {"event_id": "ROW-1"}},),
        row_count=1,
        implemented=True,
        diagnostics={"stage": "mapped"},
    )
    fetch_kwargs = {}

    monkeypatch.setattr(industrial_workers, "get_oznak_adapter_status", lambda: status)
    monkeypatch.setattr(industrial_workers, "create_oznak_cancellation_token", lambda: None)

    def fake_fetch(*args, **kwargs):
        fetch_kwargs.update(kwargs)
        return result

    monkeypatch.setattr(industrial_workers, "fetch_oznak_records_for_source_profile", fake_fetch)

    thread = IndustrialOznakAccessCheckThread(
        profile=profile,
        username="operator",
        password="secret-password",
        timeout_seconds=30,
        reference_filter_column="serial_number",
        reference_values=("SN-1",),
    )
    emitted = []
    _capture_signal(thread.result_ready, emitted)

    thread.run()

    assert emitted[0]["status"] == "succeeded"
    assert fetch_kwargs["reference_filter_column"] == "serial_number"
    assert fetch_kwargs["reference_values"] == ("SN-1",)


def test_access_check_thread_redacts_failed_error(monkeypatch):
    profile = build_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        default_pagination_column="event_id",
    )
    status = OznakAdapterStatus(available=True, version="0.1.0", fetch_available=True)
    result = OznakAdapterFetchResult(
        status=status,
        records=(),
        row_count=0,
        implemented=True,
        diagnostics={"stage": "fetch_call"},
        error="database rejected password=super-secret",
    )

    monkeypatch.setattr(industrial_workers, "get_oznak_adapter_status", lambda: status)
    monkeypatch.setattr(industrial_workers, "create_oznak_cancellation_token", lambda: None)
    monkeypatch.setattr(
        industrial_workers,
        "fetch_oznak_records_for_source_profile",
        lambda *args, **kwargs: result,
    )

    thread = IndustrialOznakAccessCheckThread(
        profile=profile,
        username="operator",
        password="secret-password",
        timeout_seconds=30,
    )
    emitted = []
    _capture_signal(thread.result_ready, emitted)

    thread.run()

    assert emitted[0]["status"] == "failed"
    assert emitted[0]["error"] == "database rejected password=<redacted>"


def test_sync_thread_deduplicates_reference_query_filter_before_fetch_and_metadata(
    monkeypatch,
    tmp_path,
):
    db_path = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        allowed_columns=("event_id", "reference", "station"),
        default_pagination_column="event_id",
    )
    status = OznakAdapterStatus(available=True, version="0.1.0", fetch_available=True)
    result = OznakAdapterFetchResult(
        status=status,
        records=(
            {
                "source_primary_key": "ROW-1",
                "reference": "REF-1",
                "station": "S1",
                "raw_record": {"event_id": "ROW-1", "reference": "REF-1", "station": "S1"},
            },
        ),
        row_count=1,
        implemented=True,
        diagnostics={"stage": "mapped"},
    )
    fetch_kwargs = {}

    monkeypatch.setattr(industrial_workers, "get_oznak_adapter_status", lambda: status)
    monkeypatch.setattr(industrial_workers, "create_oznak_cancellation_token", lambda: None)
    monkeypatch.setattr(
        industrial_workers,
        "materialize_industrial_report_links",
        lambda _db: SimpleNamespace(accepted_links=0, ambiguous_reports=0, unmatched_reports=0),
    )

    def fake_fetch(*args, **kwargs):
        fetch_kwargs.update(kwargs)
        return result

    monkeypatch.setattr(industrial_workers, "fetch_oznak_records_for_source_profile", fake_fetch)
    thread = IndustrialOznakSyncThread(
        db_file=db_path,
        profile=profile,
        username="operator",
        password="secret-password",
        limit=50,
        timeout_seconds=30,
        reference_filter_column="reference",
        reference_values=("REF-1",),
        test_only=False,
        fetch_state=IndustrialFetchState(
            filters=(
                IndustrialQueryFilter("reference", "IN", ("REF-1",)),
                IndustrialQueryFilter("station", "=", ("S1",)),
            ),
            limit_rows=50,
        ),
    )
    emitted = []
    _capture_signal(thread.result_ready, emitted)

    thread.run()

    assert emitted[0]["status"] == "succeeded"
    assert emitted[0]["upsert_summary"]["processed"] == 1
    assert emitted[0]["cache_summary"]["records"] == 1
    assert emitted[0]["cache_summary"]["sync_runs"] == 1
    assert fetch_kwargs["query_filters"] == (IndustrialQueryFilter("station", "=", ("S1",)),)
    with sqlite_connection_scope(db_path) as conn:
        filters_json = conn.execute("SELECT filters_json FROM industrial_sync_runs").fetchone()[0]
    filters_payload = json.loads(filters_json)
    assert filters_payload["query_filters"] == [
        {"column": "station", "operator": "=", "value_count": 1}
    ]
    assert filters_payload["deduplicated_reference_query_filter_count"] == 1

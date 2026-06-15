from types import SimpleNamespace

from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_credentials import IndustrialStoredCredentials
from metroliza.industrial.realtime.db_poller import SourceReadRequest, build_bounded_poll_query
from metroliza.industrial.realtime.oznak_source_adapter import OznakRealtimeSourceAdapter
from metroliza.industrial.realtime.stream_config import RealtimePollConfig


def _profile(db_path: str):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="line_a_mes",
        database_type="mssql",
        source_object_name="dbo.events",
        allowed_columns=("event_id", "process_timestamp", "record_id", "cycle_time_s"),
        timestamp_column="process_timestamp",
        default_pagination_column="event_id",
    )


def _config(profile_id: int):
    return RealtimePollConfig(
        source_profile_id=profile_id,
        stream_key="line_a",
        cursor_column="event_id",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        signal_keys=("cycle_time",),
        signal_columns={"cycle_time": "cycle_time_s"},
        context_fields=(),
    )


def test_oznak_realtime_source_adapter_passes_parameterized_query(monkeypatch, tmp_path):
    db_path = str(tmp_path / "adapter.db")
    profile = _profile(db_path)
    config = _config(profile.id)
    query = build_bounded_poll_query(profile=profile, config=config)
    calls = []

    def fake_fetch(profile_arg, **kwargs):
        calls.append((profile_arg, kwargs))
        return SimpleNamespace(
            records=({"event_id": 1, "record_id": "R1", "process_timestamp": "2026-06-15T10:00:00Z"},),
            diagnostics={"row_count": 1},
            row_count=1,
            error=None,
        )

    monkeypatch.setattr(
        "metroliza.industrial.realtime.oznak_source_adapter.fetch_oznak_records_for_source_sql",
        fake_fetch,
    )
    adapter = OznakRealtimeSourceAdapter(
        credential_loader=lambda _profile_key: IndustrialStoredCredentials(
            username="user",
            password="secret",
            source="test",
        )
    )

    result = adapter.fetch_rows(SourceReadRequest(profile=profile, config=config, query=query))

    assert result.error is None
    assert len(result.rows) == 1
    assert calls[0][0] == profile
    assert calls[0][1]["sql_text"] == query.sql_text
    assert calls[0][1]["parameters"] == query.parameters
    assert calls[0][1]["limit"] == query.limit
    assert calls[0][1]["timeout_seconds"] == query.timeout_seconds


def test_oznak_realtime_source_adapter_reports_missing_credentials(tmp_path):
    db_path = str(tmp_path / "adapter.db")
    profile = _profile(db_path)
    config = _config(profile.id)
    query = build_bounded_poll_query(profile=profile, config=config)
    adapter = OznakRealtimeSourceAdapter(
        credential_loader=lambda _profile_key: IndustrialStoredCredentials()
    )

    result = adapter.fetch_rows(SourceReadRequest(profile=profile, config=config, query=query))

    assert result.rows == ()
    assert "No saved industrial database credentials" in result.error
    assert result.diagnostics["credentials_source"] == "missing"

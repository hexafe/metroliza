import pytest

from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.db_poller import (
    build_bounded_poll_query,
    safe_query_diagnostics,
)
from metroliza.industrial.realtime.stream_config import (
    RealtimePollConfig,
    RealtimeStreamConfigError,
)
from metroliza.industrial.realtime.stream_contracts import StreamOffset


def _profile(db_path: str, *, allowed_columns=None):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
        allowed_columns=allowed_columns,
    )


def _config(profile_id: int):
    return RealtimePollConfig(
        source_profile_id=profile_id,
        stream_key="cycle_time",
        cursor_column="event_id",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        signal_keys=("cycle_time",),
        signal_columns={"cycle_time": "cycle_time_s"},
        context_fields=("station",),
        chunk_size=250,
        max_catchup_rows_per_cycle=1_000,
    )


def test_bounded_poll_query_uses_cursor_limit_order_and_safe_diagnostics(tmp_path):
    db_path = str(tmp_path / "poller.db")
    profile = _profile(
        db_path,
        allowed_columns=("event_id", "process_timestamp", "record_id", "cycle_time_s", "station"),
    )
    config = _config(profile.id)
    offset = StreamOffset(
        source_profile_id=profile.id,
        stream_key="cycle_time",
        cursor_column="event_id",
        cursor_value="500",
    )

    query = build_bounded_poll_query(profile=profile, config=config, offset=offset)
    diagnostics = safe_query_diagnostics(query)

    assert 'FROM "dbo"."events"' in query.sql_text
    assert 'WHERE "event_id" > ?' in query.sql_text
    assert 'ORDER BY "event_id" ASC LIMIT ?' in query.sql_text
    assert query.parameters == ("500", 250)
    assert query.limit == 250
    assert diagnostics["sql_hash"] == query.sql_hash
    assert "sql_text" not in diagnostics
    assert "SELECT" not in str(diagnostics)


def test_bounded_poll_query_rejects_columns_outside_source_allowlist(tmp_path):
    db_path = str(tmp_path / "poller.db")
    profile = _profile(
        db_path,
        allowed_columns=("event_id", "process_timestamp", "record_id"),
    )

    with pytest.raises(RealtimeStreamConfigError) as exc:
        build_bounded_poll_query(profile=profile, config=_config(profile.id))

    assert "cycle_time_s" in str(exc.value)

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

    assert query.sql_text.startswith("SELECT TOP (?)")
    assert 'FROM "dbo"."events"' in query.sql_text
    assert 'WHERE "event_id" >= ?' in query.sql_text
    assert 'ORDER BY "event_id" ASC, "record_id" ASC' in query.sql_text
    assert "LIMIT" not in query.sql_text
    assert query.parameters == (250, "500")
    assert query.limit == 250
    assert diagnostics["summary"]["dialect"] == "mssql"
    assert diagnostics["summary"]["cursor_resume_mode"] == "cursor_reseed"
    assert diagnostics["sql_hash"] == query.sql_hash
    assert "sql_text" not in diagnostics
    assert "SELECT" not in str(diagnostics)


def test_bounded_poll_query_uses_limit_placeholder_for_mysql_and_sqlite(tmp_path):
    db_path = str(tmp_path / "poller.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mysql",
        source_object_name="events",
        allowed_columns=("event_id", "process_timestamp", "record_id", "cycle_time_s", "station"),
    )

    query = build_bounded_poll_query(
        profile=profile,
        config=_config(profile.id),
        offset=StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="500",
        ),
    )

    assert 'WHERE "event_id" >= ?' in query.sql_text
    assert 'ORDER BY "event_id" ASC, "record_id" ASC LIMIT ?' in query.sql_text
    assert query.parameters == ("500", 250)
    assert query.summary["dialect"] == "mysql"
    assert query.summary["cursor_resume_mode"] == "cursor_reseed"


def test_bounded_poll_query_uses_record_key_tie_breaker_for_duplicate_cursors(tmp_path):
    db_path = str(tmp_path / "poller.db")
    profile = _profile(
        db_path,
        allowed_columns=("event_id", "process_timestamp", "record_id", "cycle_time_s", "station"),
    )

    query = build_bounded_poll_query(
        profile=profile,
        config=_config(profile.id),
        offset=StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="500",
            cursor_tie_breaker_column="record_id",
            cursor_tie_breaker_value="ROW-9",
        ),
    )

    assert (
        'WHERE ("event_id" > ? OR ("event_id" = ? AND "record_id" > ?))'
        in query.sql_text
    )
    assert 'ORDER BY "event_id" ASC, "record_id" ASC' in query.sql_text
    assert query.parameters == (250, "500", "500", "ROW-9")
    assert query.summary["cursor_tie_breaker_column"] == "record_id"
    assert query.summary["cursor_resume_mode"] == "composite"


def test_bounded_poll_query_uses_tuple_comparison_for_sqlite_composite_cursor(tmp_path):
    db_path = str(tmp_path / "poller.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="sqlite",
        source_object_name="events",
        allowed_columns=("event_id", "process_timestamp", "record_id", "cycle_time_s", "station"),
    )

    query = build_bounded_poll_query(
        profile=profile,
        config=_config(profile.id),
        offset=StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="500",
            cursor_tie_breaker_column="record_id",
            cursor_tie_breaker_value="ROW-9",
        ),
    )

    assert 'WHERE ("event_id", "record_id") > (?, ?)' in query.sql_text
    assert 'ORDER BY "event_id" ASC, "record_id" ASC LIMIT ?' in query.sql_text
    assert query.parameters == ("500", "ROW-9", 250)
    assert query.summary["dialect"] == "sqlite"
    assert query.summary["cursor_resume_mode"] == "composite"


def test_bounded_poll_query_rejects_stale_record_key_tie_breaker(tmp_path):
    db_path = str(tmp_path / "poller.db")
    profile = _profile(
        db_path,
        allowed_columns=("event_id", "process_timestamp", "record_id", "cycle_time_s", "station"),
    )

    with pytest.raises(RealtimeStreamConfigError) as exc:
        build_bounded_poll_query(
            profile=profile,
            config=_config(profile.id),
            offset=StreamOffset(
                source_profile_id=profile.id,
                stream_key="cycle_time",
                cursor_column="event_id",
                cursor_value="500",
                cursor_tie_breaker_column="legacy_record_id",
                cursor_tie_breaker_value="ROW-9",
            ),
        )

    assert "tie-breaker column 'legacy_record_id'" in str(exc.value)
    assert "Reset or reseed" in str(exc.value)


def test_bounded_poll_query_rejects_columns_outside_source_allowlist(tmp_path):
    db_path = str(tmp_path / "poller.db")
    profile = _profile(
        db_path,
        allowed_columns=("event_id", "process_timestamp", "record_id"),
    )

    with pytest.raises(RealtimeStreamConfigError) as exc:
        build_bounded_poll_query(profile=profile, config=_config(profile.id))

    assert "cycle_time_s" in str(exc.value)

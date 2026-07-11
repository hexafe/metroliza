from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.db_poller import SourceReadResult
from metroliza.industrial.realtime.source_runtime import RealtimeSourceRuntime
from metroliza.industrial.realtime.stream_config import RealtimePollConfig


class EmptyAdapter:
    def __init__(self):
        self.requests = []

    def fetch_rows(self, request):
        self.requests.append(request)
        return SourceReadResult(rows=())


def _config(profile_id: int, *, enabled: bool = True):
    return RealtimePollConfig(
        source_profile_id=profile_id,
        stream_key="cycle_time",
        cursor_column="event_id",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        signal_keys=("cycle_time",),
        signal_columns={"cycle_time": "cycle_time_s"},
        enabled=enabled,
    )


def test_realtime_source_runtime_skips_disabled_streams_and_reports_missing_profiles(tmp_path):
    db_path = str(tmp_path / "runtime.db")
    profile = IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        allowed_columns=(
            "event_id",
            "process_timestamp",
            "record_id",
            "cycle_time_s",
            "reference",
            "part_number",
            "revision",
            "station",
            "line",
            "work_order",
            "batch_lot",
        ),
    )
    runtime = RealtimeSourceRuntime(
        database=db_path,
        configs=(
            _config(profile.id),
            _config(999),
            _config(profile.id, enabled=False),
        ),
        adapter=EmptyAdapter(),
    )

    statuses = runtime.list_statuses()
    results = runtime.poll_once()

    assert len(statuses) == 3
    assert len(results) == 2
    assert results[0].status == "completed"
    assert results[0].diagnostics["source_health"]["status"] == "no_data"
    assert results[1].status == "failed"
    assert "Source profile" in results[1].error


def test_realtime_source_runtime_reports_disabled_source_profiles(tmp_path):
    db_path = str(tmp_path / "runtime.db")
    profile = IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="disabled",
        profile_name="Disabled",
        source_db_alias="disabled_mes",
        database_type="mssql",
        source_object_name="events",
        allowed_columns=("event_id", "process_timestamp", "record_id", "cycle_time_s"),
        is_enabled=False,
    )
    adapter = EmptyAdapter()
    runtime = RealtimeSourceRuntime(
        database=db_path,
        configs=(_config(profile.id),),
        adapter=adapter,
    )

    results = runtime.poll_once()

    assert len(results) == 1
    assert results[0].status == "failed"
    assert "disabled" in str(results[0].error).lower()
    assert adapter.requests == []

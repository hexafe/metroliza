import pytest

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.monitor_config import (
    RealtimeMonitorConfig,
    RealtimeMonitorConfigRepository,
)
from metroliza.industrial.realtime.stream_config import RealtimeStreamConfigError


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


def _config(profile_id: int, **overrides):
    values = {
        "source_profile_id": profile_id,
        "stream_key": "line_a",
        "cursor_column": "event_id",
        "event_time_column": "process_timestamp",
        "record_key_column": "record_id",
        "signal_keys": ("cycle_time",),
        "signal_columns": {"cycle_time": "cycle_time_s"},
        "display_mode": "aggregated",
        "aggregation_time_bucket": "hour",
        "aggregation_methods": ("mean", "median"),
        "aggregation_group_fields": ("station",),
    }
    values.update(overrides)
    return RealtimeMonitorConfig(**values)


def test_realtime_monitor_config_repository_upserts_and_lists_configs(tmp_path):
    db_path = str(tmp_path / "monitor_config.db")
    profile = _profile(db_path)
    repository = RealtimeMonitorConfigRepository(db_path)

    created = repository.upsert_config(_config(profile.id, source_timezone="Europe/Warsaw"))
    updated = repository.upsert_config(
        _config(profile.id, polling_interval_seconds=15, timeout_seconds=10)
    )
    listed = repository.list_configs()

    assert created.id == updated.id
    assert updated.polling_interval_seconds == 15.0
    assert updated.to_poll_config().stream_key == "line_a"
    assert [config.id for config in listed] == [updated.id]
    assert listed[0].aggregation_methods == ("mean", "median")
    assert created.source_timezone == "Europe/Warsaw"
    assert updated.source_timezone == "UTC"


def test_realtime_monitor_config_repository_filters_and_deletes_configs(tmp_path):
    db_path = str(tmp_path / "monitor_config.db")
    profile = _profile(db_path)
    repository = RealtimeMonitorConfigRepository(db_path)
    repository.upsert_config(_config(profile.id, enabled=False))

    assert repository.list_configs(enabled_only=True) == []

    repository.delete_config(source_profile_id=profile.id, stream_key="line_a")

    assert repository.list_configs() == []


def test_realtime_monitor_config_rejects_sensitive_and_invalid_payloads(tmp_path):
    db_path = str(tmp_path / "monitor_config.db")
    profile = _profile(db_path)
    repository = RealtimeMonitorConfigRepository(db_path)

    with pytest.raises(RealtimeStreamConfigError):
        repository.upsert_config(
            _config(
                profile.id,
                signal_keys=("password",),
                signal_columns={"password": "password"},
            )
        )

    with pytest.raises(RealtimeStreamConfigError):
        repository.upsert_config(_config(profile.id, aggregation_methods=("mean", "bogus")))

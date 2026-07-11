from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.offset_store import StreamOffsetStore
from metroliza.industrial.realtime.realtime_dashboard_service import RealtimeDashboardService
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.source_health_service import RealtimeSourceHealthService
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import (
    IndustrialSample,
    SignalDefinition,
    StreamOffset,
)


def _config(profile_id: int) -> RealtimePollConfig:
    return RealtimePollConfig(
        source_profile_id=profile_id,
        stream_key="cycle_time",
        cursor_column="event_id",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        signal_keys=("cycle_time",),
        signal_columns={"cycle_time": "cycle_time_s"},
        detectors=("stale_source",),
    )


def test_scheduled_source_health_advances_without_new_samples_and_drives_dashboard(tmp_path):
    db_path = str(tmp_path / "source-health.db")
    profile = IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="line-a",
        profile_name="Line A",
        source_db_alias="plant_a",
        database_type="mssql",
        source_object_name="dbo.events",
    )
    samples = RealtimeSampleRepository(db_path)
    signal = samples.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
        )
    )
    samples.insert_samples(
        (
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=signal.id,
                source_record_key="ROW-1",
                event_time="2026-07-09T10:00:00Z",
                metric_name="cycle_time_s",
                value=10.0,
            ),
        )
    )
    StreamOffsetStore(db_path).upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            event_time_watermark="2026-07-09T10:00:00Z",
            lag_seconds=5.0,
            status="idle",
        )
    )
    service = RealtimeSourceHealthService(db_path)

    first = service.evaluate(_config(profile.id), now="2026-07-09T10:20:00Z")
    second = service.evaluate(_config(profile.id), now="2026-07-09T10:30:00Z")
    persisted = service.get_snapshot(
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )
    dashboard_health = RealtimeDashboardService(db_path).source_lag_health(
        max_lag_seconds=300.0
    )[0]
    anomaly_events = AnomalyEventRepository(db_path).list_events(detector_key="stale_source")

    assert first.lag_seconds == 1_200.0
    assert second.lag_seconds == 1_800.0
    assert persisted == second
    assert len(anomaly_events) == 1
    assert dashboard_health.lag_seconds == 1_800.0
    assert dashboard_health.health == "lagging"
    assert dashboard_health.event_time_watermark == "2026-07-09T10:00:00.000000Z"


def test_source_health_records_no_data_without_synthetic_anomaly(tmp_path):
    db_path = str(tmp_path / "source-health-empty.db")
    profile = IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="line-a",
        profile_name="Line A",
        source_db_alias="plant_a",
        database_type="mssql",
        source_object_name="dbo.events",
    )

    snapshot = RealtimeSourceHealthService(db_path).evaluate(
        _config(profile.id),
        now="2026-07-09T10:00:00Z",
    )

    assert snapshot.status == "no_data"
    assert snapshot.lag_seconds is None
    assert AnomalyEventRepository(db_path).list_events() == []
    dashboard_health = RealtimeDashboardService(db_path).source_lag_health()
    assert len(dashboard_health) == 1
    assert dashboard_health[0].stream_key == "cycle_time"
    assert dashboard_health[0].status == "no_data"
    assert dashboard_health[0].health == "unknown"

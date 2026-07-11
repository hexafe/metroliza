from dataclasses import asdict

from metroliza.industrial.anomaly.contracts import DetectionResult
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.offset_store import StreamOffsetStore
from metroliza.industrial.realtime.realtime_dashboard_service import RealtimeDashboardService
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_contracts import (
    IndustrialSample,
    SignalDefinition,
    StreamOffset,
)


def _seed_dashboard_data(db_path):
    profile = IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly Line",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
        host="tcp://operator:super-secret@prod-db.local",
        database_name="production_secret_db",
    )
    sample_repository = RealtimeSampleRepository(db_path)
    cycle_signal = sample_repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
            unit="s",
            nominal=10.0,
            usl=12.0,
        )
    )
    temperature_signal = sample_repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="oven_temperature",
            metric_name="temperature_c",
            unit="C",
        )
    )
    cycle_samples = sample_repository.insert_samples(
        [
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=cycle_signal.id,
                source_record_key="CYCLE-1",
                event_time="2026-06-13T10:00:00Z",
                metric_name="cycle_time_s",
                value=10.1,
                station="S1",
                quality_flags=("ok",),
                raw_record={"connection_string": "Server=prod;Pwd=super-secret"},
            ),
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=cycle_signal.id,
                source_record_key="CYCLE-2",
                event_time="2026-06-13T10:01:00Z",
                metric_name="cycle_time_s",
                value=12.8,
                station="S1",
                part_number="PN-100",
                raw_record={"password": "super-secret"},
            ),
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=cycle_signal.id,
                source_record_key="CYCLE-3",
                event_time="2026-06-13T10:02:00Z",
                metric_name="cycle_time_s",
                value=13.5,
                station="S2",
            ),
        ]
    )
    temperature_samples = sample_repository.insert_samples(
        [
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=temperature_signal.id,
                source_record_key="TEMP-1",
                event_time="2026-06-13T10:01:30Z",
                metric_name="temperature_c",
                value=220.0,
                line="L1",
            )
        ]
    )
    event_repository = AnomalyEventRepository(db_path)
    event_result = event_repository.insert_events(
        [
            DetectionResult(
                detector_key="spec_limits",
                sample_id=cycle_samples.sample_ids[1],
                signal_id=cycle_signal.id,
                signal_key=cycle_signal.signal_key,
                event_time="2026-06-13T10:01:00Z",
                severity="critical",
                score=0.8,
                observed_value=12.8,
                expected_value=10.0,
                threshold={"usl": 12.0},
                explanation="Observed value 12.8 is above USL 12.",
                context={"internal_note": "not returned by dashboard"},
            ),
            DetectionResult(
                detector_key="rolling_zscore",
                sample_id=cycle_samples.sample_ids[2],
                signal_id=cycle_signal.id,
                signal_key=cycle_signal.signal_key,
                event_time="2026-06-13T10:02:00Z",
                severity="warning",
                score=2.2,
                observed_value=13.5,
                expected_value=10.0,
                threshold={"z": 2.0},
                explanation="Rolling z-score is outside warning range.",
            ),
            DetectionResult(
                detector_key="mad_zscore",
                sample_id=temperature_samples.sample_ids[0],
                signal_id=temperature_signal.id,
                signal_key=temperature_signal.signal_key,
                event_time="2026-06-13T10:01:30Z",
                severity="major",
                score=4.0,
                observed_value=220.0,
                expected_value=200.0,
                threshold={"mad_z": 3.5},
                explanation="Temperature is outside robust z-score threshold.",
            ),
        ]
    )
    offset_store = StreamOffsetStore(db_path)
    offset_store.upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="CYCLE-3",
            event_time_watermark="2026-06-13T10:02:00Z",
            last_success_at="2026-06-13T10:02:10Z",
            last_error="Driver failed with Password=super-secret;Server=prod-db.local",
            lag_seconds=30.0,
            status="idle",
        )
    )
    offset_store.upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="oven_temperature",
            cursor_column="event_id",
            cursor_value="TEMP-1",
            event_time_watermark="2026-06-13T10:01:30Z",
            last_success_at="2026-06-13T10:01:40Z",
            last_error="Connection string contains super-secret",
            lag_seconds=999.0,
            status="running",
        )
    )
    return {
        "profile": profile,
        "cycle_signal": cycle_signal,
        "temperature_signal": temperature_signal,
        "cycle_sample_ids": cycle_samples.sample_ids,
        "temperature_sample_ids": temperature_samples.sample_ids,
        "event_ids": event_result.event_ids,
    }


def test_dashboard_counts_and_open_filters_project_operator_safe_payloads(tmp_path):
    db_path = str(tmp_path / "dashboard_counts.db")
    seeded = _seed_dashboard_data(db_path)
    service = RealtimeDashboardService(db_path)

    open_events = service.list_open_anomaly_events(
        signal_id=seeded["cycle_signal"].id,
        severity="critical",
    )
    severity_counts = service.anomaly_counts_by_severity(status="open")
    detector_counts = service.anomaly_counts_by_detector(status="open")
    payload_text = str([asdict(event) for event in open_events])

    assert [event.detector_key for event in open_events] == ["spec_limits"]
    assert open_events[0].threshold == {"usl": 12.0}
    assert severity_counts == {"info": 0, "warning": 1, "major": 1, "critical": 1}
    assert detector_counts == {"mad_zscore": 1, "rolling_zscore": 1, "spec_limits": 1}
    assert "super-secret" not in payload_text
    assert "prod-db.local" not in payload_text
    assert "production_secret_db" not in payload_text
    assert "connection_string" not in payload_text


def test_recent_events_by_signal_filters_and_orders(tmp_path):
    db_path = str(tmp_path / "dashboard_recent.db")
    seeded = _seed_dashboard_data(db_path)
    service = RealtimeDashboardService(db_path)

    recent = service.recent_events_by_signal(signal_id=seeded["cycle_signal"].id)
    limited = service.recent_events_by_signal(signal_id=seeded["cycle_signal"].id, limit=1)

    assert [event.detector_key for event in recent] == ["rolling_zscore", "spec_limits"]
    assert [event.id for event in limited] == [seeded["event_ids"][1]]
    assert all(event.metric_name == "cycle_time_s" for event in recent)


def test_signal_timeline_window_returns_samples_with_persisted_overlays(tmp_path):
    db_path = str(tmp_path / "dashboard_timeline.db")
    seeded = _seed_dashboard_data(db_path)
    service = RealtimeDashboardService(db_path)

    timeline = service.signal_timeline_window(
        signal_id=seeded["cycle_signal"].id,
        start_time="2026-06-13T10:00:30Z",
        end_time="2026-06-13T10:02:00Z",
    )
    payload_text = str([asdict(point) for point in timeline])

    assert [point.sample_id for point in timeline] == list(seeded["cycle_sample_ids"][1:])
    assert [point.value for point in timeline] == [12.8, 13.5]
    assert [point.anomaly_count for point in timeline] == [1, 1]
    assert [point.open_anomaly_count for point in timeline] == [1, 1]
    assert [point.highest_severity for point in timeline] == ["critical", "warning"]
    assert timeline[0].part_number == "PN-100"
    assert "super-secret" not in payload_text
    assert "connection_string" not in payload_text


def test_recent_signal_timeline_window_returns_latest_samples_in_chart_order(tmp_path):
    db_path = str(tmp_path / "dashboard_recent_samples.db")
    seeded = _seed_dashboard_data(db_path)
    service = RealtimeDashboardService(db_path)

    timeline = service.recent_signal_timeline_window(signal_id=seeded["cycle_signal"].id, limit=2)

    assert [point.sample_id for point in timeline] == list(seeded["cycle_sample_ids"][1:])
    assert [point.value for point in timeline] == [12.8, 13.5]
    assert [point.event_time for point in timeline] == [
        "2026-06-13T10:01:00.000000Z",
        "2026-06-13T10:02:00.000000Z",
    ]


def test_sample_aggregate_rows_compute_csv_summary_style_counts(tmp_path):
    db_path = str(tmp_path / "dashboard_aggregates.db")
    _seed_dashboard_data(db_path)
    service = RealtimeDashboardService(db_path)

    aggregates = service.sample_aggregate_rows()
    by_signal = {row.signal_key: row for row in aggregates}
    cycle = by_signal["cycle_time"]
    temperature = by_signal["oven_temperature"]

    assert [row.signal_key for row in aggregates] == ["cycle_time", "oven_temperature"]
    assert cycle.sample_count == 3
    assert cycle.minimum == 10.1
    assert cycle.maximum == 13.5
    assert round(cycle.average, 3) == 12.133
    assert cycle.latest_value == 13.5
    assert cycle.nominal == 10.0
    assert cycle.usl == 12.0
    assert cycle.below_lsl_count == 0
    assert cycle.above_usl_count == 2
    assert cycle.nok_count == 2
    assert round(cycle.nok_pct, 6) == round(2 / 3, 6)
    assert temperature.sample_count == 1
    assert temperature.nok_count == 0
    assert temperature.nok_pct == 0.0


def test_dashboard_snapshot_includes_recent_samples_when_no_open_anomalies(tmp_path):
    db_path = str(tmp_path / "dashboard_snapshot_samples.db")
    seeded = _seed_dashboard_data(db_path)
    service = RealtimeDashboardService(db_path)

    service.resolve_event(
        event_id=seeded["event_ids"][0],
        resolved_by="operator-a",
        comment="reviewed",
    )
    service.resolve_event(
        event_id=seeded["event_ids"][1],
        resolved_by="operator-a",
        comment="reviewed",
    )
    service.mark_event_false_positive(
        event_id=seeded["event_ids"][2],
        marked_by="operator-a",
        comment="sensor maintenance",
    )

    snapshot = service.dashboard_snapshot(timeline_limit=2)
    signals_by_key = {signal["signal_key"]: signal for signal in snapshot["signals"]}
    aggregates_by_key = {row["signal_key"]: row for row in snapshot["aggregate_rows"]}
    payload_text = str(snapshot)

    assert snapshot["events"] == []
    assert set(signals_by_key) == {"cycle_time", "oven_temperature"}
    assert signals_by_key["cycle_time"]["source_name"] == "Assembly Line"
    assert [point["sample_id"] for point in signals_by_key["cycle_time"]["samples"]] == list(
        seeded["cycle_sample_ids"][1:]
    )
    assert [point["value"] for point in signals_by_key["cycle_time"]["samples"]] == [12.8, 13.5]
    assert signals_by_key["oven_temperature"]["samples"][0]["value"] == 220.0
    assert aggregates_by_key["cycle_time"]["sample_count"] == 3
    assert aggregates_by_key["cycle_time"]["nok_count"] == 2
    assert "super-secret" not in payload_text
    assert "connection_string" not in payload_text


def test_source_lag_health_omits_offset_errors_and_classifies_lag(tmp_path):
    db_path = str(tmp_path / "dashboard_health.db")
    _seed_dashboard_data(db_path)
    service = RealtimeDashboardService(db_path)

    health = service.source_lag_health(max_lag_seconds=120.0)
    by_stream = {row.stream_key: row for row in health}
    payload_text = str([asdict(row) for row in health])

    assert by_stream["cycle_time"].health == "healthy"
    assert by_stream["cycle_time"].lag_seconds == 30.0
    assert by_stream["oven_temperature"].health == "lagging"
    assert by_stream["oven_temperature"].lag_seconds == 999.0
    assert "super-secret" not in payload_text
    assert "prod-db.local" not in payload_text
    assert "cursor_value" not in payload_text
    assert "last_error" not in payload_text


def test_event_status_update_methods_flow_through_service(tmp_path):
    db_path = str(tmp_path / "dashboard_status.db")
    seeded = _seed_dashboard_data(db_path)
    service = RealtimeDashboardService(db_path)
    event_repository = AnomalyEventRepository(db_path)

    service.acknowledge_event(event_id=seeded["event_ids"][0], ack_by="operator-a", comment="seen")
    service.resolve_event(
        event_id=seeded["event_ids"][1],
        resolved_by="operator-b",
        comment="fixture adjusted",
    )
    service.mark_event_false_positive(
        event_id=seeded["event_ids"][2],
        marked_by="operator-c",
        comment="sensor maintenance",
    )

    events = {event.id: event for event in event_repository.list_events()}
    open_events = service.list_open_anomaly_events()
    open_counts = service.anomaly_counts_by_severity(status="open")

    assert events[seeded["event_ids"][0]].status == "acknowledged"
    assert events[seeded["event_ids"][0]].ack_by == "operator-a"
    assert events[seeded["event_ids"][1]].status == "resolved"
    assert events[seeded["event_ids"][1]].ack_by == "operator-b"
    assert events[seeded["event_ids"][2]].status == "false_positive"
    assert events[seeded["event_ids"][2]].ack_by == "operator-c"
    assert open_events == []
    assert open_counts == {"info": 0, "warning": 0, "major": 0, "critical": 0}

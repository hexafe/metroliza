from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.anomaly.baseline_repository import BaselineRepository, IndustrialBaseline
from metroliza.industrial.anomaly.contracts import DetectionResult
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


def _persist_sample(db_path):
    profile = IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
    )
    sample_repository = RealtimeSampleRepository(db_path)
    signal = sample_repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
        )
    )
    result = sample_repository.insert_samples(
        [
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=signal.id,
                source_record_key="ROW-1",
                event_time="2026-06-13T10:00:00Z",
                metric_name="cycle_time_s",
                value=12.5,
            )
        ]
    )
    return signal, result.sample_ids[0]


def test_anomaly_event_insert_deduplicates_and_acknowledges(tmp_path):
    db_path = str(tmp_path / "events.db")
    signal, sample_id = _persist_sample(db_path)
    repository = AnomalyEventRepository(db_path)
    event = DetectionResult(
        detector_key="spec_limits",
        sample_id=sample_id,
        signal_id=signal.id,
        signal_key=signal.signal_key,
        event_time="2026-06-13T10:00:00Z",
        severity="critical",
        score=0.5,
        observed_value=12.5,
        expected_value=10.0,
        threshold={"usl": 12.0},
        explanation="Observed value 12.5 is above USL 12.",
        context={"source": "pytest"},
    )

    first = repository.insert_events([event])
    second = repository.insert_events([event])
    repository.acknowledge_event(event_id=first.event_ids[0], ack_by="operator", comment="seen")
    events = repository.list_events()

    assert first.inserted == 1
    assert second.inserted == 0
    assert second.skipped == 1
    assert first.event_ids == second.event_ids
    assert len(events) == 1
    assert events[0].status == "acknowledged"
    assert events[0].threshold == {"usl": 12.0}
    assert events[0].context == {"source": "pytest"}


def test_anomaly_event_insert_accepts_generator_batches(tmp_path):
    db_path = str(tmp_path / "event_generator.db")
    signal, sample_id = _persist_sample(db_path)
    repository = AnomalyEventRepository(db_path)

    def _events():
        yield DetectionResult(
            detector_key="spec_limits",
            sample_id=sample_id,
            signal_id=signal.id,
            signal_key=signal.signal_key,
            event_time="2026-06-13T10:00:00Z",
            severity="critical",
            score=0.5,
            observed_value=12.5,
            expected_value=10.0,
            threshold={"usl": 12.0},
            explanation="Observed value 12.5 is above USL 12.",
        )

    result = repository.insert_events(_events())

    assert result.processed == 1
    assert result.inserted == 1
    assert len(result.event_ids) == 1


def test_baseline_repository_returns_latest_by_created_at(tmp_path):
    db_path = str(tmp_path / "baselines.db")
    signal, _sample_id = _persist_sample(db_path)
    repository = BaselineRepository(db_path)

    older_id = repository.insert_baseline(
        IndustrialBaseline(
            signal_id=signal.id,
            baseline_version="v1",
            n=20,
            mean=10.0,
            created_at="2026-06-13T09:00:00Z",
        )
    )
    newer_id = repository.insert_baseline(
        IndustrialBaseline(
            signal_id=signal.id,
            baseline_version="v2",
            n=30,
            mean=10.5,
            created_at="2026-06-13T10:00:00Z",
        )
    )

    latest = repository.latest_baseline(signal_id=signal.id)

    assert older_id != newer_id
    assert latest is not None
    assert latest["id"] == newer_id
    assert latest["baseline_version"] == "v2"
    assert latest["n"] == 30

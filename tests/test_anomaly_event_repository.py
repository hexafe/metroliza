import sqlite3

import pytest

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.anomaly.baseline_repository import BaselineRepository, IndustrialBaseline
from metroliza.industrial.anomaly.contracts import DetectionResult
from metroliza.industrial.anomaly.event_repository import (
    AnomalyEventRepository,
    AnomalyEventStatusConflictError,
)
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


def test_event_review_update_rejects_stale_open_status(tmp_path):
    db_path = str(tmp_path / "event-conflict.db")
    signal, sample_id = _persist_sample(db_path)
    repository = AnomalyEventRepository(db_path)
    inserted = repository.insert_events(
        [
            DetectionResult(
                detector_key="spec_limits",
                sample_id=sample_id,
                signal_id=signal.id,
                signal_key=signal.signal_key,
                event_time="2026-06-13T10:00:00Z",
                severity="warning",
                score=0.5,
                observed_value=12.5,
                expected_value=10.0,
                threshold={"usl": 12.0},
                explanation="Observed value is above the specification limit.",
            )
        ]
    )
    event_id = inserted.event_ids[0]

    repository.acknowledge_event(
        event_id=event_id,
        ack_by="operator-a",
        comment="inspected",
        expected_status="open",
    )
    with pytest.raises(AnomalyEventStatusConflictError) as conflict:
        repository.resolve_event(
            event_id=event_id,
            resolved_by="operator-b",
            comment="stale decision",
            expected_status="open",
        )

    assert conflict.value.actual_status == "acknowledged"
    event = repository.list_events()[0]
    assert event.status == "acknowledged"
    assert event.ack_by == "operator-a"
    assert event.comment == "inspected"


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


def test_anomaly_event_insert_empty_batch_returns_complete_result(tmp_path):
    result = AnomalyEventRepository(str(tmp_path / "empty-events.db")).insert_events(())

    assert result.processed == 0
    assert result.inserted == 0
    assert result.skipped == 0
    assert result.event_ids == ()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"severity": "fatal"}, "unsupported anomaly severity"),
        ({"score": float("nan")}, "score must be finite"),
        ({"event_time": "not-a-time"}, "Invalid ISO-8601 timestamp"),
        ({"explanation": ""}, "explanation is required"),
    ],
)
def test_anomaly_event_insert_rejects_invalid_detector_output(tmp_path, overrides, message):
    db_path = str(tmp_path / "invalid-events.db")
    signal, sample_id = _persist_sample(db_path)
    values = {
        "detector_key": "spec_limits",
        "sample_id": sample_id,
        "signal_id": signal.id,
        "event_time": "2026-06-13T10:00:00Z",
        "severity": "critical",
        "score": 0.5,
        "observed_value": 12.5,
        "expected_value": 10.0,
        "threshold": {"usl": 12.0},
        "explanation": "Observed value is above USL.",
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        AnomalyEventRepository(db_path).insert_events((DetectionResult(**values),))

    assert AnomalyEventRepository(db_path).list_events() == []


def test_anomaly_event_insert_does_not_hide_foreign_key_failures(tmp_path):
    db_path = str(tmp_path / "invalid-foreign-key.db")
    signal, sample_id = _persist_sample(db_path)
    event = DetectionResult(
        detector_key="spec_limits",
        sample_id=sample_id,
        signal_id=signal.id + 999,
        event_time="2026-06-13T10:00:00Z",
        severity="critical",
        score=1.0,
        observed_value=12.5,
        expected_value=10.0,
        threshold={},
        explanation="Invalid signal reference for test.",
    )

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        AnomalyEventRepository(db_path).insert_events((event,))


def test_anomaly_event_insert_uses_batched_id_lookup(tmp_path):
    db_path = str(tmp_path / "event_batch_lookup.db")
    signal, sample_id = _persist_sample(db_path)
    connection = sqlite3.connect(db_path)
    traced: list[str] = []
    connection.set_trace_callback(traced.append)
    repository = AnomalyEventRepository(db_path, connection=connection)

    try:
        result = repository.insert_events(
            [
                DetectionResult(
                    detector_key=f"detector_{index}",
                    sample_id=sample_id,
                    signal_id=signal.id,
                    signal_key=signal.signal_key,
                    event_time="2026-06-13T10:00:00Z",
                    severity="warning",
                    score=float(index),
                    observed_value=12.5,
                    expected_value=10.0,
                    threshold={"usl": 12.0},
                    explanation=f"warning {index}",
                )
                for index in range(3)
            ]
        )
    finally:
        connection.close()

    legacy_lookup_count = sum(
        1
        for statement in traced
        if "FROM industrial_anomaly_events" in statement
        and "WHERE sample_id =" in statement
        and "detector_key =" in statement
        and "LIMIT 1" in statement
    )
    batched_lookup_count = sum(
        1 for statement in traced if "_metroliza_event_key_lookup" in statement
    )
    assert result.inserted == 3
    assert len(result.event_ids) == 3
    assert legacy_lookup_count == 0
    assert batched_lookup_count >= 1


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

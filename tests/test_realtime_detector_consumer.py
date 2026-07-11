from datetime import datetime, timedelta, timezone

from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.detector_consumer import RealtimeDetectorConsumer
from metroliza.industrial.realtime.event_stream import (
    DEFAULT_DETECTOR_CONSUMER_KEY,
    RealtimeConsumerOffset,
    RealtimeStreamEvent,
)
from metroliza.industrial.realtime.event_stream_repository import RealtimeEventStreamRepository
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.realtime_service import _load_detection_samples
from metroliza.industrial.realtime.replay import run_detectors_for_samples
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition
from metroliza.reports.db import sqlite_connection_scope


def _profile(db_path: str):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
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
        detectors=("spec_limits",),
        chunk_size=100,
    )


def _seed_sample_batch(db_path: str):
    profile = _profile(db_path)
    sample_repository = RealtimeSampleRepository(db_path)
    signal = sample_repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
            usl=12.0,
        )
    )
    sample_result = sample_repository.insert_samples(
        [
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=signal.id,
                source_record_key="ROW-1",
                event_time="2026-06-13T10:00:00Z",
                metric_name="cycle_time_s",
                value=13.5,
            )
        ]
    )
    stream_repository = RealtimeEventStreamRepository(db_path)
    stream_result = stream_repository.append_sample_batch_committed(
        source_profile_id=profile.id,
        stream_key="cycle_time",
        sample_ids=sample_result.sample_ids,
        signal_ids=(signal.id,),
        detectors=("spec_limits",),
        event_time="2026-06-13T10:00:00Z",
    )
    return profile, sample_result, stream_result


def test_detector_consumer_creates_events_and_advances_offset(tmp_path):
    db_path = str(tmp_path / "consumer.db")
    profile, sample_result, stream_result = _seed_sample_batch(db_path)

    result = RealtimeDetectorConsumer(db_path).process_once(config=_config(profile.id))
    events = AnomalyEventRepository(db_path).list_events()
    offset = RealtimeEventStreamRepository(db_path).get_consumer_offset(
        consumer_key=DEFAULT_DETECTOR_CONSUMER_KEY,
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "completed"
    assert result.stream_events_processed == 1
    assert result.samples_loaded == 1
    assert result.detector_events_created == 1
    assert result.last_event_id == stream_result.event_ids[0]
    assert offset.last_event_id == stream_result.event_ids[0]
    assert events[0].sample_id == sample_result.sample_ids[0]
    assert events[0].detector_key == "spec_limits"


def test_detector_consumer_retry_does_not_duplicate_anomaly_events(tmp_path):
    db_path = str(tmp_path / "consumer-retry.db")
    profile, _sample_result, _stream_result = _seed_sample_batch(db_path)
    consumer = RealtimeDetectorConsumer(db_path)

    first = consumer.process_once(config=_config(profile.id))
    with sqlite_connection_scope(db_path) as connection, connection:
        connection.execute(
            """
            UPDATE industrial_realtime_consumer_offsets
            SET last_event_id = 0
            WHERE consumer_key = ? AND source_profile_id = ? AND stream_key = ?
            """,
            (DEFAULT_DETECTOR_CONSUMER_KEY, profile.id, "cycle_time"),
        )
    second = consumer.process_once(config=_config(profile.id))
    events = AnomalyEventRepository(db_path).list_events()

    assert first.detector_events_created == 1
    assert second.detector_events_created == 0
    assert second.detector_events_skipped == 1
    assert len(events) == 1


def test_detector_consumer_failure_does_not_advance_offset(tmp_path):
    db_path = str(tmp_path / "consumer-failure.db")
    profile, _sample_result, _stream_result = _seed_sample_batch(db_path)

    class FailingEventRepository:
        def insert_events(self, events):
            raise RuntimeError("sqlite busy password=secret123")

    result = RealtimeDetectorConsumer(
        db_path,
        event_repository=FailingEventRepository(),
    ).process_once(config=_config(profile.id))
    offset = RealtimeEventStreamRepository(db_path).get_consumer_offset(
        consumer_key=DEFAULT_DETECTOR_CONSUMER_KEY,
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "failed"
    assert result.last_event_id == 0
    assert result.error == "sqlite busy password=<redacted>"
    assert offset.last_event_id == 0
    assert offset.status == "failed"
    assert offset.last_error == "sqlite busy password=<redacted>"


def test_detector_consumer_offset_write_failure_uses_persisted_checkpoint(tmp_path):
    db_path = str(tmp_path / "consumer-offset-write-failure.db")
    profile, _sample_result, stream_result = _seed_sample_batch(db_path)
    repository = RealtimeEventStreamRepository(db_path)

    class FailingOffsetStreamRepository:
        expected_failure_checkpoint = None

        def __getattr__(self, name):
            return getattr(repository, name)

        def update_consumer_offset(self, **_kwargs):
            raise RuntimeError("offset write failed token=secret123")

        def mark_consumer_failure(self, **kwargs):
            self.expected_failure_checkpoint = kwargs["expected_last_event_id"]
            return repository.mark_consumer_failure(**kwargs)

    failing_repository = FailingOffsetStreamRepository()
    result = RealtimeDetectorConsumer(
        db_path,
        event_stream_repository=failing_repository,
    ).process_once(config=_config(profile.id))
    offset = repository.get_consumer_offset(
        consumer_key=DEFAULT_DETECTOR_CONSUMER_KEY,
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "failed"
    assert result.last_event_id == 0
    assert result.error == "offset write failed token=<redacted>"
    assert failing_repository.expected_failure_checkpoint == 0
    assert offset.last_event_id == 0
    assert offset.last_event_id != stream_result.event_ids[0]
    assert offset.status == "failed"


def test_detector_consumer_detector_runner_failure_does_not_advance_offset(tmp_path):
    db_path = str(tmp_path / "consumer-detector-failure.db")
    profile, _sample_result, _stream_result = _seed_sample_batch(db_path)

    def fail_detector(samples, signal, detectors):
        raise RuntimeError("detector crashed password=secret123")

    result = RealtimeDetectorConsumer(
        db_path,
        detector_runner=fail_detector,
    ).process_once(config=_config(profile.id))
    offset = RealtimeEventStreamRepository(db_path).get_consumer_offset(
        consumer_key=DEFAULT_DETECTOR_CONSUMER_KEY,
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "failed"
    assert result.last_event_id == 0
    assert result.error == "detector failure: detector crashed password=<redacted>"
    assert offset.last_event_id == 0
    assert offset.status == "failed"


def test_detector_consumer_offset_read_failure_returns_failed_result(tmp_path):
    db_path = str(tmp_path / "consumer-offset-read-failure.db")
    profile = _profile(db_path)

    class FailingStreamRepository:
        def get_consumer_offset(self, **kwargs):
            raise RuntimeError("offset read failed token=secret123")

        def mark_consumer_failure(self, **kwargs):
            return RealtimeConsumerOffset(
                consumer_key=kwargs["consumer_key"],
                source_profile_id=kwargs["source_profile_id"],
                stream_key=kwargs["stream_key"],
                last_event_id=0,
                last_error=kwargs["error"],
                failure_count=1,
                status="failed",
            )

    result = RealtimeDetectorConsumer(
        db_path,
        event_stream_repository=FailingStreamRepository(),
    ).process_once(config=_config(profile.id))

    assert result.status == "failed"
    assert result.last_event_id == 0
    assert result.error == "offset read failed token=<redacted>"
    assert result.diagnostics["stage"] == "read_consumer_offset"


def test_detector_consumer_stale_failure_cannot_overwrite_concurrent_progress(tmp_path):
    db_path = str(tmp_path / "consumer-stale-failure.db")
    profile = _profile(db_path)
    repository = RealtimeEventStreamRepository(db_path)
    repository.update_consumer_offset(
        consumer_key=DEFAULT_DETECTOR_CONSUMER_KEY,
        source_profile_id=profile.id,
        stream_key="cycle_time",
        last_event_id=2,
    )

    class RacingStreamRepository:
        expected_failure_checkpoint = None

        def get_consumer_offset(self, **kwargs):
            return repository.get_consumer_offset(**kwargs)

        def read_events_after(self, **_kwargs):
            repository.update_consumer_offset(
                consumer_key=DEFAULT_DETECTOR_CONSUMER_KEY,
                source_profile_id=profile.id,
                stream_key="cycle_time",
                last_event_id=10,
                updated_at="2026-07-09T10:00:00Z",
            )
            raise RuntimeError("stream read failed token=secret123")

        def mark_consumer_failure(self, **kwargs):
            self.expected_failure_checkpoint = kwargs["expected_last_event_id"]
            return repository.mark_consumer_failure(**kwargs)

    racing_repository = RacingStreamRepository()
    result = RealtimeDetectorConsumer(
        db_path,
        event_stream_repository=racing_repository,
    ).process_once(config=_config(profile.id))
    offset = repository.get_consumer_offset(
        consumer_key=DEFAULT_DETECTOR_CONSUMER_KEY,
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "failed"
    assert result.last_event_id == 10
    assert racing_repository.expected_failure_checkpoint == 2
    assert offset.last_event_id == 10
    assert offset.status == "idle"
    assert offset.last_error is None


def test_detector_consumer_quarantines_permanent_poison_and_continues(tmp_path):
    db_path = str(tmp_path / "consumer-poison.db")
    profile = _profile(db_path)
    samples = RealtimeSampleRepository(db_path)
    signal = samples.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
            usl=12.0,
        )
    )
    inserted = samples.insert_samples(
        [
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=signal.id,
                source_record_key=f"ROW-{index}",
                event_time=f"2026-06-13T10:0{index}:00Z",
                metric_name="cycle_time_s",
                value=13.0 + index,
            )
            for index in range(2)
        ]
    )
    stream = RealtimeEventStreamRepository(db_path)
    poison = stream.append_sample_batch_committed(
        source_profile_id=profile.id,
        stream_key="cycle_time",
        sample_ids=(inserted.sample_ids[0],),
        signal_ids=(signal.id,),
        detectors=("not_implemented",),
        payload={"password": "raw-secret"},
    )
    valid = stream.append_sample_batch_committed(
        source_profile_id=profile.id,
        stream_key="cycle_time",
        sample_ids=(inserted.sample_ids[1],),
        signal_ids=(signal.id,),
        detectors=("spec_limits",),
    )

    result = RealtimeDetectorConsumer(db_path).process_once(config=_config(profile.id))
    dead_letters = stream.list_dead_letters()
    offset = stream.get_consumer_offset(
        consumer_key=DEFAULT_DETECTOR_CONSUMER_KEY,
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "completed"
    assert result.stream_events_processed == 2
    assert result.detector_events_created == 1
    assert result.diagnostics["dead_letter_count"] == 1
    assert offset.last_event_id == valid.event_ids[0]
    assert dead_letters[0].event_id == poison.event_ids[0]
    assert "Unsupported realtime detector" in dead_letters[0].error_summary
    assert dead_letters[0].payload["password"] == "<redacted>"


def test_detector_consumer_quarantines_non_integral_boolean_and_overflow_ids(tmp_path):
    db_path = str(tmp_path / "consumer-malformed-ids.db")
    profile = _profile(db_path)
    stream = RealtimeEventStreamRepository(db_path)
    malformed_ids = ([True], [1.5], [2**63])
    poison_event_ids = []
    for index, raw_ids in enumerate(malformed_ids):
        appended = stream.append_event(
            RealtimeStreamEvent(
                source_profile_id=profile.id,
                stream_key="cycle_time",
                event_type="sample_batch_committed",
                aggregate_type="sample_batch",
                idempotency_key=f"malformed-{index}",
                payload={"sample_ids": raw_ids, "detectors": ["spec_limits"]},
            )
        )
        poison_event_ids.extend(appended.event_ids)

    result = RealtimeDetectorConsumer(db_path).process_once(config=_config(profile.id))
    dead_letters = stream.list_dead_letters()

    assert result.status == "completed"
    assert result.stream_events_processed == 3
    assert result.diagnostics["dead_letter_count"] == 3
    assert [letter.event_id for letter in dead_letters] == poison_event_ids
    assert all("positive integers" in letter.error_summary for letter in dead_letters)


def test_detection_history_is_loaded_strictly_before_first_new_sample(tmp_path):
    db_path = str(tmp_path / "consumer-history-boundary.db")
    profile = _profile(db_path)
    repository = RealtimeSampleRepository(db_path)
    signal = repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
        )
    )
    start = datetime(2026, 6, 13, 10, 0, tzinfo=timezone.utc)
    history = repository.insert_samples(
        [
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=signal.id,
                source_record_key=f"HISTORY-{index}",
                event_time=(start + timedelta(seconds=index)).isoformat(),
                metric_name="cycle_time_s",
                value=9.9 if index % 2 else 10.1,
            )
            for index in range(30)
        ]
    )
    assert history.inserted == 30
    new_batch = repository.insert_samples(
        [
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=signal.id,
                source_record_key=f"NEW-{index}",
                event_time=(start + timedelta(minutes=1, seconds=index)).isoformat(),
                metric_name="cycle_time_s",
                value=100.0 if index == 0 else 10.0,
            )
            for index in range(500)
        ]
    )

    detection_samples = _load_detection_samples(
        repository,
        (signal,),
        new_batch.sample_ids,
        detectors=("rolling_zscore",),
    )
    events = run_detectors_for_samples(
        detection_samples,
        signal=signal,
        detectors=("rolling_zscore",),
        score_sample_ids=new_batch.sample_ids,
    )

    assert len(detection_samples) == 530
    assert any(event.sample_id == new_batch.sample_ids[0] for event in events)

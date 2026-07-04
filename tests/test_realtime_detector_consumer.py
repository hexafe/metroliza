from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.detector_consumer import RealtimeDetectorConsumer
from metroliza.industrial.realtime.event_stream import (
    DEFAULT_DETECTOR_CONSUMER_KEY,
    RealtimeConsumerOffset,
)
from metroliza.industrial.realtime.event_stream_repository import RealtimeEventStreamRepository
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


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
    stream_repository = RealtimeEventStreamRepository(db_path)

    first = consumer.process_once(config=_config(profile.id))
    stream_repository.update_consumer_offset(
        consumer_key=DEFAULT_DETECTOR_CONSUMER_KEY,
        source_profile_id=profile.id,
        stream_key="cycle_time",
        last_event_id=0,
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

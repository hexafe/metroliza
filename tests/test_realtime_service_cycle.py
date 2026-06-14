from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.realtime.db_poller import SourceReadResult
from metroliza.industrial.realtime.offset_store import StreamOffsetStore
from metroliza.industrial.realtime.realtime_service import run_polling_cycle
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import StreamOffset


class FakeAdapter:
    def __init__(self, rows=(), *, error=None):
        self.rows = tuple(rows)
        self.error = error
        self.requests = []

    def fetch_rows(self, request):
        self.requests.append(request)
        return SourceReadResult(
            rows=self.rows,
            diagnostics={"adapter": "fake", "sql_text": "SELECT password FROM secrets"},
            error=self.error,
        )


def _profile(db_path: str):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        allowed_columns=("event_id", "process_timestamp", "record_id", "cycle_time_s", "station"),
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
        detectors=("spec_limits",),
        chunk_size=100,
    )


def test_realtime_poll_cycle_persists_samples_events_and_offset(tmp_path):
    db_path = str(tmp_path / "service.db")
    profile = _profile(db_path)
    config = _config(profile.id)
    adapter = FakeAdapter(
        [
            {
                "event_id": "100",
                "record_id": "row-100",
                "process_timestamp": "2026-06-13T10:00:00Z",
                "cycle_time_s": "25",
                "station": "S1",
            }
        ]
    )

    result = run_polling_cycle(
        database=db_path,
        profile=profile,
        config=config,
        adapter=adapter,
        detector_runner=lambda samples, signal, detectors: [],
    )

    assert result.status == "completed"
    assert result.rows_fetched == 1
    assert result.samples_inserted == 1
    assert result.cursor_value == "100"
    assert "sql_text" not in result.diagnostics
    assert StreamOffsetStore(db_path).get_offset(
        source_profile_id=profile.id,
        stream_key="cycle_time",
    ).cursor_value == "100"


def test_realtime_poll_cycle_creates_explainable_detector_events(tmp_path):
    db_path = str(tmp_path / "events.db")
    profile = _profile(db_path)
    repository = RealtimeSampleRepository(db_path)
    repository.upsert_signal_definition(
        config_signal := config_signal_definition(profile.id)
    )
    config = _config(profile.id)
    adapter = FakeAdapter(
        [
            {
                "event_id": "101",
                "record_id": "row-101",
                "process_timestamp": "2026-06-13T10:01:00Z",
                "cycle_time_s": "13.5",
                "station": "S1",
            }
        ]
    )

    result = run_polling_cycle(database=db_path, profile=profile, config=config, adapter=adapter)
    events = AnomalyEventRepository(db_path).list_events()

    assert config_signal.signal_key == "cycle_time"
    assert result.detector_events_created == 1
    assert events[0].severity == "critical"
    assert "above USL" in events[0].explanation


def test_realtime_poll_cycle_does_not_advance_offset_on_adapter_error(tmp_path):
    db_path = str(tmp_path / "adapter-error.db")
    profile = _profile(db_path)
    config = _config(profile.id)
    StreamOffsetStore(db_path).upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="50",
        )
    )

    result = run_polling_cycle(
        database=db_path,
        profile=profile,
        config=config,
        adapter=FakeAdapter(error="failed password=secret123"),
    )
    offset = StreamOffsetStore(db_path).get_offset(
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "failed"
    assert result.error == "failed password=<redacted>"
    assert offset.cursor_value == "50"
    assert offset.last_error == "failed password=<redacted>"


def test_realtime_poll_cycle_is_idempotent_for_duplicate_rows(tmp_path):
    db_path = str(tmp_path / "duplicates.db")
    profile = _profile(db_path)
    config = _config(profile.id)
    rows = [
        {
            "event_id": "100",
            "record_id": "row-100",
            "process_timestamp": "2026-06-13T10:00:00Z",
            "cycle_time_s": "10",
            "station": "S1",
        }
    ]

    first = run_polling_cycle(database=db_path, profile=profile, config=config, adapter=FakeAdapter(rows))
    second = run_polling_cycle(database=db_path, profile=profile, config=config, adapter=FakeAdapter(rows))

    assert first.samples_inserted == 1
    assert second.samples_inserted == 0
    assert second.samples_skipped == 1
    assert second.cursor_value == "100"


def test_realtime_poll_cycle_isolates_detector_failures_and_advances_successful_fetch(tmp_path):
    db_path = str(tmp_path / "detector-error.db")
    profile = _profile(db_path)
    config = _config(profile.id)

    def failing_runner(samples, signal, detectors):
        raise RuntimeError("detector token=secret failed")

    result = run_polling_cycle(
        database=db_path,
        profile=profile,
        config=config,
        adapter=FakeAdapter(
            [
                {
                    "event_id": "100",
                    "record_id": "row-100",
                    "process_timestamp": "2026-06-13T10:00:00Z",
                    "cycle_time_s": "10",
                    "station": "S1",
                }
            ]
        ),
        detector_runner=failing_runner,
    )
    offset = StreamOffsetStore(db_path).get_offset(
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "completed"
    assert result.detector_events_created == 0
    assert "token=<redacted>" in result.diagnostics["warnings"][0]
    assert offset.cursor_value == "100"


def test_realtime_poll_cycle_does_not_advance_offset_when_event_write_fails(
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "event-write-error.db")
    profile = _profile(db_path)
    RealtimeSampleRepository(db_path).upsert_signal_definition(config_signal_definition(profile.id))
    config = _config(profile.id)
    StreamOffsetStore(db_path).upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="50",
        )
    )

    def fail_insert(self, events):
        raise RuntimeError("sqlite busy password=secret123")

    monkeypatch.setattr(AnomalyEventRepository, "insert_events", fail_insert)

    result = run_polling_cycle(
        database=db_path,
        profile=profile,
        config=config,
        adapter=FakeAdapter(
            [
                {
                    "event_id": "100",
                    "record_id": "row-100",
                    "process_timestamp": "2026-06-13T10:00:00Z",
                    "cycle_time_s": "13.5",
                    "station": "S1",
                }
            ]
        ),
    )
    offset = StreamOffsetStore(db_path).get_offset(
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "failed"
    assert result.error == "sqlite busy password=<redacted>"
    assert offset.cursor_value == "50"
    assert offset.last_error == "sqlite busy password=<redacted>"


def config_signal_definition(profile_id):
    from metroliza.industrial.realtime.stream_contracts import SignalDefinition

    return SignalDefinition(
        source_profile_id=profile_id,
        signal_key="cycle_time",
        metric_name="cycle_time_s",
        lsl=8.0,
        usl=12.0,
    )

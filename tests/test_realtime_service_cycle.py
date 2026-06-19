from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.realtime.db_poller import SourceReadResult
from metroliza.industrial.realtime.offset_store import StreamOffsetStore
from metroliza.industrial.realtime.realtime_service import _load_persisted_samples, run_polling_cycle
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition, StreamOffset


class FakeAdapter:
    def __init__(self, rows=(), *, error=None, diagnostics=None):
        self.rows = tuple(rows)
        self.error = error
        self.diagnostics = dict(diagnostics or {})
        self.requests = []

    def fetch_rows(self, request):
        self.requests.append(request)
        diagnostics = {"adapter": "fake", "sql_text": "SELECT password FROM secrets"}
        diagnostics.update(self.diagnostics)
        return SourceReadResult(
            rows=self.rows,
            diagnostics=diagnostics,
            error=self.error,
        )


class RaisingAdapter:
    def __init__(self):
        self.requests = []

    def fetch_rows(self, request):
        self.requests.append(request)
        raise RuntimeError("driver timeout password=source-secret")


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
    assert result.diagnostics["stage"] == "source_read"
    assert result.diagnostics["rows_fetched"] == 0
    assert result.diagnostics["cursor_value"] == "50"
    assert result.diagnostics["error"] == "failed password=<redacted>"
    assert "sql_hash" in result.diagnostics
    assert "query_summary" in result.diagnostics
    diagnostics_text = str(result.diagnostics)
    assert "SELECT password FROM secrets" not in diagnostics_text
    assert "secret123" not in diagnostics_text
    assert offset.cursor_value == "50"
    assert offset.last_error == "failed password=<redacted>"


def test_realtime_poll_cycle_reports_source_fetch_exception_diagnostics(tmp_path):
    db_path = str(tmp_path / "adapter-exception.db")
    profile = _profile(db_path)
    config = _config(profile.id)
    StreamOffsetStore(db_path).upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="75",
            event_time_watermark="2026-06-13T10:00:00Z",
        )
    )

    result = run_polling_cycle(
        database=db_path,
        profile=profile,
        config=config,
        adapter=RaisingAdapter(),
    )

    assert result.status == "failed"
    assert result.error == "driver timeout password=<redacted>"
    assert result.cursor_value == "75"
    assert result.event_time_watermark == "2026-06-13T10:00:00Z"
    assert result.diagnostics["stage"] == "source_fetch"
    assert result.diagnostics["cursor_value"] == "75"
    assert result.diagnostics["event_time_watermark"] == "2026-06-13T10:00:00Z"
    assert result.diagnostics["error"] == "driver timeout password=<redacted>"
    assert "sql_hash" in result.diagnostics
    assert result.diagnostics["query_summary"].startswith("bounded mssql poll")


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


def test_realtime_poll_cycle_rejects_stale_offset_tie_breaker_column(tmp_path):
    db_path = str(tmp_path / "stale-offset-tie-breaker.db")
    profile = _profile(db_path)
    config = _config(profile.id)
    StreamOffsetStore(db_path).upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="100",
            cursor_tie_breaker_column="legacy_record_id",
            cursor_tie_breaker_value="row-100",
        )
    )
    adapter = FakeAdapter(
        [
            {
                "event_id": "101",
                "record_id": "row-101",
                "process_timestamp": "2026-06-13T10:01:00Z",
                "cycle_time_s": "10",
                "station": "S1",
            }
        ]
    )

    result = run_polling_cycle(database=db_path, profile=profile, config=config, adapter=adapter)
    offset = StreamOffsetStore(db_path).get_offset(
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "failed"
    assert result.diagnostics["stage"] == "query_build"
    assert "legacy_record_id" in result.error
    assert "Reset or reseed" in result.error
    assert adapter.requests == []
    assert offset.cursor_value == "100"
    assert offset.cursor_tie_breaker_column == "legacy_record_id"
    assert offset.cursor_tie_breaker_value == "row-100"
    assert offset.last_error == result.error


def test_realtime_poll_cycle_does_not_advance_offset_to_trailing_unkeyed_row(tmp_path):
    db_path = str(tmp_path / "trailing-unkeyed-row.db")
    profile = _profile(db_path)
    config = _config(profile.id)

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
                },
                {
                    "event_id": "101",
                    "record_id": None,
                    "process_timestamp": "2026-06-13T10:01:00Z",
                    "cycle_time_s": "11",
                    "station": "S1",
                },
            ]
        ),
        detector_runner=lambda samples, signal, detectors: [],
    )
    offset = StreamOffsetStore(db_path).get_offset(
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )

    assert result.status == "completed"
    assert result.rows_fetched == 2
    assert result.samples_inserted == 1
    assert result.cursor_value == "100"
    assert result.event_time_watermark == "2026-06-13T10:00:00Z"
    assert offset.cursor_value == "100"
    assert offset.cursor_tie_breaker_column == "record_id"
    assert offset.cursor_tie_breaker_value == "row-100"
    assert offset.event_time_watermark == "2026-06-13T10:00:00Z"


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


def test_load_persisted_samples_uses_targeted_sample_ids():
    samples = [
        IndustrialSample(
            id=10,
            source_profile_id=1,
            signal_id=1,
            source_record_key="ROW-10",
            event_time="2026-06-13T10:00:00Z",
            metric_name="cycle_time_s",
            value=10.0,
        ),
        IndustrialSample(
            id=11,
            source_profile_id=1,
            signal_id=2,
            source_record_key="ROW-11",
            event_time="2026-06-13T10:01:00Z",
            metric_name="pressure_bar",
            value=2.4,
        ),
    ]

    class TargetedRepository:
        requested_ids = None

        def list_samples_by_ids(self, sample_ids):
            self.requested_ids = tuple(sample_ids)
            return list(samples)

        def list_samples(self, **kwargs):
            raise AssertionError("historical signal scans should not be used")

    repository = TargetedRepository()
    loaded = _load_persisted_samples(
        repository,
        (
            SignalDefinition(
                id=1,
                source_profile_id=1,
                signal_key="cycle_time",
                metric_name="cycle_time_s",
            ),
        ),
        (10, 11),
    )

    assert repository.requested_ids == (10, 11)
    assert [sample.id for sample in loaded] == [10]


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

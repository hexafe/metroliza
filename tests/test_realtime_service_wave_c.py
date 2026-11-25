from contextlib import closing
from dataclasses import replace
import sqlite3

import pytest

from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime import realtime_service
from metroliza.industrial.realtime.db_poller import SourceReadResult
from metroliza.industrial.realtime.event_stream import (
    DEFAULT_DETECTOR_CONSUMER_KEY,
    SAMPLE_BATCH_COMMITTED_EVENT_TYPE,
)
from metroliza.industrial.realtime.event_stream_repository import RealtimeEventStreamRepository
from metroliza.industrial.realtime.offset_store import StreamOffsetStore
from metroliza.industrial.realtime.realtime_service import run_polling_cycle
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import SignalDefinition, StreamOffset
from metroliza.reports.db import sqlite_connection_scope


def _profile(database: str, *, database_type: str = "mssql"):
    return IndustrialDataRepository(database).upsert_source_profile(
        profile_key="wave-c",
        profile_name="Wave C",
        source_db_alias="mes",
        database_type=database_type,
        source_object_name="events",
        allowed_columns=(
            "event_id",
            "record_id",
            "process_timestamp",
            "cycle_time_s",
        ),
    )


def _config(profile_id: int, **changes) -> RealtimePollConfig:
    base = RealtimePollConfig(
        source_profile_id=profile_id,
        stream_key="cycle_time",
        cursor_column="event_id",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        signal_keys=("cycle_time",),
        signal_columns={"cycle_time": "cycle_time_s"},
        segment_fields=(),
        context_fields=(),
        detectors=("spec_limits",),
        chunk_size=10,
        max_catchup_rows_per_cycle=20,
    )
    return replace(base, **changes)


def _row(cursor: int, event_time: str | None = None) -> dict[str, object]:
    return {
        "event_id": str(cursor),
        "record_id": f"row-{cursor}",
        "process_timestamp": event_time or f"2026-07-09T10:{cursor:02d}:00Z",
        "cycle_time_s": 10.0,
    }


class SequenceAdapter:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.requests = []

    def fetch_rows(self, request):
        self.requests.append(request)
        rows = self.chunks.pop(0) if self.chunks else ()
        return SourceReadResult(rows=tuple(rows))


def test_losing_poller_rolls_back_without_marking_winning_offset_failed(tmp_path):
    database = str(tmp_path / "two-pollers.db")
    profile = _profile(database)
    config = _config(profile.id)
    StreamOffsetStore(database).upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key=config.stream_key,
            cursor_column=config.cursor_column,
            cursor_value="50",
            cursor_tie_breaker_column=config.record_key_column,
            cursor_tie_breaker_value="row-50",
            event_time_watermark="2026-07-09T10:00:00Z",
            status="idle",
        )
    )

    class InterleavedAdapter:
        def fetch_rows(self, request):
            winner = run_polling_cycle(
                database=database,
                profile=profile,
                config=config,
                adapter=SequenceAdapter(((_row(200, "2026-07-09T10:02:00Z"),),)),
            )
            assert winner.status == "completed"
            return SourceReadResult(rows=(_row(100, "2026-07-09T10:01:00Z"),))

    loser = run_polling_cycle(
        database=database,
        profile=profile,
        config=config,
        adapter=InterleavedAdapter(),
    )
    offset = StreamOffsetStore(database).get_offset(
        source_profile_id=profile.id,
        stream_key=config.stream_key,
    )
    signal = RealtimeSampleRepository(database).get_signal_definition(
        source_profile_id=profile.id,
        signal_key="cycle_time",
    )

    assert loser.status == "completed_with_warnings"
    assert loser.diagnostics["stage"] == "concurrent_offset_advance"
    assert offset.cursor_value == "200"
    assert offset.status == "idle"
    assert [sample.source_record_key for sample in RealtimeSampleRepository(database).list_samples(
        signal_id=signal.id
    )] == ["row-200"]


def test_stale_fetch_failure_does_not_mark_newer_winning_offset_failed(tmp_path):
    database = str(tmp_path / "stale-fetch-failure.db")
    profile = _profile(database)
    config = _config(profile.id)
    StreamOffsetStore(database).upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key=config.stream_key,
            cursor_column=config.cursor_column,
            cursor_value="50",
            cursor_tie_breaker_column=config.record_key_column,
            cursor_tie_breaker_value="row-50",
            event_time_watermark="2026-07-09T10:00:00Z",
            status="idle",
        )
    )

    class StaleFailingAdapter:
        def fetch_rows(self, request):
            winner = run_polling_cycle(
                database=database,
                profile=profile,
                config=config,
                adapter=SequenceAdapter(((_row(200, "2026-07-09T10:02:00Z"),),)),
            )
            assert winner.status == "completed"
            return SourceReadResult(error="stale reader failed")

    failed = run_polling_cycle(
        database=database,
        profile=profile,
        config=config,
        adapter=StaleFailingAdapter(),
    )
    offset = StreamOffsetStore(database).get_offset(
        source_profile_id=profile.id,
        stream_key=config.stream_key,
    )

    assert failed.status == "failed"
    assert failed.cursor_value == "200"
    assert offset.cursor_value == "200"
    assert offset.status == "idle"
    assert offset.last_error is None


def test_allowed_lateness_accepts_boundary_and_advances_past_older_rows(tmp_path):
    database = str(tmp_path / "lateness.db")
    profile = _profile(database)
    config = _config(profile.id, allowed_lateness_seconds=60)
    StreamOffsetStore(database).upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key=config.stream_key,
            cursor_column=config.cursor_column,
            cursor_value="50",
            cursor_tie_breaker_column=config.record_key_column,
            cursor_tie_breaker_value="row-50",
            event_time_watermark="2026-07-09T10:00:00Z",
        )
    )
    adapter = SequenceAdapter(
        (
            (
                _row(51, "2026-07-09T09:58:59Z"),
                _row(52, "2026-07-09T09:59:00Z"),
                _row(53, "2026-07-09T10:01:00Z"),
            ),
        )
    )

    result = run_polling_cycle(
        database=database,
        profile=profile,
        config=config,
        adapter=adapter,
    )

    assert result.samples_inserted == 2
    assert result.cursor_value == "53"
    assert result.event_time_watermark == "2026-07-09T10:01:00.000000Z"
    assert result.diagnostics["mapping"]["skipped_late"] == 1


def test_polling_cycle_catches_up_across_multiple_bounded_chunks(tmp_path):
    database = str(tmp_path / "catchup.db")
    profile = _profile(database)
    adapter = SequenceAdapter((((_row(1), _row(2))), ((_row(3), _row(4))), ((_row(5),))))

    result = run_polling_cycle(
        database=database,
        profile=profile,
        config=_config(profile.id, chunk_size=2, max_catchup_rows_per_cycle=6),
        adapter=adapter,
    )

    assert result.status == "completed"
    assert result.rows_fetched == 5
    assert result.samples_inserted == 5
    assert result.cursor_value == "5"
    assert result.diagnostics["chunks_processed"] == 3
    assert [request.query.limit for request in adapter.requests] == [2, 2, 2]


def test_polling_cycle_stops_on_full_chunk_without_cursor_progress(tmp_path):
    database = str(tmp_path / "no-progress.db")
    profile = _profile(database)
    repeated = (_row(1), _row(2))
    adapter = SequenceAdapter((repeated, repeated, repeated))

    result = run_polling_cycle(
        database=database,
        profile=profile,
        config=_config(profile.id, chunk_size=2, max_catchup_rows_per_cycle=8),
        adapter=adapter,
    )

    assert result.status == "completed_with_warnings"
    assert result.rows_fetched == 4
    assert result.samples_inserted == 2
    assert len(adapter.requests) == 2
    assert "no cursor progress" in " ".join(result.diagnostics["warnings"])


def test_polling_cycle_honors_stop_between_atomic_chunks(tmp_path):
    database = str(tmp_path / "cancel.db")
    profile = _profile(database)
    adapter = SequenceAdapter((((_row(1), _row(2))), ((_row(3), _row(4)))))
    stop_calls = 0

    def stop_check():
        nonlocal stop_calls
        stop_calls += 1
        return stop_calls >= 4

    result = run_polling_cycle(
        database=database,
        profile=profile,
        config=_config(profile.id, chunk_size=2, max_catchup_rows_per_cycle=6),
        adapter=adapter,
        stop_check=stop_check,
    )

    assert result.status == "completed_with_warnings"
    assert result.rows_fetched == 2
    assert result.samples_inserted == 2
    assert len(adapter.requests) == 1
    with sqlite_connection_scope(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM industrial_samples").fetchone()[0] == 2


def test_reopened_poller_resumes_composite_checkpoint_after_interrupted_commits(tmp_path, monkeypatch):
    database = str(tmp_path / "restart-cache.db")
    source = tmp_path / "restart-source.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("""CREATE TABLE events (
            event_id TEXT, record_id TEXT, process_timestamp TEXT, cycle_time_s REAL
        )""")
        connection.execute("INSERT INTO events VALUES ('100', 'row-a', '2026-07-09T10:00:00Z', 15)")
        connection.commit()

    profile = _profile(database, database_type="sqlite")
    config = _config(profile.id)
    stream = {"source_profile_id": profile.id, "stream_key": config.stream_key}
    signal = RealtimeSampleRepository(database).upsert_signal_definition(SignalDefinition(
        source_profile_id=profile.id, signal_key="cycle_time", metric_name="cycle_time_s", usl=12.0,
    ))

    class SQLiteSource:
        def __init__(self):
            self.requests = []

        def fetch_rows(self, request):
            self.requests.append(request)
            with closing(sqlite3.connect(source)) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(request.query.sql_text, request.query.parameters).fetchall()
            return SourceReadResult(rows=tuple(dict(row) for row in rows))

    def poll(adapter):
        reopened_profile = IndustrialDataRepository(database).list_source_profiles()[0]
        return run_polling_cycle(database=database, profile=reopened_profile, config=config, adapter=adapter)

    def sample_batches():
        return RealtimeEventStreamRepository(database).read_events_after(
            **stream, event_types=(SAMPLE_BATCH_COMMITTED_EVENT_TYPE,),
        )

    def stop_before_detector_consumption(**_kwargs):
        raise KeyboardInterrupt("interrupted after source commit")

    with monkeypatch.context() as fault:
        fault.setattr(realtime_service, "_run_detector_consumer", stop_before_detector_consumption)
        with pytest.raises(KeyboardInterrupt, match="after source commit"):
            poll(SQLiteSource())

    first_offset = StreamOffsetStore(database).get_offset(**stream)
    first_batch, = sample_batches()
    assert (first_offset.cursor_value, first_offset.cursor_tie_breaker_value) == ("100", "row-a")
    assert AnomalyEventRepository(database).list_events() == []

    # No source rows arrive after reopening. The pending committed batch still runs.
    empty_source = SQLiteSource()
    recovered = poll(empty_source)
    assert empty_source.requests[0].query.parameters == ("100", "row-a", config.chunk_size)
    assert recovered.rows_fetched == 0
    assert recovered.detector_events_created == 1
    assert recovered.detector_consumer_last_event_id == first_batch.event_id

    with closing(sqlite3.connect(source)) as connection:
        connection.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", [
            ("100", "row-b", "2026-07-09T10:01:00Z", 16),
            ("101", "row-c", "2026-07-09T10:02:00Z", 17),
        ])
        connection.commit()

    real_upsert = StreamOffsetStore.upsert_offset

    def fail_after_offset_write(self, offset, **kwargs):
        real_upsert(self, offset, **kwargs)
        raise RuntimeError("interrupted before transaction commit")

    with monkeypatch.context() as fault:
        fault.setattr(StreamOffsetStore, "upsert_offset", fail_after_offset_write)
        failed = poll(SQLiteSource())
    assert failed.status == "failed"
    assert failed.diagnostics["stage"] == "update_source_offset"
    failed_offset = StreamOffsetStore(database).get_offset(**stream)
    assert (failed_offset.cursor_value, failed_offset.cursor_tie_breaker_value) == ("100", "row-a")
    assert [batch.event_id for batch in sample_batches()] == [first_batch.event_id]
    assert [sample.source_record_key for sample in RealtimeSampleRepository(database).list_samples(
        signal_id=signal.id,
    )] == ["row-a"]

    resumed_source = SQLiteSource()
    resumed = poll(resumed_source)
    assert resumed_source.requests[0].query.parameters == ("100", "row-a", config.chunk_size)
    assert resumed.rows_fetched == resumed.samples_inserted == resumed.detector_events_created == 2
    final_offset = StreamOffsetStore(database).get_offset(**stream)
    assert (final_offset.cursor_value, final_offset.cursor_tie_breaker_value) == ("101", "row-c")
    batches = sample_batches()
    assert [batch.payload["cursor_tie_breaker_value"] for batch in batches] == ["row-a", "row-c"]
    consumer = RealtimeEventStreamRepository(database).get_consumer_offset(
        **stream, consumer_key=DEFAULT_DETECTOR_CONSUMER_KEY,
    )
    assert consumer.last_event_id == batches[-1].event_id
    assert poll(SQLiteSource()).rows_fetched == 0
    assert len(sample_batches()) == 2
    assert len(AnomalyEventRepository(database).list_events()) == 3

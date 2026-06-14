from __future__ import annotations

from dataclasses import dataclass

from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.realtime.db_poller import SourceReadRequest, SourceReadResult
from metroliza.industrial.realtime.offset_store import StreamOffsetStore
from metroliza.industrial.realtime.realtime_service import RealtimeIndustrialService
from metroliza.industrial.realtime.stream_config import RealtimeStreamConfig, StreamPollPolicy
from metroliza.industrial.realtime.stream_contracts import StreamOffset


@dataclass
class FakeReader:
    result: SourceReadResult
    calls: int = 0

    def fetch_rows(self, request: SourceReadRequest) -> SourceReadResult:
        self.calls += 1
        return self.result


def _profile(db_path):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="line_a",
        database_type="mysql",
        source_object_name="measurements",
        host="db.example.invalid",
        port=3306,
        database_name="process",
        allowed_columns=("record_id", "process_timestamp", "metric_value", "station"),
        timestamp_column="process_timestamp",
        default_pagination_column="record_id",
    )


def _config(source_profile_id: int, *, detectors=("spec_limits",)):
    return RealtimeStreamConfig(
        source_profile_id=source_profile_id,
        stream_key="diameter",
        signal_key="diameter",
        metric_column="metric_value",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        segment_fields=("station",),
        usl=10.0,
        detectors=detectors,
        policy=StreamPollPolicy(batch_limit=10, timeout_seconds=5, history_limit=20),
    )


def test_realtime_service_cycle_persists_samples_events_and_advances_offset(tmp_path):
    db_path = str(tmp_path / "cycle.db")
    profile = _profile(db_path)
    reader = FakeReader(
        SourceReadResult(
            rows=(
                {
                    "record_id": "100",
                    "process_timestamp": "2026-06-13T10:00:00Z",
                    "metric_value": "12.5",
                    "station": "S1",
                },
            )
        )
    )

    result = RealtimeIndustrialService(db_path).poll_stream(
        profile=profile,
        config=_config(profile.id),
        reader=reader,
        now="2026-06-13T10:00:05Z",
    )
    offset = StreamOffsetStore(db_path).get_offset(
        source_profile_id=profile.id,
        stream_key="diameter",
    )
    events = AnomalyEventRepository(db_path).list_open_events()

    assert result.status == "success"
    assert result.rows_fetched == 1
    assert result.samples_inserted == 1
    assert result.events_created == 1
    assert result.cursor_value == "100"
    assert result.event_time_watermark == "2026-06-13T10:00:00Z"
    assert result.lag_seconds == 5.0
    assert offset is not None
    assert offset.cursor_value == "100"
    assert len(events) == 1
    assert events[0].severity == "critical"
    assert "USL" in events[0].explanation


def test_realtime_service_no_rows_keeps_existing_offset_and_reports_idle(tmp_path):
    db_path = str(tmp_path / "no_rows.db")
    profile = _profile(db_path)
    StreamOffsetStore(db_path).upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="diameter",
            cursor_column="record_id",
            cursor_value="100",
            event_time_watermark="2026-06-13T10:00:00Z",
            status="idle",
        )
    )

    result = RealtimeIndustrialService(db_path).poll_stream(
        profile=profile,
        config=_config(profile.id),
        reader=FakeReader(SourceReadResult(rows=())),
        now="2026-06-13T10:01:00Z",
    )
    offset = StreamOffsetStore(db_path).get_offset(
        source_profile_id=profile.id,
        stream_key="diameter",
    )

    assert result.status == "idle"
    assert result.rows_fetched == 0
    assert result.samples_inserted == 0
    assert offset is not None
    assert offset.cursor_value == "100"
    assert offset.event_time_watermark == "2026-06-13T10:00:00Z"


def test_realtime_service_duplicate_rows_still_allow_offset_advancement(tmp_path):
    db_path = str(tmp_path / "duplicates.db")
    profile = _profile(db_path)
    reader = FakeReader(
        SourceReadResult(
            rows=(
                {
                    "record_id": "100",
                    "process_timestamp": "2026-06-13T10:00:00Z",
                    "metric_value": "9.5",
                    "station": "S1",
                },
            )
        )
    )
    service = RealtimeIndustrialService(db_path)
    first = service.poll_stream(profile=profile, config=_config(profile.id), reader=reader)
    second = service.poll_stream(profile=profile, config=_config(profile.id), reader=reader)

    assert first.samples_inserted == 1
    assert second.samples_inserted == 0
    assert second.samples_skipped == 1
    assert second.cursor_value == "100"


def test_realtime_service_fetch_error_redacts_error_and_does_not_advance_cursor(tmp_path):
    db_path = str(tmp_path / "fetch_error.db")
    profile = _profile(db_path)
    StreamOffsetStore(db_path).upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="diameter",
            cursor_column="record_id",
            cursor_value="100",
            status="idle",
        )
    )

    result = RealtimeIndustrialService(db_path).poll_stream(
        profile=profile,
        config=_config(profile.id),
        reader=FakeReader(SourceReadResult(error="password=secret123 host=db.example.invalid")),
    )
    offset = StreamOffsetStore(db_path).get_offset(
        source_profile_id=profile.id,
        stream_key="diameter",
    )

    assert result.status == "error"
    assert result.error is not None
    assert "secret123" not in result.error
    assert "db.example.invalid" not in result.error
    assert offset is not None
    assert offset.cursor_value == "100"
    assert offset.status == "error"


def test_realtime_service_detector_error_is_partial_without_blocking_offset(tmp_path):
    db_path = str(tmp_path / "detector_error.db")
    profile = _profile(db_path)

    result = RealtimeIndustrialService(db_path).poll_stream(
        profile=profile,
        config=_config(profile.id, detectors=("unknown_detector",)),
        reader=FakeReader(
            SourceReadResult(
                rows=(
                    {
                        "record_id": "100",
                        "process_timestamp": "2026-06-13T10:00:00Z",
                        "metric_value": "9.5",
                    },
                )
            )
        ),
    )
    offset = StreamOffsetStore(db_path).get_offset(
        source_profile_id=profile.id,
        stream_key="diameter",
    )

    assert result.status == "partial"
    assert result.samples_inserted == 1
    assert result.events_created == 0
    assert result.diagnostics["detectors"]["errors"]
    assert offset is not None
    assert offset.cursor_value == "100"

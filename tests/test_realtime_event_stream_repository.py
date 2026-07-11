import pytest

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.event_stream import RealtimeStreamEvent
from metroliza.industrial.realtime.event_stream_repository import RealtimeEventStreamRepository
from metroliza.reports.db import sqlite_connection_scope


def _profile(db_path: str):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
    )


def test_stream_event_append_is_ordered_and_idempotent(tmp_path):
    db_path = str(tmp_path / "stream.db")
    profile = _profile(db_path)
    repository = RealtimeEventStreamRepository(db_path)

    first = repository.append_event(
        RealtimeStreamEvent(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            event_type="sample_batch_committed",
            aggregate_type="sample_batch",
            idempotency_key="batch-1",
            event_time="2026-06-13T10:00:00Z",
            payload={"sample_ids": [1], "password": "super-secret"},
        )
    )
    duplicate = repository.append_event(
        RealtimeStreamEvent(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            event_type="sample_batch_committed",
            aggregate_type="sample_batch",
            idempotency_key="batch-1",
            event_time="2026-06-13T10:00:00Z",
            payload={"sample_ids": [1]},
        )
    )
    second = repository.append_event(
        RealtimeStreamEvent(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            event_type="sample_batch_committed",
            aggregate_type="sample_batch",
            idempotency_key="batch-2",
            event_time="2026-06-13T10:01:00Z",
            payload={"sample_ids": [2]},
        )
    )

    events = repository.read_events_after(
        source_profile_id=profile.id,
        stream_key="cycle_time",
        after_event_id=0,
    )
    newer_events = repository.read_events_after(
        source_profile_id=profile.id,
        stream_key="cycle_time",
        after_event_id=first.event_ids[0],
    )

    assert first.inserted == 1
    assert duplicate.inserted == 0
    assert duplicate.event_ids == first.event_ids
    assert second.event_ids[0] > first.event_ids[0]
    assert [event.event_id for event in events] == [first.event_ids[0], second.event_ids[0]]
    assert [event.event_id for event in newer_events] == [second.event_ids[0]]
    assert events[0].payload["password"] == "<redacted>"
    assert "super-secret" not in str(events[0].payload)


def test_stream_event_idempotency_is_scoped_to_source_stream(tmp_path):
    db_path = str(tmp_path / "stream-scope.db")
    profile = _profile(db_path)
    repository = RealtimeEventStreamRepository(db_path)

    line_a = repository.append_event(
        RealtimeStreamEvent(
            source_profile_id=profile.id,
            stream_key="line_a",
            event_type="sample_batch_committed",
            aggregate_type="sample_batch",
            idempotency_key="external-batch-1",
            event_time="2026-06-13T10:00:00Z",
            payload={"sample_ids": [1]},
        )
    )
    line_b = repository.append_event(
        RealtimeStreamEvent(
            source_profile_id=profile.id,
            stream_key="line_b",
            event_type="sample_batch_committed",
            aggregate_type="sample_batch",
            idempotency_key="external-batch-1",
            event_time="2026-06-13T10:00:00Z",
            payload={"sample_ids": [2]},
        )
    )

    assert line_a.inserted == 1
    assert line_b.inserted == 1
    assert line_b.event_ids[0] > line_a.event_ids[0]


def test_consumer_offsets_are_independent_and_failure_is_redacted(tmp_path):
    db_path = str(tmp_path / "offsets.db")
    profile = _profile(db_path)
    repository = RealtimeEventStreamRepository(db_path)

    detector_offset = repository.update_consumer_offset(
        consumer_key="detectors",
        source_profile_id=profile.id,
        stream_key="cycle_time",
        last_event_id=10,
    )
    dashboard_offset = repository.update_consumer_offset(
        consumer_key="dashboard",
        source_profile_id=profile.id,
        stream_key="cycle_time",
        last_event_id=2,
    )
    failed_offset = repository.mark_consumer_failure(
        consumer_key="detectors",
        source_profile_id=profile.id,
        stream_key="cycle_time",
        error="driver password=secret123 failed",
    )

    assert detector_offset.last_event_id == 10
    assert dashboard_offset.last_event_id == 2
    assert failed_offset.last_event_id == 10
    assert failed_offset.status == "failed"
    assert failed_offset.failure_count == 1
    assert failed_offset.last_error == "driver password=<redacted> failed"


def test_stale_consumer_offset_update_cannot_rewind_newer_progress(tmp_path):
    db_path = str(tmp_path / "monotonic-offset.db")
    profile = _profile(db_path)
    repository = RealtimeEventStreamRepository(db_path)

    advanced = repository.update_consumer_offset(
        consumer_key="detectors",
        source_profile_id=profile.id,
        stream_key="cycle_time",
        last_event_id=10,
        updated_at="2026-07-09T10:00:00Z",
    )
    stale = repository.update_consumer_offset(
        consumer_key="detectors",
        source_profile_id=profile.id,
        stream_key="cycle_time",
        last_event_id=5,
        updated_at="2026-07-09T10:01:00Z",
    )

    assert advanced.last_event_id == 10
    assert stale.last_event_id == 10
    assert stale.updated_at == "2026-07-09T10:00:00.000000Z"


def test_stale_consumer_failure_cannot_overwrite_newer_progress(tmp_path):
    db_path = str(tmp_path / "stale-failure.db")
    profile = _profile(db_path)
    repository = RealtimeEventStreamRepository(db_path)
    repository.update_consumer_offset(
        consumer_key="detectors",
        source_profile_id=profile.id,
        stream_key="cycle_time",
        last_event_id=2,
    )
    advanced = repository.update_consumer_offset(
        consumer_key="detectors",
        source_profile_id=profile.id,
        stream_key="cycle_time",
        last_event_id=10,
        updated_at="2026-07-09T10:00:00Z",
    )

    stale_failure = repository.mark_consumer_failure(
        consumer_key="detectors",
        source_profile_id=profile.id,
        stream_key="cycle_time",
        error="driver password=secret123 failed",
        expected_last_event_id=2,
        updated_at="2026-07-09T10:01:00Z",
    )

    assert stale_failure == advanced
    assert stale_failure.last_event_id == 10
    assert stale_failure.status == "idle"
    assert stale_failure.failure_count == 0
    assert stale_failure.last_error is None


def test_schema_uses_event_id_column_for_stream_events(tmp_path):
    db_path = str(tmp_path / "schema.db")
    _profile(db_path)
    RealtimeEventStreamRepository(db_path).ensure_schema()

    with sqlite_connection_scope(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(industrial_realtime_stream_events)")
        }

    assert "event_id" in columns
    assert "id" not in columns


@pytest.mark.parametrize("invalid_id", [True, 1.5, 2**63])
def test_event_stream_repository_rejects_non_exact_ids(tmp_path, invalid_id):
    db_path = str(tmp_path / "invalid-id.db")
    profile = _profile(db_path)
    repository = RealtimeEventStreamRepository(db_path)

    with pytest.raises(ValueError, match="positive integer"):
        repository.append_event(
            RealtimeStreamEvent(
                source_profile_id=invalid_id,
                stream_key="cycle_time",
                event_type="sample_batch_committed",
                aggregate_type="sample_batch",
                idempotency_key="bad-id",
            )
        )

    assert profile.id == 1

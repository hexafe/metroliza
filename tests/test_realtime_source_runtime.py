from __future__ import annotations

from dataclasses import dataclass

from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.db_poller import SourceReadRequest, SourceReadResult
from metroliza.industrial.realtime.source_runtime import RealtimeSourceRuntime
from metroliza.industrial.realtime.stream_config import RealtimeStreamConfig, StreamPollPolicy


@dataclass
class FakeReader:
    rows: tuple[dict[str, str], ...]

    def fetch_rows(self, request: SourceReadRequest) -> SourceReadResult:
        return SourceReadResult(rows=self.rows)


def test_realtime_source_runtime_polls_enabled_configs_once(tmp_path):
    db_path = str(tmp_path / "runtime.db")
    profile = IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="line_a",
        database_type="mysql",
        source_object_name="measurements",
        host="db.example.invalid",
        port=3306,
        database_name="process",
        allowed_columns=("record_id", "process_timestamp", "metric_value"),
    )
    enabled = RealtimeStreamConfig(
        source_profile_id=profile.id,
        stream_key="diameter",
        signal_key="diameter",
        metric_column="metric_value",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        policy=StreamPollPolicy(batch_limit=5),
    )
    disabled = RealtimeStreamConfig(
        source_profile_id=profile.id,
        stream_key="disabled",
        signal_key="disabled",
        metric_column="metric_value",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        enabled=False,
    )

    results, status = RealtimeSourceRuntime(db_path).poll_once(
        profile=profile,
        configs=(enabled, disabled),
        reader=FakeReader(
            rows=(
                {
                    "record_id": "100",
                    "process_timestamp": "2026-06-13T10:00:00Z",
                    "metric_value": "9.5",
                },
            )
        ),
    )

    assert len(results) == 1
    assert status.cycles == 1
    assert status.succeeded == 1
    assert status.rows_fetched == 1

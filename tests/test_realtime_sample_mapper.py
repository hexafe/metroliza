from __future__ import annotations

from metroliza.industrial.realtime.sample_mapper import (
    SignalSampleMapping,
    map_row_to_sample,
    map_rows_to_samples,
)
from metroliza.industrial.realtime.stream_config import RealtimeStreamConfig
from metroliza.industrial.realtime.stream_contracts import SignalDefinition


def _mapping(metric_column: str = "metric_value", signal_id: int = 10):
    config = RealtimeStreamConfig(
        source_profile_id=1,
        stream_key=f"{metric_column}_stream",
        signal_key=metric_column,
        metric_column=metric_column,
        event_time_column="process_timestamp",
        record_key_column="record_id",
        segment_fields=("station",),
        context_columns=("part_number",),
    ).validated()
    signal = SignalDefinition(
        id=signal_id,
        source_profile_id=1,
        signal_key=metric_column,
        metric_name=metric_column,
    )
    return SignalSampleMapping(config=config, signal=signal)


def test_map_row_to_sample_keeps_operator_context_and_redacts_raw_record():
    sample, reason = map_row_to_sample(
        {
            "record_id": "ROW-1",
            "process_timestamp": "2026-06-13T10:00:00+00:00",
            "metric_value": "10.25",
            "station": "S1",
            "part_number": "PN-1",
            "password": "secret123",
        },
        _mapping(),
        ingest_time="2026-06-13T10:00:01Z",
    )

    assert reason is None
    assert sample is not None
    assert sample.event_time == "2026-06-13T10:00:00Z"
    assert sample.value == 10.25
    assert sample.station == "S1"
    assert sample.part_number == "PN-1"
    assert sample.segment_key == {"station": "S1"}
    assert "secret123" not in repr(sample.raw_record)


def test_map_rows_to_samples_supports_multiple_signal_mappings():
    result = map_rows_to_samples(
        [
            {
                "record_id": "ROW-1",
                "process_timestamp": "2026-06-13T10:00:00Z",
                "diameter": "10.2",
                "pressure": "2.5",
            }
        ],
        [_mapping("diameter", signal_id=11), _mapping("pressure", signal_id=12)],
    )

    assert result.stats.rows_processed == 1
    assert result.stats.samples_mapped == 2
    assert {sample.metric_name for sample in result.samples} == {"diameter", "pressure"}


def test_map_rows_to_samples_counts_invalid_rows_without_crashing():
    result = map_rows_to_samples(
        [
            {"record_id": "ROW-1", "process_timestamp": "2026-06-13T10:00:00Z", "metric_value": "10"},
            {"record_id": "", "process_timestamp": "2026-06-13T10:00:00Z", "metric_value": "10"},
            {"record_id": "ROW-2", "process_timestamp": "not-a-time", "metric_value": "10"},
            {"record_id": "ROW-3", "process_timestamp": "2026-06-13T10:00:00Z", "metric_value": "nan"},
        ],
        _mapping(),
    )

    assert result.stats.rows_processed == 4
    assert result.stats.samples_mapped == 1
    assert result.stats.missing_required == 1
    assert result.stats.invalid_timestamp == 1
    assert result.stats.non_numeric == 1

from metroliza.industrial.realtime.sample_mapper import map_rows_to_samples
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import SignalDefinition


def _config():
    return RealtimePollConfig(
        source_profile_id=1,
        stream_key="process_metrics",
        cursor_column="event_id",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        signal_keys=("cycle_time", "temperature"),
        signal_columns={
            "cycle_time": "cycle_time_s",
            "temperature": "temperature_c",
        },
        segment_fields=("station", "line"),
    )


def _signals():
    return {
        "cycle_time": SignalDefinition(
            id=10,
            source_profile_id=1,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
        ),
        "temperature": SignalDefinition(
            id=11,
            source_profile_id=1,
            signal_key="temperature",
            metric_name="temperature_c",
        ),
    }


def test_sample_mapper_maps_multiple_signals_and_redacts_raw_record():
    result = map_rows_to_samples(
        [
            {
                "event_id": "100",
                "record_id": "row-100",
                "process_timestamp": "2026-06-13T10:00:00Z",
                "cycle_time_s": "10.5",
                "temperature_c": "205",
                "station": "S1",
                "line": "L1",
                "password": "secret",
                "reference": "REF-1",
                "work_order": "mysql://operator:secret@db/prod",
            }
        ],
        config=_config(),
        signals=_signals(),
        ingest_time="2026-06-13T10:00:05Z",
    )

    assert result.stats.rows_seen == 1
    assert result.stats.mapped == 2
    assert result.cursor_value == "100"
    assert result.event_time_watermark == "2026-06-13T10:00:00Z"
    assert {sample.signal_id for sample in result.samples} == {10, 11}
    first = result.samples[0]
    assert first.segment_key == {"station": "S1", "line": "L1"}
    assert "password" not in first.raw_record
    assert first.raw_record["work_order"] == "mysql://operator:<redacted>@db/prod"


def test_sample_mapper_skips_invalid_values_without_crashing():
    result = map_rows_to_samples(
        [
            {
                "event_id": "101",
                "record_id": "row-101",
                "process_timestamp": "2026-06-13T10:01:00Z",
                "cycle_time_s": "not-number",
                "temperature_c": "inf",
            },
            {
                "event_id": "102",
                "record_id": "",
                "process_timestamp": "2026-06-13T10:02:00Z",
                "cycle_time_s": "10",
                "temperature_c": "200",
            },
        ],
        config=_config(),
        signals=_signals(),
    )

    assert result.samples == ()
    assert result.stats.skipped_non_numeric == 1
    assert result.stats.skipped_non_finite == 1
    assert result.stats.skipped_missing == 2

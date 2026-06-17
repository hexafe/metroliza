from decimal import Decimal

import pandas as pd

from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.offset_store import StreamOffsetStore
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_contracts import (
    IndustrialSample,
    SignalDefinition,
    StreamOffset,
)


def _source_profile(db_path):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
    )


def test_signal_definition_upsert_and_sample_idempotency(tmp_path):
    db_path = str(tmp_path / "samples.db")
    profile = _source_profile(db_path)
    repository = RealtimeSampleRepository(db_path)

    signal = repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
            unit="s",
            nominal=10.0,
            lsl=8.0,
            usl=12.0,
            lower_warning=8.5,
            upper_warning=11.5,
            segment_fields=("station", "part_number"),
        )
    )
    updated = repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
            unit="seconds",
            enabled=False,
        )
    )

    assert signal.id == updated.id
    assert updated.unit == "seconds"
    assert updated.enabled is False

    sample = IndustrialSample(
        source_profile_id=profile.id,
        signal_id=signal.id,
        source_record_key="ROW-1",
        event_time="2026-06-13T10:00:00Z",
        metric_name="cycle_time_s",
        value=10.2,
        station="S1",
        segment_key={"station": "S1"},
        quality_flags=("ok",),
        raw_record={"event_id": "ROW-1", "cycle_time_s": 10.2},
    )
    first = repository.insert_samples([sample])
    second = repository.insert_samples([sample])
    loaded = repository.list_samples(signal_id=signal.id)

    assert first.processed == 1
    assert first.inserted == 1
    assert first.skipped == 0
    assert second.inserted == 0
    assert second.skipped == 1
    assert first.sample_ids == second.sample_ids
    assert len(loaded) == 1
    assert loaded[0].source_record_key == "ROW-1"
    assert loaded[0].segment_key == {"station": "S1"}
    assert loaded[0].quality_flags == ("ok",)
    assert loaded[0].raw_record == {"event_id": "ROW-1", "cycle_time_s": 10.2}


def test_insert_samples_accepts_generator_batches(tmp_path):
    db_path = str(tmp_path / "sample_generator.db")
    profile = _source_profile(db_path)
    repository = RealtimeSampleRepository(db_path)
    signal = repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
        )
    )

    def _samples():
        for index in range(2):
            yield IndustrialSample(
                source_profile_id=profile.id,
                signal_id=signal.id,
                source_record_key=f"ROW-{index}",
                event_time=f"2026-06-13T10:0{index}:00Z",
                metric_name="cycle_time_s",
                value=10.0 + index,
            )

    result = repository.insert_samples(_samples())

    assert result.processed == 2
    assert result.inserted == 2
    assert len(result.sample_ids) == 2


def test_insert_samples_normalizes_datetime_like_raw_record_scalars(tmp_path):
    db_path = str(tmp_path / "sample_json_safe.db")
    profile = _source_profile(db_path)
    repository = RealtimeSampleRepository(db_path)
    signal = repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
        )
    )

    result = repository.insert_samples(
        [
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=signal.id,
                source_record_key="ROW-TS",
                event_time="2026-06-13T10:00:00Z",
                metric_name="cycle_time_s",
                value=10.0,
                segment_key={"observed_at": pd.Timestamp("2026-06-13T10:00:00")},
                raw_record={
                    "event_time": pd.Timestamp("2026-06-13T10:00:00"),
                    "missing": pd.NaT,
                    "amount": Decimal("10.25"),
                    "not_a_number": float("nan"),
                },
            )
        ]
    )
    loaded = repository.list_samples(signal_id=signal.id)

    assert result.inserted == 1
    assert loaded[0].segment_key == {"observed_at": "2026-06-13T10:00:00"}
    assert loaded[0].raw_record == {
        "amount": "10.25",
        "event_time": "2026-06-13T10:00:00",
        "missing": None,
        "not_a_number": None,
    }


def test_list_samples_by_ids_loads_targeted_rows_in_chunks(tmp_path):
    db_path = str(tmp_path / "sample_ids.db")
    profile = _source_profile(db_path)
    repository = RealtimeSampleRepository(db_path)
    cycle_signal = repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_name="cycle_time_s",
        )
    )
    pressure_signal = repository.upsert_signal_definition(
        SignalDefinition(
            source_profile_id=profile.id,
            signal_key="pressure",
            metric_name="pressure_bar",
        )
    )
    result = repository.insert_samples(
        [
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=cycle_signal.id,
                source_record_key="ROW-1",
                event_time="2026-06-13T10:00:00Z",
                metric_name="cycle_time_s",
                value=10.0,
            ),
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=pressure_signal.id,
                source_record_key="ROW-2",
                event_time="2026-06-13T10:01:00Z",
                metric_name="pressure_bar",
                value=2.4,
            ),
            IndustrialSample(
                source_profile_id=profile.id,
                signal_id=cycle_signal.id,
                source_record_key="ROW-3",
                event_time="2026-06-13T10:02:00Z",
                metric_name="cycle_time_s",
                value=11.0,
            ),
        ]
    )

    loaded = repository.list_samples_by_ids(
        (result.sample_ids[2], result.sample_ids[0], result.sample_ids[2], 999_999),
        chunk_size=1,
    )

    assert [sample.source_record_key for sample in loaded] == ["ROW-3", "ROW-1"]


def test_stream_offset_upsert_replaces_cursor(tmp_path):
    db_path = str(tmp_path / "offsets.db")
    profile = _source_profile(db_path)
    store = StreamOffsetStore(db_path)

    first = store.upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="100",
            event_time_watermark="2026-06-13T10:00:00Z",
            lag_seconds=4.0,
            status="running",
        )
    )
    second = store.upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="101",
            event_time_watermark="2026-06-13T10:01:00Z",
            lag_seconds=2.0,
            status="idle",
        )
    )

    assert first.id == second.id
    assert second.cursor_value == "101"
    assert second.event_time_watermark == "2026-06-13T10:01:00Z"
    assert second.lag_seconds == 2.0
    assert second.status == "idle"


def test_stream_offset_watermark_is_scoped_by_profile_and_stream(tmp_path):
    db_path = str(tmp_path / "offset_scope.db")
    profile = _source_profile(db_path)
    store = StreamOffsetStore(db_path)

    cycle_time = store.upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="cycle_time",
            cursor_column="event_id",
            cursor_value="102",
            event_time_watermark="2026-06-13T10:02:00Z",
            status="idle",
        )
    )
    pressure = store.upsert_offset(
        StreamOffset(
            source_profile_id=profile.id,
            stream_key="pressure",
            cursor_column="event_id",
            cursor_value="77",
            event_time_watermark="2026-06-13T09:59:00Z",
            status="idle",
        )
    )

    loaded_cycle_time = store.get_offset(
        source_profile_id=profile.id,
        stream_key="cycle_time",
    )
    loaded_pressure = store.get_offset(
        source_profile_id=profile.id,
        stream_key="pressure",
    )

    assert loaded_cycle_time is not None
    assert loaded_pressure is not None
    assert loaded_cycle_time.id == cycle_time.id
    assert loaded_cycle_time.cursor_value == "102"
    assert loaded_cycle_time.event_time_watermark == "2026-06-13T10:02:00Z"
    assert loaded_pressure.id == pressure.id
    assert loaded_pressure.cursor_value == "77"
    assert loaded_pressure.event_time_watermark == "2026-06-13T09:59:00Z"

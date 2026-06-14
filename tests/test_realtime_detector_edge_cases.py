import math
from pathlib import Path

from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.anomaly.contracts import DetectorContext, DetectorState
from metroliza.industrial.anomaly.detectors import (
    IQRDetector,
    MadZScoreDetector,
    RollingZScoreDetector,
    SpecLimitDetector,
)
from metroliza.industrial.realtime.replay import (
    ReplayRequest,
    replay_industrial_stream,
    rows_to_samples,
    run_detectors_for_samples,
)
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


def _request() -> ReplayRequest:
    return ReplayRequest(
        input_file="unused.csv",
        database="unused.db",
        source_profile_id=7,
        signal_key="cycle_time",
        metric_column="cycle_time_s",
        event_time_column="event_time",
        record_key_column="event_id",
    )


def _sample(value, *, sample_id: int = 1, event_time: str = "2026-06-13T10:00:00Z"):
    return IndustrialSample(
        id=sample_id,
        source_profile_id=7,
        signal_id=42,
        source_record_key=f"ROW-{sample_id}",
        event_time=event_time,
        metric_name="cycle_time_s",
        value=value,
    )


def _signal() -> SignalDefinition:
    return SignalDefinition(
        id=42,
        source_profile_id=7,
        signal_key="cycle_time",
        metric_name="cycle_time_s",
        lsl=8.0,
        usl=12.0,
    )


def _source_profile(db_path: str):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
    )


def test_rows_to_samples_skips_invalid_numbers_and_missing_timestamps():
    rows = [
        {"event_id": "ROW-1", "event_time": "2026-06-13T10:00:00Z", "cycle_time_s": "10.0"},
        {"event_id": "ROW-2", "event_time": "2026-06-13T10:01:00Z", "cycle_time_s": "NaN"},
        {"event_id": "ROW-3", "event_time": "2026-06-13T10:02:00Z", "cycle_time_s": "bad"},
        {"event_id": "ROW-4", "event_time": "2026-06-13T10:03:00Z", "cycle_time_s": "inf"},
        {"event_id": "ROW-5", "event_time": "", "cycle_time_s": "10.5"},
    ]

    samples = rows_to_samples(rows, _request(), signal_id=42)

    assert [sample.source_record_key for sample in samples] == ["ROW-1"]
    assert samples[0].value == 10.0


def test_detectors_return_no_events_for_invalid_sample_values():
    signal = _signal()
    detectors = (
        (SpecLimitDetector(), DetectorContext(signal=signal)),
        (
            IQRDetector(),
            DetectorContext(signal=signal, baseline={"n": 25, "q1": 9.0, "q3": 11.0, "iqr": 2.0}),
        ),
        (
            MadZScoreDetector(),
            DetectorContext(signal=signal, baseline={"n": 30, "median": 10.0, "mad": 1.0}),
        ),
        (
            RollingZScoreDetector(min_n=4),
            DetectorContext(signal=signal, state=DetectorState(values=(9.0, 10.0, 11.0, 10.0))),
        ),
    )

    for invalid_value in (math.nan, math.inf, -math.inf, "not-a-number"):
        sample = _sample(invalid_value)
        for detector, context in detectors:
            assert detector.score_one(sample, context) is None


def test_statistical_detectors_skip_zero_spread_and_insufficient_history():
    sample = _sample(20.0)

    assert IQRDetector().score_one(sample, DetectorContext(baseline={"n": 19})) is None
    assert (
        IQRDetector().score_one(
            sample,
            DetectorContext(baseline={"n": 25, "q1": 10.0, "q3": 10.0, "iqr": 0.0}),
        )
        is None
    )
    assert MadZScoreDetector().score_one(sample, DetectorContext(baseline={"n": 19})) is None
    assert (
        MadZScoreDetector().score_one(
            sample,
            DetectorContext(baseline={"n": 30, "median": 10.0, "mad": 0.0}),
        )
        is None
    )
    assert (
        RollingZScoreDetector(min_n=4).score_one(
            sample,
            DetectorContext(state=DetectorState(values=(10.0,))),
        )
        is None
    )
    assert (
        RollingZScoreDetector(min_n=4).score_one(
            sample,
            DetectorContext(state=DetectorState(values=(10.0, 10.0, 10.0, 10.0))),
        )
        is None
    )


def test_run_detectors_scores_out_of_order_events_by_event_time():
    signal = _signal()
    stable_samples = [
        _sample(
            9.0 if index % 2 else 11.0,
            sample_id=index + 2,
            event_time=f"2026-06-13T10:{index:02d}:00Z",
        )
        for index in range(30)
    ]
    old_outlier = _sample(40.0, sample_id=1, event_time="2026-06-13T09:59:00Z")

    events = run_detectors_for_samples(
        [*stable_samples, old_outlier],
        signal=signal,
        detectors=("rolling_zscore",),
    )

    assert events == []


def test_replay_duplicate_record_keys_are_skipped_before_event_counting(tmp_path):
    db_path = str(tmp_path / "duplicate_keys.db")
    profile = _source_profile(db_path)
    csv_path = Path(tmp_path / "duplicate_keys.csv")
    csv_path.write_text(
        "\n".join(
            [
                "event_id,event_time,cycle_time_s",
                "ROW-1,2026-06-13T10:00:00Z,13.5",
                "ROW-1,2026-06-13T10:01:00Z,14.0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=str(csv_path),
            database=db_path,
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_column="cycle_time_s",
            event_time_column="event_time",
            record_key_column="event_id",
            detectors=("spec_limits",),
            usl=12.0,
        )
    )

    assert summary.samples_processed == 2
    assert summary.samples_inserted == 1
    assert summary.samples_skipped == 1
    assert summary.detector_events_created == 1
    assert summary.event_counts == {"spec_limits/critical": 1}

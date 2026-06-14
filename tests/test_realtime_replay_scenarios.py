from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from scripts.generate_realtime_industrial_fixtures import main as generate_fixtures
from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.detectors import StaleSourceDetector
from metroliza.industrial.realtime.replay import (
    ReplayRequest,
    load_csv_rows,
    rows_to_samples,
    run_detectors_for_samples,
)
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "industrial_realtime"
BASELINE = {"n": 40, "q1": 99.0, "q3": 101.0, "iqr": 2.0, "median": 100.0, "mad": 1.0}


def _signal(**overrides) -> SignalDefinition:
    values = {
        "id": 77,
        "source_profile_id": 1,
        "signal_key": "cycle_time",
        "metric_name": "metric_value",
        "nominal": 100.0,
        "lsl": 90.0,
        "usl": 110.0,
        "lower_warning": 95.0,
        "upper_warning": 105.0,
    }
    values.update(overrides)
    return SignalDefinition(**values)


def _samples(filename: str, *, signal: SignalDefinition | None = None) -> tuple[IndustrialSample, ...]:
    active_signal = signal or _signal()
    rows = load_csv_rows(str(FIXTURE_DIR / filename))
    request = ReplayRequest(
        input_file=str(FIXTURE_DIR / filename),
        database="unused.db",
        source_profile_id=active_signal.source_profile_id,
        signal_key=active_signal.signal_key,
        metric_column="metric_value",
        event_time_column="process_timestamp",
        record_key_column="record_id",
    )
    samples = rows_to_samples(rows, request, signal_id=active_signal.id or 1)
    return tuple(replace(sample, id=index + 1) for index, sample in enumerate(samples))


def _events(
    filename: str,
    *,
    detectors: tuple[str, ...],
    signal: SignalDefinition | None = None,
    baseline: dict | None = None,
):
    active_signal = signal or _signal()
    return run_detectors_for_samples(
        _samples(filename, signal=active_signal),
        signal=active_signal,
        detectors=detectors,
        baseline=baseline or {},
    )


def test_fixture_generator_is_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert generate_fixtures(["--output", str(first), "--force"]) == 0
    assert generate_fixtures(["--output", str(second), "--force"]) == 0

    first_files = sorted(path.name for path in first.glob("*.csv"))
    second_files = sorted(path.name for path in second.glob("*.csv"))
    assert first_files == second_files
    for filename in first_files:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()


def test_stable_normal_process_has_no_spec_or_rolling_false_positive():
    events = _events(
        "stable_normal_process.csv",
        detectors=("spec_limits", "rolling_zscore"),
    )

    assert events == []


def test_single_high_outlier_triggers_explainable_statistical_and_spec_events():
    events = _events(
        "single_high_outlier.csv",
        detectors=("spec_limits", "iqr", "mad_zscore", "rolling_zscore"),
        baseline=BASELINE,
    )

    assert {(event.detector_key, event.severity) for event in events} == {
        ("spec_limits", "critical"),
        ("iqr", "major"),
        ("mad_zscore", "major"),
        ("rolling_zscore", "major"),
    }
    explanations = "\n".join(event.explanation for event in events)
    assert "above USL 110" in explanations
    assert "outside IQR fence" in explanations
    assert "robust z-score" in explanations
    assert "rolling z-score" in explanations


def test_single_low_outlier_triggers_explainable_statistical_and_spec_events():
    events = _events(
        "single_low_outlier.csv",
        detectors=("spec_limits", "iqr", "mad_zscore", "rolling_zscore"),
        baseline=BASELINE,
    )

    assert {(event.detector_key, event.severity) for event in events} == {
        ("spec_limits", "critical"),
        ("iqr", "major"),
        ("mad_zscore", "major"),
        ("rolling_zscore", "major"),
    }
    explanations = "\n".join(event.explanation for event in events)
    assert "below LSL 90" in explanations
    assert "outside IQR fence" in explanations
    assert "robust z-score" in explanations
    assert "rolling z-score" in explanations


def test_usl_lsl_fixture_reports_two_critical_breaches():
    events = _events("usl_lsl_breach.csv", detectors=("spec_limits",))

    assert [event.severity for event in events] == ["critical", "critical"]
    assert "above USL 110" in events[0].explanation
    assert "below LSL 90" in events[1].explanation


def test_warning_limit_fixture_reports_warning_without_spec_breach():
    events = _events("warning_limit_breach.csv", detectors=("spec_limits",))

    assert len(events) == 1
    assert events[0].severity == "warning"
    assert "above warning limit 105" in events[0].explanation
    assert "USL" not in events[0].explanation


def test_gradual_drift_upward_is_detected_by_warning_limits_only_in_mvp():
    events = _events("gradual_drift_upward.csv", detectors=("spec_limits",))

    assert 1 <= len(events) <= 20
    assert {event.severity for event in events} == {"warning"}
    assert all("above warning limit 105" in event.explanation for event in events)


def test_sudden_step_change_has_at_least_one_rolling_zscore_event():
    events = _events(
        "sudden_step_change.csv",
        detectors=("rolling_zscore",),
        signal=_signal(lower_warning=None, upper_warning=None, lsl=None, usl=None),
    )

    assert 1 <= len(events) <= 8
    assert all(event.detector_key == "rolling_zscore" for event in events)
    assert "rolling z-score" in events[0].explanation
    assert events[0].threshold["n"] >= 30


def test_stuck_sensor_repeated_value_has_no_statistical_false_positive():
    events = _events(
        "stuck_sensor.csv",
        detectors=("rolling_zscore",),
        signal=_signal(lower_warning=None, upper_warning=None, lsl=None, usl=None),
    )

    assert events == []


def test_missing_stale_data_attaches_source_level_event_to_last_sample():
    signal = _signal()
    samples = _samples("missing_stale_data.csv", signal=signal)

    result = StaleSourceDetector(warning_seconds=300, major_seconds=900).score_one(
        samples[-1],
        DetectorContext(signal=signal, now="2026-06-13T10:20:00Z"),
    )

    assert result is not None
    assert result.severity == "major"
    assert result.sample_id == samples[-1].id
    assert result.context["source_level"] is True
    assert "No new samples" in result.explanation
    assert "1140 seconds" in result.explanation


def test_station_specific_baselines_avoid_cross_station_false_positive():
    signal = _signal(lsl=None, usl=None, lower_warning=None, upper_warning=None)
    samples = _samples("station_segment_baselines.csv", signal=signal)
    station_baselines = {
        "S1": {"n": 24, "q1": 99.7, "q3": 100.3, "iqr": 0.6},
        "S2": {"n": 24, "q1": 149.7, "q3": 150.3, "iqr": 0.6},
    }

    events = []
    for station, baseline in station_baselines.items():
        station_samples = [sample for sample in samples if sample.station == station]
        events.extend(
            run_detectors_for_samples(
                station_samples,
                signal=signal,
                detectors=("iqr",),
                baseline=baseline,
            )
        )

    assert len(events) == 1
    assert events[0].observed_value == 156.0
    assert events[0].severity == "major"
    assert "outside IQR fence" in events[0].explanation


def test_low_sample_count_does_not_over_alert_statistical_detectors():
    events = _events(
        "low_sample_count.csv",
        detectors=("iqr", "mad_zscore", "rolling_zscore"),
        signal=_signal(lsl=None, usl=None, lower_warning=None, upper_warning=None),
        baseline={"n": 10, "q1": 99.0, "q3": 101.0, "iqr": 2.0, "median": 100.0, "mad": 1.0},
    )

    assert events == []

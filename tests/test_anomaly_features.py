import pytest

from metroliza.industrial.anomaly.features import (
    extract_history_features,
    extract_sample_features,
)
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


def _sample(index: int, value: float, event_time: str) -> IndustrialSample:
    return IndustrialSample(
        id=index,
        source_profile_id=1,
        signal_id=7,
        source_record_key=f"ROW-{index}",
        event_time=event_time,
        metric_name="temperature_c",
        value=value,
    )


def test_extract_sample_features_uses_previous_samples_only():
    signal = SignalDefinition(
        id=7,
        source_profile_id=1,
        signal_key="temperature_c",
        metric_name="temperature_c",
        nominal=100.0,
        lsl=90.0,
        usl=110.0,
    )
    history = (
        _sample(1, 96.0, "2026-06-13T10:00:00Z"),
        _sample(2, 100.0, "2026-06-13T10:00:10Z"),
        _sample(3, 102.0, "2026-06-13T10:00:25Z"),
        _sample(4, 104.0, "2026-06-13T10:00:40Z"),
    )
    current = _sample(5, 105.0, "2026-06-13T10:01:10Z")

    features = extract_sample_features(current, history, signal=signal)

    assert features.raw_value == 105.0
    assert features.deviation_from_nominal == 5.0
    assert features.tolerance_band_percent == 75.0
    assert features.rolling_mean == 100.5
    assert features.rolling_std == pytest.approx(2.958039891549808)
    assert features.rolling_median == 101.0
    assert features.rolling_mad == 2.0
    assert features.delta_from_previous == 1.0
    assert features.seconds_since_previous == 30.0


def test_extract_sample_features_returns_missing_history_and_spec_features_as_none():
    current = _sample(1, 10.0, "2026-06-13T10:00:00Z")
    zero_width_signal = SignalDefinition(
        id=7,
        source_profile_id=1,
        signal_key="temperature_c",
        metric_name="temperature_c",
        nominal=10.0,
        lsl=10.0,
        usl=10.0,
    )

    features = extract_sample_features(current)
    invalid_band_features = extract_sample_features(current, signal=zero_width_signal)

    assert features.raw_value == 10.0
    assert features.deviation_from_nominal is None
    assert features.tolerance_band_percent is None
    assert invalid_band_features.deviation_from_nominal == 0.0
    assert invalid_band_features.tolerance_band_percent is None
    assert features.rolling_mean is None
    assert features.rolling_std is None
    assert features.rolling_median is None
    assert features.rolling_mad is None
    assert features.delta_from_previous is None
    assert features.seconds_since_previous is None


def test_extract_history_features_preserves_input_order_and_sliding_window():
    samples = (
        _sample(1, 10.0, "2026-06-13T10:00:00Z"),
        _sample(2, 12.0, "2026-06-13T10:00:05Z"),
        _sample(3, 14.0, "2026-06-13T10:00:12Z"),
        _sample(4, 16.0, "2026-06-13T10:00:20Z"),
    )

    features = extract_history_features(samples, window_size=2)

    assert tuple(item.raw_value for item in features) == (10.0, 12.0, 14.0, 16.0)
    assert [item.rolling_mean for item in features] == [None, 10.0, 11.0, 13.0]
    assert [item.rolling_std for item in features] == [None, 0.0, 1.0, 1.0]
    assert [item.rolling_median for item in features] == [None, 10.0, 11.0, 13.0]
    assert [item.rolling_mad for item in features] == [None, 0.0, 1.0, 1.0]
    assert [item.delta_from_previous for item in features] == [None, 2.0, 2.0, 2.0]
    assert [item.seconds_since_previous for item in features] == [None, 5.0, 7.0, 8.0]


def test_extract_sample_features_validates_window_size_and_current_value():
    current = _sample(1, 10.0, "2026-06-13T10:00:00Z")

    with pytest.raises(ValueError, match="window_size must be positive"):
        extract_sample_features(current, window_size=0)

    with pytest.raises(ValueError, match="sample.value must be a finite number"):
        extract_sample_features(_sample(2, float("nan"), "2026-06-13T10:00:01Z"))

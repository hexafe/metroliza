from metroliza.industrial.anomaly.contracts import DetectorContext, DetectorState
from metroliza.industrial.anomaly.detectors import RollingZScoreDetector
from metroliza.industrial.realtime.stream_contracts import IndustrialSample


def test_rolling_zscore_uses_previous_values_only():
    sample = IndustrialSample(
        id=4,
        source_profile_id=1,
        signal_id=9,
        source_record_key="ROW-4",
        event_time="2026-06-13T10:00:00Z",
        metric_name="torque_nm",
        value=25.0,
    )
    context = DetectorContext(state=DetectorState(values=(10.0, 11.0, 9.0, 10.0)))
    detector = RollingZScoreDetector(min_n=4, threshold=3.0)

    result = detector.score_one(sample, context)
    updated = detector.update_one(sample, context)

    assert result is not None
    assert result.expected_value == 10.0
    assert result.threshold["n"] == 4
    assert result.context["z_score"] > 10
    assert updated.values == (10.0, 11.0, 9.0, 10.0, 25.0)


def test_rolling_zscore_skips_before_minimum_or_zero_std():
    sample = IndustrialSample(
        id=4,
        source_profile_id=1,
        signal_id=9,
        source_record_key="ROW-4",
        event_time="2026-06-13T10:00:00Z",
        metric_name="torque_nm",
        value=25.0,
    )
    detector = RollingZScoreDetector(min_n=4, threshold=3.0)

    assert detector.score_one(sample, DetectorContext(state=DetectorState(values=(10.0,)))) is None
    assert (
        detector.score_one(sample, DetectorContext(state=DetectorState(values=(10.0,) * 4)))
        is None
    )

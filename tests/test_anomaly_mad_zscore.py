from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.detectors import MadZScoreDetector
from metroliza.industrial.realtime.stream_contracts import IndustrialSample


def test_mad_zscore_detector_flags_robust_outlier():
    sample = IndustrialSample(
        id=3,
        source_profile_id=1,
        signal_id=8,
        source_record_key="ROW-3",
        event_time="2026-06-13T10:00:00Z",
        metric_name="pressure_bar",
        value=20.0,
    )
    context = DetectorContext(baseline={"n": 30, "median": 10.0, "mad": 1.0})

    result = MadZScoreDetector().score_one(sample, context)

    assert result is not None
    assert result.severity == "major"
    assert result.score == 6.745
    assert result.context["robust_z"] == 6.745
    assert "robust z-score 6.75" in result.explanation


def test_mad_zscore_detector_skips_zero_mad_or_insufficient_baseline():
    sample = IndustrialSample(
        id=3,
        source_profile_id=1,
        signal_id=8,
        source_record_key="ROW-3",
        event_time="2026-06-13T10:00:00Z",
        metric_name="pressure_bar",
        value=20.0,
    )

    assert MadZScoreDetector().score_one(sample, DetectorContext(baseline={"n": 19})) is None
    assert (
        MadZScoreDetector().score_one(
            sample,
            DetectorContext(baseline={"n": 30, "median": 10.0, "mad": 0.0}),
        )
        is None
    )

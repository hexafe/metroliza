from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.detectors import IQRDetector
from metroliza.industrial.realtime.stream_contracts import IndustrialSample


def test_iqr_detector_flags_value_outside_fence():
    sample = IndustrialSample(
        id=2,
        source_profile_id=1,
        signal_id=7,
        source_record_key="ROW-2",
        event_time="2026-06-13T10:00:00Z",
        metric_name="force_n",
        value=20.0,
    )
    context = DetectorContext(baseline={"n": 25, "q1": 9.0, "q3": 11.0, "iqr": 2.0})

    result = IQRDetector().score_one(sample, context)

    assert result is not None
    assert result.severity == "major"
    assert result.threshold["lower_fence"] == 6.0
    assert result.threshold["upper_fence"] == 14.0
    assert result.score == 3.0
    assert "outside IQR fence" in result.explanation


def test_iqr_detector_skips_insufficient_or_zero_iqr():
    sample = IndustrialSample(
        id=2,
        source_profile_id=1,
        signal_id=7,
        source_record_key="ROW-2",
        event_time="2026-06-13T10:00:00Z",
        metric_name="force_n",
        value=20.0,
    )

    assert IQRDetector().score_one(sample, DetectorContext(baseline={"n": 19})) is None
    assert (
        IQRDetector().score_one(
            sample,
            DetectorContext(baseline={"n": 25, "q1": 10.0, "q3": 10.0, "iqr": 0.0}),
        )
        is None
    )
    assert (
        IQRDetector().score_one(
            sample,
            DetectorContext(baseline={"n": 25, "q1": 9.0, "q3": 11.0, "iqr": -2.0}),
        )
        is None
    )
    assert (
        IQRDetector().score_one(
            sample,
            DetectorContext(baseline={"n": 25, "q1": 11.0, "q3": 9.0, "iqr": 2.0}),
        )
        is None
    )

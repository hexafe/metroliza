from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.detectors import StaleSourceDetector
from metroliza.industrial.realtime.stream_contracts import IndustrialSample


def test_stale_source_attaches_context_event_to_last_sample():
    sample = IndustrialSample(
        id=5,
        source_profile_id=1,
        signal_id=10,
        source_record_key="ROW-5",
        event_time="2026-06-13T10:00:00Z",
        metric_name="cycle_time_s",
        value=10.0,
    )
    detector = StaleSourceDetector(warning_seconds=300, major_seconds=900)
    context = DetectorContext(now="2026-06-13T10:16:00Z")

    result = detector.score_one(sample, context)

    assert result is not None
    assert result.sample_id == 5
    assert result.severity == "major"
    assert result.score == 960.0
    assert result.context["source_level"] is True
    assert result.context["last_sample_id"] == 5
    assert "No new samples for 960 seconds" in result.explanation


def test_stale_source_returns_none_without_attachable_last_sample():
    sample = IndustrialSample(
        source_profile_id=1,
        signal_id=10,
        source_record_key="ROW-5",
        event_time="2026-06-13T10:00:00Z",
        metric_name="cycle_time_s",
        value=10.0,
    )

    assert StaleSourceDetector().score_one(sample, DetectorContext(now="2026-06-13T10:16:00Z")) is None

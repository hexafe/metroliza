from metroliza.industrial.anomaly.contracts import DetectorContext, DetectorState
from metroliza.industrial.anomaly.detectors import RollingZScoreDetector
from metroliza.industrial.realtime.stream_contracts import IndustrialSample


def test_detector_contract_scores_before_state_update():
    detector = RollingZScoreDetector(min_n=3, threshold=2.0)
    sample = IndustrialSample(
        id=10,
        source_profile_id=1,
        signal_id=2,
        source_record_key="ROW-10",
        event_time="2026-06-13T10:00:00Z",
        metric_name="cycle_time_s",
        value=100.0,
    )
    context = DetectorContext(state=DetectorState(values=(10.0, 10.0, 11.0)))

    result = detector.score_one(sample, context)
    next_state = detector.update_one(sample, context)

    assert result is not None
    assert result.expected_value != sample.value
    assert next_state.values[-1] == 100.0
    assert context.state.values == (10.0, 10.0, 11.0)


def test_sample_batch_result_and_contracts_are_importable():
    from metroliza.industrial.anomaly.contracts import DetectionResult, Detector  # noqa: PLC0415
    from metroliza.industrial.realtime.stream_contracts import (  # noqa: PLC0415
        SampleBatchResult,
        SignalDefinition,
        StreamOffset,
    )

    assert DetectionResult
    assert Detector
    assert SignalDefinition(source_profile_id=1, signal_key="s", metric_name="m")
    assert StreamOffset(source_profile_id=1, stream_key="s", cursor_column="id")
    assert SampleBatchResult(processed=1, inserted=1, skipped=0)

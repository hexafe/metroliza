import pytest

from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.detectors import SpecLimitDetector
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


def _sample(value: float) -> IndustrialSample:
    return IndustrialSample(
        id=1,
        source_profile_id=1,
        signal_id=5,
        source_record_key=f"ROW-{value}",
        event_time="2026-06-13T10:00:00Z",
        metric_name="diameter_mm",
        value=value,
    )


def test_spec_limit_detector_critical_for_usl_breach():
    signal = SignalDefinition(
        id=5,
        source_profile_id=1,
        signal_key="diameter",
        metric_name="diameter_mm",
        nominal=10.0,
        lsl=9.5,
        usl=10.5,
        lower_warning=9.7,
        upper_warning=10.3,
    )

    result = SpecLimitDetector().score_one(_sample(10.8), DetectorContext(signal=signal))

    assert result is not None
    assert result.severity == "critical"
    assert result.score == pytest.approx(0.3)
    assert result.threshold["usl"] == 10.5
    assert "above USL 10.5" in result.explanation


def test_spec_limit_detector_warning_for_warning_breach():
    signal = SignalDefinition(
        id=5,
        source_profile_id=1,
        signal_key="diameter",
        metric_name="diameter_mm",
        nominal=10.0,
        lsl=9.5,
        usl=10.5,
        lower_warning=9.7,
        upper_warning=10.3,
    )

    result = SpecLimitDetector().score_one(_sample(10.4), DetectorContext(signal=signal))

    assert result is not None
    assert result.severity == "warning"
    assert "above warning limit 10.3" in result.explanation


def test_spec_limit_detector_returns_none_inside_limits():
    signal = SignalDefinition(
        id=5,
        source_profile_id=1,
        signal_key="diameter",
        metric_name="diameter_mm",
        nominal=10.0,
        lsl=9.5,
        usl=10.5,
        lower_warning=9.7,
        upper_warning=10.3,
    )

    assert SpecLimitDetector().score_one(_sample(10.0), DetectorContext(signal=signal)) is None

from dataclasses import replace

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


def test_spec_limit_configuration_identity_tracks_effective_parameters():
    signal = SignalDefinition(1, "diameter", "diameter_mm", id=5, nominal=10.0, usl=10.5)
    detector = SpecLimitDetector()
    sample = _sample(12.0)

    def evidence(**changes):
        result = detector.score_one(sample, DetectorContext(signal=replace(signal, **changes)))
        assert result is not None
        return result.context["detector_evidence"]

    original = evidence()
    assert original["schema_version"] == 1 and original["window"] == {"kind": "trigger_sample"}
    assert original["configuration"]["parameters"]["usl"] == 10.5
    assert original == evidence(updated_at="2026-06-13T11:00:00Z")
    assert original["configuration_revision"] != evidence(usl=11.0)["configuration_revision"]
    assert original["configuration_revision"] == evidence(nominal=None)["configuration_revision"]
    assert evidence(usl=11)["configuration_revision"] == evidence(usl=11.0)["configuration_revision"]

import pytest

from metroliza.industrial.anomaly.contracts import DetectorContext, DetectorState
from metroliza.industrial.anomaly.online_drift import (
    PageHinkleyOnlineDriftDetector,
    RiverOnlineDriftDetector,
)
from metroliza.industrial.realtime.stream_contracts import IndustrialSample


def _sample(sample_id: int, value: float) -> IndustrialSample:
    return IndustrialSample(
        id=sample_id,
        source_profile_id=1,
        signal_id=9,
        source_record_key=f"ROW-{sample_id}",
        event_time=f"2026-06-13T10:{sample_id:02d}:00Z",
        metric_name="cycle_time_s",
        value=value,
    )


def _state_after(detector: PageHinkleyOnlineDriftDetector, values: tuple[float, ...]) -> DetectorState:
    state = DetectorState()
    for index, value in enumerate(values, start=1):
        sample = _sample(index, value)
        state = detector.update_one(sample, DetectorContext(state=state))
    return state


def test_page_hinkley_online_drift_reports_warning_without_failure_language():
    detector = PageHinkleyOnlineDriftDetector(
        min_n=5,
        delta=0.0,
        info_threshold=2.0,
        warning_threshold=4.0,
    )
    state = _state_after(detector, (10.0, 10.0, 10.0, 10.0, 10.0))
    sample = _sample(20, 20.0)

    result = detector.score_one(sample, DetectorContext(state=state))

    assert result is not None
    assert result.severity == "warning"
    assert result.detector_key == "online_drift"
    assert result.expected_value == 10.0
    assert result.threshold["algorithm"] == "page_hinkley"
    assert result.context["direction"] == "upward"
    assert result.context["samples_seen"] == 5
    assert result.score >= result.threshold["warning_threshold"]
    assert "process shift" in result.explanation
    assert "failure" not in result.explanation.lower()


def test_page_hinkley_online_drift_defaults_to_info_before_warning():
    detector = PageHinkleyOnlineDriftDetector(
        min_n=5,
        delta=0.0,
        info_threshold=2.0,
        warning_threshold=10.0,
    )
    state = _state_after(detector, (10.0, 10.0, 10.0, 10.0, 10.0))

    result = detector.score_one(_sample(14, 14.0), DetectorContext(state=state))

    assert result is not None
    assert result.severity == "info"
    assert result.threshold["warning_threshold"] == 10.0
    assert result.context["direction"] == "upward"


def test_page_hinkley_online_drift_scores_before_state_update():
    detector = PageHinkleyOnlineDriftDetector(
        min_n=3,
        delta=0.0,
        info_threshold=1.0,
        warning_threshold=2.0,
    )
    state = _state_after(detector, (10.0, 10.0, 10.0))
    context = DetectorContext(state=state)
    sample = _sample(15, 15.0)

    result = detector.score_one(sample, context)
    updated = detector.update_one(sample, context)

    assert result is not None
    assert result.expected_value == 10.0
    assert context.state.values == state.values
    assert updated.values != state.values
    assert updated.last_sample_id == 15


def test_page_hinkley_online_drift_skips_warmup_and_non_finite_values():
    detector = PageHinkleyOnlineDriftDetector(min_n=5)
    warmup_state = _state_after(detector, (10.0, 10.0, 10.0))
    warmup_context = DetectorContext(state=warmup_state)

    assert detector.score_one(_sample(4, 30.0), warmup_context) is None

    non_finite_sample = _sample(5, float("nan"))
    mature_state = _state_after(detector, (10.0, 10.0, 10.0, 10.0, 10.0))
    mature_context = DetectorContext(state=mature_state)

    assert detector.score_one(non_finite_sample, mature_context) is None
    assert detector.update_one(non_finite_sample, mature_context) is mature_state


def test_river_wrapper_is_lazy_before_minimum_history(monkeypatch):
    from metroliza.industrial.anomaly import online_drift  # noqa: PLC0415

    def fail_import(module_name: str):
        raise AssertionError(f"unexpected import of {module_name}")

    monkeypatch.setattr(online_drift.importlib, "import_module", fail_import)
    detector = RiverOnlineDriftDetector(min_n=5)

    result = detector.score_one(
        _sample(4, 10.0),
        DetectorContext(state=DetectorState(values=(10.0, 10.0, 10.0))),
    )

    assert result is None


def test_river_wrapper_updates_history_without_river_import():
    detector = RiverOnlineDriftDetector(min_n=5, max_history=3)
    context = DetectorContext(state=DetectorState(values=(1.0, 2.0, 3.0)))

    updated = detector.update_one(_sample(4, 4.0), context)

    assert updated.values == (2.0, 3.0, 4.0)
    assert updated.last_sample_id == 4


def test_river_wrapper_scores_when_river_is_installed():
    pytest.importorskip("river")
    detector = RiverOnlineDriftDetector(min_n=3)
    context = DetectorContext(state=DetectorState(values=(10.0, 10.1, 9.9, 10.0)))

    result = detector.score_one(_sample(5, 10.0), context)

    assert result is None or result.detector_key == "river_online_drift"

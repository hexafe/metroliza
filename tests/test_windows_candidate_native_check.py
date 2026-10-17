"""The fallback control cannot silently select native work or escape its scope."""
from __future__ import annotations

import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

from metroliza.app import windows_candidate_native_check as control
from scripts import qualify_windows_candidate_core as driver
from tests.test_windows_candidate_core_protocol import native_observation, payload


def _enable(monkeypatch, mode="unavailable"):
    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "1")
    monkeypatch.setenv(control.MODE_ENV, mode)


def test_gate_off_does_not_import_or_change_native_bridges(monkeypatch):
    monkeypatch.delenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", raising=False)
    monkeypatch.setattr(control, "_bindings", lambda: pytest.fail("ordinary launch imported control"))
    with pytest.raises(ValueError, match="candidate_native_gate_missing"):
        control.run_with_native_mode(lambda: pytest.fail("ran without gate"))


@pytest.mark.parametrize("mode", ["default", "unavailable"])
@pytest.mark.parametrize("interruption", [None, RuntimeError, KeyboardInterrupt, SystemExit])
def test_all_exact_bindings_restore_after_real_fallback_or_interruption(monkeypatch, mode, interruption):
    _enable(monkeypatch, mode)
    bindings = control._bindings()
    assert [name for name, _, _ in bindings] == list(driver.NATIVE_BINDINGS)
    originals = [getattr(module, attr) for _, module, attr in bindings]
    primary = None if interruption is None else interruption("synthetic")

    def operation():
        for (_, module, attr), original in zip(bindings, originals, strict=True):
            assert getattr(module, attr) is (None if mode == "unavailable" else original)
        from metroliza.native_bridges.group_stats_native import coerce_sequence_to_float64
        values = coerce_sequence_to_float64([1, "2.5", "bad"])
        assert list(values[:2]) == [1.0, 2.5]
        assert str(values[2]) == "nan"
        if primary is not None:
            raise primary

    if primary is None:
        result = control.run_with_native_mode(operation)
        assert driver._validate_native_observation(result, expected_mode=mode) is result
    else:
        with pytest.raises(interruption) as caught:
            control.run_with_native_mode(operation)
        assert caught.value is primary
    assert all(getattr(module, attr) is original for (_, module, attr), original in zip(bindings, originals, strict=True))


def test_partial_shadow_failure_restores_already_changed_bindings(monkeypatch):
    _enable(monkeypatch)

    class FailOnceModule(ModuleType):
        def __setattr__(self, name, value):
            if name == "fail" and value is None:
                raise KeyboardInterrupt("synthetic")
            super().__setattr__(name, value)

    module = FailOnceModule("synthetic")
    originals = [lambda: None for _ in range(16)]
    bindings = []
    for index, original in enumerate(originals):
        attr = "fail" if index == 1 else "binding" + str(index)
        setattr(module, attr, original)
        bindings.append((str(index), module, attr))
    monkeypatch.setattr(control, "_bindings", lambda: bindings)
    with pytest.raises(KeyboardInterrupt):
        control.run_with_native_mode(lambda: pytest.fail("partial enter ran operation"))
    assert all(getattr(module, attr) is original for (_, module, attr), original in zip(bindings, originals, strict=True))


def test_resurrected_native_binding_cannot_claim_fallback_success(monkeypatch):
    _enable(monkeypatch)
    bindings = control._bindings()
    _, module, attr = bindings[0]
    original = getattr(module, attr)
    with pytest.raises(ValueError, match="candidate_native_control_changed"):
        control.run_with_native_mode(lambda: setattr(module, attr, lambda: None))
    assert getattr(module, attr) is original


def test_frozen_candidate_requires_all_original_native_functions_before_shadow(monkeypatch):
    _enable(monkeypatch)
    bindings = control._bindings()
    for _, module, attr in bindings:
        monkeypatch.setattr(module, attr, lambda: None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    result = control.run_with_native_mode(lambda: None)
    assert driver._validate_native_observation(result, packaged=True, expected_mode="unavailable") is result
    _, module, attr = bindings[-1]
    monkeypatch.setattr(module, attr, None)
    with pytest.raises(ValueError, match="candidate_native_package_bindings_missing"):
        control.run_with_native_mode(lambda: pytest.fail("missing package binding ran"))


@pytest.mark.parametrize("field,value", [
    ("mode", "unknown"), ("runtime_context", "unknown"), ("bindings", []),
    ("available_before", True), ("forced_unavailable", True), ("forced_unavailable", 15), ("restored", False),
])
def test_host_rejects_incomplete_or_unbounded_native_observation(field, value):
    observation = native_observation(mode="unavailable")
    observation[field] = value
    with pytest.raises(driver.CandidateFailure):
        driver._validate_native_observation(observation, packaged=True, expected_mode="unavailable")


def test_host_binds_native_mode_and_requires_original_package_bindings():
    sample = payload()
    with pytest.raises(driver.CandidateFailure, match="native_mode_mismatch"):
        driver.validate_runtime_receipt(sample, "1" * 40, native_mode="unavailable")
    sample["native_observation"] = native_observation(mode="unavailable")
    assert driver.validate_runtime_receipt(sample, "1" * 40, native_mode="unavailable") is sample
    sample["native_observation"]["available_before"] = 15
    with pytest.raises(driver.CandidateFailure, match="packaged_native_bindings_missing"):
        driver.validate_runtime_receipt(sample, "1" * 40, native_mode="unavailable")


def test_unknown_mode_cannot_start_operation(monkeypatch):
    _enable(monkeypatch, "unknown")
    with pytest.raises(ValueError, match="candidate_native_mode_invalid"):
        control.run_with_native_mode(lambda: pytest.fail("unknown mode ran"))


def test_failed_operation_joins_active_fallback_worker_before_restoring(monkeypatch):
    _enable(monkeypatch)
    bindings = control._bindings()
    entered, stop = threading.Event(), threading.Event()
    observed = []
    primary = RuntimeError("synthetic operation failure")

    def work():
        entered.set()
        if stop.wait(5):
            observed.append(all(getattr(module, attr) is None for _, module, attr in bindings))

    thread = threading.Thread(target=work)

    class Worker:
        def wait(self, milliseconds):
            assert milliseconds == 20000
            thread.join(5)
            return not thread.is_alive()

    window = SimpleNamespace(
        _reports_workspace=SimpleNamespace(preflight_thread=None, parse_thread=Worker(),
                                           _request_active_worker_cancellation=stop.set),
        close=lambda: not thread.is_alive(), isVisible=lambda: False,
    )

    def operation():
        thread.start()
        try:
            assert entered.wait(5)
            raise primary
        finally:
            control.close_report_owner(window, SimpleNamespace(processEvents=lambda: None))

    try:
        with pytest.raises(RuntimeError) as caught:
            control.run_with_native_mode(operation)
        assert caught.value is primary
        assert observed == [True] and not thread.is_alive()
    finally:
        stop.set()
        if thread.ident is not None:
            thread.join(5)


@pytest.mark.parametrize("owner_kind", ["reports", "dashboard", "import_guard"])
def test_join_failure_exits_red_without_restoring_under_unjoined_owner(monkeypatch, owner_kind):
    _enable(monkeypatch)
    bindings = control._bindings()
    originals = [(module, attr, getattr(module, attr)) for _, module, attr in bindings]
    retained_before = len(control._UNJOINED_OWNERS)
    worker = SimpleNamespace(wait=lambda _milliseconds: False)
    window = SimpleNamespace(
        _reports_workspace=SimpleNamespace(preflight_thread=None, parse_thread=worker,
                                           _request_active_worker_cancellation=lambda: None),
        realtime_monitoring_dialog=SimpleNamespace(request_shutdown=lambda: None, dashboard_thread=worker),
        close=lambda: pytest.fail("unjoined owner was closed"),
    )

    def operation():
        app = SimpleNamespace(processEvents=lambda: None)
        if owner_kind == "reports":
            control.close_report_owner(window, app)
        elif owner_kind == "dashboard":
            from metroliza.app.windows_candidate_ui_checks import _close_window_safely
            _close_window_safely(app, window)
        else:
            # Same post-wait failure signal used by the import-guard finally.
            assert worker.wait(20000) is False
            control.abort_unavailable_after_join_failure(window)

    try:
        with pytest.raises(control._UnjoinedNativeOwner) as caught:
            control.run_with_native_mode(operation)
        assert caught.value.code == 22
        assert all(getattr(module, attr) is None for _, module, attr in bindings)
        assert control._UNJOINED_OWNERS[-1] is window
        assert control._UNAVAILABLE_ACTIVE.get() is False
    finally:
        # In production the failed synthetic process exits into owned Job
        # teardown. Restore this pytest process after observing that boundary.
        for module, attr, original in originals:
            setattr(module, attr, original)
        del control._UNJOINED_OWNERS[retained_before:]

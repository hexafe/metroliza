"""Regression coverage for the normal package-entry qualification seam."""
from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

import pytest


ENTRY = Path(__file__).resolve().parents[1] / "packaging" / "metroliza_package_entry.py"


def _module(**members):
    value = types.ModuleType("candidate_stub")
    for name, member in members.items():
        setattr(value, name, member)
    return value


def _run_entry(monkeypatch, *, startup_code: int, diagnostic_scenario, candidate_scenario, events=None):
    events = [] if events is None else events

    class Recorder:
        def close(self):
            events.append("recorder_close")

    transport = _module(
        attach_child_recorder=lambda: Recorder(),
        supervised_mode_requested=lambda: False,
    )
    bootstrap = _module(run_application=lambda: events.append("bootstrap") or startup_code)
    diagnostic = _module(
        requested_scenario=lambda: diagnostic_scenario,
        run_qualification=lambda scenario: events.append(("diagnostic", scenario)) or 11,
    )
    candidate = _module(
        requested_scenario=lambda: events.append("candidate_requested") or candidate_scenario,
        run_qualification=lambda: events.append("candidate_run") or 12,
    )
    # Both real requested_scenario() functions return a scenario only when
    # METROLIZA_STARTUP_SMOKE=1, and the entry checks that shared gate before importing
    # either harness (#1112). Stubbed scenarios therefore run under the gate.
    if diagnostic_scenario is not None or candidate_scenario is not None:
        monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    else:
        monkeypatch.delenv("METROLIZA_STARTUP_SMOKE", raising=False)
    monkeypatch.setitem(sys.modules, "metroliza.shared.diagnostic_transport", transport)
    monkeypatch.setitem(sys.modules, "metroliza.app.bootstrap", bootstrap)
    monkeypatch.setitem(sys.modules, "metroliza.app.diagnostic_qualification", diagnostic)
    monkeypatch.setitem(sys.modules, "metroliza.app.windows_candidate_qualification", candidate)
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(str(ENTRY), run_name="__main__")
    return exited.value.code, events


def test_diagnostic_qualification_has_priority_and_recorder_closes(monkeypatch):
    code, events = _run_entry(
        monkeypatch, startup_code=0, diagnostic_scenario="diagnostic", candidate_scenario="core"
    )
    assert code == 11
    assert events == ["bootstrap", ("diagnostic", "diagnostic"), "recorder_close"]


def test_candidate_qualification_runs_only_after_diagnostic_gate_declines(monkeypatch):
    code, events = _run_entry(
        monkeypatch, startup_code=0, diagnostic_scenario=None, candidate_scenario="core"
    )
    assert code == 12
    assert events == ["bootstrap", "candidate_requested", "candidate_run", "recorder_close"]


def test_recorder_closes_when_bootstrap_fails_before_all_qualification_gates(monkeypatch):
    code, events = _run_entry(
        monkeypatch, startup_code=7, diagnostic_scenario="diagnostic", candidate_scenario="core"
    )
    assert code == 7
    assert events == ["bootstrap", "recorder_close"]


def test_candidate_gate_requires_both_explicit_environment_values(monkeypatch):
    from metroliza.app.windows_candidate_qualification import requested_scenario

    for startup, qualification, expected in ((None, None, None), ("1", None, None), (None, "1", None), ("1", "1", "core")):
        monkeypatch.delenv("METROLIZA_STARTUP_SMOKE", raising=False)
        monkeypatch.delenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", raising=False)
        if startup is not None:
            monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", startup)
        if qualification is not None:
            monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", qualification)
        assert requested_scenario() == expected


@pytest.mark.parametrize("qualification", [False, True])
def test_package_parent_installs_native_version_before_bootstrap(monkeypatch, qualification):
    from metroliza.shared import compute_worker

    events = []
    monkeypatch.setattr(compute_worker, "use_native_windows_version", lambda: events.append("native_version"))
    code, entry_events = _run_entry(
        monkeypatch, startup_code=0, diagnostic_scenario=None,
        candidate_scenario="core" if qualification else None, events=events,
    )
    assert code == (12 if qualification else 0)
    assert entry_events[:2] == ["native_version", "bootstrap"]
    assert events.count("native_version") == 1


@pytest.mark.parametrize("qualification", [False, True])
def test_production_parent_uses_native_fallback_before_bootstrap_import(monkeypatch, qualification):
    import builtins
    import platform
    from metroliza.shared import compute_worker

    original_import = builtins.__import__
    native_fallback = compute_worker.use_native_windows_version
    runtime_sys = types.SimpleNamespace(
        frozen=True, platform="win32",
        getwindowsversion=lambda: types.SimpleNamespace(platform_version=(10, 0, 20348)),
    )
    monkeypatch.setattr(platform, "_syscmd_ver", lambda *_a, **_k: pytest.fail("shell fallback called"))
    monkeypatch.setattr(compute_worker, "use_native_windows_version", lambda: native_fallback(
        runtime_sys=runtime_sys, runtime_os=types.SimpleNamespace(name="nt")))
    checked = []

    def checked_import(name, *args, **kwargs):
        if name == "metroliza.app.bootstrap":
            assert platform._syscmd_ver() == ("", "", "10.0.20348")
            checked.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    code, _ = _run_entry(
        monkeypatch, startup_code=0, diagnostic_scenario=None,
        candidate_scenario="core" if qualification else None,
    )
    assert code == (12 if qualification else 0)
    assert checked == ["metroliza.app.bootstrap"]


def test_compute_qualification_uses_the_production_parent_path(monkeypatch, tmp_path):
    import json
    from metroliza.app import compute_worker_qualification as workload
    from metroliza.shared import compute_worker, diagnostic_runtime_audit

    events = []
    monkeypatch.setenv(workload.GATE, str(tmp_path))
    monkeypatch.setattr(compute_worker, "use_native_windows_version", lambda: events.append("native_version"))
    monkeypatch.setattr(diagnostic_runtime_audit, "wait_for_host_ready", lambda **_kwargs: None)

    def imported(*_args):
        assert events == ["native_version", "bootstrap"]
        events.append("import")
        return {"seconds": 1}

    def exported(*_args):
        assert events == ["native_version", "bootstrap", "import"]
        events.append("export")
        return {"seconds": 2}

    monkeypatch.setattr(workload, "run_import", imported)
    monkeypatch.setattr(workload, "run_export", exported)
    code, _ = _run_entry(
        monkeypatch, startup_code=0, diagnostic_scenario=None, candidate_scenario="core", events=events,
    )
    assert code == 0
    assert events == ["native_version", "bootstrap", "import", "export", "recorder_close"]
    assert json.loads((tmp_path / "compute.json").read_text())["export"]["seconds"] == 2

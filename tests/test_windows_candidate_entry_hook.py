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


def _run_entry(monkeypatch, *, startup_code: int, diagnostic_scenario, candidate_scenario):
    events = []

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

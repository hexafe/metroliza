import json
import os
from pathlib import Path
import sys

import pytest

from metroliza.app.diagnostic_launcher import run_with_store
from metroliza.app.diagnostic_qualification import requested_scenario
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus


def test_destructive_synthetic_scenario_requires_both_explicit_test_flags(monkeypatch):
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", "hard_exit")
    monkeypatch.delenv("METROLIZA_STARTUP_SMOKE", raising=False)
    assert requested_scenario() is None
    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    assert requested_scenario() == "hard_exit"
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", "arbitrary-command")
    assert requested_scenario() is None


@pytest.mark.parametrize("scenario,code", [("normal", 0), ("hard_exit", 9)])
def test_actual_package_entry_runs_only_the_pinned_synthetic_workflow(tmp_path, scenario, code):
    root = Path(__file__).resolve().parents[1]
    work = tmp_path / "Metroliza próba ze spacjami"
    work.mkdir()
    (work / "fixture.pdf").write_bytes((root / "tests/fixtures/pdf/cmm_smoke_fixture.pdf").read_bytes())
    env = dict(os.environ, METROLIZA_STARTUP_SMOKE="1", METROLIZA_LICENSE_VERIFICATION="0",
               METROLIZA_DIAGNOSTIC_QUALIFICATION=scenario,
               METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT=str(work))
    store = IncidentStore(tmp_path / "state")
    result = run_with_store([sys.executable, str(root / "packaging/metroliza_package_entry.py")],
                            store=store, env=env, cwd=work)
    assert result.observation.exit_code == code
    receipt = json.loads((work / "qualification.json").read_bytes())
    assert set(receipt) == {"schema_version", "scenario", "stage", "packaged", "console_none", "ordinary_user"}
    assert receipt["stage"] == ("ready" if code else "complete")
    assert receipt["packaged"] is False
    events = [json.loads(event) for event in result.observation.history.events]
    assert {event.get("operation") for event in events if event["event_code"] == "workflow_diagnostic"} == {
        "selected_import", "local_export",
    }
    assert (work / "scratch.sqlite").is_file()
    assert (work / "scratch.xlsx").is_file()
    if code:
        assert result.storage_status is StoreStatus.SAVED
        assert len(store.list_reports().reports) == 1


def test_unavailable_default_store_still_runs_and_preserves_actual_child_exit(tmp_path, monkeypatch):
    from metroliza.shared import diagnostic_store

    def unavailable():
        raise OSError("SYNTHETIC_PRIVATE_ROOT")
    monkeypatch.setattr(diagnostic_store, "_default_root", unavailable)
    store = IncidentStore()
    child = Path(__file__).parent / "fixtures/diagnostic_child.py"
    result = run_with_store([sys.executable, str(child), "hard_exit"], store=store, cwd=tmp_path)
    assert result.observation.exit_code == 9
    assert result.storage_status is StoreStatus.ROOT_UNAVAILABLE
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("headless_environment", [False, True], ids=["desktop-env", "headless-env"])
def test_next_actual_entry_previews_and_exports_previous_surviving_incident(
    tmp_path, headless_environment
):
    root = Path(__file__).resolve().parents[1]
    state = tmp_path / "application-state"
    store = IncidentStore(state / ("Metroliza" if os.name == "nt" else "metroliza") / "diagnostics")
    child = Path(__file__).parent / "fixtures/diagnostic_child.py"
    crashed = run_with_store([sys.executable, str(child), "hard_exit"], store=store)
    assert crashed.storage_status is StoreStatus.SAVED
    work = tmp_path / "preview"
    work.mkdir()
    env = dict(os.environ, METROLIZA_STARTUP_SMOKE="1", METROLIZA_LICENSE_VERIFICATION="0",
               METROLIZA_DIAGNOSTIC_QUALIFICATION="preview",
               METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT=str(work),
               XDG_STATE_HOME=str(state), LOCALAPPDATA=str(state))
    if headless_environment:
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORMTHEME", "QT_STYLE_OVERRIDE"):
            env.pop(key, None)
    result = run_with_store([sys.executable, str(root / "packaging/metroliza_package_entry.py")],
                            store=store, env=env, cwd=work)
    assert result.observation.exit_code == 0
    assert json.loads((work / "qualification.json").read_bytes())["stage"] == "complete"
    import zipfile

    with zipfile.ZipFile(work / "selected.zip") as bundle:
        assert set(bundle.namelist()) == {"incident.json", "manifest.json", "summary.json"}
        incident = json.loads(bundle.read("incident.json"))
        assert incident["session_id"] == crashed.observation.session_id

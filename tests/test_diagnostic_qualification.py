import json
import os
from pathlib import Path
import sys

import pytest

from metroliza.app.diagnostic_launcher import run_with_store
from metroliza.app import diagnostic_qualification
from metroliza.app.diagnostic_qualification import requested_scenario
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus


def test_qualification_receipt_includes_closed_integrity_level(tmp_path, monkeypatch):
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT", str(tmp_path))
    monkeypatch.setattr(diagnostic_qualification, "_ordinary_user", lambda: True)
    monkeypatch.setattr(diagnostic_qualification, "_integrity_level", lambda: "medium")

    diagnostic_qualification.write_receipt("normal", "ready")
    diagnostic_qualification.write_receipt("normal", "complete")

    receipt = json.loads((tmp_path / "qualification-complete.json").read_bytes())
    ready = json.loads((tmp_path / "qualification-ready.json").read_bytes())
    assert receipt["ordinary_user"] is True
    assert receipt["integrity_level"] == "medium"
    assert ready["stage"] == "ready"


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
    receipt_name = "qualification-ready.json" if code else "qualification-complete.json"
    receipt = json.loads((work / receipt_name).read_bytes())
    assert set(receipt) == {
        "schema_version", "scenario", "stage", "packaged", "console_none",
        "ordinary_user", "integrity_level",
    }
    assert receipt["stage"] == ("ready" if code else "complete")
    assert receipt["packaged"] is False
    assert receipt["integrity_level"] in {
        "low", "medium", "high", "system", "other", "unavailable", "not_windows"
    }
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


@pytest.mark.parametrize("cleanup_status", ["complete", "failed"])
@pytest.mark.parametrize("menu_fault", ["missing_action", "hidden_help", "disabled_help"])
def test_preview_requires_the_real_normal_help_action(
    tmp_path, monkeypatch, cleanup_status, menu_fault
):
    from metroliza.app.bootstrap import get_or_create_qapplication
    from metroliza.ui.main_window import MainWindow

    state = tmp_path / "application-state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("LOCALAPPDATA", str(state))
    store = IncidentStore()
    child = Path(__file__).parent / "fixtures/diagnostic_child.py"
    crashed = run_with_store([sys.executable, str(child), "hard_exit"], store=store)
    assert crashed.storage_status is StoreStatus.SAVED
    work = tmp_path / "preview"
    work.mkdir()
    monkeypatch.chdir(work)
    original_setup = MainWindow.setup_menu_actions

    def with_unavailable_menu(window):
        original_setup(window)
        action = window.diagnostic_incidents_action
        assert action in window.help_menu.actions()
        assert action.isEnabled() and action.isVisible()
        assert action.text() == "Diagnostic incidents…"
        if menu_fault == "missing_action":
            window.help_menu.removeAction(action)
        elif menu_fault == "hidden_help":
            window.help_menu.menuAction().setVisible(False)
        else:
            window.help_menu.menuAction().setEnabled(False)

    monkeypatch.setattr(MainWindow, "setup_menu_actions", with_unavailable_menu)
    app = get_or_create_qapplication()
    assert app is not None
    windows = []
    close_methods = []
    create_window = diagnostic_qualification._preview_main_window

    def capture_window(root):
        window = create_window(root)
        windows.append(window)
        close_methods.append(window.close)
        if cleanup_status == "failed":
            monkeypatch.setattr(window, "close", lambda: False)
        return window

    monkeypatch.setattr(diagnostic_qualification, "_preview_main_window", capture_window)
    try:
        with pytest.raises(ValueError, match="^qualification_menu_unavailable$") as failure:
            diagnostic_qualification._preview_export(work)
        assert failure.value.cleanup == cleanup_status
        assert len(windows) == 1
        assert windows[0].isVisible() is (cleanup_status == "failed")
        diagnostic_qualification._write_failure(work, "preview", failure.value)
        assert json.loads((work / "failure.json").read_bytes()) == {
            "schema_version": 1,
            "stage": "preview",
            "reason": "qualification_menu_unavailable",
            "cleanup": cleanup_status,
        }
    finally:
        for close in close_methods:
            close()
    assert not (work / "selected.zip").exists()


def test_preview_failure_receipt_revalidates_cleanup_without_private_text(tmp_path):
    failure = diagnostic_qualification._PreviewFailure("qualification_menu_unavailable", "complete")
    failure.cleanup = "PRIVATE_CLEANUP_DETAIL"
    diagnostic_qualification._write_failure(tmp_path, "preview", failure)
    assert json.loads((tmp_path / "failure.json").read_bytes()) == {
        "schema_version": 1,
        "stage": "preview",
        "reason": "qualification_menu_unavailable",
        "cleanup": "failed",
    }


@pytest.mark.parametrize("has_window", [False, True])
def test_preview_cleanup_survives_widget_import_failure(monkeypatch, has_window):
    import builtins

    from metroliza.app.bootstrap import get_or_create_qapplication
    from PyQt6.QtWidgets import QMainWindow

    app = get_or_create_qapplication()
    assert app is not None
    window = QMainWindow() if has_window else None
    if window is not None:
        window.show()
        assert window.isVisible()
    original_import = builtins.__import__

    def unavailable_dialog(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PyQt6.QtWidgets" and "QDialog" in fromlist:
            raise ImportError("PRIVATE_IMPORT_FAILURE")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", unavailable_dialog)
    try:
        assert diagnostic_qualification._close_preview_windows(window) == (
            "failed" if has_window else "not_attempted"
        )
        if window is not None:
            assert not window.isVisible()
    finally:
        if window is not None:
            window.close()


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
    assert json.loads((work / "qualification-complete.json").read_bytes())[
        "stage"
    ] == "complete"
    import zipfile

    with zipfile.ZipFile(work / "selected.zip") as bundle:
        assert set(bundle.namelist()) == {"incident.json", "manifest.json", "summary.json"}
        incident = json.loads(bundle.read("incident.json"))
        assert incident["session_id"] == crashed.observation.session_id

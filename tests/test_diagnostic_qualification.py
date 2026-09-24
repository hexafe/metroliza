import json
import logging
import os
from pathlib import Path
import sys

import pytest

from metroliza.app.diagnostic_launcher import run_with_store
from metroliza.app import diagnostic_qualification
from metroliza.app.diagnostic_qualification import requested_scenario
from metroliza.shared.diagnostic_events import WorkflowDiagnosticEvent, WorkflowOutcome
from metroliza.shared.diagnostic_ring import DEFAULT_MAX_OPERATIONS, DiagnosticRing
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus
from metroliza.shared.diagnostic_wire import encode_event


@pytest.mark.parametrize("count,error,window,expected", [
    (0, 6, 0, True), (0, 0, 0, False), (0, 87, 0, False),
    (1, 0, 0, False), (2, 0, 41, False), (0, 6, 41, False),
])
@pytest.mark.parametrize("streams_none", [False, True])
def test_console_receipt_requires_native_absence_not_python_streams(
    monkeypatch, count, error, window, expected, streams_none
):
    import ctypes
    from types import SimpleNamespace

    calls = []

    def process_list(buffer, size):
        assert buffer is not None and size == 1
        calls.append("process_list")
        return count

    def console_window():
        return window

    kernel = SimpleNamespace(GetConsoleProcessList=process_list, GetConsoleWindow=console_window)
    monkeypatch.setattr(diagnostic_qualification, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(diagnostic_qualification, "sys", SimpleNamespace(
        stdout=None if streams_none else object(), stderr=None if streams_none else object()))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: kernel, raising=False)
    monkeypatch.setattr(ctypes, "set_last_error", lambda value: calls.append(("clear", value)), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    assert diagnostic_qualification._console_absent() is expected
    assert calls == [("clear", 0), "process_list"]


def test_console_probe_unavailable_is_not_absence(monkeypatch):
    import ctypes
    from types import SimpleNamespace

    monkeypatch.setattr(diagnostic_qualification, "os", SimpleNamespace(name="nt"))

    def unavailable(*args, **kwargs):
        raise OSError("synthetic unavailable API")

    monkeypatch.setattr(ctypes, "WinDLL", unavailable, raising=False)
    assert diagnostic_qualification._console_absent() is False


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


def test_flood_stimulus_forces_explicit_receiver_loss_when_transport_keeps_up(caplog):
    with caplog.at_level(logging.INFO, logger="metroliza.shared.workflow_diagnostics"):
        diagnostic_qualification._flood()

    emitted = [
        record.msg for record in caplog.records
        if type(record.msg) is WorkflowDiagnosticEvent
    ]
    starts = [event for event in emitted if event.outcome is WorkflowOutcome.STARTED]
    assert len({event.operation_id for event in starts}) > DEFAULT_MAX_OPERATIONS
    first_finished = next(
        index for index, event in enumerate(emitted) if event.outcome is WorkflowOutcome.COMPLETED
    )
    assert len({event.operation_id for event in emitted[:first_finished]}) > DEFAULT_MAX_OPERATIONS

    ring = DiagnosticRing()
    for event in emitted:
        ring.add(encode_event(event), 0.0)
    loss = ring.snapshot(0.0).loss
    assert loss.normal_count_dropped_events > 0


@pytest.mark.parametrize("marker_kind", ("absent", "directory"))
def test_finish_barrier_rejects_missing_or_nonfile_marker(tmp_path, marker_kind):
    marker = tmp_path / "finish"
    if marker_kind == "directory":
        marker.mkdir()

    with pytest.raises(ValueError, match="^qualification_barrier_timeout$"):
        diagnostic_qualification._wait_for_finish(tmp_path, seconds=0)


@pytest.mark.parametrize("delivery", ("existing", "during_wait"))
def test_finish_barrier_accepts_file(tmp_path, monkeypatch, delivery):
    marker = tmp_path / "finish"
    if delivery == "existing":
        marker.touch()
    else:
        from metroliza.app.bootstrap import get_or_create_qapplication

        app = get_or_create_qapplication()
        assert app is not None
        monkeypatch.setattr(
            diagnostic_qualification.time,
            "sleep",
            lambda _seconds: marker.touch(exist_ok=False),
        )

    diagnostic_qualification._wait_for_finish(
        tmp_path, seconds=1
    )


@pytest.mark.parametrize("delivered_at", (109, 110, 111))
def test_finish_barrier_accepts_only_file_observed_before_deadline(
    tmp_path, monkeypatch, delivered_at
):
    from metroliza.app.bootstrap import get_or_create_qapplication

    app = get_or_create_qapplication()
    assert app is not None
    marker = tmp_path / "finish"
    clock = [100]
    monkeypatch.setattr(diagnostic_qualification.time, "monotonic", lambda: clock[0])

    def deliver_after_event_pump(_seconds):
        marker.touch(exist_ok=False)
        clock[0] = delivered_at

    monkeypatch.setattr(diagnostic_qualification.time, "sleep", deliver_after_event_pump)
    if delivered_at < 110:
        diagnostic_qualification._wait_for_finish(tmp_path, seconds=10)
    else:
        with pytest.raises(ValueError, match="^qualification_barrier_timeout$"):
            diagnostic_qualification._wait_for_finish(tmp_path, seconds=10)
    assert marker.is_file()


def test_finish_barrier_rechecks_clock_after_marker_observation(monkeypatch):
    clock = [100]
    monkeypatch.setattr(diagnostic_qualification.time, "monotonic", lambda: clock[0])

    class DelayedMarker:
        def exists(self):
            return True

        def is_file(self):
            clock[0] = 111
            return True

    class Root:
        def __truediv__(self, name):
            assert name == "finish"
            return DelayedMarker()

    with pytest.raises(ValueError, match="^qualification_barrier_timeout$"):
        diagnostic_qualification._wait_for_finish(Root(), seconds=10)


@pytest.mark.parametrize("finish_delivery", ("absent", "after_deadline"))
def test_handled_failure_barrier_timeout_is_a_closed_failure(
    tmp_path, monkeypatch, finish_delivery
):
    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", "handled_failure")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT", str(tmp_path))
    monkeypatch.setattr(diagnostic_qualification, "_run_work", lambda *_args: None)
    actual_wait = diagnostic_qualification._wait_for_finish
    wait_seconds = 0
    if finish_delivery == "after_deadline":
        clock = [100]
        monkeypatch.setattr(diagnostic_qualification.time, "monotonic", lambda: clock[0])

        def late_finish(_seconds):
            (tmp_path / "finish").touch(exist_ok=False)
            clock[0] = 111

        monkeypatch.setattr(diagnostic_qualification.time, "sleep", late_finish)
        wait_seconds = 10
    monkeypatch.setattr(
        diagnostic_qualification,
        "_wait_for_finish",
        lambda root: actual_wait(root, seconds=wait_seconds),
    )

    assert diagnostic_qualification.run_qualification("handled_failure") == 21
    assert json.loads((tmp_path / "failure.json").read_bytes()) == {
        "schema_version": 1,
        "stage": "application",
        "reason": "qualification_barrier_timeout",
    }
    failed = json.loads((tmp_path / "qualification-failed.json").read_bytes())
    assert failed["scenario"] == "handled_failure"
    assert failed["stage"] == "failed"
    assert not (tmp_path / "qualification-complete.json").exists()


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
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent
    from metroliza.app.bootstrap import get_or_create_qapplication
    from metroliza.ui.main_window import MainWindow

    state = tmp_path / "application-state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("LOCALAPPDATA", str(state))
    store = IncidentStore()
    # Menu faults need a stored incident, not an asynchronous publisher race.
    import time
    import uuid
    from metroliza.shared.diagnostic_incident import (
        ChannelState, HandshakeState, IncidentObservation, LaunchState,
        TerminationState, build_incident,
    )
    from metroliza.shared.diagnostic_ring import LOSS_ACCOUNTING_BYTES, RingLoss, RingSnapshot

    incident = build_incident(
        session_id=uuid.uuid4(), created_at_ms=time.time_ns() // 1_000_000,
        build_git_sha="a" * 40,
        observation=IncidentObservation(
            launch=LaunchState.STARTED, handshake=HandshakeState.ACCEPTED,
            channel=ChannelState.COMPLETE, exit_code=9,
            termination=TerminationState.OBSERVED_EXIT,
            clean_terminal_received=True, source_dropped=0,
            source_loss_known=True, elapsed_ms=20,
        ),
        history=RingSnapshot((), RingLoss(), LOSS_ACCOUNTING_BYTES),
    )
    assert store.publish(incident).status is StoreStatus.SAVED
    assert len(store.list_reports().reports) == 1
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
        if cleanup_status == "complete":
            assert sip.isdeleted(windows[0])
        else:
            assert not sip.isdeleted(windows[0])
            assert windows[0].isVisible()
        diagnostic_qualification._write_failure(work, "preview", failure.value)
        assert json.loads((work / "failure.json").read_bytes()) == {
            "schema_version": 1,
            "stage": "preview",
            "reason": "qualification_menu_unavailable",
            "cleanup": cleanup_status,
        }
    finally:
        for window, close in zip(windows, close_methods, strict=True):
            if not sip.isdeleted(window):
                close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
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


def test_preview_cleanup_destroys_owned_qt_widgets_before_app_release():
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QDialog, QMainWindow
    from metroliza.app.bootstrap import get_or_create_qapplication

    app = get_or_create_qapplication()
    window = QMainWindow()
    dialog = QDialog(window)
    window.show()
    dialog.show()
    app.processEvents()
    try:
        assert diagnostic_qualification._close_preview_windows(window) == "complete"
        assert sip.isdeleted(window)
        assert sip.isdeleted(dialog)
    finally:
        if not sip.isdeleted(window):
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_preview_cleanup_reports_failed_if_owned_qt_widget_remains(monkeypatch):
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QMainWindow
    from metroliza.app.bootstrap import get_or_create_qapplication

    app = get_or_create_qapplication()
    window = QMainWindow()
    window.show()
    app.processEvents()
    delete_later = window.deleteLater
    monkeypatch.setattr(window, "deleteLater", lambda: None)
    try:
        assert diagnostic_qualification._close_preview_windows(window) == "failed"
        assert not sip.isdeleted(window)
        assert not window.isVisible()
    finally:
        delete_later()
        QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(window)


@pytest.mark.parametrize("has_window", [False, True])
def test_preview_cleanup_survives_widget_import_failure(monkeypatch, has_window):
    import builtins

    from PyQt6 import sip
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
            assert sip.isdeleted(window)
    finally:
        if window is not None and not sip.isdeleted(window):
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
               XDG_STATE_HOME=str(state), XDG_CONFIG_HOME=str(work / "config"),
               XDG_DATA_HOME=str(work / "data"), APPDATA=str(state),
               LOCALAPPDATA=str(state))
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


def test_real_qualification_work_waits_for_host_to_observe_startup(tmp_path, monkeypatch):
    import threading
    import time
    from metroliza.shared import diagnostic_runtime_audit as audit
    from scripts.windows_owned_process_probe import RuntimeEvidence
    from types import SimpleNamespace

    journal = tmp_path / "audit"
    journal.mkdir()
    nonce = "a" * 32
    audit._write(journal, "installed.json", {"schema_version": 1, "nonce": nonce, "installed": True})
    monkeypatch.setenv(audit.GATE, "1")
    monkeypatch.setenv(audit.ROOT, str(journal))
    monkeypatch.setenv(audit.NONCE, nonce)
    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", "normal")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT", str(tmp_path))
    evidence = object.__new__(RuntimeEvidence)
    evidence.root = journal
    evidence.nonce = nonce
    evidence.root_identity = evidence._identity()
    evidence.failure_factory = lambda: ValueError("synthetic failure")
    evidence.probe = SimpleNamespace(phase="startup")
    work_phases = []
    host_observed = []

    def work(*_args):
        work_phases.append(evidence.probe.phase)
        assert evidence.probe.phase == "running"

    def host():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (tmp_path / "startup.json").exists():
                time.sleep(0.05)  # Host scheduling delay must not relabel work as startup.
                host_observed.append(list(work_phases))
                evidence.ready()
                return
            time.sleep(0.005)

    monkeypatch.setattr(diagnostic_qualification, "_run_work", work)
    observer = threading.Thread(target=host)
    observer.start()
    try:
        result = diagnostic_qualification.run_qualification("normal")
    finally:
        observer.join(timeout=6)
    assert not observer.is_alive()
    assert host_observed == [[]]
    assert result == 0
    assert work_phases == ["running"]


@pytest.mark.parametrize("fault,reason", [("absent", "runtime_ready_timeout"), ("directory", "runtime_audit_invalid")])
def test_runtime_ack_failure_never_enters_work_and_is_closed_on_host(tmp_path, monkeypatch, fault, reason):
    from metroliza.shared import diagnostic_runtime_audit as audit
    from scripts import qualify_windows_diagnostics as host

    journal = tmp_path / "audit"
    journal.mkdir()
    nonce = "a" * 32
    audit._write(journal, "installed.json", {"schema_version": 1, "nonce": nonce, "installed": True})
    if fault == "directory":
        (journal / "ready").mkdir()
    monkeypatch.setenv(audit.GATE, "1")
    monkeypatch.setenv(audit.ROOT, str(journal))
    monkeypatch.setenv(audit.NONCE, nonce)
    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", "normal")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT", str(tmp_path))
    monkeypatch.setattr(diagnostic_qualification, "_run_work", lambda *_: pytest.fail("work ran before valid host ack"))
    wait = audit.wait_for_host_ready
    monkeypatch.setattr(audit, "wait_for_host_ready", lambda: wait(seconds=0 if fault == "absent" else 1))
    assert diagnostic_qualification.run_qualification("normal") == 21
    assert host._validate_child_failure(tmp_path / "failure.json") == {
        "schema_version": 1, "stage": "receipt", "reason": reason,
    }
    assert not (tmp_path / "qualification-ready.json").exists()
    assert not (tmp_path / "qualification-complete.json").exists()

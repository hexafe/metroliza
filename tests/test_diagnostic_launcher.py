import json
import os
import sys
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from metroliza.app.diagnostic_launcher import run_with_store
from metroliza.shared.diagnostic_events import (
    WorkflowDiagnosticEvent,
    WorkflowError,
    WorkflowOperation,
    WorkflowOutcome,
    WorkflowStage,
)
from metroliza.shared.diagnostic_ring import DiagnosticRing
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus
from metroliza.shared.diagnostic_wire import encode_event


def test_real_exit_publishes_same_session_incident_and_selected_export(tmp_path):
    store = IncidentStore(tmp_path / "state")
    child = Path(__file__).parent / "fixtures" / "diagnostic_child.py"
    delivery = run_with_store([sys.executable, str(child), "hard_exit"], store=store)
    assert delivery.observation.exit_code == 9
    assert delivery.storage_status is StoreStatus.SAVED
    listing = store.list_reports()
    assert listing.status is StoreStatus.AVAILABLE
    assert len(listing.reports) == 1
    loaded = store.load(listing.reports[0].report_id)
    assert loaded.incident.session_id.hex == delivery.observation.session_id
    assert json.loads(loaded.incident.events[0])["invocation_id"] == delivery.observation.session_id
    assert store.list_unclean_sessions().sessions == ()
    target = tmp_path / "chosen.zip"
    assert store.export(listing.reports[0].report_id, target).status is StoreStatus.EXPORTED
    import zipfile

    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {"incident.json", "manifest.json", "summary.json"}
        assert b"SYNTHETIC_RAW_SECRET" not in archive.read("incident.json")


def test_normal_observed_exit_has_only_clean_marker_and_no_crash_report(tmp_path):
    store = IncidentStore(tmp_path / "state")
    child = Path(__file__).parent / "fixtures" / "diagnostic_child.py"
    delivery = run_with_store([sys.executable, str(child), "normal"], store=store)
    assert delivery.storage_status is StoreStatus.MARKER_CLEAN_ENDED
    assert not delivery.observation.needs_incident
    assert store.list_reports().reports == ()
    assert store.list_unclean_sessions().sessions == ()


def test_unavailable_store_does_not_change_child_result_or_use_cwd(tmp_path, monkeypatch):
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("synthetic", encoding="utf-8")
    store = IncidentStore(occupied)
    child = Path(__file__).parent / "fixtures" / "diagnostic_child.py"
    monkeypatch.chdir(tmp_path)
    delivery = run_with_store([sys.executable, str(child), "hard_exit"], store=store)
    assert delivery.observation.exit_code == 9
    assert delivery.storage_status is not StoreStatus.SAVED
    assert not (tmp_path / "metroliza.log").exists()
    assert not tuple(tmp_path.glob("incident-*"))


def test_real_caught_import_failure_is_viewable_while_app_still_runs(tmp_path):
    store = IncidentStore(tmp_path / "state")
    scratch = tmp_path / "work"
    scratch.mkdir()
    root = Path(__file__).resolve().parents[1]
    child = root / "tests/fixtures/diagnostic_workflow_child.py"
    env = dict(os.environ, METROLIZA_STARTUP_SMOKE="1", METROLIZA_LICENSE_VERIFICATION="0",
               PYTHONPATH=os.pathsep.join((str(root / "src"), str(root))))
    deliveries = []
    thread = threading.Thread(
        target=lambda: deliveries.append(
            run_with_store(
                [sys.executable, str(child), str(scratch), "handled_failure"],
                store=store,
                env=env,
                cwd=scratch,
            )
        )
    )
    thread.start()
    try:
        deadline = time.monotonic() + 7
        reports = store.list_reports().reports
        operation_returned = (scratch / "operation_returned").exists()
        while (not reports or not operation_returned) and time.monotonic() < deadline:
            time.sleep(0.02)
            if not reports:
                reports = store.list_reports().reports
            operation_returned = (scratch / "operation_returned").exists()
        assert operation_returned
        assert thread.is_alive()
        assert len(reports) == 1
        incident = store.load(reports[0].report_id).incident
        assert incident.observation.termination.value == "still_running"
        assert incident.observation.exit_code is None
        terminal = json.loads(incident.events[-1])
        assert terminal["operation"] == "selected_import"
        assert terminal["outcome"] == "failed"
        assert terminal["validation_status"] == "not_performed"
        export = store.export(reports[0].report_id, tmp_path / "selected.zip")
        assert export.status is StoreStatus.EXPORTED
    finally:
        (scratch / "finish").touch()
        thread.join(10)
    assert not thread.is_alive()
    assert deliveries[0].observation.exit_code == 0
    assert deliveries[0].storage_status is StoreStatus.SAVED
    reports = store.list_reports().reports
    assert len(reports) == 2
    incidents = [store.load(report.report_id).incident for report in reports]
    final = next(
        incident
        for incident in incidents
        if incident is not None and incident.observation.exit_code == 0
    )
    assert final.observation.clean_terminal_received
    assert json.loads(final.events[-1])["outcome"] == "failed"
    assert store.list_unclean_sessions().sessions == ()


def _live_observation():
    from metroliza.app.diagnostic_supervisor import launch_supervised

    child = Path(__file__).parent / "fixtures/diagnostic_child.py"
    observed = launch_supervised([sys.executable, str(child), "hard_exit"])
    return replace(observed, termination="still_running", exit_code=None)


def _failed_history_observation():
    observed = _live_observation()
    ring = DiagnosticRing()
    now = time.monotonic()
    for sequence in range(1, 4):
        event = WorkflowDiagnosticEvent(
            invocation_id=uuid.UUID(hex=observed.session_id),
            operation_id=uuid.UUID(f"{sequence:08x}-0000-4000-8000-000000000000"),
            sequence=1,
            operation=WorkflowOperation.LOCAL_EXPORT,
            stage=WorkflowStage.FINISHED,
            outcome=WorkflowOutcome.FAILED,
            error=WorkflowError.OUTPUT_FAILED,
        )
        assert ring.add(encode_event(event), now=now)
    return replace(observed, history=ring.snapshot(now=now))


def test_transient_cross_process_store_lock_does_not_lose_live_incident(tmp_path):
    from metroliza.app.diagnostic_launcher import _OperationPublisher
    from metroliza.shared.diagnostic_store import _StoreLock

    store = IncidentStore(tmp_path / "state")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    lock = _StoreLock(store.root)
    assert lock.acquire()
    observed = _live_observation()
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()
    try:
        assert publisher.submit(observed)
        time.sleep(0.3)  # Exceeds the first real store lock attempt's 0.25s bound.
        lock.release()
        deadline = time.monotonic() + 2
        while not store.list_reports().reports and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(store.list_reports().reports) == 1
        final = replace(
            observed,
            channel="complete",
            clean_terminal_received=True,
            source_loss_known=True,
            exit_code=0,
            termination="observed_exit",
        )
        assert publisher.close(final) is StoreStatus.MARKER_CLEAN_ENDED
    finally:
        lock.release()


def test_stalled_disk_publisher_returns_unknown_completion_with_bounded_queue(
    tmp_path, monkeypatch
):
    from metroliza.app.diagnostic_launcher import _OperationPublisher
    from metroliza.shared.diagnostic_store import StoreResult

    entered, release = threading.Event(), threading.Event()
    store = IncidentStore(tmp_path / "state")
    def stalled(_incident):
        entered.set()
        release.wait(3)
        return StoreResult(StoreStatus.IO_FAILED)
    monkeypatch.setattr(store, "publish", stalled)
    observed = _live_observation()
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()
    try:
        assert publisher.submit(observed)
        assert entered.wait(1)
        assert publisher.submit(observed)
        assert not publisher.submit(observed)
        started = time.monotonic()
        assert publisher.close(observed) is StoreStatus.PUBLISH_INCOMPLETE
        assert time.monotonic() - started < 1.5
    finally:
        release.set()
        publisher.worker.join(2)
    assert not publisher.worker.is_alive()


@pytest.mark.parametrize("caught_failure", (False, True))
def test_final_incident_skips_unnecessary_marker_retries(
    tmp_path,
    monkeypatch,
    caught_failure,
):
    from metroliza.app.diagnostic_launcher import _OperationPublisher

    store = IncidentStore(tmp_path / "state")
    observed = _failed_history_observation() if caught_failure else _live_observation()
    if caught_failure:
        observed = replace(
            observed,
            channel="complete",
            clean_terminal_received=True,
            source_loss_known=True,
            exit_code=0,
            termination="observed_exit",
        )

    def unnecessary_marker_call(*_args, **_kwargs):
        raise AssertionError("final incident must not create marker controls")

    monkeypatch.setattr(store, "begin_session", unnecessary_marker_call)
    monkeypatch.setattr(store, "authenticate_session", unnecessary_marker_call)
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()

    started = time.monotonic()
    assert publisher.close(observed) is StoreStatus.SAVED
    assert time.monotonic() - started < 0.75
    reports = store.list_reports().reports
    assert len(reports) == 1
    assert store.load(reports[0].report_id).incident.session_id.hex == observed.session_id
    assert store.list_unclean_sessions().sessions == ()


def test_inflight_begin_finishes_before_final_incident_is_persisted(tmp_path, monkeypatch):
    from metroliza.app.diagnostic_launcher import _OperationPublisher

    store = IncidentStore(tmp_path / "state")
    observed = replace(_live_observation(), termination="observed_exit", exit_code=9)
    begin_entered, release_begin = threading.Event(), threading.Event()
    sequence = []
    original_begin = store.begin_session
    original_publish = store.publish

    def held_begin(*args, **kwargs):
        sequence.append("begin_entered")
        begin_entered.set()
        release_begin.wait(2)
        result = original_begin(*args, **kwargs)
        sequence.append("begin_finished")
        return result

    def recorded_publish(incident):
        sequence.append("publish")
        return original_publish(incident)

    monkeypatch.setattr(store, "begin_session", held_begin)
    monkeypatch.setattr(store, "publish", recorded_publish)
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()
    assert publisher.begin()
    assert begin_entered.wait(1)
    statuses = []
    closer = threading.Thread(target=lambda: statuses.append(publisher.close(observed)))
    closer.start()
    try:
        release_begin.set()
        closer.join(2)
    finally:
        release_begin.set()
        closer.join(2)

    assert statuses == [StoreStatus.SAVED]
    assert sequence == ["begin_entered", "begin_finished", "publish"]
    assert store.list_unclean_sessions().sessions == ()


@pytest.mark.parametrize(
    ("method", "scenario", "expected_exit"),
    (("begin_session", "normal", 0), ("publish", "hard_exit", 9), ("end_session", "normal", 0)),
)
def test_stalled_store_io_is_bounded_and_preserves_actual_child_exit(
    tmp_path, monkeypatch, method, scenario, expected_exit
):
    store = IncidentStore(tmp_path / "state")
    entered, release = threading.Event(), threading.Event()
    original = getattr(store, method)

    def stalled(*args, **kwargs):
        entered.set()
        release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, method, stalled)
    child = Path(__file__).parent / "fixtures" / "diagnostic_child.py"
    started = time.monotonic()
    try:
        delivery = run_with_store([sys.executable, str(child), scenario], store=store)
        assert entered.is_set()
        assert delivery.observation.exit_code == expected_exit
        assert delivery.storage_status is StoreStatus.PUBLISH_INCOMPLETE
        assert time.monotonic() - started < 2.5
    finally:
        release.set()


def test_final_control_survives_three_failed_terminal_backlog(tmp_path, monkeypatch):
    from metroliza.app.diagnostic_launcher import _OperationPublisher
    from metroliza.shared.diagnostic_store import StoreResult

    store = IncidentStore(tmp_path / "state")
    observed = _failed_history_observation()
    entered, release = threading.Event(), threading.Event()
    original = store.publish
    first = True

    def fail_first(incident):
        nonlocal first
        if first:
            first = False
            entered.set()
            release.wait(3)
            return StoreResult(StoreStatus.IO_FAILED)
        return original(incident)

    monkeypatch.setattr(store, "publish", fail_first)
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()
    assert publisher.submit(observed)
    assert entered.wait(1)
    assert publisher.submit(observed)
    assert not publisher.submit(observed)
    final = replace(
        observed,
        channel="complete",
        clean_terminal_received=True,
        source_loss_known=True,
        exit_code=0,
        termination="observed_exit",
    )
    statuses = []
    closer = threading.Thread(target=lambda: statuses.append(publisher.close(final)))
    closer.start()
    try:
        deadline = time.monotonic() + 1
        while not publisher.closing and time.monotonic() < deadline:
            time.sleep(0.01)
        release.set()
        closer.join(2)
    finally:
        release.set()
        closer.join(2)
    assert statuses == [StoreStatus.SAVED]
    reports = store.list_reports().reports
    assert len(reports) == 1
    incident = store.load(reports[0].report_id).incident
    assert incident is not None
    assert incident.observation.channel.value == "complete"
    assert incident.observation.exit_code == 0
    assert len(incident.events) == 3


def test_real_child_final_preserves_recent_failure_after_saved_live_backlog(
    tmp_path, monkeypatch
):
    from metroliza.shared.diagnostic_store import StoreResult

    store = IncidentStore(tmp_path / "state")
    original = store.publish
    publish_count = 0

    def hold_first_live_publish(incident):
        nonlocal publish_count
        publish_count += 1
        if publish_count == 1:
            (tmp_path / "live_publish_entered").touch()
            deadline = time.monotonic() + 5
            while not (tmp_path / "child_finished").exists():
                if time.monotonic() >= deadline:
                    return StoreResult(StoreStatus.IO_FAILED)
                time.sleep(0.01)
            time.sleep(0.15)
        return original(incident)

    monkeypatch.setattr(store, "publish", hold_first_live_publish)
    child = Path(__file__).parent / "fixtures" / "diagnostic_protocol_child.py"
    delivery = run_with_store(
        [sys.executable, str(child), "failure_backlog", str(tmp_path)],
        store=store,
    )

    assert delivery.observation.exit_code == 0
    assert delivery.observation.clean_terminal_received
    assert delivery.observation.channel == "complete"
    assert delivery.storage_status is StoreStatus.SAVED
    assert publish_count == 2
    assert store.list_unclean_sessions().sessions == ()
    incidents = [
        store.load(report.report_id).incident
        for report in store.list_reports().reports
    ]
    assert len(incidents) == 2
    final = next(
        incident
        for incident in incidents
        if incident is not None and incident.observation.exit_code == 0
    )
    assert final.session_id.hex == delivery.observation.session_id
    assert final.observation.clean_terminal_received
    assert len(final.events) == 2
    recent = json.loads(final.events[-1])
    assert recent["operation_id"] == "00000002000040008000000000000000"
    assert recent["outcome"] == "failed"


@pytest.mark.parametrize("failed_thread", ["diagnostic-receiver", "incident-publisher"])
def test_diagnostic_thread_exhaustion_does_not_prevent_actual_app_start(
    tmp_path, monkeypatch, failed_thread
):
    start = threading.Thread.start
    def exhausted(self):
        if self.name == failed_thread:
            raise RuntimeError("SYNTHETIC_THREAD_LIMIT")
        return start(self)
    monkeypatch.setattr(threading.Thread, "start", exhausted)
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, METROLIZA_STARTUP_SMOKE="1", METROLIZA_LICENSE_VERIFICATION="0")
    delivery = run_with_store(
        [sys.executable, str(root / "packaging/metroliza_package_entry.py")],
        store=IncidentStore(tmp_path / "state"), env=env, cwd=tmp_path,
    )
    assert delivery.observation.exit_code == 0
    if failed_thread == "diagnostic-receiver":
        assert delivery.observation.handshake == "missing"
        assert delivery.storage_status is StoreStatus.SAVED
    else:
        assert delivery.storage_status is StoreStatus.IO_FAILED

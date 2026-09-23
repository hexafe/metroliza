import json
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
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
from metroliza.shared.diagnostic_store import IncidentStore, StoreResult, StoreStatus
from metroliza.shared.diagnostic_wire import encode_event


_FIXTURE_SETUP_MARKERS = (
    ("setup_started", "started"),
    ("setup_bootstrap_ready", "bootstrap_ready"),
    ("setup_parser_imports_ready", "parser_imports_ready"),
    ("setup_preflight_ready", "preflight_ready"),
)


def _fixture_setup_failure(scratch, thread, deliveries):
    stage = "not_started"
    for marker, observed_stage in _FIXTURE_SETUP_MARKERS:
        if (scratch / marker).exists():
            stage = observed_stage
    if thread.is_alive():
        child_state = "running"
    elif not deliveries:
        child_state = "delivery_unavailable"
    elif deliveries[0].observation.exit_code == 0:
        child_state = "exit_zero"
    else:
        child_state = "exit_nonzero"
    return f"fixture_setup_not_ready:{stage}:{child_state}"


def _trace_publisher_calls(monkeypatch, store):
    """Capture only fixed operation/status/timing facts for a failing native test."""
    from metroliza.app.diagnostic_launcher import _OperationPublisher

    calls = []
    guard = threading.Lock()
    dropped_calls = 0
    frozen_snapshot = None
    operations = (
        "begin_session", "authenticate_session", "publish", "end_session",
        "resolve_session",
    )
    for name in operations:
        original = getattr(store, name)

        def recorded(*args, _name=name, _original=original, **kwargs):
            nonlocal dropped_calls
            started = time.monotonic()
            item = {"operation": _name, "started": started, "status": "in_flight"}
            with guard:
                if len(calls) < 16:
                    calls.append(item)
                else:
                    dropped_calls = min(1_000, dropped_calls + 1)
            status = "raised"
            try:
                result = _original(*args, **kwargs)
                result_status = getattr(result, "status", None)
                status = (
                    result_status.value
                    if type(result_status) is StoreStatus else "invalid_status"
                )
                return result
            finally:
                with guard:
                    item["status"] = status
                    item["finished"] = time.monotonic()
                    item["elapsed_ms"] = min(
                        10_000, int((item["finished"] - started) * 1000)
                    )

        monkeypatch.setattr(store, name, recorded)

    original_close = _OperationPublisher.close

    def recorded_close(publisher, observed):
        nonlocal frozen_snapshot
        started = time.monotonic()
        result = original_close(publisher, observed)
        close_returned = time.monotonic()
        with guard:
            frozen_snapshot = {
                "calls": [
                    {
                        "operation": item["operation"],
                        "status": item["status"],
                        "completion": (
                            "started_after_close_return"
                            if item["started"] > close_returned else
                            "in_flight_at_close_return"
                            if "finished" not in item or item["finished"] > close_returned else
                            "completed_before_close_return"
                        ),
                        "elapsed_ms": item.get(
                            "elapsed_ms", max(
                                0, min(
                                    10_000, int((close_returned - item["started"]) * 1000)
                                )
                            )
                        ),
                    }
                    for item in calls
                ],
                "dropped_calls": dropped_calls,
                "observation_phase": "post_close_return",
                "close": {
                    "status": result.value,
                    "elapsed_ms": min(10_000, int((close_returned - started) * 1000)),
                    "post_close_worker_alive": publisher.worker.is_alive(),
                    "post_close_done": publisher.done.is_set(),
                    "post_close_final_saved": publisher.final_saved.is_set(),
                },
            }
        return result

    monkeypatch.setattr(_OperationPublisher, "close", recorded_close)

    def snapshot():
        with guard:
            return frozen_snapshot

    return snapshot


@contextmanager
def _authenticated_marker_child(tmp_path, monkeypatch, store, scenario):
    """Separate final persistence from the separately tested cold-I/O backlog."""
    barrier = tmp_path / "authenticated-marker-ready"
    authenticate = store.authenticate_session

    def authenticated(*args, **kwargs):
        result = authenticate(*args, **kwargs)
        if result.status is StoreStatus.MARKER_AUTHENTICATED:
            with barrier.open("x", encoding="ascii") as stream:
                stream.write("ready")
        return result

    monkeypatch.setattr(store, "authenticate_session", authenticated)
    child = Path(__file__).parent / "fixtures" / "diagnostic_child.py"
    try:
        yield [sys.executable, str(child), scenario, str(barrier)]
    finally:
        barrier.unlink(missing_ok=True)


def test_real_exit_publishes_same_session_incident_and_selected_export(tmp_path, monkeypatch):
    store = IncidentStore(tmp_path / "state")
    with _authenticated_marker_child(tmp_path, monkeypatch, store, "hard_exit_after_marker") as command:
        trace = _trace_publisher_calls(monkeypatch, store)
        delivery = run_with_store(command, store=store)
    exit_code = delivery.observation.exit_code
    assert exit_code == 9
    actual_status = delivery.storage_status
    assert actual_status is StoreStatus.SAVED, json.dumps(trace(), sort_keys=True)
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


def test_normal_observed_exit_has_only_clean_marker_and_no_crash_report(tmp_path, monkeypatch):
    store = IncidentStore(tmp_path / "state")
    with _authenticated_marker_child(tmp_path, monkeypatch, store, "normal_after_marker") as command:
        trace = _trace_publisher_calls(monkeypatch, store)
        delivery = run_with_store(command, store=store)
    actual_status = delivery.storage_status
    assert actual_status is StoreStatus.MARKER_CLEAN_ENDED, json.dumps(trace(), sort_keys=True)
    assert not delivery.observation.needs_incident
    assert store.list_reports().reports == ()
    assert store.list_unclean_sessions().sessions == ()


def test_publisher_trace_identifies_unfinished_store_call_without_changing_close(
    tmp_path, monkeypatch
):
    from metroliza.app.diagnostic_launcher import _OperationPublisher

    store = IncidentStore(tmp_path / "state")
    entered, release = threading.Event(), threading.Event()
    original_begin = store.begin_session

    def held_begin(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original_begin(*args, **kwargs)

    monkeypatch.setattr(store, "begin_session", held_begin)
    trace = _trace_publisher_calls(monkeypatch, store)
    observed = _live_observation()
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()
    assert publisher.begin()
    try:
        assert entered.wait(1)
        actual_status = publisher.close(observed)
        at_return = trace()
        assert actual_status is StoreStatus.PUBLISH_INCOMPLETE
        assert at_return["close"]["status"] == StoreStatus.PUBLISH_INCOMPLETE.value
        assert at_return["close"]["post_close_worker_alive"] is True
        assert at_return["close"]["post_close_done"] is False
        assert at_return["close"]["post_close_final_saved"] is False
        assert at_return["calls"][0]["operation"] == "begin_session"
        assert at_return["calls"][0]["status"] == "in_flight"
        assert at_return["calls"][0]["completion"] == "in_flight_at_close_return"
    finally:
        release.set()
        publisher.worker.join(2)
    assert not publisher.worker.is_alive()


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
        # This is cold fixture initialization, not the measured incident path.
        # A native integration run exceeded 10 s before bootstrap was ready;
        # preserve the separate 7 s operation and 10 s shutdown bounds below.
        readiness_deadline = time.monotonic() + 30
        while (
            not (scratch / "operation_ready").exists()
            and thread.is_alive()
            and time.monotonic() < readiness_deadline
        ):
            time.sleep(0.02)
        if not (scratch / "operation_ready").exists():
            pytest.fail(_fixture_setup_failure(scratch, thread, deliveries))
        assert all((scratch / marker).exists() for marker, _stage in _FIXTURE_SETUP_MARKERS)
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
        # A setup/operation assertion must not bypass the cleanup assertion.
        assert not thread.is_alive(), _fixture_setup_failure(scratch, thread, deliveries)
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


def test_final_incident_retries_one_lock_denial_then_real_publication_within_close_deadline(
    tmp_path, monkeypatch
):
    from metroliza.app.diagnostic_launcher import _OperationPublisher
    store = IncidentStore(tmp_path / "state")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    observed = replace(_live_observation(), termination="observed_exit", exit_code=9)
    attempted_statuses = []
    original_publish = store.publish

    def recorded_publish(incident):
        # Retry policy is separate from the real store's 0.25s lock wait.
        # Held-lock denial/no partial file and over-deadline close have their
        # own real-lock controls. The accepted retry still writes the real store.
        result = (StoreResult(StoreStatus.LOCK_UNAVAILABLE)
                  if not attempted_statuses else original_publish(incident))
        attempted_statuses.append(result.status)
        return result

    def unnecessary_marker_call(*_args, **_kwargs):
        raise AssertionError("final incident must not create marker controls")

    monkeypatch.setattr(store, "publish", recorded_publish)
    monkeypatch.setattr(store, "begin_session", unnecessary_marker_call)
    monkeypatch.setattr(store, "authenticate_session", unnecessary_marker_call)
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()
    try:
        status = publisher.close(observed)
    finally:
        publisher.worker.join(1)

    assert status is StoreStatus.SAVED
    assert attempted_statuses == [StoreStatus.LOCK_UNAVAILABLE, StoreStatus.SAVED]
    reports = store.list_reports().reports
    assert len(reports) == 1
    incident = store.load(reports[0].report_id).incident
    assert incident is not None
    assert incident.session_id.hex == observed.session_id
    assert incident.events == observed.history.events
    assert incident.ring_loss == observed.history.loss
    assert store.list_unclean_sessions().sessions == ()


def test_clean_marker_retries_one_lock_denial_then_real_end_within_close_deadline(
    tmp_path, monkeypatch
):
    from metroliza.app.diagnostic_launcher import _OperationPublisher
    store = IncidentStore(tmp_path / "state")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    observed = replace(
        _live_observation(),
        channel="complete",
        clean_terminal_received=True,
        source_loss_known=True,
        termination="observed_exit",
        exit_code=0,
    )
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher._ensure_begin() is StoreStatus.MARKER_STARTED
    assert publisher._ensure_authenticated() is StoreStatus.MARKER_AUTHENTICATED
    assert publisher.start()
    marker = store.root / f"marker-{observed.session_id}.json"
    attempted_statuses = []
    original_end = store.end_session

    def recorded_end(*args, **kwargs):
        result = (StoreResult(StoreStatus.LOCK_UNAVAILABLE)
                  if not attempted_statuses else original_end(*args, **kwargs))
        attempted_statuses.append(result.status)
        return result

    monkeypatch.setattr(store, "end_session", recorded_end)
    try:
        status = publisher.close(observed)
    finally:
        publisher.worker.join(1)

    assert status is StoreStatus.MARKER_CLEAN_ENDED
    assert attempted_statuses == [
        StoreStatus.LOCK_UNAVAILABLE,
        StoreStatus.MARKER_CLEAN_ENDED,
    ]
    assert marker.is_file()
    assert store.end_session(observed.session_id, clean=False).status is StoreStatus.INVALID


def test_clean_marker_store_lock_past_close_deadline_is_bounded(
    tmp_path, monkeypatch
):
    from metroliza.app.diagnostic_launcher import _OperationPublisher
    from metroliza.shared.diagnostic_store import _StoreLock

    store = IncidentStore(tmp_path / "state")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    observed = replace(
        _live_observation(),
        channel="complete",
        clean_terminal_received=True,
        source_loss_known=True,
        termination="observed_exit",
        exit_code=0,
    )
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher._ensure_begin() is StoreStatus.MARKER_STARTED
    assert publisher._ensure_authenticated() is StoreStatus.MARKER_AUTHENTICATED
    assert publisher.start()
    marker = store.root / f"marker-{observed.session_id}.json"
    lock = _StoreLock(store.root)
    assert lock.acquire()
    attempted_statuses = []
    original_end = store.end_session

    def recorded_end(*args, **kwargs):
        result = original_end(*args, **kwargs)
        attempted_statuses.append(result.status)
        return result

    monkeypatch.setattr(store, "end_session", recorded_end)
    started = time.monotonic()
    try:
        assert publisher.close(observed) is StoreStatus.PUBLISH_INCOMPLETE
        assert time.monotonic() - started < 1.0
        publisher.worker.join(1)
    finally:
        lock.release()
        publisher.worker.join(1)

    assert not publisher.worker.is_alive()
    assert attempted_statuses
    assert set(attempted_statuses) == {StoreStatus.LOCK_UNAVAILABLE}
    assert publisher.final_status is StoreStatus.LOCK_UNAVAILABLE
    assert marker.is_file()
    assert (
        store.end_session(observed.session_id, clean=False).status
        is StoreStatus.MARKER_RETAINED
    )
    assert marker.is_file()


@pytest.mark.parametrize("inflight_method", ("begin_session", "authenticate_session"))
def test_clean_finalize_starts_no_store_call_after_close_deadline(
    tmp_path, monkeypatch, inflight_method
):
    from metroliza.app.diagnostic_launcher import _OperationPublisher

    store = IncidentStore(tmp_path / "state")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    observed = replace(
        _live_observation(),
        channel="complete",
        clean_terminal_received=True,
        source_loss_known=True,
        termination="observed_exit",
        exit_code=0,
    )
    entered, release = threading.Event(), threading.Event()
    calls = {"begin_session": 0, "authenticate_session": 0, "end_session": 0}
    original_begin = store.begin_session
    original_authenticate = store.authenticate_session
    original_end = store.end_session

    def recorded_begin(*args, **kwargs):
        calls["begin_session"] += 1
        if inflight_method == "begin_session":
            entered.set()
            assert release.wait(2)
        return original_begin(*args, **kwargs)

    def recorded_authenticate(*args, **kwargs):
        calls["authenticate_session"] += 1
        if inflight_method == "authenticate_session":
            entered.set()
            assert release.wait(2)
        return original_authenticate(*args, **kwargs)

    def recorded_end(*args, **kwargs):
        calls["end_session"] += 1
        return original_end(*args, **kwargs)

    monkeypatch.setattr(store, "begin_session", recorded_begin)
    monkeypatch.setattr(store, "authenticate_session", recorded_authenticate)
    monkeypatch.setattr(store, "end_session", recorded_end)
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()
    queued = (
        publisher.begin()
        if inflight_method == "begin_session"
        else publisher.authenticate(observed.session_id)
    )
    assert queued
    assert entered.wait(1)
    statuses = []
    close_returned = threading.Event()

    def close_publisher():
        statuses.append(publisher.close(observed))
        close_returned.set()

    closer = threading.Thread(target=close_publisher)
    closer.start()
    try:
        assert close_returned.wait(1.2)
        assert statuses == [StoreStatus.PUBLISH_INCOMPLETE]
        release.set()
        publisher.worker.join(2)
    finally:
        release.set()
        closer.join(2)
        publisher.worker.join(2)

    assert not publisher.worker.is_alive()
    expected = (
        {"begin_session": 1, "authenticate_session": 0, "end_session": 0}
        if inflight_method == "begin_session"
        else {"begin_session": 1, "authenticate_session": 1, "end_session": 0}
    )
    assert calls == expected
    assert (store.root / f"marker-{observed.session_id}.json").is_file()


def test_final_incident_starts_no_publish_after_close_deadline(tmp_path, monkeypatch):
    from metroliza.app.diagnostic_launcher import _OperationPublisher

    store = IncidentStore(tmp_path / "state")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    observed = replace(_live_observation(), termination="observed_exit", exit_code=9)
    entered, release = threading.Event(), threading.Event()
    original_begin = store.begin_session
    original_publish = store.publish
    publish_calls = 0

    def held_begin(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original_begin(*args, **kwargs)

    def recorded_publish(*args, **kwargs):
        nonlocal publish_calls
        publish_calls += 1
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(store, "begin_session", held_begin)
    monkeypatch.setattr(store, "publish", recorded_publish)
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()
    assert publisher.begin()
    assert entered.wait(1)
    statuses = []
    close_returned = threading.Event()

    def close_publisher():
        statuses.append(publisher.close(observed))
        close_returned.set()

    closer = threading.Thread(target=close_publisher)
    closer.start()
    try:
        assert close_returned.wait(1.2)
        assert statuses == [StoreStatus.PUBLISH_INCOMPLETE]
        release.set()
        publisher.worker.join(2)
    finally:
        release.set()
        closer.join(2)
        publisher.worker.join(2)

    assert not publisher.worker.is_alive()
    assert publish_calls == 0
    assert store.list_reports().reports == ()
    assert (store.root / f"marker-{observed.session_id}.json").is_file()


def test_final_incident_store_lock_past_close_deadline_is_bounded(tmp_path, monkeypatch):
    from metroliza.app.diagnostic_launcher import _OperationPublisher
    from metroliza.shared.diagnostic_store import _StoreLock

    store = IncidentStore(tmp_path / "state")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    lock = _StoreLock(store.root)
    assert lock.acquire()
    observed = replace(_live_observation(), termination="observed_exit", exit_code=9)

    def unnecessary_marker_call(*_args, **_kwargs):
        raise AssertionError("final incident must not create marker controls")

    monkeypatch.setattr(store, "begin_session", unnecessary_marker_call)
    monkeypatch.setattr(store, "authenticate_session", unnecessary_marker_call)
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()
    started = time.monotonic()
    try:
        assert publisher.close(observed) is StoreStatus.PUBLISH_INCOMPLETE
        assert time.monotonic() - started < 1.0
    finally:
        lock.release()
        publisher.worker.join(1)
    assert not publisher.worker.is_alive()


@pytest.mark.parametrize("resolution", ("stalled", "raised"))
def test_saved_final_incident_is_authoritative_before_marker_resolution(
    tmp_path, monkeypatch, resolution
):
    from metroliza.app.diagnostic_launcher import _OperationPublisher

    store = IncidentStore(tmp_path / "state")
    observed = replace(_live_observation(), termination="observed_exit", exit_code=9)
    marker = store.root / f"marker-{observed.session_id}.json"
    assert store.begin_session(observed.session_id, "unknown").status is StoreStatus.MARKER_STARTED
    assert (
        store.authenticate_session(observed.session_id).status
        is StoreStatus.MARKER_AUTHENTICATED
    )
    resolve_entered, release_resolve = threading.Event(), threading.Event()
    original_resolve = store.resolve_session

    def stalled_resolve(*args, **kwargs):
        resolve_entered.set()
        if resolution == "raised":
            raise OSError("synthetic marker resolution failure")
        release_resolve.wait(2)
        return original_resolve(*args, **kwargs)

    def unnecessary_marker_call(*_args, **_kwargs):
        raise AssertionError("final incident must not create marker controls")

    monkeypatch.setattr(store, "resolve_session", stalled_resolve)
    monkeypatch.setattr(store, "begin_session", unnecessary_marker_call)
    monkeypatch.setattr(store, "authenticate_session", unnecessary_marker_call)
    publisher = _OperationPublisher(store, "unknown", observed.session_id)
    assert publisher.start()
    started = time.monotonic()
    try:
        assert publisher.close(observed) is StoreStatus.SAVED
        assert resolve_entered.is_set()
        assert time.monotonic() - started < 1.0
        reports = store.list_reports().reports
        assert len(reports) == 1
        incident = store.load(reports[0].report_id).incident
        assert incident is not None
        assert incident.session_id.hex == observed.session_id
        assert incident.events == observed.history.events
        assert incident.ring_loss == observed.history.loss
        assert marker.is_file()
    finally:
        release_resolve.set()
        publisher.worker.join(1)
    assert not publisher.worker.is_alive()
    if resolution == "stalled":
        assert not marker.exists()
        assert store.list_unclean_sessions().sessions == ()
    else:
        assert marker.is_file()


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
    assert store.list_reports().status is StoreStatus.AVAILABLE
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
    command = [sys.executable, str(child), scenario]
    child_context = (
        _authenticated_marker_child(tmp_path, monkeypatch, store, "normal_after_marker")
        if method == "end_session" else nullcontext(command)
    )
    trace = _trace_publisher_calls(monkeypatch, store)
    started = time.monotonic()
    try:
        with child_context as selected_command:
            delivery = run_with_store(selected_command, store=store)
        assert entered.is_set(), json.dumps(trace(), sort_keys=True)
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
    # This barrier measures backlog delivery, after real marker preparation.
    assert publisher._ensure_begin() is StoreStatus.MARKER_STARTED
    assert publisher._ensure_authenticated() is StoreStatus.MARKER_AUTHENTICATED
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


@pytest.mark.parametrize("scenario", ["normal", "hard_exit", "handled_failure", "preview", "idle", "flood", "concurrent"])
@pytest.mark.parametrize("synthetic", [False, True])
def test_fixed_notice_is_noninteractive_only_in_explicit_synthetic_scenarios(monkeypatch, scenario, synthetic):
    import ctypes
    from types import SimpleNamespace
    from metroliza.app import diagnostic_launcher as launcher

    calls = []
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(
        MessageBoxW=lambda *args: calls.append(args)
    )), raising=False)
    monkeypatch.setattr(launcher, "os", SimpleNamespace(name="nt", getenv=os.getenv))
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", scenario)
    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1" if synthetic else "0")
    launcher._fixed_notice("fixed notice")
    assert calls == ([] if synthetic else [(None, "fixed notice", "Metroliza", 0x10)])

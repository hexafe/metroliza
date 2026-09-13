import json
from pathlib import Path
import sys
import os
import threading
import time

from metroliza.app.diagnostic_launcher import run_with_store
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus


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
    thread = threading.Thread(target=lambda: deliveries.append(run_with_store(
        [sys.executable, str(child), str(scratch), "handled_failure"], store=store, env=env, cwd=scratch,
    )))
    thread.start()
    try:
        deadline = time.monotonic() + 7
        while not store.list_reports().reports and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (scratch / "operation_returned").exists()
        assert thread.is_alive()
        reports = store.list_reports().reports
        assert len(reports) == 1
        incident = store.load(reports[0].report_id).incident
        assert incident.observation.termination.value == "still_running"
        assert incident.observation.exit_code is None
        terminal = json.loads(incident.events[-1])
        assert terminal["operation"] == "selected_import"
        assert terminal["outcome"] == "failed"
        assert terminal["validation_status"] == "not_performed"
        assert store.export(reports[0].report_id, tmp_path / "selected.zip").status is StoreStatus.EXPORTED
    finally:
        (scratch / "finish").touch()
        thread.join(10)
    assert not thread.is_alive()
    assert deliveries[0].observation.exit_code == 0
    assert deliveries[0].storage_status is StoreStatus.MARKER_CLEAN_ENDED
    assert len(store.list_reports().reports) == 1


def _live_observation():
    from dataclasses import replace
    from metroliza.app.diagnostic_supervisor import launch_supervised

    child = Path(__file__).parent / "fixtures/diagnostic_child.py"
    observed = launch_supervised([sys.executable, str(child), "hard_exit"])
    return replace(observed, termination="still_running", exit_code=None)


def test_transient_cross_process_store_lock_does_not_lose_live_incident(tmp_path):
    from metroliza.app.diagnostic_launcher import _OperationPublisher
    from metroliza.shared.diagnostic_store import _StoreLock

    store = IncidentStore(tmp_path / "state")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    lock = _StoreLock(store.root)
    assert lock.acquire()
    publisher = _OperationPublisher(store, "unknown")
    publisher.worker.start()
    try:
        assert publisher.submit(_live_observation())
        time.sleep(0.3)  # Exceeds the first real store lock attempt's 0.25s bound.
        lock.release()
        deadline = time.monotonic() + 2
        while not store.list_reports().reports and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(store.list_reports().reports) == 1
        assert publisher.close() is StoreStatus.AVAILABLE
    finally:
        lock.release()
        publisher.close()


def test_stalled_disk_publisher_returns_unknown_completion_with_bounded_queue(tmp_path, monkeypatch):
    from metroliza.app.diagnostic_launcher import _OperationPublisher
    from metroliza.shared.diagnostic_store import StoreResult

    entered, release = threading.Event(), threading.Event()
    store = IncidentStore(tmp_path / "state")
    def stalled(_incident):
        entered.set()
        release.wait(3)
        return StoreResult(StoreStatus.IO_FAILED)
    monkeypatch.setattr(store, "publish", stalled)
    publisher = _OperationPublisher(store, "unknown")
    publisher.worker.start()
    observed = _live_observation()
    try:
        assert publisher.submit(observed)
        assert entered.wait(1)
        assert publisher.submit(observed)
        assert not publisher.submit(observed)
        started = time.monotonic()
        assert publisher.close() is StoreStatus.PUBLISH_INCOMPLETE
        assert time.monotonic() - started < 1.5
    finally:
        release.set()
        publisher.worker.join(2)
    assert not publisher.worker.is_alive()

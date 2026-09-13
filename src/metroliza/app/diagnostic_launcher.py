"""Compose the minimal supervisor and local private incident store."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import queue
import sys
import threading
import time
import uuid

from metroliza.app.diagnostic_supervisor import SupervisedResult, launch_supervised
from metroliza.shared.diagnostic_incident import (
    ChannelState, HandshakeState, IncidentObservation, LaunchState, TerminationState,
    build_incident,
)
from metroliza.shared.diagnostic_package import inspect_package
from metroliza.shared.diagnostic_ring import DiagnosticRing
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus


@dataclass(frozen=True)
class LaunchDelivery:
    observation: SupervisedResult
    storage_status: StoreStatus


def persist_observation(store: IncidentStore, observed: SupervisedResult, git_sha: str) -> StoreStatus:
    try:
        incident = build_incident(
            session_id=uuid.UUID(hex=observed.session_id), created_at_ms=round(time.time() * 1000),
            build_git_sha=git_sha,
            observation=IncidentObservation(
                LaunchState(observed.launch), HandshakeState(observed.handshake),
                ChannelState(observed.channel), observed.exit_code, TerminationState(observed.termination),
                observed.clean_terminal_received, observed.source_dropped, observed.source_loss_known,
                observed.elapsed_ms,
            ),
            history=observed.history,
        )
        result = store.publish(incident)
        if result.status is StoreStatus.SAVED and observed.termination != "still_running":
            store.resolve_session(observed.session_id, result.report_id)
        return result.status
    except Exception:
        return StoreStatus.IO_FAILED


class _OperationPublisher:
    """One pending snapshot plus one writer; admission never waits for disk.

    Snapshot bytes share the ring's immutable events. Each retained snapshot is
    independently capped at 2 MiB/2000 events; at most two exist outside the ring.
    """

    def __init__(self, store: IncidentStore, git_sha: str):
        self.store, self.git_sha = store, git_sha
        self.pending: queue.Queue[SupervisedResult] = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self.failed = threading.Event()
        self.worker = threading.Thread(target=self._run, name="incident-publisher", daemon=True)

    def submit(self, observed: SupervisedResult) -> bool:
        try:
            self.pending.put_nowait(observed)
            return True
        except queue.Full:
            self.failed.set()
            return False

    def _run(self) -> None:
        while not self.stopping.is_set() or not self.pending.empty():
            try:
                observed = self.pending.get(timeout=0.05)
            except queue.Empty:
                continue
            deadline = time.monotonic() + 1.0
            status = persist_observation(self.store, observed, self.git_sha)
            while (status is StoreStatus.LOCK_UNAVAILABLE and time.monotonic() < deadline
                   and not self.stopping.is_set()):
                time.sleep(0.025)
                status = persist_observation(self.store, observed, self.git_sha)
            if status is not StoreStatus.SAVED:
                self.failed.set()

    def close(self) -> StoreStatus:
        self.stopping.set()
        # At most two outstanding attempts, each with a 0.25s lock deadline;
        # stopping cancels retries. A stalled filesystem remains explicitly unknown.
        self.worker.join(0.75)
        if self.worker.is_alive():
            return StoreStatus.PUBLISH_INCOMPLETE
        return StoreStatus.IO_FAILED if self.failed.is_set() else StoreStatus.AVAILABLE


def run_with_store(argv: list[str], *, store: IncidentStore, git_sha: str = "unknown",
                   env: dict[str, str] | None = None, cwd: Path | None = None) -> LaunchDelivery:
    session = uuid.uuid4().hex
    marker = store.begin_session(session, git_sha)
    publisher = _OperationPublisher(store, git_sha)
    publisher.worker.start()
    try:
        observed = launch_supervised(
            argv, env=env, cwd=cwd, session_id=session,
            on_authenticated=store.authenticate_session,
            on_operation_failure=publisher.submit,
        )
    finally:
        published = publisher.close()
    if observed.needs_incident:
        status = persist_observation(store, observed, git_sha)
    elif marker.status is StoreStatus.MARKER_STARTED:
        status = store.end_session(session, clean=True).status
    else:
        status = marker.status
    if published is not StoreStatus.AVAILABLE:
        status = published
    return LaunchDelivery(observed, status)


def _fixed_notice(message: str) -> None:
    # Fixed UI strings only. No exception, file path, native stack, or raw stream.
    if (os.getenv("METROLIZA_STARTUP_SMOKE") == "1"
            and os.getenv("METROLIZA_DIAGNOSTIC_QUALIFICATION") in
            {"normal", "hard_exit", "handled_failure", "preview", "idle", "flood"}):
        # Disposable qualification asserts exit/store status and cannot dismiss
        # interactive native dialogs. The ordinary-user path retains its notice.
        return
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Metroliza", 0x10)
    elif sys.stderr is not None:
        sys.stderr.write(message + "\n")


def main() -> int:
    store = IncidentStore()
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).absolute().parent
        identity = inspect_package(root)
        if not identity.valid:
            observed = SupervisedResult(
                uuid.uuid4().hex, "failed", "missing", "incomplete", None, "not_started",
                False, 0, False, DiagnosticRing().snapshot(now=time.monotonic()), 0,
            )
            persist_observation(store, observed, identity.git_sha)
            _fixed_notice("Nie można uruchomić aplikacji: brak lub niezgodność składników pakietu.")
            return 1
        argv = [str(root / "metroliza_application.exe"), *sys.argv[1:]]
        git_sha = identity.git_sha
    else:
        root = Path(__file__).resolve().parents[3]
        argv = [sys.executable, str(root / "packaging" / "metroliza_package_entry.py"), *sys.argv[1:]]
        git_sha = "unknown"
    delivery = run_with_store(argv, store=store, git_sha=git_sha)
    if delivery.storage_status not in {StoreStatus.SAVED, StoreStatus.MARKER_CLEAN_ENDED}:
        _fixed_notice("Historia diagnostyczna jest niedostępna lub raport nie został zapisany.")
    code = delivery.observation.exit_code
    return code if code is not None else 1

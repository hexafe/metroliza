"""Compose the minimal supervisor and local private incident store."""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from metroliza.app.diagnostic_supervisor import SupervisedResult, launch_supervised
from metroliza.shared.diagnostic_events import WorkflowDiagnosticEvent, WorkflowOutcome
from metroliza.shared.diagnostic_incident import (
    ChannelState,
    HandshakeState,
    IncidentObservation,
    LaunchState,
    TerminationState,
    build_incident,
)
from metroliza.shared.diagnostic_package import inspect_package
from metroliza.shared.diagnostic_ring import DiagnosticRing
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus
from metroliza.shared.diagnostic_wire import decode_event


@dataclass(frozen=True)
class LaunchDelivery:
    observation: SupervisedResult
    storage_status: StoreStatus


def persist_observation(
    store: IncidentStore, observed: SupervisedResult, git_sha: str
) -> StoreStatus:
    try:
        incident = build_incident(
            session_id=uuid.UUID(hex=observed.session_id), created_at_ms=round(time.time() * 1000),
            build_git_sha=git_sha,
            observation=IncidentObservation(
                LaunchState(observed.launch), HandshakeState(observed.handshake),
                ChannelState(observed.channel),
                observed.exit_code,
                TerminationState(observed.termination),
                observed.clean_terminal_received,
                observed.source_dropped,
                observed.source_loss_known,
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
    """One bounded daemon owns every store call for the supervised process.

    Begin/authentication controls and one live snapshot are bounded. The final
    observation has a separate reserved slot and supersedes queued live history.
    """

    def __init__(self, store: IncidentStore, git_sha: str, session_id: str):
        self.store, self.git_sha, self.session_id = store, git_sha, session_id
        self.controls: deque[str] = deque(maxlen=2)
        self.pending: SupervisedResult | None = None
        self.final: SupervisedResult | None = None
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.done = threading.Event()
        self.failed = threading.Event()
        self.started = False
        self.closing = False
        self.marker_status: StoreStatus | None = None
        self.authentication_status: StoreStatus | None = None
        self.live_saved = False
        self.final_status = StoreStatus.IO_FAILED
        self.worker = threading.Thread(target=self._run, name="incident-publisher", daemon=True)

    def start(self) -> bool:
        try:
            self.worker.start()
            self.started = True
            return True
        except Exception:
            self.failed.set()
            self.done.set()
            return False

    def begin(self) -> bool:
        return self._submit_control("begin")

    def authenticate(self, session_id: str) -> bool:
        if session_id != self.session_id:
            return False
        return self._submit_control("authenticate")

    def _submit_control(self, command: str) -> bool:
        with self.lock:
            if not self.started or self.closing or len(self.controls) >= 2:
                self.failed.set()
                return False
            self.controls.append(command)
            self.wake.set()
            return True

    def submit(self, observed: SupervisedResult) -> bool:
        with self.lock:
            if not self.started or self.closing or self.pending is not None:
                self.failed.set()
                return False
            self.pending = observed
            self.wake.set()
            return True

    def _run(self) -> None:
        try:
            while True:
                item = self._next_item()
                if item is None:
                    return
                kind, observed = item
                if kind == "final":
                    self.final_status = self._finalize(observed)
                    return
                if kind == "begin":
                    self._ensure_begin()
                elif kind == "authenticate":
                    self._ensure_authenticated()
                else:
                    self._publish_live(observed)
        except Exception:
            self.failed.set()
            self.final_status = StoreStatus.IO_FAILED
        finally:
            self.done.set()

    def _next_item(self) -> tuple[str, SupervisedResult | None] | None:
        while True:
            with self.lock:
                if self.final is not None:
                    return "final", self.final
                if self.controls:
                    return self.controls.popleft(), None
                if self.pending is not None:
                    observed, self.pending = self.pending, None
                    return "live", observed
                if self.closing:
                    return None
                self.wake.clear()
            self.wake.wait(0.05)

    def _ensure_begin(self) -> StoreStatus:
        if self.marker_status is StoreStatus.MARKER_STARTED:
            return self.marker_status
        status = self._retry_lock(
            lambda: self.store.begin_session(self.session_id, self.git_sha).status
        )
        if status is not StoreStatus.LOCK_UNAVAILABLE:
            self.marker_status = status
        if status is not StoreStatus.MARKER_STARTED:
            self.failed.set()
        return status

    def _ensure_authenticated(self) -> StoreStatus:
        marker = self._ensure_begin()
        if marker is not StoreStatus.MARKER_STARTED:
            return marker
        if self.authentication_status is StoreStatus.MARKER_AUTHENTICATED:
            return self.authentication_status
        status = self._retry_lock(
            lambda: self.store.authenticate_session(self.session_id).status
        )
        if status is not StoreStatus.LOCK_UNAVAILABLE:
            self.authentication_status = status
        if status is not StoreStatus.MARKER_AUTHENTICATED:
            self.failed.set()
        return status

    @staticmethod
    def _retry_lock(callback: Callable[[], StoreStatus]) -> StoreStatus:
        deadline = time.monotonic() + 1.0
        status = callback()
        while status is StoreStatus.LOCK_UNAVAILABLE and time.monotonic() < deadline:
            time.sleep(0.025)
            status = callback()
        return status

    def _publish_live(self, observed: SupervisedResult) -> None:
        self._ensure_authenticated()
        status = self._retry_lock(
            lambda: persist_observation(self.store, observed, self.git_sha)
        )
        if status is StoreStatus.LOCK_UNAVAILABLE:
            with self.lock:
                if self.final is not None:
                    return
        if status is StoreStatus.SAVED:
            self.live_saved = True
        else:
            self.failed.set()

    def _finalize(self, observed: SupervisedResult | None) -> StoreStatus:
        if observed is None:
            return StoreStatus.IO_FAILED
        if observed.launch == "started":
            self._ensure_begin()
            if observed.handshake == "accepted":
                self._ensure_authenticated()
        retain_failure = _has_caught_failure(observed) and not self.live_saved
        if observed.needs_incident or retain_failure:
            return persist_observation(self.store, observed, self.git_sha)
        if self.authentication_status is StoreStatus.MARKER_AUTHENTICATED:
            return self.store.end_session(self.session_id, clean=True).status
        return self.authentication_status or self.marker_status or StoreStatus.IO_FAILED

    def close(self, observed: SupervisedResult) -> StoreStatus:
        with self.lock:
            self.closing = True
            if not self.started:
                return StoreStatus.IO_FAILED
            self.controls.clear()
            self.pending = None
            self.final = observed
            self.wake.set()
        self.done.wait(0.75)
        if self.worker.is_alive():
            return StoreStatus.PUBLISH_INCOMPLETE
        return self.final_status


def run_with_store(argv: list[str], *, store: IncidentStore, git_sha: str = "unknown",
                   env: dict[str, str] | None = None, cwd: Path | None = None) -> LaunchDelivery:
    session = uuid.uuid4().hex
    publisher = _OperationPublisher(store, git_sha, session)
    publisher.start()
    observed = launch_supervised(
        argv,
        env=env,
        cwd=cwd,
        session_id=session,
        on_started=publisher.begin,
        on_authenticated=publisher.authenticate,
        on_operation_failure=publisher.submit,
    )
    return LaunchDelivery(observed, publisher.close(observed))


def _persist_unstarted_bounded(
    store: IncidentStore, observed: SupervisedResult, git_sha: str
) -> StoreStatus:
    publisher = _OperationPublisher(store, git_sha, observed.session_id)
    publisher.start()
    return publisher.close(observed)


def _has_caught_failure(observed: SupervisedResult) -> bool:
    for payload in observed.history.events:
        event = decode_event(payload)
        if type(event) is WorkflowDiagnosticEvent and event.outcome is WorkflowOutcome.FAILED:
            return True
    return False


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
            _persist_unstarted_bounded(store, observed, identity.git_sha)
            _fixed_notice("Nie można uruchomić aplikacji: brak lub niezgodność składników pakietu.")
            return 1
        argv = [str(root / "metroliza_application.exe"), *sys.argv[1:]]
        git_sha = identity.git_sha
    else:
        root = Path(__file__).resolve().parents[3]
        argv = [
            sys.executable,
            str(root / "packaging" / "metroliza_package_entry.py"),
            *sys.argv[1:],
        ]
        git_sha = "unknown"
    delivery = run_with_store(argv, store=store, git_sha=git_sha)
    if delivery.storage_status not in {StoreStatus.SAVED, StoreStatus.MARKER_CLEAN_ENDED}:
        _fixed_notice("Historia diagnostyczna jest niedostępna lub raport nie został zapisany.")
    code = delivery.observation.exit_code
    return code if code is not None else 1

"""Minimal process observation without Qt, raw output capture, or recovery policy."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
import uuid
from typing import Callable

from metroliza.shared.diagnostic_ring import DiagnosticRing, RingSnapshot
from metroliza.shared.diagnostic_transport import (
    CHANNEL_ENV, MAX_COUNTER, control_bytes, parse_control, read_frame, write_frame,
)

_SPAWN_LOCK = threading.Lock()
HANDSHAKE_SECONDS = 2.0
DRAIN_SECONDS = 0.35
MAX_FRAMES_PER_SECOND = 2000


@dataclass(frozen=True)
class SupervisedResult:
    session_id: str
    launch: str
    handshake: str
    channel: str
    exit_code: int | None
    termination: str
    clean_terminal_received: bool
    source_dropped: int
    source_loss_known: bool
    history: RingSnapshot
    elapsed_ms: int

    @property
    def needs_incident(self) -> bool:
        return (self.launch != "started" or self.exit_code != 0
                or self.handshake != "accepted" or not self.clean_terminal_received
                or self.channel != "complete")


class _Receiver:
    def __init__(self, incoming: int, outgoing: int, session_id: str, token: str,
                 on_operation_failure: Callable[[SupervisedResult], bool] | None = None):
        self.incoming, self.outgoing = incoming, outgoing
        self.session_id, self.token = session_id, token
        self.ring = DiagnosticRing()
        self.lock = threading.Lock()
        self.accepted = threading.Event()
        self.stop = threading.Event()
        self.handshake = "missing"
        self.channel = "incomplete"
        self.clean_terminal = False
        self.source_dropped = 0
        self.source_loss_known = False
        self.recording_loss = False
        self.on_operation_failure = on_operation_failure
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._run, name="diagnostic-receiver", daemon=True)

    def _authenticate(self) -> None:
        value = parse_control(read_frame(self.incoming), "hello", {"session_id", "token"})
        if (value["session_id"] != self.session_id or type(value["token"]) is not str
                or not hmac.compare_digest(value["token"], self.token)
                or self.stop.is_set()):
            self.handshake = "rejected"
            raise ValueError("handshake_rejected")
        write_frame(self.outgoing, control_bytes("accepted"))
        self.handshake = "accepted"
        self.accepted.set()

    def _receive(self, payload: bytes) -> bool:
        # Parsing is capped by framing; domain bytes are revalidated by the ring.
        if payload.startswith(b'{"control":'):
            value = parse_control(payload, "ended", {"dropped"})
            count = value["dropped"]
            if type(count) is not int or not 0 <= count <= MAX_COUNTER:
                raise ValueError("invalid_control")
            self.source_dropped, self.source_loss_known = count, True
            self.clean_terminal = True
            self.channel = "loss_observed" if count or self.recording_loss else "complete"
            return False
        fields = json.loads(payload)
        if type(fields) is not dict or fields.get("invocation_id") != self.session_id:
            raise ValueError("wrong_session")
        with self.lock:
            added = self.ring.add(payload, now=time.monotonic())
            if not added:
                self.recording_loss = True
            failed_operation = (added and fields.get("event_code") == "workflow_diagnostic"
                                and fields.get("outcome") == "failed")
            if failed_operation and self.on_operation_failure is not None:
                # Callback only admits a bounded snapshot to a separate publisher.
                # No store or GUI call is permitted on this receiving thread.
                observed = SupervisedResult(
                    self.session_id, "started", "accepted", "incomplete", None,
                    "still_running", False, 0, False,
                    self.ring.snapshot(now=time.monotonic()),
                    min(86_400_000, round((time.monotonic() - self.started) * 1000)),
                )
                if not self.on_operation_failure(observed):
                    self.recording_loss = True
        return True

    def _run(self) -> None:
        try:
            self._authenticate()
            started, count = time.monotonic(), 0
            while not self.stop.is_set():
                payload = read_frame(self.incoming)
                if payload is None:
                    break
                if self.stop.is_set():
                    break
                now = time.monotonic()
                if now - started >= 1:
                    started, count = now, 0
                count += 1
                if count > MAX_FRAMES_PER_SECOND:
                    self.channel = "flooded"
                    break
                if not self._receive(payload):
                    break
        except (OSError, ValueError, TypeError, RecursionError):
            self.channel = "invalid"
        finally:
            self.accepted.set()
            for fd in (self.incoming, self.outgoing):
                try:
                    os.close(fd)
                except OSError:
                    pass


def _child_channel(incoming: int, outgoing: int) -> tuple[str, dict]:
    if os.name == "nt":
        import msvcrt

        handles = [msvcrt.get_osfhandle(fd) for fd in (incoming, outgoing)]
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {"handle_list": handles}
        return f"{handles[0]}:{handles[1]}", {"startupinfo": startup}
    return f"{incoming}:{outgoing}", {"pass_fds": (incoming, outgoing)}


def _spawn_child(argv, env, cwd, child_read, child_write, descriptors):
    with _SPAWN_LOCK:
        channel, options = _child_channel(child_read, child_write)
        child_env = dict(os.environ if env is None else env)
        child_env[CHANNEL_ENV] = channel
        for fd in (child_read, child_write):
            os.set_inheritable(fd, True)
        try:
            return subprocess.Popen(
                argv, cwd=cwd, env=child_env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, **options,
            )
        finally:
            for fd in (child_read, child_write):
                os.close(fd)
                descriptors.discard(fd)


def _await_handshake(receiver: _Receiver, on_authenticated) -> None:
    receiver.accepted.wait(HANDSHAKE_SECONDS)
    # A missing handshake is evidence only, never authority to kill the app.
    if receiver.handshake != "accepted":
        receiver.stop.set()
    elif on_authenticated is not None:
        try:
            on_authenticated(receiver.session_id)
        except Exception:
            pass


def launch_supervised(argv: list[str], *, env: dict[str, str] | None = None,
                      cwd: str | Path | None = None,
                      session_id: str | None = None,
                      on_authenticated: Callable[[str], object] | None = None,
                      on_operation_failure: Callable[[SupervisedResult], bool] | None = None) -> SupervisedResult:
    """Launch one exact child and observe it; never terminate or restart it.

    Only the two anonymous-pipe capabilities are inherited. Child stdout/stderr,
    including native output, go to the OS null sink even for no-console builds.
    """
    started = time.monotonic()
    session = session_id or uuid.uuid4().hex
    if not argv or not os.path.isabs(argv[0]):
        raise ValueError("absolute_child_required")
    from metroliza.shared.diagnostic_transport import valid_id

    if not valid_id(session):
        raise ValueError("invalid_session")
    descriptors: set[int] = set()
    receiver = None
    child = None
    try:
        parent_read, child_write = os.pipe()
        descriptors.update((parent_read, child_write))
        child_read, parent_write = os.pipe()
        descriptors.update((child_read, parent_write))
        token = secrets.token_hex(32)
        receiver = _Receiver(parent_read, parent_write, session, token, on_operation_failure)
        child = _spawn_child(argv, env, cwd, child_read, child_write, descriptors)
        receiver.thread.start()
        descriptors.difference_update((parent_read, parent_write))
        write_frame(parent_write, control_bytes("challenge", session_id=session, token=token))
        _await_handshake(receiver, on_authenticated)
        exit_code = child.wait()
        receiver.thread.join(DRAIN_SECONDS)
        receiver.stop.set()
        termination = "posix_signal" if os.name != "nt" and exit_code < 0 else "observed_exit"
    except OSError:
        if child is not None:
            # Pipe failure cannot orphan/restart/kill the real product operation.
            exit_code = child.wait()
            termination = "posix_signal" if os.name != "nt" and exit_code < 0 else "observed_exit"
            receiver.stop.set()
            if receiver.thread.ident is not None:
                receiver.thread.join(DRAIN_SECONDS)
        else:
            exit_code, termination = None, "not_started"
    finally:
        for fd in descriptors:
            try:
                os.close(fd)
            except OSError:
                pass
    if receiver is None:
        return SupervisedResult(
            session, "failed", "missing", "incomplete", None, "not_started",
            False, 0, False, DiagnosticRing().snapshot(now=time.monotonic()),
            min(86_400_000, round((time.monotonic() - started) * 1000)),
        )
    with receiver.lock:
        history = receiver.ring.snapshot(now=time.monotonic())
    return SupervisedResult(
        session, "started" if child is not None else "failed", receiver.handshake,
        receiver.channel, exit_code, termination, receiver.clean_terminal,
        receiver.source_dropped, receiver.source_loss_known, history,
        min(86_400_000, round((time.monotonic() - started) * 1000)),
    )

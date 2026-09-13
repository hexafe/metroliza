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
    def __init__(self, incoming: int, outgoing: int, session_id: str, token: str):
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
            if not self.ring.add(payload, now=time.monotonic()):
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


def launch_supervised(argv: list[str], *, env: dict[str, str] | None = None,
                      cwd: str | Path | None = None,
                      session_id: str | None = None,
                      on_authenticated: Callable[[str], object] | None = None) -> SupervisedResult:
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
    parent_read, child_write = os.pipe()
    child_read, parent_write = os.pipe()
    token = secrets.token_hex(32)
    receiver = _Receiver(parent_read, parent_write, session, token)
    child = None
    try:
        with _SPAWN_LOCK:
            channel, options = _child_channel(child_read, child_write)
            child_env = dict(os.environ if env is None else env)
            child_env[CHANNEL_ENV] = channel
            for fd in (child_read, child_write):
                os.set_inheritable(fd, True)
            try:
                child = subprocess.Popen(
                    argv, cwd=cwd, env=child_env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    close_fds=True, **options,
                )
            finally:
                for fd in (child_read, child_write):
                    os.close(fd)
        receiver.thread.start()
        write_frame(parent_write, control_bytes("challenge", session_id=session, token=token))
        receiver.accepted.wait(HANDSHAKE_SECONDS)
        # A missing handshake is evidence only, never authority to kill the app.
        if receiver.handshake != "accepted":
            receiver.stop.set()
        elif on_authenticated is not None:
            try:
                on_authenticated(session)
            except Exception:
                pass
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
            receiver.thread.join(DRAIN_SECONDS)
        else:
            exit_code, termination = None, "not_started"
            for fd in (parent_read, parent_write):
                try:
                    os.close(fd)
                except OSError:
                    pass
    with receiver.lock:
        history = receiver.ring.snapshot(now=time.monotonic())
    return SupervisedResult(
        session, "started" if child is not None else "failed", receiver.handshake,
        receiver.channel, exit_code, termination, receiver.clean_terminal,
        receiver.source_dropped, receiver.source_loss_known, history,
        min(86_400_000, round((time.monotonic() - started) * 1000)),
    )

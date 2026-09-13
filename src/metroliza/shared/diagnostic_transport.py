"""Bounded safe bytes on a private inherited pipe; never render a LogRecord."""

from __future__ import annotations

from collections import deque
import json
import os
import struct
import threading
import uuid

from metroliza.shared.diagnostic_wire import MAX_EVENT_BYTES, encode_event

CHANNEL_ENV = "METROLIZA_DIAGNOSTIC_CHANNEL"
MAX_FRAME_BYTES = MAX_EVENT_BYTES + 512
MAX_QUEUE_BYTES = 256 * 1024
MAX_QUEUE_EVENTS = 256
RESERVED_EVENTS = 16
RESERVED_BYTES = 16 * 1024
MAX_COUNTER = 2**32 - 1
_recorder: ChildRecorder | None = None
_supervised_requested = False


def control_bytes(kind: str, **fields: object) -> bytes:
    """Internal control producer; receivers validate every field independently."""
    return json.dumps({"control": kind, **fields}, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def write_frame(fd: int, payload: bytes) -> None:
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_FRAME_BYTES:
        raise ValueError("invalid_frame")
    remaining = memoryview(struct.pack("!I", len(payload)) + payload)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise OSError("channel_unavailable")
        remaining = remaining[written:]


def read_frame(fd: int) -> bytes | None:
    """One bounded frame. Caller owns thread/deadline and peer lifetime."""
    header = _read_exact(fd, 4)
    if header is None:
        return None
    size, = struct.unpack("!I", header)
    if not 0 < size <= MAX_FRAME_BYTES:
        raise ValueError("invalid_frame")
    payload = _read_exact(fd, size)
    if payload is None:
        raise ValueError("partial_frame")
    return payload


def _read_exact(fd: int, count: int) -> bytes | None:
    result = bytearray()
    while len(result) < count:
        block = os.read(fd, count - len(result))
        if not block:
            if result:
                raise ValueError("partial_frame")
            return None
        result.extend(block)
    return bytes(result)


def parse_control(payload: bytes, kind: str, fields: set[str]) -> dict:
    if type(payload) is not bytes or len(payload) > 512:
        raise ValueError("invalid_control")
    value = json.loads(payload.decode("ascii"), object_pairs_hook=_unique_fields)
    if type(value) is not dict or set(value) != fields | {"control"}:
        raise ValueError("invalid_control")
    if value["control"] != kind:
        raise ValueError("invalid_control")
    return value


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_control")
        result[key] = value
    return result


def valid_id(value: object) -> bool:
    if type(value) is not str or len(value) != 32:
        return False
    try:
        parsed = uuid.UUID(hex=value)
    except ValueError:
        return False
    return parsed.version == 4 and parsed.hex == value


def _open_channel(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2 or any(not p.isascii() or not p.isdecimal() or len(p) > 20 for p in parts):
        raise ValueError("invalid_channel")
    incoming, outgoing = (int(p) for p in parts)
    if incoming == outgoing or min(incoming, outgoing) < 3:
        raise ValueError("invalid_channel")
    if os.name == "nt":
        import msvcrt

        incoming = msvcrt.open_osfhandle(incoming, os.O_RDONLY | os.O_BINARY)
        outgoing = msvcrt.open_osfhandle(outgoing, os.O_WRONLY | os.O_BINARY)
    os.set_inheritable(incoming, False)
    os.set_inheritable(outgoing, False)
    return incoming, outgoing


class ChildRecorder:
    """A bounded nonblocking producer queue; only its daemon writes transport."""

    def __init__(self, incoming: int, outgoing: int):
        self.invocation_id: uuid.UUID | None = None
        self.connected = False
        self.qualified = False
        self.dropped = 0
        self._unquantified_loss = False
        self._incoming = incoming
        self._outgoing = outgoing
        self._queue: deque[tuple[bytes, bool]] = deque()
        self._bytes = 0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._ready = threading.Event()
        self._closing = False
        self._worker = threading.Thread(target=self._run, name="diagnostic-channel", daemon=True)

    def start(self, timeout: float = 1.0) -> bool:
        self._worker.start()
        self._ready.wait(timeout)
        return self.qualified

    def enqueue(self, event: object) -> bool:
        try:
            payload = encode_event(event)
        except Exception:
            return False
        return self.enqueue_bytes(payload)

    def enqueue_bytes(self, payload: bytes) -> bool:
        from metroliza.shared.diagnostic_events import (
            RuntimeProvenanceEvent, StartupDiagnosticEvent, WorkflowDiagnosticEvent,
        )
        from metroliza.shared.diagnostic_wire import decode_event

        try:
            event = decode_event(payload)
            if type(event) not in (RuntimeProvenanceEvent, StartupDiagnosticEvent, WorkflowDiagnosticEvent):
                return False
            # Classification uses a validated closed serializer projection, never user text.
            del event
            fields = json.loads(payload)
            terminal = fields.get("outcome") not in (None, "milestone", "started", "invocation_started")
            terminal = terminal or fields.get("event_code") == "runtime_provenance"
        except Exception:
            return False
        if not self._lock.acquire(blocking=False):
            # Do not pretend a raced read/modify/write is an exact loss count.
            self._unquantified_loss = True
            return False
        try:
            count_cap = MAX_QUEUE_EVENTS if terminal else MAX_QUEUE_EVENTS - RESERVED_EVENTS
            byte_cap = MAX_QUEUE_BYTES if terminal else MAX_QUEUE_BYTES - RESERVED_BYTES
            if (not self.connected or self._closing or len(self._queue) >= count_cap
                    or self._bytes + len(payload) > byte_cap):
                self.dropped = min(MAX_COUNTER, self.dropped + 1)
                return False
            self._queue.append((payload, terminal))
            self._bytes += len(payload)
            self._wake.set()
            return True
        finally:
            self._lock.release()

    def close(self, timeout: float = 0.25) -> None:
        self._closing = True
        self._wake.set()
        self._worker.join(timeout)

    def _handshake(self) -> None:
        challenge = read_frame(self._incoming)
        value = parse_control(challenge, "challenge", {"session_id", "token"})
        token = value["token"]
        if (not valid_id(value["session_id"]) or type(token) is not str
                or len(token) != 64 or any(c not in "0123456789abcdef" for c in token)):
            raise ValueError("invalid_handshake")
        write_frame(self._outgoing, control_bytes("hello", **{k: value[k] for k in ("session_id", "token")}))
        acknowledgement = read_frame(self._incoming)
        if acknowledgement != control_bytes("accepted"):
            raise ValueError("handshake_unavailable")
        self.invocation_id = uuid.UUID(hex=value["session_id"])
        self.connected = self.qualified = True
        self._ready.set()

    def _run(self) -> None:
        try:
            self._handshake()
            while True:
                with self._lock:
                    entry = self._queue.popleft() if self._queue else None
                    if entry is not None:
                        self._bytes -= len(entry[0])
                if entry is not None:
                    write_frame(self._outgoing, entry[0])
                elif self._closing:
                    if not self._unquantified_loss:
                        write_frame(self._outgoing, control_bytes("ended", dropped=self.dropped))
                    break
                else:
                    self._wake.wait(0.1)
                    self._wake.clear()
        except (OSError, ValueError, TypeError):
            self.connected = False
        finally:
            self.connected = False
            self._ready.set()
            for fd in (self._incoming, self._outgoing):
                try:
                    os.close(fd)
                except OSError:
                    pass


def attach_child_recorder() -> ChildRecorder | None:
    """Consume one-use inherited handles before app/Qt imports, bounded to one second."""
    global _recorder, _supervised_requested
    channel = os.environ.pop(CHANNEL_ENV, None)
    if channel is None:
        return None
    _supervised_requested = True
    try:
        recorder = ChildRecorder(*_open_channel(channel))
        _recorder = recorder
        recorder.start()
        return recorder
    except (OSError, ValueError):
        return None


def current_recorder() -> ChildRecorder | None:
    return _recorder


def supervised_mode_requested() -> bool:
    return _supervised_requested


def supervised_invocation_id() -> uuid.UUID | None:
    recorder = current_recorder()
    return recorder.invocation_id if recorder is not None else None

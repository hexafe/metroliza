import os
import runpy
import secrets
import struct
import subprocess
import sys
import types
import threading
import uuid
from pathlib import Path

import pytest

from metroliza.shared import diagnostic_transport
from metroliza.shared.diagnostic_transport import (
    MAX_FRAME_BYTES,
    control_bytes,
    parse_control,
    read_frame,
    write_frame,
)


@pytest.mark.parametrize("payload", [b"{}", b"x" * MAX_FRAME_BYTES])
def test_pipe_round_trip(payload):
    import threading

    incoming, outgoing = os.pipe()
    worker = threading.Thread(target=write_frame, args=(outgoing, payload))
    try:
        worker.start()
        assert read_frame(incoming) == payload
        worker.join(1)
        assert not worker.is_alive()
    finally:
        os.close(incoming)
        os.close(outgoing)


@pytest.mark.parametrize("data", [b"\x00", struct.pack("!I", MAX_FRAME_BYTES + 1),
                                  struct.pack("!I", 0), struct.pack("!I", 4) + b"a"])
def test_partial_and_oversized_frames_fail_closed(data):
    incoming, outgoing = os.pipe()
    os.write(outgoing, data)
    os.close(outgoing)
    try:
        with pytest.raises(ValueError):
            read_frame(incoming)
    finally:
        os.close(incoming)


@pytest.mark.parametrize("data", [b'{"control":"ended","dropped":0,"path":"SECRET"}',
                                  b'{"control":"ended","dropped":0,"dropped":1}',
                                  b"x" * 513])
def test_control_rejects_extra_duplicate_and_oversized_payload(data):
    with pytest.raises(ValueError):
        parse_control(data, "ended", {"dropped"})


def test_control_round_trip():
    assert parse_control(control_bytes("ended", dropped=3), "ended", {"dropped"}) == {
        "control": "ended", "dropped": 3,
    }


def test_late_parent_accept_cannot_qualify_timed_out_child_recorder(monkeypatch):
    child_in, parent_write = os.pipe()
    parent_read, child_out = os.pipe()
    recorder = diagnostic_transport.ChildRecorder(child_in, child_out)
    session_id = uuid.uuid4()
    token = secrets.token_hex(32)
    hello_seen = threading.Event()
    release_accept = threading.Event()
    parent_errors = []

    def parent():
        try:
            hello = read_frame(parent_read)
            hello_fields = parse_control(hello, "hello", {"session_id", "token"})
            assert hello_fields == {
                "control": "hello",
                "session_id": session_id.hex,
                "token": token,
            }
            hello_seen.set()
            assert release_accept.wait(2)
            write_frame(parent_write, control_bytes("accepted"))
        except Exception as error:
            parent_errors.append(error)

    worker = threading.Thread(target=parent)
    diagnostic_transport.write_frame(
        parent_write,
        control_bytes("challenge", session_id=session_id.hex, token=token),
    )
    monkeypatch.setattr(diagnostic_transport, "_recorder", recorder)
    try:
        worker.start()
        assert recorder.start() is False
        assert hello_seen.wait(1)
        assert diagnostic_transport.supervised_invocation_id() is None
        release_accept.set()
        worker.join(1)
        recorder._worker.join(1)
        assert not worker.is_alive()
        assert not recorder._worker.is_alive()
        assert parent_errors == []
        assert recorder.invocation_id is None
        assert diagnostic_transport.supervised_invocation_id() is None
        assert not recorder.qualified
        assert not recorder.connected
        assert read_frame(parent_read) is None
        with pytest.raises(OSError):
            os.fstat(child_in)
        with pytest.raises(OSError):
            os.fstat(child_out)
    finally:
        release_accept.set()
        recorder.close()
        os.close(parent_write)
        os.close(parent_read)


def test_on_time_parent_accept_keeps_exact_supervised_session_identity():
    child_in, parent_write = os.pipe()
    parent_read, child_out = os.pipe()
    recorder = diagnostic_transport.ChildRecorder(child_in, child_out)
    session_id = uuid.uuid4()
    token = secrets.token_hex(32)

    def parent():
        hello = read_frame(parent_read)
        assert parse_control(hello, "hello", {"session_id", "token"}) == {
            "control": "hello",
            "session_id": session_id.hex,
            "token": token,
        }
        write_frame(parent_write, control_bytes("accepted"))

    worker = threading.Thread(target=parent)
    write_frame(
        parent_write,
        control_bytes("challenge", session_id=session_id.hex, token=token),
    )
    try:
        worker.start()
        assert recorder.start(timeout=1) is True
        worker.join(1)
        assert not worker.is_alive()
        assert recorder.invocation_id == session_id
        assert recorder.qualified
    finally:
        recorder.close()
        os.close(parent_write)
        os.close(parent_read)


class SyntheticDiagnosticFailure(Exception):
    pass


def _duplicate_windows_handle(descriptor):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    current_process = kernel.GetCurrentProcess
    current_process.argtypes = []
    current_process.restype = wintypes.HANDLE
    duplicate = kernel.DuplicateHandle
    duplicate.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    duplicate.restype = wintypes.BOOL
    process = current_process()
    copied = wintypes.HANDLE()
    if not duplicate(
        process,
        wintypes.HANDLE(msvcrt.get_osfhandle(descriptor)),
        process,
        ctypes.byref(copied),
        0,
        True,
        0x00000002,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return copied.value


def _owned_channel():
    incoming, parent_write = os.pipe()
    parent_read, outgoing = os.pipe()
    if os.name != "nt":
        return f"{incoming}:{outgoing}", (incoming, outgoing), (parent_write, parent_read)
    handles = []
    try:
        handles.append(_duplicate_windows_handle(incoming))
        handles.append(_duplicate_windows_handle(outgoing))
    except BaseException:
        diagnostic_transport._close_windows_handles(handles)
        raise
    finally:
        os.close(incoming)
        os.close(outgoing)
    return f"{handles[0]}:{handles[1]}", tuple(handles), (parent_write, parent_read)


def _windows_handle_open(handle):
    import ctypes
    from ctypes import wintypes

    get_information = ctypes.WinDLL(
        "kernel32", use_last_error=True
    ).GetHandleInformation
    get_information.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    get_information.restype = wintypes.BOOL
    flags = wintypes.DWORD()
    return bool(get_information(wintypes.HANDLE(handle), ctypes.byref(flags)))


def _assert_owned_channel_closed(owned):
    for descriptor in owned:
        if os.name == "nt":
            assert not _windows_handle_open(descriptor)
        else:
            with pytest.raises(OSError):
                os.fstat(descriptor)


def _close_test_channel(owned, peers):
    for descriptor in peers:
        os.close(descriptor)
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    for handle in owned:
        if _windows_handle_open(handle):
            close_handle(wintypes.HANDLE(handle))


@pytest.mark.parametrize("failure_type", [RuntimeError, SyntheticDiagnosticFailure])
def test_attach_thread_start_failure_closes_channels_and_preserves_attempted_mode(
    monkeypatch, failure_type
):
    channel, owned, peers = _owned_channel()
    monkeypatch.setattr(diagnostic_transport, "_recorder", object())
    monkeypatch.setattr(diagnostic_transport, "_supervised_requested", False)
    monkeypatch.setenv(diagnostic_transport.CHANNEL_ENV, channel)

    def fail_start(_thread):
        raise failure_type("synthetic_thread_start_failure")

    monkeypatch.setattr(diagnostic_transport.threading.Thread, "start", fail_start)
    try:
        assert diagnostic_transport.attach_child_recorder() is None
        assert diagnostic_transport.current_recorder() is None
        assert diagnostic_transport.supervised_mode_requested()
        assert diagnostic_transport.CHANNEL_ENV not in os.environ
        _assert_owned_channel_closed(owned)
    finally:
        _close_test_channel(owned, peers)


def test_windows_partial_channel_conversion_closes_crt_fd_and_raw_handle(
    monkeypatch,
):
    owned, peer = os.pipe()
    calls = 0
    closed_handles: list[int] = []

    def partial_open(_handle, _flags):
        nonlocal calls
        calls += 1
        if calls == 1:
            return owned
        raise OSError("synthetic_second_conversion_failure")

    fake_msvcrt = types.SimpleNamespace(open_osfhandle=partial_open)
    def close_raw(handle):
        closed_handles.append(handle.value)
        return 1

    class CloseHandle:
        argtypes = None
        restype = None

        def __call__(self, handle):
            return close_raw(handle)

    fake_kernel = types.SimpleNamespace(CloseHandle=CloseHandle())
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(diagnostic_transport.os, "name", "nt")
    monkeypatch.setattr(diagnostic_transport.os, "O_BINARY", 0, raising=False)
    monkeypatch.setattr(
        diagnostic_transport.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: fake_kernel,
        raising=False,
    )
    try:
        with pytest.raises(OSError):
            diagnostic_transport._open_channel("100:101")
        with pytest.raises(OSError):
            os.fstat(owned)
        assert calls == 2
        assert closed_handles == [101]
    finally:
        os.close(peer)


def test_channel_inheritability_failure_closes_both_owned_descriptors(monkeypatch):
    channel, owned, peers = _owned_channel()
    calls = 0

    def fail_second(_descriptor, _inheritable):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SyntheticDiagnosticFailure("synthetic_inheritability_failure")

    monkeypatch.setattr(diagnostic_transport.os, "set_inheritable", fail_second)
    try:
        with pytest.raises(SyntheticDiagnosticFailure):
            diagnostic_transport._open_channel(channel)
        _assert_owned_channel_closed(owned)
    finally:
        _close_test_channel(owned, peers)


def _run_package_entry(monkeypatch, *, setup_fails: bool, close_fails: bool):
    calls: list[str] = []

    class Recorder:
        def close(self):
            calls.append("close")
            if close_fails:
                raise RuntimeError("synthetic_diagnostic_close_failure")

    recorder = Recorder()
    transport = types.ModuleType("metroliza.shared.diagnostic_transport")
    transport.attach_child_recorder = lambda: recorder
    transport.supervised_mode_requested = lambda: True
    logging_utils = types.ModuleType("metroliza.shared.logging_utils")

    def ensure_logging():
        calls.append("logging")
        if setup_fails:
            raise RuntimeError("synthetic_diagnostic_setup_failure")

    logging_utils.ensure_application_logging = ensure_logging
    bootstrap = types.ModuleType("metroliza.app.bootstrap")

    def run_application():
        calls.append("application")
        return 7

    bootstrap.run_application = run_application
    monkeypatch.setitem(sys.modules, transport.__name__, transport)
    monkeypatch.setitem(sys.modules, logging_utils.__name__, logging_utils)
    monkeypatch.setitem(sys.modules, bootstrap.__name__, bootstrap)
    monkeypatch.setattr(sys, "path", list(sys.path))
    entry = Path(__file__).resolve().parents[1] / "packaging" / "metroliza_package_entry.py"
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(str(entry), run_name="__main__")
    return exited.value.code, calls


def test_packaged_diagnostic_logging_setup_failure_does_not_prevent_application(
    monkeypatch,
):
    code, calls = _run_package_entry(
        monkeypatch, setup_fails=True, close_fails=False
    )

    assert code == 7
    assert calls == ["logging", "application", "close"]


def test_packaged_diagnostic_close_failure_does_not_replace_application_result(
    monkeypatch,
):
    code, calls = _run_package_entry(
        monkeypatch, setup_fails=False, close_fails=True
    )

    assert code == 7
    assert calls == ["logging", "application", "close"]


@pytest.fixture
def recorder_receiver_pair():
    from metroliza.app.diagnostic_supervisor import _Receiver

    child_in, parent_out = os.pipe()
    parent_in, child_out = os.pipe()
    session, token = uuid.uuid4().hex, secrets.token_hex(32)
    receiver = _Receiver(parent_in, parent_out, session, token)
    recorder = diagnostic_transport.ChildRecorder(child_in, child_out)
    receiver.thread.start()
    write_frame(parent_out, control_bytes("challenge", session_id=session, token=token))
    try:
        assert recorder.start()
        yield recorder, receiver
    finally:
        recorder.close(timeout=2)
        receiver.thread.join(2)
        assert not recorder._worker.is_alive()
        assert not receiver.thread.is_alive()


def _recorder_startup_payload(recorder):
    from metroliza.shared.diagnostic_events import (
        StartupCallsite, StartupDiagnosticEvent, StartupMode, StartupOutcome,
    )
    from metroliza.shared.diagnostic_wire import encode_event

    return encode_event(StartupDiagnosticEvent(
        recorder.invocation_id, uuid.uuid4(), 1, StartupMode.UNKNOWN,
        StartupCallsite.BOOTSTRAP, StartupOutcome.INVOCATION_STARTED,
    ))


def test_contended_producer_counts_exact_loss_and_sends_clean_terminal(recorder_receiver_pair):
    recorder, receiver = recorder_receiver_pair
    locked, release = threading.Event(), threading.Event()

    def hold_queue_lock():
        with recorder._lock:
            locked.set()
            release.wait(2)

    holder = threading.Thread(target=hold_queue_lock)
    holder.start()
    try:
        assert locked.wait(1)
        assert not recorder.enqueue_bytes(_recorder_startup_payload(recorder))
        assert recorder.dropped == 1
    finally:
        release.set()
        holder.join(2)
    assert not holder.is_alive()
    recorder.close(timeout=2)
    receiver.thread.join(2)
    assert not recorder._worker.is_alive()
    assert not receiver.thread.is_alive()
    assert receiver.handshake == "accepted"
    assert receiver.channel == "loss_observed"
    assert receiver.clean_terminal
    assert receiver.source_loss_known
    assert receiver.source_dropped == 1


@pytest.mark.parametrize("initial", [0, diagnostic_transport.MAX_COUNTER - 2])
def test_concurrent_contended_admissions_have_exact_saturating_count(recorder_receiver_pair, initial):
    recorder, receiver = recorder_receiver_pair
    recorder.dropped = initial
    payload = _recorder_startup_payload(recorder)
    barrier = threading.Barrier(9)

    def produce():
        barrier.wait()
        for _ in range(1000):
            assert not recorder.enqueue_bytes(payload)

    workers = [threading.Thread(target=produce) for _ in range(8)]
    with recorder._lock:
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(5)
            assert not worker.is_alive()
    recorder.close(timeout=2)
    receiver.thread.join(2)
    assert receiver.source_dropped == min(diagnostic_transport.MAX_COUNTER, initial + 8000)
    assert receiver.clean_terminal
    assert receiver.source_loss_known


def test_recorder_close_waits_for_progressing_queue_until_terminal(recorder_receiver_pair, monkeypatch):
    import time

    recorder, receiver = recorder_receiver_pair
    entered, release = threading.Event(), threading.Event()
    original = diagnostic_transport.write_frame

    def slow_write(descriptor, payload):
        if b'"event_code":' in payload:
            entered.set()
            assert release.wait(2)
            time.sleep(0.02)  # Test-only pipe latency: 32 frames exceed the old total budget.
        original(descriptor, payload)

    monkeypatch.setattr(diagnostic_transport, "write_frame", slow_write)
    try:
        assert recorder.enqueue_bytes(_recorder_startup_payload(recorder))
        assert entered.wait(1)
        for _ in range(31):
            assert recorder.enqueue_bytes(_recorder_startup_payload(recorder))
        release.set()
        recorder.close()
        assert not recorder._worker.is_alive()
        receiver.thread.join(2)
        assert not receiver.thread.is_alive()
        assert receiver.clean_terminal
        assert receiver.source_loss_known
    finally:
        release.set()


def test_slow_small_pipe_progress_delivers_ended(recorder_receiver_pair, monkeypatch):
    import time

    recorder, receiver = recorder_receiver_pair
    if sys.platform == "linux":
        import fcntl

        # Match a small Windows anonymous buffer, rather than assume Linux 64 KiB.
        assert fcntl.fcntl(recorder._outgoing, fcntl.F_SETPIPE_SZ, 4096) == 4096
    receive = receiver._receive

    def slow_receive(payload):
        time.sleep(0.02)  # The same B2 slow-reader control, within the hard byte cap.
        return receive(payload)

    monkeypatch.setattr(receiver, "_receive", slow_receive)
    payload = _recorder_startup_payload(recorder)
    with recorder._lock:
        recorder._queue.extend([(payload, True)] * 64)
        recorder._bytes = len(payload) * 64
    started = time.monotonic()
    recorder.close()
    assert not recorder._worker.is_alive()
    receiver.thread.join(2)
    assert not receiver.thread.is_alive()
    assert receiver.clean_terminal
    assert receiver.source_loss_known
    assert recorder._completed_frames == 65
    assert time.monotonic() - started < 3  # 65 * 20 ms + bounded scheduling allowance.


def test_recorder_close_budget_does_not_prove_terminal_sent(recorder_receiver_pair, monkeypatch):
    recorder, receiver = recorder_receiver_pair
    entered, release = threading.Event(), threading.Event()
    original = diagnostic_transport.write_frame

    def held_write(descriptor, payload):
        if b'"event_code":' in payload:
            entered.set()
            if not release.wait(2):
                raise OSError("synthetic_test_barrier_timeout")
        original(descriptor, payload)

    monkeypatch.setattr(diagnostic_transport, "write_frame", held_write)
    try:
        assert recorder.enqueue_bytes(_recorder_startup_payload(recorder))
        assert entered.wait(1)
        recorder.close(timeout=0)
        assert recorder._worker.is_alive()
        assert receiver.channel == "incomplete"
        assert not receiver.clean_terminal
    finally:
        release.set()
        recorder._worker.join(2)
        receiver.thread.join(2)
    assert not recorder._worker.is_alive()
    assert not receiver.thread.is_alive()
    assert receiver.channel == "complete"
    assert receiver.clean_terminal
    assert receiver.source_loss_known


def test_close_stops_after_one_window_without_completed_frame():
    import time

    recorder = diagnostic_transport.ChildRecorder(-1, -1)
    budgets = []
    recorder._worker = types.SimpleNamespace(ident=1, join=budgets.append, is_alive=lambda: True)
    recorder._queue.extend([(b"{}", True)] * diagnostic_transport.MAX_QUEUE_EVENTS)
    started = time.monotonic()
    recorder.close()
    assert len(budgets) == 1
    assert 0.25 <= budgets[0] <= 1
    assert time.monotonic() - started < 1
    assert recorder._closing


def test_close_hard_cap_even_with_continuing_frame_progress(monkeypatch):
    clock = [0.0]
    budgets = []
    recorder = diagnostic_transport.ChildRecorder(-1, -1)
    recorder._completed_frames = 0

    def join(window):
        budgets.append(window)
        clock[0] += window
        recorder._completed_frames += 1

    monkeypatch.setattr(diagnostic_transport, "time", types.SimpleNamespace(monotonic=lambda: clock[0]), raising=False)
    recorder._worker = types.SimpleNamespace(ident=1, join=join, is_alive=lambda: True)
    recorder.close()
    wire_bound = (diagnostic_transport.MAX_QUEUE_BYTES + 4 * diagnostic_transport.MAX_QUEUE_EVENTS
                  + diagnostic_transport.MAX_FRAME_BYTES + 4 + 512 + 4)
    assert len(budgets) > 1
    assert sum(budgets) == pytest.approx(wire_bound / (64 * 1024))
    assert sum(budgets) < 5


def test_stalled_full_pipe_close_returns_within_one_progress_window(recorder_receiver_pair, monkeypatch):
    import time

    recorder, receiver = recorder_receiver_pair
    entered, release = threading.Event(), threading.Event()
    original = diagnostic_transport.write_frame

    def stalled_write(descriptor, payload):
        if b'"event_code":' in payload:
            entered.set()
            if not release.wait(5):
                raise OSError("synthetic_test_barrier_timeout")
        original(descriptor, payload)

    monkeypatch.setattr(diagnostic_transport, "write_frame", stalled_write)
    try:
        assert recorder.enqueue_bytes(_recorder_startup_payload(recorder))
        assert entered.wait(1)
        with recorder._lock:
            payload = _recorder_startup_payload(recorder)
            recorder._queue.extend([(payload, True)] * diagnostic_transport.MAX_QUEUE_EVENTS)
            recorder._bytes = len(payload) * diagnostic_transport.MAX_QUEUE_EVENTS
        started = time.monotonic()
        recorder.close()
        elapsed = time.monotonic() - started
        assert elapsed < 1.5  # One 1-s progress window plus 0.5-s scheduler tolerance.
        assert recorder._worker.is_alive()
        assert not receiver.clean_terminal
    finally:
        release.set()
        recorder._worker.join(3)
        receiver.thread.join(3)
    assert not recorder._worker.is_alive()
    assert not receiver.thread.is_alive()


def test_drop_allows_same_thread_reentry_without_deadlock():
    # Interrupt a Python line inside the old locked increment; the new single C
    # next() has no interruptible Python interior. The child confines old deadlock.
    program = '''
import sys
sys.path.insert(0, sys.argv[1])
from metroliza.shared.diagnostic_transport import ChildRecorder
recorder = ChildRecorder(-1, -1)
lines = 0
reentered = False
def trace(frame, event, arg):
    global lines, reentered
    if frame.f_code is ChildRecorder._drop.__code__ and not reentered:
        if event == "line":
            lines += 1
        if lines >= 2 or event == "return":
            reentered = True
            recorder._drop()
    return trace
sys.settrace(trace)
recorder._drop()
sys.settrace(None)
assert reentered
assert recorder.dropped == 2
'''
    source = str(Path(diagnostic_transport.__file__).resolve().parents[2])
    completed = subprocess.run([sys.executable, "-c", program, source], timeout=3, check=False)
    assert completed.returncode == 0


def test_close_cannot_end_after_empty_pop_before_last_admission(recorder_receiver_pair, monkeypatch):
    import time

    recorder, receiver = recorder_receiver_pair
    emptied, release = threading.Event(), threading.Event()
    original_lock = recorder._lock

    class EmptyPopBarrier:
        def acquire(self, *args, **kwargs):
            return original_lock.acquire(*args, **kwargs)

        def release(self):
            original_lock.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *args):
            self.release()
            if threading.current_thread() is recorder._worker and not emptied.is_set():
                emptied.set()
                assert release.wait(2)

    monkeypatch.setattr(recorder, "_lock", EmptyPopBarrier())
    recorder._wake.set()
    try:
        assert emptied.wait(1)
        assert recorder.enqueue_bytes(_recorder_startup_payload(recorder))
        recorder.close(timeout=0)
    finally:
        release.set()
    recorder._worker.join(2)
    receiver.thread.join(2)
    assert not recorder._worker.is_alive()
    assert not receiver.thread.is_alive()
    assert receiver.clean_terminal
    assert len(receiver.ring.snapshot(now=time.monotonic()).events) == 1

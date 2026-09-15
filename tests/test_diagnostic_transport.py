import os
import runpy
import struct
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
    hello_seen = threading.Event()
    release_accept = threading.Event()
    parent_errors = []

    def parent():
        try:
            hello = read_frame(parent_read)
            assert parse_control(hello, "hello", {"session_id", "token"})[
                "session_id"
            ] == session_id.hex
            hello_seen.set()
            assert release_accept.wait(2)
            write_frame(parent_write, control_bytes("accepted"))
        except Exception as error:
            parent_errors.append(error)

    worker = threading.Thread(target=parent)
    diagnostic_transport.write_frame(
        parent_write,
        control_bytes("challenge", session_id=session_id.hex, token="a" * 64),
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

    def parent():
        hello = read_frame(parent_read)
        assert parse_control(hello, "hello", {"session_id", "token"})[
            "session_id"
        ] == session_id.hex
        write_frame(parent_write, control_bytes("accepted"))

    worker = threading.Thread(target=parent)
    write_frame(
        parent_write,
        control_bytes("challenge", session_id=session_id.hex, token="a" * 64),
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

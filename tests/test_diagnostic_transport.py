import os
import runpy
import struct
import sys
import types
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


class SyntheticDiagnosticFailure(Exception):
    pass


@pytest.mark.parametrize("failure_type", [RuntimeError, SyntheticDiagnosticFailure])
def test_attach_thread_start_failure_closes_channels_and_preserves_attempted_mode(
    monkeypatch, failure_type
):
    incoming, parent_write = os.pipe()
    parent_read, outgoing = os.pipe()
    monkeypatch.setattr(diagnostic_transport, "_recorder", object())
    monkeypatch.setattr(diagnostic_transport, "_supervised_requested", False)
    monkeypatch.setenv(diagnostic_transport.CHANNEL_ENV, f"{incoming}:{outgoing}")

    def fail_start(_thread):
        raise failure_type("synthetic_thread_start_failure")

    monkeypatch.setattr(diagnostic_transport.threading.Thread, "start", fail_start)
    try:
        assert diagnostic_transport.attach_child_recorder() is None
        assert diagnostic_transport.current_recorder() is None
        assert diagnostic_transport.supervised_mode_requested()
        assert diagnostic_transport.CHANNEL_ENV not in os.environ
        for descriptor in (incoming, outgoing):
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        os.close(parent_write)
        os.close(parent_read)


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
    incoming, incoming_peer = os.pipe()
    outgoing_peer, outgoing = os.pipe()
    calls = 0

    def fail_second(_descriptor, _inheritable):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SyntheticDiagnosticFailure("synthetic_inheritability_failure")

    monkeypatch.setattr(diagnostic_transport.os, "set_inheritable", fail_second)
    try:
        with pytest.raises(SyntheticDiagnosticFailure):
            diagnostic_transport._open_channel(f"{incoming}:{outgoing}")
        for descriptor in (incoming, outgoing):
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        os.close(incoming_peer)
        os.close(outgoing_peer)


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

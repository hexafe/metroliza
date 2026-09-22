from __future__ import annotations

import ctypes
import dis
import hashlib
import json
import os
import sys
import time
import uuid
import zipfile
from pathlib import Path

import pytest

from metroliza.app import diagnostic_qualification as qualification_entry
from metroliza.shared.diagnostic_incident import (
    ChannelState,
    HandshakeState,
    IncidentObservation,
    LaunchState,
    TerminationState,
    build_incident,
)
from metroliza.shared.diagnostic_ring import LOSS_ACCOUNTING_BYTES, RingLoss, RingSnapshot
from scripts import qualify_windows_diagnostics as qualification

TEST_NATIVE_ANCHOR = r"\Device\HarddiskVolume7\fixed\application.exe"


class _TokenWinTypes:
    HANDLE = ctypes.c_void_p
    BOOL = ctypes.c_long
    BYTE = ctypes.c_ubyte
    DWORD = ctypes.c_uint32


class _WindowUser:
    def __init__(self, windows):
        self.windows = windows
        self.posted = []
        self.failure = None
        self.post_succeeds = True

    def EnumWindows(self, callback, parameter):
        for window in tuple(self.windows):
            if not callback(window, parameter):
                return False
        return True

    def IsWindow(self, window):
        if self.failure is not None:
            raise self.failure
        return window in self.windows

    def IsWindowVisible(self, window):
        return self.windows[window]["visible"]

    def IsWindowEnabled(self, window):
        return self.windows[window]["enabled"]

    def GetWindowThreadProcessId(self, window, process_id):
        ctypes.cast(process_id, ctypes.POINTER(ctypes.c_uint32)).contents.value = (
            self.windows[window]["process_id"]
        )
        return 1

    def GetWindow(self, window, _kind):
        return self.windows[window]["owner"]

    def GetWindowLongPtrW(self, window, index):
        field = "style" if index == qualification.GWL_STYLE else "extended_style"
        return self.windows[window][field]

    def GetWindowTextW(self, window, title, capacity):
        value = self.windows[window]["title"][: capacity - 1]
        title.value = value
        return len(value)

    def PostMessageW(self, window, message, word, long_value):
        self.posted.append((window, message, word, long_value))
        return self.post_succeeds


def _window_api(windows):
    api = object.__new__(qualification._WindowsApi)
    api.wintypes = _TokenWinTypes
    api.WNDENUMPROC = lambda callback: callback
    api.user = _WindowUser(windows)
    return api


def _normal_window(process_id, title):
    return {
        "process_id": process_id,
        "title": title,
        "visible": True,
        "enabled": True,
        "owner": 0,
        "style": qualification.NORMAL_WINDOW_REQUIRED_STYLE,
        "extended_style": 0,
    }


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]


class _SidIdentifierAuthority(ctypes.Structure):
    _fields_ = [("Value", ctypes.c_ubyte * 6)]


class _TokenMandatoryLabel(ctypes.Structure):
    _fields_ = [("Label", _SidAndAttributes)]


class _TokenKernel:
    def __init__(self) -> None:
        self.closed: list[int] = []

    def CloseHandle(self, handle) -> int:
        self.closed.append(handle.value)
        return 1


class _TokenAdvapi:
    def __init__(self, *, membership_ok: bool = True, is_admin: bool = False) -> None:
        self.membership_ok = membership_ok
        self.is_admin = is_admin
        self.checked: list[int] = []

    def DuplicateToken(self, token, level, duplicate) -> int:
        assert token.value == 101
        assert level == 1
        ctypes.cast(duplicate, ctypes.POINTER(ctypes.c_void_p))[0] = 202
        return 1

    def CheckTokenMembership(self, token, _sid, is_member) -> int:
        self.checked.append(token.value)
        if not self.membership_ok:
            return 0
        ctypes.cast(is_member, ctypes.POINTER(ctypes.c_long))[0] = self.is_admin
        return 1


def _token_api(*, membership_ok: bool = True, is_admin: bool = False):
    api = object.__new__(qualification._WindowsApi)
    api.wintypes = _TokenWinTypes
    api.kernel = _TokenKernel()
    api.advapi = _TokenAdvapi(membership_ok=membership_ok, is_admin=is_admin)
    api.SID_AND_ATTRIBUTES = _SidAndAttributes
    api.SID_IDENTIFIER_AUTHORITY = _SidIdentifierAuthority
    api.TOKEN_MANDATORY_LABEL = _TokenMandatoryLabel
    return api


@pytest.mark.parametrize("is_admin", [False, True])
def test_admin_membership_uses_impersonation_duplicate_and_closes_it(
    is_admin,
) -> None:
    api = _token_api(is_admin=is_admin)

    assert api._has_effective_admin_membership(
        ctypes.c_void_p(101), object()
    ) is is_admin
    assert api.advapi.checked == [202]
    assert api.kernel.closed == [202]


def test_admin_membership_closes_duplicate_when_check_fails() -> None:
    api = _token_api(membership_ok=False)

    with pytest.raises(qualification.QualificationFailure) as error:
        api._has_effective_admin_membership(ctypes.c_void_p(101), object())
    assert error.value.failure_id == "restricted_launch_unavailable"
    assert api.advapi.checked == [202]
    assert api.kernel.closed == [202]


class _IntegrityAdvapi:
    def __init__(
        self, *, set_ok: bool = True, rid: int = 0x2000, free_result=None
    ) -> None:
        self.set_ok = set_ok
        self.free_result = free_result
        self.rid = ctypes.c_uint32(rid)
        self.authority = _SidIdentifierAuthority((0, 0, 0, 0, 0, 16))
        self.count = ctypes.c_ubyte(1)
        self.freed: list[int] = []
        self.set_calls: list[tuple[int, int, int]] = []

    def AllocateAndInitializeSid(self, *_arguments) -> int:
        ctypes.cast(_arguments[-1], ctypes.POINTER(ctypes.c_void_p))[0] = 303
        return 1

    def FreeSid(self, sid):
        self.freed.append(sid.value)
        return self.free_result

    def GetLengthSid(self, sid) -> int:
        assert sid.value == 303
        return 12

    def SetTokenInformation(self, token, info_class, label, length) -> int:
        value = ctypes.cast(label, ctypes.POINTER(_TokenMandatoryLabel)).contents
        assert value.Label.Sid == 303
        assert value.Label.Attributes == 0x20
        self.set_calls.append((token.value, info_class, length))
        return self.set_ok

    def GetTokenInformation(self, token, info_class, output, length, returned) -> int:
        assert token.value == 101
        assert info_class == qualification.TOKEN_INTEGRITY_LEVEL
        required = ctypes.cast(returned, ctypes.POINTER(ctypes.c_uint32))
        required[0] = ctypes.sizeof(_TokenMandatoryLabel)
        if output is None:
            return 0
        assert length == required[0]
        label = _TokenMandatoryLabel(_SidAndAttributes(ctypes.c_void_p(303), 0x20))
        ctypes.memmove(output, ctypes.byref(label), ctypes.sizeof(label))
        return 1

    def IsValidSid(self, sid) -> int:
        return int(sid == 303)

    def GetSidIdentifierAuthority(self, sid):
        assert sid == 303
        return ctypes.pointer(self.authority)

    def GetSidSubAuthorityCount(self, sid):
        assert sid == 303
        return ctypes.pointer(self.count)

    def GetSidSubAuthority(self, sid, index):
        assert sid == 303
        assert index == 0
        return ctypes.pointer(self.rid)


@pytest.mark.parametrize("set_ok", [True, False])
def test_medium_integrity_sid_is_freed_on_every_set_path(set_ok) -> None:
    api = _token_api()
    api.advapi = _IntegrityAdvapi(set_ok=set_ok)

    if set_ok:
        api._set_medium_integrity(ctypes.c_void_p(101))
    else:
        with pytest.raises(qualification.QualificationFailure):
            api._set_medium_integrity(ctypes.c_void_p(101))
    assert api.advapi.set_calls == [
        (
            101,
            qualification.TOKEN_INTEGRITY_LEVEL,
            ctypes.sizeof(_TokenMandatoryLabel) + 12,
        )
    ]
    assert api.advapi.freed == [303]


def test_medium_integrity_sid_cleanup_failure_is_not_reported_complete() -> None:
    api = _token_api()
    api.advapi = _IntegrityAdvapi(free_result=ctypes.c_void_p(303))

    with pytest.raises(qualification.QualificationFailure) as caught:
        api._set_medium_integrity(ctypes.c_void_p(101))

    assert api.advapi.freed == [303]
    assert caught.value.qualification_cleanup == "failed"


@pytest.mark.parametrize("rid", [0x1000, 0x2000, 0x3000, 0x4000])
def test_integrity_query_reads_final_mandatory_sid_subauthority(rid) -> None:
    api = _token_api()
    api.advapi = _IntegrityAdvapi(rid=rid)

    assert api._integrity_rid(ctypes.c_void_p(101)) == rid


def test_entry_failure_receipt_maps_only_closed_stage_and_reason(tmp_path) -> None:
    qualification_entry._write_failure(
        tmp_path, "preview", ValueError("qualification_export_unavailable")
    )
    assert json.loads((tmp_path / "failure.json").read_text(encoding="ascii")) == {
        "schema_version": 1,
        "stage": "preview",
        "reason": "qualification_export_unavailable",
    }
    qualification_entry._write_failure(
        tmp_path, "private-stage", RuntimeError("PRIVATE_PATH")
    )
    assert json.loads((tmp_path / "failure.json").read_text(encoding="ascii")) == {
        "schema_version": 1,
        "stage": "application",
        "reason": "unexpected",
    }


def test_driver_phase_closes_unexpected_failure_without_private_text() -> None:
    def fail() -> None:
        raise LookupError("PRIVATE_PATH_AND_NATIVE_TEXT")

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._run_driver_phase("startups", fail)

    assert error.value.failure_id == "scenario_failed"
    assert error.value.qualification_stage == "startups"
    assert error.value.qualification_reason == "unexpected"
    assert "PRIVATE_PATH" not in str(error.value)


def test_private_cleanup_failure_does_not_replace_classified_primary(
    tmp_path, monkeypatch
) -> None:
    class _Temporary:
        name = str(tmp_path)

        def cleanup(self) -> None:
            raise PermissionError("PRIVATE_LOCKED_PATH")

    monkeypatch.setattr(
        qualification.tempfile, "TemporaryDirectory", lambda **_keywords: _Temporary()
    )
    primary = qualification.QualificationFailure(
        "scenario_failed",
        qualification_stage="direct_normal_1",
        qualification_reason="process_exit_mismatch",
        qualification_exit_code=7,
    )

    def fail(_root: Path) -> None:
        raise primary

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._run_in_private_directory(fail)

    assert caught.value is primary
    assert caught.value.qualification_cleanup == "failed"


def test_private_cleanup_failure_after_success_is_closed_failure(
    tmp_path, monkeypatch
) -> None:
    class _Temporary:
        name = str(tmp_path)

        def cleanup(self) -> None:
            raise PermissionError("PRIVATE_LOCKED_PATH")

    monkeypatch.setattr(
        qualification.tempfile, "TemporaryDirectory", lambda **_keywords: _Temporary()
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._run_in_private_directory(lambda _root: "complete")

    assert caught.value.qualification_stage == "runner"
    assert caught.value.qualification_reason == "qualification_cleanup_failed"
    assert caught.value.qualification_cleanup == "failed"
    assert "PRIVATE_LOCKED_PATH" not in str(caught.value)


def test_private_cleanup_success_is_independent_from_classified_primary(
    tmp_path, monkeypatch
) -> None:
    class _Temporary:
        name = str(tmp_path)

        def cleanup(self) -> None:
            return None

    monkeypatch.setattr(
        qualification.tempfile, "TemporaryDirectory", lambda **_keywords: _Temporary()
    )
    primary = qualification.QualificationFailure(
        "scenario_failed",
        qualification_stage="hard_exit",
        qualification_reason="process_exit_mismatch",
        qualification_exit_code=7,
    )

    def fail(_root: Path) -> None:
        raise primary

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._run_in_private_directory(fail)

    assert caught.value is primary
    assert caught.value.qualification_cleanup == "complete"


def test_process_close_preserves_primary_when_cleanup_raises() -> None:
    class _Api:
        def close_process(self, *_arguments, **_keywords) -> None:
            raise OSError("PRIVATE_HANDLE_FAILURE")

    process = object.__new__(qualification._WindowsProcess)
    process._api = _Api()
    process._process = object()
    process._job = object()
    process._closed = False
    primary = qualification.QualificationFailure(
        "scenario_timeout",
        qualification_stage="direct_normal_1",
        qualification_reason="unexpected",
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        try:
            raise primary
        except qualification.QualificationFailure:
            process.close(terminate=True)
            raise

    assert caught.value is primary
    assert caught.value.qualification_cleanup == "failed"


def test_process_close_cleanup_failure_is_not_treated_as_success() -> None:
    class _Api:
        def close_process(self, *_arguments, **_keywords) -> None:
            raise OSError("PRIVATE_HANDLE_FAILURE")

    process = object.__new__(qualification._WindowsProcess)
    process._api = _Api()
    process._process = object()
    process._job = object()
    process._closed = False

    with pytest.raises(qualification.QualificationFailure) as caught:
        process.close(terminate=False)

    assert caught.value.qualification_reason == "qualification_cleanup_failed"
    assert caught.value.qualification_cleanup == "failed"
    assert "PRIVATE_HANDLE_FAILURE" not in str(caught.value)


def test_owned_job_termination_waits_for_zero_active_before_closing() -> None:
    class _Kernel:
        def __init__(self) -> None:
            self.calls = []

        def TerminateJobObject(self, job, code):
            self.calls.append(("terminate_job", job, code))
            return 1

        def TerminateProcess(self, process, code):
            self.calls.append(("terminate_process", process, code))
            return 1

        def WaitForSingleObject(self, process, milliseconds):
            self.calls.append(("wait", process, milliseconds))
            return qualification.WAIT_OBJECT_0

        def CloseHandle(self, handle):
            self.calls.append(("close", handle))
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    accounting = iter(((1, 2), (0, 2)))
    api._job_accounting = lambda _job: next(accounting)

    api.close_process("primary", "owned-job", terminate=True)

    assert api.kernel.calls == [
        ("terminate_job", "owned-job", 23),
        ("wait", "primary", 0),
        ("wait", "primary", 0),
        ("close", "owned-job"),
        ("close", "primary"),
    ]


def test_owned_job_zero_active_does_not_hide_unsignaled_primary(monkeypatch) -> None:
    class _Kernel:
        def TerminateJobObject(self, _job, _code):
            return 1

        def TerminateProcess(self, _process, _code):
            return 1

        def WaitForSingleObject(self, _process, _milliseconds):
            return qualification.WAIT_TIMEOUT

        def CloseHandle(self, _handle):
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    api._job_accounting = lambda _job: (0, 1)
    monotonic = iter((0.0, 0.001, 6.0))
    monkeypatch.setattr(qualification.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(qualification.time, "sleep", lambda _seconds: None)

    with pytest.raises(qualification.QualificationFailure) as caught:
        api.close_process("primary", "owned-job", terminate=True)

    assert caught.value.qualification_reason == "qualification_cleanup_failed"


def test_owned_job_close_checks_both_handle_results() -> None:
    class _Kernel:
        def __init__(self) -> None:
            self.closed = []

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return handle != "owned-job"

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()

    with pytest.raises(qualification.QualificationFailure) as caught:
        api.close_process("primary", "owned-job", terminate=False)

    assert api.kernel.closed == ["owned-job", "primary"]
    assert caught.value.qualification_cleanup == "failed"


def test_failed_launch_cleanup_drains_job_and_closes_every_handle() -> None:
    class _Kernel:
        def __init__(self) -> None:
            self.calls = []

        def TerminateJobObject(self, job, code):
            self.calls.append(("terminate_job", job, code))
            return 1

        def TerminateProcess(self, process, code):
            self.calls.append(("terminate_process", process, code))
            return 1

        def WaitForSingleObject(self, process, milliseconds):
            self.calls.append(("wait", process, milliseconds))
            return qualification.WAIT_OBJECT_0

        def CloseHandle(self, handle):
            self.calls.append(("close", handle))
            return 1

    class _Process:
        hThread = "thread"
        hProcess = "primary"

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    accounting = iter(((1, 2), (0, 2)))
    api._job_accounting = lambda _job: next(accounting)

    assert api._cleanup_created_process(_Process(), "owned-job")
    assert api.kernel.calls == [
        ("terminate_job", "owned-job", 22),
        ("terminate_process", "primary", 22),
        ("wait", "primary", 0),
        ("wait", "primary", 0),
        ("close", "thread"),
        ("close", "primary"),
        ("close", "owned-job"),
    ]


class _InterruptedLaunchKernel:
    def __init__(self, primary, failure_phase):
        self.primary = primary
        self.failure_phase = failure_phase
        self.closed = []
        self.terminated = []

    def CreateJobObjectW(self, _security, _name):
        if self.failure_phase == "job":
            raise self.primary
        return "owned-job"

    def SetInformationJobObject(self, *_arguments):
        return 1

    def AssignProcessToJobObject(self, _job, _process):
        raise self.primary

    def TerminateJobObject(self, _job, _code):
        self.terminated.append("owned-job")
        return 1

    def TerminateProcess(self, _process, _code):
        self.terminated.append("primary")
        return 1

    def WaitForSingleObject(self, _process, _milliseconds):
        return qualification.WAIT_OBJECT_0

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


@pytest.mark.parametrize(
    ("failure_type", "expected_type"),
    [
        (RuntimeError, qualification.QualificationFailure),
        (KeyboardInterrupt, KeyboardInterrupt),
        (SystemExit, SystemExit),
    ],
)
@pytest.mark.parametrize(
    ("failure_phase", "terminated", "closed"),
    [
        ("job", [], ["token"]),
        ("create", ["owned-job", "primary"], ["thread", "primary", "owned-job", "token"]),
        ("assign", ["owned-job", "primary"], ["thread", "primary", "owned-job", "token"]),
    ],
)
def test_launch_failure_cleans_created_process_and_preserves_primary(
    tmp_path, monkeypatch, failure_type, expected_type, failure_phase, terminated, closed
) -> None:
    primary = failure_type("PRIVATE_NATIVE_TEXT")
    class _Limits:
        class _Basic:
            LimitFlags = 0

        BasicLimitInformation = _Basic()

    class _Startup:
        cb = 0

    class _Process:
        hThread = None
        hProcess = None
        dwProcessId = 123

    class _Advapi:
        def CreateProcessAsUserW(self, *_arguments):
            _arguments[-1].hThread = "thread"
            _arguments[-1].hProcess = "primary"
            if failure_phase == "create":
                raise primary
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _InterruptedLaunchKernel(primary, failure_phase)
    api.advapi = _Advapi()
    api.EXTENDED_LIMITS = _Limits
    api.STARTUPINFOW = _Startup
    api.PROCESS_INFORMATION = _Process
    api._restricted_token = lambda: "token"
    api._job_accounting = lambda _job: (0, 1)
    monkeypatch.setattr(qualification.ctypes, "byref", lambda value: value)
    monkeypatch.setattr(qualification.ctypes, "sizeof", lambda _value: 1)

    with pytest.raises(expected_type) as caught:
        api.launch(tmp_path / "app.exe", {"SYSTEMROOT": "fixed"}, tmp_path)

    if failure_type is RuntimeError:
        assert caught.value.failure_id == "restricted_launch_unavailable"
        assert caught.value.qualification_cleanup == "complete"
        assert "PRIVATE_NATIVE_TEXT" not in str(caught.value)
    else:
        assert caught.value is primary
    assert api.kernel.terminated == terminated
    assert api.kernel.closed == closed


class _LaunchTransferProcessInfo:
    hThread = None
    hProcess = None
    dwProcessId = 12


class _LaunchTransferKernel:
    def __init__(self, closed):
        self.closed = closed

    def CreateJobObjectW(self, *_arguments):
        return "job"

    def SetInformationJobObject(self, *_arguments):
        return True

    def AssignProcessToJobObject(self, *_arguments):
        return True

    def ResumeThread(self, _thread):
        return 1

    def TerminateJobObject(self, *_arguments):
        return True

    def TerminateProcess(self, *_arguments):
        return True

    def WaitForSingleObject(self, *_arguments):
        return qualification.WAIT_OBJECT_0

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


class _InterruptingOwner(list):
    def __init__(self, interrupt_at, primary):
        super().__init__()
        self.interrupt_at = interrupt_at
        self.primary = primary

    def append(self, value):
        if self.interrupt_at == "before_register":
            raise self.primary
        super().append(value)
        if self.interrupt_at == "after_register":
            raise self.primary


def _fake_launch_api(tmp_path, monkeypatch, kernel):
    api = object.__new__(qualification._WindowsApi)
    api.kernel = kernel
    api.PROCESS_INFORMATION = _LaunchTransferProcessInfo
    api.EXTENDED_LIMITS = lambda: type(
        "Limits", (), {"BasicLimitInformation": type("Basic", (), {"LimitFlags": 0})()}
    )()
    api.STARTUPINFOW = lambda: type("Startup", (), {"cb": 0})()
    api._restricted_token = lambda: "token"

    def create(*arguments):
        process = arguments[-1]
        process.hThread = "thread"
        process.hProcess = "process"
        return True

    api._create_suspended_process = create
    api._process_observation = lambda *_args: qualification._ProcessObservation(
        12, 1, str(tmp_path / "app.exe")
    )
    api._verify_requested_initial = lambda _initial, _executable: None
    api._native_process_image = lambda _handle: (
        r"\Device\HarddiskVolume7\app.exe", None
    )
    api._job_accounting = lambda _job: (0, 1)
    monkeypatch.setattr(qualification.ctypes, "byref", lambda value: value)
    monkeypatch.setattr(qualification.ctypes, "sizeof", lambda _value: 1)
    return api


@pytest.mark.parametrize("mode", ("unavailable", "empty", "invalid", "interrupt"))
def test_suspended_native_anchor_capture_failure_closes_all_launch_handles(
    tmp_path, monkeypatch, mode
):
    closed = []
    api = _fake_launch_api(tmp_path, monkeypatch, _LaunchTransferKernel(closed))
    interrupt = KeyboardInterrupt("PRIVATE_ANCHOR_INTERRUPT")
    if mode == "interrupt":
        api._native_process_image = lambda _handle: (_ for _ in ()).throw(interrupt)
    elif mode == "unavailable":
        api._native_process_image = lambda _handle: (
            None, qualification._NativeAlternativeObservation("k32_image", "false", 5)
        )
    else:
        api._native_process_image = lambda _handle: (
            "" if mode == "empty" else r"C:\invalid\image.exe", None
        )
    owned = []

    with pytest.raises(
        KeyboardInterrupt if mode == "interrupt" else qualification.QualificationFailure
    ) as caught:
        api.launch(tmp_path / "app.exe", {}, tmp_path, owned=owned)
    if mode == "interrupt":
        assert caught.value is interrupt
    else:
        assert caught.value.qualification_reason == "native_image_query_unavailable"
        assert caught.value.native_observation is None
        assert caught.value.qualification_cleanup == "complete"
    assert owned == []
    assert closed == ["thread", "process", "job", "token"]


def test_launch_transfers_private_native_anchor_into_owned_wrapper(
    tmp_path, monkeypatch
):
    closed = []
    api = _fake_launch_api(tmp_path, monkeypatch, _LaunchTransferKernel(closed))
    owned = []
    process = api.launch(tmp_path / "app.exe", {}, tmp_path, owned=owned)
    try:
        assert owned == [process]
        assert process._initial_native_image == r"\Device\HarddiskVolume7\app.exe"
    finally:
        qualification._close_owned_processes(owned, terminate=True)
    assert process._closed
    assert closed == ["thread", "job", "process", "token"]


@pytest.mark.parametrize(
    "interrupt_at", ["before_wrapper_assignment", "before_register", "after_register"]
)
def test_native_launch_transfer_closes_wrapper_once_on_interrupt(
    tmp_path, monkeypatch, interrupt_at
) -> None:
    primary = KeyboardInterrupt("PRIVATE_INTERRUPT_DETAIL")
    closed = []
    api = _fake_launch_api(tmp_path, monkeypatch, _LaunchTransferKernel(closed))
    owned = _InterruptingOwner(interrupt_at, primary)

    with pytest.raises(KeyboardInterrupt) as caught:
        if interrupt_at == "before_wrapper_assignment":
            _interrupt_after_call(
                qualification._WindowsApi.launch.__code__, "launched", primary,
                lambda: api.launch(tmp_path / "app.exe", {}, tmp_path, owned=owned),
            )
        else:
            api.launch(tmp_path / "app.exe", {}, tmp_path, owned=owned)
    qualification._close_owned_processes(owned, terminate=True)

    assert caught.value is primary
    assert closed == (
        ["thread", "process", "job", "token"]
        if interrupt_at == "before_wrapper_assignment"
        else ["thread", "job", "process", "token"]
    )
    assert len(owned) == (1 if interrupt_at == "after_register" else 0)
    assert all(process._closed for process in owned)


def test_raw_launch_cleanup_attempts_all_handles_after_secondary_interrupt() -> None:
    primary = KeyboardInterrupt("PRIVATE_PRIMARY")
    secondary = SystemExit("PRIVATE_SECONDARY")
    calls = []

    class _Process:
        hThread = "thread"
        hProcess = "process"

    class _Kernel:
        def TerminateJobObject(self, *_arguments):
            calls.append("terminate_job")
            raise secondary

        def TerminateProcess(self, *_arguments):
            calls.append("terminate_process")
            return True

        def WaitForSingleObject(self, *_arguments):
            calls.append("wait")
            return qualification.WAIT_OBJECT_0

        def CloseHandle(self, handle):
            calls.append(handle)
            if handle == "thread":
                raise secondary
            return True

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    api._job_accounting = lambda _job: (0, 1)

    with pytest.raises(KeyboardInterrupt) as caught:
        try:
            raise primary
        except KeyboardInterrupt:
            complete, cleanup_error = api._cleanup_failed_launch(
                _Process(), "job", "token", None
            )
            assert not complete
            assert cleanup_error is secondary
            raise

    assert caught.value is primary
    assert calls == [
        "terminate_job", "terminate_process", "wait",
        "thread", "process", "job", "token",
    ]


@pytest.mark.parametrize("secondary_type", [KeyboardInterrupt, SystemExit])
def test_ordinary_launch_failure_propagates_secondary_cleanup_interrupt(
    tmp_path, monkeypatch, secondary_type
) -> None:
    ordinary = RuntimeError("PRIVATE_ORDINARY_DETAIL")
    secondary = secondary_type("PRIVATE_CLEANUP_DETAIL")
    closed = []

    class _Kernel(_LaunchTransferKernel):
        def AssignProcessToJobObject(self, *_arguments):
            raise ordinary

        def CloseHandle(self, handle):
            super().CloseHandle(handle)
            if handle == "thread":
                raise secondary
            return True

    api = _fake_launch_api(tmp_path, monkeypatch, _Kernel(closed))
    with pytest.raises(secondary_type) as caught:
        api.launch(tmp_path / "app.exe", {}, tmp_path)

    assert caught.value is secondary
    assert closed == ["thread", "process", "job", "token"]


@pytest.mark.parametrize("secondary_type", [KeyboardInterrupt, SystemExit])
def test_ordinary_launch_failure_preserves_raw_termination_interrupt(
    tmp_path, monkeypatch, secondary_type
) -> None:
    ordinary = RuntimeError("PRIVATE_ORDINARY_DETAIL")
    secondary = secondary_type("PRIVATE_TERMINATION_DETAIL")
    closed = []
    termination_attempts = []

    class _Kernel(_LaunchTransferKernel):
        def AssignProcessToJobObject(self, *_arguments):
            raise ordinary

        def TerminateJobObject(self, *_arguments):
            termination_attempts.append("job")
            raise secondary

        def TerminateProcess(self, *_arguments):
            termination_attempts.append("process")
            return True

    api = _fake_launch_api(tmp_path, monkeypatch, _Kernel(closed))
    with pytest.raises(secondary_type) as caught:
        api.launch(tmp_path / "app.exe", {}, tmp_path)

    assert caught.value is secondary
    assert termination_attempts == ["job", "process"]
    assert closed == ["thread", "process", "job", "token"]


def test_later_raw_cleanup_interrupt_outweighs_earlier_ordinary_error(
    tmp_path, monkeypatch
) -> None:
    ordinary = RuntimeError("PRIVATE_LAUNCH_DETAIL")
    cleanup_error = RuntimeError("PRIVATE_TERMINATION_DETAIL")
    secondary = SystemExit("PRIVATE_HANDLE_DETAIL")
    closed = []

    class _Kernel(_LaunchTransferKernel):
        def AssignProcessToJobObject(self, *_arguments):
            raise ordinary

        def TerminateJobObject(self, *_arguments):
            raise cleanup_error

        def CloseHandle(self, handle):
            super().CloseHandle(handle)
            if handle == "thread":
                raise secondary
            return True

    api = _fake_launch_api(tmp_path, monkeypatch, _Kernel(closed))
    with pytest.raises(SystemExit) as caught:
        api.launch(tmp_path / "app.exe", {}, tmp_path)

    assert caught.value is secondary
    assert closed == ["thread", "process", "job", "token"]


@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("failure_phase", ["open", "restrict", "medium"])
def test_interrupted_token_creation_closes_acquired_handles(
    monkeypatch, failure_type, failure_phase
) -> None:
    from types import SimpleNamespace

    primary = failure_type("PRIVATE_INTERRUPT_DETAIL")
    closed = []

    class _Handle:
        value = 0

        def __bool__(self):
            return bool(self.value)

    class _Advapi:
        def OpenProcessToken(self, _process, _access, current):
            current.value = 1
            if failure_phase == "open":
                raise primary
            return True

        def CreateWellKnownSid(self, *_arguments):
            return True

        def CreateRestrictedToken(self, *_arguments):
            _arguments[-1].value = 2
            if failure_phase == "restrict":
                raise primary
            return True

    def interrupt_medium(_token):
        raise primary

    def close(handle):
        closed.append(handle.value)
        return True

    api = object.__new__(qualification._WindowsApi)
    api.wintypes = SimpleNamespace(HANDLE=_Handle, DWORD=qualification.ctypes.c_uint32)
    api.kernel = SimpleNamespace(GetCurrentProcess=lambda: -1, CloseHandle=close)
    api.advapi = _Advapi()
    api.SID_AND_ATTRIBUTES = lambda *_arguments: object()
    api._set_medium_integrity = interrupt_medium
    monkeypatch.setattr(qualification.ctypes, "byref", lambda value: value)

    with pytest.raises(failure_type) as caught:
        api._restricted_token()

    assert caught.value is primary
    assert closed == ([1] if failure_phase == "open" else [2, 1])


@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("restricted_cleanup_fails", [False, True])
def test_interrupted_final_current_token_close_attempts_restricted_cleanup(
    monkeypatch, failure_type, restricted_cleanup_fails
) -> None:
    from types import SimpleNamespace

    primary = failure_type("PRIVATE_INTERRUPT_DETAIL")
    secondary = SystemExit("PRIVATE_CLEANUP_DETAIL")
    closed = []

    class _Handle:
        value = 0

        def __bool__(self):
            return bool(self.value)

    class _Advapi:
        def OpenProcessToken(self, _process, _access, current):
            current.value = 1
            return True

        def CreateWellKnownSid(self, *_arguments):
            return True

        def CreateRestrictedToken(self, *_arguments):
            _arguments[-1].value = 2
            return True

    def close(handle):
        closed.append(handle.value)
        if handle.value == 1:
            raise primary
        if restricted_cleanup_fails:
            raise secondary
        return True

    api = object.__new__(qualification._WindowsApi)
    api.wintypes = SimpleNamespace(HANDLE=_Handle, DWORD=qualification.ctypes.c_uint32)
    api.kernel = SimpleNamespace(GetCurrentProcess=lambda: -1, CloseHandle=close)
    api.advapi = _Advapi()
    api.SID_AND_ATTRIBUTES = lambda *_arguments: object()
    api._set_medium_integrity = lambda _token: None
    api._integrity_rid = lambda _token: qualification.MEDIUM_INTEGRITY_RID
    api._has_effective_admin_membership = lambda _token, _sid: False
    api._set_private_default_dacl = lambda _token: None
    monkeypatch.setattr(qualification.ctypes, "byref", lambda value: value)

    with pytest.raises(failure_type) as caught:
        api._restricted_token()

    assert caught.value is primary
    assert closed == [1, 2]


@pytest.mark.parametrize(
    "body_failure_type", [qualification.QualificationFailure, KeyboardInterrupt]
)
@pytest.mark.parametrize("final_failure_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("first_restricted_close_succeeds", [True, False])
def test_final_token_close_retries_only_a_still_owned_restricted_handle(
    monkeypatch,
    body_failure_type,
    final_failure_type,
    first_restricted_close_succeeds,
) -> None:
    from types import SimpleNamespace

    body_failure = body_failure_type("restricted_launch_unavailable")
    final_failure = final_failure_type("PRIVATE_FINAL_INTERRUPT")
    closed = []

    class _Handle:
        value = 0

        def __bool__(self):
            return bool(self.value)

    class _Advapi:
        def OpenProcessToken(self, _process, _access, current):
            current.value = 1
            return True

        def CreateWellKnownSid(self, *_arguments):
            return True

        def CreateRestrictedToken(self, *_arguments):
            _arguments[-1].value = 2
            return True

    def close(handle):
        closed.append(handle.value)
        if handle.value == 1:
            raise final_failure
        if handle.value == 2 and closed.count(2) == 1:
            return first_restricted_close_succeeds
        return True

    def fail_medium(_token):
        raise body_failure

    api = object.__new__(qualification._WindowsApi)
    api.wintypes = SimpleNamespace(HANDLE=_Handle, DWORD=qualification.ctypes.c_uint32)
    api.kernel = SimpleNamespace(GetCurrentProcess=lambda: -1, CloseHandle=close)
    api.advapi = _Advapi()
    api.SID_AND_ATTRIBUTES = lambda *_arguments: object()
    api._set_medium_integrity = fail_medium
    monkeypatch.setattr(qualification.ctypes, "byref", lambda value: value)

    with pytest.raises(final_failure_type) as caught:
        api._restricted_token()

    assert caught.value is final_failure
    assert closed == ([2, 1] if first_restricted_close_succeeds else [2, 1, 2])


def test_concurrent_cleanup_attempts_every_owned_process() -> None:
    calls = []

    class _Process:
        def __init__(self, label, fail):
            self.label = label
            self.fail = fail

        def close(self, *, terminate):
            calls.append((self.label, terminate))
            if self.fail:
                raise qualification.QualificationFailure(
                    "scenario_failed",
                    qualification_reason="qualification_cleanup_failed",
                    qualification_cleanup="failed",
                )

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._close_processes(
            (_Process("first", True), _Process("second", False)), terminate=True
        )

    assert calls == [("first", True), ("second", True)]
    assert caught.value.qualification_cleanup == "failed"


@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_second_concurrent_launch_interrupt_closes_first_owned_process(
    tmp_path, monkeypatch, failure_type, cleanup_fails
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    primary = failure_type("PRIVATE_INTERRUPT_DETAIL")
    launched = []
    closed = []

    class _Process:
        def close(self, *, terminate):
            closed.append(terminate)
            if cleanup_fails:
                raise qualification.QualificationFailure(
                    "scenario_failed",
                    qualification_reason="qualification_cleanup_failed",
                    qualification_cleanup="failed",
                )

    class _Api:
        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            launched.append(_cwd)
            if len(launched) == 2:
                raise primary
            process = _Process()
            owned.append(process)
            return process

    roots = (tmp_path / "first", tmp_path / "second")
    with pytest.raises(failure_type) as caught:
        qualification._launch_concurrent_pair(
            _Api(), tmp_path / "application.exe", tmp_path, roots, tmp_path
        )

    assert caught.value is primary
    assert launched == list(roots)
    assert closed == [True]


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_second_concurrent_launch_failure_records_first_process_cleanup(
    tmp_path, monkeypatch, cleanup_fails
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    primary = qualification.QualificationFailure("restricted_launch_unavailable")
    closed = []

    class _Process:
        def close(self, *, terminate):
            closed.append(terminate)
            if cleanup_fails:
                raise qualification.QualificationFailure(
                    "scenario_failed", qualification_cleanup="failed"
                )

    class _Api:
        count = 0

        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            self.count += 1
            if self.count == 2:
                raise primary
            process = _Process()
            owned.append(process)
            return process

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._launch_concurrent_pair(
            _Api(),
            tmp_path / "application.exe",
            tmp_path,
            (tmp_path / "first", tmp_path / "second"),
            tmp_path,
        )

    assert caught.value is primary
    assert primary.qualification_cleanup == ("failed" if cleanup_fails else "complete")
    assert closed == [True]


@pytest.mark.parametrize("failure_type", [qualification.QualificationFailure, RuntimeError])
def test_first_concurrent_launch_failure_has_no_owned_process_to_clean(
    tmp_path, monkeypatch, failure_type
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    primary = failure_type("restricted_launch_unavailable")
    launches = []

    class _Api:
        def launch(self, _executable, _environment, cwd, owned=None, expected_images=None):
            launches.append(cwd)
            raise primary

    with pytest.raises(failure_type) as caught:
        qualification._launch_concurrent_pair(
            _Api(),
            tmp_path / "application.exe",
            tmp_path,
            (tmp_path / "first", tmp_path / "second"),
            tmp_path,
        )

    assert caught.value is primary
    assert launches == [tmp_path / "first"]
    if isinstance(primary, qualification.QualificationFailure):
        assert primary.qualification_cleanup == "not_attempted"


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_second_concurrent_launch_ordinary_error_preserves_existing_cleanup_route(
    tmp_path, monkeypatch, cleanup_fails
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    primary = RuntimeError("PRIVATE_LAUNCH_ERROR")
    closed = []

    class _Process:
        def close(self, *, terminate):
            closed.append(terminate)
            if cleanup_fails:
                raise qualification.QualificationFailure(
                    "scenario_failed", qualification_cleanup="failed"
                )

    class _Api:
        count = 0

        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            self.count += 1
            if self.count == 2:
                raise primary
            process = _Process()
            owned.append(process)
            return process

    caught_type = qualification.QualificationFailure if cleanup_fails else RuntimeError
    with pytest.raises(caught_type) as caught:
        qualification._launch_concurrent_pair(
            _Api(),
            tmp_path / "application.exe",
            tmp_path,
            (tmp_path / "first", tmp_path / "second"),
            tmp_path,
        )

    if cleanup_fails:
        assert caught.value.qualification_cleanup == "failed"
    else:
        assert caught.value is primary
    assert closed == [True]


@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("cleanup_type", [KeyboardInterrupt, SystemExit])
def test_concurrent_cleanup_interrupt_does_not_replace_launch_interrupt(
    tmp_path, monkeypatch, failure_type, cleanup_type
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    primary = failure_type("PRIVATE_LAUNCH_INTERRUPT")
    secondary = cleanup_type("PRIVATE_CLEANUP_INTERRUPT")
    closed = []

    class _Process:
        def close(self, *, terminate):
            closed.append(terminate)
            raise secondary

    class _Api:
        count = 0

        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            self.count += 1
            if self.count == 2:
                raise primary
            process = _Process()
            owned.append(process)
            return process

    with pytest.raises(failure_type) as caught:
        qualification._launch_concurrent_pair(
            _Api(),
            tmp_path / "application.exe",
            tmp_path,
            (tmp_path / "first", tmp_path / "second"),
            tmp_path,
        )

    assert caught.value is primary
    assert closed == [True]


def test_owned_pair_cleanup_attempts_second_after_secondary_interrupt() -> None:
    primary = KeyboardInterrupt("PRIVATE_PRIMARY")
    secondary = SystemExit("PRIVATE_SECONDARY")
    closed = []

    class _Process:
        def __init__(self, index):
            self.index = index

        def close(self, *, terminate):
            closed.append((self.index, terminate))
            if self.index == 1:
                raise secondary

    try:
        raise primary
    except KeyboardInterrupt:
        qualification._close_owned_processes(
            [_Process(1), _Process(2)], terminate=True
        )

    assert closed == [(1, True), (2, True)]


def test_owned_pair_cleanup_propagates_interrupt_without_prior_primary() -> None:
    secondary = SystemExit("PRIVATE_CLEANUP")
    closed = []

    class _Process:
        def __init__(self, index):
            self.index = index

        def close(self, *, terminate):
            closed.append((self.index, terminate))
            if self.index == 1:
                raise secondary

    with pytest.raises(SystemExit) as caught:
        qualification._close_owned_processes(
            [_Process(1), _Process(2)], terminate=True
        )

    assert caught.value is secondary
    assert closed == [(1, True), (2, True)]


def test_later_owned_process_interrupt_outweighs_earlier_ordinary_error() -> None:
    ordinary = qualification.QualificationFailure(
        "scenario_failed", qualification_cleanup="failed"
    )
    secondary = KeyboardInterrupt("PRIVATE_SECOND_CLOSE")
    closed = []

    class _Process:
        def __init__(self, index):
            self.index = index

        def close(self, *, terminate):
            closed.append((self.index, terminate))
            raise ordinary if self.index == 1 else secondary

    with pytest.raises(KeyboardInterrupt) as caught:
        qualification._close_owned_processes(
            [_Process(1), _Process(2)], terminate=True
        )

    assert caught.value is secondary
    assert closed == [(1, True), (2, True)]


def test_thread_close_interrupt_still_attempts_job_and_process_handles() -> None:
    secondary = KeyboardInterrupt("PRIVATE_THREAD_CLOSE")
    closed = []

    class _Kernel:
        def CloseHandle(self, handle):
            closed.append(handle)
            if handle == "thread":
                raise secondary
            return True

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    with pytest.raises(KeyboardInterrupt) as caught:
        api.close_process("process", "job", terminate=False, thread="thread")

    assert caught.value is secondary
    assert closed == ["thread", "job", "process"]


def test_handle_close_prefers_later_interrupt_after_ordinary_failure() -> None:
    ordinary = qualification.QualificationFailure("scenario_failed")
    secondary = SystemExit("PRIVATE_JOB_CLOSE")
    closed = []

    class _Kernel:
        def CloseHandle(self, handle):
            closed.append(handle)
            if handle == "thread":
                raise ordinary
            if handle == "job":
                raise secondary
            return True

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    with pytest.raises(SystemExit) as caught:
        api.close_process("process", "job", terminate=False, thread="thread")

    assert caught.value is secondary
    assert closed == ["thread", "job", "process"]


@pytest.mark.parametrize("phase", ["termination", "drain"])
@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
def test_inflight_interrupt_survives_secondary_handle_close_interrupt(
    phase, primary_type
) -> None:
    primary = primary_type("PRIVATE_PRIMARY")
    secondary = SystemExit("PRIVATE_SECONDARY") if primary_type is KeyboardInterrupt else KeyboardInterrupt("PRIVATE_SECONDARY")
    closed = []

    class _Kernel:
        def TerminateJobObject(self, *_arguments):
            if phase == "termination":
                raise primary
            return True

        def WaitForSingleObject(self, *_arguments):
            return qualification.WAIT_OBJECT_0

        def CloseHandle(self, handle):
            closed.append(handle)
            if handle == "thread":
                raise secondary
            return True

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()

    def accounting(_job):
        if phase == "drain":
            raise primary
        return 0, 1

    api._job_accounting = accounting
    with pytest.raises(primary_type) as caught:
        api.close_process(
            "process", "job", terminate=True, thread="thread", token="token"
        )

    assert caught.value is primary
    assert closed == ["thread", "job", "process", "token"]


def test_ordinary_termination_error_keeps_secondary_interrupt_semantics() -> None:
    ordinary = qualification.QualificationFailure("scenario_failed")
    secondary = KeyboardInterrupt("PRIVATE_SECONDARY")
    closed = []

    class _Kernel:
        def TerminateJobObject(self, *_arguments):
            raise ordinary

        def CloseHandle(self, handle):
            closed.append(handle)
            if handle == "thread":
                raise secondary
            return True

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    with pytest.raises(KeyboardInterrupt) as caught:
        api.close_process(
            "process", "job", terminate=True, thread="thread", token="token"
        )

    assert caught.value is secondary
    assert closed == ["thread", "job", "process", "token"]


def _interrupt_after_call(code, store_name: str | None, primary, action) -> None:
    instructions = list(dis.get_instructions(code))
    transfer = next(
        instruction.offset
        for index, instruction in enumerate(instructions)
        if instructions[index - 1].opname == "CALL"
        and instruction.opname in (
            ("POP_TOP",) if store_name is None else ("STORE_FAST", "STORE_DEREF")
        )
        and (store_name is None or instruction.argval == store_name)
    )

    def trace(frame, event, _argument):
        if frame.f_code is code:
            if event == "call":
                frame.f_trace_opcodes = True
            elif event == "opcode" and frame.f_lasti == transfer:
                raise primary
        return trace

    previous_trace = sys.gettrace()
    sys.settrace(trace)
    try:
        action()
    finally:
        sys.settrace(previous_trace)


def test_concurrent_launch_transfer_interrupt_closes_registered_process(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    primary = KeyboardInterrupt("PRIVATE_TRANSFER")
    closed = []

    class _Process:
        def close(self, *, terminate):
            closed.append(terminate)

    class _Api:
        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            process = _Process()
            owned.append(process)
            return process

    with pytest.raises(KeyboardInterrupt) as caught:
        _interrupt_after_call(
            qualification._launch_concurrent_pair.__code__, None, primary,
            lambda: qualification._launch_concurrent_pair(
                _Api(), tmp_path / "app.exe", tmp_path,
                (tmp_path / "one", tmp_path / "two"), tmp_path,
            ),
        )

    assert caught.value is primary
    assert closed == [True]


def test_scenario_launch_transfer_interrupt_closes_registered_process(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    primary = SystemExit("PRIVATE_TRANSFER")
    closed = []

    class _Process:
        def close(self, *, terminate):
            closed.append(terminate)

    class _Api:
        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            process = _Process()
            owned.append(process)
            return process

    with pytest.raises(SystemExit) as caught:
        _interrupt_after_call(
            qualification._run_scenario.__code__, "process", primary,
            lambda: qualification._run_scenario(
                _Api(), tmp_path / "app.exe", tmp_path, tmp_path, tmp_path,
                "normal", time.monotonic() + 1,
                expected_exit=0, expected_stage="complete",
            ),
        )

    assert caught.value is primary
    assert closed == [True]


@pytest.mark.parametrize(
    ("method", "store_name", "expected_closed"),
    [
        ("run_concurrent_instances", "processes", 2),
        ("run_ui_smoke", "process", 1),
        ("run_missing_components", "process", 1),
        ("run_missing_qt_resource", "process", 1),
    ],
)
def test_runner_launch_transfer_interrupt_closes_every_registered_process(
    tmp_path, monkeypatch, method, store_name, expected_closed
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setattr(qualification, "_reports", lambda _store: ())
    primary = KeyboardInterrupt("PRIVATE_TRANSFER")
    closed = []

    class _Process:
        def close(self, *, terminate):
            closed.append(terminate)

    class _Api:
        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            process = _Process()
            owned.append(process)
            return process

    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "metroliza.exe").write_bytes(b"fixed")
    (artifact / qualification.MANIFEST_NAME).write_bytes(b"fixed")
    resource = (
        artifact / "_internal" / "PyQt6" / "Qt6" / "plugins"
        / "platforms" / "qwindows.dll"
    )
    resource.parent.mkdir(parents=True)
    resource.write_bytes(b"fixed")
    runner = object.__new__(qualification._QualificationRunner)
    runner.api = _Api()
    runner.artifact = artifact
    runner.launcher = artifact / "metroliza.exe"
    runner.state_base = tmp_path / "state"
    runner.private_root = tmp_path / "work"
    runner.private_root.mkdir()
    runner.store = object()
    runner.results = {}
    runner.deadline = time.monotonic() + 1
    runner._root = lambda label: qualification._prepare_work_root(
        runner.private_root, label
    )
    action = getattr(runner, method)

    with pytest.raises(KeyboardInterrupt) as caught:
        _interrupt_after_call(
            getattr(qualification._QualificationRunner, method).__code__,
            store_name, primary, action,
        )

    assert caught.value is primary
    assert closed == [True] * expected_closed
    assert resource.read_bytes() == b"fixed"


def test_driver_phase_preserves_safe_early_process_exit_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    class _NoReceiptApi(_FakeApi):
        def launch(self, executable, environment, cwd, owned=None, expected_images=None):
            process = super().launch(executable, environment, cwd, owned=owned)
            (cwd / "startup.json").unlink()
            (cwd / qualification.QUALIFICATION_RECEIPT_NAMES[self.stage]).unlink()
            markers = cwd / qualification.PROBE_DIRECTORY
            markers.mkdir()
            (markers / "launcher_entry").touch()
            (markers / "package_rejected").touch()
            return process

    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_STARTUP_PROBE", "1")
    api = _NoReceiptApi(3221225477, "failed")
    artifact = tmp_path / "artifact"
    work = tmp_path / "work"
    state = tmp_path / "state"
    for path in (artifact, work, state):
        path.mkdir()

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._run_driver_phase(
            "startups",
            lambda: qualification._run_scenario(
                api,
                artifact / "metroliza_application.exe",
                artifact,
                work,
                state,
                "normal",
                time.monotonic() + 1,
                expected_exit=0,
                expected_stage="complete",
            ),
        )

    assert error.value.qualification_stage == "startups"
    assert error.value.qualification_reason == "process_exited_before_startup"
    assert error.value.qualification_exit_code == 3221225477
    assert error.value.startup_phases == ("launcher_entry", "package_rejected")
    detail = qualification._failure_detail(
        error.value.qualification_stage, error.value.qualification_reason,
        None, error.value.qualification_exit_code, None, error.value.startup_phases,
    )
    assert qualification._valid_failure_detail(detail)
    assert detail["startup_phases"] == ["launcher_entry", "package_rejected"]


def test_startup_failure_retains_exact_host_and_child_stage(monkeypatch) -> None:
    runner = object.__new__(qualification._QualificationRunner)
    runner.store = object()
    runner.application = Path("metroliza_application.exe")
    monkeypatch.setattr(qualification, "_reports", lambda _store: ())

    def fail_scenario(*_arguments, **_keywords) -> None:
        raise qualification.QualificationFailure(
            "scenario_failed",
            qualification_reason="qualification_result_mismatch",
            qualification_child_stage="workflows",
        )

    runner._scenario = fail_scenario

    with pytest.raises(qualification.QualificationFailure) as error:
        runner.run_startups()

    assert error.value.qualification_stage == "direct_normal_1"
    assert error.value.qualification_child_stage == "workflows"
    assert error.value.qualification_reason == "qualification_result_mismatch"


def test_job_observation_omits_only_confirmed_disappeared_pid(monkeypatch) -> None:
    class _ProcessIds(ctypes.Structure):
        _fields_ = [
            ("NumberOfAssignedProcesses", ctypes.c_uint32),
            ("NumberOfProcessIdsInList", ctypes.c_uint32),
            ("ProcessIdList", ctypes.c_size_t * 16),
        ]

    class _Accounting(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong),
            ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", ctypes.c_uint32),
            ("TotalProcesses", ctypes.c_uint32),
            ("ActiveProcesses", ctypes.c_uint32),
            ("TotalTerminatedProcesses", ctypes.c_uint32),
        ]

    class _Kernel:
        process_queries = 0

        def QueryInformationJobObject(self, _job, kind, value, _size, _returned):
            if kind == 1:
                accounting = ctypes.cast(value, ctypes.POINTER(_Accounting)).contents
                accounting.TotalProcesses = 1
                accounting.ActiveProcesses = 0
                return 1
            info = ctypes.cast(value, ctypes.POINTER(_ProcessIds)).contents
            self.process_queries += 1
            if self.process_queries == 1:
                info.NumberOfAssignedProcesses = 1
                info.NumberOfProcessIdsInList = 1
                info.ProcessIdList[0] = 404
            return 1

        def OpenProcess(self, _access, _inherit, process_id):
            assert process_id == 404
            return 0

    api = object.__new__(qualification._WindowsApi)
    api.wintypes = _TokenWinTypes
    api.PROCESS_IDS = _ProcessIds
    api.BASIC_ACCOUNTING = _Accounting
    api.kernel = _Kernel()
    monkeypatch.setattr(
        qualification.ctypes,
        "get_last_error",
        lambda: qualification.WINDOWS_ERROR_INVALID_PARAMETER,
        raising=False,
    )

    observations, active, assigned = api.job_observations(object())

    assert observations == ()
    assert (active, assigned) == (0, 1)
    topology = qualification._classify_topology(
        observations,
        assigned,
        active,
        True,
        Path("launcher"),
        Path("application"),
    )
    assert topology.unexpected_processes_observed == 1


@pytest.mark.parametrize(
    "reason",
    ["native_image_query_unavailable", "native_process_times_unavailable"],
)
def test_job_observation_omits_confirmed_disappearance_after_open_query_failure(
    reason,
) -> None:
    class _Kernel:
        closed = []

        def OpenProcess(self, _access, _inherit, process_id):
            assert process_id == 407
            return 77

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    snapshots = iter(((407,), ()))
    api._job_process_ids = lambda _job: next(snapshots)
    primary = qualification.QualificationFailure(
        "scenario_failed", qualification_reason=reason
    )

    def fail_observation(_process, _process_id):
        raise primary

    api._process_observation = fail_observation
    api._job_accounting = lambda _job: (0, 1)

    observations, active, assigned = api.job_observations(object())

    assert observations == ()
    assert (active, assigned) == (0, 1)
    assert api.kernel.closed == [77]
    topology = qualification._classify_topology(
        observations,
        assigned,
        active,
        True,
        Path("launcher"),
        Path("application"),
    )
    assert topology.unexpected_processes_observed == 1


@pytest.mark.parametrize("drift", (None, "image", "creation"))
def test_job_observation_uses_retained_primary_and_rechecks_identity(drift) -> None:
    initial = qualification._ProcessObservation(407, 1234, r"C:\fixed\application.exe")
    retained = object()

    class _Kernel:
        opened = []
        closed = []

        def OpenProcess(self, _access, _inherit, process_id):
            self.opened.append(process_id)
            return 88

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    api._job_process_ids = lambda _job: (initial.process_id,)
    api._job_accounting = lambda _job: (1, 1)

    def observe(handle, process_id):
        assert handle is retained
        assert process_id == initial.process_id
        return qualification._ProcessObservation(
            process_id,
            initial.creation_time + (drift == "creation"),
            initial.image + (".other" if drift == "image" else ""),
        )

    api._process_observation = observe
    if drift is None:
        observations, active, assigned = api.job_observations(
            object(), primary_process=retained, primary_initial=initial,
            primary_native_image=TEST_NATIVE_ANCHOR,
        )
        assert (observations, active, assigned) == ((initial,), 1, 1)
    else:
        with pytest.raises(qualification.QualificationFailure) as caught:
            api.job_observations(
                object(), primary_process=retained, primary_initial=initial,
                primary_native_image=TEST_NATIVE_ANCHOR,
            )
        assert caught.value.qualification_reason == "native_primary_identity_mismatch"
        assert caught.value.native_observation is None
    assert api.kernel.opened == []
    assert api.kernel.closed == []


def test_owned_process_observe_survives_primary_reopen_image_denial() -> None:
    initial = qualification._ProcessObservation(411, 1234, r"C:\fixed\application.exe")
    retained = object()

    class _Kernel:
        opened = []
        closed = []

        def OpenProcess(self, _access, _inherit, process_id):
            self.opened.append(process_id)
            return 88

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    api._job_process_ids = lambda _job: (initial.process_id,)
    api._job_accounting = lambda _job: (1, 1)

    def observe(handle, process_id):
        assert process_id == initial.process_id
        if handle is retained:
            return initial
        raise qualification.QualificationFailure(
            "scenario_failed", qualification_reason="native_image_query_unavailable",
            native_observation=qualification._NativeIdentityObservation(
                None, "image", "false", 5, "unknown"
            ),
        )

    api._process_observation = observe
    process = qualification._WindowsProcess(
        api, retained, object(), 0.0, initial,
        (Path(r"C:\fixed\application.exe"),),
        initial_native_image=TEST_NATIVE_ANCHOR,
    )
    process.observe()
    assert process._observations == {initial.process_id: initial}
    assert api.kernel.opened == []
    assert api.kernel.closed == []


def test_retired_primary_absent_from_fresh_job_ids_keeps_verified_initial() -> None:
    initial = qualification._ProcessObservation(412, 4321, r"C:\fixed\application.exe")
    retained = object()
    api = object.__new__(qualification._WindowsApi)
    api._job_process_ids = lambda _job: ()
    api._job_accounting = lambda _job: (0, 1)

    def unexpected_observation(*_arguments):
        raise AssertionError("absent process must not be reattributed")

    api._process_observation = unexpected_observation
    process = qualification._WindowsProcess(
        api, retained, object(), 0.0, initial,
        (Path(r"C:\fixed\application.exe"),),
        initial_native_image=TEST_NATIVE_ANCHOR,
    )

    process.observe()

    assert process._observations == {initial.process_id: initial}
    assert process._assigned_processes == 1
    assert process.active_processes() == 0


@pytest.mark.parametrize("membership", ("absent", "still_listed", "requery_failed"))
def test_retained_primary_query_failure_requires_proven_job_disappearance(
    membership,
) -> None:
    initial = qualification._ProcessObservation(408, 5678, r"C:\fixed\application.exe")
    retained = object()
    api = object.__new__(qualification._WindowsApi)
    queries = []

    def ids(_job):
        queries.append(None)
        if len(queries) == 1:
            return (initial.process_id,)
        if membership == "requery_failed":
            raise qualification.QualificationFailure(
                "scenario_failed", qualification_reason="native_job_ids_unavailable"
            )
        return () if membership == "absent" else (initial.process_id,)

    api._job_process_ids = ids
    api._job_accounting = lambda _job: (0, 1)
    api.kernel = object()
    api._native_process_image = lambda _handle: (
        None, qualification._NativeAlternativeObservation("k32_image", "false", 5)
    )
    primary = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        native_observation=qualification._NativeIdentityObservation(
            None, "image", "false", 5, "exited"
        ),
    )

    def fail_observation(handle, process_id):
        assert handle is retained
        assert process_id == initial.process_id
        raise primary

    api._process_observation = fail_observation
    if membership == "absent":
        assert api.job_observations(
            object(), primary_process=retained, primary_initial=initial,
            primary_native_image=TEST_NATIVE_ANCHOR,
        ) == ((), 0, 1)
    else:
        with pytest.raises(qualification.QualificationFailure) as caught:
            api.job_observations(
                object(), primary_process=retained, primary_initial=initial,
                primary_native_image=TEST_NATIVE_ANCHOR,
            )
        assert caught.value is primary
        assert primary.native_observation.receipt() == {
            "phase": "owned_job_observation", "api": "image", "outcome": "false",
            "winerror": 5, "process_state": "exited",
            "alternative": {
                "api": "k32_image", "outcome": "false", "winerror": 5,
            },
        }
    assert len(queries) == 2


def test_retained_primary_does_not_hide_other_job_member_query_failure() -> None:
    initial = qualification._ProcessObservation(409, 1234, r"C:\fixed\application.exe")
    retained = object()

    class _Kernel:
        opened = []
        closed = []

        def OpenProcess(self, _access, _inherit, process_id):
            self.opened.append(process_id)
            return 99

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    api._job_process_ids = lambda _job: (409, 410)
    api._job_accounting = lambda _job: (2, 2)
    primary = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        native_observation=qualification._NativeIdentityObservation(
            None, "image", "false", 5, "unknown"
        ),
    )

    def observe(handle, process_id):
        if process_id == initial.process_id:
            assert handle is retained
            return initial
        assert handle == 99
        raise primary

    api._process_observation = observe
    with pytest.raises(qualification.QualificationFailure) as caught:
        api.job_observations(
            object(), primary_process=retained, primary_initial=initial,
            primary_native_image=TEST_NATIVE_ANCHOR,
        )
    assert caught.value is primary
    assert primary.native_observation.phase == "job_observation"
    assert api.kernel.opened == [410]
    assert api.kernel.closed == [99]


@pytest.mark.parametrize("mode", ["still_listed", "requery_failed", "unrelated"])
def test_job_observation_keeps_post_open_failures_fatal(mode) -> None:
    class _Kernel:
        closed = []

        def OpenProcess(self, _access, _inherit, process_id):
            assert process_id == 408
            return 78

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    calls = []

    def process_ids(_job):
        calls.append(None)
        if len(calls) == 1:
            return (408,)
        if mode == "requery_failed":
            raise qualification.QualificationFailure(
                "scenario_failed", qualification_reason="native_job_ids_unavailable"
            )
        return (408,) if mode == "still_listed" else ()

    api._job_process_ids = process_ids
    primary = qualification.QualificationFailure(
        "artifact_invalid"
        if mode == "unrelated"
        else "scenario_failed",
        qualification_reason=(
            None if mode == "unrelated" else "native_image_query_unavailable"
        ),
        native_observation=(
            None if mode == "unrelated" else qualification._NativeIdentityObservation(
                None, "image", "false", 31, "unknown"
            )
        ),
    )

    def fail_observation(_process, _process_id):
        raise primary

    api._process_observation = fail_observation
    api._job_accounting = lambda _job: (1, 1)

    with pytest.raises(qualification.QualificationFailure) as caught:
        api.job_observations(object())

    assert caught.value is primary
    if mode != "unrelated":
        assert caught.value.qualification_reason == "native_image_query_unavailable"
        assert caught.value.native_observation.phase == "job_observation"
        assert caught.value.native_observation.winerror == 31
    assert len(calls) == (1 if mode == "unrelated" else 2)
    assert api.kernel.closed == [78]


@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit])
def test_job_observation_preserves_post_open_interrupt(failure_type) -> None:
    class _Kernel:
        closed = []

        def OpenProcess(self, *_arguments):
            return 79

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    ids_calls = []
    api._job_process_ids = lambda _job: ids_calls.append(None) or (409,)
    primary = failure_type("PRIVATE_INTERRUPT")

    def fail_observation(_process, _process_id):
        raise primary

    api._process_observation = fail_observation
    api._job_accounting = lambda _job: (1, 1)

    with pytest.raises(failure_type) as caught:
        api.job_observations(object())

    assert caught.value is primary
    assert ids_calls == [None]
    assert api.kernel.closed == [79]


@pytest.mark.parametrize("raises_private", [False, True])
def test_job_observation_keeps_other_open_failures_fatal(
    monkeypatch, raises_private
) -> None:
    class _ProcessIds(ctypes.Structure):
        _fields_ = [
            ("NumberOfAssignedProcesses", ctypes.c_uint32),
            ("NumberOfProcessIdsInList", ctypes.c_uint32),
            ("ProcessIdList", ctypes.c_size_t * 16),
        ]

    class _Kernel:
        def QueryInformationJobObject(self, _job, _kind, value, _size, _returned):
            info = ctypes.cast(value, ctypes.POINTER(_ProcessIds)).contents
            info.NumberOfAssignedProcesses = 1
            info.NumberOfProcessIdsInList = 1
            info.ProcessIdList[0] = 405
            return 1

        def OpenProcess(self, *_arguments):
            if raises_private:
                raise OSError("PRIVATE_OPEN_PROCESS_DETAIL")
            return 0

    api = object.__new__(qualification._WindowsApi)
    api.wintypes = _TokenWinTypes
    api.PROCESS_IDS = _ProcessIds
    api.kernel = _Kernel()
    monkeypatch.setattr(
        qualification.ctypes,
        "get_last_error",
        lambda: 5,
        raising=False,
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        api.job_observations(object())
    assert caught.value.qualification_reason == "native_open_process_unavailable"
    assert "PRIVATE" not in str(caught.value)


def test_job_observation_keeps_pid_listed_after_open_failure_fatal(monkeypatch) -> None:
    class _ProcessIds(ctypes.Structure):
        _fields_ = [
            ("NumberOfAssignedProcesses", ctypes.c_uint32),
            ("NumberOfProcessIdsInList", ctypes.c_uint32),
            ("ProcessIdList", ctypes.c_size_t * 16),
        ]

    class _Kernel:
        def QueryInformationJobObject(self, _job, _kind, value, _size, _returned):
            info = ctypes.cast(value, ctypes.POINTER(_ProcessIds)).contents
            info.NumberOfAssignedProcesses = 1
            info.NumberOfProcessIdsInList = 1
            info.ProcessIdList[0] = 406
            return 1

        def OpenProcess(self, *_arguments):
            return 0

    api = object.__new__(qualification._WindowsApi)
    api.wintypes = _TokenWinTypes
    api.PROCESS_IDS = _ProcessIds
    api.kernel = _Kernel()
    monkeypatch.setattr(
        qualification.ctypes,
        "get_last_error",
        lambda: qualification.WINDOWS_ERROR_INVALID_PARAMETER,
        raising=False,
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        api.job_observations(object())
    assert caught.value.qualification_reason == "native_open_process_unavailable"


@pytest.mark.parametrize(
    ("failing_call", "reason"),
    [
        ("image", "native_image_query_unavailable"),
        ("times", "native_process_times_unavailable"),
    ],
)
@pytest.mark.parametrize("raises_private", [False, True])
def test_native_process_observation_names_only_failing_api(
    failing_call, reason, raises_private
) -> None:
    class _FileTime(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", ctypes.c_uint32),
            ("dwHighDateTime", ctypes.c_uint32),
        ]

    class _Kernel:
        def QueryFullProcessImageNameW(self, *_arguments):
            if failing_call == "image" and raises_private:
                raise OSError("PRIVATE_IMAGE_QUERY_DETAIL")
            return failing_call != "image"

        def GetProcessTimes(self, *_arguments):
            if failing_call == "times" and raises_private:
                raise OSError("PRIVATE_PROCESS_TIME_DETAIL")
            return failing_call != "times"

    api = object.__new__(qualification._WindowsApi)
    api.wintypes = _TokenWinTypes
    api.FILETIME = _FileTime
    api.kernel = _Kernel()

    with pytest.raises(qualification.QualificationFailure) as caught:
        api._process_observation(object(), 123)
    assert caught.value.failure_id == "scenario_failed"
    assert caught.value.qualification_reason == reason
    assert "PRIVATE" not in str(caught.value)


def _fallback_identity_api(monkeypatch, *, process_image=None, file_image=None):
    expected = Path(r"C:\package\metroliza_application.exe")
    native = r"\Device\HarddiskVolume7\package\metroliza_application.exe"
    calls = []
    process_image = native if process_image is None else process_image
    file_image = native if file_image is None else file_image

    class _FileTime(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", ctypes.c_uint32),
            ("dwHighDateTime", ctypes.c_uint32),
        ]

    class _Kernel:
        def K32GetProcessImageFileNameW(self, handle, buffer, capacity):
            assert handle == 77 and capacity == len(buffer)
            calls.append("k32")
            buffer.value = process_image
            return len(process_image)

        def CreateFileW(self, path, access, share, security, disposition, flags, template):
            assert (path, access, share, security, disposition, flags, template) == (
                str(expected), 0, 7, None, 3, 0x80, None
            )
            calls.append("open")
            return 91

        def GetFinalPathNameByHandleW(self, handle, buffer, capacity, flags):
            assert (handle, capacity) == (91, len(buffer))
            assert flags in (2, 10)
            calls.append("file_name_opened" if flags == 10 else "file_name")
            buffer.value = file_image
            return len(file_image)

        def CloseHandle(self, handle):
            assert handle == 91
            calls.append("close")
            return 1

        def GetProcessTimes(self, handle, created, _exited, _kernel, _user):
            assert handle == 77
            calls.append("times")
            ctypes.cast(created, ctypes.POINTER(_FileTime)).contents.dwLowDateTime = 1234
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    api.FILETIME = _FileTime
    api.wintypes = _TokenWinTypes
    primary = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        native_observation=qualification._NativeIdentityObservation(
            None, "image", "false", 5, "alive"
        ),
    )

    def fail_win32(_handle, _pid):
        raise primary

    api._process_observation = fail_win32
    monkeypatch.setattr(qualification.ctypes, "set_last_error", lambda _code: None, raising=False)
    monkeypatch.setattr(qualification.ctypes, "get_last_error", lambda: 5, raising=False)
    return api, expected, primary, calls


def test_native_fallback_binds_fresh_process_and_opened_expected_file(monkeypatch):
    api, expected, _primary, calls = _fallback_identity_api(monkeypatch)
    observed = api._observe_job_member(77, 407, (expected,))
    assert observed == qualification._ProcessObservation(407, 1234, str(expected))
    assert calls == ["k32", "open", "file_name", "close", "times"]


@pytest.mark.parametrize("opened_matches", (True, False))
def test_native_fallback_checks_opened_name_on_normalized_mismatch(
    monkeypatch, opened_matches
):
    api, expected, primary, calls = _fallback_identity_api(monkeypatch)
    native = r"\Device\HarddiskVolume7\package\metroliza_application.exe"
    normalized = r"\Device\HarddiskVolume7\resolved\metroliza_application.exe"
    wrong_opened = r"\Device\HarddiskVolume7\other\metroliza_application.exe"

    def file_name(handle, buffer, capacity, flags):
        assert (handle, capacity) == (91, len(buffer))
        assert flags in (2, 10)
        calls.append("file_name_opened" if flags == 10 else "file_name")
        value = normalized if flags == 2 else native if opened_matches else wrong_opened
        buffer.value = value
        return len(value)

    api.kernel.GetFinalPathNameByHandleW = file_name
    if opened_matches:
        observed = api._observe_job_member(77, 407, (expected,))
        assert observed == qualification._ProcessObservation(407, 1234, str(expected))
        assert calls == [
            "k32", "open", "file_name", "file_name_opened", "close", "times",
        ]
    else:
        with pytest.raises(qualification.QualificationFailure) as caught:
            api._observe_job_member(77, 407, (expected,))
        assert caught.value is primary
        assert primary.native_observation.alternative.receipt() == {
            "api": "image_match", "outcome": "mismatch", "winerror": None,
        }
        assert calls == ["k32", "open", "file_name", "file_name_opened", "close"]


@pytest.mark.parametrize(("copied", "outcome"), ((0, "false"), (32768, "invalid_result")))
def test_native_fallback_opened_name_query_failure_keeps_primary_and_closes_file(
    monkeypatch, copied, outcome
):
    api, expected, primary, calls = _fallback_identity_api(monkeypatch)
    native = r"\Device\HarddiskVolume7\resolved\metroliza_application.exe"

    def file_name(handle, buffer, capacity, flags):
        assert (handle, capacity) == (91, len(buffer))
        calls.append("file_name_opened" if flags == 10 else "file_name")
        if flags == 10:
            return copied
        assert flags == 2
        buffer.value = native
        return len(native)

    api.kernel.GetFinalPathNameByHandleW = file_name
    with pytest.raises(qualification.QualificationFailure) as caught:
        api._observe_job_member(77, 407, (expected,))
    assert caught.value is primary
    assert primary.native_observation.alternative.receipt() == {
        "api": "expected_file_name", "outcome": outcome,
        "winerror": 5 if copied == 0 else None,
    }
    assert calls == ["k32", "open", "file_name", "file_name_opened", "close"]


def test_native_fallback_wrong_image_preserves_original_failure(monkeypatch):
    api, expected, primary, calls = _fallback_identity_api(
        monkeypatch, process_image=r"\Device\HarddiskVolume7\other.exe"
    )
    with pytest.raises(qualification.QualificationFailure) as caught:
        api._observe_job_member(77, 407, (expected,))
    assert caught.value is primary
    assert primary.native_observation.alternative.receipt() == {
        "api": "image_match", "outcome": "mismatch", "winerror": None,
    }
    assert calls == ["k32", "open", "file_name", "file_name_opened", "close"]


def test_native_fallback_applies_to_other_owned_job_member(monkeypatch):
    api, expected, _primary, calls = _fallback_identity_api(monkeypatch)
    api.kernel.OpenProcess = lambda access, inherit, pid: (
        77 if (access, inherit, pid) == (0x1000, False, 407) else 0
    )
    original_close = api.kernel.CloseHandle

    def close(handle):
        if handle == 77:
            calls.append("close_process")
            return 1
        return original_close(handle)

    api.kernel.CloseHandle = close
    api._job_process_ids = lambda _job: (407,)
    api._job_accounting = lambda _job: (1, 1)
    observations, active, total = api.job_observations(
        object(), expected_images=(expected,)
    )
    assert observations == (
        qualification._ProcessObservation(407, 1234, str(expected)),
    )
    assert (active, total) == (1, 1)
    assert calls == ["k32", "open", "file_name", "close", "times", "close_process"]


@pytest.mark.parametrize("drift", (None, "native_image", "creation"))
def test_owned_primary_uses_immutable_suspended_native_anchor_not_reopened_file(
    monkeypatch, drift
):
    wrong_file = r"\Device\HarddiskVolume7\other\metroliza_application.exe"
    api, expected, _primary, calls = _fallback_identity_api(
        monkeypatch, file_image=wrong_file
    )
    native = r"\Device\HarddiskVolume7\package\metroliza_application.exe"
    initial = qualification._ProcessObservation(
        407, 1234 + (drift == "creation"), str(expected)
    )
    api._job_process_ids = lambda _job: (407,)
    api._job_accounting = lambda _job: (1, 1)
    anchor = native if drift != "native_image" else wrong_file

    if drift is None:
        assert api.job_observations(
            object(), primary_process=77, primary_initial=initial,
            primary_native_image=anchor, expected_images=(expected,),
        ) == ((initial,), 1, 1)
        assert calls == ["k32", "times"]
    else:
        with pytest.raises(qualification.QualificationFailure) as caught:
            api.job_observations(
                object(), primary_process=77, primary_initial=initial,
                primary_native_image=anchor, expected_images=(expected,),
            )
        assert caught.value.qualification_reason == "native_primary_identity_mismatch"
        assert caught.value.native_observation is None
        assert calls == (["k32"] if drift == "native_image" else ["k32", "times"])


@pytest.mark.parametrize("anchor", (None, "", r"C:\invalid\image.exe"))
def test_owned_primary_rejects_missing_or_invalid_native_anchor(anchor):
    api = object.__new__(qualification._WindowsApi)
    api._job_process_ids = lambda _job: pytest.fail("invalid anchor reached Job query")
    initial = qualification._ProcessObservation(
        407, 1234, r"C:\package\metroliza_application.exe"
    )
    with pytest.raises(qualification.QualificationFailure) as caught:
        api.job_observations(
            object(), primary_process=77, primary_initial=initial,
            primary_native_image=anchor, expected_images=(Path(initial.image),),
        )
    assert caught.value.qualification_reason == "native_image_query_unavailable"
    assert caught.value.native_observation is None


def test_owned_primary_fresh_native_failure_preserves_image5_and_no_file_open(
    monkeypatch,
):
    api, expected, primary, calls = _fallback_identity_api(monkeypatch)
    initial = qualification._ProcessObservation(407, 1234, str(expected))
    api._job_process_ids = lambda _job: (407,)
    api._job_accounting = lambda _job: (1, 1)
    api.kernel.K32GetProcessImageFileNameW = lambda *_args: calls.append("k32") or 0

    with pytest.raises(qualification.QualificationFailure) as caught:
        api.job_observations(
            object(), primary_process=77, primary_initial=initial,
            primary_native_image=TEST_NATIVE_ANCHOR,
            expected_images=(expected,),
        )
    assert caught.value is primary
    assert primary.native_observation.phase == "owned_job_observation"
    assert primary.native_observation.alternative.receipt() == {
        "api": "k32_image", "outcome": "false", "winerror": 5,
    }
    assert calls == ["k32"]


@pytest.mark.parametrize("still_listed", (False, True))
def test_other_member_native_fallback_times_failure_keeps_job_disappearance_rule(
    monkeypatch, still_listed
):
    api, expected, _primary, calls = _fallback_identity_api(monkeypatch)
    snapshots = []

    def ids(_job):
        snapshots.append(None)
        return (407,) if len(snapshots) == 1 or still_listed else ()

    api._job_process_ids = ids
    api._job_accounting = lambda _job: (0, 1)
    api.kernel.OpenProcess = lambda _access, _inherit, _pid: 77
    original_close = api.kernel.CloseHandle

    def close(handle):
        if handle == 77:
            calls.append("close_process")
            return 1
        return original_close(handle)

    api.kernel.CloseHandle = close
    api.kernel.GetProcessTimes = lambda *_args: calls.append("times") or 0
    if still_listed:
        with pytest.raises(qualification.QualificationFailure) as caught:
            api.job_observations(
                object(), expected_images=(expected,),
            )
        assert caught.value.qualification_reason == "native_process_times_unavailable"
        assert caught.value.native_observation.api == "times"
        assert caught.value.native_observation.winerror == 5
        assert caught.value.native_observation.phase == "job_observation"
    else:
        assert api.job_observations(
            object(), expected_images=(expected,),
        ) == ((), 0, 1)
    assert len(snapshots) == 2
    assert calls == [
        "k32", "open", "file_name", "close", "times", "close_process",
    ]


def test_native_fallback_closes_file_if_buffer_allocation_interrupts(monkeypatch):
    api, expected, primary, calls = _fallback_identity_api(monkeypatch)
    interrupt = KeyboardInterrupt("PRIVATE_INTERRUPT")
    original_buffer = qualification.ctypes.create_unicode_buffer
    allocations = []

    def fail_second_allocation(*args):
        allocations.append(None)
        if len(allocations) == 2:
            raise interrupt
        return original_buffer(*args)

    monkeypatch.setattr(qualification.ctypes, "create_unicode_buffer", fail_second_allocation)
    with pytest.raises(KeyboardInterrupt) as caught:
        api._observe_job_member(77, 407, (expected,))
    assert caught.value is interrupt
    assert calls == ["k32", "open", "close"]
    assert primary.qualification_cleanup == "not_attempted"


@pytest.mark.parametrize("interrupt_type", (KeyboardInterrupt, SystemExit))
def test_native_fallback_closes_file_if_handle_check_interrupts(
    monkeypatch, interrupt_type
):
    api, expected, _primary, calls = _fallback_identity_api(monkeypatch)
    interrupt = interrupt_type("PRIVATE_HANDLE_CHECK")
    valid = api._valid_file_handle
    attempts = []

    def interrupted_check(handle):
        attempts.append(None)
        if len(attempts) == 1:
            raise interrupt
        return valid(handle)

    api._valid_file_handle = interrupted_check
    with pytest.raises(interrupt_type) as caught:
        api._observe_job_member(77, 407, (expected,))
    assert caught.value is interrupt
    assert calls == ["k32", "open", "close"]


@pytest.mark.parametrize("interrupt_type", (KeyboardInterrupt, SystemExit))
def test_native_fallback_interrupted_invalid_handle_is_not_closed(
    monkeypatch, interrupt_type
):
    api, expected, _primary, calls = _fallback_identity_api(monkeypatch)
    interrupt = interrupt_type("PRIVATE_HANDLE_CHECK")
    api.kernel.CreateFileW = lambda *_args: -1
    api._valid_file_handle = lambda _handle: (_ for _ in ()).throw(interrupt)

    def unexpected_close(_handle):
        pytest.fail("invalid handle must not be closed")

    api.kernel.CloseHandle = unexpected_close
    with pytest.raises(interrupt_type) as caught:
        api._observe_job_member(77, 407, (expected,))
    assert caught.value is interrupt
    assert calls == ["k32"]


@pytest.mark.parametrize("interrupt_type", (KeyboardInterrupt, SystemExit))
def test_native_fallback_never_revalidates_acquired_handle_in_finally(
    monkeypatch, interrupt_type
):
    api, expected, _primary, calls = _fallback_identity_api(monkeypatch)
    original_check = api._valid_file_handle
    checks = []

    def check_once(handle):
        checks.append(None)
        if len(checks) > 1:
            raise interrupt_type("PRIVATE_FINAL_CHECK")
        return original_check(handle)

    api._valid_file_handle = check_once
    observed = api._observe_job_member(77, 407, (expected,))
    assert observed == qualification._ProcessObservation(407, 1234, str(expected))
    assert len(checks) == 1
    assert calls == ["k32", "open", "file_name", "close", "times"]


def test_native_fallback_never_closes_definitively_invalid_file_handle(monkeypatch):
    api, expected, primary, calls = _fallback_identity_api(monkeypatch)
    api.kernel.CreateFileW = lambda *_args: -1

    def unexpected_close(_handle):
        pytest.fail("invalid handle must not be closed")

    api.kernel.CloseHandle = unexpected_close
    with pytest.raises(qualification.QualificationFailure) as caught:
        api._observe_job_member(77, 407, (expected,))
    assert caught.value is primary
    assert primary.native_observation.alternative.api == "expected_file_open"
    assert primary.native_observation.alternative.outcome == "false"
    assert calls == ["k32"]


def test_native_fallback_close_interrupt_keeps_primary_interrupt(monkeypatch):
    api, expected, _primary, calls = _fallback_identity_api(monkeypatch)
    interrupt = KeyboardInterrupt("PRIVATE_BUFFER_INTERRUPT")
    secondary = SystemExit("PRIVATE_CLOSE_INTERRUPT")
    original_buffer = qualification.ctypes.create_unicode_buffer
    allocations = []

    def fail_second_allocation(*args):
        allocations.append(None)
        if len(allocations) == 2:
            raise interrupt
        return original_buffer(*args)

    def fail_close(handle):
        calls.append("close")
        raise secondary

    api.kernel.CloseHandle = fail_close
    monkeypatch.setattr(qualification.ctypes, "create_unicode_buffer", fail_second_allocation)
    with pytest.raises(KeyboardInterrupt) as caught:
        api._observe_job_member(77, 407, (expected,))
    assert caught.value is interrupt
    assert calls == ["k32", "open", "close"]


@pytest.mark.parametrize(
    ("failure", "api_name", "outcome", "file_closed"),
    [
        ("k32_false", "k32_image", "false", False),
        ("k32_truncated", "k32_image", "invalid_result", False),
        ("file_open_false", "expected_file_open", "false", False),
        ("file_name_false", "expected_file_name", "false", True),
        ("file_name_truncated", "expected_file_name", "invalid_result", True),
        ("file_close_false", "expected_file_close", "false", True),
    ],
)
def test_native_fallback_preserves_original_and_closed_alternate(
    monkeypatch, failure, api_name, outcome, file_closed
):
    api, expected, primary, calls = _fallback_identity_api(monkeypatch)
    if failure.startswith("k32"):
        api.kernel.K32GetProcessImageFileNameW = (
            lambda *_args: 0 if failure == "k32_false" else 32768
        )
    elif failure == "file_open_false":
        api.kernel.CreateFileW = lambda *_args: 0
    elif failure.startswith("file_name"):
        api.kernel.GetFinalPathNameByHandleW = (
            lambda *_args: 0 if failure == "file_name_false" else 32768
        )
    else:
        api.kernel.CloseHandle = lambda handle: calls.append("close") or 0

    with pytest.raises(qualification.QualificationFailure) as caught:
        api._observe_job_member(77, 407, (expected,))

    assert caught.value is primary
    alternate = primary.native_observation.alternative
    assert (alternate.api, alternate.outcome) == (api_name, outcome)
    assert alternate.winerror == (5 if outcome == "false" else None)
    assert ("close" in calls) is file_closed
    assert "times" not in calls
    assert primary.qualification_cleanup == (
        "failed" if failure == "file_close_false" else "not_attempted"
    )


@pytest.mark.parametrize("kind", ("wrong_image", "failed_close"))
def test_native_fallback_mismatch_is_never_forgiven_by_job_disappearance(kind):
    api = object.__new__(qualification._WindowsApi)
    pid = 407
    snapshots = []

    def ids(_job):
        snapshots.append(None)
        return (pid,) if len(snapshots) == 1 else ()

    api._job_process_ids = ids
    api._job_accounting = lambda _job: (0, 1)
    initial = qualification._ProcessObservation(
        pid, 1234, r"C:\package\metroliza_application.exe"
    )
    original = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        qualification_cleanup="failed" if kind == "failed_close" else "not_attempted",
        native_observation=qualification._NativeIdentityObservation(
            None, "image", "false", 5, "alive",
            qualification._NativeAlternativeObservation(
                "expected_file_close" if kind == "failed_close" else "image_match",
                "false" if kind == "failed_close" else "mismatch",
                5 if kind == "failed_close" else None,
            ),
        ),
    )

    def fail(*_args):
        raise original

    class _Kernel:
        closed = []

        def OpenProcess(self, _access, _inherit, observed_pid):
            assert observed_pid == pid
            return 77

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return 1

    api.kernel = _Kernel()
    api._observe_job_member = fail
    with pytest.raises(qualification.QualificationFailure) as caught:
        api.job_observations(
            object(), expected_images=(Path(initial.image),),
        )
    assert caught.value is original
    assert len(snapshots) == 1
    assert original.native_observation.phase == "job_observation"
    assert api.kernel.closed == [77]


@pytest.mark.parametrize("still_listed", (False, True))
def test_native_k32_false_requires_fresh_proven_job_disappearance(still_listed):
    api = object.__new__(qualification._WindowsApi)
    initial = qualification._ProcessObservation(
        407, 1234, r"C:\package\metroliza_application.exe"
    )
    snapshots = []

    def ids(_job):
        snapshots.append(None)
        return (407,) if len(snapshots) == 1 or still_listed else ()

    api._job_process_ids = ids
    api._job_accounting = lambda _job: (0, 1)
    original = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        native_observation=qualification._NativeIdentityObservation(
            None, "image", "false", 5, "exited",
            qualification._NativeAlternativeObservation("k32_image", "false", 5),
        ),
    )

    def fail(*_args):
        raise original

    api._observe_owned_primary = fail
    if still_listed:
        with pytest.raises(qualification.QualificationFailure) as caught:
            api.job_observations(
                object(), primary_process=77, primary_initial=initial,
                primary_native_image=TEST_NATIVE_ANCHOR,
                expected_images=(Path(initial.image),),
            )
        assert caught.value is original
    else:
        assert api.job_observations(
            object(), primary_process=77, primary_initial=initial,
            primary_native_image=TEST_NATIVE_ANCHOR,
            expected_images=(Path(initial.image),),
        ) == ((), 0, 1)
    assert len(snapshots) == 2


@pytest.mark.parametrize("observed", (
    r"c:\fixed\APPLICATION.exe", r"\\?\C:\fixed\application.exe"
))
def test_owned_identity_accepts_only_canonical_dos_spelling(observed):
    initial = qualification._ProcessObservation(
        407, 1234, r"C:\FIXED\application.exe"
    )
    api = object.__new__(qualification._WindowsApi)
    api._job_process_ids = lambda _job: (407,)
    api._job_accounting = lambda _job: (1, 1)
    api._process_observation = lambda *_args: qualification._ProcessObservation(
        407, 1234, observed
    )
    observations, active, total = api.job_observations(
        object(), primary_process=77, primary_initial=initial,
        primary_native_image=TEST_NATIVE_ANCHOR,
    )
    assert (active, total) == (1, 1)
    assert observations[0].image == observed


@pytest.mark.parametrize("observed", (
    r"C:\elsewhere\application.exe",
    r"\FIXED\application.exe",
    r"FIXED\application.exe",
    r"\\host\share\application.exe",
    r"\\?\UNC\host\share\application.exe",
    r"\Device\HarddiskVolume7\application.exe",
))
def test_requested_image_rejects_other_or_non_drive_paths(observed):
    assert not qualification._WindowsApi._same_requested_image(
        observed, Path(r"C:\FIXED\application.exe")
    )


@pytest.mark.parametrize(
    ("wait_result", "state"), [(0, "exited"), (258, "alive"), (0xFFFFFFFF, "unknown")]
)
@pytest.mark.parametrize("api_name", ["image", "times"])
def test_native_identity_captures_primary_error_before_state_query(
    monkeypatch, wait_result, state, api_name
) -> None:
    last_error = [999]
    calls = []

    class _Kernel:
        def WaitForSingleObject(self, process, timeout):
            assert process is process_handle and timeout == 0
            calls.append("state")
            last_error[0] = 1234  # Secondary observation must not replace the error.
            return wait_result

    def query():
        assert last_error[0] == 0
        calls.append("query")
        last_error[0] = 5
        return 0

    def read_error():
        calls.append("error")
        return last_error[0]

    monkeypatch.setattr(ctypes, "set_last_error", lambda code: last_error.__setitem__(0, code), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", read_error, raising=False)
    process_handle = object()
    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    with pytest.raises(qualification.QualificationFailure) as caught:
        api._identity_call(process_handle, api_name, query)
    detail = caught.value.native_observation
    assert detail.winerror == 5
    assert detail.api == api_name and detail.outcome == "false"
    assert detail.process_state == state
    assert calls == ["query", "error", "state"]


def test_native_identity_keeps_original_failure_if_state_probe_raises(monkeypatch) -> None:
    class _Kernel:
        def WaitForSingleObject(self, *_args):
            raise OSError("PRIVATE_STATE_DETAIL")

    monkeypatch.setattr(ctypes, "set_last_error", lambda _code: None, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 6, raising=False)
    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    with pytest.raises(qualification.QualificationFailure) as caught:
        api._identity_call(object(), "image", lambda: 0)
    assert caught.value.qualification_reason == "native_image_query_unavailable"
    assert caught.value.native_observation.winerror == 6
    assert caught.value.native_observation.process_state == "unknown"
    assert "PRIVATE" not in str(caught.value)


def test_native_identity_launch_phase_precedes_resume_and_survives_cleanup(
    tmp_path, monkeypatch
) -> None:
    closed = []
    api = _fake_launch_api(tmp_path, monkeypatch, _LaunchTransferKernel(closed))
    primary = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        native_observation=qualification._NativeIdentityObservation(
            None, "image", "false", 31, "alive"
        ),
    )

    def fail(*_args):
        raise primary

    api._process_observation = fail
    api.kernel.ResumeThread = lambda _thread: pytest.fail("Failed identity must not resume")
    with pytest.raises(qualification.QualificationFailure) as caught:
        api.launch(tmp_path / "app.exe", {}, tmp_path)
    assert caught.value is primary
    assert primary.native_observation.phase == "pre_resume"
    assert primary.native_observation.winerror == 31
    assert primary.qualification_cleanup == "complete"
    assert closed == ["thread", "process", "job", "token"]


def test_native_identity_job_phase_stays_fatal_when_process_remains_listed() -> None:
    closed = []

    class _Kernel:
        def OpenProcess(self, *_args):
            return 77

        def CloseHandle(self, handle):
            closed.append(handle)
            return 1

    primary = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        native_observation=qualification._NativeIdentityObservation(
            None, "image", "false", 5, "unknown"
        ),
    )
    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    api._job_process_ids = lambda _job: (407,)

    def fail(*_args):
        raise primary

    api._process_observation = fail
    with pytest.raises(qualification.QualificationFailure) as caught:
        api.job_observations(object())
    assert caught.value is primary
    assert primary.native_observation.phase == "job_observation"
    assert primary.native_observation.process_state == "unknown"
    assert closed == [77]


def test_native_identity_exception_does_not_report_stale_last_error(monkeypatch) -> None:
    class _Kernel:
        def WaitForSingleObject(self, *_args):
            return 258

    def query():
        raise OSError("PRIVATE_IMAGE_DETAIL")

    def stale_error():
        pytest.fail("A Python exception has no reliable failed-BOOL last error")

    monkeypatch.setattr(ctypes, "set_last_error", lambda _code: None, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", stale_error, raising=False)
    api = object.__new__(qualification._WindowsApi)
    api.kernel = _Kernel()
    with pytest.raises(qualification.QualificationFailure) as caught:
        api._identity_call(object(), "image", query)
    assert caught.value.native_observation.winerror is None
    assert caught.value.native_observation.outcome == "exception"
    assert caught.value.native_observation.process_state == "alive"
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_native_identity_survives_phase_cleanup_and_public_receipt(
    tmp_path, monkeypatch, cleanup_fails
) -> None:
    observation = qualification._NativeIdentityObservation(
        "pre_resume", "image", "false", 31, "alive"
    )
    primary = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        native_observation=observation,
    )

    def cleanup():
        if cleanup_fails:
            raise OSError("PRIVATE_CLEANUP_DETAIL")

    def fail():
        try:
            raise primary
        finally:
            qualification._attempt_cleanup(cleanup)

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._run_driver_phase("direct_ui_smoke", fail)
    failure = caught.value
    assert failure.native_observation == observation
    assert failure.qualification_reason == primary.qualification_reason
    result = qualification.QualificationResult(
        "failed", failure.failure_id, None,
        qualification_stage=failure.qualification_stage,
        qualification_reason=failure.qualification_reason,
        qualification_cleanup=failure.qualification_cleanup,
        native_observation=failure.native_observation,
    )
    monkeypatch.setattr(qualification, "qualify_windows_diagnostics", lambda *_args: result)
    output = tmp_path / "out"
    assert qualification.main([
        "--artifact-dir", str(tmp_path / "package"), "--output-dir", str(output)
    ]) == 1
    raw = (output / qualification.OUTPUT_NAME).read_bytes()
    receipt = json.loads(raw)
    qualification._validate_output_payload(receipt)
    assert receipt["qualification_failure"]["native_observation"] == {
        "phase": "pre_resume", "api": "image", "outcome": "false",
        "winerror": 31, "process_state": "alive",
    }
    assert receipt["qualification_cleanup"] == ("failed" if cleanup_fails else "complete")
    assert b"PRIVATE" not in raw and b"package" not in json.dumps(
        receipt["qualification_failure"]
    ).encode()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [("phase", "PRIVATE_PATH"), ("api", "PRIVATE_API"), ("outcome", "success"),
     ("process_state", "PRIVATE_STATE"), ("winerror", True), ("winerror", -1),
     ("winerror", 2**32), ("winerror", "5"), ("pid", 123), ("path", "PRIVATE_PATH")],
)
def test_native_identity_receipt_rejects_unbounded_or_misleading_fields(field, invalid):
    detail = {
        "stage": "direct_ui_smoke", "reason": "native_image_query_unavailable",
        "native_observation": {
            "phase": "job_observation", "api": "image", "outcome": "false",
            "winerror": 5, "process_state": "unknown",
        },
    }
    assert qualification._valid_failure_detail(detail)
    detail["native_observation"][field] = invalid
    assert not qualification._valid_failure_detail(detail)


def test_owned_job_identity_failure_receipt_accepts_only_closed_phase_and_reason():
    detail = {
        "stage": "direct_ui_smoke", "reason": "native_image_query_unavailable",
        "native_observation": {
            "phase": "owned_job_observation", "api": "image", "outcome": "false",
            "winerror": 5, "process_state": "unknown",
        },
    }
    assert qualification._valid_failure_detail(detail)
    detail["reason"] = "native_primary_identity_mismatch"
    assert not qualification._valid_failure_detail(detail)
    detail.pop("native_observation")
    assert qualification._valid_failure_detail(detail)
    detail["private_image"] = "PRIVATE_PATH"
    assert not qualification._valid_failure_detail(detail)


def test_native_fallback_failure_receipt_keeps_original_and_closed_alternative():
    detail = {
        "stage": "direct_ui_smoke", "reason": "native_image_query_unavailable",
        "native_observation": {
            "phase": "owned_job_observation", "api": "image", "outcome": "false",
            "winerror": 5, "process_state": "alive",
            "alternative": {
                "api": "expected_file_name", "outcome": "false", "winerror": 5,
            },
        },
    }
    assert qualification._valid_failure_detail(detail)
    for changed in (
        {"api": "image_match", "outcome": "false", "winerror": 5},
        {"api": "expected_file_name", "outcome": "mismatch", "winerror": None},
        {"api": "expected_file_name", "outcome": "false", "winerror": 5,
         "private_path": r"C:\PRIVATE"},
    ):
        rejected = json.loads(json.dumps(detail))
        rejected["native_observation"]["alternative"] = changed
        assert not qualification._valid_failure_detail(rejected)
    for phase, code in (("pre_resume", 5), ("owned_job_observation", 6)):
        rejected = json.loads(json.dumps(detail))
        rejected["native_observation"]["phase"] = phase
        rejected["native_observation"]["winerror"] = code
        assert not qualification._valid_failure_detail(rejected)


@pytest.mark.parametrize("cleanup", ["complete", "failed"])
def test_identity_probe_preserves_control_failure_and_bounds_application_attempt(
    tmp_path, monkeypatch, cleanup
) -> None:
    calls = []
    primary = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        qualification_cleanup=cleanup,
        native_observation=qualification._NativeIdentityObservation(
            "pre_resume", "image", "false", 31, "alive"
        ),
    )

    def control(*_args):
        calls.append("control")
        raise primary

    monkeypatch.setattr(qualification, "_validate_identity_control_executable", lambda path: path)
    monkeypatch.setattr(qualification, "_run_native_identity_controls", control)
    monkeypatch.setattr(qualification, "_run_identity_application", lambda *_args: calls.append("app"))
    payload = qualification._identity_control_payload(tmp_path, tmp_path / "fixed.exe", 123)
    qualification._validate_identity_control_payload(payload)
    assert payload["status"] == "failed"
    assert payload["failure"]["native_observation"]["winerror"] == 31
    assert payload["failure"]["native_observation"]["phase"] == "pre_resume"
    assert payload["cleanup"] == cleanup
    assert calls == (["control", "app"] if cleanup == "complete" else ["control"])
    assert payload["application"]["status"] == ("passed" if cleanup == "complete" else "not_run")


def test_identity_cli_never_runs_full_qualification(tmp_path, monkeypatch) -> None:
    calls = []

    def control(artifact, output, executable):
        calls.append((artifact, output, executable))
        return 1

    monkeypatch.setattr(qualification, "run_identity_control", control)
    monkeypatch.setattr(qualification, "qualify_windows_diagnostics", lambda *_args: pytest.fail("Full qualification forbidden in identity mode"))
    artifact, output, executable = [tmp_path / name for name in ("package", "output", "control.exe")]
    assert qualification.main([
        "--artifact-dir", str(artifact), "--output-dir", str(output),
        "--identity-control-executable", str(executable),
    ]) == 1
    assert calls == [(artifact, output, executable)]


@pytest.mark.parametrize(
    ("reason", "api", "outcome", "code"),
    [("process_exit_timeout", "image", "false", 5),
     ("native_process_times_unavailable", "image", "false", 5),
     ("native_image_query_unavailable", "times", "false", 5),
     ("native_image_query_unavailable", "image", "exception", 5)],
)
def test_native_identity_failure_detail_rejects_inconsistent_attribution(reason, api, outcome, code):
    assert not qualification._valid_failure_detail({
        "stage": "direct_ui_smoke", "reason": reason,
        "native_observation": {
            "phase": "pre_resume", "api": api, "outcome": outcome,
            "winerror": code, "process_state": "alive",
        },
    })


@pytest.mark.parametrize(
    ("check_id", "state", "image_result", "code"),
    [("invalid_handle", "alive", "unavailable", 6),
     ("invalid_handle", "unknown", "unavailable", 5),
     ("denied_handle", "alive", "matched", 5),
     ("denied_handle", "alive", "unavailable", 6),
     ("pre_resume", "unknown", "matched", None),
     ("retired", "alive", "matched", None),
     ("wrong_image", "alive", "matched", None)],
)
def test_native_identity_control_cannot_validate_false_positive(check_id, state, image_result, code):
    assert not qualification._valid_identity_control_check({
        "id": check_id, "status": "passed", "process_state": state,
        "image_result": image_result, "winerror": code,
    })


@pytest.mark.parametrize("application_fails", [False, True])
def test_identity_probe_complete_controls_then_exact_application_receipt(
    tmp_path, monkeypatch, application_fails
) -> None:
    expected_checks = [
        {"id": check_id, "status": "passed", "process_state": state,
         "image_result": image_result, "winerror": code}
        for check_id, state, image_result, code in [
            ("pre_resume", "alive", "matched", None),
            ("retired", "exited", "matched", None),
            ("sleeper_pre_resume", "alive", "matched", None),
            ("resumed_live", "alive", "matched", None),
            ("invalid_handle", "unknown", "unavailable", 6),
            ("denied_handle", "alive", "unavailable", 5),
            ("wrong_image", "alive", "rejected", None),
        ]
    ]
    calls = []

    def control(_artifact, _executable, _deadline, checks):
        calls.append("control")
        checks.extend(expected_checks)

    def application(*_args):
        calls.append("app")
        if application_fails:
            raise qualification.QualificationFailure(
                "scenario_failed", qualification_stage="direct_ui_smoke",
                qualification_reason="native_image_query_unavailable",
                qualification_cleanup="complete",
                native_observation=qualification._NativeIdentityObservation(
                    "pre_resume", "image", "false", 31, "alive"
                ),
            )

    monkeypatch.setattr(qualification, "_validate_identity_control_executable", lambda path: path)
    monkeypatch.setattr(qualification, "_run_native_identity_controls", control)
    monkeypatch.setattr(qualification, "_run_identity_application", application)
    payload = qualification._identity_control_payload(tmp_path, tmp_path / "control.exe", 123)
    assert calls == ["control", "app"]
    assert payload["checks"] == expected_checks
    assert payload["failure"] is None
    assert payload["status"] == ("failed" if application_fails else "passed")
    assert payload["application"]["status"] == payload["status"]
    output = tmp_path / "bounded"
    output.mkdir()
    metadata = output.stat()
    result = qualification._write_identity_control_receipt(
        output, (metadata.st_dev, metadata.st_ino), payload
    )
    assert json.loads(result.read_bytes()) == payload
    assert sorted(path.name for path in output.iterdir()) == ["native-identity-control.json"]
    # An identity probe never creates or validates a full-qualification success receipt.
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_output_payload(payload)
    if application_fails:
        assert payload["application"]["qualification_failure"] == {
            "stage": "direct_ui_smoke", "reason": "native_image_query_unavailable",
            "native_observation": {
                "phase": "pre_resume", "api": "image", "outcome": "false",
                "winerror": 31, "process_state": "alive",
            },
        }


@pytest.mark.parametrize(
    ("api_name", "invalid", "reason"),
    [
        ("ids", False, "native_job_ids_unavailable"),
        ("ids", True, "native_job_ids_invalid"),
        ("accounting", False, "native_job_accounting_unavailable"),
        ("accounting", True, "native_job_accounting_invalid"),
    ],
)
@pytest.mark.parametrize("raises_private", [False, True])
def test_native_job_query_names_only_failing_api(
    api_name, invalid, reason, raises_private
) -> None:
    class _ProcessIds(ctypes.Structure):
        _fields_ = [
            ("NumberOfAssignedProcesses", ctypes.c_uint32),
            ("NumberOfProcessIdsInList", ctypes.c_uint32),
            ("ProcessIdList", ctypes.c_size_t * 16),
        ]

    class _Accounting(ctypes.Structure):
        _fields_ = [
            ("TotalProcesses", ctypes.c_uint32),
            ("ActiveProcesses", ctypes.c_uint32),
        ]

    class _Kernel:
        def QueryInformationJobObject(self, _job, kind, value, _size, _returned):
            if raises_private and not invalid:
                raise OSError("PRIVATE_JOB_QUERY_DETAIL")
            if not invalid:
                return False
            if kind == 3:
                info = ctypes.cast(value, ctypes.POINTER(_ProcessIds)).contents
                info.NumberOfAssignedProcesses = 1
                info.NumberOfProcessIdsInList = 0
            else:
                info = ctypes.cast(value, ctypes.POINTER(_Accounting)).contents
                info.TotalProcesses = 0
                info.ActiveProcesses = 1
            return True

    api = object.__new__(qualification._WindowsApi)
    api.wintypes = _TokenWinTypes
    api.PROCESS_IDS = _ProcessIds
    api.BASIC_ACCOUNTING = _Accounting
    api.kernel = _Kernel()
    action = api._job_process_ids if api_name == "ids" else api._job_accounting

    with pytest.raises(qualification.QualificationFailure) as caught:
        action(object())
    assert caught.value.failure_id == "scenario_failed"
    assert caught.value.qualification_reason == reason
    assert "PRIVATE" not in str(caught.value)


def test_normal_window_requires_exact_owned_application_and_revalidates_close(
    tmp_path,
) -> None:
    application = tmp_path / "metroliza_application.exe"
    title = "Metroliza [fixed]"
    api = _window_api(
        {
            100: _normal_window(41, title),
            200: _normal_window(99, title),
        }
    )
    observations = (
        qualification._ProcessObservation(41, 1, str(application)),
        qualification._ProcessObservation(99, 2, str(tmp_path / "foreign.exe")),
    )

    window = api.normal_window(observations, application, title)
    assert window == 100
    api.close_normal_window(observations, application, title, window)
    assert api.user.posted == [(100, qualification.WM_CLOSE, 0, 0)]


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("visible", False),
        ("enabled", False),
        ("owner", 500),
        ("style", qualification.WS_SYSMENU),
        ("style", qualification.NORMAL_WINDOW_REQUIRED_STYLE | qualification.WS_CHILD),
        ("extended_style", qualification.WS_EX_TOOLWINDOW),
        ("title", "PRIVATE_DIALOG_TITLE"),
        ("title", "Metroliza [fixed] suffix"),
        ("process_id", 99),
    ],
)
def test_normal_window_rejects_non_main_or_foreign_window(
    tmp_path, change, value
) -> None:
    application = tmp_path / "metroliza_application.exe"
    title = "Metroliza [fixed]"
    window = _normal_window(41, title)
    window[change] = value
    api = _window_api({100: window})
    observations = (
        qualification._ProcessObservation(41, 1, str(application)),
    )

    assert api.normal_window(observations, application, title) is None
    assert api.user.posted == []


def test_normal_window_rejects_ambiguity_reuse_and_post_failure(tmp_path) -> None:
    application = tmp_path / "metroliza_application.exe"
    title = "Metroliza [fixed]"
    observations = (
        qualification._ProcessObservation(41, 1, str(application)),
    )
    api = _window_api(
        {100: _normal_window(41, title), 101: _normal_window(41, title)}
    )
    with pytest.raises(qualification.QualificationFailure) as ambiguous:
        api.normal_window(observations, application, title)
    assert ambiguous.value.qualification_reason == "normal_window_ambiguous"

    api.user.windows.pop(101)
    matched = api.normal_window(observations, application, title)
    api.user.windows[100]["process_id"] = 99
    with pytest.raises(qualification.QualificationFailure) as reused:
        api.close_normal_window(observations, application, title, matched)
    assert reused.value.qualification_reason == "normal_window_invalid"
    assert api.user.posted == []

    api.user.windows[100]["process_id"] = 41
    api.user.windows[100]["enabled"] = False
    with pytest.raises(qualification.QualificationFailure) as disabled:
        api.close_normal_window(observations, application, title, matched)
    assert disabled.value.qualification_reason == "normal_window_invalid"
    assert api.user.posted == []

    api.user.windows[100]["enabled"] = True
    api.user.post_succeeds = False
    with pytest.raises(qualification.QualificationFailure) as post_failed:
        api.close_normal_window(observations, application, title, matched)
    assert post_failed.value.qualification_reason == "normal_window_close_failed"


@pytest.mark.parametrize("failure_type", [RuntimeError, KeyboardInterrupt])
def test_window_callback_contains_exception_and_preserves_interrupt(
    tmp_path, failure_type
) -> None:
    application = tmp_path / "metroliza_application.exe"
    title = "Metroliza [fixed]"
    api = _window_api({100: _normal_window(41, title)})
    failure = failure_type("PRIVATE_WINDOW_CALLBACK")
    api.user.failure = failure
    observations = (
        qualification._ProcessObservation(41, 1, str(application)),
    )

    expected = (
        qualification.QualificationFailure
        if failure_type is RuntimeError
        else KeyboardInterrupt
    )
    with pytest.raises(expected) as caught:
        api.normal_window(observations, application, title)
    if failure_type is RuntimeError:
        assert caught.value.qualification_reason == "normal_window_enumeration_failed"
        assert "PRIVATE" not in str(caught.value)
    else:
        assert caught.value is failure


def test_job_accounting_exposes_unobserved_short_lived_processes() -> None:
    class _ProcessIds(ctypes.Structure):
        _fields_ = [
            ("NumberOfAssignedProcesses", ctypes.c_uint32),
            ("NumberOfProcessIdsInList", ctypes.c_uint32),
            ("ProcessIdList", ctypes.c_size_t * 16),
        ]

    class _Accounting(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong),
            ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", ctypes.c_uint32),
            ("TotalProcesses", ctypes.c_uint32),
            ("ActiveProcesses", ctypes.c_uint32),
            ("TotalTerminatedProcesses", ctypes.c_uint32),
        ]

    class _Kernel:
        def QueryInformationJobObject(self, _job, kind, value, _size, _returned):
            if kind == 1:
                accounting = ctypes.cast(value, ctypes.POINTER(_Accounting)).contents
                accounting.TotalProcesses = 3
                accounting.ActiveProcesses = 0
                accounting.TotalTerminatedProcesses = 3
                return 1
            info = ctypes.cast(value, ctypes.POINTER(_ProcessIds)).contents
            info.NumberOfAssignedProcesses = 0
            info.NumberOfProcessIdsInList = 0
            return 1

    api = object.__new__(qualification._WindowsApi)
    api.wintypes = _TokenWinTypes
    api.PROCESS_IDS = _ProcessIds
    api.BASIC_ACCOUNTING = _Accounting
    api.kernel = _Kernel()

    observations, active, total = api.job_observations(object())

    assert observations == ()
    assert (active, total) == (0, 3)
    topology = qualification._classify_topology(
        observations,
        total,
        active,
        True,
        Path("launcher"),
        Path("application"),
    )
    assert topology.unexpected_processes_observed == 3


def _write_pe(path: Path, subsystem: int = 2) -> None:
    image = bytearray(512)
    image[0:2] = b"MZ"
    image[0x3C:0x40] = (128).to_bytes(4, "little")
    image[128:132] = b"PE\x00\x00"
    optional = 128 + 4 + 20
    image[optional : optional + 2] = (0x20B).to_bytes(2, "little")
    image[optional + 68 : optional + 70] = subsystem.to_bytes(2, "little")
    path.write_bytes(image)


def _package_receipt() -> dict[str, object]:
    return {
        "git_sha": "a" * 40,
        "launcher_sha256": "b" * 64,
        "application_sha256": "c" * 64,
        "manifest_sha256": "d" * 64,
        "notice_hashes": {
            "THIRD_PARTY_NOTICES.md": "e" * 64,
            "third_party_inventory_260711.json": "f" * 64,
        },
        "tested_tree_sha256": "1" * 64,
        "package_manifest_sha256": "2" * 64,
        "archive_name": qualification.PACKAGE_ARCHIVE_NAME,
        "archive_sha256": "3" * 64,
        "archive_size_bytes": 100,
    }


def _environment_receipt() -> dict[str, str]:
    return {
        "windows_version": "10.0.26100",
        "architecture": "amd64",
        "python_version": "3.11.16",
        "pyinstaller_version": "6.16.0",
    }


def _flood_loss(value: int = 1) -> dict[str, object]:
    return {
        "source_dropped": value,
        **{
            field: False if field == "counters_saturated" else value
            for field in qualification.RING_LOSS_FIELDS
        },
    }


def _metrics(value: int = 1) -> qualification.ProcessMetrics:
    return qualification.ProcessMetrics(value, value, value, value, value)


def _scenario(
    value: int = 1, *, supervised: bool = False
) -> qualification.ScenarioResult:
    topology = qualification.ProcessTopology(
        2 if supervised else 0,
        1,
        0,
        3 if supervised else 1,
        3 if supervised else 1,
        (
            ("launcher_bootloader", "launcher_supervisor", "application")
            if supervised
            else ("application",)
        ),
        True,
    )
    return qualification.ScenarioResult(
        0, value, value, "complete", _metrics(value), topology
    )


def _success_payload() -> dict[str, object]:
    results = {
        "direct_normal_1": _scenario(),
        "direct_normal_2": _scenario(2),
        "supervised_normal_1": _scenario(3, supervised=True),
        "supervised_normal_2": _scenario(4, supervised=True),
        "flood": _scenario(5),
    }
    return qualification._success_payload(
        _package_receipt(),
        _environment_receipt(),
        results,
        direct_idle_write_bytes=5,
        supervised_idle_write_bytes=6,
        hard_ready_to_report_ms=7,
        handled_ready_to_report_ms=8,
        hard_assembly_to_verification_ms=9,
        handled_assembly_to_verification_ms=10,
        flood_loss=_flood_loss(),
    )


def test_sanitized_environment_has_only_fixed_runtime_inputs(tmp_path) -> None:
    artifact = tmp_path / "package"
    work = tmp_path / "work"
    state = tmp_path / "state"
    inherited = {
        "SYSTEMROOT": r"C:\Windows",
        "USERPROFILE": r"C:\Users\runner",
        "PYTHONPATH": r"C:\development\src",
        "PYTHONHOME": r"C:\development\python",
        "VIRTUAL_ENV": r"C:\development\.venv",
        "METROLIZA_STARTUP_PROFILE": "1",
        "SECRET_VALUE": "not-for-child",
        "PATH": r"C:\development\python",
    }

    environment = qualification._sanitized_environment(
        artifact, work, state, "normal", inherited=inherited
    )

    assert environment["PATH"].split(";") == [
        str(artifact),
        str(artifact / "_internal"),
        str(Path(r"C:\Windows") / "System32"),
        r"C:\Windows",
    ]
    assert environment["METROLIZA_STARTUP_SMOKE"] == "1"
    assert environment["METROLIZA_DIAGNOSTIC_QUALIFICATION"] == "normal"
    assert environment["METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT"] == str(work)
    assert environment["LOCALAPPDATA"] == str(state)
    assert not any(key.startswith("PYTHON") for key in environment)
    assert "VIRTUAL_ENV" not in environment
    assert "METROLIZA_STARTUP_PROFILE" not in environment
    assert "SECRET_VALUE" not in environment


def test_pe_subsystem_requires_a_gui_executable(tmp_path) -> None:
    gui = tmp_path / "gui.exe"
    console = tmp_path / "console.exe"
    invalid = tmp_path / "invalid.exe"
    _write_pe(gui, 2)
    _write_pe(console, 3)
    invalid.write_bytes(b"not a portable executable")

    assert qualification._pe_subsystem(gui) == 2
    assert qualification._pe_subsystem(console) == 3
    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._pe_subsystem(invalid)
    assert error.value.failure_id == "artifact_invalid"


def test_child_receipt_requires_packaged_medium_integrity_ordinary_user(tmp_path) -> None:
    path = tmp_path / "qualification.json"
    payload = {
        "schema_version": 1,
        "scenario": "normal",
        "stage": "complete",
        "packaged": True,
        "console_none": True,
        "ordinary_user": True,
        "integrity_level": "medium",
    }
    path.write_text(json.dumps(payload), encoding="ascii")
    assert qualification._validate_child_receipt(path, "normal") == payload

    for field in ("packaged", "console_none", "ordinary_user"):
        changed = dict(payload)
        changed[field] = False
        path.write_text(json.dumps(changed), encoding="ascii")
        with pytest.raises(qualification.QualificationFailure):
            qualification._validate_child_receipt(path, "normal")

    for value in ("low", "high", "system", "other", "unavailable", "not_windows"):
        changed = {**payload, "integrity_level": value}
        path.write_text(json.dumps(changed), encoding="ascii")
        with pytest.raises(qualification.QualificationFailure):
            qualification._validate_child_receipt(path, "normal")

    path.write_text('{"schema_version":1,"schema_version":1}', encoding="ascii")
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_child_receipt(path, "normal")

    failure_path = tmp_path / "failure.json"
    failure = {
        "schema_version": 1,
        "stage": "preview",
        "reason": "qualification_export_unavailable",
    }
    failure_path.write_text(json.dumps(failure), encoding="ascii")
    assert qualification._validate_child_failure(failure_path) == failure
    failure["reason"] = "arbitrary private exception"
    failure_path.write_text(json.dumps(failure), encoding="ascii")
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_child_failure(failure_path)


def test_child_failure_accepts_closed_cleanup_and_rejects_malformed_cleanup(
    tmp_path,
) -> None:
    failure_path = tmp_path / "failure.json"
    qualification_entry._write_failure(
        tmp_path,
        "preview",
        qualification_entry._PreviewFailure(
            "qualification_menu_unavailable", "failed"
        ),
    )
    expected = {
        "schema_version": 1,
        "stage": "preview",
        "reason": "qualification_menu_unavailable",
        "cleanup": "failed",
    }
    assert qualification._validate_child_failure(failure_path) == expected

    for cleanup in qualification.QUALIFICATION_CLEANUP_STATUSES:
        candidate = {**expected, "cleanup": cleanup}
        failure_path.write_text(json.dumps(candidate), encoding="ascii")
        assert qualification._validate_child_failure(failure_path) == candidate

    for cleanup in ("PRIVATE_PATH", [], {"private": "value"}):
        failure_path.write_text(
            json.dumps({**expected, "cleanup": cleanup}), encoding="ascii"
        )
        with pytest.raises(qualification.QualificationFailure):
            qualification._validate_child_failure(failure_path)

    failure_path.write_text(
        json.dumps({**expected, "private": "value"}), encoding="ascii"
    )
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_child_failure(failure_path)

    failure_path.write_text(
        json.dumps({**expected, "stage": "workflows"}), encoding="ascii"
    )
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_child_failure(failure_path)


def test_provenance_and_notices_bind_the_exact_launcher(tmp_path) -> None:
    launcher = tmp_path / "metroliza.exe"
    launcher.write_bytes(b"exact launcher")
    digest = hashlib.sha256(launcher.read_bytes()).hexdigest()
    sidecar = {
        "schema_version": 1,
        "release_label": "260913",
        "git_sha": "a" * 40,
        "dirty": False,
        "built_at_utc": "2026-09-13T10:00:00Z",
        "packager": "pyinstaller",
        "python_version": "3.11.16",
        "artifact": {
            "name": launcher.name,
            "sha256": digest,
            "size_bytes": launcher.stat().st_size,
        },
    }
    launcher.with_name("metroliza.exe.provenance.json").write_text(
        json.dumps(sidecar), encoding="utf-8"
    )
    notices = launcher.with_name("metroliza.exe.licenses")
    notices.mkdir()
    entries = []
    for name in qualification.NOTICE_FILES:
        path = notices / name
        path.write_text(f"fixed {name}\n", encoding="utf-8")
        entries.append({"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (notices / "NOTICE_MANIFEST.json").write_text(
        json.dumps({"files": entries}), encoding="utf-8"
    )

    assert qualification._validate_sidecar(launcher, "a" * 40) == digest
    assert set(qualification._validate_notices(launcher)) == set(qualification.NOTICE_FILES)

    launcher.write_bytes(b"changed launcher")
    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._validate_sidecar(launcher, "a" * 40)
    assert error.value.failure_id == "provenance_invalid"


def test_output_receipt_is_closed_bounded_and_atomic(tmp_path) -> None:
    output = tmp_path / "receipts"
    output.mkdir()
    source = tmp_path / "source"
    tested = tmp_path / "tested"
    source.mkdir()
    tested.mkdir()
    (source / "fixed component.bin").write_bytes(b"approved package bytes")
    (tested / "fixed component.bin").write_bytes(b"approved package bytes")
    payload_to_write = _success_payload()
    payload_to_write["package"].update(
        qualification._write_development_artifacts(source, tested, output)
    )
    destination = qualification._write_receipt(output, payload_to_write)

    payload = json.loads(destination.read_text(encoding="ascii"))
    assert {path.name for path in output.iterdir()} == {
        qualification.OUTPUT_NAME,
        qualification.PACKAGE_MANIFEST_NAME,
        qualification.PACKAGE_ARCHIVE_NAME,
    }
    assert payload["status"] == "passed"
    assert [check["id"] for check in payload["checks"]] == [
        *qualification.CHECK_IDS,
        qualification.OPERATIONAL_CHECK_ID,
    ]
    assert qualification.CHECK_IDS[:4] == (
        "package_identity",
        "no_console",
        "restricted_token",
        "direct_ui_smoke",
    )
    assert set(payload["metrics"]) == {
        "direct_startup_ready_ms",
        "supervised_startup_ready_ms",
        "direct_peak_process_tree_memory_bytes",
        "supervised_peak_process_tree_memory_bytes",
        "direct_idle_write_bytes",
        "supervised_idle_write_bytes",
        "hard_exit_ready_receipt_to_report_verification_ms",
        "handled_ready_receipt_to_report_verification_ms",
        "hard_incident_assembly_to_verification_ms",
        "handled_incident_assembly_to_verification_ms",
        "flood_elapsed_ms",
        "flood_loss",
    }
    manifest = json.loads(
        (output / qualification.PACKAGE_MANIFEST_NAME).read_text(encoding="ascii")
    )
    assert manifest["entries"] == [
        {
            "path": "fixed component.bin",
            "sha256": hashlib.sha256(b"approved package bytes").hexdigest(),
            "size_bytes": len(b"approved package bytes"),
        }
    ]
    assert payload["package"]["archive_sha256"] == manifest["archive"]["sha256"]

    second = tmp_path / "second"
    second.mkdir()
    unsafe = _success_payload()
    unsafe["raw_exception"] = "must not be written"
    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._write_receipt(second, unsafe)
    assert error.value.failure_id == "output_failed"

    assert not tuple(second.iterdir())


def test_late_payload_failure_removes_only_created_artifacts_for_failure_receipt(
    tmp_path, monkeypatch, capsys
) -> None:
    source = tmp_path / "source"
    tested = tmp_path / "tested"
    output = tmp_path / "output"
    for path in (source, tested, output):
        path.mkdir()
    (source / "component.bin").write_bytes(b"approved")
    (tested / "component.bin").write_bytes(b"approved")
    runner = object.__new__(qualification._QualificationRunner)
    runner.artifact = tested
    runner.results = {}
    runner.direct_idle_write_bytes = 0
    runner.supervised_idle_write_bytes = 0
    runner.hard_ready_to_report_ms = 0
    runner.handled_ready_to_report_ms = 0
    runner.hard_assembly_to_verification_ms = 0
    runner.handled_assembly_to_verification_ms = 0
    runner.flood_loss = {}
    phase_calls = []
    for name in (
        "run_direct_ui_smoke",
        "run_startups",
        "run_concurrent_instances",
        "run_ui_smoke",
        "run_hard_exit",
        "run_handled_failure",
        "run_preview",
        "run_idle",
        "run_flood",
        "run_unavailable_store",
        "run_missing_components",
        "run_missing_qt_resource",
    ):
        setattr(runner, name, lambda name=name: phase_calls.append(name))

    def fail_payload(*_arguments, **_keywords):
        raise qualification.QualificationFailure("scenario_failed")

    monkeypatch.setattr(qualification, "_success_payload", fail_payload)
    with pytest.raises(qualification.QualificationFailure) as caught:
        runner.run({}, source, output)

    assert caught.value.qualification_stage == "receipt"
    assert phase_calls[:2] == ["run_direct_ui_smoke", "run_startups"]
    assert capsys.readouterr().out == qualification.DIRECT_UI_CHECKPOINT + "\n"
    assert not tuple(output.iterdir())
    failure_payload = {
        "schema_version": 1,
        "status": "failed",
        "failure_id": caught.value.failure_id,
        "qualification_failure": {
            "stage": caught.value.qualification_stage,
            "reason": caught.value.qualification_reason,
        },
        "qualification_cleanup": caught.value.qualification_cleanup,
        "package": None,
        "environment": None,
        "topology": None,
        "checks": [],
        "metrics": None,
        "operational_cost": None,
    }
    destination = qualification._write_receipt(output, failure_payload)
    assert {path.name for path in output.iterdir()} == {qualification.OUTPUT_NAME}
    assert json.loads(destination.read_text(encoding="ascii"))["status"] == "failed"


def test_direct_ui_failure_emits_no_success_checkpoint(
    tmp_path, capsys
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    artifact = tmp_path / "artifact"
    for path in (source, output, artifact):
        path.mkdir()
    runner = object.__new__(qualification._QualificationRunner)
    runner.artifact = artifact

    def fail_direct_ui():
        raise qualification.QualificationFailure(
            "scenario_failed", qualification_reason="normal_window_unavailable"
        )

    runner.run_direct_ui_smoke = fail_direct_ui
    for name in (
        "run_startups",
        "run_concurrent_instances",
        "run_ui_smoke",
        "run_hard_exit",
        "run_handled_failure",
        "run_preview",
        "run_idle",
        "run_flood",
        "run_unavailable_store",
        "run_missing_components",
        "run_missing_qt_resource",
    ):
        setattr(runner, name, lambda: None)

    with pytest.raises(qualification.QualificationFailure) as caught:
        runner.run({}, source, output)

    assert caught.value.qualification_stage == "direct_ui_smoke"
    assert caught.value.qualification_reason == "normal_window_unavailable"
    assert capsys.readouterr().out == ""


def test_main_replaces_late_created_artifacts_with_closed_failure_receipt(
    tmp_path, monkeypatch
) -> None:
    artifact = tmp_path / "artifact"
    output = tmp_path / "output"
    artifact.mkdir()

    class _Arguments:
        artifact_dir = artifact
        output_dir = output

    class _Parser:
        def parse_args(self, _arguments):
            return _Arguments()

    def fail_after_artifacts(_artifact, output_dir, _deadline):
        (output_dir / qualification.PACKAGE_ARCHIVE_NAME).write_bytes(b"partial")
        (output_dir / qualification.PACKAGE_MANIFEST_NAME).write_bytes(b"partial")
        raise qualification.QualificationFailure("output_failed")

    monkeypatch.setattr(qualification, "_parser", lambda: _Parser())
    monkeypatch.setattr(qualification, "_qualification_payload", fail_after_artifacts)
    monkeypatch.setattr(qualification.os, "name", "nt")

    assert qualification.main([]) == 1
    assert {path.name for path in output.iterdir()} == {qualification.OUTPUT_NAME}
    receipt = json.loads((output / qualification.OUTPUT_NAME).read_text(encoding="ascii"))
    assert receipt["status"] == "failed"
    assert receipt["failure_id"] == "output_failed"
    assert receipt["qualification_failure"] == {
        "stage": "runner",
        "reason": "unexpected",
    }
    assert receipt["qualification_cleanup"] == "complete"


def test_main_preserves_primary_and_independent_failed_cleanup(
    tmp_path, monkeypatch
) -> None:
    artifact = tmp_path / "artifact"
    output = tmp_path / "output"
    artifact.mkdir()

    class _Arguments:
        artifact_dir = artifact
        output_dir = output

    class _Parser:
        def parse_args(self, _arguments):
            return _Arguments()

    monkeypatch.setattr(qualification, "_parser", lambda: _Parser())
    monkeypatch.setattr(
        qualification,
        "qualify_windows_diagnostics",
        lambda *_arguments: qualification.QualificationResult(
            "failed",
            "scenario_failed",
            None,
            qualification_stage="missing_qt_resource",
            qualification_reason="process_exit_mismatch",
            qualification_exit_code=7,
            qualification_cleanup="failed",
        ),
    )

    assert qualification.main([]) == 1
    receipt = json.loads((output / qualification.OUTPUT_NAME).read_text("ascii"))
    qualification._validate_output_payload(receipt)
    assert receipt["qualification_failure"] == {
        "stage": "missing_qt_resource",
        "reason": "process_exit_mismatch",
        "exit_code": 7,
    }
    assert receipt["qualification_cleanup"] == "failed"


@pytest.mark.parametrize(
    ("reason", "exit_code"),
    [
        ("qualification_observation_failed", None),
        ("process_exit_mismatch", 7),
        ("normal_window_unavailable", None),
        ("process_exit_timeout", None),
        ("qualification_job_drain_failed", None),
    ],
)
def test_main_serializes_closed_scenario_reason_without_private_detail(
    tmp_path, monkeypatch, reason, exit_code
) -> None:
    artifact = tmp_path / "artifact"
    output = tmp_path / "output"
    artifact.mkdir()

    class _Arguments:
        artifact_dir = artifact
        output_dir = output

    class _Parser:
        def parse_args(self, _arguments):
            return _Arguments()

    monkeypatch.setattr(qualification, "_parser", lambda: _Parser())
    monkeypatch.setattr(
        qualification,
        "qualify_windows_diagnostics",
        lambda *_arguments: qualification.QualificationResult(
            "failed",
            "scenario_failed",
            None,
            qualification_stage="direct_normal_1",
            qualification_reason=reason,
            qualification_exit_code=exit_code,
            qualification_cleanup="complete",
        ),
    )

    assert qualification.main([]) == 1
    receipt_bytes = (output / qualification.OUTPUT_NAME).read_bytes()
    receipt = json.loads(receipt_bytes)
    qualification._validate_output_payload(receipt)
    assert receipt["qualification_failure"] == {
        "stage": "direct_normal_1",
        "reason": reason,
        **({"exit_code": exit_code} if exit_code is not None else {}),
    }
    assert receipt["qualification_cleanup"] == "complete"
    assert b"PRIVATE" not in receipt_bytes


def test_main_does_not_write_output_failure_into_preexisting_directory(
    tmp_path, monkeypatch
) -> None:
    artifact = tmp_path / "artifact"
    output = tmp_path / "output"
    artifact.mkdir()
    output.mkdir()
    sentinel = output / "existing.txt"
    sentinel.write_bytes(b"preserve")

    class _Arguments:
        artifact_dir = artifact
        output_dir = output

    class _Parser:
        def parse_args(self, _arguments):
            return _Arguments()

    monkeypatch.setattr(qualification, "_parser", lambda: _Parser())
    monkeypatch.setattr(qualification.os, "name", "nt")

    assert qualification.main([]) == 1
    assert {path.name for path in output.iterdir()} == {sentinel.name}
    assert sentinel.read_bytes() == b"preserve"


def test_package_relocation_rejects_links_and_entry_overflow(tmp_path, monkeypatch) -> None:
    source = tmp_path / "package"
    source.mkdir()
    (source / "component").write_bytes(b"safe")
    linked = source / "linked"
    linked.symlink_to(source / "component")

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._validate_package_tree(source)
    assert error.value.failure_id == "artifact_invalid"

    linked.unlink()
    monkeypatch.setattr(qualification, "MAX_PACKAGE_ENTRIES", 0)
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_package_tree(source)


def test_operational_cost_is_truthful_and_environment_is_closed() -> None:
    payload = _success_payload()
    assert payload["operational_cost"]["status"] == "within_budget"
    payload["metrics"]["supervised_idle_write_bytes"] = (
        qualification.MAX_IDLE_WRITE_BYTES + 1
    )
    payload["operational_cost"] = qualification._operational_cost(payload["metrics"])
    payload["checks"][-1]["status"] = "unresolved"
    qualification._validate_output_payload(payload)
    assert payload["operational_cost"]["status"] == "unresolved"

    payload["environment"]["architecture"] = "x86"
    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._validate_output_payload(payload)
    assert error.value.failure_id == "output_failed"

    payload = _success_payload()
    threshold = qualification.MAX_SUPERVISOR_MEMORY_OVERHEAD_BYTES
    payload["metrics"]["direct_peak_process_tree_memory_bytes"] = [threshold * 2, 1]
    payload["metrics"]["supervised_peak_process_tree_memory_bytes"] = [
        threshold * 2,
        threshold + 2,
    ]
    cost = qualification._operational_cost(payload["metrics"])
    assert cost["observed"]["max_supervisor_memory_overhead_bytes"] == threshold + 1
    assert cost["status"] == "unresolved"


def test_output_failure_detail_accepts_only_closed_qualification_evidence() -> None:
    payload = {
        "schema_version": 1,
        "status": "failed",
        "failure_id": "scenario_failed",
        "qualification_failure": {
            "stage": "preview",
            "child_stage": "preview",
            "reason": "qualification_preview_unavailable",
            "exit_code": 3221225477,
        },
        "qualification_cleanup": "complete",
        "package": None,
        "environment": None,
        "topology": None,
        "checks": [],
        "metrics": None,
        "operational_cost": None,
    }
    qualification._validate_output_payload(payload)
    payload["qualification_failure"]["exit_code"] = True
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_output_payload(payload)
    payload["qualification_failure"]["exit_code"] = 3221225477
    payload["qualification_failure"]["reason"] = "PRIVATE_PATH"
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_output_payload(payload)
    payload["qualification_failure"]["reason"] = "qualification_preview_unavailable"
    payload["qualification_cleanup"] = "PRIVATE_PATH"
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_output_payload(payload)
    payload["qualification_cleanup"] = []
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_output_payload(payload)


def test_topology_rejects_path_selected_or_recursive_children(tmp_path) -> None:
    launcher = tmp_path / "metroliza.exe"
    application = tmp_path / "metroliza_application.exe"
    unexpected = tmp_path / "elsewhere" / "metroliza_application.exe"
    observations = (
        qualification._ProcessObservation(1, 1, str(launcher)),
        qualification._ProcessObservation(2, 2, str(launcher)),
        qualification._ProcessObservation(3, 3, str(application)),
        qualification._ProcessObservation(4, 4, str(unexpected)),
    )

    topology = qualification._classify_topology(
        observations, 4, 4, True, launcher, application
    )

    assert topology.unexpected_processes_observed == 1
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_topology_record(
            qualification._topology_record(topology), supervised=True
        )


def test_full_tree_identity_rejects_post_copy_change(tmp_path) -> None:
    source = tmp_path / "source"
    tested = tmp_path / "tested"
    output = tmp_path / "output"
    for path in (source, tested, output):
        path.mkdir()
    (source / "one.bin").write_bytes(b"one")
    (tested / "one.bin").write_bytes(b"changed")

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._write_development_artifacts(source, tested, output)
    assert error.value.failure_id == "artifact_invalid"
    assert not tuple(output.iterdir())


@pytest.mark.parametrize("replacement", [b"two", b"unexpected growth"])
def test_archive_copy_rejects_change_after_inventory(
    tmp_path, monkeypatch, replacement
) -> None:
    source = tmp_path / "source"
    tested = tmp_path / "tested"
    output = tmp_path / "output"
    for path in (source, tested, output):
        path.mkdir()
    (source / "one.bin").write_bytes(b"one")
    tested_file = tested / "one.bin"
    tested_file.write_bytes(b"one")
    inventory = qualification._package_inventory

    def mutate_after_inventory(root):
        result = inventory(root)
        if root == tested:
            tested_file.write_bytes(replacement)
        return result

    monkeypatch.setattr(qualification, "_package_inventory", mutate_after_inventory)
    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._write_development_artifacts(source, tested, output)
    assert error.value.failure_id == "artifact_invalid"
    assert not tuple(output.iterdir())


def test_published_archive_revalidates_each_member_sha(tmp_path) -> None:
    source = tmp_path / "source"
    tested = tmp_path / "tested"
    output = tmp_path / "output"
    for path in (source, tested, output):
        path.mkdir()
    (source / "one.bin").write_bytes(b"one")
    (tested / "one.bin").write_bytes(b"one")
    package = qualification._write_development_artifacts(source, tested, output)
    archive_path = output / qualification.PACKAGE_ARCHIVE_NAME
    archive_path.unlink()
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr("one.bin", b"two")
    manifest_path = output / qualification.PACKAGE_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    archive_sha256 = qualification._sha256(
        archive_path, maximum=qualification.MAX_PACKAGE_ARCHIVE_BYTES
    )
    manifest["archive"].update(
        sha256=archive_sha256, size_bytes=archive_path.stat().st_size
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        encoding="ascii",
    )
    package.update(
        archive_sha256=archive_sha256,
        archive_size_bytes=archive_path.stat().st_size,
        package_manifest_sha256=qualification._sha256(
            manifest_path, maximum=qualification.MAX_PACKAGE_MANIFEST_BYTES
        ),
    )

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._validate_development_artifacts(output, package)
    assert error.value.failure_id == "output_failed"


def test_package_inventory_rejects_empty_directories(tmp_path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "component.bin").write_bytes(b"one")
    (package / "required-empty").mkdir()

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._package_inventory(package)
    assert error.value.failure_id == "artifact_invalid"


def test_hard_exit_rejects_a_valid_incident_with_empty_history() -> None:
    incident = build_incident(
        session_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        report_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        created_at_ms=1_800_000_000_000,
        build_git_sha="a" * 40,
        observation=IncidentObservation(
            launch=LaunchState.STARTED,
            handshake=HandshakeState.ACCEPTED,
            channel=ChannelState.INCOMPLETE,
            exit_code=9,
            termination=TerminationState.OBSERVED_EXIT,
            clean_terminal_received=False,
            source_dropped=0,
            source_loss_known=False,
            elapsed_ms=100,
        ),
        history=RingSnapshot((), RingLoss(), LOSS_ACCOUNTING_BYTES),
    )

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._validate_hard_exit_history(incident)
    assert error.value.failure_id == "incident_invalid"


class _FakeProcess:
    def __init__(
        self, exit_code: int | None, *, supervised: bool, active_processes: int = 0
    ) -> None:
        self.started = time.perf_counter()
        self.exit_code = exit_code
        self.closed_with: bool | None = None
        self.supervised = supervised
        self._active_processes = active_processes

    def poll(self) -> int | None:
        return self.exit_code

    def metrics(self) -> qualification.ProcessMetrics:
        return _metrics()

    def observe(self) -> None:
        return None

    def active_processes(self) -> int:
        return self._active_processes

    def topology(self, _artifact, *, all_exited: bool) -> qualification.ProcessTopology:
        return _scenario(supervised=self.supervised).topology

    def close(self, *, terminate: bool = False) -> None:
        self.closed_with = terminate


class _FakeApi:
    def __init__(
        self, exit_code: int | None, stage: str, *, active_processes: int = 0
    ) -> None:
        self.exit_code = exit_code
        self.stage = stage
        self.active_processes = active_processes
        self.process: _FakeProcess | None = None
        self.environment: dict[str, str] | None = None

    def launch(self, executable, environment, cwd, owned=None, expected_images=None):
        self.environment = environment
        common = {
            "schema_version": 1,
            "scenario": environment["METROLIZA_DIAGNOSTIC_QUALIFICATION"],
            "packaged": True,
            "console_none": True,
            "ordinary_user": True,
            "integrity_level": "medium",
        }
        startup = {**common, "stage": "startup_ready"}
        payload = {**common, "stage": self.stage}
        (cwd / "startup.json").write_text(json.dumps(startup), encoding="ascii")
        (cwd / qualification.QUALIFICATION_RECEIPT_NAMES[self.stage]).write_text(
            json.dumps(payload), encoding="ascii"
        )
        self.process = _FakeProcess(
            self.exit_code,
            supervised=Path(executable).name == "metroliza.exe",
            active_processes=self.active_processes,
        )
        if owned is not None:
            owned.append(self.process)
        return self.process


class _DirectWindowProcess:
    def __init__(self, application, *, window=700, early_exit=None):
        self.application = application
        self.window = window
        self.early_exit = early_exit
        self.started = time.perf_counter()
        self.window_closed = False
        self.closed_with = None
        self.requested_title = None

    def normal_window(self, application, expected_title):
        assert application == self.application
        self.requested_title = expected_title
        return self.window

    def close_normal_window(self, window, application, expected_title):
        assert window == self.window
        assert application == self.application
        assert expected_title == self.requested_title
        self.window_closed = True

    def observe(self):
        return None

    def poll(self):
        if self.early_exit is not None:
            return self.early_exit
        return 0 if self.window_closed else None

    def active_processes(self):
        return 0 if self.window_closed else 1

    def metrics(self):
        return _metrics()

    def topology(self, _artifact, *, all_exited):
        assert all_exited
        return _scenario().topology

    def close(self, *, terminate=False):
        self.closed_with = terminate


class _DirectWindowApi:
    def __init__(self, application, *, window=700, early_exit=None):
        self.process = _DirectWindowProcess(
            application, window=window, early_exit=early_exit
        )
        self.executable = None
        self.environment = None

    def launch(self, executable, environment, _root, owned=None, expected_images=None):
        self.executable = executable
        self.environment = dict(environment)
        owned.append(self.process)
        return self.process


def test_missing_qt_restore_failure_preserves_classified_primary(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    artifact = tmp_path / "artifact"
    resource = (
        artifact
        / "_internal"
        / "PyQt6"
        / "Qt6"
        / "plugins"
        / "platforms"
        / "qwindows.dll"
    )
    resource.parent.mkdir(parents=True)
    resource.write_bytes(b"fixed qwindows")
    work = tmp_path / "work"
    state = tmp_path / "state"
    work.mkdir()
    state.mkdir()
    runner = object.__new__(qualification._QualificationRunner)
    runner.artifact = artifact
    runner.state_base = state
    runner.launcher = artifact / "metroliza.exe"
    runner.store = qualification.IncidentStore(state / "diagnostics")
    runner.results = {}
    runner.api = _FakeApi(1, "ready")
    runner._root = lambda _label: work
    primary = qualification.QualificationFailure(
        "scenario_failed",
        qualification_stage="missing_qt_resource",
        qualification_reason="process_exit_mismatch",
        qualification_exit_code=7,
    )

    def fail_after_hiding(_process):
        resource.with_name("qwindows.qualification-missing").unlink()
        raise primary

    runner._wait_missing_exit = fail_after_hiding

    with pytest.raises(qualification.QualificationFailure) as caught:
        runner.run_missing_qt_resource()

    assert caught.value is primary
    assert caught.value.qualification_cleanup == "failed"
    assert caught.value.qualification_exit_code == 7


def test_immutable_receipts_preserve_ready_during_complete_observation(
    tmp_path,
) -> None:
    process = _FakeProcess(0, supervised=True)
    common = {
        "schema_version": 1,
        "scenario": "normal",
        "packaged": True,
        "console_none": True,
        "ordinary_user": True,
        "integrity_level": "medium",
    }
    for stage in ("ready", "complete"):
        (tmp_path / qualification.QUALIFICATION_RECEIPT_NAMES[stage]).write_text(
            json.dumps({**common, "stage": stage}), encoding="ascii"
        )
    called: list[qualification._WindowsProcess] = []

    receipt, ready_called = qualification._observe_qualification_receipt(
        tmp_path, "normal", process, called.append, False
    )

    assert receipt is not None and receipt["stage"] == "complete"
    assert ready_called is True
    assert called == [process]
    assert (tmp_path / qualification.QUALIFICATION_RECEIPT_NAMES["ready"]).is_file()


def test_failed_child_receipt_retains_host_stage_and_closed_child_evidence(
    tmp_path,
) -> None:
    process = _FakeProcess(21, supervised=True)
    receipt = {
        "schema_version": 1,
        "scenario": "handled_failure",
        "stage": "failed",
        "packaged": True,
        "console_none": True,
        "ordinary_user": True,
        "integrity_level": "medium",
    }
    (tmp_path / qualification.QUALIFICATION_RECEIPT_NAMES["failed"]).write_text(
        json.dumps(receipt), encoding="ascii"
    )
    (tmp_path / "failure.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": "workflows",
                "reason": "qualification_result_mismatch",
            }
        ),
        encoding="ascii",
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._run_driver_phase(
            "handled_failure",
            lambda: qualification._observe_qualification_receipt(
                tmp_path, "handled_failure", process, None, False
            ),
        )

    assert caught.value.qualification_stage == "handled_failure"
    assert caught.value.qualification_child_stage == "workflows"
    assert caught.value.qualification_reason == "qualification_result_mismatch"


def test_failed_child_cleanup_survives_host_cleanup_and_public_receipt(
    tmp_path, monkeypatch
) -> None:
    work = tmp_path / "work"
    artifact = tmp_path / "artifact"
    output = tmp_path / "output"
    work.mkdir()
    artifact.mkdir()
    receipt = {
        "schema_version": 1,
        "scenario": "preview",
        "stage": "failed",
        "packaged": True,
        "console_none": True,
        "ordinary_user": True,
        "integrity_level": "medium",
    }
    (work / qualification.QUALIFICATION_RECEIPT_NAMES["failed"]).write_text(
        json.dumps(receipt), encoding="ascii"
    )
    qualification_entry._write_failure(
        work,
        "preview",
        qualification_entry._PreviewFailure(
            "qualification_menu_unavailable", "failed"
        ),
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        try:
            qualification._run_driver_phase(
                "preview",
                lambda: qualification._observe_qualification_receipt(
                    work, "preview", _FakeProcess(21, supervised=True), None, False
                ),
            )
        finally:
            qualification._attempt_cleanup(lambda: None)

    failure = caught.value
    assert failure.qualification_stage == "preview"
    assert failure.qualification_child_stage == "preview"
    assert failure.qualification_reason == "qualification_menu_unavailable"
    assert failure.qualification_cleanup == "failed"

    class _Arguments:
        artifact_dir = artifact
        output_dir = output

    class _Parser:
        def parse_args(self, _arguments):
            return _Arguments()

    monkeypatch.setattr(qualification, "_parser", lambda: _Parser())
    monkeypatch.setattr(
        qualification,
        "qualify_windows_diagnostics",
        lambda *_arguments: qualification.QualificationResult(
            "failed",
            failure.failure_id,
            None,
            qualification_stage=failure.qualification_stage,
            qualification_reason=failure.qualification_reason,
            qualification_child_stage=failure.qualification_child_stage,
            qualification_cleanup=failure.qualification_cleanup,
        ),
    )

    assert qualification.main([]) == 1
    payload = json.loads((output / qualification.OUTPUT_NAME).read_text("ascii"))
    qualification._validate_output_payload(payload)
    assert payload["qualification_failure"] == {
        "stage": "preview",
        "reason": "qualification_menu_unavailable",
        "child_stage": "preview",
    }
    assert payload["qualification_cleanup"] == "failed"


def test_scenario_uses_fixed_receipt_and_closes_completed_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    api = _FakeApi(9, "ready")
    artifact = tmp_path / "artifact"
    work = tmp_path / "work"
    state = tmp_path / "state"
    for path in (artifact, work, state):
        path.mkdir()
    called = []

    result = qualification._run_scenario(
        api,
        artifact / "metroliza.exe",
        artifact,
        work,
        state,
        "hard_exit",
        time.monotonic() + 1,
        expected_exit=9,
        expected_stage="ready",
        on_ready=lambda process: called.append(process),
    )

    assert result.exit_code == 9
    assert result.startup_ready_ms >= 0
    assert result.receipt_stage == "ready"
    assert called == [api.process]
    assert api.process.closed_with is False
    assert not any(key.startswith("PYTHON") for key in api.environment)


def test_direct_ui_smoke_uses_normal_application_window_and_clean_close(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setattr(qualification, "_reports", lambda _store: ())
    runner = object.__new__(qualification._QualificationRunner)
    runner.artifact = tmp_path / "artifact"
    runner.state_base = tmp_path / "state"
    runner.application = runner.artifact / "metroliza_application.exe"
    runner.launcher = runner.artifact / "metroliza.exe"
    runner.deadline = time.monotonic() + 1
    runner.store = object()
    runner.results = {}
    for path in (runner.artifact, runner.state_base):
        path.mkdir()
    root = tmp_path / "direct-ui"
    root.mkdir()
    runner._root = lambda _label: root
    runner.api = _DirectWindowApi(runner.application)

    runner.run_direct_ui_smoke()

    assert runner.api.executable == runner.application
    assert runner.api.process.requested_title == (
        f"Metroliza [{qualification.VERSION_LABEL}]"
    )
    assert runner.api.process.window_closed
    assert runner.api.process.closed_with is False
    assert runner.results["direct_ui_smoke"].exit_code == 0
    assert runner.api.environment["METROLIZA_LICENSE_VERIFICATION"] == "0"
    assert runner.api.environment["LOCALAPPDATA"] == str(runner.state_base)
    assert runner.api.environment["APPDATA"] == str(runner.state_base / "Roaming")
    assert not {
        "METROLIZA_STARTUP_SMOKE",
        "METROLIZA_STARTUP_UI_SMOKE",
        "METROLIZA_DIAGNOSTIC_QUALIFICATION",
        "METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT",
        "QT_QPA_PLATFORM",
    } & set(runner.api.environment)
    assert not qualification._has_qualification_receipt(root)
    assert not (root / "startup.json").exists()


@pytest.mark.parametrize(
    ("window", "early_exit", "deadline_offset", "reason", "exit_code"),
    [
        (None, 7, 1, "process_exited_before_window", 7),
        (None, None, 0, "normal_window_unavailable", None),
    ],
)
def test_direct_ui_smoke_fails_closed_before_visible_window(
    tmp_path, monkeypatch, window, early_exit, deadline_offset, reason, exit_code
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setattr(qualification, "_reports", lambda _store: ())
    runner = object.__new__(qualification._QualificationRunner)
    runner.artifact = tmp_path / "artifact"
    runner.state_base = tmp_path / "state"
    runner.application = runner.artifact / "metroliza_application.exe"
    runner.deadline = time.monotonic() + deadline_offset
    runner.store = object()
    runner.results = {}
    for path in (runner.artifact, runner.state_base):
        path.mkdir()
    root = tmp_path / "direct-ui"
    root.mkdir()
    runner._root = lambda _label: root
    runner.api = _DirectWindowApi(
        runner.application, window=window, early_exit=early_exit
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._run_driver_phase(
            "direct_ui_smoke", runner.run_direct_ui_smoke
        )

    assert caught.value.qualification_stage == "direct_ui_smoke"
    assert caught.value.qualification_reason == reason
    assert caught.value.qualification_exit_code == exit_code
    assert runner.api.process.closed_with is True


@pytest.mark.parametrize(
    ("fault", "expected_reason"),
    [
        ("launch", "qualification_launch_failed"),
        ("observation", "qualification_observation_failed"),
    ],
)
def test_direct_scenario_failure_identifies_closed_operation_before_cleanup(
    tmp_path, monkeypatch, fault, expected_reason
) -> None:
    monkeypatch.setattr(qualification, "_sanitized_environment", lambda *_args: {})

    class _Process:
        def observe(self):
            raise RuntimeError("PRIVATE_OBSERVATION_DETAIL")

        def close(self, *, terminate):
            qualification._attempt_cleanup(lambda: None)

    class _Api:
        def launch(self, *_arguments, owned=None, expected_images=None):
            if fault == "launch":
                raise qualification.QualificationFailure(
                    "scenario_failed", qualification_cleanup="complete"
                )
            process = _Process()
            owned.append(process)
            return process

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._run_driver_phase(
            "direct_normal_1",
            lambda: qualification._run_scenario(
                _Api(), tmp_path / "app.exe", tmp_path, tmp_path, tmp_path,
                "normal", time.monotonic() + 1,
                expected_exit=0, expected_stage="complete",
            ),
        )

    assert caught.value.failure_id == "scenario_failed"
    assert caught.value.qualification_stage == "direct_normal_1"
    assert caught.value.qualification_reason == expected_reason
    assert caught.value.qualification_cleanup == "complete"
    assert "PRIVATE" not in str(caught.value)


def test_direct_scenario_final_stage_mismatch_names_receipt_operation(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    api = _FakeApi(0, "complete")
    validate_receipt = qualification._validate_child_receipt
    final_calls = 0

    def changed_final_receipt(path, scenario):
        nonlocal final_calls
        if path.name != "startup.json":
            final_calls += 1
            if final_calls == 2:
                return {"stage": "ready"}
        return validate_receipt(path, scenario)

    monkeypatch.setattr(
        qualification,
        "_validate_child_receipt",
        changed_final_receipt,
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._run_driver_phase(
            "direct_normal_1",
            lambda: qualification._run_scenario(
                api, tmp_path / "app.exe", tmp_path, tmp_path, tmp_path,
                "normal", time.monotonic() + 1,
                expected_exit=0, expected_stage="complete",
            ),
        )

    assert caught.value.failure_id == "scenario_failed"
    assert caught.value.qualification_reason == "qualification_final_receipt_failed"
    assert api.process.closed_with is True


def test_scenario_step_keeps_specific_failure_and_primary_interrupt() -> None:
    specific = qualification.QualificationFailure(
        "scenario_failed",
        qualification_reason="process_exit_mismatch",
        qualification_exit_code=9,
    )
    primary = KeyboardInterrupt("PRIVATE_PRIMARY")

    def raise_specific():
        raise specific

    def raise_primary():
        raise primary

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._scenario_step("qualification_poll_failed", raise_specific)
    assert caught.value is specific
    assert caught.value.qualification_exit_code == 9

    with pytest.raises(KeyboardInterrupt) as caught_interrupt:
        qualification._scenario_step("qualification_poll_failed", raise_primary)
    assert caught_interrupt.value is primary


def test_scenario_step_keeps_authenticated_child_unknown_reason() -> None:
    child_failure = qualification.QualificationFailure(
        "scenario_failed",
        qualification_reason="unexpected",
        qualification_child_stage="application",
    )

    def raise_child_failure():
        raise child_failure

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._scenario_step(
            "qualification_result_receipt_failed", raise_child_failure
        )
    assert caught.value is child_failure
    assert caught.value.qualification_reason == "unexpected"
    assert caught.value.qualification_child_stage == "application"


def test_scenario_expected_exit_with_active_descendant_is_timeout(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    api = _FakeApi(0, "complete", active_processes=1)
    artifact = tmp_path / "artifact"
    work = tmp_path / "work"
    state = tmp_path / "state"
    for path in (artifact, work, state):
        path.mkdir()

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._run_scenario(
            api,
            artifact / "metroliza.exe",
            artifact,
            work,
            state,
            "normal",
            time.monotonic() + 0.01,
            expected_exit=0,
            expected_stage="complete",
        )

    assert caught.value.failure_id == "scenario_timeout"
    assert caught.value.qualification_reason is None
    assert caught.value.qualification_exit_code is None
    assert api.process is not None and api.process.closed_with is True


@pytest.mark.parametrize(
    ("exit_code", "active_processes", "expected_reason"),
    [
        (None, 0, "process_exit_timeout"),
        (0, 1, "qualification_job_drain_failed"),
    ],
)
def test_direct_process_timeout_identifies_exit_or_job_drain(
    tmp_path, monkeypatch, exit_code, active_processes, expected_reason
) -> None:
    process = _FakeProcess(
        exit_code, supervised=False, active_processes=active_processes
    )
    clock = iter((0.0, 1.0))
    monkeypatch.setattr(qualification.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(qualification.time, "sleep", lambda _seconds: None)

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._finish_process_without_receipt(
            process, tmp_path, 1.0, 0
        )

    assert caught.value.failure_id == "scenario_timeout"
    assert caught.value.qualification_reason == expected_reason
    assert caught.value.qualification_exit_code is None


def _concurrent_roots(tmp_path) -> tuple[Path, Path]:
    roots = (tmp_path / "one", tmp_path / "two")
    payload = {
        "schema_version": 1,
        "scenario": "concurrent",
        "stage": "ready",
        "packaged": True,
        "console_none": True,
        "ordinary_user": True,
        "integrity_level": "medium",
    }
    for root in roots:
        root.mkdir()
        (root / qualification.QUALIFICATION_RECEIPT_NAMES["ready"]).write_text(
            json.dumps(payload), encoding="ascii"
        )
    return roots


def test_concurrent_primary_not_exited_is_timeout(tmp_path) -> None:
    processes = (
        _FakeProcess(None, supervised=True),
        _FakeProcess(9, supervised=True),
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._finish_concurrent_processes(
            processes,
            _concurrent_roots(tmp_path),
            (1, 1),
            tmp_path,
            time.monotonic() + 0.01,
        )

    assert caught.value.failure_id == "scenario_timeout"
    assert caught.value.qualification_stage == "concurrent_1"
    assert caught.value.qualification_exit_code is None


def test_concurrent_expected_exit_with_active_descendant_is_timeout(tmp_path) -> None:
    processes = (
        _FakeProcess(9, supervised=True, active_processes=1),
        _FakeProcess(9, supervised=True),
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._finish_concurrent_processes(
            processes,
            _concurrent_roots(tmp_path),
            (1, 1),
            tmp_path,
            time.monotonic() + 0.01,
        )

    assert caught.value.failure_id == "scenario_timeout"
    assert caught.value.qualification_stage == "concurrent_1"
    assert caught.value.qualification_exit_code is None


def test_concurrent_wrong_exit_retains_only_observed_numeric_code(tmp_path) -> None:
    processes = (
        _FakeProcess(7, supervised=True),
        _FakeProcess(9, supervised=True),
    )

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._finish_concurrent_processes(
            processes,
            _concurrent_roots(tmp_path),
            (1, 1),
            tmp_path,
            time.monotonic() + 1,
        )

    assert caught.value.failure_id == "scenario_failed"
    assert caught.value.qualification_stage == "concurrent_1"
    assert caught.value.qualification_reason == "process_exit_mismatch"
    assert caught.value.qualification_exit_code == 7


def test_ui_process_exit_mismatch_retains_observed_numeric_code(tmp_path) -> None:
    process = _FakeProcess(3221225477, supervised=True)

    with pytest.raises(qualification.QualificationFailure) as caught:
        qualification._run_driver_phase(
            "ui_smoke",
            lambda: qualification._finish_process_without_receipt(
                process,
                tmp_path,
                time.monotonic() + 1,
                0,
            ),
        )

    assert caught.value.qualification_stage == "ui_smoke"
    assert caught.value.qualification_reason == "process_exit_mismatch"
    assert caught.value.qualification_exit_code == 3221225477


def test_idle_early_exit_retains_exact_mode_and_numeric_code(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    runner = object.__new__(qualification._QualificationRunner)
    runner.artifact = tmp_path / "artifact"
    runner.state_base = tmp_path / "state"
    runner.application = runner.artifact / "metroliza_application.exe"
    runner.launcher = runner.artifact / "metroliza.exe"
    runner.deadline = time.monotonic() + 1
    runner.api = _FakeApi(3221225477, "ready")
    runner.results = {}
    work = tmp_path / "work"
    for path in (runner.artifact, runner.state_base, work):
        path.mkdir()
    runner._root = lambda _label: work

    with pytest.raises(qualification.QualificationFailure) as caught:
        runner.run_idle()

    assert caught.value.qualification_stage == "direct_idle"
    assert caught.value.qualification_reason == "process_exit_mismatch"
    assert caught.value.qualification_exit_code == 3221225477


def test_platform_and_relative_arguments_fail_without_creating_output(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = qualification.qualify_windows_diagnostics(
        Path("artifact"), Path("output")
    )

    if os.name == "nt":
        assert result.failure_id == "invalid_arguments"
    else:
        assert result == qualification.QualificationResult(
            "failed",
            "unsupported_platform",
            None,
            qualification_stage="runner",
            qualification_reason="unexpected",
        )
    assert not (tmp_path / "output").exists()


def test_qualification_build_pins_observed_onnxruntime_version() -> None:
    requirements = (qualification.REPO_ROOT / "requirements-ocr.txt").read_text(
        encoding="utf-8"
    )
    assert [
        line for line in requirements.splitlines() if line.startswith("onnxruntime")
    ] == ["onnxruntime==1.30.0"]


def _duplicate_native_process_handle(api, process, duplicate) -> None:
    current_process = api.kernel.GetCurrentProcess
    current_process.argtypes = []
    current_process.restype = api.wintypes.HANDLE
    duplicate_handle = api.kernel.DuplicateHandle
    duplicate_handle.argtypes = [
        api.wintypes.HANDLE,
        api.wintypes.HANDLE,
        api.wintypes.HANDLE,
        ctypes.POINTER(api.wintypes.HANDLE),
        api.wintypes.DWORD,
        api.wintypes.BOOL,
        api.wintypes.DWORD,
    ]
    duplicate_handle.restype = api.wintypes.BOOL
    owner = current_process()
    assert duplicate_handle(
        owner,
        process._process,
        owner,
        ctypes.byref(duplicate),
        0,
        False,
        0x00000002,
    )


def _wait_for_native_process_and_job_exit(api, process) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and process.poll() is None:
        time.sleep(0.01)
    assert process.poll() is not None
    while time.monotonic() < deadline and api._job_accounting(process._job)[0]:
        time.sleep(0.01)
    assert api._job_accounting(process._job)[0] == 0


def _native_observation_result(api, process_handle, process_id) -> str:
    try:
        api._process_observation(process_handle, process_id)
    except qualification.QualificationFailure as error:
        assert error.qualification_reason in {
            "native_image_query_unavailable",
            "native_process_times_unavailable",
        }
        return "unavailable"
    return "available"


class _ControlledNativeQueryFailureKernel:
    def __init__(self, real_kernel, process_id, duplicate) -> None:
        self.real_kernel = real_kernel
        self.process_id = process_id
        self.duplicate = duplicate
        self.duplicate_value = duplicate.value
        self.duplicate_open = True
        self.duplicate_closes = 0
        self.image_queries = 0

    def __getattr__(self, name):
        return getattr(self.real_kernel, name)

    def OpenProcess(self, _access, _inherit, observed_process_id):
        assert observed_process_id == self.process_id
        return self.duplicate

    def QueryFullProcessImageNameW(self, *_arguments):
        self.image_queries += 1
        return 0

    def CloseHandle(self, handle):
        value = handle.value if hasattr(handle, "value") else handle
        result = self.real_kernel.CloseHandle(handle)
        if value == self.duplicate_value:
            assert self.duplicate_open
            if result:
                self.duplicate_open = False
                self.duplicate_closes += 1
        return result


def _assert_native_restricted_fallback(
    api, job, handle, initial, executable, monkeypatch
) -> None:
    forced_win32 = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        native_observation=qualification._NativeIdentityObservation(
            None, "image", "false", 5, "alive"
        ),
    )

    def controlled_win32_denial(_handle, _pid):
        raise forced_win32

    assert initial.process_id in api._job_process_ids(job)
    with monkeypatch.context() as context:
        context.setattr(api, "_process_observation", controlled_win32_denial)
        observation = api._observe_job_member(
            handle, initial.process_id, (executable,)
        )
        assert observation.creation_time == initial.creation_time
        assert api._same_requested_image(observation.image, executable)
        wrong_expected = executable.with_name("cmd.exe")
        with pytest.raises(qualification.QualificationFailure) as wrong:
            api._observe_job_member(
                handle, initial.process_id, (wrong_expected,)
            )
        assert wrong.value is forced_win32
        assert wrong.value.native_observation.alternative.api == "image_match"


def _assert_native_restricted_opened_name_fallback(
    api, job, handle, initial, executable, monkeypatch
) -> None:
    # The normalized mismatch is controlled; K32 and the opened-name query are native.
    forced_win32 = qualification.QualificationFailure(
        "scenario_failed", qualification_reason="native_image_query_unavailable",
        native_observation=qualification._NativeIdentityObservation(
            None, "image", "false", 5, "alive"
        ),
    )

    def controlled_win32_denial(_handle, _process_id):
        raise forced_win32

    real_file_name = api._expected_file_name
    name_modes = []

    def force_only_normalized_mismatch(file_handle, *, opened=False):
        name_modes.append("opened" if opened else "normalized")
        if not opened:
            return r"\Device\HarddiskVolume0\controlled-mismatch.exe", None
        return real_file_name(file_handle, opened=True)

    assert initial.process_id in api._job_process_ids(job)
    with monkeypatch.context() as opened_context:
        opened_context.setattr(api, "_process_observation", controlled_win32_denial)
        opened_context.setattr(api, "_expected_file_name", force_only_normalized_mismatch)
        opened_observation = api._observe_job_member(
            handle, initial.process_id, (executable,)
        )
    assert opened_observation == initial
    assert name_modes == ["normalized", "opened"]


def test_restricted_opened_name_control_routes_through_denied_image_query(
    monkeypatch,
):
    api, expected, _primary, calls = _fallback_identity_api(monkeypatch)
    initial = qualification._ProcessObservation(407, 1234, str(expected))
    api._process_observation = lambda *_args: initial
    api._job_process_ids = lambda _job: (407,)
    api._job_accounting = lambda _job: (1, 1)

    _assert_native_restricted_opened_name_fallback(
        api, object(), 77, initial, expected, monkeypatch
    )
    assert api._process_observation(77, 407) is initial
    assert calls == ["k32", "open", "file_name_opened", "close", "times"]


@pytest.mark.skipif(os.name != "nt", reason="native restricted-token proof requires Windows")
def test_native_windows_identity_errors_on_owned_suspended_and_retired_process(
    tmp_path, monkeypatch
) -> None:
    api = qualification._WindowsApi()
    executable = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "whoami.exe"
    original_observe = api._process_observation
    observed = []
    native_anchors = []
    paired_outcomes = []
    assigned_jobs = []
    real_kernel = api.kernel

    class _CaptureAssignedJob:
        def __getattr__(self, name):
            return getattr(real_kernel, name)

        def AssignProcessToJobObject(self, job, handle):
            result = real_kernel.AssignProcessToJobObject(job, handle)
            if result:
                assigned_jobs.append(job)
            return result

    api.kernel = _CaptureAssignedJob()

    def observe_before_resume(handle, process_id):
        initial = original_observe(handle, process_id)
        assert api._native_process_state(handle) == "alive"
        creation_present = initial.creation_time > 0
        image_matches = os.path.normcase(initial.image) == os.path.normcase(str(executable))
        assert creation_present
        assert image_matches
        assert len(assigned_jobs) == 1
        assert process_id in api._job_process_ids(assigned_jobs[0])
        initial_native, native_error = api._native_process_image(handle)
        assert native_error is None
        assert api._valid_native_image_anchor(initial_native)
        native_anchors.append(initial_native)
        fresh_native, fresh_error = api._native_process_image(handle)
        assert fresh_error is None
        same_native_name = (
            qualification.ntpath.normcase(initial_native)
            == qualification.ntpath.normcase(fresh_native)
        )
        assert same_native_name
        monkeypatch.setattr(api, "_process_observation", original_observe)
        try:
            job_observations, active, total = api.job_observations(
                assigned_jobs[0], primary_process=handle, primary_initial=initial,
                primary_native_image=initial_native,
            )
        finally:
            monkeypatch.setattr(api, "_process_observation", observe_before_resume)
        assert initial in job_observations
        assert active >= 1
        assert total >= 1
        assert api._native_process_state(handle) == "alive"
        _assert_native_restricted_fallback(
            api, assigned_jobs[0], handle, initial, executable, monkeypatch
        )
        _assert_native_restricted_opened_name_fallback(
            api, assigned_jobs[0], handle, initial, executable, monkeypatch
        )
        reopened = api.kernel.OpenProcess(0x1000, False, process_id)
        if not reopened:
            paired_outcomes.append("reopen_unavailable")
        else:
            try:
                try:
                    reopened_observation = original_observe(reopened, process_id)
                except qualification.QualificationFailure as failure:
                    assert failure.qualification_reason in {
                        "native_image_query_unavailable", "native_process_times_unavailable"
                    }
                    assert failure.native_observation is not None
                    assert failure.native_observation.api in {"image", "times"}
                    paired_outcomes.append("reopened_query_unavailable")
                else:
                    assert reopened_observation == initial
                    paired_outcomes.append("reopened_matched")
            finally:
                api._require_closed_handles(reopened)
        with pytest.raises(qualification.QualificationFailure) as invalid:
            original_observe(api.wintypes.HANDLE(), 0)
        assert invalid.value.native_observation.api == "image"
        assert invalid.value.native_observation.outcome == "false"
        assert invalid.value.native_observation.winerror == 6
        assert invalid.value.native_observation.process_state == "unknown"
        duplicate = api.duplicate_synchronize_only(handle)
        try:
            with pytest.raises(qualification.QualificationFailure) as denied:
                original_observe(duplicate, process_id)
            assert denied.value.native_observation.api == "image"
            assert denied.value.native_observation.outcome == "false"
            assert denied.value.native_observation.winerror == 5
            assert denied.value.native_observation.process_state == "alive"
        finally:
            api._require_closed_handles(duplicate)
        observed.append(initial)
        return initial

    monkeypatch.setattr(api, "_process_observation", observe_before_resume)
    owned = []
    try:
        environment = qualification._sanitized_environment(
            tmp_path, tmp_path, tmp_path / "state", "normal"
        )
        process = api.launch(executable, environment, tmp_path, owned=owned)
        assert len(native_anchors) == 1
        assert qualification.ntpath.normcase(process._initial_native_image) == (
            qualification.ntpath.normcase(native_anchors[0])
        )
        monkeypatch.setattr(api, "_process_observation", original_observe)
        _wait_for_native_process_and_job_exit(api, process)
        assert api._native_process_state(process._process) == "exited"
        assert len(observed) == 1
        assert paired_outcomes[0] in {
            "reopen_unavailable", "reopened_query_unavailable", "reopened_matched"
        }
        try:
            retired = original_observe(process._process, observed[0].process_id)
        except qualification.QualificationFailure as failure:
            assert failure.native_observation.process_state == "exited"
            assert failure.native_observation.outcome == "false"
            assert type(failure.native_observation.winerror) is int
        else:
            same_identity = retired == observed[0]
            assert same_identity
    finally:
        qualification._close_owned_processes(owned, terminate=True)


@pytest.mark.skipif(os.name != "nt", reason="native restricted-token proof requires Windows")
def test_native_windows_restricted_token_job_launches_without_console(tmp_path, monkeypatch) -> None:
    api = qualification._WindowsApi()
    token = api._restricted_token()
    try:
        assert api._integrity_rid(token) == qualification.MEDIUM_INTEGRITY_RID
    finally:
        api.kernel.CloseHandle(token)
    system_root = Path(os.environ["SYSTEMROOT"])
    executable = system_root / "System32" / "whoami.exe"
    environment = qualification._sanitized_environment(
        tmp_path, tmp_path, tmp_path, "normal"
    )
    # Inspect only this owned Job's rejected member while its handle remains
    # owned. Exact fixed-system-file comparisons never authorize that member.
    rejected_images = []
    original_observe_member = api._observe_job_member

    def observe_member(handle, process_id, expected_images):
        try:
            return original_observe_member(handle, process_id, expected_images)
        except qualification.QualificationFailure as error:
            native, unavailable = api._native_process_image(handle)
            classification = "unavailable" if unavailable is not None else "unknown"
            if unavailable is None:
                for name in ("whoami.exe", "conhost.exe", "WerFault.exe", "wermgr.exe", "OpenConsole.exe"):
                    matches, failed = api._expected_file_native_image(
                        system_root / "System32" / name, native, error
                    )
                    if failed is None and matches:
                        classification = name
                        break
            rejected_images.append(classification)
            raise

    monkeypatch.setattr(api, "_observe_job_member", observe_member)
    process = api.launch(executable, environment, tmp_path)
    try:
        deadline = time.monotonic() + 10
        exit_code = None
        while time.monotonic() < deadline:
            process.observe()
            exit_code = process.poll()
            if exit_code is not None:
                break
            time.sleep(0.02)
        assert exit_code == 0, {"native_whoami_exit_code": exit_code}
        process.observe()
        while time.monotonic() < deadline and process.active_processes() != 0:
            time.sleep(0.02)
        assert process.active_processes() == 0
        assert process.metrics().peak_job_memory_bytes >= 0
    except qualification.QualificationFailure as error:
        # Retain only the existing fixed-schema observer detail. This remains
        # a failing gate; raw image paths, PID and exception text stay private.
        detail = error.native_observation
        # Query only the already-owned primary handle, without an extra wait.
        try:
            primary_exit = process.poll()
        except qualification.QualificationFailure:
            primary_exit = "unavailable"
        pytest.fail("native_token_job_observation=" + json.dumps({
            "rejected_images": rejected_images[:16],
            "primary_exit_code": primary_exit,
            "reason": error.qualification_reason,
            "native_observation": detail.receipt() if detail is not None else None,
        }, sort_keys=True), pytrace=False)
    finally:
        process.close(terminate=exit_code is None)


@pytest.mark.skipif(os.name != "nt", reason="native Job race proof requires Windows")
def test_native_windows_hybrid_stale_job_snapshot_closes_disappeared_query_handle(
    tmp_path,
) -> None:
    api = qualification._WindowsApi()
    system_root = Path(os.environ["SYSTEMROOT"])
    executable = system_root / "System32" / "whoami.exe"
    environment = qualification._sanitized_environment(
        tmp_path, tmp_path, tmp_path, "normal"
    )
    owned = []
    real_kernel = None
    duplicate = None
    controlled_kernel = None
    drained = False
    try:
        process = api.launch(executable, environment, tmp_path, owned=owned)
        real_kernel = api.kernel
        duplicate = api.wintypes.HANDLE()
        _duplicate_native_process_handle(api, process, duplicate)
        process_id = next(iter(process._observations))
        _wait_for_native_process_and_job_exit(api, process)
        drained = True
        assert process_id not in api._job_process_ids(process._job)
        actual_query_result = _native_observation_result(
            api, duplicate, process_id
        )
        controlled_kernel = _ControlledNativeQueryFailureKernel(
            real_kernel, process_id, duplicate
        )
        original_process_ids = api._job_process_ids
        snapshots = []

        def stale_then_current(job):
            snapshots.append(None)
            if len(snapshots) == 1:
                return (process_id,)
            return original_process_ids(job)

        api.kernel = controlled_kernel
        api._job_process_ids = stale_then_current

        observations, active, assigned = api.job_observations(process._job)

        assert actual_query_result in {"available", "unavailable"}
        assert observations == ()
        assert active == 0
        assert assigned >= 1
        assert snapshots == [None, None]
        assert controlled_kernel.image_queries == 1
        assert controlled_kernel.duplicate_closes == 1
        assert not controlled_kernel.duplicate_open
    finally:
        try:
            if (
                real_kernel is not None
                and duplicate is not None
                and duplicate.value
                and (controlled_kernel is None or controlled_kernel.duplicate_open)
            ):
                assert real_kernel.CloseHandle(duplicate)
        finally:
            qualification._close_owned_processes(
                owned, terminate=not drained
            )


@pytest.mark.skipif(os.name != "nt", reason="native User32 window proof requires Windows")
def test_native_windows_matches_and_closes_test_owned_qt_main_window() -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow

    application = QApplication.instance() or QApplication([])
    assert application.platformName() == "windows"
    window = QMainWindow()
    title = f"Metroliza [native-test-{uuid.uuid4().hex}]"
    window.setWindowTitle(title)
    window.show()
    modal = QDialog(None)
    modal.setWindowModality(Qt.WindowModality.ApplicationModal)
    modal.show()
    application.processEvents()
    api = qualification._WindowsApi()
    observations = (
        qualification._ProcessObservation(os.getpid(), 1, sys.executable),
    )
    try:
        assert not api.user.IsWindowEnabled(int(window.winId()))
        assert api.normal_window(observations, Path(sys.executable), title) is None
        modal.close()
        application.processEvents()
        assert api.user.IsWindowEnabled(int(window.winId()))
        handle = api.normal_window(observations, Path(sys.executable), title)
        assert handle is not None
        api.close_normal_window(
            observations, Path(sys.executable), title, handle
        )
        deadline = time.monotonic() + 2
        while window.isVisible() and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        assert not window.isVisible()
    finally:
        modal.close()
        window.close()
        application.processEvents()


@pytest.mark.parametrize("observed_kind", ["exact", "null", "outside", "changed", "short"])
def test_private_token_default_dacl_requires_nonnull_exact_readback(observed_kind):
    from types import SimpleNamespace

    api = object.__new__(qualification._WindowsApi)
    acl = ctypes.create_string_buffer(b"fixed-private-acl")
    api._private_default_acl = lambda token: acl
    observed = ctypes.create_string_buffer(ctypes.sizeof(ctypes.c_void_p) + len(acl))
    acl_address = ctypes.addressof(observed) + ctypes.sizeof(ctypes.c_void_p)
    ctypes.memmove(acl_address, acl, len(acl))
    ctypes.cast(observed, ctypes.POINTER(ctypes.c_void_p))[0] = acl_address
    if observed_kind == "null":
        ctypes.cast(observed, ctypes.POINTER(ctypes.c_void_p))[0] = None
    elif observed_kind == "outside":
        ctypes.cast(observed, ctypes.POINTER(ctypes.c_void_p))[0] = 1
    elif observed_kind == "changed":
        ctypes.memset(acl_address, 0, len(acl))
    elif observed_kind == "short":
        observed = ctypes.create_string_buffer(1)
    api._token_information = lambda token, kind: observed
    applied = []

    def apply(token, kind, pointer, size):
        assert token == 17
        assert kind == qualification.TOKEN_DEFAULT_DACL
        assert size == ctypes.sizeof(ctypes.c_void_p)
        acl_pointer = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        assert acl_pointer
        applied.append(ctypes.string_at(acl_pointer, len(acl)))
        return True

    api.advapi = SimpleNamespace(SetTokenInformation=apply)
    if observed_kind == "exact":
        api._set_private_default_dacl(17)
    else:
        with pytest.raises(qualification.QualificationFailure, match="restricted_launch_unavailable"):
            api._set_private_default_dacl(17)
    assert applied == [acl.raw]


def test_private_token_default_dacl_rejects_failed_apply_before_query():
    from types import SimpleNamespace

    api = object.__new__(qualification._WindowsApi)
    api._private_default_acl = lambda token: ctypes.create_string_buffer(b"private")
    api.advapi = SimpleNamespace(SetTokenInformation=lambda *args: False)
    api._token_information = lambda *args: pytest.fail("failed apply must not become acceptance")
    with pytest.raises(qualification.QualificationFailure, match="restricted_launch_unavailable"):
        api._set_private_default_dacl(17)


@pytest.mark.parametrize("reported", [0, 257])
def test_token_information_rejects_unbounded_allocation(reported):
    from types import SimpleNamespace

    api = object.__new__(qualification._WindowsApi)
    api.wintypes = _TokenWinTypes

    def query(token, kind, output, length, required):
        assert output is None
        ctypes.cast(required, ctypes.POINTER(ctypes.c_uint32))[0] = reported
        return False

    api.advapi = SimpleNamespace(GetTokenInformation=query)
    with pytest.raises(qualification.QualificationFailure, match="restricted_launch_unavailable"):
        api._token_information(17, qualification.TOKEN_USER)


def test_failed_topology_emits_only_closed_counts_and_roles(capsys):
    record = {
        "launcher_processes_observed": 0, "application_processes_observed": 1,
        "unexpected_processes_observed": 1, "assigned_processes": 2,
        "max_active_processes": 2, "creation_order": ["application", "unexpected"],
        "all_processes_exited": True,
    }
    with pytest.raises(qualification.QualificationFailure) as failure:
        qualification._validate_topology_record(record, supervised=False)
    assert failure.value.qualification_reason == "qualification_topology_failed"
    observed = capsys.readouterr().err.strip().split("=", 1)[1]
    assert json.loads(observed) == record
    record.update(creation_order=["PRIVATE_PATH"], assigned_processes=True,
                  application_processes_observed=100000, private="PRIVATE_PATH")
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_topology_record(record, supervised=False)
    output = capsys.readouterr().err
    assert "PRIVATE_PATH" not in output
    safe = json.loads(output.strip().split("=", 1)[1])
    assert safe["creation_order"] == safe["assigned_processes"] == "invalid"
    assert safe["application_processes_observed"] == "invalid"

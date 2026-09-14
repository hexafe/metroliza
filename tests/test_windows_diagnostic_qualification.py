from __future__ import annotations

import ctypes
import hashlib
import json
import os
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


class _TokenWinTypes:
    HANDLE = ctypes.c_void_p
    BOOL = ctypes.c_long
    BYTE = ctypes.c_ubyte
    DWORD = ctypes.c_uint32


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
    monkeypatch.setattr(qualification.ctypes, "byref", lambda value: value)

    with pytest.raises(failure_type) as caught:
        api._restricted_token()

    assert caught.value is primary
    assert closed == [1, 2]


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


def test_driver_phase_preserves_safe_early_process_exit_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    class _NoReceiptApi(_FakeApi):
        def launch(self, executable, environment, cwd):
            process = super().launch(executable, environment, cwd)
            (cwd / "startup.json").unlink()
            (cwd / qualification.QUALIFICATION_RECEIPT_NAMES[self.stage]).unlink()
            return process

    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
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


def test_job_observation_keeps_other_open_failures_fatal(monkeypatch) -> None:
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

    with pytest.raises(qualification.QualificationFailure):
        api.job_observations(object())


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

    with pytest.raises(qualification.QualificationFailure):
        api.job_observations(object())


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
    tmp_path, monkeypatch
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

    def fail_payload(*_arguments, **_keywords):
        raise qualification.QualificationFailure("scenario_failed")

    monkeypatch.setattr(qualification, "_success_payload", fail_payload)
    with pytest.raises(qualification.QualificationFailure) as caught:
        runner.run({}, source, output)

    assert caught.value.qualification_stage == "receipt"
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

    def launch(self, executable, environment, cwd):
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


@pytest.mark.skipif(os.name != "nt", reason="native restricted-token proof requires Windows")
def test_native_windows_restricted_token_job_launches_without_console(tmp_path) -> None:
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
    process = api.launch(executable, environment, tmp_path)
    try:
        deadline = time.monotonic() + 10
        exit_code = None
        while time.monotonic() < deadline:
            exit_code = process.poll()
            if exit_code is not None:
                break
            time.sleep(0.02)
        assert exit_code is not None
        assert process.metrics().peak_job_memory_bytes >= 0
    finally:
        process.close(terminate=exit_code is None)

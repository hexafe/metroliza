"""Bounded native proof for the PowerShell capture completion boundary.

The retained-pipe case proves a generic harness hazard. It does not attribute
the historical ``pwsh-pass-0`` timeout, whose cause remains unknown.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from types import SimpleNamespace
import uuid

import pytest

from tests import windows_ocr_process as process
from tests.windows_ocr_process import run_owned


ROOT = Path(__file__).resolve().parents[1]
PY_FIXTURE = Path(__file__).with_name("windows_ocr_fixture.py")
PS_FIXTURE = Path(__file__).parent / "fixtures/windows_wrapper_pipe_fixture.ps1"
_NATIVE = pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows")
_RECEIPTS = "METROLIZA_WRAPPER_RECEIPTS"
_REASONS = {
    "completed", "timeout", "cancelled", "containment_unavailable", "startup_failed",
    "assignment_failed", "resume_failed", "not_completed", "output_limit",
}


@pytest.fixture(params=["powershell", "pwsh"])
def powershell(request):
    executable = shutil.which(request.param)
    if executable is None:
        pytest.fail(f"Required native Windows shell unavailable: {request.param}")
    return executable


class _Abort(BaseException):
    pass


class _Kernel:
    def WaitForSingleObject(self, _handle, _milliseconds):
        return 0


class _Child:
    def __init__(self):
        self._handle = None
        self.returncode = None
        self.killed = False
        self.closed = 0

    def start(self, *_args, **_kwargs):
        self._handle = 41

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = 1

    def close(self):
        self.closed += 1
        self._handle = None


class _Job:
    def __init__(self, *, assign_error=None, resume_error=None):
        self.assign_error = assign_error
        self.resume_error = resume_error
        self.kernel = _Kernel()
        self.closed = 0

    def assign(self, _child):
        if self.assign_error:
            raise self.assign_error

    def _drain_members(self, _deadline):
        pass

    def _terminate_job(self, _deadline):
        self.child.kill()

    def close(self):
        self.closed += 1


def _mock_owned(monkeypatch, job):
    child = _Child()
    job.child = child
    monkeypatch.setattr(process, "os", SimpleNamespace(name="nt", fstat=os.fstat))
    monkeypatch.setattr(process.contract, "_WindowsJob", lambda: job)
    monkeypatch.setattr(process, "_SuspendedChild", lambda *_args: child)

    def resume_exact(_child, _job):
        if job.resume_error:
            raise job.resume_error

    monkeypatch.setattr(process, "_resume_exact", resume_exact)
    return child


@pytest.mark.parametrize(
    "failure,reason",
    [(OSError("start"), "assignment_failed"), (OSError("resume"), "resume_failed")],
)
def test_owned_failures_close_retained_job_and_process(monkeypatch, failure, reason):
    kwargs = {"assign_error": failure} if reason == "assignment_failed" else {
        "resume_error": failure
    }
    job = _Job(**kwargs)
    child = _mock_owned(monkeypatch, job)
    result = run_owned(["synthetic"], cwd=None, env=None, timeout_s=1, cleanup_timeout_s=1)
    assert result.reason == reason
    assert result.cleanup_complete and result.tree_empty
    assert job.closed == child.closed == 1 and child.killed


def test_owned_unexpected_base_exception_cleans_up_then_reraises(monkeypatch):
    job = _Job(resume_error=_Abort())
    child = _mock_owned(monkeypatch, job)
    with pytest.raises(_Abort):
        run_owned(["synthetic"], cwd=None, env=None, timeout_s=1, cleanup_timeout_s=1)
    assert job.closed == child.closed == 1 and child.killed


def test_owned_cancellation_closes_tree_once(monkeypatch):
    job, cancel = _Job(), threading.Event()
    child = _mock_owned(monkeypatch, job)
    cancel.set()
    result = run_owned(
        ["synthetic"], cwd=None, env=None, timeout_s=1, cleanup_timeout_s=1,
        cancel_event=cancel,
    )
    assert result.reason == "cancelled"
    assert result.cleanup_complete and result.tree_empty
    assert job.closed == child.closed == 1 and child.killed


def test_start_failure_closes_fresh_job(monkeypatch):
    job = _Job()
    child = _mock_owned(monkeypatch, job)

    def fail_start(*_args, **_kwargs):
        raise OSError

    monkeypatch.setattr(child, "start", fail_start)
    result = run_owned(["synthetic"], cwd=None, env=None, timeout_s=1, cleanup_timeout_s=1)
    assert result.reason == "startup_failed"
    assert result.cleanup_complete and result.tree_empty
    assert job.closed == child.closed == 1 and not child.killed


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), OSError(), _Abort()])
def test_interrupted_creation_retains_suspended_child_for_cleanup(monkeypatch, failure):
    job = _Job()
    child = _mock_owned(monkeypatch, job)

    def interrupted_start(*_args, **_kwargs):
        child._handle = 41  # Native creation wrote the already-owned output slot.
        raise failure

    monkeypatch.setattr(child, "start", interrupted_start)
    if isinstance(failure, _Abort):
        with pytest.raises(_Abort):
            run_owned(["synthetic"], cwd=None, env=None, timeout_s=1, cleanup_timeout_s=1)
    else:
        result = run_owned(["synthetic"], cwd=None, env=None, timeout_s=1, cleanup_timeout_s=1)
        assert result.reason == (
            "cancelled" if isinstance(failure, KeyboardInterrupt) else "startup_failed"
        )
        assert result.cleanup_complete and result.tree_empty
    assert child.killed and job.closed == child.closed == 1


def test_failed_handle_close_cannot_publish_completed(monkeypatch):
    job = _Job()
    child = _mock_owned(monkeypatch, job)
    child.returncode = 0

    def fail_close():
        raise OSError("close_failed")

    monkeypatch.setattr(child, "close", fail_close)
    result = run_owned(["synthetic"], cwd=None, env=None, timeout_s=1, cleanup_timeout_s=1)
    assert result.reason == "not_completed" and not result.cleanup_complete


class _NativeFunction:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


def _identity_kernel(order=(41, 43), *, mismatch=None):
    resumed, enumerated = [], []
    position = iter(order)

    def entry(_snapshot, pointer):
        enumerated.append(True)
        tid = next(position, None)
        if tid is None:
            return False
        pointer._obj.owner, pointer._obj.thread_id = 123, tid
        return True

    def in_job(_process, _job, pointer):
        pointer._obj.value = mismatch != "membership_false"
        return mismatch != "membership_unavailable"

    def resume(thread):
        resumed.append(thread)
        return {"count_zero": 0, "count_two": 2, "resume_failed": 0xffffffff}.get(mismatch, 1)

    functions = {
        "WaitForSingleObject": lambda handle, _: (
            0 if (handle, mismatch) in {(61, "process_dead"), (41, "thread_dead")} else 258
        ),
        "IsProcessInJob": in_job,
        "GetThreadId": lambda _: 43 if mismatch == "thread_id" else 41,
        "GetProcessIdOfThread": lambda _: 124 if mismatch == "process_id" else 123,
        "ResumeThread": resume,
        # Available to the old algorithm: both owned candidates have count one.
        "CreateToolhelp32Snapshot": lambda *_: 71,
        "Thread32First": entry, "Thread32Next": entry,
        "OpenThread": lambda _rights, _inherit, tid: tid,
        "CloseHandle": lambda _: True,
    }
    kernel = SimpleNamespace(**{
        name: _NativeFunction(callback) for name, callback in functions.items()
    })
    child = SimpleNamespace(pid=123, _handle=61, primary_thread=41, primary_thread_id=41)
    return child, SimpleNamespace(kernel=kernel, handle=81), resumed, enumerated


@pytest.mark.parametrize("order", [(41, 43), (43, 41)], ids=["primary-first", "secondary-first"])
def test_resume_uses_creation_primary_thread_independently_of_snapshot_order(order):
    child, job, resumed, enumerated = _identity_kernel(order)
    process._resume_exact(child, job)
    # Independent origin fact: CreateProcess designated 41, even when 43 is
    # first in the snapshot, belongs to the same process, and has count one.
    assert resumed == [41]
    assert not enumerated


@pytest.mark.parametrize("mismatch", [
    "thread_id", "process_id", "thread_dead", "process_dead", "membership_false",
    "membership_unavailable", "count_zero", "count_two", "resume_failed",
])
def test_resume_rejects_invalid_retained_identity_or_suspend_state(mismatch):
    child, job, resumed, enumerated = _identity_kernel(mismatch=mismatch)
    with pytest.raises(OSError, match="resume_failed"):
        process._resume_exact(child, job)
    assert resumed == ([41] if mismatch in {"count_zero", "count_two", "resume_failed"} else [])
    assert not enumerated


@pytest.mark.parametrize("failed_handle", [None, 41, 61])
def test_native_child_closes_both_retained_handles_even_if_one_close_fails(failed_handle):
    closed = []

    def close(handle):
        closed.append(handle)
        return handle != failed_handle

    child = process._SuspendedChild(SimpleNamespace(CloseHandle=close))
    child.info.thread, child.info.process = 41, 61
    if failed_handle is None:
        child.close()
        child.close()
        assert child.primary_thread is None and child._handle is None
    else:
        with pytest.raises(OSError, match="handle_close_failed"):
            child.close()
    assert closed == [41, 61]


@pytest.mark.parametrize("failure", [
    None, "interrupt", "duplicate_first", "duplicate_second", "initialize", "update", "create",
])
@pytest.mark.parametrize("capture", [False, True])
def test_creation_owns_output_slots_and_inherits_only_selected_streams(
    monkeypatch, tmp_path, failure, capture,
):
    """Exercise the actual launch path against a recording API, without processes."""
    observed = {"duplicates": [], "closed": [], "attributes_deleted": 0}
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda fd: fd))

    def duplicate(_owner, source, _target, pointer, _access, inherit, options):
        assert inherit and options == 2
        observed["duplicates"].append(source)
        if (failure, len(observed["duplicates"])) in {
            ("duplicate_first", 1), ("duplicate_second", 2),
        }:
            return False
        pointer._obj.value = 100 + len(observed["duplicates"])
        return True

    def initialize(attributes, count, _flags, size):
        assert count == 1
        size._obj.value = 64
        return attributes is not None and failure != "initialize"

    def update(_attributes, _flags, attribute, handles, _size, _previous, _returned):
        assert attribute == 0x20002
        observed["inherited"] = list(handles)
        return failure != "update"

    def delete(_attributes):
        observed["attributes_deleted"] += 1

    def create(_app, _command, process_security, thread_security, inherit, flags,
               environment, _cwd, startup, info):
        assert process_security is thread_security is None
        assert inherit and flags == 0x80404
        assert "".join(environment) == "A=synthetic\0\0"
        assert startup._obj.startup.flags == 0x100
        assert [startup._obj.startup.stdin, startup._obj.startup.stdout,
                startup._obj.startup.stderr] == observed["inherited"] == [101, 102, 103]
        if failure == "create":
            return False
        info._obj.process, info._obj.thread = 61, 41
        info._obj.pid, info._obj.tid = 123, 41
        if failure == "interrupt":
            raise KeyboardInterrupt
        return True

    def close(handle):
        observed["closed"].append(handle)
        return True

    functions = {
        "GetCurrentProcess": lambda: 71, "DuplicateHandle": duplicate,
        "InitializeProcThreadAttributeList": initialize,
        "UpdateProcThreadAttribute": update, "DeleteProcThreadAttributeList": delete,
        "CreateProcessW": create, "CloseHandle": close,
    }
    kernel = SimpleNamespace(**{
        name: _NativeFunction(callback) for name, callback in functions.items()
    })
    child = process._SuspendedChild(kernel)
    with (tmp_path / "stdout").open("w+b") as stdout, (tmp_path / "stderr").open("w+b") as stderr:
        kwargs = {"cwd": None, "env": {"A": "synthetic"},
                  "stdout_target": stdout if capture else None,
                  "stderr_target": stderr if capture else None}
        if failure:
            with pytest.raises(KeyboardInterrupt if failure == "interrupt" else OSError):
                child.start(["synthetic"], **kwargs)
        else:
            child.start(["synthetic"], **kwargs)
        assert not stdout.closed and not stderr.closed
        if capture and len(observed["duplicates"]) == 3:
            assert observed["duplicates"][1:] == [stdout.fileno(), stderr.fileno()]
    created = failure in {None, "interrupt"}
    assert child._handle == (61 if created else None)
    assert child.primary_thread == (41 if created else None)
    assert child.pid == (123 if created else 0) and child.primary_thread_id == (41 if created else 0)
    duplicated = {"duplicate_first": [], "duplicate_second": [101]}.get(failure, [101, 102, 103])
    assert observed["closed"] == duplicated
    assert observed["attributes_deleted"] == (
        0 if failure in {"duplicate_first", "duplicate_second", "initialize"} else 1
    )
    child.close()
    assert observed["closed"] == duplicated + ([41, 61] if created else [])


class _NoReadCapture:
    def __init__(self, target):
        self.target = target
        self.read_called = False

    def fileno(self):
        return self.target.fileno()

    def tell(self):
        return self.target.tell()

    def read(self, *_args, **_kwargs):
        self.read_called = True
        raise AssertionError("capture bytes must not be read by the guard")


def test_output_over_limit_is_bounded_without_reading_capture(monkeypatch, tmp_path):
    job = _Job()
    child = _mock_owned(monkeypatch, job)
    with (tmp_path / "bounded-capture").open("w+b") as raw:
        capture = _NoReadCapture(raw)

        def write_flood(*_args, **_kwargs):
            child._handle = 41
            raw.write(b"x" * 33)
            raw.flush()

        monkeypatch.setattr(child, "start", write_flood)
        result = run_owned(
            ["synthetic"], cwd=None, env=None, timeout_s=1, cleanup_timeout_s=1,
            stdout_target=capture, output_limit=32,
        )
    assert result.reason == "output_limit" and result.output_limited
    assert result.cleanup_complete and result.tree_empty and not capture.read_called


def _event() -> str:
    return "Local\\metroliza_1043_" + uuid.uuid4().hex


def _write_config(
    root: Path,
    scenario: str,
    state: Path,
    events: dict[str, str],
    expected_types: tuple[int, ...],
    *,
    cancel: bool = False,
) -> Path:
    config = root / "fixture-config.json"
    config.write_text(
        json.dumps({
            **events,
            "python": sys.executable,
            "child": str(PY_FIXTURE),
            "root": str(root),
            "state": str(state),
            "phase": str(root / "phase.jsonl"),
            "stdout": str(root / "fixture.stdout"),
            "stderr": str(root / "fixture.stderr"),
            "scenario": scenario,
            "expected_types": list(expected_types),
            "cancel": cancel,
            "parent_pid": 0,
        }, separators=(",", ":")),
        encoding="utf-8",
    )
    return config


def _read_records(path: Path, *, allow_partial_final: bool = False) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    records = []
    for index, line in enumerate(lines):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # Owned cleanup may stop the optional state append mid-write. Never
            # hide a malformed completed line, or damage to an earlier record.
            if allow_partial_final and index == len(lines) - 1 and not line.endswith("\n"):
                break
            raise
    return records


def _read_optional(path: Path, *, allow_partial_final: bool = False) -> list[dict]:
    try:
        return _read_records(path, allow_partial_final=allow_partial_final)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []


@pytest.mark.parametrize('tail,expected_prefix', [
    ('{"schema_version":1,"stage":"parent_exi', True),
    ('{"schema_version":1,"stage":"parent_exi\n', False),
    ('invalid\n{"schema_version":1}', False),
])
def test_state_reader_preserves_only_unfinished_final_append(tmp_path, tail, expected_prefix):
    ready = {"schema_version": 1, "stage": "child_ready", "parent_live": True}
    path = tmp_path / "state.jsonl"
    path.write_text(json.dumps(ready) + "\n" + tail, encoding="utf-8")
    assert _read_optional(path, allow_partial_final=True) == ([ready] if expected_prefix else [])
    assert _read_optional(path) == []


def _read_phase(path: Path) -> str:
    try:
        rows = _read_records(path, allow_partial_final=True)
    except FileNotFoundError:
        return "unobserved"
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "fixture_mismatch"
    stages = ("shell_initialized", "native_factory_ready", "child_created")
    expected = [{"schema_version": 1, "stage": stage} for stage in stages]
    if not rows:
        return "unobserved"
    if len(rows) <= len(expected) and rows == expected[:len(rows)]:
        return stages[len(rows) - 1]
    return "fixture_mismatch"


@pytest.mark.parametrize('rows,expected', [
    ([], "unobserved"),
    ([{"schema_version": 1, "stage": "shell_initialized"}], "shell_initialized"),
    ([{"schema_version": 1, "stage": "native_factory_ready"}], "fixture_mismatch"),
    ([{"schema_version": 1, "stage": "SYNTHETIC_PRIVATE_CANARY"}], "fixture_mismatch"),
    ([{"schema_version": 1, "stage": "shell_initialized", "extra": True}], "fixture_mismatch"),
])
def test_phase_reader_requires_closed_ordered_records(tmp_path, rows, expected):
    path = tmp_path / "phase.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert _read_phase(path) == expected


def test_phase_reader_retains_complete_prefix_only(tmp_path):
    path = tmp_path / "phase.jsonl"
    records = [{"schema_version": 1, "stage": stage} for stage in
               ("shell_initialized", "native_factory_ready", "child_created")]
    for length in (2, 3):
        text = "".join(json.dumps(row) + "\n" for row in records[:length])
        path.write_text(text + '{"stage":', encoding="utf-8")
        assert _read_phase(path) == records[length - 1]["stage"]
    path.write_text(text + '{"stage":\n', encoding="utf-8")
    assert _read_phase(path) == "fixture_mismatch"


def _record(shell, scenario, result, ready=None, probe=(), outcome=(), phase="unobserved"):
    directory = os.environ.get(_RECEIPTS)
    if not directory:
        return
    name = Path(shell).name.lower().removesuffix(".exe")
    timeout = next((row for row in probe if row.get("stage") == "timeout_before_kill"), {})
    ready = ready or {}
    final = outcome[-1] if outcome else {}
    shell_state = timeout.get("shell_state", "unobserved")
    if shell_state not in {"exited", "live", "wait_failed"}:
        shell_state = "unobserved"
    fixture_stage = ready.get("stage", "unobserved")
    if scenario == "preflight" and ready.get("descendant_in_job") is True:
        fixture_stage = "child_ready"
    if fixture_stage not in {"child_ready", "shell_ready", "fixture_mismatch"}:
        fixture_stage = "unobserved"
    invoke_state = {
        "invoke_returned": "returned",
        "timeout_returned": "timeout_returned",
        "invoke_failed": "failed",
    }.get(final.get("stage"), "unobserved")
    raw_invoke_reason = final.get("reason")
    invoke_reason = (
        raw_invoke_reason
        if type(raw_invoke_reason) is str and raw_invoke_reason in _REASONS
        else "unobserved"
    )
    cleanup_values = (final.get("cleanup_complete"), final.get("tree_empty"))
    if all(type(value) is bool for value in cleanup_values):
        invoke_cleanup = (
            "complete" if all(value is True for value in cleanup_values) else "incomplete"
        )
    else:
        invoke_cleanup = "unobserved"
    raw_code = final.get("returncode")
    invoke_exit_code = raw_code if type(raw_code) is int and -(2**31) <= raw_code < 2**32 else None
    raw_process_code = final.get("process_returncode")
    invoke_process_exit_code = (
        raw_process_code
        if type(raw_process_code) is int and -(2**31) <= raw_process_code < 2**32
        else None
    )
    outer_exit_code = result.returncode if type(result.returncode) is int else None
    if scenario == "preflight":
        fixture_ready = all(ready.get(key) is True for key in (
            "assigned_before_code", "descendant_ready", "descendant_in_job",
        ))
    else:
        expected_stage = "shell_ready" if scenario == "live_shell" else "child_ready"
        fixture_ready = fixture_stage == expected_stage
    fixture_phase = phase if phase in {
        "unobserved", "shell_initialized", "native_factory_ready", "child_created",
    } else "fixture_mismatch"
    expected_phase = "shell_initialized" if scenario == "live_shell" else "child_created"
    completed = (
        result.reason == "completed" and outer_exit_code == 0
        and result.cleanup_complete and result.tree_empty and fixture_ready
        and (
            scenario == "preflight"
            or (
                fixture_phase == expected_phase
                and invoke_state == "returned" and invoke_exit_code == 0
                and invoke_process_exit_code == 0
                and invoke_reason == "completed" and invoke_cleanup == "complete"
                and final.get("output_limited") is False
            )
        )
    )
    receipt = {
        "schema_version": 1,
        "shell": name if name in {"python", "powershell", "pwsh"} else "unknown",
        "scenario": scenario,
        "stage": "completion",
        "result": "completed" if completed else "bounded_failure",
        # The reason belongs to the outer guard; both process exits remain explicit.
        "reason": result.reason if result.reason in _REASONS else "not_completed",
        "elapsed_ms": max(0, min(60000, round(result.elapsed_s * 1000))),
        "shell_exited_before_timeout": timeout.get("shell_state") == "exited",
        "stdout_pipe": ready.get("stdout_pipe") is True,
        "stderr_pipe": ready.get("stderr_pipe") is True,
        "shell_state": shell_state,
        "fixture_stage": fixture_stage,
        "fixture_phase": fixture_phase,
        "invoke_state": invoke_state,
        "invoke_reason": invoke_reason,
        "invoke_cleanup": invoke_cleanup,
        "cleanup_complete": result.cleanup_complete,
        "outer_exit_code": outer_exit_code,
        "invoke_exit_code": invoke_exit_code,
        "invoke_process_exit_code": invoke_process_exit_code,
    }
    target = Path(directory) / "windows-ocr-wrapper-receipts.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt, separators=(",", ":")) + "\n")


@_NATIVE
def test_00_native_containment_preflight(tmp_path):
    state = tmp_path / "preflight.json"
    result = run_owned(
        [sys.executable, "-I", "-S", str(PY_FIXTURE), "preflight", str(state)],
        cwd=tmp_path, env=os.environ.copy(), timeout_s=8, cleanup_timeout_s=5,
    )
    state_records = _read_optional(state)
    _record("python", "preflight", result, state_records[0] if state_records else {})
    assert state_records == [{
        "schema_version": 1,
        "assigned_before_code": True,
        "descendant_ready": True,
        "descendant_in_job": True,
    }]
    assert result.reason == "completed" and result.returncode == 0
    assert result.cleanup_complete and result.tree_empty


@_NATIVE
def test_native_resumed_thread_matches_child_initial_thread(monkeypatch, tmp_path):
    observed = {}
    original_resume = process._resume_exact

    def observe_resume(child, job):
        observed["pid"] = child.pid
        observed["tid"] = child.primary_thread_id
        original_resume(child, job)

    monkeypatch.setattr(process, "_resume_exact", observe_resume)
    # The base interpreter is the executable under test, avoiding a venv
    # redirector whose Python code would correctly run in a different process.
    result = run_owned(
        [sys._base_executable, "-I", "-S", "-c",
         "import ctypes,json,os; from pathlib import Path; "
         "ctypes.windll.kernel32.GetCurrentThreadId.restype=ctypes.c_uint32; "
         "Path('identity.json').write_text(json.dumps({'pid':os.getpid(),"
         "'tid':ctypes.windll.kernel32.GetCurrentThreadId()}),encoding='ascii')"],
        cwd=tmp_path, env=os.environ.copy(), timeout_s=8, cleanup_timeout_s=5,
    )
    assert result.reason == "completed" and result.returncode == 0
    assert result.cleanup_complete and result.tree_empty
    identity = json.loads((tmp_path / "identity.json").read_text(encoding="ascii"))
    assert identity == observed and identity["tid"] > 0


@_NATIVE
def test_native_interrupted_creation_cleans_unresumed_primary_thread(monkeypatch, tmp_path):
    original_start = process._SuspendedChild.start
    children = []

    def interrupted_start(child, *args, **kwargs):
        children.append(child)
        original_start(child, *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(process._SuspendedChild, "start", interrupted_start)
    result = run_owned(
        [sys._base_executable, "-I", "-S", "-c",
         "from pathlib import Path; Path('must-not-run').touch()"],
        cwd=tmp_path, env=os.environ.copy(), timeout_s=8, cleanup_timeout_s=5,
    )
    assert result.reason == "cancelled" and result.cleanup_complete and result.tree_empty
    assert not (tmp_path / "must-not-run").exists()
    assert len(children) == 1
    assert children[0]._handle is None and children[0].primary_thread is None


def _run_scenario(
    shell: str,
    root: Path,
    scenario: str,
    *,
    expected_types: tuple[int, ...],
    cancel: bool = False,
):
    state = root / "state.jsonl"
    probe_path = root / "timeout-probe.jsonl"
    outcome_path = root / "invoke-outcome.jsonl"
    events = {name: _event() for name in ("ready", "release", "exited", "hold")}
    config = _write_config(root, scenario, state, events, expected_types, cancel=cancel)
    stop, observed = threading.Event(), {}

    def observer():
        while not stop.is_set():
            records = _read_optional(state, allow_partial_final=True)
            if any(row.get("stage") in {"child_ready", "shell_ready"} for row in records):
                observed["ns"] = time.monotonic_ns()
                return
            stop.wait(0.005)

    watcher = threading.Thread(target=observer, daemon=True)
    watcher.start()
    started = time.monotonic_ns()
    result = run_owned(
        [
            sys.executable, "-I", str(PY_FIXTURE), "driver", str(ROOT), shell,
            str(PS_FIXTURE), str(config), str(probe_path), str(outcome_path),
        ],
        cwd=root, env=os.environ.copy(), timeout_s=22, cleanup_timeout_s=5,
    )
    stop.set()
    watcher.join(timeout=1)
    records = _read_optional(state, allow_partial_final=True)
    probe = _read_optional(probe_path)
    outcome = _read_optional(outcome_path)
    phase = _read_phase(root / "phase.jsonl")
    _record(shell, scenario, result, records[0] if records else {}, probe, outcome, phase)
    assert phase == ("shell_initialized" if scenario == "live_shell" else "child_created")
    assert result.cleanup_complete and result.tree_empty
    assert math.isfinite(result.elapsed_s) and result.elapsed_s <= 27.5
    assert started <= observed.get("ns", 0) < started + 22_000_000_000
    return result, records, probe, outcome


@pytest.mark.parametrize("scenario", ["no_inherited_pipe", "live_shell", "retained_pipes"])
@_NATIVE
def test_native_invoke_completion_matrix(powershell, tmp_path, scenario):
    expected_types = (1, 3) if scenario == "retained_pipes" else (1,)
    result, records, probe, outcome = _run_scenario(
        powershell, tmp_path, scenario, expected_types=expected_types
    )
    ready = records[0]
    assert probe == []
    if scenario == "no_inherited_pipe":
        assert ready == {
            "schema_version": 1, "stage": "child_ready", "stdout_pipe": False,
            "stderr_pipe": False, "stdout_type": 1, "stderr_type": 1, "parent_live": True,
        }
        expected_type = 1
    elif scenario == "live_shell":
        assert records == [{"schema_version": 1, "stage": "shell_ready"}]
        assert len(outcome) == 1
        assert outcome[0]["schema_version"] == 1
        assert outcome[0]["stage"] == "invoke_returned"
        assert outcome[0]["returncode"] != 0
        assert outcome[0]["reason"] == "timeout"
        assert type(outcome[0]["process_returncode"]) is int
        assert outcome[0]["cleanup_complete"] and outcome[0]["tree_empty"]
        assert not outcome[0]["output_limited"]
        assert not outcome[0]["cancel_ready_seen"]
        assert 0 <= outcome[0]["elapsed_ms"] <= 15500
        assert result.reason == "completed" and result.returncode == 0
        return
    else:
        assert ready == {
            "schema_version": 1, "stage": "child_ready", "stdout_pipe": False,
            "stderr_pipe": False, "stdout_type": 1, "stderr_type": 1, "parent_live": True,
        }
        expected_type = 1
    assert 1 <= len(records) <= 2
    if len(records) == 2:
        assert records[1] == {
            "schema_version": 1, "stage": "parent_exited", "release_observed": True,
            "parent_exited": True, "stdout_pipe": expected_type == 3,
            "stderr_pipe": expected_type == 3, "stdout_type": expected_type,
            "stderr_type": expected_type,
        }
    assert len(outcome) == 1
    assert outcome[0]["schema_version"] == 1
    assert outcome[0]["stage"] == "invoke_returned"
    assert outcome[0]["returncode"] == outcome[0]["process_returncode"] == 0
    assert outcome[0]["reason"] == "completed"
    assert outcome[0]["cleanup_complete"] and outcome[0]["tree_empty"]
    assert not outcome[0]["output_limited"]
    assert not outcome[0]["cancel_ready_seen"]
    assert 0 <= outcome[0]["elapsed_ms"] <= 15000
    assert result.reason == "completed" and result.returncode == 0


@_NATIVE
def test_native_invoke_cancellation(powershell, tmp_path):
    result, records, probe, outcome = _run_scenario(
        powershell, tmp_path, "live_shell", expected_types=(1,), cancel=True
    )
    assert records == [{"schema_version": 1, "stage": "shell_ready"}]
    assert probe == [] and len(outcome) == 1
    final = outcome[0]
    assert final["schema_version"] == 1 and final["stage"] == "invoke_returned"
    assert final["returncode"] != 0 and final["reason"] == "cancelled"
    assert type(final["process_returncode"]) is int
    assert final["cleanup_complete"] and final["tree_empty"]
    assert final["cancel_ready_seen"] and not final["output_limited"]
    assert 0 <= final["elapsed_ms"] <= 15000
    assert result.reason == "completed" and result.returncode == 0

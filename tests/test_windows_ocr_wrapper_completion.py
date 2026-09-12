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
    _handle = 41

    def __init__(self):
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = 1


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
    monkeypatch.setattr(process.subprocess, "Popen", lambda *_args, **_kwargs: child)

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
    assert job.closed == 1 and child.killed


def test_owned_unexpected_base_exception_cleans_up_then_reraises(monkeypatch):
    job = _Job(resume_error=_Abort())
    child = _mock_owned(monkeypatch, job)
    with pytest.raises(_Abort):
        run_owned(["synthetic"], cwd=None, env=None, timeout_s=1, cleanup_timeout_s=1)
    assert job.closed == 1 and child.killed


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
    assert job.closed == 1 and child.killed


def test_start_failure_closes_fresh_job(monkeypatch):
    job = _Job()
    _mock_owned(monkeypatch, job)

    def fail_start(*_args, **_kwargs):
        raise OSError

    monkeypatch.setattr(process.subprocess, "Popen", fail_start)
    result = run_owned(["synthetic"], cwd=None, env=None, timeout_s=1, cleanup_timeout_s=1)
    assert result.reason == "startup_failed"
    assert result.cleanup_complete and result.tree_empty and job.closed == 1


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
            raw.write(b"x" * 33)
            raw.flush()
            return child

        monkeypatch.setattr(process.subprocess, "Popen", write_flood)
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

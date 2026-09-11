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
_BASELINE = os.environ.get("METROLIZA_WINDOWS_WRAPPER_BASELINE") == "1"
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
    expected_type: int,
) -> Path:
    config = root / "fixture-config.json"
    config.write_text(
        json.dumps({
            **events,
            "python": sys.executable,
            "child": str(PY_FIXTURE),
            "root": str(root),
            "state": str(state),
            "stdout": str(root / "fixture.stdout"),
            "stderr": str(root / "fixture.stderr"),
            "scenario": scenario,
            "expected_type": expected_type,
            "parent_pid": 0,
        }, separators=(",", ":")),
        encoding="utf-8",
    )
    return config


def _read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _read_optional(path: Path) -> list[dict]:
    try:
        return _read_records(path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []


def _record(shell, scenario, result, ready=None, probe=(), outcome=()):
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
    raw_code = final.get("returncode")
    invoke_exit_code = raw_code if type(raw_code) is int and -(2**31) <= raw_code < 2**32 else None
    outer_exit_code = result.returncode if type(result.returncode) is int else None
    if scenario == "preflight":
        fixture_ready = all(ready.get(key) is True for key in (
            "assigned_before_code", "descendant_ready", "descendant_in_job",
        ))
    else:
        expected_stage = "shell_ready" if scenario == "live_shell" else "child_ready"
        fixture_ready = fixture_stage == expected_stage
    completed = (
        result.reason == "completed" and outer_exit_code == 0
        and result.cleanup_complete and result.tree_empty and fixture_ready
        and (scenario == "preflight" or (invoke_state == "returned" and invoke_exit_code == 0))
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
        "invoke_state": invoke_state,
        "cleanup_complete": result.cleanup_complete,
        "outer_exit_code": outer_exit_code,
        "invoke_exit_code": invoke_exit_code,
    }
    target = Path(directory) / "windows-ocr-wrapper-receipts.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt, separators=(",", ":")) + "\n")


@pytest.mark.skipif(not _BASELINE, reason="Set METROLIZA_WINDOWS_WRAPPER_BASELINE=1")
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


def _run_scenario(shell: str, root: Path, scenario: str, *, expected_type: int):
    state = root / "state.jsonl"
    probe_path = root / "timeout-probe.jsonl"
    outcome_path = root / "invoke-outcome.jsonl"
    events = {name: _event() for name in ("ready", "release", "exited", "hold")}
    config = _write_config(root, scenario, state, events, expected_type)
    stop, observed = threading.Event(), {}

    def observer():
        while not stop.is_set():
            records = _read_optional(state)
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
    records = _read_optional(state)
    probe = _read_optional(probe_path)
    outcome = _read_optional(outcome_path)
    _record(shell, scenario, result, records[0] if records else {}, probe, outcome)
    assert result.cleanup_complete and result.tree_empty
    assert math.isfinite(result.elapsed_s) and result.elapsed_s <= 27.5
    assert started <= observed.get("ns", 0) < started + 22_000_000_000
    return result, records, probe, outcome


@pytest.mark.skipif(not _BASELINE, reason="Set METROLIZA_WINDOWS_WRAPPER_BASELINE=1")
@pytest.mark.parametrize("scenario", ["no_inherited_pipe", "live_shell", "retained_pipes"])
@_NATIVE
def test_opt_in_original_invoke_pipe_discriminator(powershell, tmp_path, scenario):
    expected_type = 3 if scenario == "retained_pipes" else 1
    result, records, probe, outcome = _run_scenario(
        powershell, tmp_path, scenario, expected_type=expected_type
    )
    ready = records[0]
    assert probe[0] == {
        "schema_version": 1, "stage": "communicate_entered", "ready_seen": True,
    }
    if scenario == "no_inherited_pipe":
        assert ready == {
            "schema_version": 1, "stage": "child_ready", "stdout_pipe": False,
            "stderr_pipe": False, "stdout_type": 1, "stderr_type": 1, "parent_live": True,
        }
        assert records[1]["stage"] == "parent_exited"
        assert records[1]["release_observed"] and records[1]["parent_exited"]
        assert len(probe) == 1
        assert outcome == [{"schema_version": 1, "stage": "invoke_returned", "returncode": 0}]
        assert result.reason == "completed" and result.returncode == 0
    elif scenario == "live_shell":
        assert records == [{"schema_version": 1, "stage": "shell_ready"}]
        assert probe[1] == {
            "schema_version": 1, "stage": "timeout_before_kill", "shell_state": "live",
            "exited_seen": False,
        }
        assert outcome == [{"schema_version": 1, "stage": "timeout_returned"}]
        assert result.reason == "completed" and result.returncode == 0
    else:
        assert ready["stdout_pipe"] is True and ready["stderr_pipe"] is True
        assert ready["stdout_type"] == 3 and ready["stderr_type"] == 3
        assert records[1]["stage"] == "parent_exited"
        assert probe[1] == {
            "schema_version": 1, "stage": "timeout_before_kill", "shell_state": "exited",
            "exited_seen": True,
        }
        assert outcome == [] and result.reason == "timeout"


@_NATIVE
def test_invoke_retained_descendant_is_bounded(powershell, tmp_path):
    result, records, probe, outcome = _run_scenario(
        powershell, tmp_path, "retained_pipes", expected_type=1
    )
    ready = records[0]
    assert ready["stdout_pipe"] is False and ready["stderr_pipe"] is False
    assert ready["stdout_type"] == 1 and ready["stderr_type"] == 1
    assert probe == []
    assert outcome == [{"schema_version": 1, "stage": "invoke_returned", "returncode": 0}]
    assert result.reason == "completed" and result.returncode == 0

"""Portable contracts for the bounded native PowerShell invocation adapter."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import shutil
import tempfile
import threading

import pytest

from scripts import ocr_diagnostic_contract as contract
from tests import test_windows_ocr_powershell as harness


CANARY = b"SYNTHETIC_INVOKE_PRIVATE_1043"
_REAL_TEMPORARY_FILE = tempfile.TemporaryFile


@dataclass
class _Owned:
    returncode: int | None = 0
    reason: str = "completed"
    cleanup_complete: bool = True
    tree_empty: bool = True
    output_limited: bool = False
    elapsed_s: float = 0.01


class _Capture:
    def __init__(self, directory: Path, *, fail_read: bool = False, fail_close: bool = False):
        self.directory = directory
        self._file = _REAL_TEMPORARY_FILE(mode="w+b", dir=directory)
        self.closed = False
        self.fail_read = fail_read
        self.fail_close = fail_close
        self.read_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            self._file.close()
            if self.fail_close:
                raise OSError("synthetic capture close failure")

    def fileno(self):
        return self._file.fileno()

    def seek(self, *args):
        return self._file.seek(*args)

    def read(self, *args):
        assert len(args) == 1
        assert 0 < args[0] <= contract.MAX_OUTPUT + 1
        self.read_count += 1
        if self.fail_read:
            raise OSError("synthetic read failure")
        return self._file.read(*args)

    def write(self, data):
        return self._file.write(data)

    def flush(self):
        return self._file.flush()


class _Abort(BaseException):
    pass


class _PrivateDirectory:
    def __init__(self, prefix, *, fail_close: bool = False):
        self.path = Path(tempfile.mkdtemp(prefix=prefix))
        self.fail_close = fail_close
        self.closed = False

    def __enter__(self):
        return str(self.path)

    def __exit__(self, *_args):
        self.cleanup()

    def cleanup(self):
        if not self.closed:
            self.closed = True
            shutil.rmtree(self.path)
            if self.fail_close:
                raise OSError("synthetic private directory close failure")


def _install_captures(
    monkeypatch,
    *,
    fail_read: bool = False,
    fail_close: bool = False,
    fail_second_open: bool = False,
):
    captures: list[_Capture] = []
    directories: list[_PrivateDirectory] = []

    def temporary_directory(*, prefix):
        directory = _PrivateDirectory(prefix, fail_close=fail_close)
        directories.append(directory)
        return directory

    def temporary_file(*, mode, dir):
        assert mode == "w+b"
        assert isinstance(dir, Path)
        assert directories and dir == directories[-1].path
        if fail_second_open and captures:
            raise OSError("synthetic second capture failure")
        capture = _Capture(dir, fail_read=fail_read, fail_close=fail_close)
        captures.append(capture)
        return capture

    monkeypatch.setattr(harness.tempfile, "TemporaryDirectory", temporary_directory)
    monkeypatch.setattr(harness.tempfile, "TemporaryFile", temporary_file)
    return captures, directories


def _owned_run(
    calls,
    result: _Owned,
    stdout: bytes = b"",
    stderr: bytes = b"",
    *,
    before_return=None,
):
    def run(command, **kwargs):
        calls.append((command, kwargs))
        first, second = kwargs["stdout_target"], kwargs["stderr_target"]
        assert first is not second
        assert os.fstat(first.fileno()).st_size == 0
        assert os.fstat(second.fileno()).st_size == 0
        first.write(stdout)
        second.write(stderr)
        first.flush()
        second.flush()
        if before_return is not None:
            before_return(first, second)
        return result

    return run


def _invoke(tmp_path, **kwargs):
    return harness.invoke("synthetic-shell", tmp_path, "synthetic.ps1", "-Compact", **kwargs)


def test_invoke_preserves_exact_success_bytes_and_helper_arguments(monkeypatch, tmp_path):
    calls = []
    captures, directories = _install_captures(monkeypatch)
    expected_out = b'{"schema_version":1}'
    expected_err = b""
    monkeypatch.setattr(
        harness.process,
        "run_owned",
        _owned_run(calls, _Owned(), expected_out, expected_err),
    )
    monkeypatch.setattr(harness.time, "monotonic", lambda: 0.0)

    result = _invoke(tmp_path, timeout_s=15)

    assert result.returncode == 0
    assert result.process_returncode == 0
    assert result.reason == "completed"
    assert result.stdout == expected_out and result.stderr == expected_err
    assert result.cleanup_complete and result.tree_empty and not result.output_limited
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:5] == [
        "synthetic-shell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"
    ]
    assert command[-1] == "-Compact"
    assert kwargs["cwd"] == tmp_path
    assert kwargs["output_limit"] == contract.MAX_OUTPUT
    assert kwargs["cleanup_timeout_s"] == 5.0
    assert kwargs["timeout_s"] == pytest.approx(9.75)
    assert kwargs["env"]["PATH"].split(os.pathsep)[0] == str(Path(harness.sys.executable).parent)
    assert captures and all(capture.closed for capture in captures)
    assert all(capture.directory == directories[0].path for capture in captures)
    assert directories[0].path != tmp_path and not directories[0].path.exists()


def test_invoke_preserves_actual_nonzero_process_exit(monkeypatch, tmp_path):
    calls = []
    captures, directories = _install_captures(monkeypatch)
    monkeypatch.setattr(
        harness.process,
        "run_owned",
        _owned_run(calls, _Owned(returncode=17), b'{"safe":"failure"}', b""),
    )

    result = _invoke(tmp_path)

    assert result.returncode == 17 and result.process_returncode == 17
    assert result.reason == "completed"
    assert result.stdout == b'{"safe":"failure"}' and result.stderr == b""
    assert all(capture.closed for capture in captures)
    assert not directories[0].path.exists()


@pytest.mark.parametrize(
    "owned",
    [
        _Owned(reason="timeout", returncode=None),
        _Owned(reason="startup_failed", returncode=None),
        _Owned(reason="assignment_failed", returncode=None),
        _Owned(reason="resume_failed", returncode=None),
        _Owned(reason="cancelled", returncode=None),
        _Owned(reason="not_completed", returncode=23),
        _Owned(cleanup_complete=False, returncode=0),
        _Owned(tree_empty=False, returncode=0),
    ],
)
def test_invoke_guard_failure_discards_private_captures(monkeypatch, tmp_path, owned):
    calls = []
    captures, directories = _install_captures(monkeypatch)
    monkeypatch.setattr(
        harness.process,
        "run_owned",
        _owned_run(calls, owned, CANARY + b"-out", CANARY + b"-err"),
    )

    result = _invoke(tmp_path)

    assert result.returncode != 0
    assert result.process_returncode == owned.returncode
    assert result.reason != "completed"
    assert result.stdout == b""
    assert CANARY not in result.stderr
    assert result.stderr.isascii() and len(result.stderr) <= 128
    assert all(capture.closed for capture in captures)
    assert not directories[0].path.exists()


def test_invoke_forwards_cancellation_and_returns_fixed_failure(monkeypatch, tmp_path):
    calls = []
    captures, directories = _install_captures(monkeypatch)
    cancelled = threading.Event()
    cancelled.set()
    monkeypatch.setattr(
        harness.process,
        "run_owned",
        _owned_run(calls, _Owned(reason="cancelled", returncode=None), CANARY, CANARY),
    )

    result = _invoke(tmp_path, cancel_event=cancelled)

    assert calls[0][1]["cancel_event"] is cancelled
    assert result.returncode != 0 and result.reason == "cancelled"
    assert result.stdout == b"" and CANARY not in result.stderr
    assert all(capture.closed for capture in captures)
    assert not directories[0].path.exists()


@pytest.mark.parametrize("where", ["stdout", "stderr", "both", "late"])
def test_invoke_output_overflow_discards_both_captures(monkeypatch, tmp_path, where):
    calls = []
    captures, directories = _install_captures(monkeypatch)
    oversized = b"x" * (contract.MAX_OUTPUT + 1)
    stdout = oversized if where in {"stdout", "both"} else CANARY + b"-out"
    stderr = oversized if where in {"stderr", "both"} else CANARY + b"-err"

    def late(first, second):
        if where == "late":
            first.write(oversized)
            first.flush()

    monkeypatch.setattr(
        harness.process,
        "run_owned",
        _owned_run(calls, _Owned(), stdout, stderr, before_return=late),
    )

    result = _invoke(tmp_path)

    assert result.returncode != 0
    assert result.reason == "output_limit" and result.output_limited
    assert result.stdout == b""
    assert CANARY not in result.stderr
    assert result.stderr.isascii() and len(result.stderr) <= 128
    assert all(capture.closed for capture in captures)
    assert all(capture.read_count == 0 for capture in captures)
    assert not directories[0].path.exists()


def test_owned_output_limit_discards_both_captures_without_reading(monkeypatch, tmp_path):
    calls = []
    captures, directories = _install_captures(monkeypatch)
    monkeypatch.setattr(
        harness.process,
        "run_owned",
        _owned_run(
            calls,
            _Owned(output_limited=True),
            CANARY + b"-out",
            CANARY + b"-err",
        ),
    )

    result = _invoke(tmp_path)

    assert result.returncode != 0
    assert result.reason == "output_limit" and result.output_limited
    assert result.stdout == b"" and CANARY not in result.stderr
    assert all(capture.read_count == 0 for capture in captures)
    assert all(capture.closed for capture in captures)
    assert not directories[0].path.exists()


def test_invoke_stat_or_read_failure_discards_both_captures(monkeypatch, tmp_path):
    calls = []
    captures, directories = _install_captures(monkeypatch)
    original_fstat = harness.os.fstat
    capture_descriptors = set()
    failed_descriptors = set()

    def run(command, **kwargs):
        calls.append((command, kwargs))
        for target, value in (
            (kwargs["stdout_target"], CANARY + b"-out"),
            (kwargs["stderr_target"], CANARY + b"-err"),
        ):
            target.write(value)
            target.flush()
            capture_descriptors.add(target.fileno())
        return _Owned()

    def fail_after_guard(descriptor):
        if descriptor in capture_descriptors and descriptor not in failed_descriptors:
            failed_descriptors.add(descriptor)
            raise OSError("synthetic stat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(harness.process, "run_owned", run)
    monkeypatch.setattr(harness.os, "fstat", fail_after_guard)
    result = _invoke(tmp_path)

    assert result.returncode != 0
    assert result.reason == "not_completed"
    assert result.stdout == b"" and CANARY not in result.stderr
    assert all(capture.closed for capture in captures)
    assert not directories[0].path.exists()


def test_invoke_read_failure_discards_both_captures(monkeypatch, tmp_path):
    calls = []
    captures, directories = _install_captures(monkeypatch, fail_read=True)
    monkeypatch.setattr(
        harness.process,
        "run_owned",
        _owned_run(calls, _Owned(), CANARY + b"-out", CANARY + b"-err"),
    )

    result = _invoke(tmp_path)

    assert result.returncode != 0
    assert result.reason == "not_completed"
    assert result.stdout == b"" and CANARY not in result.stderr
    assert all(capture.closed for capture in captures)
    assert not directories[0].path.exists()


def test_invoke_closes_both_captures_when_guard_reraises(monkeypatch, tmp_path):
    captures, directories = _install_captures(monkeypatch)

    def abort(*_args, **_kwargs):
        raise _Abort()

    monkeypatch.setattr(harness.process, "run_owned", abort)
    with pytest.raises(_Abort):
        _invoke(tmp_path)
    assert len(captures) == 2
    assert all(capture.closed for capture in captures)
    assert not directories[0].path.exists()


def test_second_capture_creation_failure_closes_first_and_private_directory(monkeypatch, tmp_path):
    captures, directories = _install_captures(monkeypatch, fail_second_open=True)
    called = []
    monkeypatch.setattr(harness.process, "run_owned", lambda *_args, **_kwargs: called.append(True))

    result = _invoke(tmp_path)

    assert result.returncode != 0 and result.reason == "startup_failed"
    assert len(captures) == 1 and captures[0].closed
    assert len(directories) == 1 and not directories[0].path.exists()
    assert called == []


def test_capture_or_private_directory_close_failure_marks_cleanup_incomplete(monkeypatch, tmp_path):
    calls = []
    captures, directories = _install_captures(monkeypatch, fail_close=True)
    monkeypatch.setattr(harness.process, "run_owned", _owned_run(calls, _Owned()))

    result = _invoke(tmp_path)

    assert result.returncode != 0
    assert result.cleanup_complete is False
    assert result.reason == "not_completed"
    assert CANARY not in result.stderr
    assert str(directories[0].path).encode() not in result.stderr
    assert result.stderr.isascii() and len(result.stderr) <= 128
    assert all(capture.closed for capture in captures)
    assert directories[0].closed and not directories[0].path.exists()


@pytest.mark.parametrize(
    "deadline,execution,cleanup",
    [(45.0, 39.75, 5.0), (15.0, 9.75, 5.0), (0.3, 0.185, 0.1)],
)
def test_invoke_decomposes_one_total_deadline(monkeypatch, tmp_path, deadline, execution, cleanup):
    calls = []
    _install_captures(monkeypatch)
    monkeypatch.setattr(harness.process, "run_owned", _owned_run(calls, _Owned()))
    monkeypatch.setattr(harness.time, "monotonic", lambda: 0.0)

    result = _invoke(tmp_path, timeout_s=deadline)

    assert result.returncode == 0
    assert calls[0][1]["timeout_s"] == pytest.approx(execution)
    assert calls[0][1]["cleanup_timeout_s"] == pytest.approx(cleanup)
    assert calls[0][1]["timeout_s"] + calls[0][1]["cleanup_timeout_s"] < deadline


@pytest.mark.parametrize("deadline", [0, -1, math.inf, -math.inf, math.nan, True, "15"])
def test_invoke_rejects_invalid_total_deadline_before_opening_captures(
    monkeypatch, tmp_path, deadline
):
    opened, directories = _install_captures(monkeypatch)
    called = []
    monkeypatch.setattr(harness.process, "run_owned", lambda *_args, **_kwargs: called.append(True))

    result = _invoke(tmp_path, timeout_s=deadline)

    assert result.returncode != 0
    assert result.reason == "startup_failed"
    assert result.stdout == b"" and result.stderr == b"startup_failed"
    assert opened == [] and directories == [] and called == []

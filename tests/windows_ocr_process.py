"""Bounded Windows process-tree containment for native wrapper tests.

The guarded command is trusted test code, but its output is not.  This helper
discards stdin and defaults output to DEVNULL. Callers may supply distinct
empty regular files for private capture; this helper only polls their sizes
and returns closed status values, never their bytes. Phase evidence uses
fixed-schema synthetic state files in a disposable fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import subprocess
import stat
import threading
import time
from typing import BinaryIO, Literal, Mapping, Sequence

from scripts import ocr_diagnostic_contract as contract


Reason = Literal[
    "completed",
    "timeout",
    "cancelled",
    "containment_unavailable",
    "startup_failed",
    "assignment_failed",
    "resume_failed",
    "output_limit",
    "not_completed",
]


@dataclass(frozen=True)
class OwnedProcessResult:
    """Safe completion receipt for one exclusively owned Windows process tree."""

    returncode: int | None
    reason: Reason
    cleanup_complete: bool
    tree_empty: bool
    output_limited: bool
    elapsed_s: float


def _valid_budget(value: float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _capture_state(targets: tuple[BinaryIO | None, BinaryIO | None], limit: int) -> str:
    try:
        return (
            "exceeded"
            if any(
                target is not None and os.fstat(target.fileno()).st_size > limit
                for target in targets
            )
            else "within"
        )
    except (AttributeError, OSError, ValueError):
        return "unavailable"


def _valid_capture_targets(
    stdout_target: BinaryIO | None, stderr_target: BinaryIO | None
) -> bool:
    targets = [target for target in (stdout_target, stderr_target) if target is not None]
    try:
        descriptors = [target.fileno() for target in targets]
        return (
            len(descriptors) == len(set(descriptors))
            and all(stat.S_ISREG(os.fstat(descriptor).st_mode) for descriptor in descriptors)
            and all(os.fstat(descriptor).st_size == 0 for descriptor in descriptors)
            and all(target.tell() == 0 for target in targets)
        )
    except (AttributeError, OSError, ValueError):
        return False


def _wait_for_exact_process(
    process: subprocess.Popen[bytes], job: contract._WindowsJob, deadline: float
) -> bool:
    remaining_ms = max(0, math.ceil((deadline - time.monotonic()) * 1000))
    if job.kernel.WaitForSingleObject(int(process._handle), remaining_ms) != 0:
        return False
    process.poll()
    return True


def _resume_exact(process: subprocess.Popen[bytes], job: contract._WindowsJob) -> None:
    """Resume the sole initial thread while the retained process is still owned."""
    import ctypes
    from ctypes import wintypes

    class ThreadEntry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("thread_id", wintypes.DWORD),
            ("owner", wintypes.DWORD),
            ("base_priority", wintypes.LONG),
            ("delta_priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
        ]

    kernel = job.kernel
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenThread.restype = wintypes.HANDLE
    kernel.GetProcessIdOfThread.argtypes = [wintypes.HANDLE]
    kernel.GetProcessIdOfThread.restype = wintypes.DWORD
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD

    process_handle = int(process._handle)
    belongs = wintypes.BOOL()
    if (
        kernel.WaitForSingleObject(process_handle, 0) != 258
        or not kernel.IsProcessInJob(process_handle, job.handle, ctypes.byref(belongs))
        or not belongs.value
    ):
        raise OSError("resume_failed")

    snapshot = kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise OSError("resume_failed")
    try:
        entry = ThreadEntry()
        entry.size = ctypes.sizeof(entry)
        present = kernel.Thread32First(snapshot, ctypes.byref(entry))
        while present:
            if entry.owner == process.pid:
                rights = 0x0002 | 0x0800  # SUSPEND_RESUME | QUERY_LIMITED_INFORMATION
                thread = kernel.OpenThread(rights, False, entry.thread_id)
                if not thread:
                    raise OSError("resume_failed")
                try:
                    belongs = wintypes.BOOL()
                    if (
                        kernel.GetProcessIdOfThread(thread) != process.pid
                        or kernel.WaitForSingleObject(process_handle, 0) != 258
                        or not kernel.IsProcessInJob(
                            process_handle, job.handle, ctypes.byref(belongs)
                        )
                        or not belongs.value
                        or kernel.ResumeThread(thread) != 1
                    ):
                        raise OSError("resume_failed")
                    return
                finally:
                    kernel.CloseHandle(thread)
            present = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        raise OSError("resume_failed")
    finally:
        kernel.CloseHandle(snapshot)


def _cleanup(
    process: subprocess.Popen[bytes] | None,
    job: contract._WindowsJob | None,
    assigned: bool,
    deadline: float,
) -> tuple[bool, bool]:
    """Stop and account for the retained process/job handles by one deadline."""
    complete = True
    tree_empty = process is None
    unexpected: BaseException | None = None
    try:
        if process is not None and not assigned:
            try:
                if process.poll() is None:
                    process.kill()  # Popen retains the exact process handle.
            except (OSError, subprocess.SubprocessError):
                complete = False
            except BaseException as error:
                complete = False
                unexpected = error
            try:
                tree_empty = _wait_for_exact_process(process, job, deadline) if job else False
            except (OSError, subprocess.SubprocessError):
                complete = False
            except BaseException as error:
                complete = False
                if unexpected is None:
                    unexpected = error
        elif process is not None and job is not None:
            # Reuse the contract's retained-handle membership verification.  Its
            # public stop helper has several independent ten-second waits, so the
            # two deadline-aware primitives are used directly here instead.
            try:
                job._drain_members(deadline)
            except (OSError, subprocess.SubprocessError):
                complete = False
            except BaseException as error:
                complete = False
                unexpected = error
            try:
                job._terminate_job(deadline)
                tree_empty = True
            except (OSError, subprocess.SubprocessError):
                complete = False
            except BaseException as error:
                complete = False
                if unexpected is None:
                    unexpected = error
            try:
                if not _wait_for_exact_process(process, job, deadline):
                    complete = False
                    tree_empty = False
            except (OSError, subprocess.SubprocessError):
                complete = False
                tree_empty = False
            except BaseException as error:
                complete = False
                tree_empty = False
                if unexpected is None:
                    unexpected = error
    finally:
        if job is not None:
            job.close()
    if unexpected is not None:
        raise unexpected
    return complete and tree_empty, tree_empty


def run_owned(
    command: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None,
    env: Mapping[str, str] | None,
    timeout_s: float,
    cleanup_timeout_s: float = 10,
    cancel_event: threading.Event | None = None,
    stdout_target: BinaryIO | None = None,
    stderr_target: BinaryIO | None = None,
    output_limit: int = contract.MAX_OUTPUT,
) -> OwnedProcessResult:
    """Run a native Windows test command inside a fresh, bounded Job Object.

    The execution deadline and cleanup reserve are explicit.  Every cleanup
    operation shares one absolute cleanup deadline; no phase starts a fresh
    wait budget.
    """
    started = time.monotonic()
    if os.name != "nt" or not _valid_budget(timeout_s) or not _valid_budget(cleanup_timeout_s):
        return OwnedProcessResult(None, "containment_unavailable", True, True, False, 0.0)
    if (
        not _valid_capture_targets(stdout_target, stderr_target)
        or type(output_limit) is not int
        or not 0 < output_limit <= contract.MAX_OUTPUT
    ):
        return OwnedProcessResult(None, "startup_failed", True, True, False, 0.0)

    execution_deadline = started + timeout_s
    cleanup_deadline = execution_deadline + cleanup_timeout_s
    process: subprocess.Popen[bytes] | None = None
    job: contract._WindowsJob | None = None
    assigned = False
    reason: Reason = "completed"
    unexpected: BaseException | None = None
    cleanup_complete = False
    tree_empty = False
    output_limited = False
    capture_targets = (stdout_target, stderr_target)

    try:
        try:
            job = contract._WindowsJob()
        except OSError:
            reason = "containment_unavailable"
        else:
            try:
                process = subprocess.Popen(
                    list(command),
                    cwd=Path(cwd) if cwd is not None else None,
                    env=dict(env) if env is not None else None,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_target if stdout_target is not None else subprocess.DEVNULL,
                    stderr=stderr_target if stderr_target is not None else subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_SUSPENDED", 0x00000004),
                )
            except (OSError, ValueError):
                reason = "startup_failed"
            if process is not None:
                try:
                    job.assign(process)
                    assigned = True
                except OSError:
                    reason = "assignment_failed"
                if assigned:
                    try:
                        _resume_exact(process, job)
                    except OSError:
                        reason = "resume_failed"
                    else:
                        while True:
                            capture_state = _capture_state(capture_targets, output_limit)
                            if capture_state == "exceeded":
                                output_limited = True
                                reason = "output_limit"
                                break
                            if capture_state == "unavailable":
                                reason = "not_completed"
                                break
                            if process.poll() is not None:
                                break
                            if cancel_event is not None and cancel_event.is_set():
                                reason = "cancelled"
                                break
                            if time.monotonic() >= execution_deadline:
                                reason = "timeout"
                                break
                            time.sleep(0.01)
    except KeyboardInterrupt:
        reason = "cancelled"
    except (OSError, subprocess.SubprocessError):
        reason = "not_completed"
    except BaseException as error:
        unexpected = error
    finally:
        try:
            cleanup_complete, tree_empty = _cleanup(process, job, assigned, cleanup_deadline)
        except BaseException as error:
            if unexpected is None:
                unexpected = error

    if unexpected is not None:
        raise unexpected
    final_capture_state = _capture_state(capture_targets, output_limit)
    output_limited = output_limited or final_capture_state == "exceeded"
    if reason == "completed" and final_capture_state == "unavailable":
        reason = "not_completed"
    elif reason == "completed" and output_limited:
        reason = "output_limit"
    if reason == "completed" and not cleanup_complete:
        reason = "not_completed"
    elapsed_s = max(0.0, time.monotonic() - started)
    return OwnedProcessResult(
        process.returncode if process is not None else None,
        reason,
        cleanup_complete,
        tree_empty,
        output_limited,
        elapsed_s,
    )

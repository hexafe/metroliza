"""Bounded Windows process-tree containment for native wrapper tests.

The guarded command is trusted test code, but its output is not.  This helper
discards stdin and defaults output to DEVNULL. Callers may supply distinct
empty regular files for private capture; this helper only polls their sizes
and returns closed status values, never their bytes. Phase evidence uses
fixed-schema synthetic state files in a disposable fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes
import math
import os
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


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR),
        ("desktop", wintypes.LPWSTR), ("title", wintypes.LPWSTR),
        ("x", wintypes.DWORD), ("y", wintypes.DWORD),
        ("width", wintypes.DWORD), ("height", wintypes.DWORD),
        ("columns", wintypes.DWORD), ("rows", wintypes.DWORD),
        ("fill", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("show", wintypes.WORD), ("reserved_size", wintypes.WORD),
        ("reserved_bytes", ctypes.c_void_p),
        ("stdin", wintypes.HANDLE), ("stdout", wintypes.HANDLE),
        ("stderr", wintypes.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("startup", _StartupInfo), ("attributes", ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
        ("pid", wintypes.DWORD), ("tid", wintypes.DWORD),
    ]


@contextmanager
def _standard_handles(kernel, stdout_target, stderr_target):
    """Duplicate only the three selected streams; never inherit incidental handles."""
    import msvcrt

    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    ]
    handles = []
    with ExitStack() as files:
        try:
            inputs = (
                files.enter_context(open(os.devnull, "rb")),
                stdout_target if stdout_target is not None else
                files.enter_context(open(os.devnull, "wb")),
                stderr_target if stderr_target is not None else
                files.enter_context(open(os.devnull, "wb")),
            )
            owner = kernel.GetCurrentProcess()
            for stream in inputs:
                # Own the output slot before calling the API, including interrupts.
                handle = wintypes.HANDLE()
                handles.append(handle)
                if not kernel.DuplicateHandle(
                    owner, msvcrt.get_osfhandle(stream.fileno()), owner,
                    ctypes.byref(handle), 0, True, 2,  # DUPLICATE_SAME_ACCESS
                ):
                    raise OSError("startup_failed")
            yield [handle.value for handle in handles]
        finally:
            failed = False
            for handle in handles:
                if handle.value and not kernel.CloseHandle(handle.value):
                    failed = True
            if failed:
                raise OSError("handle_close_failed")


@contextmanager
def _startup_info(kernel, handles):
    kernel.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
    ]
    kernel.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel.DeleteProcThreadAttributeList.restype = None
    size = ctypes.c_size_t()
    kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    if not size.value:
        raise OSError("startup_failed")
    attributes = ctypes.create_string_buffer(size.value)
    if not kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
        raise OSError("startup_failed")
    try:
        inherited = (wintypes.HANDLE * 3)(*handles)
        if not kernel.UpdateProcThreadAttribute(
            attributes, 0, 0x20002, inherited, ctypes.sizeof(inherited), None, None,
        ):  # PROC_THREAD_ATTRIBUTE_HANDLE_LIST
            raise OSError("startup_failed")
        info = _StartupInfoEx()
        info.startup.cb = ctypes.sizeof(info)
        info.startup.flags = 0x100  # STARTF_USESTDHANDLES
        info.startup.stdin, info.startup.stdout, info.startup.stderr = handles
        info.attributes = ctypes.cast(attributes, ctypes.c_void_p)
        yield info
    finally:
        kernel.DeleteProcThreadAttributeList(attributes)


def _environment_block(env):
    if env is None:
        return None
    for key, value in env.items():
        if not key or "=" in key[1:] or "\0" in key or "\0" in value:
            raise ValueError("startup_failed")
    # CreateProcess requires two terminal NULs, including for an empty mapping.
    return ctypes.create_unicode_buffer(
        "\0".join(f"{key}={env[key]}" for key in sorted(env, key=str.upper)) + "\0"
    )


class _SuspendedChild:
    """Retain CreateProcess's exact process and primary-thread ownership slots."""

    def __init__(self, kernel):
        self.kernel = kernel
        self.info = _ProcessInformation()
        self.returncode = None

    @property
    def _handle(self):
        return self.info.process

    @property
    def pid(self):
        return self.info.pid

    @property
    def primary_thread(self):
        return self.info.thread

    @property
    def primary_thread_id(self):
        return self.info.tid

    def start(self, command, *, cwd, env, stdout_target, stderr_target):
        kernel = self.kernel
        kernel.CreateProcessW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
            ctypes.POINTER(_StartupInfoEx), ctypes.POINTER(_ProcessInformation),
        ]
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        environment = _environment_block(env)
        with _standard_handles(kernel, stdout_target, stderr_target) as handles:
            with _startup_info(kernel, handles) as startup:
                # run_owned owns self.info before this call. Even interruption
                # immediately after native creation cannot lose its handles.
                if not kernel.CreateProcessW(
                    None, command_line, None, None, True,
                    0x4 | 0x80000 | 0x400,  # SUSPENDED | EXTENDED_STARTUPINFO | UNICODE_ENV
                    environment, os.fspath(cwd) if cwd is not None else None,
                    ctypes.byref(startup), ctypes.byref(self.info),
                ):
                    raise OSError("startup_failed")

    def poll(self):
        if self.returncode is None:
            status = self.kernel.WaitForSingleObject(self._handle, 0)
            if status == 258:
                return None
            code = wintypes.DWORD()
            self.kernel.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
            ]
            if status != 0 or not self.kernel.GetExitCodeProcess(self._handle, ctypes.byref(code)):
                raise OSError("process_status_unavailable")
            self.returncode = code.value
        return self.returncode

    def kill(self):
        if not self.kernel.TerminateProcess(self._handle, 1) and self.poll() is None:
            raise OSError("process_stop_unavailable")

    def close(self):
        failed = False
        for field in ("thread", "process"):
            handle = getattr(self.info, field)
            if handle:
                if self.kernel.CloseHandle(handle):
                    setattr(self.info, field, None)
                else:
                    failed = True
        if failed:
            raise OSError("handle_close_failed")


def _wait_for_exact_process(
    process: _SuspendedChild, job: contract._WindowsJob, deadline: float
) -> bool:
    remaining_ms = max(0, math.ceil((deadline - time.monotonic()) * 1000))
    if job.kernel.WaitForSingleObject(int(process._handle), remaining_ms) != 0:
        return False
    process.poll()
    return True


def _resume_exact(process: _SuspendedChild, job: contract._WindowsJob) -> None:
    """Resume CreateProcess's retained primary thread, never a snapshot candidate."""
    kernel = job.kernel
    kernel.GetThreadId.argtypes = [wintypes.HANDLE]
    kernel.GetThreadId.restype = wintypes.DWORD
    kernel.GetProcessIdOfThread.argtypes = [wintypes.HANDLE]
    kernel.GetProcessIdOfThread.restype = wintypes.DWORD
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD

    process_handle = int(process._handle)
    thread = process.primary_thread
    belongs = wintypes.BOOL()
    if (
        not thread
        or not process.primary_thread_id
        or kernel.GetThreadId(thread) != process.primary_thread_id
        or kernel.GetProcessIdOfThread(thread) != process.pid
        or kernel.WaitForSingleObject(thread, 0) != 258
        or kernel.WaitForSingleObject(process_handle, 0) != 258
        or not kernel.IsProcessInJob(process_handle, job.handle, ctypes.byref(belongs))
        or not belongs.value
        or kernel.ResumeThread(thread) != 1
    ):
        raise OSError("resume_failed")


def _cleanup(
    process: _SuspendedChild | None,
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
                    process.kill()  # The child retains the exact process handle.
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
    process: _SuspendedChild | None = None
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
            process = _SuspendedChild(job.kernel)
            try:
                process.start(
                    list(command), cwd=cwd, env=env,
                    stdout_target=stdout_target, stderr_target=stderr_target,
                )
            except (OSError, ValueError):
                reason = "startup_failed"
            if reason == "completed":
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
            created = process if process is not None and process._handle else None
            cleanup_complete, tree_empty = _cleanup(created, job, assigned, cleanup_deadline)
        except BaseException as error:
            if unexpected is None:
                unexpected = error
        finally:
            if process is not None:
                try:
                    process.close()
                except OSError:
                    cleanup_complete = False
                except BaseException as error:
                    cleanup_complete = False
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

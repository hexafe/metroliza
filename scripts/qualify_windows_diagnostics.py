"""Qualify the bounded diagnostics path in one exact Windows onedir package."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from metroliza.app.build_provenance import BuildProvenance
from metroliza.shared.diagnostic_events import (
    RuntimeProvenanceEvent,
    StartupDiagnosticEvent,
    WorkflowDiagnosticEvent,
    WorkflowOutcome,
)
from metroliza.shared.diagnostic_incident import (
    ChannelState,
    HandshakeState,
    LaunchState,
    decode_incident,
)
from metroliza.shared.diagnostic_package import MANIFEST_NAME, inspect_package
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus
from metroliza.shared.diagnostic_wire import decode_event

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"
FIXTURE_SHA256 = "ca500bd52afc2551560e7c0009851906a0d3bec6b35282e20703c1e298da608b"
OUTPUT_NAME = "windows-diagnostic-qualification.json"
MAX_TOTAL_SECONDS = 720
MAX_SCENARIO_SECONDS = 90
MAX_RECEIPT_BYTES = 64 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_PACKAGE_COPY_BYTES = 2 * 1024 * 1024 * 1024
MAX_PACKAGE_ENTRIES = 25_000
NOTICE_FILES = ("THIRD_PARTY_NOTICES.md", "third_party_inventory_260711.json")
CHECK_IDS = (
    "package_identity",
    "no_console",
    "restricted_token",
    "direct_workflow",
    "supervised_workflow",
    "repeat_starts",
    "hard_exit_incident",
    "handled_failure_live",
    "selected_export",
    "idle_writes",
    "flood_loss",
    "unavailable_store",
    "missing_components",
    "missing_qt_resource",
)
FAILURE_IDS = frozenset(
    {
        "invalid_arguments",
        "unsupported_platform",
        "artifact_invalid",
        "provenance_invalid",
        "notices_invalid",
        "fixture_invalid",
        "restricted_launch_unavailable",
        "scenario_timeout",
        "scenario_failed",
        "incident_invalid",
        "export_invalid",
        "output_failed",
    }
)


class QualificationFailure(RuntimeError):
    """A fixed failure identity which never includes native or input-controlled text."""

    def __init__(self, failure_id: str) -> None:
        if failure_id not in FAILURE_IDS:
            failure_id = "scenario_failed"
        self.failure_id = failure_id
        super().__init__(failure_id)


@dataclass(frozen=True, slots=True)
class ProcessMetrics:
    peak_job_memory_bytes: int
    read_operations: int
    write_operations: int
    read_bytes: int
    write_bytes: int


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    exit_code: int
    elapsed_ms: int
    ready_ms: int
    receipt_stage: str | None
    metrics: ProcessMetrics


@dataclass(frozen=True, slots=True)
class QualificationResult:
    status: str
    failure_id: str | None
    receipt_path: Path | None


def _sha256(path: Path, *, maximum: int = MAX_FILE_BYTES) -> str:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size < 0
        or metadata.st_size > maximum
        or getattr(metadata, "st_file_attributes", 0) & 0x400
    ):
        raise QualificationFailure("artifact_invalid")
    digest = hashlib.sha256()
    remaining = maximum + 1
    with path.open("rb") as stream:
        while remaining:
            block = stream.read(min(1024 * 1024, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
    if remaining == 0:
        raise QualificationFailure("artifact_invalid")
    return digest.hexdigest()


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_field")
        result[key] = value
    return result


def _bounded_json(path: Path, maximum: int) -> object:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 0 < metadata.st_size <= maximum
        or getattr(metadata, "st_file_attributes", 0) & 0x400
    ):
        raise ValueError("unsafe_json")
    data = path.read_bytes()
    if len(data) != metadata.st_size:
        raise ValueError("changed_json")
    return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_fields)


def _validate_sidecar(artifact: Path, expected_git_sha: str) -> str:
    try:
        sidecar = artifact.with_name(f"{artifact.name}.provenance.json")
        payload = _bounded_json(sidecar, 16 * 1024)
        expected = {
            "schema_version",
            "release_label",
            "git_sha",
            "dirty",
            "built_at_utc",
            "packager",
            "python_version",
            "artifact",
        }
        if type(payload) is not dict or set(payload) != expected:
            raise ValueError("invalid_sidecar")
        artifact_value = payload["artifact"]
        if type(artifact_value) is not dict or set(artifact_value) != {
            "name",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("invalid_sidecar")
        if (
            artifact_value["name"] != artifact.name
            or artifact_value["sha256"] != _sha256(artifact)
            or type(artifact_value["size_bytes"]) is not int
            or artifact_value["size_bytes"] != artifact.stat().st_size
        ):
            raise ValueError("invalid_sidecar")
        provenance = BuildProvenance.from_mapping(
            {key: value for key, value in payload.items() if key != "artifact"}
        )
        if provenance.packager != "pyinstaller" or provenance.git_sha != expected_git_sha:
            raise ValueError("invalid_sidecar")
        return artifact_value["sha256"]
    except (OSError, ValueError, KeyError, TypeError, QualificationFailure):
        raise QualificationFailure("provenance_invalid") from None


def _validate_notices(launcher: Path) -> dict[str, str]:
    try:
        directory = launcher.with_name(f"{launcher.name}.licenses")
        manifest = _bounded_json(directory / "NOTICE_MANIFEST.json", 16 * 1024)
        if type(manifest) is not dict or set(manifest) != {"files"}:
            raise ValueError("invalid_notices")
        entries = manifest["files"]
        if type(entries) is not list or len(entries) != len(NOTICE_FILES):
            raise ValueError("invalid_notices")
        observed: dict[str, str] = {}
        for entry in entries:
            if type(entry) is not dict or set(entry) != {"name", "sha256"}:
                raise ValueError("invalid_notices")
            name, digest = entry["name"], entry["sha256"]
            if name not in NOTICE_FILES or name in observed or type(digest) is not str:
                raise ValueError("invalid_notices")
            if _sha256(directory / name, maximum=16 * 1024 * 1024) != digest:
                raise ValueError("invalid_notices")
            observed[name] = digest
        if set(observed) != set(NOTICE_FILES):
            raise ValueError("invalid_notices")
        return observed
    except (OSError, ValueError, KeyError, TypeError, QualificationFailure):
        raise QualificationFailure("notices_invalid") from None


def _pe_subsystem(path: Path) -> int:
    try:
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("not_pe")
            stream.seek(0x3C)
            pe_offset = int.from_bytes(stream.read(4), "little")
            if not 64 <= pe_offset <= 1024 * 1024:
                raise ValueError("not_pe")
            stream.seek(pe_offset)
            if stream.read(4) != b"PE\x00\x00":
                raise ValueError("not_pe")
            stream.seek(20, 1)
            magic = int.from_bytes(stream.read(2), "little")
            if magic not in (0x10B, 0x20B):
                raise ValueError("not_pe")
            stream.seek(66, 1)
            return int.from_bytes(stream.read(2), "little")
    except (OSError, ValueError):
        raise QualificationFailure("artifact_invalid") from None


def _validate_package(artifact_dir: Path) -> dict[str, object]:
    launcher = artifact_dir / "metroliza.exe"
    application = artifact_dir / "metroliza_application.exe"
    identity = inspect_package(artifact_dir)
    if not identity.valid or identity.reason != "verified":
        raise QualificationFailure("artifact_invalid")
    try:
        if _pe_subsystem(launcher) != 2 or _pe_subsystem(application) != 2:
            raise QualificationFailure("artifact_invalid")
        launcher_hash = _validate_sidecar(launcher, identity.git_sha)
        notice_hashes = _validate_notices(launcher)
        return {
            "git_sha": identity.git_sha,
            "launcher_sha256": launcher_hash,
            "application_sha256": _sha256(application),
            "manifest_sha256": _sha256(artifact_dir / MANIFEST_NAME, maximum=4096),
            "notice_hashes": notice_hashes,
        }
    except OSError:
        raise QualificationFailure("artifact_invalid") from None


def _sanitized_environment(
    artifact_dir: Path,
    work_root: Path,
    state_base: Path,
    scenario: str,
    *,
    inherited: dict[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if inherited is None else inherited
    keep = (
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "PROGRAMDATA",
    )
    environment = {key: source[key] for key in keep if source.get(key)}
    windows_root = environment.get("SYSTEMROOT") or environment.get("WINDIR")
    if windows_root is None:
        raise QualificationFailure("restricted_launch_unavailable")
    environment.update(
        {
            "PATH": ";".join(
                (
                    str(artifact_dir),
                    str(artifact_dir / "_internal"),
                    str(Path(windows_root) / "System32"),
                    windows_root,
                )
            ),
            "LOCALAPPDATA": str(state_base),
            "APPDATA": str(state_base / "Roaming"),
            "METROLIZA_STARTUP_SMOKE": "1",
            "METROLIZA_DIAGNOSTIC_QUALIFICATION": scenario,
            "METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT": str(work_root),
            "METROLIZA_LICENSE_VERIFICATION": "0",
            "QT_QPA_PLATFORM": "offscreen",
        }
    )
    return environment


class _WindowsProcess:
    def __init__(self, api, process_handle, job_handle, started: float) -> None:
        self._api = api
        self._process = process_handle
        self._job = job_handle
        self.started = started
        self._closed = False

    def poll(self) -> int | None:
        return self._api.poll(self._process)

    def metrics(self) -> ProcessMetrics:
        return self._api.job_metrics(self._job)

    def close(self, *, terminate: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        self._api.close_process(self._process, self._job, terminate=terminate)


class _WindowsApi:
    """Small ctypes boundary for a non-admin restricted token and kill-on-close job."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise QualificationFailure("unsupported_platform")
        from ctypes import wintypes

        self.wintypes = wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._declare_structures()
        self._declare_functions()

    def _declare_structures(self) -> None:
        wt = self.wintypes

        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD),
                ("lpReserved", wt.LPWSTR),
                ("lpDesktop", wt.LPWSTR),
                ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD),
                ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD),
                ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD),
                ("dwYCountChars", wt.DWORD),
                ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD),
                ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.POINTER(wt.BYTE)),
                ("hStdInput", wt.HANDLE),
                ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE),
            ]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", wt.HANDLE),
                ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD),
            ]

        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wt.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wt.DWORD),
                ("SchedulingClass", wt.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.STARTUPINFOW = STARTUPINFOW
        self.PROCESS_INFORMATION = PROCESS_INFORMATION
        self.SID_AND_ATTRIBUTES = SID_AND_ATTRIBUTES
        self.EXTENDED_LIMITS = JOBOBJECT_EXTENDED_LIMIT_INFORMATION

    def _declare_functions(self) -> None:
        wt = self.wintypes
        self.kernel.GetCurrentProcess.restype = wt.HANDLE
        self.kernel.CloseHandle.argtypes = [wt.HANDLE]
        self.kernel.CloseHandle.restype = wt.BOOL
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wt.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wt.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wt.DWORD,
        ]
        self.kernel.SetInformationJobObject.restype = wt.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wt.BOOL
        self.kernel.QueryInformationJobObject.argtypes = [
            wt.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wt.DWORD,
            ctypes.POINTER(wt.DWORD),
        ]
        self.kernel.QueryInformationJobObject.restype = wt.BOOL
        self.kernel.ResumeThread.argtypes = [wt.HANDLE]
        self.kernel.ResumeThread.restype = wt.DWORD
        self.kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        self.kernel.WaitForSingleObject.restype = wt.DWORD
        self.kernel.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
        self.kernel.GetExitCodeProcess.restype = wt.BOOL
        self.kernel.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
        self.kernel.TerminateProcess.restype = wt.BOOL

        self.advapi.OpenProcessToken.argtypes = [
            wt.HANDLE,
            wt.DWORD,
            ctypes.POINTER(wt.HANDLE),
        ]
        self.advapi.OpenProcessToken.restype = wt.BOOL
        self.advapi.CreateWellKnownSid.argtypes = [
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(wt.DWORD),
        ]
        self.advapi.CreateWellKnownSid.restype = wt.BOOL
        self.advapi.CreateRestrictedToken.argtypes = [
            wt.HANDLE,
            wt.DWORD,
            wt.DWORD,
            ctypes.POINTER(self.SID_AND_ATTRIBUTES),
            wt.DWORD,
            ctypes.c_void_p,
            wt.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(wt.HANDLE),
        ]
        self.advapi.CreateRestrictedToken.restype = wt.BOOL
        self.advapi.IsTokenRestricted.argtypes = [wt.HANDLE]
        self.advapi.IsTokenRestricted.restype = wt.BOOL
        process_arguments = [
            wt.HANDLE,
            wt.LPCWSTR,
            wt.LPWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wt.BOOL,
            wt.DWORD,
            ctypes.c_void_p,
            wt.LPCWSTR,
            ctypes.POINTER(self.STARTUPINFOW),
            ctypes.POINTER(self.PROCESS_INFORMATION),
        ]
        self.advapi.CreateProcessAsUserW.argtypes = process_arguments
        self.advapi.CreateProcessAsUserW.restype = wt.BOOL
        self.advapi.CreateProcessWithTokenW.argtypes = [
            wt.HANDLE,
            wt.DWORD,
            wt.LPCWSTR,
            wt.LPWSTR,
            wt.DWORD,
            ctypes.c_void_p,
            wt.LPCWSTR,
            ctypes.POINTER(self.STARTUPINFOW),
            ctypes.POINTER(self.PROCESS_INFORMATION),
        ]
        self.advapi.CreateProcessWithTokenW.restype = wt.BOOL

    def _restricted_token(self):
        wt = self.wintypes
        current = wt.HANDLE()
        restricted = wt.HANDLE()
        token_access = 0x0001 | 0x0002 | 0x0008
        if not self.advapi.OpenProcessToken(
            self.kernel.GetCurrentProcess(), token_access, ctypes.byref(current)
        ):
            raise QualificationFailure("restricted_launch_unavailable")
        sid_size = wt.DWORD(68)
        sid = ctypes.create_string_buffer(sid_size.value)
        try:
            if not self.advapi.CreateWellKnownSid(
                26, None, sid, ctypes.byref(sid_size)
            ):
                raise QualificationFailure("restricted_launch_unavailable")
            disabled = self.SID_AND_ATTRIBUTES(ctypes.cast(sid, ctypes.c_void_p), 0)
            if not self.advapi.CreateRestrictedToken(
                current,
                0x1,
                1,
                ctypes.byref(disabled),
                0,
                None,
                0,
                None,
                ctypes.byref(restricted),
            ):
                raise QualificationFailure("restricted_launch_unavailable")
            if not self.advapi.IsTokenRestricted(restricted):
                raise QualificationFailure("restricted_launch_unavailable")
            return restricted
        except Exception:
            if restricted:
                self.kernel.CloseHandle(restricted)
            raise
        finally:
            self.kernel.CloseHandle(current)

    def launch(
        self,
        executable: Path,
        environment: dict[str, str],
        cwd: Path,
    ) -> _WindowsProcess:
        token = self._restricted_token()
        job = self.kernel.CreateJobObjectW(None, None)
        if not job:
            self.kernel.CloseHandle(token)
            raise QualificationFailure("restricted_launch_unavailable")
        limits = self.EXTENDED_LIMITS()
        limits.BasicLimitInformation.LimitFlags = 0x2000
        if not self.kernel.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.kernel.CloseHandle(job)
            self.kernel.CloseHandle(token)
            raise QualificationFailure("restricted_launch_unavailable")
        startup = self.STARTUPINFOW()
        startup.cb = ctypes.sizeof(startup)
        process = self.PROCESS_INFORMATION()
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(executable)]))
        environment_block = ctypes.create_unicode_buffer(
            "\0".join(f"{key}={value}" for key, value in sorted(environment.items())) + "\0\0"
        )
        flags = 0x00000400 | 0x08000000 | 0x00000004
        started = time.perf_counter()
        created = self.advapi.CreateProcessAsUserW(
            token,
            str(executable),
            command,
            None,
            None,
            False,
            flags,
            environment_block,
            str(cwd),
            ctypes.byref(startup),
            ctypes.byref(process),
        )
        if not created and ctypes.get_last_error() == 1314:
            command = ctypes.create_unicode_buffer(
                subprocess.list2cmdline([str(executable)])
            )
            created = self.advapi.CreateProcessWithTokenW(
                token,
                0,
                str(executable),
                command,
                flags,
                environment_block,
                str(cwd),
                ctypes.byref(startup),
                ctypes.byref(process),
            )
        self.kernel.CloseHandle(token)
        if not created:
            self.kernel.CloseHandle(job)
            raise QualificationFailure("restricted_launch_unavailable")
        try:
            if not self.kernel.AssignProcessToJobObject(job, process.hProcess):
                raise QualificationFailure("restricted_launch_unavailable")
            if self.kernel.ResumeThread(process.hThread) == 0xFFFFFFFF:
                raise QualificationFailure("restricted_launch_unavailable")
        except QualificationFailure:
            self.kernel.TerminateProcess(process.hProcess, 22)
            self.kernel.CloseHandle(process.hThread)
            self.kernel.CloseHandle(process.hProcess)
            self.kernel.CloseHandle(job)
            raise
        self.kernel.CloseHandle(process.hThread)
        return _WindowsProcess(self, process.hProcess, job, started)

    def poll(self, process) -> int | None:
        result = self.kernel.WaitForSingleObject(process, 0)
        if result == 0x00000102:
            return None
        if result != 0:
            raise QualificationFailure("scenario_failed")
        code = self.wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(process, ctypes.byref(code)):
            raise QualificationFailure("scenario_failed")
        return int(code.value)

    def job_metrics(self, job) -> ProcessMetrics:
        info = self.EXTENDED_LIMITS()
        returned = self.wintypes.DWORD()
        if not self.kernel.QueryInformationJobObject(
            job, 9, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned)
        ):
            raise QualificationFailure("scenario_failed")
        io = info.IoInfo
        return ProcessMetrics(
            int(info.PeakJobMemoryUsed),
            int(io.ReadOperationCount),
            int(io.WriteOperationCount),
            int(io.ReadTransferCount),
            int(io.WriteTransferCount),
        )

    def close_process(self, process, job, *, terminate: bool) -> None:
        if terminate:
            self.kernel.TerminateProcess(process, 23)
        self.kernel.CloseHandle(job)
        self.kernel.CloseHandle(process)


def _validate_child_receipt(path: Path, scenario: str) -> dict[str, object]:
    try:
        payload = _bounded_json(path, 4096)
        if type(payload) is not dict or set(payload) != {
            "schema_version",
            "scenario",
            "stage",
            "packaged",
            "console_none",
            "ordinary_user",
        }:
            raise ValueError("invalid_receipt")
        if (
            payload["schema_version"] != 1
            or type(payload["schema_version"]) is not int
            or payload["scenario"] != scenario
            or payload["stage"] not in {"ready", "complete", "failed"}
            or payload["packaged"] is not True
            or payload["console_none"] is not True
            or payload["ordinary_user"] is not True
        ):
            raise ValueError("invalid_receipt")
        return payload
    except (OSError, ValueError, KeyError, TypeError):
        raise QualificationFailure("scenario_failed") from None


def _prepare_work_root(parent: Path, label: str) -> Path:
    root = parent / f"{label}-{uuid.uuid4().hex}" / "próba ze spacjami"
    root.mkdir(parents=True)
    fixture = root / "fixture.pdf"
    shutil.copyfile(FIXTURE, fixture)
    if _sha256(fixture, maximum=128 * 1024) != FIXTURE_SHA256:
        raise QualificationFailure("fixture_invalid")
    return root


def _validate_package_tree(root: Path) -> None:
    entries = 0
    total_bytes = 0
    try:
        for directory, names, files in os.walk(root, followlinks=False):
            for name in (*names, *files):
                entries += 1
                if entries > MAX_PACKAGE_ENTRIES:
                    raise QualificationFailure("artifact_invalid")
                path = Path(directory) / name
                metadata = path.lstat()
                if getattr(metadata, "st_file_attributes", 0) & 0x400:
                    raise QualificationFailure("artifact_invalid")
                if stat.S_ISREG(metadata.st_mode):
                    if metadata.st_nlink != 1 or metadata.st_size < 0:
                        raise QualificationFailure("artifact_invalid")
                    total_bytes += metadata.st_size
                    if total_bytes > MAX_PACKAGE_COPY_BYTES:
                        raise QualificationFailure("artifact_invalid")
                elif not stat.S_ISDIR(metadata.st_mode):
                    raise QualificationFailure("artifact_invalid")
    except OSError:
        raise QualificationFailure("artifact_invalid") from None


def _relocate_package(artifact: Path, private_root: Path, deadline: float) -> Path:
    _validate_package_tree(artifact)
    destination = private_root / "pakiet żółć ze spacjami"
    try:
        shutil.copytree(artifact, destination)
    except OSError:
        raise QualificationFailure("artifact_invalid") from None
    if time.monotonic() >= deadline:
        raise QualificationFailure("scenario_timeout")
    _validate_package_tree(destination)
    return destination


def _run_scenario(
    api: _WindowsApi,
    executable: Path,
    artifact_dir: Path,
    work_root: Path,
    state_base: Path,
    scenario: str,
    deadline: float,
    *,
    expected_exit: int,
    expected_stage: str,
    on_ready: Callable[[_WindowsProcess], None] | None = None,
) -> ScenarioResult:
    environment = _sanitized_environment(artifact_dir, work_root, state_base, scenario)
    process = api.launch(executable, environment, work_root)
    receipt_path = work_root / "qualification.json"
    ready_ms: int | None = None
    ready_called = False
    terminate = True
    try:
        scenario_deadline = min(deadline, time.monotonic() + MAX_SCENARIO_SECONDS)
        exit_code: int | None = None
        last_receipt: dict[str, object] | None = None
        while time.monotonic() < scenario_deadline:
            if receipt_path.exists():
                last_receipt = _validate_child_receipt(receipt_path, scenario)
                if ready_ms is None:
                    ready_ms = round((time.perf_counter() - process.started) * 1000)
                if last_receipt["stage"] == "failed":
                    raise QualificationFailure("scenario_failed")
                if on_ready is not None and not ready_called:
                    ready_called = True
                    on_ready(process)
            exit_code = process.poll()
            if exit_code is not None:
                break
            time.sleep(0.02)
        if exit_code is None:
            raise QualificationFailure("scenario_timeout")
        if exit_code != expected_exit or last_receipt is None:
            raise QualificationFailure("scenario_failed")
        final_receipt = _validate_child_receipt(receipt_path, scenario)
        if final_receipt["stage"] != expected_stage:
            raise QualificationFailure("scenario_failed")
        metrics = process.metrics()
        elapsed_ms = round((time.perf_counter() - process.started) * 1000)
        terminate = False
        return ScenarioResult(
            exit_code,
            elapsed_ms,
            ready_ms if ready_ms is not None else elapsed_ms,
            str(final_receipt["stage"]),
            metrics,
        )
    finally:
        process.close(terminate=terminate)


def _reports(store: IncidentStore):
    listing = store.list_reports()
    if listing.status is not StoreStatus.AVAILABLE:
        raise QualificationFailure("incident_invalid")
    return listing.reports


def _newest_incident(store: IncidentStore, previous: set[uuid.UUID]):
    records = _reports(store)
    added = [record for record in records if record.report_id not in previous]
    if not added:
        raise QualificationFailure("incident_invalid")
    loaded = store.load(added[0].report_id)
    if loaded.status is not StoreStatus.AVAILABLE or loaded.incident is None:
        raise QualificationFailure("incident_invalid")
    return loaded.incident


def _wait_newest_incident(
    store: IncidentStore,
    previous: set[uuid.UUID],
    deadline: float,
):
    while time.monotonic() < deadline:
        try:
            return _newest_incident(store, previous)
        except QualificationFailure:
            time.sleep(0.02)
    raise QualificationFailure("incident_invalid")


def _validate_selected_export(path: Path, report_id: uuid.UUID) -> None:
    try:
        if _sha256(path, maximum=4 * 1024 * 1024) == "":
            raise ValueError("empty_export")
        with zipfile.ZipFile(path) as bundle:
            if set(bundle.namelist()) != {"incident.json", "manifest.json", "summary.json"}:
                raise ValueError("invalid_export")
            data = bundle.read("incident.json")
        if decode_incident(data).report_id != report_id:
            raise ValueError("wrong_export")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, QualificationFailure):
        raise QualificationFailure("export_invalid") from None


def _write_receipt(output_dir: Path, payload: dict[str, object]) -> Path:
    if set(output_dir.iterdir()):
        raise QualificationFailure("output_failed")
    _validate_output_payload(payload)
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")
    if not encoded or len(encoded) > MAX_RECEIPT_BYTES:
        raise QualificationFailure("output_failed")
    stage = output_dir / f".{OUTPUT_NAME}.{uuid.uuid4().hex}.tmp"
    destination = output_dir / OUTPUT_NAME
    try:
        with stage.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, destination)
        return destination
    except OSError:
        try:
            stage.unlink()
        except OSError:
            pass
        raise QualificationFailure("output_failed") from None


def _bounded_counter(value: object) -> bool:
    return type(value) is int and 0 <= value <= 2**63 - 1


def _valid_digest(value: object, lengths: tuple[int, ...] = (64,)) -> bool:
    return (
        type(value) is str
        and len(value) in lengths
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_package_receipt(package: object) -> None:
    expected = {
        "git_sha",
        "launcher_sha256",
        "application_sha256",
        "manifest_sha256",
        "notice_hashes",
    }
    if type(package) is not dict or set(package) != expected:
        raise QualificationFailure("output_failed")
    if not _valid_digest(package["git_sha"], (40, 64)):
        raise QualificationFailure("output_failed")
    if not all(
        _valid_digest(package[key])
        for key in ("launcher_sha256", "application_sha256", "manifest_sha256")
    ):
        raise QualificationFailure("output_failed")
    notices = package["notice_hashes"]
    if type(notices) is not dict or set(notices) != set(NOTICE_FILES):
        raise QualificationFailure("output_failed")
    if not all(_valid_digest(notices[name]) for name in NOTICE_FILES):
        raise QualificationFailure("output_failed")


def _validate_success_metrics(metrics: object) -> None:
    expected = {
        "direct_ready_ms",
        "supervised_ready_ms",
        "peak_process_tree_memory_bytes",
        "idle_write_bytes",
        "hard_exit_ready_receipt_to_report_verification_ms",
        "handled_ready_receipt_to_report_verification_ms",
        "hard_incident_assembly_to_verification_ms",
        "handled_incident_assembly_to_verification_ms",
        "flood_elapsed_ms",
    }
    if type(metrics) is not dict or set(metrics) != expected:
        raise QualificationFailure("output_failed")
    supervised = metrics["supervised_ready_ms"]
    scalar_keys = expected - {"supervised_ready_ms"}
    if (
        type(supervised) is not list
        or len(supervised) != 3
        or not all(_bounded_counter(value) for value in supervised)
        or not all(_bounded_counter(metrics[key]) for key in scalar_keys)
    ):
        raise QualificationFailure("output_failed")


def _validate_output_payload(payload: object) -> None:
    expected = {"schema_version", "status", "failure_id", "package", "checks", "metrics"}
    if type(payload) is not dict or set(payload) != expected:
        raise QualificationFailure("output_failed")
    if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
        raise QualificationFailure("output_failed")
    if payload["status"] == "failed":
        if (
            payload["failure_id"] not in FAILURE_IDS
            or payload["package"] is not None
            or payload["checks"] != []
            or payload["metrics"] is not None
        ):
            raise QualificationFailure("output_failed")
        return
    if payload["status"] != "passed" or payload["failure_id"] is not None:
        raise QualificationFailure("output_failed")
    checks = payload["checks"]
    if checks != [{"id": check_id, "status": "passed"} for check_id in CHECK_IDS]:
        raise QualificationFailure("output_failed")
    _validate_package_receipt(payload["package"])
    _validate_success_metrics(payload["metrics"])


def _success_payload(
    package: dict[str, object],
    results: dict[str, ScenarioResult],
    *,
    idle_write_bytes: int,
    hard_ready_to_report_ms: int,
    handled_ready_to_report_ms: int,
    hard_assembly_to_verification_ms: int,
    handled_assembly_to_verification_ms: int,
) -> dict[str, object]:
    peak = max(result.metrics.peak_job_memory_bytes for result in results.values())
    return {
        "schema_version": 1,
        "status": "passed",
        "failure_id": None,
        "package": package,
        "checks": [{"id": check_id, "status": "passed"} for check_id in CHECK_IDS],
        "metrics": {
            "direct_ready_ms": results["direct_normal"].ready_ms,
            "supervised_ready_ms": [
                results[name].ready_ms
                for name in ("supervised_normal_1", "supervised_normal_2", "supervised_normal_3")
            ],
            "peak_process_tree_memory_bytes": peak,
            "idle_write_bytes": idle_write_bytes,
            "hard_exit_ready_receipt_to_report_verification_ms": hard_ready_to_report_ms,
            "handled_ready_receipt_to_report_verification_ms": handled_ready_to_report_ms,
            "hard_incident_assembly_to_verification_ms": hard_assembly_to_verification_ms,
            "handled_incident_assembly_to_verification_ms": (
                handled_assembly_to_verification_ms
            ),
            "flood_elapsed_ms": results["flood"].elapsed_ms,
        },
    }


class _QualificationRunner:
    def __init__(self, artifact: Path, private_root: Path, deadline: float) -> None:
        self.artifact = artifact
        self.private_root = private_root
        self.deadline = deadline
        self.api = _WindowsApi()
        self.state_base = private_root / "stan lokalny"
        (self.state_base / "Roaming").mkdir(parents=True)
        self.store = IncidentStore(self.state_base / "Metroliza" / "diagnostics")
        self.launcher = artifact / "metroliza.exe"
        self.application = artifact / "metroliza_application.exe"
        self.results: dict[str, ScenarioResult] = {}
        self.idle_write_bytes = 0
        self.hard_ready_to_report_ms = 0
        self.handled_ready_to_report_ms = 0
        self.hard_assembly_to_verification_ms = 0
        self.handled_assembly_to_verification_ms = 0

    def _root(self, label: str) -> Path:
        return _prepare_work_root(self.private_root, label)

    def _scenario(
        self,
        key: str,
        scenario: str,
        *,
        executable: Path | None = None,
        state_base: Path | None = None,
        expected_exit: int = 0,
        expected_stage: str = "complete",
        on_ready: Callable[[_WindowsProcess], None] | None = None,
    ) -> Path:
        root = self._root(key.replace("_", "-"))
        self.results[key] = _run_scenario(
            self.api,
            self.launcher if executable is None else executable,
            self.artifact,
            root,
            self.state_base if state_base is None else state_base,
            scenario,
            self.deadline,
            expected_exit=expected_exit,
            expected_stage=expected_stage,
            on_ready=on_ready,
        )
        return root

    def run_startups(self) -> None:
        self._scenario("direct_normal", "normal", executable=self.application)
        before = {record.report_id for record in _reports(self.store)}
        for index in range(1, 4):
            self._scenario(f"supervised_normal_{index}", "normal")
        if {record.report_id for record in _reports(self.store)} != before:
            raise QualificationFailure("incident_invalid")

    def run_hard_exit(self) -> None:
        before = {record.report_id for record in _reports(self.store)}
        observed: dict[str, float] = {}

        def note_ready(_process: _WindowsProcess) -> None:
            observed["ready"] = time.perf_counter()

        self._scenario(
            "hard_exit",
            "hard_exit",
            expected_exit=9,
            expected_stage="ready",
            on_ready=note_ready,
        )
        incident = _newest_incident(self.store, before)
        self.hard_ready_to_report_ms = round(
            (time.perf_counter() - observed["ready"]) * 1000
        )
        self.hard_assembly_to_verification_ms = max(
            0, time.time_ns() // 1_000_000 - incident.created_at_ms
        )
        if (
            incident.observation.exit_code != 9
            or incident.observation.channel is ChannelState.COMPLETE
        ):
            raise QualificationFailure("incident_invalid")

    def run_handled_failure(self) -> None:
        before = {record.report_id for record in _reports(self.store)}
        root = self._root("handled-failure")

        def finish(_process: _WindowsProcess) -> None:
            observed = time.perf_counter()
            incident = _wait_newest_incident(self.store, before, self.deadline)
            if incident.observation.termination.value != "still_running":
                raise QualificationFailure("incident_invalid")
            events = [decode_event(event) for event in incident.events]
            terminal = next(
                (
                    event
                    for event in reversed(events)
                    if type(event) is WorkflowDiagnosticEvent
                ),
                None,
            )
            if terminal is None or terminal.outcome is not WorkflowOutcome.FAILED:
                raise QualificationFailure("incident_invalid")
            self.handled_ready_to_report_ms = round(
                (time.perf_counter() - observed) * 1000
            )
            self.handled_assembly_to_verification_ms = max(
                0, time.time_ns() // 1_000_000 - incident.created_at_ms
            )
            (root / "finish").touch(exist_ok=False)

        self.results["handled_failure"] = _run_scenario(
            self.api,
            self.launcher,
            self.artifact,
            root,
            self.state_base,
            "handled_failure",
            self.deadline,
            expected_exit=0,
            expected_stage="complete",
            on_ready=finish,
        )

    def run_preview(self) -> None:
        selected = _reports(self.store)[0].report_id
        root = self._scenario("preview", "preview")
        _validate_selected_export(root / "selected.zip", selected)

    def run_idle(self) -> None:
        root = self._root("idle")

        def finish(process: _WindowsProcess) -> None:
            before = process.metrics().write_bytes
            hold_until = min(self.deadline, time.monotonic() + 2.0)
            while time.monotonic() < hold_until:
                if process.poll() is not None:
                    raise QualificationFailure("scenario_failed")
                time.sleep(0.05)
            self.idle_write_bytes = max(0, process.metrics().write_bytes - before)
            (root / "finish").touch(exist_ok=False)

        self.results["idle"] = _run_scenario(
            self.api,
            self.launcher,
            self.artifact,
            root,
            self.state_base,
            "idle",
            self.deadline,
            expected_exit=0,
            expected_stage="complete",
            on_ready=finish,
        )

    def run_flood(self) -> None:
        before = {record.report_id for record in _reports(self.store)}
        self._scenario("flood", "flood")
        incident = _newest_incident(self.store, before)
        explicit_channel = incident.observation.channel in {
            ChannelState.FLOODED,
            ChannelState.LOSS_OBSERVED,
        }
        loss = incident.ring_loss
        explicit_loss = incident.observation.source_dropped > 0 or any(
            (
                loss.invalid_events,
                loss.sequence_rejected_events,
                loss.normal_count_dropped_events,
                loss.normal_byte_dropped_events,
                loss.terminal_dropped_events,
            )
        )
        if not explicit_channel or (
            incident.observation.channel is ChannelState.LOSS_OBSERVED and not explicit_loss
        ):
            raise QualificationFailure("incident_invalid")

    def run_unavailable_store(self) -> None:
        before = {record.report_id for record in _reports(self.store)}
        occupied = self.private_root / "occupied-local-state"
        occupied.write_bytes(b"fixed")
        root = self._scenario("unavailable_store", "normal", state_base=occupied)
        after = {record.report_id for record in _reports(self.store)}
        fallback_files = tuple(root.glob("incident-*.json")) + tuple(root.glob("metroliza.log"))
        if after != before or fallback_files:
            raise QualificationFailure("incident_invalid")

    def run_missing_components(self) -> None:
        before = {record.report_id for record in _reports(self.store)}
        root = self._root("missing-components")
        package = root / "minimal package"
        package.mkdir()
        shutil.copy2(self.launcher, package / self.launcher.name)
        shutil.copy2(self.artifact / MANIFEST_NAME, package / MANIFEST_NAME)
        environment = _sanitized_environment(package, root, self.state_base, "normal")
        process = self.api.launch(package / self.launcher.name, environment, root)
        terminate = True
        try:
            exit_code = self._wait_missing_exit(process)
            if exit_code != 1 or (root / "qualification.json").exists():
                raise QualificationFailure("scenario_failed")
            terminate = False
            self.results["missing_components"] = ScenarioResult(
                1,
                round((time.perf_counter() - process.started) * 1000),
                0,
                None,
                process.metrics(),
            )
        finally:
            process.close(terminate=terminate)
        incident = _newest_incident(self.store, before)
        if incident.observation.launch is not LaunchState.FAILED:
            raise QualificationFailure("incident_invalid")

    def run_missing_qt_resource(self) -> None:
        before = {record.report_id for record in _reports(self.store)}
        root = self._root("missing-qt-resource")
        resource = (
            self.artifact
            / "_internal"
            / "PyQt6"
            / "Qt6"
            / "plugins"
            / "platforms"
            / "qwindows.dll"
        )
        hidden = resource.with_name("qwindows.qualification-missing")
        digest = _sha256(resource)
        environment = _sanitized_environment(
            self.artifact, root, self.state_base, "normal"
        )
        environment["QT_QPA_PLATFORM"] = "windows"
        resource.replace(hidden)
        try:
            process = self.api.launch(self.launcher, environment, root)
            terminate = True
            try:
                exit_code = self._wait_missing_exit(process)
                if exit_code in (None, 0) or (root / "qualification.json").exists():
                    raise QualificationFailure("scenario_failed")
                terminate = False
                self.results["missing_qt_resource"] = ScenarioResult(
                    exit_code,
                    round((time.perf_counter() - process.started) * 1000),
                    0,
                    None,
                    process.metrics(),
                )
            finally:
                process.close(terminate=terminate)
        finally:
            hidden.replace(resource)
        if _sha256(resource) != digest:
            raise QualificationFailure("artifact_invalid")
        incident = _newest_incident(self.store, before)
        events = [decode_event(event) for event in incident.events]
        useful = any(
            type(event) in (RuntimeProvenanceEvent, StartupDiagnosticEvent)
            for event in events
        )
        observation = incident.observation
        if (
            observation.launch is not LaunchState.STARTED
            or observation.handshake is not HandshakeState.ACCEPTED
            or observation.exit_code in (None, 0)
            or not useful
        ):
            raise QualificationFailure("incident_invalid")

    def _wait_missing_exit(self, process: _WindowsProcess) -> int | None:
        deadline = min(self.deadline, time.monotonic() + MAX_SCENARIO_SECONDS)
        while time.monotonic() < deadline:
            exit_code = process.poll()
            if exit_code is not None:
                return exit_code
            time.sleep(0.02)
        raise QualificationFailure("scenario_timeout")

    def run(self, package: dict[str, object]) -> dict[str, object]:
        self.run_startups()
        self.run_hard_exit()
        self.run_handled_failure()
        self.run_preview()
        self.run_idle()
        self.run_flood()
        self.run_unavailable_store()
        self.run_missing_components()
        self.run_missing_qt_resource()
        return _success_payload(
            package,
            self.results,
            idle_write_bytes=self.idle_write_bytes,
            hard_ready_to_report_ms=self.hard_ready_to_report_ms,
            handled_ready_to_report_ms=self.handled_ready_to_report_ms,
            hard_assembly_to_verification_ms=self.hard_assembly_to_verification_ms,
            handled_assembly_to_verification_ms=(
                self.handled_assembly_to_verification_ms
            ),
        )


def _qualification_payload(
    artifact: Path,
    deadline: float,
) -> dict[str, object]:
    package = _validate_package(artifact)
    if _sha256(FIXTURE, maximum=128 * 1024) != FIXTURE_SHA256:
        raise QualificationFailure("fixture_invalid")
    if time.monotonic() >= deadline:
        raise QualificationFailure("scenario_timeout")
    with tempfile.TemporaryDirectory(prefix="Metroliza kwalifikacja żółć ") as private:
        private_root = Path(private)
        relocated = _relocate_package(artifact, private_root, deadline)
        if _validate_package(relocated) != package:
            raise QualificationFailure("artifact_invalid")
        return _QualificationRunner(relocated, private_root, deadline).run(package)


def qualify_windows_diagnostics(
    artifact_dir: Path,
    output_dir: Path,
    *,
    timeout_seconds: int = MAX_TOTAL_SECONDS,
) -> QualificationResult:
    if os.name != "nt":
        return QualificationResult("failed", "unsupported_platform", None)
    valid = (
        type(timeout_seconds) is int
        and 60 <= timeout_seconds <= MAX_TOTAL_SECONDS
        and artifact_dir.is_absolute()
        and output_dir.is_absolute()
    )
    if not valid:
        return QualificationResult("failed", "invalid_arguments", None)
    try:
        if artifact_dir.is_symlink():
            raise QualificationFailure("artifact_invalid")
        try:
            artifact = artifact_dir.resolve(strict=True)
        except OSError:
            raise QualificationFailure("artifact_invalid") from None
        if not artifact.is_dir():
            raise QualificationFailure("artifact_invalid")
        try:
            output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        except OSError:
            raise QualificationFailure("output_failed") from None
        deadline = time.monotonic() + timeout_seconds
        payload = _qualification_payload(artifact, deadline)
        if time.monotonic() >= deadline:
            raise QualificationFailure("scenario_timeout")
        destination = _write_receipt(output_dir, payload)
        return QualificationResult("passed", None, destination)
    except QualificationFailure as error:
        return QualificationResult("failed", error.failure_id, None)
    except Exception:
        return QualificationResult("failed", "scenario_failed", None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    result = qualify_windows_diagnostics(arguments.artifact_dir, arguments.output_dir)
    if result.status == "passed":
        return 0
    if result.failure_id in FAILURE_IDS and result.failure_id != "output_failed":
        try:
            output = arguments.output_dir
            if output.is_absolute() and not output.exists():
                output.mkdir(mode=0o700, parents=True)
            if output.is_dir() and not set(output.iterdir()):
                _write_receipt(
                    output,
                    {
                        "schema_version": 1,
                        "status": "failed",
                        "failure_id": result.failure_id,
                        "package": None,
                        "checks": [],
                        "metrics": None,
                    },
                )
        except (OSError, QualificationFailure):
            pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

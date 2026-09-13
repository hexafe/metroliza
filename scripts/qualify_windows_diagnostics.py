"""Qualify the bounded diagnostics path in one exact Windows onedir package."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, TypeVar

from metroliza.app.build_provenance import BuildProvenance
from metroliza.shared.diagnostic_events import (
    RuntimeProvenanceEvent,
    StartupDiagnosticEvent,
    ValidationStatus,
    WorkflowDiagnosticEvent,
    WorkflowOperation,
    WorkflowOutcome,
    WorkflowStage,
)
from metroliza.shared.diagnostic_incident import (
    ChannelState,
    HandshakeState,
    LaunchState,
    decode_incident,
)
from metroliza.shared.diagnostic_package import MANIFEST_NAME, inspect_package
from metroliza.shared.diagnostic_ring import RingLoss
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus
from metroliza.shared.diagnostic_wire import decode_event

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"
FIXTURE_SHA256 = "ca500bd52afc2551560e7c0009851906a0d3bec6b35282e20703c1e298da608b"
OUTPUT_NAME = "windows-diagnostic-qualification.json"
PACKAGE_MANIFEST_NAME = "package-manifest.json"
PACKAGE_ARCHIVE_NAME = "qualified-windows-development-package.zip"
QUALIFICATION_RECEIPT_NAMES = {
    "ready": "qualification-ready.json",
    "complete": "qualification-complete.json",
    "failed": "qualification-failed.json",
}
MAX_TOTAL_SECONDS = 720
MAX_SCENARIO_SECONDS = 90
MAX_RECEIPT_BYTES = 64 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_PACKAGE_COPY_BYTES = 2 * 1024 * 1024 * 1024
MAX_PACKAGE_ARCHIVE_BYTES = MAX_PACKAGE_COPY_BYTES + 64 * 1024 * 1024
MAX_PACKAGE_ENTRIES = 25_000
MAX_PACKAGE_PATH_CHARS = 512
MAX_PACKAGE_MANIFEST_BYTES = 16 * 1024 * 1024
IDLE_SAMPLE_MILLISECONDS = 2_000
MAX_STARTUP_READY_MILLISECONDS = 60_000
MAX_SUPERVISOR_STARTUP_OVERHEAD_MILLISECONDS = 10_000
MAX_SUPERVISOR_MEMORY_OVERHEAD_BYTES = 128 * 1024 * 1024
MAX_IDLE_WRITE_BYTES = 64 * 1024
MAX_INCIDENT_ASSEMBLY_TO_VERIFICATION_MILLISECONDS = 10_000
MAX_FLOOD_ELAPSED_MILLISECONDS = 90_000
MAX_TERMINATION_DRAIN_MILLISECONDS = 5_000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x00000102
TOKEN_INTEGRITY_LEVEL = 25
MEDIUM_INTEGRITY_RID = 0x2000
MAX_TOKEN_INFORMATION_BYTES = 256
WINDOWS_ERROR_INVALID_PARAMETER = 87
NOTICE_FILES = ("THIRD_PARTY_NOTICES.md", "third_party_inventory_260711.json")
CHECK_IDS = (
    "package_identity",
    "no_console",
    "restricted_token",
    "direct_workflow",
    "supervised_workflow",
    "repeat_starts",
    "concurrent_instances",
    "interactive_ui_smoke",
    "hard_exit_incident",
    "handled_failure_live",
    "selected_export",
    "idle_writes",
    "flood_loss",
    "unavailable_store",
    "missing_components",
    "missing_qt_resource",
)
OPERATIONAL_CHECK_ID = "operational_cost"
RING_LOSS_FIELDS = tuple(RingLoss.__dataclass_fields__)
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
DRIVER_FAILURE_STAGES = frozenset(
    {
        "package",
        "relocation",
        "runner",
        "startups",
        "direct_normal_1",
        "direct_normal_2",
        "supervised_normal_1",
        "supervised_normal_2",
        "concurrent",
        "concurrent_1",
        "concurrent_2",
        "ui_smoke",
        "hard_exit",
        "handled_failure",
        "preview",
        "idle",
        "direct_idle",
        "supervised_idle",
        "flood",
        "unavailable_store",
        "missing_components",
        "missing_qt_resource",
        "artifacts",
        "receipt",
    }
)
QUALIFICATION_FAILURE_STAGES = DRIVER_FAILURE_STAGES
CHILD_FAILURE_STAGES = frozenset(
    {"root", "application", "workflows", "preview", "flood", "receipt"}
)
QUALIFICATION_FAILURE_REASONS = frozenset(
    {
        "invalid_qualification_root",
        "invalid_qualification_arguments",
        "qualification_barrier_timeout",
        "qualification_fixture_mismatch",
        "qualification_output_exists",
        "qualification_output_unavailable",
        "qualification_result_mismatch",
        "qualification_import_failed",
        "qualification_incident_missing",
        "qualification_measurements_missing",
        "qualification_export_failed",
        "qualification_export_unavailable",
        "qualification_filename_control_unavailable",
        "qualification_preview_unavailable",
        "qualification_cleanup_failed",
        "process_exited_before_startup",
        "process_exited_before_result",
        "process_exit_mismatch",
        "unexpected",
    }
)
QUALIFICATION_CLEANUP_STATUSES = frozenset(
    {"not_attempted", "complete", "failed"}
)


class QualificationFailure(RuntimeError):
    """A fixed failure identity which never includes native or input-controlled text."""

    def __init__(
        self,
        failure_id: str,
        *,
        qualification_stage: str | None = None,
        qualification_reason: str | None = None,
        qualification_child_stage: str | None = None,
        qualification_exit_code: int | None = None,
        qualification_cleanup: str = "not_attempted",
    ) -> None:
        if failure_id not in FAILURE_IDS:
            failure_id = "scenario_failed"
        self.failure_id = failure_id
        self.qualification_stage = qualification_stage
        self.qualification_reason = qualification_reason
        self.qualification_child_stage = (
            qualification_child_stage
            if qualification_child_stage in CHILD_FAILURE_STAGES
            else None
        )
        self.qualification_exit_code = (
            qualification_exit_code
            if type(qualification_exit_code) is int
            and -(2**31) <= qualification_exit_code <= 2**32 - 1
            else None
        )
        self.qualification_cleanup = (
            qualification_cleanup
            if type(qualification_cleanup) is str
            and qualification_cleanup in QUALIFICATION_CLEANUP_STATUSES
            else "not_attempted"
        )
        super().__init__(failure_id)

    def record_cleanup(self, *, succeeded: bool) -> None:
        if not succeeded:
            self.qualification_cleanup = "failed"
        elif self.qualification_cleanup == "not_attempted":
            self.qualification_cleanup = "complete"


_T = TypeVar("_T")


def _run_driver_phase(stage: str, action: Callable[[], _T]) -> _T:
    if stage not in DRIVER_FAILURE_STAGES:
        raise QualificationFailure("scenario_failed")
    try:
        return action()
    except QualificationFailure as error:
        if (
            error.qualification_stage in QUALIFICATION_FAILURE_STAGES
            and error.qualification_reason in QUALIFICATION_FAILURE_REASONS
        ):
            raise
        raise QualificationFailure(
            error.failure_id,
            qualification_stage=stage,
            qualification_reason=(
                error.qualification_reason
                if error.qualification_reason in QUALIFICATION_FAILURE_REASONS
                else "unexpected"
            ),
            qualification_child_stage=error.qualification_child_stage,
            qualification_exit_code=error.qualification_exit_code,
            qualification_cleanup=error.qualification_cleanup,
        ) from None
    except Exception:
        raise QualificationFailure(
            "scenario_failed",
            qualification_stage=stage,
            qualification_reason="unexpected",
        ) from None


@dataclass(frozen=True, slots=True)
class ProcessMetrics:
    peak_job_memory_bytes: int
    read_operations: int
    write_operations: int
    read_bytes: int
    write_bytes: int


@dataclass(frozen=True, slots=True)
class _ProcessObservation:
    process_id: int
    creation_time: int
    image: str


@dataclass(frozen=True, slots=True)
class ProcessTopology:
    launcher_processes_observed: int
    application_processes_observed: int
    unexpected_processes_observed: int
    assigned_processes: int
    max_active_processes: int
    creation_order: tuple[str, ...]
    all_processes_exited: bool


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    exit_code: int
    elapsed_ms: int
    startup_ready_ms: int
    receipt_stage: str | None
    metrics: ProcessMetrics
    topology: ProcessTopology


@dataclass(frozen=True, slots=True)
class PackageEntry:
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class QualificationResult:
    status: str
    failure_id: str | None
    receipt_path: Path | None
    qualification_stage: str | None = None
    qualification_reason: str | None = None
    qualification_child_stage: str | None = None
    qualification_exit_code: int | None = None
    qualification_cleanup: str = "not_attempted"
    output_identity: tuple[int, int] | None = None


def _attempt_cleanup(action: Callable[[], None]) -> None:
    primary = sys.exc_info()[1]
    try:
        action()
    except Exception:
        if isinstance(primary, QualificationFailure):
            primary.record_cleanup(succeeded=False)
            return
        if primary is not None and not isinstance(primary, Exception):
            return
        raise QualificationFailure(
            "scenario_failed",
            qualification_reason=(
                "unexpected" if isinstance(primary, Exception)
                else "qualification_cleanup_failed"
            ),
            qualification_cleanup="failed",
        ) from None
    if isinstance(primary, QualificationFailure):
        primary.record_cleanup(succeeded=True)
    elif isinstance(primary, Exception):
        raise QualificationFailure(
            "scenario_failed",
            qualification_reason="unexpected",
            qualification_cleanup="complete",
        ) from None


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
        opened = os.fstat(stream.fileno())
        expected_identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            )
            != expected_identity
        ):
            raise QualificationFailure("artifact_invalid")
        while remaining:
            block = stream.read(min(1024 * 1024, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
        closed_identity = os.fstat(stream.fileno())
    if remaining == 0:
        raise QualificationFailure("artifact_invalid")
    final = path.lstat()
    if (
        (
            closed_identity.st_dev,
            closed_identity.st_ino,
            closed_identity.st_size,
            closed_identity.st_mtime_ns,
        )
        != expected_identity
        or (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
        != expected_identity
    ):
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


def _classify_topology(
    observations: tuple[_ProcessObservation, ...],
    assigned_processes: int,
    max_active_processes: int,
    all_exited: bool,
    launcher: Path,
    application: Path,
) -> ProcessTopology:
    launcher_image = os.path.normcase(os.path.abspath(launcher))
    application_image = os.path.normcase(os.path.abspath(application))
    launcher_count = 0
    application_count = 0
    unexpected_count = 0
    order: list[str] = []
    for observation in sorted(
        observations, key=lambda value: (value.creation_time, value.process_id)
    ):
        image = os.path.normcase(os.path.abspath(observation.image))
        if image == launcher_image:
            launcher_count += 1
            order.append(
                "launcher_bootloader" if launcher_count == 1 else "launcher_supervisor"
            )
        elif image == application_image:
            application_count += 1
            order.append("application")
        else:
            unexpected_count += 1
            order.append("unexpected")
    for _ in range(max(0, assigned_processes - len(observations))):
        unexpected_count += 1
        order.append("unexpected")
    return ProcessTopology(
        launcher_count,
        application_count,
        unexpected_count,
        assigned_processes,
        max_active_processes,
        tuple(order),
        all_exited,
    )


class _WindowsProcess:
    def __init__(
        self,
        api,
        process_handle,
        job_handle,
        started: float,
        initial: _ProcessObservation,
    ) -> None:
        self._api = api
        self._process = process_handle
        self._job = job_handle
        self.started = started
        self._closed = False
        self._observations = {initial.process_id: initial}
        self._assigned_processes = 1
        self._max_active_processes = 1

    def poll(self) -> int | None:
        return self._api.poll(self._process)

    def metrics(self) -> ProcessMetrics:
        return self._api.job_metrics(self._job)

    def observe(self) -> None:
        observations, active, assigned = self._api.job_observations(self._job)
        self._assigned_processes = max(self._assigned_processes, assigned)
        self._max_active_processes = max(self._max_active_processes, active)
        self._observations.update(
            {observation.process_id: observation for observation in observations}
        )

    def topology(self, artifact_dir: Path, *, all_exited: bool) -> ProcessTopology:
        return _classify_topology(
            tuple(self._observations.values()),
            self._assigned_processes,
            self._max_active_processes,
            all_exited,
            artifact_dir / "metroliza.exe",
            artifact_dir / "metroliza_application.exe",
        )

    def active_processes(self) -> int:
        observations, active, assigned = self._api.job_observations(self._job)
        self._assigned_processes = max(self._assigned_processes, assigned)
        self._observations.update(
            {observation.process_id: observation for observation in observations}
        )
        self._max_active_processes = max(self._max_active_processes, active)
        return active

    def close(self, *, terminate: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        _attempt_cleanup(
            lambda: self._api.close_process(
                self._process, self._job, terminate=terminate
            )
        )


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

        class SID_IDENTIFIER_AUTHORITY(ctypes.Structure):
            _fields_ = [("Value", wt.BYTE * 6)]

        class TOKEN_MANDATORY_LABEL(ctypes.Structure):
            _fields_ = [("Label", SID_AND_ATTRIBUTES)]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wt.DWORD), ("dwHighDateTime", wt.DWORD)]

        class JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
            _fields_ = [
                ("NumberOfAssignedProcesses", wt.DWORD),
                ("NumberOfProcessIdsInList", wt.DWORD),
                ("ProcessIdList", ctypes.c_size_t * 16),
            ]

        class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wt.DWORD),
                ("TotalProcesses", wt.DWORD),
                ("ActiveProcesses", wt.DWORD),
                ("TotalTerminatedProcesses", wt.DWORD),
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
        self.SID_IDENTIFIER_AUTHORITY = SID_IDENTIFIER_AUTHORITY
        self.TOKEN_MANDATORY_LABEL = TOKEN_MANDATORY_LABEL
        self.EXTENDED_LIMITS = JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        self.FILETIME = FILETIME
        self.PROCESS_IDS = JOBOBJECT_BASIC_PROCESS_ID_LIST
        self.BASIC_ACCOUNTING = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION

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
        self.kernel.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
        self.kernel.TerminateJobObject.restype = wt.BOOL
        self.kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        self.kernel.OpenProcess.restype = wt.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [
            wt.HANDLE,
            wt.DWORD,
            wt.LPWSTR,
            ctypes.POINTER(wt.DWORD),
        ]
        self.kernel.QueryFullProcessImageNameW.restype = wt.BOOL
        self.kernel.GetProcessTimes.argtypes = [
            wt.HANDLE,
            ctypes.POINTER(self.FILETIME),
            ctypes.POINTER(self.FILETIME),
            ctypes.POINTER(self.FILETIME),
            ctypes.POINTER(self.FILETIME),
        ]
        self.kernel.GetProcessTimes.restype = wt.BOOL

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
        self.advapi.AllocateAndInitializeSid.argtypes = [
            ctypes.POINTER(self.SID_IDENTIFIER_AUTHORITY),
            wt.BYTE,
            wt.DWORD,
            wt.DWORD,
            wt.DWORD,
            wt.DWORD,
            wt.DWORD,
            wt.DWORD,
            wt.DWORD,
            wt.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.advapi.AllocateAndInitializeSid.restype = wt.BOOL
        self.advapi.FreeSid.argtypes = [ctypes.c_void_p]
        self.advapi.FreeSid.restype = ctypes.c_void_p
        self.advapi.GetLengthSid.argtypes = [ctypes.c_void_p]
        self.advapi.GetLengthSid.restype = wt.DWORD
        self.advapi.SetTokenInformation.argtypes = [
            wt.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wt.DWORD,
        ]
        self.advapi.SetTokenInformation.restype = wt.BOOL
        self.advapi.GetTokenInformation.argtypes = [
            wt.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wt.DWORD,
            ctypes.POINTER(wt.DWORD),
        ]
        self.advapi.GetTokenInformation.restype = wt.BOOL
        self.advapi.IsValidSid.argtypes = [ctypes.c_void_p]
        self.advapi.IsValidSid.restype = wt.BOOL
        self.advapi.GetSidIdentifierAuthority.argtypes = [ctypes.c_void_p]
        self.advapi.GetSidIdentifierAuthority.restype = ctypes.POINTER(
            self.SID_IDENTIFIER_AUTHORITY
        )
        self.advapi.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        self.advapi.GetSidSubAuthorityCount.restype = ctypes.POINTER(wt.BYTE)
        self.advapi.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wt.DWORD]
        self.advapi.GetSidSubAuthority.restype = ctypes.POINTER(wt.DWORD)
        self.advapi.DuplicateToken.argtypes = [
            wt.HANDLE,
            ctypes.c_int,
            ctypes.POINTER(wt.HANDLE),
        ]
        self.advapi.DuplicateToken.restype = wt.BOOL
        self.advapi.CheckTokenMembership.argtypes = [
            wt.HANDLE,
            ctypes.c_void_p,
            ctypes.POINTER(wt.BOOL),
        ]
        self.advapi.CheckTokenMembership.restype = wt.BOOL
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

    def _close_handles(self, *handles) -> bool:
        complete = True
        for handle in handles:
            if not handle:
                continue
            try:
                if not self.kernel.CloseHandle(handle):
                    complete = False
            except Exception:
                complete = False
        return complete

    def _require_closed_handles(self, *handles) -> None:
        if not self._close_handles(*handles):
            raise QualificationFailure(
                "scenario_failed",
                qualification_reason="qualification_cleanup_failed",
                qualification_cleanup="failed",
            )

    def _free_sid(self, sid) -> None:
        if self.advapi.FreeSid(sid):
            raise QualificationFailure(
                "scenario_failed",
                qualification_reason="qualification_cleanup_failed",
                qualification_cleanup="failed",
            )

    def _cleanup_created_process(self, process, job) -> bool:
        with contextlib.suppress(Exception):
            self.kernel.TerminateJobObject(job, 22)
        with contextlib.suppress(Exception):
            self.kernel.TerminateProcess(process.hProcess, 22)
        deadline = time.monotonic() + MAX_TERMINATION_DRAIN_MILLISECONDS / 1000
        drained = False
        while time.monotonic() < deadline:
            try:
                wait_result = self.kernel.WaitForSingleObject(process.hProcess, 0)
                active, _total = self._job_accounting(job)
            except Exception:
                break
            if wait_result == WAIT_OBJECT_0 and active == 0:
                drained = True
                break
            if wait_result not in {WAIT_OBJECT_0, WAIT_TIMEOUT}:
                break
            time.sleep(0.01)
        return self._close_handles(process.hThread, process.hProcess, job) and drained

    def _create_suspended_process(
        self,
        token,
        executable: Path,
        command,
        flags: int,
        environment_block,
        cwd: Path,
        startup,
        process,
    ) -> bool:
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
        if created or ctypes.get_last_error() != 1314:
            return bool(created)
        fallback_command = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([str(executable)])
        )
        return bool(
            self.advapi.CreateProcessWithTokenW(
                token,
                0,
                str(executable),
                fallback_command,
                flags,
                environment_block,
                str(cwd),
                ctypes.byref(startup),
                ctypes.byref(process),
            )
        )

    def _finish_launched_process(self, process, job, started, initial):
        if not self._close_handles(process.hThread):
            raise QualificationFailure("restricted_launch_unavailable")
        return _WindowsProcess(self, process.hProcess, job, started, initial)

    def _has_effective_admin_membership(self, token, sid) -> bool:
        wt = self.wintypes
        impersonation = wt.HANDLE()
        if not self.advapi.DuplicateToken(token, 1, ctypes.byref(impersonation)):
            raise QualificationFailure("restricted_launch_unavailable")
        try:
            is_admin = wt.BOOL()
            if not self.advapi.CheckTokenMembership(
                impersonation, sid, ctypes.byref(is_admin)
            ):
                raise QualificationFailure("restricted_launch_unavailable")
            return bool(is_admin.value)
        finally:
            _attempt_cleanup(
                lambda: self._require_closed_handles(impersonation)
            )

    def _set_medium_integrity(self, token) -> None:
        authority = self.SID_IDENTIFIER_AUTHORITY((0, 0, 0, 0, 0, 16))
        medium_sid = ctypes.c_void_p()
        if not self.advapi.AllocateAndInitializeSid(
            ctypes.byref(authority),
            1,
            MEDIUM_INTEGRITY_RID,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            ctypes.byref(medium_sid),
        ):
            raise QualificationFailure("restricted_launch_unavailable")
        try:
            sid_length = int(self.advapi.GetLengthSid(medium_sid))
            if not 0 < sid_length <= 68:
                raise QualificationFailure("restricted_launch_unavailable")
            label = self.TOKEN_MANDATORY_LABEL(
                self.SID_AND_ATTRIBUTES(medium_sid, 0x20)
            )
            if not self.advapi.SetTokenInformation(
                token,
                TOKEN_INTEGRITY_LEVEL,
                ctypes.byref(label),
                ctypes.sizeof(label) + sid_length,
            ):
                raise QualificationFailure("restricted_launch_unavailable")
        finally:
            _attempt_cleanup(lambda: self._free_sid(medium_sid))

    def _integrity_rid(self, token) -> int:
        wt = self.wintypes
        required = wt.DWORD()
        self.advapi.GetTokenInformation(
            token, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(required)
        )
        if not 0 < required.value <= MAX_TOKEN_INFORMATION_BYTES:
            raise QualificationFailure("restricted_launch_unavailable")
        buffer = ctypes.create_string_buffer(required.value)
        if not self.advapi.GetTokenInformation(
            token,
            TOKEN_INTEGRITY_LEVEL,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise QualificationFailure("restricted_launch_unavailable")
        label = ctypes.cast(
            buffer, ctypes.POINTER(self.TOKEN_MANDATORY_LABEL)
        ).contents.Label
        if not label.Sid or not self.advapi.IsValidSid(label.Sid):
            raise QualificationFailure("restricted_launch_unavailable")
        authority = self.advapi.GetSidIdentifierAuthority(label.Sid)
        count = self.advapi.GetSidSubAuthorityCount(label.Sid)
        if (
            not authority
            or not count
            or tuple(authority.contents.Value) != (0, 0, 0, 0, 0, 16)
            or not 0 < count.contents.value <= 8
        ):
            raise QualificationFailure("restricted_launch_unavailable")
        rid = self.advapi.GetSidSubAuthority(label.Sid, count.contents.value - 1)
        if not rid:
            raise QualificationFailure("restricted_launch_unavailable")
        return int(rid.contents.value)

    def _restricted_token(self):
        wt = self.wintypes
        current = wt.HANDLE()
        restricted = wt.HANDLE()
        token_access = 0x0001 | 0x0002 | 0x0008 | 0x0080
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
            self._set_medium_integrity(restricted)
            if self._integrity_rid(restricted) != MEDIUM_INTEGRITY_RID:
                raise QualificationFailure("restricted_launch_unavailable")
            if self._has_effective_admin_membership(restricted, sid):
                raise QualificationFailure("restricted_launch_unavailable")
            return restricted
        except Exception:
            if restricted:
                _attempt_cleanup(
                    lambda: self._require_closed_handles(restricted)
                )
            raise
        finally:
            try:
                _attempt_cleanup(lambda: self._require_closed_handles(current))
            except QualificationFailure as error:
                if restricted:
                    error.record_cleanup(
                        succeeded=self._close_handles(restricted)
                    )
                raise

    def launch(
        self,
        executable: Path,
        environment: dict[str, str],
        cwd: Path,
    ) -> _WindowsProcess:
        token = self._restricted_token()
        process = self.PROCESS_INFORMATION()
        job = None
        token_open = True
        try:
            job = self.kernel.CreateJobObjectW(None, None)
            if not job:
                raise QualificationFailure("restricted_launch_unavailable")
            limits = self.EXTENDED_LIMITS()
            limits.BasicLimitInformation.LimitFlags = 0x2000
            if not self.kernel.SetInformationJobObject(
                job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise QualificationFailure("restricted_launch_unavailable")
            startup = self.STARTUPINFOW()
            startup.cb = ctypes.sizeof(startup)
            command = ctypes.create_unicode_buffer(
                subprocess.list2cmdline([str(executable)])
            )
            environment_block = ctypes.create_unicode_buffer(
                "\0".join(
                    f"{key}={value}" for key, value in sorted(environment.items())
                )
                + "\0\0"
            )
            flags = 0x00000400 | 0x08000000 | 0x00000004
            started = time.perf_counter()
            created = self._create_suspended_process(
                token,
                executable,
                command,
                flags,
                environment_block,
                cwd,
                startup,
                process,
            )
            if not created:
                raise QualificationFailure("restricted_launch_unavailable")
            if not self.kernel.AssignProcessToJobObject(job, process.hProcess):
                raise QualificationFailure("restricted_launch_unavailable")
            initial = self._process_observation(
                process.hProcess, int(process.dwProcessId)
            )
            if self.kernel.ResumeThread(process.hThread) == 0xFFFFFFFF:
                raise QualificationFailure("restricted_launch_unavailable")
            self._require_closed_handles(token)
            token_open = False
            return self._finish_launched_process(process, job, started, initial)
        except Exception as error:
            primary = (
                error
                if isinstance(error, QualificationFailure)
                else QualificationFailure("restricted_launch_unavailable")
            )
            if process.hProcess:
                cleanup_succeeded = self._cleanup_created_process(process, job)
            else:
                cleanup_succeeded = self._close_handles(job)
            if token_open:
                cleanup_succeeded = self._close_handles(token) and cleanup_succeeded
            primary.record_cleanup(succeeded=cleanup_succeeded)
            raise primary from None

    def _process_observation(self, process, process_id: int) -> _ProcessObservation:
        wt = self.wintypes
        capacity = wt.DWORD(32_768)
        image = ctypes.create_unicode_buffer(capacity.value)
        created = self.FILETIME()
        exited = self.FILETIME()
        kernel = self.FILETIME()
        user = self.FILETIME()
        if not self.kernel.QueryFullProcessImageNameW(
            process, 0, image, ctypes.byref(capacity)
        ) or not self.kernel.GetProcessTimes(
            process,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise QualificationFailure("scenario_failed")
        creation_time = (int(created.dwHighDateTime) << 32) | int(
            created.dwLowDateTime
        )
        return _ProcessObservation(process_id, creation_time, image.value)

    def _job_process_ids(self, job) -> tuple[int, ...]:
        process_ids = self.PROCESS_IDS()
        returned = self.wintypes.DWORD()
        if not self.kernel.QueryInformationJobObject(
            job,
            3,
            ctypes.byref(process_ids),
            ctypes.sizeof(process_ids),
            ctypes.byref(returned),
        ):
            raise QualificationFailure("scenario_failed")
        listed = int(process_ids.NumberOfProcessIdsInList)
        assigned = int(process_ids.NumberOfAssignedProcesses)
        if listed > len(process_ids.ProcessIdList) or assigned != listed:
            raise QualificationFailure("scenario_failed")
        values = tuple(int(process_ids.ProcessIdList[index]) for index in range(listed))
        if any(value <= 0 for value in values) or len(set(values)) != len(values):
            raise QualificationFailure("scenario_failed")
        return values

    def _job_accounting(self, job) -> tuple[int, int]:
        accounting = self.BASIC_ACCOUNTING()
        returned = self.wintypes.DWORD()
        if not self.kernel.QueryInformationJobObject(
            job,
            1,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            ctypes.byref(returned),
        ):
            raise QualificationFailure("scenario_failed")
        active = int(accounting.ActiveProcesses)
        total = int(accounting.TotalProcesses)
        if active > total:
            raise QualificationFailure("scenario_failed")
        return active, total

    def job_observations(
        self, job
    ) -> tuple[tuple[_ProcessObservation, ...], int, int]:
        process_ids = self._job_process_ids(job)
        observations: list[_ProcessObservation] = []
        for process_id in process_ids:
            process = self.kernel.OpenProcess(0x1000, False, process_id)
            if not process:
                if (
                    ctypes.get_last_error() == WINDOWS_ERROR_INVALID_PARAMETER
                    and process_id not in self._job_process_ids(job)
                ):
                    continue
                raise QualificationFailure("scenario_failed")
            try:
                observations.append(self._process_observation(process, process_id))
            finally:
                _attempt_cleanup(
                    lambda process=process: self._require_closed_handles(process)
                )
        active, total = self._job_accounting(job)
        return tuple(observations), active, total

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
        drained = not terminate
        handles_closed = True
        try:
            if terminate:
                if not self.kernel.TerminateJobObject(job, 23):
                    self.kernel.TerminateProcess(process, 23)
                deadline = (
                    time.monotonic() + MAX_TERMINATION_DRAIN_MILLISECONDS / 1000
                )
                while time.monotonic() < deadline:
                    active, _total = self._job_accounting(job)
                    wait_result = self.kernel.WaitForSingleObject(process, 0)
                    if wait_result not in {WAIT_OBJECT_0, WAIT_TIMEOUT}:
                        raise QualificationFailure(
                            "scenario_failed",
                            qualification_reason="qualification_cleanup_failed",
                        )
                    if active == 0 and wait_result == WAIT_OBJECT_0:
                        drained = True
                        break
                    time.sleep(0.01)
        finally:
            for handle in (job, process):
                try:
                    if not self.kernel.CloseHandle(handle):
                        handles_closed = False
                except Exception:
                    handles_closed = False
        if not drained or not handles_closed:
            raise QualificationFailure(
                "scenario_failed",
                qualification_reason="qualification_cleanup_failed",
                qualification_cleanup="failed",
            )


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
            "integrity_level",
        }:
            raise ValueError("invalid_receipt")
        if (
            payload["schema_version"] != 1
            or type(payload["schema_version"]) is not int
            or payload["scenario"] != scenario
            or payload["stage"] not in {"startup_ready", "ready", "complete", "failed"}
            or payload["packaged"] is not True
            or payload["console_none"] is not True
            or payload["ordinary_user"] is not True
            or payload["integrity_level"] != "medium"
        ):
            raise ValueError("invalid_receipt")
        return payload
    except (OSError, ValueError, KeyError, TypeError):
        raise QualificationFailure(
            "scenario_failed",
            qualification_reason="qualification_result_mismatch",
        ) from None


def _validate_child_failure(path: Path) -> dict[str, object]:
    try:
        payload = _bounded_json(path, 4096)
        if type(payload) is not dict or set(payload) != {
            "schema_version",
            "stage",
            "reason",
        }:
            raise ValueError("invalid_failure")
        if (
            payload["schema_version"] != 1
            or type(payload["schema_version"]) is not int
            or type(payload["stage"]) is not str
            or type(payload["reason"]) is not str
            or payload["stage"] not in CHILD_FAILURE_STAGES
            or payload["reason"] not in QUALIFICATION_FAILURE_REASONS
        ):
            raise ValueError("invalid_failure")
        return payload
    except (OSError, ValueError, KeyError, TypeError):
        raise QualificationFailure(
            "scenario_failed",
            qualification_reason="qualification_result_mismatch",
        ) from None


def _prepare_work_root(parent: Path, label: str) -> Path:
    root = parent / f"{label}-{uuid.uuid4().hex}" / "próba ze spacjami"
    try:
        root.mkdir(parents=True)
    except OSError:
        raise QualificationFailure(
            "scenario_failed",
            qualification_reason="invalid_qualification_root",
        ) from None
    fixture = root / "fixture.pdf"
    try:
        shutil.copyfile(FIXTURE, fixture)
        if _sha256(fixture, maximum=128 * 1024) != FIXTURE_SHA256:
            raise QualificationFailure("fixture_invalid")
    except (OSError, QualificationFailure):
        raise QualificationFailure(
            "fixture_invalid",
            qualification_reason="qualification_fixture_mismatch",
        ) from None
    return root


def _write_control(path: Path) -> None:
    try:
        path.touch(exist_ok=False)
    except OSError:
        raise QualificationFailure(
            "scenario_failed",
            qualification_reason="qualification_filename_control_unavailable",
        ) from None


def _relative_package_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    if (
        not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or any(ord(character) < 32 or ord(character) == 127 for character in str(relative))
    ):
        raise QualificationFailure("artifact_invalid")
    value = relative.as_posix()
    if len(value) > MAX_PACKAGE_PATH_CHARS:
        raise QualificationFailure("artifact_invalid")
    return value


def _package_item(root: Path, path: Path) -> PackageEntry | None:
    metadata = path.lstat()
    if getattr(metadata, "st_file_attributes", 0) & 0x400:
        raise QualificationFailure("artifact_invalid")
    if stat.S_ISDIR(metadata.st_mode):
        return None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 0 <= metadata.st_size <= MAX_FILE_BYTES
    ):
        raise QualificationFailure("artifact_invalid")
    return PackageEntry(
        _relative_package_path(root, path), metadata.st_size, _sha256(path)
    )


def _reject_empty_package_directory(names: list[str], files: list[str]) -> None:
    if not names and not files:
        raise QualificationFailure("artifact_invalid")


def _package_inventory(root: Path) -> tuple[PackageEntry, ...]:
    entries = 0
    total_bytes = 0
    files_found: list[PackageEntry] = []
    normalized_paths: set[str] = set()
    try:
        root_metadata = root.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode) or getattr(
            root_metadata, "st_file_attributes", 0
        ) & 0x400:
            raise QualificationFailure("artifact_invalid")

        def walk_error(_error: OSError) -> None:
            raise QualificationFailure("artifact_invalid")

        for directory, names, files in os.walk(
            root, followlinks=False, onerror=walk_error
        ):
            names.sort()
            files.sort()
            _reject_empty_package_directory(names, files)
            for name in (*names, *files):
                entries += 1
                if entries > MAX_PACKAGE_ENTRIES:
                    raise QualificationFailure("artifact_invalid")
                path = Path(directory) / name
                relative = _relative_package_path(root, path)
                normalized = relative.casefold()
                if normalized in normalized_paths:
                    raise QualificationFailure("artifact_invalid")
                normalized_paths.add(normalized)
                item = _package_item(root, path)
                if item is None:
                    continue
                total_bytes += item.size_bytes
                if total_bytes > MAX_PACKAGE_COPY_BYTES:
                    raise QualificationFailure("artifact_invalid")
                files_found.append(item)
    except OSError:
        raise QualificationFailure("artifact_invalid") from None
    return tuple(sorted(files_found, key=lambda entry: entry.path))


def _validate_package_tree(root: Path) -> None:
    _package_inventory(root)


def _tree_digest(entries: tuple[PackageEntry, ...]) -> str:
    payload = [
        {"path": entry.path, "sha256": entry.sha256, "size_bytes": entry.size_bytes}
        for entry in entries
    ]
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _relocate_package(artifact: Path, private_root: Path, deadline: float) -> Path:
    source_inventory = _package_inventory(artifact)
    destination = private_root / "pakiet żółć ze spacjami"
    try:
        shutil.copytree(artifact, destination)
    except OSError:
        raise QualificationFailure("artifact_invalid") from None
    if time.monotonic() >= deadline:
        raise QualificationFailure("scenario_timeout")
    if _package_inventory(destination) != source_inventory:
        raise QualificationFailure("artifact_invalid")
    return destination


def _observe_startup_receipt(
    path: Path,
    scenario: str,
    process: _WindowsProcess,
    observed_ms: int | None,
) -> int | None:
    if observed_ms is not None or not path.exists():
        return observed_ms
    receipt = _validate_child_receipt(path, scenario)
    if receipt["stage"] != "startup_ready":
        raise QualificationFailure("scenario_failed")
    return round((time.perf_counter() - process.started) * 1000)


def _observe_qualification_receipt(
    root: Path,
    scenario: str,
    process: _WindowsProcess,
    on_ready: Callable[[_WindowsProcess], None] | None,
    ready_called: bool,
) -> tuple[dict[str, object] | None, bool]:
    receipt: dict[str, object] | None = None
    for stage in ("failed", "complete", "ready"):
        path = root / QUALIFICATION_RECEIPT_NAMES[stage]
        if path.exists():
            receipt = _validate_child_receipt(path, scenario)
            if receipt["stage"] != stage:
                raise QualificationFailure("scenario_failed")
            break
    if receipt is None:
        return None, ready_called
    if receipt["stage"] == "failed":
        failure = _validate_child_failure(root / "failure.json")
        raise QualificationFailure(
            "scenario_failed",
            qualification_reason=failure["reason"],
            qualification_child_stage=failure["stage"],
        )
    if on_ready is not None and not ready_called:
        on_ready(process)
        ready_called = True
    return receipt, ready_called


def _has_qualification_receipt(root: Path) -> bool:
    return any((root / name).exists() for name in QUALIFICATION_RECEIPT_NAMES.values())


def _wait_for_job_exit(process: _WindowsProcess, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if process.active_processes() == 0:
            return True
        time.sleep(0.01)
    return False


def _finish_process_without_receipt(
    process: _WindowsProcess,
    artifact_dir: Path,
    deadline: float,
    expected_exit: int,
) -> ScenarioResult:
    exit_code: int | None = None
    while time.monotonic() < deadline:
        process.observe()
        exit_code = process.poll()
        if exit_code is not None:
            break
        time.sleep(0.02)
    if exit_code is None:
        raise QualificationFailure("scenario_timeout")
    if exit_code != expected_exit:
        raise QualificationFailure(
            "scenario_failed",
            qualification_reason="process_exit_mismatch",
            qualification_exit_code=exit_code,
        )
    if not _wait_for_job_exit(process, deadline):
        raise QualificationFailure("scenario_timeout")
    return ScenarioResult(
        exit_code,
        round((time.perf_counter() - process.started) * 1000),
        0,
        None,
        process.metrics(),
        process.topology(artifact_dir, all_exited=True),
    )


def _wait_concurrent_barrier(
    processes: tuple[_WindowsProcess, _WindowsProcess],
    roots: tuple[Path, Path],
    scenario_deadline: float,
) -> tuple[int, int]:
    startup_ms: list[int | None] = [None, None]
    while time.monotonic() < scenario_deadline:
        for index, process in enumerate(processes):
            process.observe()
            exit_code = process.poll()
            if exit_code is not None:
                raise QualificationFailure(
                    "scenario_failed",
                    qualification_stage=f"concurrent_{index + 1}",
                    qualification_reason="process_exit_mismatch",
                    qualification_exit_code=exit_code,
                )
            startup_ms[index] = _observe_startup_receipt(
                roots[index] / "startup.json",
                "concurrent",
                process,
                startup_ms[index],
            )
        if all(value is not None for value in startup_ms) and all(
            (root / "waiting").is_file() for root in roots
        ):
            return startup_ms[0], startup_ms[1]
        time.sleep(0.02)
    raise QualificationFailure("scenario_timeout")


def _launch_concurrent_pair(
    api: _WindowsApi,
    launcher: Path,
    artifact: Path,
    roots: tuple[Path, Path],
    state_base: Path,
) -> tuple[_WindowsProcess, _WindowsProcess]:
    processes: list[_WindowsProcess] = []
    try:
        for root in roots:
            processes.append(
                api.launch(
                    launcher,
                    _sanitized_environment(
                        artifact, root, state_base, "concurrent"
                    ),
                    root,
                )
            )
    except Exception:
        _close_processes(tuple(processes), terminate=True)
        raise
    return processes[0], processes[1]


def _close_processes(
    processes: tuple[_WindowsProcess, ...], *, terminate: bool
) -> None:
    first_failure: QualificationFailure | None = None
    for process in processes:
        try:
            process.close(terminate=terminate)
        except QualificationFailure as error:
            if first_failure is None:
                first_failure = error
    if first_failure is not None:
        raise first_failure


def _finish_concurrent_processes(
    processes: tuple[_WindowsProcess, _WindowsProcess],
    roots: tuple[Path, Path],
    startup_ms: tuple[int, int],
    artifact_dir: Path,
    scenario_deadline: float,
) -> tuple[ScenarioResult, ScenarioResult]:
    exit_codes: list[int | None] = [None, None]
    while time.monotonic() < scenario_deadline and any(
        code is None for code in exit_codes
    ):
        for index, process in enumerate(processes):
            process.observe()
            if exit_codes[index] is None:
                exit_codes[index] = process.poll()
        time.sleep(0.02)
    results: list[ScenarioResult] = []
    for index, process in enumerate(processes):
        def finish_one() -> ScenarioResult:
            exit_code = exit_codes[index]
            if exit_code is None:
                raise QualificationFailure("scenario_timeout")
            if exit_code != 9:
                raise QualificationFailure(
                    "scenario_failed",
                    qualification_reason="process_exit_mismatch",
                    qualification_exit_code=exit_code,
                )
            receipt = _validate_child_receipt(
                roots[index] / QUALIFICATION_RECEIPT_NAMES["ready"], "concurrent"
            )
            if receipt["stage"] != "ready":
                raise QualificationFailure("scenario_failed")
            if not _wait_for_job_exit(process, scenario_deadline):
                raise QualificationFailure("scenario_timeout")
            return ScenarioResult(
                9,
                round((time.perf_counter() - process.started) * 1000),
                startup_ms[index],
                "ready",
                process.metrics(),
                process.topology(artifact_dir, all_exited=True),
            )

        results.append(
            _run_driver_phase(f"concurrent_{index + 1}", finish_one)
        )
    return results[0], results[1]


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
    startup_path = work_root / "startup.json"
    startup_ready_ms: int | None = None
    ready_called = False
    terminate = True
    try:
        scenario_deadline = min(deadline, time.monotonic() + MAX_SCENARIO_SECONDS)
        exit_code: int | None = None
        last_receipt: dict[str, object] | None = None
        while time.monotonic() < scenario_deadline:
            process.observe()
            startup_ready_ms = _observe_startup_receipt(
                startup_path, scenario, process, startup_ready_ms
            )
            observed_receipt, ready_called = _observe_qualification_receipt(
                work_root, scenario, process, on_ready, ready_called
            )
            if observed_receipt is not None:
                last_receipt = observed_receipt
            exit_code = process.poll()
            if exit_code is not None:
                break
            time.sleep(0.02)
        if exit_code is None:
            raise QualificationFailure("scenario_timeout")
        if startup_ready_ms is None:
            raise QualificationFailure(
                "scenario_failed",
                qualification_reason="process_exited_before_startup",
                qualification_exit_code=exit_code,
            )
        if last_receipt is None:
            raise QualificationFailure(
                "scenario_failed",
                qualification_reason="process_exited_before_result",
                qualification_exit_code=exit_code,
            )
        if exit_code != expected_exit:
            raise QualificationFailure(
                "scenario_failed",
                qualification_reason="process_exit_mismatch",
                qualification_exit_code=exit_code,
            )
        final_receipt = _validate_child_receipt(
            work_root / QUALIFICATION_RECEIPT_NAMES[expected_stage], scenario
        )
        if final_receipt["stage"] != expected_stage:
            raise QualificationFailure("scenario_failed")
        all_exited = _wait_for_job_exit(process, scenario_deadline)
        if not all_exited:
            raise QualificationFailure("scenario_timeout")
        metrics = process.metrics()
        elapsed_ms = round((time.perf_counter() - process.started) * 1000)
        terminate = False
        return ScenarioResult(
            exit_code,
            elapsed_ms,
            startup_ready_ms,
            str(final_receipt["stage"]),
            metrics,
            process.topology(artifact_dir, all_exited=all_exited),
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


def _validate_hard_exit_history(incident) -> None:
    events = [decode_event(event) for event in incident.events]
    provenance = [event for event in events if type(event) is RuntimeProvenanceEvent]
    startup = [event for event in events if type(event) is StartupDiagnosticEvent]
    if (
        not provenance
        or not startup
        or any(event.invocation_id != incident.session_id for event in events)
        or not any(
            left.startup_id == right.startup_id
            for left in provenance
            for right in startup
        )
    ):
        raise QualificationFailure("incident_invalid")
    workflows = [event for event in events if type(event) is WorkflowDiagnosticEvent]
    expected = {
        WorkflowOperation.SELECTED_IMPORT: (
            WorkflowStage.STARTED,
            WorkflowStage.PREFLIGHT_COMPLETE,
            WorkflowStage.PROCESSING,
            WorkflowStage.PERSISTENCE_COMPLETE,
            WorkflowStage.FINISHED,
        ),
        WorkflowOperation.LOCAL_EXPORT: (
            WorkflowStage.STARTED,
            WorkflowStage.OUTPUT_STAGING,
            WorkflowStage.OUTPUT_PUBLISHED,
            WorkflowStage.FINISHED,
        ),
    }
    for operation, stages in expected.items():
        rows = [event for event in workflows if event.operation is operation]
        if (
            not rows
            or tuple(event.stage for event in rows) != stages
            or len({event.operation_id for event in rows}) != 1
            or rows[-1].outcome is not WorkflowOutcome.COMPLETED
            or any(
                event.validation_status is not ValidationStatus.NOT_PERFORMED
                for event in rows
            )
        ):
            raise QualificationFailure("incident_invalid")


def _validate_hard_exit_incident(incident) -> None:
    observation = incident.observation
    if (
        observation.exit_code != 9
        or observation.launch is not LaunchState.STARTED
        or observation.handshake is not HandshakeState.ACCEPTED
        or observation.channel is ChannelState.COMPLETE
    ):
        raise QualificationFailure("incident_invalid")
    _validate_hard_exit_history(incident)


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


def _remove_generated_paths(paths: tuple[Path, ...]) -> bool:
    complete = True
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            complete = False
    return complete


def _remove_owned_development_artifacts(
    output_dir: Path, identity: tuple[int, int]
) -> bool:
    try:
        metadata = output_dir.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino) != identity
    ):
        return False
    return _remove_generated_paths(
        (output_dir / PACKAGE_ARCHIVE_NAME, output_dir / PACKAGE_MANIFEST_NAME)
    )


def _bounded_stream_sha256(source, size_bytes: int, *, destination=None) -> str:
    remaining = size_bytes
    digest = hashlib.sha256()
    while remaining:
        block = source.read(min(1024 * 1024, remaining))
        if not block:
            raise ValueError("archive_member_size_mismatch")
        remaining -= len(block)
        digest.update(block)
        if destination is not None:
            destination.write(block)
    if source.read(1):
        raise ValueError("archive_member_size_mismatch")
    return digest.hexdigest()


def _validate_archive_entries(
    bundle: zipfile.ZipFile,
    entries: tuple[PackageEntry, ...],
) -> None:
    members = bundle.infolist()
    if [member.filename for member in members] != [entry.path for entry in entries]:
        raise ValueError("archive_member_mismatch")
    for member, entry in zip(members, entries, strict=True):
        if (
            member.is_dir()
            or member.flag_bits & 0x1
            or member.file_size != entry.size_bytes
        ):
            raise ValueError("archive_member_mismatch")
        with bundle.open(member, "r") as stream:
            digest = _bounded_stream_sha256(stream, entry.size_bytes)
        if digest != entry.sha256:
            raise ValueError("archive_member_mismatch")


def _write_development_artifacts(
    source: Path,
    tested: Path,
    output_dir: Path,
) -> dict[str, object]:
    source_inventory = _package_inventory(source)
    tested_inventory = _package_inventory(tested)
    if tested_inventory != source_inventory:
        raise QualificationFailure("artifact_invalid")
    archive_stage = output_dir / f".{PACKAGE_ARCHIVE_NAME}.{uuid.uuid4().hex}.tmp"
    manifest_stage = output_dir / f".{PACKAGE_MANIFEST_NAME}.{uuid.uuid4().hex}.tmp"
    archive_path = output_dir / PACKAGE_ARCHIVE_NAME
    manifest_path = output_dir / PACKAGE_MANIFEST_NAME
    if any(
        os.path.lexists(path)
        for path in (archive_path, manifest_path, archive_stage, manifest_stage)
    ):
        raise QualificationFailure("artifact_invalid")
    try:
        with zipfile.ZipFile(
            archive_stage, "x", compression=zipfile.ZIP_STORED, allowZip64=True
        ) as archive:
            for entry in tested_inventory:
                info = zipfile.ZipInfo(entry.path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                with (tested / Path(entry.path)).open("rb") as source_stream:
                    with archive.open(info, "w", force_zip64=True) as destination:
                        copied_sha256 = _bounded_stream_sha256(
                            source_stream,
                            entry.size_bytes,
                            destination=destination,
                        )
                if copied_sha256 != entry.sha256:
                    raise ValueError("archive_member_mismatch")
        if archive_stage.stat().st_size > MAX_PACKAGE_ARCHIVE_BYTES:
            raise QualificationFailure("artifact_invalid")
        with zipfile.ZipFile(archive_stage) as archive:
            _validate_archive_entries(archive, tested_inventory)
        archive_sha256 = _sha256(archive_stage, maximum=MAX_PACKAGE_ARCHIVE_BYTES)
        manifest = {
            "schema_version": 1,
            "tree_sha256": _tree_digest(tested_inventory),
            "archive": {
                "name": PACKAGE_ARCHIVE_NAME,
                "sha256": archive_sha256,
                "size_bytes": archive_stage.stat().st_size,
            },
            "entries": [
                {
                    "path": entry.path,
                    "sha256": entry.sha256,
                    "size_bytes": entry.size_bytes,
                }
                for entry in tested_inventory
            ],
        }
        encoded = json.dumps(
            manifest,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
        if not encoded or len(encoded) > MAX_PACKAGE_MANIFEST_BYTES:
            raise QualificationFailure("artifact_invalid")
        with manifest_stage.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        archive_stage.replace(archive_path)
        manifest_stage.replace(manifest_path)
        return {
            "tested_tree_sha256": manifest["tree_sha256"],
            "package_manifest_sha256": _sha256(
                manifest_path, maximum=MAX_PACKAGE_MANIFEST_BYTES
            ),
            "archive_name": PACKAGE_ARCHIVE_NAME,
            "archive_sha256": archive_sha256,
            "archive_size_bytes": archive_path.stat().st_size,
        }
    except Exception as error:
        primary = (
            error
            if isinstance(error, QualificationFailure)
            else QualificationFailure("artifact_invalid")
        )
        primary.record_cleanup(
            succeeded=_remove_generated_paths((archive_path, manifest_path))
        )
        raise primary from None
    finally:
        primary = sys.exc_info()[1]
        stages_removed = _remove_generated_paths((archive_stage, manifest_stage))
        if isinstance(primary, QualificationFailure):
            primary.record_cleanup(succeeded=stages_removed)
        elif primary is None and not stages_removed:
            raise QualificationFailure(
                "artifact_invalid", qualification_cleanup="failed"
            ) from None


def _manifest_entries(payload: object) -> tuple[PackageEntry, ...]:
    if type(payload) is not list or not 0 < len(payload) <= MAX_PACKAGE_ENTRIES:
        raise QualificationFailure("output_failed")
    entries: list[PackageEntry] = []
    normalized: set[str] = set()
    total_bytes = 0
    for value in payload:
        if type(value) is not dict or set(value) != {"path", "sha256", "size_bytes"}:
            raise QualificationFailure("output_failed")
        path = value["path"]
        parsed = PurePosixPath(path) if type(path) is str else PurePosixPath("/")
        if (
            type(path) is not str
            or not 0 < len(path) <= MAX_PACKAGE_PATH_CHARS
            or parsed.is_absolute()
            or any(part in {"", ".", ".."} for part in parsed.parts)
            or "\\" in path
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
            or path.casefold() in normalized
            or not _valid_digest(value["sha256"])
            or not _bounded_counter(value["size_bytes"])
            or value["size_bytes"] > MAX_FILE_BYTES
        ):
            raise QualificationFailure("output_failed")
        normalized.add(path.casefold())
        total_bytes += value["size_bytes"]
        if total_bytes > MAX_PACKAGE_COPY_BYTES:
            raise QualificationFailure("output_failed")
        entries.append(PackageEntry(path, value["size_bytes"], value["sha256"]))
    result = tuple(entries)
    if tuple(sorted(result, key=lambda entry: entry.path)) != result:
        raise QualificationFailure("output_failed")
    return result


def _validate_development_artifacts(output_dir: Path, package: dict[str, object]) -> None:
    manifest_path = output_dir / PACKAGE_MANIFEST_NAME
    archive_path = output_dir / PACKAGE_ARCHIVE_NAME
    try:
        payload = _bounded_json(manifest_path, MAX_PACKAGE_MANIFEST_BYTES)
        if type(payload) is not dict or set(payload) != {
            "schema_version",
            "tree_sha256",
            "archive",
            "entries",
        }:
            raise QualificationFailure("output_failed")
        archive = payload["archive"]
        if (
            payload["schema_version"] != 1
            or type(payload["schema_version"]) is not int
            or type(archive) is not dict
            or set(archive) != {"name", "sha256", "size_bytes"}
        ):
            raise QualificationFailure("output_failed")
        entries = _manifest_entries(payload["entries"])
        archive_hash = _sha256(archive_path, maximum=MAX_PACKAGE_ARCHIVE_BYTES)
        facts = {
            "tested_tree_sha256": payload["tree_sha256"],
            "package_manifest_sha256": _sha256(
                manifest_path, maximum=MAX_PACKAGE_MANIFEST_BYTES
            ),
            "archive_name": archive["name"],
            "archive_sha256": archive_hash,
            "archive_size_bytes": archive_path.stat().st_size,
        }
        if (
            payload["tree_sha256"] != _tree_digest(entries)
            or archive["name"] != PACKAGE_ARCHIVE_NAME
            or archive["sha256"] != archive_hash
            or archive["size_bytes"] != archive_path.stat().st_size
            or any(package[key] != value for key, value in facts.items())
        ):
            raise QualificationFailure("output_failed")
        with zipfile.ZipFile(archive_path) as bundle:
            _validate_archive_entries(bundle, entries)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        raise QualificationFailure("output_failed") from None


def _write_receipt(
    output_dir: Path,
    payload: dict[str, object],
    *,
    expected_output_identity: tuple[int, int] | None = None,
) -> Path:
    if expected_output_identity is not None:
        try:
            metadata = output_dir.lstat()
        except OSError:
            raise QualificationFailure("output_failed") from None
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != expected_output_identity
        ):
            raise QualificationFailure("output_failed")
    expected_existing = (
        {output_dir / PACKAGE_MANIFEST_NAME, output_dir / PACKAGE_ARCHIVE_NAME}
        if payload.get("status") == "passed"
        else set()
    )
    if set(output_dir.iterdir()) != expected_existing:
        raise QualificationFailure("output_failed")
    _validate_output_payload(payload)
    if payload["status"] == "passed":
        _validate_development_artifacts(output_dir, payload["package"])
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
        raise QualificationFailure(
            "output_failed",
            qualification_cleanup=(
                "complete"
                if _remove_generated_paths((stage,))
                else "failed"
            ),
        ) from None


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
        "tested_tree_sha256",
        "package_manifest_sha256",
        "archive_name",
        "archive_sha256",
        "archive_size_bytes",
    }
    if type(package) is not dict or set(package) != expected:
        raise QualificationFailure("output_failed")
    if not _valid_digest(package["git_sha"], (40, 64)):
        raise QualificationFailure("output_failed")
    if not all(
        _valid_digest(package[key])
        for key in (
            "launcher_sha256",
            "application_sha256",
            "manifest_sha256",
            "tested_tree_sha256",
            "package_manifest_sha256",
            "archive_sha256",
        )
    ):
        raise QualificationFailure("output_failed")
    if (
        package["archive_name"] != PACKAGE_ARCHIVE_NAME
        or not _bounded_counter(package["archive_size_bytes"])
        or package["archive_size_bytes"] > MAX_PACKAGE_ARCHIVE_BYTES
    ):
        raise QualificationFailure("output_failed")
    notices = package["notice_hashes"]
    if type(notices) is not dict or set(notices) != set(NOTICE_FILES):
        raise QualificationFailure("output_failed")
    if not all(_valid_digest(notices[name]) for name in NOTICE_FILES):
        raise QualificationFailure("output_failed")


def _validate_success_metrics(metrics: object) -> None:
    expected = {
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
    if type(metrics) is not dict or set(metrics) != expected:
        raise QualificationFailure("output_failed")
    list_keys = {
        "direct_startup_ready_ms",
        "supervised_startup_ready_ms",
        "direct_peak_process_tree_memory_bytes",
        "supervised_peak_process_tree_memory_bytes",
    }
    scalar_keys = expected - list_keys - {"flood_loss"}
    if any(
        type(metrics[key]) is not list
        or len(metrics[key]) != 2
        or not all(_bounded_counter(value) for value in metrics[key])
        for key in list_keys
    ) or not all(_bounded_counter(metrics[key]) for key in scalar_keys):
        raise QualificationFailure("output_failed")
    loss = metrics["flood_loss"]
    expected_loss = {"source_dropped", *RING_LOSS_FIELDS}
    if type(loss) is not dict or set(loss) != expected_loss:
        raise QualificationFailure("output_failed")
    if type(loss["counters_saturated"]) is not bool or not all(
        type(loss[key]) is int and 0 <= loss[key] <= 2**32 - 1
        for key in expected_loss - {"counters_saturated"}
    ):
        raise QualificationFailure("output_failed")


def _environment_receipt() -> dict[str, str]:
    try:
        version = sys.getwindowsversion()
        windows_version = f"{version.major}.{version.minor}.{version.build}"
        machine = platform.machine().lower()
        architecture = {
            "amd64": "amd64",
            "x86_64": "amd64",
            "arm64": "arm64",
            "aarch64": "arm64",
        }[machine]
        return {
            "windows_version": windows_version,
            "architecture": architecture,
            "python_version": platform.python_version(),
            "pyinstaller_version": importlib.metadata.version("pyinstaller"),
        }
    except (AttributeError, KeyError, importlib.metadata.PackageNotFoundError):
        raise QualificationFailure("artifact_invalid") from None


def _validate_environment_receipt(environment: object) -> None:
    expected = {
        "windows_version",
        "architecture",
        "python_version",
        "pyinstaller_version",
    }
    if type(environment) is not dict or set(environment) != expected:
        raise QualificationFailure("output_failed")
    patterns = {
        "windows_version": r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,10}",
        "python_version": r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}",
        "pyinstaller_version": r"[0-9][0-9A-Za-z.+-]{0,31}",
    }
    if environment["architecture"] not in {"amd64", "arm64"} or any(
        type(environment[key]) is not str
        or re.fullmatch(pattern, environment[key]) is None
        for key, pattern in patterns.items()
    ):
        raise QualificationFailure("output_failed")


def _operational_cost(metrics: dict[str, object]) -> dict[str, object]:
    direct_startup = metrics["direct_startup_ready_ms"]
    supervised_startup = metrics["supervised_startup_ready_ms"]
    direct_memory = metrics["direct_peak_process_tree_memory_bytes"]
    supervised_memory = metrics["supervised_peak_process_tree_memory_bytes"]
    observed = {
        "max_startup_ready_ms": max((*direct_startup, *supervised_startup)),
        "max_supervisor_startup_overhead_ms": max(
            max(0, supervised - direct)
            for direct, supervised in zip(direct_startup, supervised_startup, strict=True)
        ),
        "max_supervisor_memory_overhead_bytes": max(
            max(0, supervised - direct)
            for direct, supervised in zip(direct_memory, supervised_memory, strict=True)
        ),
        "direct_idle_write_bytes": metrics["direct_idle_write_bytes"],
        "supervised_idle_write_bytes": metrics["supervised_idle_write_bytes"],
        "max_incident_assembly_to_verification_ms": max(
            metrics["hard_incident_assembly_to_verification_ms"],
            metrics["handled_incident_assembly_to_verification_ms"],
        ),
        "flood_elapsed_ms": metrics["flood_elapsed_ms"],
    }
    thresholds = {
        "max_startup_ready_ms": MAX_STARTUP_READY_MILLISECONDS,
        "max_supervisor_startup_overhead_ms": (
            MAX_SUPERVISOR_STARTUP_OVERHEAD_MILLISECONDS
        ),
        "max_supervisor_memory_overhead_bytes": MAX_SUPERVISOR_MEMORY_OVERHEAD_BYTES,
        "max_idle_write_bytes": MAX_IDLE_WRITE_BYTES,
        "max_incident_assembly_to_verification_ms": (
            MAX_INCIDENT_ASSEMBLY_TO_VERIFICATION_MILLISECONDS
        ),
        "max_flood_elapsed_ms": MAX_FLOOD_ELAPSED_MILLISECONDS,
        "idle_sample_ms": IDLE_SAMPLE_MILLISECONDS,
    }
    within = (
        observed["max_startup_ready_ms"] <= thresholds["max_startup_ready_ms"]
        and observed["max_supervisor_startup_overhead_ms"]
        <= thresholds["max_supervisor_startup_overhead_ms"]
        and observed["max_supervisor_memory_overhead_bytes"]
        <= thresholds["max_supervisor_memory_overhead_bytes"]
        and observed["direct_idle_write_bytes"] <= thresholds["max_idle_write_bytes"]
        and observed["supervised_idle_write_bytes"]
        <= thresholds["max_idle_write_bytes"]
        and observed["max_incident_assembly_to_verification_ms"]
        <= thresholds["max_incident_assembly_to_verification_ms"]
        and observed["flood_elapsed_ms"] <= thresholds["max_flood_elapsed_ms"]
    )
    return {
        "status": "within_budget" if within else "unresolved",
        "thresholds": thresholds,
        "observed": observed,
    }


def _validate_operational_cost(cost: object) -> None:
    if type(cost) is not dict or set(cost) != {"status", "thresholds", "observed"}:
        raise QualificationFailure("output_failed")
    expected_thresholds = {
        "max_startup_ready_ms": MAX_STARTUP_READY_MILLISECONDS,
        "max_supervisor_startup_overhead_ms": (
            MAX_SUPERVISOR_STARTUP_OVERHEAD_MILLISECONDS
        ),
        "max_supervisor_memory_overhead_bytes": MAX_SUPERVISOR_MEMORY_OVERHEAD_BYTES,
        "max_idle_write_bytes": MAX_IDLE_WRITE_BYTES,
        "max_incident_assembly_to_verification_ms": (
            MAX_INCIDENT_ASSEMBLY_TO_VERIFICATION_MILLISECONDS
        ),
        "max_flood_elapsed_ms": MAX_FLOOD_ELAPSED_MILLISECONDS,
        "idle_sample_ms": IDLE_SAMPLE_MILLISECONDS,
    }
    observed_keys = {
        "max_startup_ready_ms",
        "max_supervisor_startup_overhead_ms",
        "max_supervisor_memory_overhead_bytes",
        "direct_idle_write_bytes",
        "supervised_idle_write_bytes",
        "max_incident_assembly_to_verification_ms",
        "flood_elapsed_ms",
    }
    if cost["thresholds"] != expected_thresholds:
        raise QualificationFailure("output_failed")
    observed = cost["observed"]
    if (
        type(observed) is not dict
        or set(observed) != observed_keys
        or not all(_bounded_counter(observed[key]) for key in observed_keys)
        or cost["status"] not in {"within_budget", "unresolved"}
    ):
        raise QualificationFailure("output_failed")


def _topology_record(topology: ProcessTopology) -> dict[str, object]:
    return {
        "launcher_processes_observed": topology.launcher_processes_observed,
        "application_processes_observed": topology.application_processes_observed,
        "unexpected_processes_observed": topology.unexpected_processes_observed,
        "assigned_processes": topology.assigned_processes,
        "max_active_processes": topology.max_active_processes,
        "creation_order": list(topology.creation_order),
        "all_processes_exited": topology.all_processes_exited,
    }


def _validate_topology_record(value: object, *, supervised: bool) -> None:
    expected = {
        "launcher_processes_observed",
        "application_processes_observed",
        "unexpected_processes_observed",
        "assigned_processes",
        "max_active_processes",
        "creation_order",
        "all_processes_exited",
    }
    if type(value) is not dict or set(value) != expected:
        raise QualificationFailure("output_failed")
    expected_order = (
        ["launcher_bootloader", "launcher_supervisor", "application"]
        if supervised
        else ["application"]
    )
    expected_launchers = 2 if supervised else 0
    if (
        value["launcher_processes_observed"] != expected_launchers
        or value["application_processes_observed"] != 1
        or value["unexpected_processes_observed"] != 0
        or value["assigned_processes"] != (3 if supervised else 1)
        or value["creation_order"] != expected_order
        or value["all_processes_exited"] is not True
        or type(value["max_active_processes"]) is not int
        or not 1 <= value["max_active_processes"] <= 3
    ):
        raise QualificationFailure("output_failed")


def _validate_topology(topology: object, package: dict[str, object]) -> None:
    if type(topology) is not dict or set(topology) != {
        "launcher_image_sha256",
        "application_image_sha256",
        "direct",
        "supervised",
    }:
        raise QualificationFailure("output_failed")
    if (
        topology["launcher_image_sha256"] != package["launcher_sha256"]
        or topology["application_image_sha256"] != package["application_sha256"]
        or type(topology["direct"]) is not list
        or len(topology["direct"]) != 2
        or type(topology["supervised"]) is not list
        or len(topology["supervised"]) != 2
    ):
        raise QualificationFailure("output_failed")
    for record in topology["direct"]:
        _validate_topology_record(record, supervised=False)
    for record in topology["supervised"]:
        _validate_topology_record(record, supervised=True)


def _valid_failure_detail(detail: object) -> bool:
    detail_keys = set(detail) if type(detail) is dict else set()
    return bool(
        type(detail) is dict
        and {"stage", "reason"} <= detail_keys
        and detail_keys <= {"stage", "reason", "child_stage", "exit_code"}
        and type(detail["stage"]) is str
        and type(detail["reason"]) is str
        and detail["stage"] in QUALIFICATION_FAILURE_STAGES
        and detail["reason"] in QUALIFICATION_FAILURE_REASONS
        and (
            "child_stage" not in detail
            or type(detail["child_stage"]) is str
            and detail["child_stage"] in CHILD_FAILURE_STAGES
        )
        and (
            "exit_code" not in detail
            or type(detail["exit_code"]) is int
            and -(2**31) <= detail["exit_code"] <= 2**32 - 1
        )
    )


def _validate_failed_output_payload(
    payload: dict[str, object], expected: set[str]
) -> None:
    if (
        set(payload) != expected | {"qualification_cleanup"}
        or payload["failure_id"] not in FAILURE_IDS
        or not _valid_failure_detail(payload["qualification_failure"])
        or type(payload["qualification_cleanup"]) is not str
        or payload["qualification_cleanup"] not in QUALIFICATION_CLEANUP_STATUSES
        or payload["package"] is not None
        or payload["environment"] is not None
        or payload["topology"] is not None
        or payload["checks"] != []
        or payload["metrics"] is not None
        or payload["operational_cost"] is not None
    ):
        raise QualificationFailure("output_failed")


def _validate_output_payload(payload: object) -> None:
    expected = {
        "schema_version",
        "status",
        "failure_id",
        "qualification_failure",
        "package",
        "environment",
        "topology",
        "checks",
        "metrics",
        "operational_cost",
    }
    if (
        type(payload) is not dict
        or not {"schema_version", "status"} <= set(payload)
    ):
        raise QualificationFailure("output_failed")
    if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
        raise QualificationFailure("output_failed")
    if payload["status"] == "failed":
        _validate_failed_output_payload(payload, expected)
        return
    if set(payload) != expected:
        raise QualificationFailure("output_failed")
    if payload["status"] != "passed" or payload["failure_id"] is not None:
        raise QualificationFailure("output_failed")
    if payload["qualification_failure"] is not None:
        raise QualificationFailure("output_failed")
    checks = payload["checks"]
    operational = payload["operational_cost"]
    _validate_operational_cost(operational)
    expected_checks = [
        {"id": check_id, "status": "passed"} for check_id in CHECK_IDS
    ] + [{"id": OPERATIONAL_CHECK_ID, "status": operational.get("status")}]
    if checks != expected_checks:
        raise QualificationFailure("output_failed")
    _validate_package_receipt(payload["package"])
    _validate_environment_receipt(payload["environment"])
    _validate_topology(payload["topology"], payload["package"])
    _validate_success_metrics(payload["metrics"])
    if operational != _operational_cost(payload["metrics"]):
        raise QualificationFailure("output_failed")


def _success_payload(
    package: dict[str, object],
    environment: dict[str, str],
    results: dict[str, ScenarioResult],
    *,
    direct_idle_write_bytes: int,
    supervised_idle_write_bytes: int,
    hard_ready_to_report_ms: int,
    handled_ready_to_report_ms: int,
    hard_assembly_to_verification_ms: int,
    handled_assembly_to_verification_ms: int,
    flood_loss: dict[str, object],
) -> dict[str, object]:
    metrics = {
        "direct_startup_ready_ms": [
            results[name].startup_ready_ms
            for name in ("direct_normal_1", "direct_normal_2")
        ],
        "supervised_startup_ready_ms": [
            results[name].startup_ready_ms
            for name in ("supervised_normal_1", "supervised_normal_2")
        ],
        "direct_peak_process_tree_memory_bytes": [
            results[name].metrics.peak_job_memory_bytes
            for name in ("direct_normal_1", "direct_normal_2")
        ],
        "supervised_peak_process_tree_memory_bytes": [
            results[name].metrics.peak_job_memory_bytes
            for name in ("supervised_normal_1", "supervised_normal_2")
        ],
        "direct_idle_write_bytes": direct_idle_write_bytes,
        "supervised_idle_write_bytes": supervised_idle_write_bytes,
        "hard_exit_ready_receipt_to_report_verification_ms": hard_ready_to_report_ms,
        "handled_ready_receipt_to_report_verification_ms": handled_ready_to_report_ms,
        "hard_incident_assembly_to_verification_ms": hard_assembly_to_verification_ms,
        "handled_incident_assembly_to_verification_ms": (
            handled_assembly_to_verification_ms
        ),
        "flood_elapsed_ms": results["flood"].elapsed_ms,
        "flood_loss": flood_loss,
    }
    operational_cost = _operational_cost(metrics)
    topology = {
        "launcher_image_sha256": package["launcher_sha256"],
        "application_image_sha256": package["application_sha256"],
        "direct": [
            _topology_record(results[name].topology)
            for name in ("direct_normal_1", "direct_normal_2")
        ],
        "supervised": [
            _topology_record(results[name].topology)
            for name in ("supervised_normal_1", "supervised_normal_2")
        ],
    }
    return {
        "schema_version": 1,
        "status": "passed",
        "failure_id": None,
        "qualification_failure": None,
        "package": package,
        "environment": environment,
        "topology": topology,
        "checks": [
            {"id": check_id, "status": "passed"} for check_id in CHECK_IDS
        ]
        + [{"id": OPERATIONAL_CHECK_ID, "status": operational_cost["status"]}],
        "metrics": metrics,
        "operational_cost": operational_cost,
    }


class _QualificationRunner:
    def __init__(self, artifact: Path, private_root: Path, deadline: float) -> None:
        self.artifact = artifact
        self.private_root = private_root
        self.deadline = deadline
        self.api = _WindowsApi()
        self.state_base = private_root / "stan lokalny"
        try:
            (self.state_base / "Roaming").mkdir(parents=True)
        except OSError:
            raise QualificationFailure(
                "scenario_failed",
                qualification_reason="invalid_qualification_root",
            ) from None
        self.store = IncidentStore(self.state_base / "Metroliza" / "diagnostics")
        self.launcher = artifact / "metroliza.exe"
        self.application = artifact / "metroliza_application.exe"
        self.results: dict[str, ScenarioResult] = {}
        self.direct_idle_write_bytes = 0
        self.supervised_idle_write_bytes = 0
        self.hard_ready_to_report_ms = 0
        self.handled_ready_to_report_ms = 0
        self.hard_assembly_to_verification_ms = 0
        self.handled_assembly_to_verification_ms = 0
        self.flood_loss: dict[str, object] = {
            "source_dropped": 0,
            **{field: False if field == "counters_saturated" else 0 for field in RING_LOSS_FIELDS},
        }

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
        before = {record.report_id for record in _reports(self.store)}
        for index in range(1, 3):
            key = f"direct_normal_{index}"
            _run_driver_phase(
                key,
                lambda key=key: self._scenario(
                    key, "normal", executable=self.application
                ),
            )
        for index in range(1, 3):
            key = f"supervised_normal_{index}"
            _run_driver_phase(
                key, lambda key=key: self._scenario(key, "normal")
            )
        if {record.report_id for record in _reports(self.store)} != before:
            raise QualificationFailure("incident_invalid")

    def run_concurrent_instances(self) -> None:
        before = {record.report_id for record in _reports(self.store)}
        roots = (self._root("concurrent-one"), self._root("concurrent-two"))
        processes = _launch_concurrent_pair(
            self.api, self.launcher, self.artifact, roots, self.state_base
        )
        completed = False
        try:
            scenario_deadline = min(
                self.deadline, time.monotonic() + MAX_SCENARIO_SECONDS
            )
            startup_ms = _wait_concurrent_barrier(
                processes, roots, scenario_deadline
            )
            for root in roots:
                _write_control(root / "start")
            results = _finish_concurrent_processes(
                processes, roots, startup_ms, self.artifact, scenario_deadline
            )
            self.results["concurrent_1"], self.results["concurrent_2"] = results
            completed = True
        finally:
            _close_processes(processes, terminate=not completed)
        new_records = [
            record for record in _reports(self.store) if record.report_id not in before
        ]
        if len(new_records) != 2:
            raise QualificationFailure("incident_invalid")
        incidents = []
        for record in new_records:
            loaded = self.store.load(record.report_id)
            if loaded.status is not StoreStatus.AVAILABLE or loaded.incident is None:
                raise QualificationFailure("incident_invalid")
            incidents.append(loaded.incident)
        if len({incident.session_id for incident in incidents}) != 2:
            raise QualificationFailure("incident_invalid")
        for incident in incidents:
            _validate_hard_exit_incident(incident)

    def run_ui_smoke(self) -> None:
        before = {record.report_id for record in _reports(self.store)}
        root = self._root("interactive-ui-smoke")
        environment = _sanitized_environment(
            self.artifact, root, self.state_base, "normal"
        )
        for key in (
            "METROLIZA_STARTUP_SMOKE",
            "METROLIZA_DIAGNOSTIC_QUALIFICATION",
            "METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT",
        ):
            environment.pop(key)
        environment["METROLIZA_STARTUP_UI_SMOKE"] = "1"
        process = self.api.launch(self.launcher, environment, root)
        terminate = True
        try:
            result = _finish_process_without_receipt(
                process,
                self.artifact,
                min(self.deadline, time.monotonic() + MAX_SCENARIO_SECONDS),
                0,
            )
            _validate_topology_record(_topology_record(result.topology), supervised=True)
            self.results["ui_smoke"] = result
            terminate = False
        finally:
            process.close(terminate=terminate)
        if (
            {record.report_id for record in _reports(self.store)} != before
            or _has_qualification_receipt(root)
            or (root / "startup.json").exists()
        ):
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
        _validate_hard_exit_incident(incident)

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
            _write_control(root / "finish")

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

    def _idle_sample(self, key: str, executable: Path) -> int:
        root = self._root(key.replace("_", "-"))
        observed = {"write_bytes": 0}

        def finish(process: _WindowsProcess) -> None:
            before = process.metrics().write_bytes
            hold_until = min(
                self.deadline,
                time.monotonic() + IDLE_SAMPLE_MILLISECONDS / 1000,
            )
            while time.monotonic() < hold_until:
                exit_code = process.poll()
                if exit_code is not None:
                    raise QualificationFailure(
                        "scenario_failed",
                        qualification_reason="process_exit_mismatch",
                        qualification_exit_code=exit_code,
                    )
                time.sleep(0.05)
            observed["write_bytes"] = max(
                0, process.metrics().write_bytes - before
            )
            _write_control(root / "finish")

        self.results[key] = _run_scenario(
            self.api,
            executable,
            self.artifact,
            root,
            self.state_base,
            "idle",
            self.deadline,
            expected_exit=0,
            expected_stage="complete",
            on_ready=finish,
        )
        return observed["write_bytes"]

    def run_idle(self) -> None:
        self.direct_idle_write_bytes = _run_driver_phase(
            "direct_idle",
            lambda: self._idle_sample("direct_idle", self.application),
        )
        self.supervised_idle_write_bytes = _run_driver_phase(
            "supervised_idle",
            lambda: self._idle_sample("supervised_idle", self.launcher),
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
        self.flood_loss = {
            "source_dropped": incident.observation.source_dropped,
            **{field: getattr(loss, field) for field in RING_LOSS_FIELDS},
        }

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
            if exit_code is None:
                raise QualificationFailure("scenario_timeout")
            if exit_code != 1:
                raise QualificationFailure(
                    "scenario_failed",
                    qualification_reason="process_exit_mismatch",
                    qualification_exit_code=exit_code,
                )
            if _has_qualification_receipt(root):
                raise QualificationFailure("scenario_failed")
            all_exited = _wait_for_job_exit(process, self.deadline)
            if not all_exited:
                raise QualificationFailure("scenario_timeout")
            terminate = False
            self.results["missing_components"] = ScenarioResult(
                1,
                round((time.perf_counter() - process.started) * 1000),
                0,
                None,
                process.metrics(),
                process.topology(self.artifact, all_exited=all_exited),
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
        try:
            resource.replace(hidden)
        except OSError:
            raise QualificationFailure(
                "scenario_failed",
                qualification_reason="qualification_filename_control_unavailable",
            ) from None
        try:
            process = self.api.launch(self.launcher, environment, root)
            terminate = True
            try:
                exit_code = self._wait_missing_exit(process)
                if exit_code is None:
                    raise QualificationFailure("scenario_timeout")
                if exit_code == 0:
                    raise QualificationFailure(
                        "scenario_failed",
                        qualification_reason="process_exit_mismatch",
                        qualification_exit_code=exit_code,
                    )
                if _has_qualification_receipt(root):
                    raise QualificationFailure("scenario_failed")
                all_exited = _wait_for_job_exit(process, self.deadline)
                if not all_exited:
                    raise QualificationFailure("scenario_timeout")
                terminate = False
                self.results["missing_qt_resource"] = ScenarioResult(
                    exit_code,
                    round((time.perf_counter() - process.started) * 1000),
                    0,
                    None,
                    process.metrics(),
                    process.topology(self.artifact, all_exited=all_exited),
                )
            finally:
                process.close(terminate=terminate)
        finally:
            _attempt_cleanup(lambda: hidden.replace(resource))
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
            process.observe()
            exit_code = process.poll()
            if exit_code is not None:
                return exit_code
            time.sleep(0.02)
        raise QualificationFailure("scenario_timeout")

    def run(
        self,
        package: dict[str, object],
        source_artifact: Path,
        output_dir: Path,
    ) -> dict[str, object]:
        output_metadata = output_dir.lstat()
        output_identity = (output_metadata.st_dev, output_metadata.st_ino)
        phases = (
            ("startups", self.run_startups),
            ("concurrent", self.run_concurrent_instances),
            ("ui_smoke", self.run_ui_smoke),
            ("hard_exit", self.run_hard_exit),
            ("handled_failure", self.run_handled_failure),
            ("preview", self.run_preview),
            ("idle", self.run_idle),
            ("flood", self.run_flood),
            ("unavailable_store", self.run_unavailable_store),
            ("missing_components", self.run_missing_components),
            ("missing_qt_resource", self.run_missing_qt_resource),
        )
        for stage, action in phases:
            _run_driver_phase(stage, action)
        artifacts_created = False
        try:
            artifacts = _run_driver_phase(
                "artifacts",
                lambda: _write_development_artifacts(
                    source_artifact, self.artifact, output_dir
                ),
            )
            artifacts_created = True
            qualified_package = {**package, **artifacts}

            def success_payload() -> dict[str, object]:
                return _success_payload(
                    qualified_package,
                    _environment_receipt(),
                    self.results,
                    direct_idle_write_bytes=self.direct_idle_write_bytes,
                    supervised_idle_write_bytes=self.supervised_idle_write_bytes,
                    hard_ready_to_report_ms=self.hard_ready_to_report_ms,
                    handled_ready_to_report_ms=self.handled_ready_to_report_ms,
                    hard_assembly_to_verification_ms=(
                        self.hard_assembly_to_verification_ms
                    ),
                    handled_assembly_to_verification_ms=(
                        self.handled_assembly_to_verification_ms
                    ),
                    flood_loss=self.flood_loss,
                )

            return _run_driver_phase("receipt", success_payload)
        except Exception as error:
            if artifacts_created:
                cleanup_succeeded = _remove_owned_development_artifacts(
                    output_dir, output_identity
                )
                if isinstance(error, QualificationFailure):
                    error.record_cleanup(succeeded=cleanup_succeeded)
                    raise
                raise QualificationFailure(
                    "scenario_failed",
                    qualification_reason="unexpected",
                    qualification_cleanup=(
                        "complete" if cleanup_succeeded else "failed"
                    ),
                ) from None
            raise


def _qualification_payload(
    artifact: Path,
    output_dir: Path,
    deadline: float,
) -> dict[str, object]:
    package = _run_driver_phase("package", lambda: _validate_package(artifact))

    def validate_fixture() -> None:
        if _sha256(FIXTURE, maximum=128 * 1024) != FIXTURE_SHA256:
            raise QualificationFailure("fixture_invalid")

    _run_driver_phase("package", validate_fixture)
    if time.monotonic() >= deadline:
        raise QualificationFailure("scenario_timeout")

    def qualify_private(private_root: Path) -> dict[str, object]:
        relocated = _run_driver_phase(
            "relocation",
            lambda: _relocate_package(artifact, private_root, deadline),
        )
        relocated_package = _run_driver_phase(
            "relocation", lambda: _validate_package(relocated)
        )
        if relocated_package != package:
            raise QualificationFailure(
                "artifact_invalid",
                qualification_stage="relocation",
                qualification_reason="unexpected",
            )
        runner = _run_driver_phase(
            "runner", lambda: _QualificationRunner(relocated, private_root, deadline)
        )
        return runner.run(package, artifact, output_dir)

    return _run_in_private_directory(qualify_private)


def _run_in_private_directory(action: Callable[[Path], _T]) -> _T:
    try:
        temporary = tempfile.TemporaryDirectory(
            prefix="Metroliza kwalifikacja żółć "
        )
    except Exception:
        raise QualificationFailure(
            "scenario_failed",
            qualification_stage="runner",
            qualification_reason="invalid_qualification_root",
        ) from None
    try:
        result = action(Path(temporary.name))
    except BaseException as error:
        cleanup_succeeded = True
        try:
            temporary.cleanup()
        except Exception:
            cleanup_succeeded = False
        if isinstance(error, QualificationFailure):
            error.record_cleanup(succeeded=cleanup_succeeded)
        elif isinstance(error, Exception):
            raise QualificationFailure(
                "scenario_failed",
                qualification_stage="runner",
                qualification_reason="unexpected",
                qualification_cleanup=(
                    "complete" if cleanup_succeeded else "failed"
                ),
            ) from None
        raise
    try:
        temporary.cleanup()
    except Exception:
        raise QualificationFailure(
            "scenario_failed",
            qualification_stage="runner",
            qualification_reason="qualification_cleanup_failed",
            qualification_cleanup="failed",
        ) from None
    return result


def _prepare_qualification_paths(
    artifact_dir: Path, output_dir: Path, timeout_seconds: int
) -> tuple[Path, tuple[int, int]]:
    if not (
        type(timeout_seconds) is int
        and 60 <= timeout_seconds <= MAX_TOTAL_SECONDS
        and artifact_dir.is_absolute()
        and output_dir.is_absolute()
    ):
        raise QualificationFailure(
            "invalid_arguments",
            qualification_stage="runner",
            qualification_reason="invalid_qualification_arguments",
        )
    if artifact_dir.is_symlink():
        raise QualificationFailure(
            "artifact_invalid",
            qualification_stage="package",
            qualification_reason="unexpected",
        )
    try:
        artifact = artifact_dir.resolve(strict=True)
    except OSError:
        raise QualificationFailure(
            "artifact_invalid",
            qualification_stage="package",
            qualification_reason="unexpected",
        ) from None
    if not artifact.is_dir():
        raise QualificationFailure(
            "artifact_invalid",
            qualification_stage="package",
            qualification_reason="unexpected",
        )
    try:
        output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        output_metadata = output_dir.lstat()
    except FileExistsError:
        raise QualificationFailure(
            "output_failed",
            qualification_stage="receipt",
            qualification_reason="qualification_output_exists",
        ) from None
    except OSError:
        raise QualificationFailure(
            "output_failed",
            qualification_stage="receipt",
            qualification_reason="qualification_output_unavailable",
        ) from None
    return artifact, (output_metadata.st_dev, output_metadata.st_ino)


def qualify_windows_diagnostics(
    artifact_dir: Path,
    output_dir: Path,
    *,
    timeout_seconds: int = MAX_TOTAL_SECONDS,
) -> QualificationResult:
    if os.name != "nt":
        return QualificationResult(
            "failed",
            "unsupported_platform",
            None,
            qualification_stage="runner",
            qualification_reason="unexpected",
        )
    output_identity: tuple[int, int] | None = None
    try:
        artifact, output_identity = _prepare_qualification_paths(
            artifact_dir, output_dir, timeout_seconds
        )
        deadline = time.monotonic() + timeout_seconds
        payload = _run_driver_phase(
            "runner",
            lambda: _qualification_payload(artifact, output_dir, deadline),
        )
        if time.monotonic() >= deadline:
            raise QualificationFailure(
                "scenario_timeout",
                qualification_stage="receipt",
                qualification_reason="unexpected",
            )
        destination = _run_driver_phase(
            "receipt",
            lambda: _write_receipt(
                output_dir,
                payload,
                expected_output_identity=output_identity,
            ),
        )
        return QualificationResult("passed", None, destination)
    except QualificationFailure as error:
        if output_identity is not None:
            error.record_cleanup(
                succeeded=_remove_owned_development_artifacts(
                    output_dir, output_identity
                )
            )
        return QualificationResult(
            "failed",
            error.failure_id,
            None,
            qualification_stage=error.qualification_stage,
            qualification_reason=error.qualification_reason,
            qualification_child_stage=error.qualification_child_stage,
            qualification_exit_code=error.qualification_exit_code,
            qualification_cleanup=error.qualification_cleanup,
            output_identity=output_identity,
        )
    except Exception:
        cleanup_status = "not_attempted"
        if output_identity is not None:
            cleanup_status = (
                "complete"
                if _remove_owned_development_artifacts(output_dir, output_identity)
                else "failed"
            )
            return QualificationResult(
                "failed",
                "scenario_failed",
                None,
                qualification_stage="runner",
                qualification_reason="unexpected",
                qualification_cleanup=cleanup_status,
                output_identity=output_identity,
            )
        return QualificationResult(
            "failed",
            "scenario_failed",
            None,
            qualification_stage="runner",
            qualification_reason="unexpected",
            qualification_cleanup=cleanup_status,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def _failure_output_identity(
    output: Path, result: QualificationResult
) -> tuple[int, int] | None:
    if result.output_identity is not None:
        return result.output_identity
    if result.failure_id == "output_failed" or not output.is_absolute():
        return None
    try:
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        metadata = output.lstat()
    except OSError:
        return None
    if not stat.S_ISDIR(metadata.st_mode):
        return None
    return metadata.st_dev, metadata.st_ino


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    result = qualify_windows_diagnostics(arguments.artifact_dir, arguments.output_dir)
    if result.status == "passed":
        return 0
    if result.failure_id in FAILURE_IDS:
        try:
            output = arguments.output_dir
            output_identity = _failure_output_identity(output, result)
            if output_identity is not None and not set(output.iterdir()):
                _write_receipt(
                    output,
                    {
                        "schema_version": 1,
                        "status": "failed",
                        "failure_id": result.failure_id,
                        "qualification_failure": {
                            "stage": result.qualification_stage,
                            "reason": result.qualification_reason,
                            **(
                                {"child_stage": result.qualification_child_stage}
                                if result.qualification_child_stage is not None
                                else {}
                            ),
                            **(
                                {"exit_code": result.qualification_exit_code}
                                if result.qualification_exit_code is not None
                                else {}
                            ),
                        },
                        "qualification_cleanup": result.qualification_cleanup,
                        "package": None,
                        "environment": None,
                        "topology": None,
                        "checks": [],
                        "metrics": None,
                        "operational_cost": None,
                    },
                    expected_output_identity=output_identity,
                )
        except (OSError, QualificationFailure):
            pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

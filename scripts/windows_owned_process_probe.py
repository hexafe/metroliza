"""Bounded owned-handle evidence; roles alone never grant acceptance."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import sys
import time
import stat
import uuid

from metroliza.shared import diagnostic_runtime_audit as audit

MAX_MEMBERS = 16
PHASES = frozenset({"suspended", "window_wait", "window_close", "drain", "startup", "running"})
UNAVAILABLE_SOURCES = frozenset({
    "system_directory", "parent_snapshot_open", "parent_snapshot_missing",
    "native_process_image", "probe_callback",
    "expected_file_package_launcher", "expected_file_package_application",
    "expected_file_package_ocr_worker", "expected_file_system_cmd",
    "expected_file_system_conhost", "expected_file_system_werfault",
    "expected_file_system_wermgr", "expected_file_system_openconsole",
    "expected_file_system_powershell",
})


class RuntimeEvidence:
    """One application launch/Job, one private journal, one owned probe."""

    def __init__(self, api, artifact: Path, cwd: Path, environment, failure_factory,
                 *, allow_ocr_worker: bool = False):
        self.root = cwd / ("runtime-audit-" + uuid.uuid4().hex)
        self.nonce = uuid.uuid4().hex
        self.failure_factory = failure_factory
        self.probe = OwnedProcessProbe(
            api, artifact, failure_factory, allow_ocr_worker=allow_ocr_worker,
        )
        self.probe.phase = "startup"
        self._create_root()
        environment.update({audit.GATE: "1", audit.ROOT: str(self.root), audit.NONCE: self.nonce})

    def _create_root(self):
        self.root.mkdir(mode=0o700)
        try:
            self.root_identity = self._identity()
        except BaseException as primary:
            failure = self.failure_factory()
            try:
                # The exclusively created root is still empty. Never recurse
                # or delete a replacement's contents when identity is unknown.
                self.root.rmdir()
            except Exception:
                failure.record_cleanup(succeeded=False)
            else:
                failure.record_cleanup(succeeded=True)
            if not isinstance(primary, Exception):
                raise
            raise failure from None

    def _identity(self):
        info = self.root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                or not info.st_ino):
            raise self.failure_factory()
        return info.st_dev, info.st_ino

    def _require_same_root(self):
        if self._identity() != self.root_identity:
            raise self.failure_factory()

    def ready(self):
        if self.probe.phase == "startup":
            self._require_same_root()
            self.probe.phase = "running"
            # The child can resume as soon as this marker exists. Publish the
            # probe phase first so its first post-ack event cannot be
            # attributed to startup by a cross-process scheduling race. A
            # failed marker write remains fatal; no later phase is accepted.
            (self.root / "ready").touch(exist_ok=False)

    def proof(self):
        try:
            self._require_same_root()
            events = audit.read_evidence(self.root, self.nonce)
            self._require_same_root()
        except Exception:
            raise self.failure_factory() from None
        return {"installed": True, "events": events, "owned": self.probe.receipt(),
                "probe_effect": "synchronous_private_prelaunch_journal_and_owned_handle_sampling"}

    def close(self):
        try:
            self._require_same_root()
            events = audit.read_evidence(self.root, self.nonce)
            observation = {"status": "observed", "events": events}
        except Exception:
            observation = {"status": "unavailable"}
        try:
            print("qualification_runtime_audit=" + json.dumps(observation, sort_keys=True),
                  file=sys.stderr, flush=True)
        except Exception:
            pass
        self.probe.emit()
        self._remove_journal()

    def _remove_journal(self):
        try:
            self._require_same_root()
        except FileNotFoundError:
            # An interruption can arrive after rmdir completed but before
            # ownership is released. Absence is complete cleanup; an existing
            # replacement still has to pass the original identity checks.
            return
        allowed = {"installed.json", "ready"} | {f"event-{index:02}.json" for index in range(1, audit.MAX_EVENTS + 1)}
        entries = []
        with os.scandir(self.root) as iterator:
            for entry in iterator:
                entries.append(entry.name)
                if len(entries) > audit.MAX_EVENTS + 2 or entry.name not in allowed:
                    raise self.failure_factory()
                # Windows DirEntry.stat caches st_nlink=0. Query full metadata
                # without following links; a single-link file is still required.
                info = (self.root / entry.name).lstat()
                if (not audit._plain_file(info) or info.st_size > 1024
                        or entry.name == "ready" and info.st_size != 0):
                    raise self.failure_factory()
        self._require_same_root()
        for name in entries:
            (self.root / name).unlink()
        self.root.rmdir()


def _expected_runtime_roles(supervised, platform_event, allow_ocr_worker):
    roles = (["package_launcher", "package_launcher"] if supervised else []) + ["package_application"]
    order = (["launcher_bootloader", "launcher_supervisor"] if supervised else []) + ["application"]
    if platform_event:
        roles += ["system_cmd", "system_conhost"]
        order += ["windows_version_command", "windows_version_console"]
    if allow_ocr_worker:
        roles += ["package_ocr_worker"]
        order += ["ocr_worker"]
    return roles, order


def _verified_audit_events(events, allow_ocr_worker):
    def reject():
        raise ValueError("runtime_evidence_invalid")

    if type(events) is not list or len(events) > 2:
        reject()
    platform_events = [event for event in events if type(event) is dict and event.get("kind") == "platform_ver"]
    worker_events = [event for event in events if type(event) is dict and event.get("kind") == "ocr_worker_launch"]
    if (len(platform_events) > 1 or len(worker_events) != int(allow_ocr_worker)
            or len(events) != len(platform_events) + len(worker_events)
            or events != platform_events + worker_events):
        reject()
    helper_phase = "startup"
    if platform_events:
        event = platform_events[0]
        if (type(event) is not dict or set(event) != {"kind", "caller", "phase"}
                or event["kind"] != "platform_ver"
                or type(event["caller"]) is not str or event["caller"] not in audit.CALLERS):
            reject()
        # startup_ready precedes lazy workflow imports. EXE24 proved NumPy's
        # same exact version query can occur after this real readiness boundary.
        # Pair that one evidenced case with running-only native observations.
        if event["phase"] == "after_ready" and event["caller"] == "numpy":
            helper_phase = "running"
        elif event["phase"] != "startup":
            reject()
    if worker_events and worker_events[0] != {
        "kind": "ocr_worker_launch", "caller": "metroliza", "phase": "after_ready",
    }:
        reject()
    return platform_events, helper_phase


def verified_runtime_order(
    proof, *, supervised: bool, allow_ocr_worker: bool = False,
) -> tuple[str, ...]:
    """Pair an audited attempt and exact native ancestry; neither suffices alone."""
    def reject():
        raise ValueError("runtime_evidence_invalid")

    if (type(proof) is not dict or set(proof) != {"installed", "events", "owned", "probe_effect"}
            or proof["installed"] is not True
            or proof["probe_effect"] != "synchronous_private_prelaunch_journal_and_owned_handle_sampling"):
        reject()
    platform_events, helper_phase = _verified_audit_events(proof["events"], allow_ocr_worker)
    owned = proof["owned"]
    expected_roles, expected_order = _expected_runtime_roles(
        supervised, platform_events, allow_ocr_worker,
    )
    if (type(owned) is not dict
            or set(owned) != {"schema_version", "members", "assigned", "unobserved", "job_empty", "overflow", "observation_unavailable", "probe_effect"}
            or type(owned["schema_version"]) is not int or owned["schema_version"] != 1
            or type(owned["assigned"]) is not int or owned["assigned"] != len(expected_roles)
            or type(owned["unobserved"]) is not int or owned["unobserved"] != 0
            or owned["job_empty"] is not True or owned["overflow"] is not False
            or owned["observation_unavailable"] is not False
            or owned["probe_effect"] != "extra_handle_queries_and_bounded_snapshot"
            or type(owned["members"]) is not list or len(owned["members"]) != len(expected_roles)):
        reject()
    _verify_members(owned["members"], expected_roles, helper_phase)
    return tuple(expected_order)


def _verify_members(members, expected_roles, helper_phase):
    def reject():
        raise ValueError("runtime_evidence_invalid")

    for index, (member, role) in enumerate(zip(members, expected_roles)):
        if (type(member) is not dict or set(member) != {"role", "identity", "first_phase", "last_phase", "parent_ordinal_advisory", "lifecycle"}
                or member["role"] != role or member["identity"] != "fixed_file_verified"
                or member["lifecycle"] != "job_empty"
                or member["first_phase"] not in PHASES or member["last_phase"] not in PHASES):
            reject()
        parent = member["parent_ordinal_advisory"]
        if parent != "unknown" and not (type(parent) is int and 0 <= parent < index):
            reject()
        if role in {"system_cmd", "system_conhost"} and (
            member["first_phase"] != helper_phase or member["last_phase"] != helper_phase
            or type(member["parent_ordinal_advisory"]) is not int
            or member["parent_ordinal_advisory"] != index - 1
        ):
            reject()
        if role == "package_ocr_worker" and (
            member["first_phase"] not in {"running", "drain"}
            or member["last_phase"] not in {"running", "drain"}
            or parent not in {"unknown", expected_roles.index("package_application")}
        ):
            reject()


class OwnedProcessProbe:
    def __init__(self, api, artifact: Path, failure_factory, *, allow_ocr_worker=False):
        self.api = api
        self.failure_factory = failure_factory
        self.unavailable = False
        self.unavailable_sources = set()
        self.images = (
            ("package_launcher", artifact / "metroliza.exe"),
            ("package_application", artifact / "metroliza_application.exe"),
        ) + self._system_images() + (
            (("package_ocr_worker", artifact / "metroliza_ocr_worker.exe"),)
            if allow_ocr_worker else ()
        )
        self.phase = "suspended"
        self.records = {}
        self.active = None
        self.assigned = None
        self.overflow = False
        self._declare_snapshot()

    def _system_images(self):
        function = self.api.kernel.GetSystemDirectoryW
        function.argtypes = [ctypes.POINTER(self.api.wintypes.WCHAR), self.api.wintypes.DWORD]
        function.restype = self.api.wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        copied = function(buffer, len(buffer))
        if not 0 < copied < len(buffer) or len(buffer.value) != copied or not Path(buffer.value).is_absolute():
            self._mark_unavailable("system_directory")
            return ()
        system = Path(buffer.value)
        return tuple((role, system / name) for role, name in (
            ("system_cmd", "cmd.exe"), ("system_conhost", "conhost.exe"),
        ))

    def _mark_unavailable(self, source):
        self.unavailable = True
        self.unavailable_sources.add(source if source in UNAVAILABLE_SOURCES else "probe_callback")

    def _declare_snapshot(self):
        wt = self.api.wintypes

        class Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
                ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260),
            ]

        # All per-Job probes on one API share the same DLL function objects.
        # ctypes rejects an earlier probe's pointer if a later probe replaces
        # argtypes with a distinct (even layout-identical) Structure class.
        self.Entry = getattr(self.api, "_owned_probe_snapshot_entry", Entry)
        self.api._owned_probe_snapshot_entry = self.Entry
        kernel = self.api.kernel
        kernel.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wt.HANDLE
        kernel.IsProcessInJob.argtypes = [wt.HANDLE, wt.HANDLE, ctypes.POINTER(wt.BOOL)]
        kernel.IsProcessInJob.restype = wt.BOOL
        for name in ("Process32FirstW", "Process32NextW"):
            function = getattr(kernel, name)
            function.argtypes = [wt.HANDLE, ctypes.POINTER(self.Entry)]
            function.restype = wt.BOOL

    def _parent_hint(self, process_id, owned_ids):
        """Read only the requested owned row; discard all other snapshot fields."""
        snapshot = self.api.kernel.CreateToolhelp32Snapshot(0x2, 0)
        if not self.api._valid_file_handle(snapshot):
            self._mark_unavailable("parent_snapshot_open")
            return None
        try:
            entry = self.Entry()
            entry.dwSize = ctypes.sizeof(entry)
            present = self.api.kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            deadline = time.monotonic() + 0.05
            for _ in range(4096):
                if not present or time.monotonic() >= deadline:
                    break
                if int(entry.th32ProcessID) == process_id:
                    parent = int(entry.th32ParentProcessID)
                    return parent if parent in owned_ids else None
                present = self.api.kernel.Process32NextW(snapshot, ctypes.byref(entry))
            self._mark_unavailable("parent_snapshot_missing")
            return None
        finally:
            # A new owned handle must close successfully even when observation
            # is unavailable. Cleanup failure is never converted to UNKNOWN.
            self.api._require_closed_handles(snapshot)

    def _role(self, handle, failure):
        native, unavailable = self.api._native_process_image(handle)
        if unavailable is not None:
            self._mark_unavailable("native_process_image")
            return "unknown"
        for role, expected in self.images:
            matched, unavailable = self.api._expected_file_native_image(expected, native, failure)
            if failure.qualification_cleanup == "failed":
                raise failure
            if unavailable is not None:
                self._mark_unavailable("expected_file_" + role)
            if matched is True and unavailable is None:
                return role
        return "unknown"

    def _contained(self, job, handle):
        contained = self.api.wintypes.BOOL()
        return bool(self.api.kernel.IsProcessInJob(handle, job, ctypes.byref(contained))) and bool(contained.value)

    def _parent_key(self, job, parent):
        keys = [key for key, value in self.records.items()
                if key[0] == parent and not value["left_snapshot"]]
        if len(keys) != 1:
            return None
        handle = self.api._open_job_process(job, parent)
        if handle is None:
            return None
        try:
            if not self._contained(job, handle):
                return None
            return keys[0] if self.api._process_creation_time(handle) == keys[0][1] else None
        finally:
            self.api._require_closed_handles(handle)

    def observe(self, job, handle, observation, owned_ids):
        key = (observation.process_id, observation.creation_time)
        if key in self.records:
            self.records[key]["last_phase"] = self.phase
            return
        if len(self.records) >= MAX_MEMBERS:
            self.overflow = True
            return
        failure = self.failure_factory()
        record = {
            "role": "unknown", "first_phase": self.phase, "last_phase": self.phase,
            "parent_key": None, "left_snapshot": False,
        }
        self.records[key] = record
        # Identity comparison occurs while this exact process handle is owned;
        # retained image text and Toolhelp basenames are never role evidence.
        verified_member = self._contained(job, handle)
        record["role"] = self._role(handle, failure) if verified_member else "unknown"
        parent = self._parent_hint(observation.process_id, owned_ids) if verified_member else None
        record["parent_key"] = self._parent_key(job, parent)

    def rejected(self, job, handle, process_id, owned_ids):
        """Observe a rejected member without changing or consuming its failure."""
        try:
            created = self.api._process_creation_time(handle)
        except Exception:
            return
        from types import SimpleNamespace
        self.observe(job, handle, SimpleNamespace(process_id=process_id, creation_time=created), owned_ids)

    def account(self, active, assigned, owned_ids):
        self.active = active
        self.assigned = max(self.assigned or 0, assigned)
        self.overflow = self.overflow or assigned > MAX_MEMBERS
        for (process_id, _), record in self.records.items():
            if process_id not in owned_ids:
                record["left_snapshot"] = True

    def _parent_ordinal(self, key, record, keys):
        # This is an advisory parent-PID correlation, not proof of ancestry or
        # permission to accept a member. Retired/ambiguous/reused PIDs stay unknown.
        parent = record["parent_key"]
        if parent is None:
            return "unknown"
        candidates = [item for item in keys if item[0] == parent[0]]
        if len(candidates) != 1:
            return "unknown"
        candidate = candidates[0]
        if candidate == key or candidate[1] >= key[1]:
            return "unknown"
        return keys.index(candidate)

    def receipt(self):
        keys = sorted(self.records, key=lambda item: (item[1], item[0]))
        members = []
        for key in keys:
            record = self.records[key]
            members.append({
                "role": record["role"],
                "identity": "fixed_file_verified" if record["role"] != "unknown" else "unknown",
                "first_phase": record["first_phase"], "last_phase": record["last_phase"],
                "parent_ordinal_advisory": self._parent_ordinal(key, record, keys),
                "lifecycle": "job_empty" if self.active == 0 else (
                    "left_snapshot" if record["left_snapshot"] else "not_proved_exited"
                ),
            })
        return {"schema_version": 1, "members": members,
                "assigned": None if self.assigned is None else min(MAX_MEMBERS, self.assigned),
                "unobserved": None if self.assigned is None else min(MAX_MEMBERS, max(0, self.assigned - len(keys))),
                "job_empty": self.active == 0, "overflow": self.overflow,
                "observation_unavailable": self.unavailable,
                "probe_effect": "extra_handle_queries_and_bounded_snapshot"}

    def emit(self):
        try:
            print("qualification_owned_members=" + json.dumps(self.receipt(), sort_keys=True),
                  file=sys.stderr, flush=True)
        except Exception:
            pass

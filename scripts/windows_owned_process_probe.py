"""Bounded, rejection-only observations; never a process acceptance policy."""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import sys
import time

MAX_MEMBERS = 16
PHASES = frozenset({"suspended", "window_wait", "window_close", "drain"})


class OwnedProcessProbe:
    def __init__(self, api, artifact: Path, failure_factory):
        self.api = api
        self.failure_factory = failure_factory
        self.unavailable = False
        self.images = (
            ("package_launcher", artifact / "metroliza.exe"),
            ("package_application", artifact / "metroliza_application.exe"),
        ) + self._system_images()
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
            self.unavailable = True
            return ()
        system = Path(buffer.value)
        return tuple((role, system / name) for role, name in (
            ("system_cmd", "cmd.exe"), ("system_conhost", "conhost.exe"),
            ("system_werfault", "WerFault.exe"), ("system_wermgr", "wermgr.exe"),
            ("system_openconsole", "OpenConsole.exe"),
            ("system_powershell", "WindowsPowerShell/v1.0/powershell.exe"),
        ))

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

        self.Entry = Entry
        kernel = self.api.kernel
        kernel.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wt.HANDLE
        kernel.IsProcessInJob.argtypes = [wt.HANDLE, wt.HANDLE, ctypes.POINTER(wt.BOOL)]
        kernel.IsProcessInJob.restype = wt.BOOL
        for name in ("Process32FirstW", "Process32NextW"):
            function = getattr(kernel, name)
            function.argtypes = [wt.HANDLE, ctypes.POINTER(Entry)]
            function.restype = wt.BOOL

    def _parent_hint(self, process_id, owned_ids):
        """Read only the requested owned row; discard all other snapshot fields."""
        snapshot = self.api.kernel.CreateToolhelp32Snapshot(0x2, 0)
        if not self.api._valid_file_handle(snapshot):
            self.unavailable = True
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
            self.unavailable = True
            return None
        finally:
            # A new owned handle must close successfully even when observation
            # is unavailable. Cleanup failure is never converted to UNKNOWN.
            self.api._require_closed_handles(snapshot)

    def _role(self, handle, failure):
        native, unavailable = self.api._native_process_image(handle)
        if unavailable is not None:
            self.unavailable = True
            return "unknown"
        for role, expected in self.images:
            matched, unavailable = self.api._expected_file_native_image(expected, native, failure)
            if failure.qualification_cleanup == "failed":
                raise failure
            if unavailable is not None:
                self.unavailable = True
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

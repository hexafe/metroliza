from __future__ import annotations

import ctypes
import json
from types import SimpleNamespace

import pytest

from scripts import qualify_windows_diagnostics as qualification
from scripts.windows_owned_process_probe import MAX_MEMBERS, OwnedProcessProbe


class Function:
    def __init__(self, action):
        self.action = action

    def __call__(self, *args):
        return self.action(*args)


def _probe(monkeypatch, tmp_path):
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path / "FAKE_SYSTEMROOT"))
    api = SimpleNamespace(wintypes=SimpleNamespace(
        DWORD=ctypes.c_uint32, LONG=ctypes.c_int32, WCHAR=ctypes.c_wchar,
        HANDLE=ctypes.c_void_p, BOOL=ctypes.c_int,
    ))
    closed = []

    def contained(_handle, _job, pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int)).contents.value = 1
        return 1

    def system_directory(buffer, _capacity):
        buffer.value = str(tmp_path / "OS_SYSTEM32")
        return len(buffer.value)

    api.kernel = SimpleNamespace(
        GetSystemDirectoryW=Function(system_directory),
        IsProcessInJob=Function(contained),
        CreateToolhelp32Snapshot=Function(lambda *_: 99),
        Process32FirstW=Function(lambda *_: False),
        Process32NextW=Function(lambda *_: False),
    )
    api._valid_file_handle = qualification._WindowsApi._valid_file_handle
    api._require_closed_handles = lambda handle: closed.append(handle)
    api._native_process_image = lambda handle: (handle, None)
    api._expected_file_native_image = lambda expected, native, _: (str(expected) == native, None)
    api._open_job_process = lambda _job, pid: pid
    api._process_creation_time = lambda _handle: 100
    probe = OwnedProcessProbe(api, tmp_path / "package", lambda: qualification.QualificationFailure("scenario_failed"))
    return probe, api, closed


def _observation(pid=1234567, created=87654321):
    return qualification._ProcessObservation(pid, created, "PRIVATE_IMAGE_NEVER_PUBLISHED")


def test_fixed_file_roles_are_closed_and_do_not_change_topology(monkeypatch, tmp_path):
    probe, _api, closed = _probe(monkeypatch, tmp_path)
    roles = dict(probe.images)
    probe.observe(90, str(roles["package_application"]), _observation(), (1234567,))
    probe.phase = "window_wait"
    probe.observe(90, str(roles["system_cmd"]), _observation(2234567, 97654321), (1234567, 2234567))
    probe.account(0, 2, ())
    result = probe.receipt()
    assert [entry["role"] for entry in result["members"]] == ["package_application", "system_cmd"]
    assert all(entry["identity"] == "fixed_file_verified" for entry in result["members"])
    assert all(entry["lifecycle"] == "job_empty" for entry in result["members"])
    assert closed == [99, 99]
    serialized = json.dumps(result)
    for private in (str(tmp_path), "PRIVATE_IMAGE", "1234567", "87654321"):
        assert private not in serialized
    topology = qualification._classify_topology(
        (_observation(),), 2, 2, True, roles["package_launcher"], roles["package_application"],
    )
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_topology_record(qualification._topology_record(topology), supervised=False)


@pytest.mark.parametrize("defect", ["wrong_image", "query_unavailable", "not_in_job"])
def test_unknown_or_unowned_members_are_never_fixed_file_verified(monkeypatch, tmp_path, defect):
    probe, api, _ = _probe(monkeypatch, tmp_path)
    handle = str(tmp_path / "foreign" / "cmd.exe")
    if defect == "query_unavailable":
        api._native_process_image = lambda _: (None, "unavailable")
    if defect == "not_in_job":
        api.kernel.IsProcessInJob.action = lambda *_: False
        api._native_process_image = lambda _: pytest.fail("must not inspect unowned image")
    probe.observe(90, handle, _observation(), (1234567,))
    assert probe.receipt()["members"][0]["identity"] == "unknown"


def test_parent_hint_is_advisory_and_bound_before_child_observation(monkeypatch, tmp_path):
    probe, _, _ = _probe(monkeypatch, tmp_path)
    probe._parent_hint = lambda *_: 11
    probe.observe(90, "unknown", _observation(11, 100), (11,))
    probe.observe(90, "unknown", _observation(22, 200), (11, 22))
    result = probe.receipt()
    assert result["members"][0]["parent_ordinal_advisory"] == "unknown"
    assert result["members"][1]["parent_ordinal_advisory"] == 0
    # A reused PID makes the earlier advisory correlation ambiguous.
    probe.observe(90, "unknown", _observation(11, 300), (11, 22))
    assert probe.receipt()["members"][1]["parent_ordinal_advisory"] == "unknown"


def test_parent_pid_reused_between_snapshots_is_unknown(monkeypatch, tmp_path):
    probe, api, _ = _probe(monkeypatch, tmp_path)
    probe._parent_hint = lambda *_: 11
    probe.observe(90, "unknown", _observation(11, 100), (11,))
    api._process_creation_time = lambda _handle: 150
    probe.observe(90, "unknown", _observation(22, 200), (11, 22))
    assert probe.receipt()["members"][1]["parent_ordinal_advisory"] == "unknown"


@pytest.mark.parametrize("boundary", ["_open_job_process", "_process_creation_time"])
def test_parent_query_failure_retains_the_verified_child_role(monkeypatch, tmp_path, boundary):
    probe, api, _ = _probe(monkeypatch, tmp_path)
    probe._parent_hint = lambda *_: 11
    images = dict(probe.images)
    probe.observe(90, str(images["package_application"]), _observation(11, 100), (11,))
    def fail_parent(*_):
        raise qualification.QualificationFailure("scenario_failed")
    setattr(api, boundary, fail_parent)
    owner = object.__new__(qualification._WindowsApi)
    owner._owned_probe = probe
    owner._probe_call("observe", 90, str(images["system_cmd"]), _observation(22, 200), (11, 22))
    result = probe.receipt()
    assert result["observation_unavailable"] is True
    child = result["members"][1]
    assert child["role"] == "system_cmd" and child["identity"] == "fixed_file_verified"
    assert child["parent_ordinal_advisory"] == "unknown"


def test_failed_fixed_file_comparison_marks_observation_incomplete(monkeypatch, tmp_path):
    probe, api, _ = _probe(monkeypatch, tmp_path)
    api._expected_file_native_image = lambda *_: (None, "unavailable")
    probe.observe(90, "unknown", _observation(), (1234567,))
    assert probe.receipt()["observation_unavailable"] is True
    assert probe.receipt()["members"][0]["identity"] == "unknown"


def test_retired_or_not_yet_observed_parent_stays_unknown(monkeypatch, tmp_path):
    probe, _, _ = _probe(monkeypatch, tmp_path)
    probe._parent_hint = lambda *_: 11
    probe.observe(90, "unknown", _observation(11, 100), (11,))
    probe.account(0, 1, ())
    probe.observe(90, "unknown", _observation(22, 200), (11, 22))
    assert probe.receipt()["members"][1]["parent_ordinal_advisory"] == "unknown"


def test_snapshot_discards_foreign_rows_and_closes_handle(monkeypatch, tmp_path):
    probe, api, closed = _probe(monkeypatch, tmp_path)
    def row(_snapshot, pointer):
        entry = ctypes.cast(pointer, ctypes.POINTER(probe.Entry)).contents
        entry.th32ProcessID, entry.th32ParentProcessID = 44, 55
        entry.szExeFile = "PRIVATE_FOREIGN_IMAGE"
        return True
    api.kernel.Process32FirstW.action = row
    assert probe._parent_hint(44, (44,)) is None
    assert probe._parent_hint(44, (44, 55)) == 55
    assert probe._parent_hint(77, (77,)) is None
    assert closed == [99, 99, 99]


def test_probe_snapshot_cleanup_failure_remains_fatal(monkeypatch, tmp_path):
    probe, api, _ = _probe(monkeypatch, tmp_path)
    def fail_close(_):
        raise qualification.QualificationFailure("scenario_failed", qualification_cleanup="failed")
    api._require_closed_handles = fail_close
    owner = object.__new__(qualification._WindowsApi)
    owner._owned_probe = probe
    with pytest.raises(qualification.QualificationFailure) as failure:
        owner._probe_call("observe", 90, "unknown", _observation(), (1234567,))
    assert failure.value.qualification_cleanup == "failed"


def test_probe_failure_is_unknown_and_cannot_replace_acceptance(monkeypatch, tmp_path):
    probe, api, _ = _probe(monkeypatch, tmp_path)
    def fail_query(_):
        raise OSError("PRIVATE_ERROR")
    api._native_process_image = fail_query
    owner = object.__new__(qualification._WindowsApi)
    owner._owned_probe = probe
    owner._probe_call("observe", 90, "unknown", _observation(), (1234567,))
    assert probe.receipt()["observation_unavailable"] is True
    assert "PRIVATE_ERROR" not in json.dumps(probe.receipt())


def test_probe_caps_members_and_keeps_missed_processes_unknown(monkeypatch, tmp_path):
    probe, _, _ = _probe(monkeypatch, tmp_path)
    for index in range(MAX_MEMBERS + 1):
        probe.observe(90, "unknown", _observation(index, index + 1), (index,))
    probe.account(0, MAX_MEMBERS + 2, ())
    result = probe.receipt()
    assert len(result["members"]) == MAX_MEMBERS
    assert result["overflow"] is True and result["unobserved"] == 2


def test_unobserved_assignment_overflow_is_explicit(monkeypatch, tmp_path):
    probe, _, _ = _probe(monkeypatch, tmp_path)
    probe.account(0, MAX_MEMBERS + 1, ())
    assert probe.receipt()["overflow"] is True


def test_system_roles_ignore_overridden_environment_directory(monkeypatch, tmp_path):
    probe, _, _ = _probe(monkeypatch, tmp_path)
    assert dict(probe.images)["system_cmd"] == tmp_path / "OS_SYSTEM32" / "cmd.exe"


@pytest.mark.parametrize("error", [OSError, ValueError, TypeError, RuntimeError])
def test_emission_cannot_mask_the_original_failure(monkeypatch, tmp_path, error):
    probe, _, _ = _probe(monkeypatch, tmp_path)
    def fail_emit(*_, **__):
        raise error("PRIVATE_OUTPUT_ERROR")
    monkeypatch.setattr("builtins.print", fail_emit)
    with pytest.raises(qualification.QualificationFailure, match="output_failed"):
        try:
            raise qualification.QualificationFailure("output_failed")
        finally:
            probe.emit()

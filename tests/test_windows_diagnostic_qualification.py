from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
import zipfile
from pathlib import Path

import pytest

from metroliza.app import diagnostic_qualification as qualification_entry
from metroliza.shared.diagnostic_incident import (
    ChannelState,
    HandshakeState,
    IncidentObservation,
    LaunchState,
    TerminationState,
    build_incident,
)
from metroliza.shared.diagnostic_ring import LOSS_ACCOUNTING_BYTES, RingLoss, RingSnapshot
from scripts import qualify_windows_diagnostics as qualification


def test_entry_failure_receipt_maps_only_closed_stage_and_reason(tmp_path) -> None:
    qualification_entry._write_failure(
        tmp_path, "preview", ValueError("qualification_export_unavailable")
    )
    assert json.loads((tmp_path / "failure.json").read_text(encoding="ascii")) == {
        "schema_version": 1,
        "stage": "preview",
        "reason": "qualification_export_unavailable",
    }
    qualification_entry._write_failure(
        tmp_path, "private-stage", RuntimeError("PRIVATE_PATH")
    )
    assert json.loads((tmp_path / "failure.json").read_text(encoding="ascii")) == {
        "schema_version": 1,
        "stage": "application",
        "reason": "unexpected",
    }


def _write_pe(path: Path, subsystem: int = 2) -> None:
    image = bytearray(512)
    image[0:2] = b"MZ"
    image[0x3C:0x40] = (128).to_bytes(4, "little")
    image[128:132] = b"PE\x00\x00"
    optional = 128 + 4 + 20
    image[optional : optional + 2] = (0x20B).to_bytes(2, "little")
    image[optional + 68 : optional + 70] = subsystem.to_bytes(2, "little")
    path.write_bytes(image)


def _package_receipt() -> dict[str, object]:
    return {
        "git_sha": "a" * 40,
        "launcher_sha256": "b" * 64,
        "application_sha256": "c" * 64,
        "manifest_sha256": "d" * 64,
        "notice_hashes": {
            "THIRD_PARTY_NOTICES.md": "e" * 64,
            "third_party_inventory_260711.json": "f" * 64,
        },
        "tested_tree_sha256": "1" * 64,
        "package_manifest_sha256": "2" * 64,
        "archive_name": qualification.PACKAGE_ARCHIVE_NAME,
        "archive_sha256": "3" * 64,
        "archive_size_bytes": 100,
    }


def _environment_receipt() -> dict[str, str]:
    return {
        "windows_version": "10.0.26100",
        "architecture": "amd64",
        "python_version": "3.11.16",
        "pyinstaller_version": "6.16.0",
    }


def _flood_loss(value: int = 1) -> dict[str, object]:
    return {
        "source_dropped": value,
        **{
            field: False if field == "counters_saturated" else value
            for field in qualification.RING_LOSS_FIELDS
        },
    }


def _metrics(value: int = 1) -> qualification.ProcessMetrics:
    return qualification.ProcessMetrics(value, value, value, value, value)


def _scenario(
    value: int = 1, *, supervised: bool = False
) -> qualification.ScenarioResult:
    topology = qualification.ProcessTopology(
        2 if supervised else 0,
        1,
        0,
        3 if supervised else 1,
        3 if supervised else 1,
        (
            ("launcher_bootloader", "launcher_supervisor", "application")
            if supervised
            else ("application",)
        ),
        True,
    )
    return qualification.ScenarioResult(
        0, value, value, "complete", _metrics(value), topology
    )


def _success_payload() -> dict[str, object]:
    results = {
        "direct_normal_1": _scenario(),
        "direct_normal_2": _scenario(2),
        "supervised_normal_1": _scenario(3, supervised=True),
        "supervised_normal_2": _scenario(4, supervised=True),
        "flood": _scenario(5),
    }
    return qualification._success_payload(
        _package_receipt(),
        _environment_receipt(),
        results,
        direct_idle_write_bytes=5,
        supervised_idle_write_bytes=6,
        hard_ready_to_report_ms=7,
        handled_ready_to_report_ms=8,
        hard_assembly_to_verification_ms=9,
        handled_assembly_to_verification_ms=10,
        flood_loss=_flood_loss(),
    )


def test_sanitized_environment_has_only_fixed_runtime_inputs(tmp_path) -> None:
    artifact = tmp_path / "package"
    work = tmp_path / "work"
    state = tmp_path / "state"
    inherited = {
        "SYSTEMROOT": r"C:\Windows",
        "USERPROFILE": r"C:\Users\runner",
        "PYTHONPATH": r"C:\development\src",
        "PYTHONHOME": r"C:\development\python",
        "VIRTUAL_ENV": r"C:\development\.venv",
        "METROLIZA_STARTUP_PROFILE": "1",
        "SECRET_VALUE": "not-for-child",
        "PATH": r"C:\development\python",
    }

    environment = qualification._sanitized_environment(
        artifact, work, state, "normal", inherited=inherited
    )

    assert environment["PATH"].split(";") == [
        str(artifact),
        str(artifact / "_internal"),
        str(Path(r"C:\Windows") / "System32"),
        r"C:\Windows",
    ]
    assert environment["METROLIZA_STARTUP_SMOKE"] == "1"
    assert environment["METROLIZA_DIAGNOSTIC_QUALIFICATION"] == "normal"
    assert environment["METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT"] == str(work)
    assert environment["LOCALAPPDATA"] == str(state)
    assert not any(key.startswith("PYTHON") for key in environment)
    assert "VIRTUAL_ENV" not in environment
    assert "METROLIZA_STARTUP_PROFILE" not in environment
    assert "SECRET_VALUE" not in environment


def test_pe_subsystem_requires_a_gui_executable(tmp_path) -> None:
    gui = tmp_path / "gui.exe"
    console = tmp_path / "console.exe"
    invalid = tmp_path / "invalid.exe"
    _write_pe(gui, 2)
    _write_pe(console, 3)
    invalid.write_bytes(b"not a portable executable")

    assert qualification._pe_subsystem(gui) == 2
    assert qualification._pe_subsystem(console) == 3
    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._pe_subsystem(invalid)
    assert error.value.failure_id == "artifact_invalid"


def test_child_receipt_requires_packaged_console_none_and_ordinary_user(tmp_path) -> None:
    path = tmp_path / "qualification.json"
    payload = {
        "schema_version": 1,
        "scenario": "normal",
        "stage": "complete",
        "packaged": True,
        "console_none": True,
        "ordinary_user": True,
    }
    path.write_text(json.dumps(payload), encoding="ascii")
    assert qualification._validate_child_receipt(path, "normal") == payload

    for field in ("packaged", "console_none", "ordinary_user"):
        changed = dict(payload)
        changed[field] = False
        path.write_text(json.dumps(changed), encoding="ascii")
        with pytest.raises(qualification.QualificationFailure):
            qualification._validate_child_receipt(path, "normal")

    path.write_text('{"schema_version":1,"schema_version":1}', encoding="ascii")
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_child_receipt(path, "normal")

    failure_path = tmp_path / "failure.json"
    failure = {
        "schema_version": 1,
        "stage": "preview",
        "reason": "qualification_export_unavailable",
    }
    failure_path.write_text(json.dumps(failure), encoding="ascii")
    assert qualification._validate_child_failure(failure_path) == failure
    failure["reason"] = "arbitrary private exception"
    failure_path.write_text(json.dumps(failure), encoding="ascii")
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_child_failure(failure_path)


def test_provenance_and_notices_bind_the_exact_launcher(tmp_path) -> None:
    launcher = tmp_path / "metroliza.exe"
    launcher.write_bytes(b"exact launcher")
    digest = hashlib.sha256(launcher.read_bytes()).hexdigest()
    sidecar = {
        "schema_version": 1,
        "release_label": "260913",
        "git_sha": "a" * 40,
        "dirty": False,
        "built_at_utc": "2026-09-13T10:00:00Z",
        "packager": "pyinstaller",
        "python_version": "3.11.16",
        "artifact": {
            "name": launcher.name,
            "sha256": digest,
            "size_bytes": launcher.stat().st_size,
        },
    }
    launcher.with_name("metroliza.exe.provenance.json").write_text(
        json.dumps(sidecar), encoding="utf-8"
    )
    notices = launcher.with_name("metroliza.exe.licenses")
    notices.mkdir()
    entries = []
    for name in qualification.NOTICE_FILES:
        path = notices / name
        path.write_text(f"fixed {name}\n", encoding="utf-8")
        entries.append({"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (notices / "NOTICE_MANIFEST.json").write_text(
        json.dumps({"files": entries}), encoding="utf-8"
    )

    assert qualification._validate_sidecar(launcher, "a" * 40) == digest
    assert set(qualification._validate_notices(launcher)) == set(qualification.NOTICE_FILES)

    launcher.write_bytes(b"changed launcher")
    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._validate_sidecar(launcher, "a" * 40)
    assert error.value.failure_id == "provenance_invalid"


def test_output_receipt_is_closed_bounded_and_atomic(tmp_path) -> None:
    output = tmp_path / "receipts"
    output.mkdir()
    source = tmp_path / "source"
    tested = tmp_path / "tested"
    source.mkdir()
    tested.mkdir()
    (source / "fixed component.bin").write_bytes(b"approved package bytes")
    (tested / "fixed component.bin").write_bytes(b"approved package bytes")
    payload_to_write = _success_payload()
    payload_to_write["package"].update(
        qualification._write_development_artifacts(source, tested, output)
    )
    destination = qualification._write_receipt(output, payload_to_write)

    payload = json.loads(destination.read_text(encoding="ascii"))
    assert {path.name for path in output.iterdir()} == {
        qualification.OUTPUT_NAME,
        qualification.PACKAGE_MANIFEST_NAME,
        qualification.PACKAGE_ARCHIVE_NAME,
    }
    assert payload["status"] == "passed"
    assert [check["id"] for check in payload["checks"]] == [
        *qualification.CHECK_IDS,
        qualification.OPERATIONAL_CHECK_ID,
    ]
    assert set(payload["metrics"]) == {
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
    manifest = json.loads(
        (output / qualification.PACKAGE_MANIFEST_NAME).read_text(encoding="ascii")
    )
    assert manifest["entries"] == [
        {
            "path": "fixed component.bin",
            "sha256": hashlib.sha256(b"approved package bytes").hexdigest(),
            "size_bytes": len(b"approved package bytes"),
        }
    ]
    assert payload["package"]["archive_sha256"] == manifest["archive"]["sha256"]

    second = tmp_path / "second"
    second.mkdir()
    unsafe = _success_payload()
    unsafe["raw_exception"] = "must not be written"
    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._write_receipt(second, unsafe)
    assert error.value.failure_id == "output_failed"

    assert not tuple(second.iterdir())


def test_package_relocation_rejects_links_and_entry_overflow(tmp_path, monkeypatch) -> None:
    source = tmp_path / "package"
    source.mkdir()
    (source / "component").write_bytes(b"safe")
    linked = source / "linked"
    linked.symlink_to(source / "component")

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._validate_package_tree(source)
    assert error.value.failure_id == "artifact_invalid"

    linked.unlink()
    monkeypatch.setattr(qualification, "MAX_PACKAGE_ENTRIES", 0)
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_package_tree(source)


def test_operational_cost_is_truthful_and_environment_is_closed() -> None:
    payload = _success_payload()
    assert payload["operational_cost"]["status"] == "within_budget"
    payload["metrics"]["supervised_idle_write_bytes"] = (
        qualification.MAX_IDLE_WRITE_BYTES + 1
    )
    payload["operational_cost"] = qualification._operational_cost(payload["metrics"])
    payload["checks"][-1]["status"] = "unresolved"
    qualification._validate_output_payload(payload)
    assert payload["operational_cost"]["status"] == "unresolved"

    payload["environment"]["architecture"] = "x86"
    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._validate_output_payload(payload)
    assert error.value.failure_id == "output_failed"

    payload = _success_payload()
    threshold = qualification.MAX_SUPERVISOR_MEMORY_OVERHEAD_BYTES
    payload["metrics"]["direct_peak_process_tree_memory_bytes"] = [threshold * 2, 1]
    payload["metrics"]["supervised_peak_process_tree_memory_bytes"] = [
        threshold * 2,
        threshold + 2,
    ]
    cost = qualification._operational_cost(payload["metrics"])
    assert cost["observed"]["max_supervisor_memory_overhead_bytes"] == threshold + 1
    assert cost["status"] == "unresolved"


def test_output_failure_detail_accepts_only_closed_qualification_evidence() -> None:
    payload = {
        "schema_version": 1,
        "status": "failed",
        "failure_id": "scenario_failed",
        "qualification_failure": {
            "stage": "preview",
            "reason": "qualification_preview_unavailable",
        },
        "package": None,
        "environment": None,
        "topology": None,
        "checks": [],
        "metrics": None,
        "operational_cost": None,
    }
    qualification._validate_output_payload(payload)
    payload["qualification_failure"]["reason"] = "PRIVATE_PATH"
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_output_payload(payload)


def test_topology_rejects_path_selected_or_recursive_children(tmp_path) -> None:
    launcher = tmp_path / "metroliza.exe"
    application = tmp_path / "metroliza_application.exe"
    unexpected = tmp_path / "elsewhere" / "metroliza_application.exe"
    observations = (
        qualification._ProcessObservation(1, 1, str(launcher)),
        qualification._ProcessObservation(2, 2, str(launcher)),
        qualification._ProcessObservation(3, 3, str(application)),
        qualification._ProcessObservation(4, 4, str(unexpected)),
    )

    topology = qualification._classify_topology(
        observations, 4, 4, True, launcher, application
    )

    assert topology.unexpected_processes_observed == 1
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_topology_record(
            qualification._topology_record(topology), supervised=True
        )


def test_full_tree_identity_rejects_post_copy_change(tmp_path) -> None:
    source = tmp_path / "source"
    tested = tmp_path / "tested"
    output = tmp_path / "output"
    for path in (source, tested, output):
        path.mkdir()
    (source / "one.bin").write_bytes(b"one")
    (tested / "one.bin").write_bytes(b"changed")

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._write_development_artifacts(source, tested, output)
    assert error.value.failure_id == "artifact_invalid"
    assert not tuple(output.iterdir())


@pytest.mark.parametrize("replacement", [b"two", b"unexpected growth"])
def test_archive_copy_rejects_change_after_inventory(
    tmp_path, monkeypatch, replacement
) -> None:
    source = tmp_path / "source"
    tested = tmp_path / "tested"
    output = tmp_path / "output"
    for path in (source, tested, output):
        path.mkdir()
    (source / "one.bin").write_bytes(b"one")
    tested_file = tested / "one.bin"
    tested_file.write_bytes(b"one")
    inventory = qualification._package_inventory

    def mutate_after_inventory(root):
        result = inventory(root)
        if root == tested:
            tested_file.write_bytes(replacement)
        return result

    monkeypatch.setattr(qualification, "_package_inventory", mutate_after_inventory)
    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._write_development_artifacts(source, tested, output)
    assert error.value.failure_id == "artifact_invalid"
    assert not tuple(output.iterdir())


def test_published_archive_revalidates_each_member_sha(tmp_path) -> None:
    source = tmp_path / "source"
    tested = tmp_path / "tested"
    output = tmp_path / "output"
    for path in (source, tested, output):
        path.mkdir()
    (source / "one.bin").write_bytes(b"one")
    (tested / "one.bin").write_bytes(b"one")
    package = qualification._write_development_artifacts(source, tested, output)
    archive_path = output / qualification.PACKAGE_ARCHIVE_NAME
    archive_path.unlink()
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr("one.bin", b"two")
    manifest_path = output / qualification.PACKAGE_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    archive_sha256 = qualification._sha256(
        archive_path, maximum=qualification.MAX_PACKAGE_ARCHIVE_BYTES
    )
    manifest["archive"].update(
        sha256=archive_sha256, size_bytes=archive_path.stat().st_size
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        encoding="ascii",
    )
    package.update(
        archive_sha256=archive_sha256,
        archive_size_bytes=archive_path.stat().st_size,
        package_manifest_sha256=qualification._sha256(
            manifest_path, maximum=qualification.MAX_PACKAGE_MANIFEST_BYTES
        ),
    )

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._validate_development_artifacts(output, package)
    assert error.value.failure_id == "output_failed"


def test_package_inventory_rejects_empty_directories(tmp_path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "component.bin").write_bytes(b"one")
    (package / "required-empty").mkdir()

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._package_inventory(package)
    assert error.value.failure_id == "artifact_invalid"


def test_hard_exit_rejects_a_valid_incident_with_empty_history() -> None:
    incident = build_incident(
        session_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        report_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        created_at_ms=1_800_000_000_000,
        build_git_sha="a" * 40,
        observation=IncidentObservation(
            launch=LaunchState.STARTED,
            handshake=HandshakeState.ACCEPTED,
            channel=ChannelState.INCOMPLETE,
            exit_code=9,
            termination=TerminationState.OBSERVED_EXIT,
            clean_terminal_received=False,
            source_dropped=0,
            source_loss_known=False,
            elapsed_ms=100,
        ),
        history=RingSnapshot((), RingLoss(), LOSS_ACCOUNTING_BYTES),
    )

    with pytest.raises(qualification.QualificationFailure) as error:
        qualification._validate_hard_exit_history(incident)
    assert error.value.failure_id == "incident_invalid"


class _FakeProcess:
    def __init__(self, exit_code: int, *, supervised: bool) -> None:
        self.started = time.perf_counter()
        self.exit_code = exit_code
        self.closed_with: bool | None = None
        self.supervised = supervised

    def poll(self) -> int:
        return self.exit_code

    def metrics(self) -> qualification.ProcessMetrics:
        return _metrics()

    def observe(self) -> None:
        return None

    def active_processes(self) -> int:
        return 0

    def topology(self, _artifact, *, all_exited: bool) -> qualification.ProcessTopology:
        return _scenario(supervised=self.supervised).topology

    def close(self, *, terminate: bool = False) -> None:
        self.closed_with = terminate


class _FakeApi:
    def __init__(self, exit_code: int, stage: str) -> None:
        self.exit_code = exit_code
        self.stage = stage
        self.process: _FakeProcess | None = None
        self.environment: dict[str, str] | None = None

    def launch(self, executable, environment, cwd):
        self.environment = environment
        common = {
            "schema_version": 1,
            "scenario": environment["METROLIZA_DIAGNOSTIC_QUALIFICATION"],
            "packaged": True,
            "console_none": True,
            "ordinary_user": True,
        }
        startup = {**common, "stage": "startup_ready"}
        payload = {**common, "stage": self.stage}
        (cwd / "startup.json").write_text(json.dumps(startup), encoding="ascii")
        (cwd / "qualification.json").write_text(json.dumps(payload), encoding="ascii")
        self.process = _FakeProcess(
            self.exit_code, supervised=Path(executable).name == "metroliza.exe"
        )
        return self.process


def test_scenario_uses_fixed_receipt_and_closes_completed_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    api = _FakeApi(9, "ready")
    artifact = tmp_path / "artifact"
    work = tmp_path / "work"
    state = tmp_path / "state"
    for path in (artifact, work, state):
        path.mkdir()
    called = []

    result = qualification._run_scenario(
        api,
        artifact / "metroliza.exe",
        artifact,
        work,
        state,
        "hard_exit",
        time.monotonic() + 1,
        expected_exit=9,
        expected_stage="ready",
        on_ready=lambda process: called.append(process),
    )

    assert result.exit_code == 9
    assert result.startup_ready_ms >= 0
    assert result.receipt_stage == "ready"
    assert called == [api.process]
    assert api.process.closed_with is False
    assert not any(key.startswith("PYTHON") for key in api.environment)


def test_platform_and_relative_arguments_fail_without_creating_output(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = qualification.qualify_windows_diagnostics(
        Path("artifact"), Path("output")
    )

    if os.name == "nt":
        assert result.failure_id == "invalid_arguments"
    else:
        assert result == qualification.QualificationResult(
            "failed", "unsupported_platform", None
        )
    assert not (tmp_path / "output").exists()


@pytest.mark.skipif(os.name != "nt", reason="native restricted-token proof requires Windows")
def test_native_windows_restricted_token_job_launches_without_console(tmp_path) -> None:
    api = qualification._WindowsApi()
    system_root = Path(os.environ["SYSTEMROOT"])
    executable = system_root / "System32" / "whoami.exe"
    environment = qualification._sanitized_environment(
        tmp_path, tmp_path, tmp_path, "normal"
    )
    process = api.launch(executable, environment, tmp_path)
    try:
        deadline = time.monotonic() + 10
        exit_code = None
        while time.monotonic() < deadline:
            exit_code = process.poll()
            if exit_code is not None:
                break
            time.sleep(0.02)
        assert exit_code is not None
        assert process.metrics().peak_job_memory_bytes >= 0
    finally:
        process.close(terminate=exit_code is None)

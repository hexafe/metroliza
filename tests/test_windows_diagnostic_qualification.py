from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from scripts import qualify_windows_diagnostics as qualification


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
    }


def _metrics(value: int = 1) -> qualification.ProcessMetrics:
    return qualification.ProcessMetrics(value, value, value, value, value)


def _scenario(value: int = 1) -> qualification.ScenarioResult:
    return qualification.ScenarioResult(0, value, value, "complete", _metrics(value))


def _success_payload() -> dict[str, object]:
    results = {
        "direct_normal": _scenario(),
        "supervised_normal_1": _scenario(2),
        "supervised_normal_2": _scenario(3),
        "supervised_normal_3": _scenario(4),
        "flood": _scenario(5),
    }
    return qualification._success_payload(
        _package_receipt(),
        results,
        idle_write_bytes=6,
        hard_ready_to_report_ms=7,
        handled_ready_to_report_ms=8,
        hard_assembly_to_verification_ms=9,
        handled_assembly_to_verification_ms=10,
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
        r"C:\Windows/System32",
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
    destination = qualification._write_receipt(output, _success_payload())

    payload = json.loads(destination.read_text(encoding="ascii"))
    assert set(output.iterdir()) == {destination}
    assert payload["status"] == "passed"
    assert [check["id"] for check in payload["checks"]] == list(qualification.CHECK_IDS)
    assert set(payload["metrics"]) == {
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


class _FakeProcess:
    def __init__(self, exit_code: int) -> None:
        self.started = time.perf_counter()
        self.exit_code = exit_code
        self.closed_with: bool | None = None

    def poll(self) -> int:
        return self.exit_code

    def metrics(self) -> qualification.ProcessMetrics:
        return _metrics()

    def close(self, *, terminate: bool = False) -> None:
        self.closed_with = terminate


class _FakeApi:
    def __init__(self, exit_code: int, stage: str) -> None:
        self.exit_code = exit_code
        self.stage = stage
        self.process: _FakeProcess | None = None
        self.environment: dict[str, str] | None = None

    def launch(self, _executable, environment, cwd):
        self.environment = environment
        payload = {
            "schema_version": 1,
            "scenario": environment["METROLIZA_DIAGNOSTIC_QUALIFICATION"],
            "stage": self.stage,
            "packaged": True,
            "console_none": True,
            "ordinary_user": True,
        }
        (cwd / "qualification.json").write_text(json.dumps(payload), encoding="ascii")
        self.process = _FakeProcess(self.exit_code)
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

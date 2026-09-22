"""The core-package launch retains C22 ownership across opcode interrupts."""
from __future__ import annotations

import dis
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import qualify_windows_candidate_core as driver
from scripts import qualify_windows_diagnostics as diagnostics
from scripts import windows_owned_process_probe as owned_probe
from metroliza.app import windows_candidate_qualification as application


def _interrupt_after_launch_before_store(code, primary, action) -> None:
    instructions = list(dis.get_instructions(code))
    transfer = next(
        instruction.offset
        for index, instruction in enumerate(instructions)
        if instructions[index - 1].opname == "CALL"
        and instruction.opname == "STORE_FAST"
        and instruction.argval == "process"
    )

    def trace(frame, event, _argument):
        if frame.f_code is code:
            if event == "call":
                frame.f_trace_opcodes = True
            elif event == "opcode" and frame.f_lasti == transfer:
                raise primary
        return trace

    previous = sys.gettrace()
    sys.settrace(trace)
    try:
        action()
    finally:
        sys.settrace(previous)


def _legacy_unowned_launch(api) -> None:
    process = api.launch(Path("metroliza.exe"), {}, Path("."))
    try:
        return None
    finally:
        process.close(terminate=True)


def test_core_launch_transfer_interrupt_closes_registered_process_and_preserves_primary(
    tmp_path, monkeypatch
) -> None:
    primary = KeyboardInterrupt("candidate-transfer")
    secondary = SystemExit("cleanup-interrupt")
    closed = []
    evidence = []

    class Process:
        def close(self, *, terminate):
            closed.append(terminate)
            for item in evidence:
                item.close()
            raise secondary

    process = Process()

    class Api:
        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            if owned is not None:
                item = diagnostics._WindowsApi._prepare_runtime_evidence(
                    self, _executable, expected_images, _cwd, _environment, None
                )
                assert item is not None and item.root.parent == _cwd
                evidence.append(item)
                with monkeypatch.context() as launch_environment:
                    launch_environment.setenv(application.ROOT_ENV, _environment[application.ROOT_ENV])
                    root = application._root()
                    assert root != _cwd and root.parent == _cwd.parent
                scratch = _cwd.parent / "temporary files"
                assert scratch.is_dir()
                assert all(_environment[key] == str(scratch) for key in ("TEMP", "TMP", "TMPDIR"))
                assert expected_images == (_executable, _executable.with_name("metroliza_application.exe"))
                owned.append(process)
            return process

    api = Api()
    with pytest.raises(KeyboardInterrupt) as legacy:
        _interrupt_after_launch_before_store(
            _legacy_unowned_launch.__code__, primary, lambda: _legacy_unowned_launch(api)
        )
    assert legacy.value is primary
    assert closed == []

    monkeypatch.setattr(driver, "_stage_known_fixtures", lambda _fixtures, private: private)
    monkeypatch.setattr(driver, "_stage_ocr_fixture", lambda _checkout, private: private / "ocr.pdf")
    monkeypatch.setattr(
        owned_probe, "OwnedProcessProbe",
        lambda *_args: SimpleNamespace(phase="startup", emit=lambda: None),
    )
    diag = SimpleNamespace(
        _relocate_package=lambda _artifact, private, _deadline: private / "relocated",
        _sanitized_environment=lambda *args: diagnostics._sanitized_environment(
            *args, inherited={"SYSTEMROOT": str(tmp_path / "Windows")}
        ),
        _WindowsApi=lambda: api,
        _close_owned_processes=diagnostics._close_owned_processes,
    )
    args = SimpleNamespace(source_checkout=tmp_path, expected_source_sha="1" * 40, oracle=tmp_path / "oracle.json", dpi_scale="1.0", native_mode="default")
    private = tmp_path / "private"
    private.mkdir()

    with pytest.raises(KeyboardInterrupt) as current:
        _interrupt_after_launch_before_store(
            driver._run_private_core.__code__, primary,
            lambda: driver._run_private_core(
                private, args=args, diag=diag, artifact=tmp_path,
                fixtures=tmp_path, output=tmp_path / "output",
                deadline=time.monotonic() + 1, before="before",
            ),
        )

    assert current.value is primary
    assert closed == [True]
    assert len(evidence) == 1 and not evidence[0].root.exists()


def test_candidate_services_wait_for_host_startup_ack(tmp_path, monkeypatch):
    import json
    import threading
    from metroliza.shared import diagnostic_runtime_audit as audit
    from metroliza.app import windows_candidate_native_check as native

    root = tmp_path / "core"
    root.mkdir()
    journal = tmp_path / "audit"
    journal.mkdir()
    nonce = "a" * 32
    audit._write(journal, "installed.json", {"schema_version": 1, "nonce": nonce, "installed": True})
    for gate in application.GATES:
        monkeypatch.setenv(gate, "1")
    monkeypatch.setenv(application.ROOT_ENV, str(root))
    monkeypatch.setenv(audit.GATE, "1")
    monkeypatch.setenv(audit.ROOT, str(journal))
    monkeypatch.setenv(audit.NONCE, nonce)
    monkeypatch.setattr(application, "_fixture_dir", lambda: tmp_path)
    monkeypatch.setattr(application, "_ocr_fixture", lambda: tmp_path / "public.pdf")
    evidence = object.__new__(owned_probe.RuntimeEvidence)
    evidence.root = journal
    evidence.root_identity = evidence._identity()
    evidence.probe = SimpleNamespace(phase="startup")
    evidence.failure_factory = lambda: ValueError("synthetic")
    started = []
    observed = []

    def services(_callback):
        started.append(evidence.probe.phase)
        assert evidence.probe.phase == "running"
        return {}

    def host():
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            marker = root / "core-startup.json"
            if marker.exists():
                assert json.loads(marker.read_bytes()) == {"schema_version": 1, "scenario": "core", "stage": "startup_ready"}
                time.sleep(0.05)
                observed.append(list(started))
                evidence.ready()
                return
            time.sleep(0.005)

    monkeypatch.setattr(native, "run_with_native_mode", services)
    observer = threading.Thread(target=host)
    observer.start()
    try:
        result = application.run_qualification()
    finally:
        observer.join(timeout=2)
    assert not observer.is_alive()
    assert observed == [[]]
    assert started == ["running"]
    assert result == 0


@pytest.mark.parametrize("fault", ["missing", "nonempty_schema", "boolean", "directory", "valid", "host_failure"])
def test_candidate_host_ack_requires_valid_startup_and_successful_phase_change(tmp_path, fault):
    import json

    calls = []
    marker = tmp_path / "core-startup.json"
    payload = {"schema_version": 1, "scenario": "core", "stage": "startup_ready"}
    if fault == "nonempty_schema":
        payload["unrecognized"] = True
    if fault == "boolean":
        payload["schema_version"] = True
    if fault == "directory":
        marker.mkdir()
    elif fault != "missing":
        marker.write_text(json.dumps(payload))

    def ready():
        calls.append("ready")
        if fault == "host_failure":
            raise diagnostics.QualificationFailure("output_failed")

    process = SimpleNamespace(mark_runtime_ready=ready)
    if fault == "missing":
        assert not driver._observe_core_startup(tmp_path, process, False)
        assert calls == []
    elif fault == "valid":
        assert driver._observe_core_startup(tmp_path, process, False)
        assert driver._observe_core_startup(tmp_path, process, True)
        assert calls == ["ready"]
    else:
        with pytest.raises((driver.CandidateFailure, diagnostics.QualificationFailure)):
            driver._observe_core_startup(tmp_path, process, False)
        assert calls == (["ready"] if fault == "host_failure" else [])

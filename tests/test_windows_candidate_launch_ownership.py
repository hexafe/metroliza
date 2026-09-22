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

    class Process:
        def close(self, *, terminate):
            closed.append(terminate)
            raise secondary

    process = Process()

    class Api:
        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            if owned is not None:
                scratch = _cwd / "temporary files"
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
    diag = SimpleNamespace(
        _relocate_package=lambda _artifact, private, _deadline: private / "relocated",
        _sanitized_environment=lambda *_args: {},
        _WindowsApi=lambda: api,
        _close_owned_processes=diagnostics._close_owned_processes,
    )
    args = SimpleNamespace(source_checkout=tmp_path, expected_source_sha="1" * 40, oracle=tmp_path / "oracle.json", dpi_scale="1.0")
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

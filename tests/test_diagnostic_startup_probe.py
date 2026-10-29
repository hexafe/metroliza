from __future__ import annotations

import builtins
import atexit
import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from metroliza.shared import diagnostic_startup_probe as probe
from scripts import qualify_windows_diagnostics as qualifier


@pytest.fixture(autouse=True)
def isolated_fatal_probe():
    """Restore pytest's handler before closing any sink opened by an entry."""
    import faulthandler
    from metroliza.shared import diagnostic_fatal_probe as fatal

    previous_enabled = faulthandler.is_enabled()
    previous_stream = fatal._fatal_stream
    enable, disable = faulthandler.enable, faulthandler.disable
    try:
        yield
    finally:
        stream = fatal._fatal_stream
        if stream is not previous_stream:
            if previous_enabled:
                enable(file=sys.__stderr__, all_threads=True)
            else:
                disable()
            fatal._fatal_stream = previous_stream
            if type(stream) is int:
                os.close(stream)
            elif stream is not None:
                stream.close()
        assert faulthandler.is_enabled() is previous_enabled
        assert fatal._fatal_stream is previous_stream


@pytest.fixture(autouse=True)
def atexit_callbacks(monkeypatch):
    callbacks = []
    monkeypatch.setattr(atexit, "register", lambda *args: callbacks.append(args))
    return callbacks


@pytest.fixture
def probe_root(tmp_path, monkeypatch):
    (tmp_path / probe.PROBE_DIRECTORY).mkdir()
    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", "normal")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_STARTUP_PROBE", "1")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("name,value", [
    ("METROLIZA_STARTUP_SMOKE", "0"),
    ("METROLIZA_DIAGNOSTIC_QUALIFICATION", "idle"),
    ("METROLIZA_DIAGNOSTIC_STARTUP_PROBE", "0"),
])
def test_probe_requires_all_synthetic_opt_ins(probe_root, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    probe.mark("launcher_entry")
    assert qualifier._startup_phases(probe_root) == ()


def test_core_probe_uses_separate_private_root_without_diagnostic_scenario(probe_root, monkeypatch):
    monkeypatch.delenv("METROLIZA_DIAGNOSTIC_QUALIFICATION")
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "1")
    probe.mark("supervision_returned")
    assert qualifier._startup_phases(probe_root) == ("supervision_returned",)
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "0")
    probe.mark("persist_entered")
    assert qualifier._startup_phases(probe_root) == ("supervision_returned",)


@pytest.mark.parametrize("name", ["METROLIZA_STARTUP_SMOKE", "METROLIZA_DIAGNOSTIC_STARTUP_PROBE"])
@pytest.mark.parametrize("value", [None, "0", "true"])
def test_core_probe_requires_smoke_and_probe_gates(probe_root, monkeypatch, name, value):
    monkeypatch.delenv("METROLIZA_DIAGNOSTIC_QUALIFICATION")
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "1")
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    probe.mark("child_entry")
    assert qualifier._startup_phases(probe_root) == ()


@pytest.mark.parametrize("entry_name,phase", [
    ("metroliza_package_entry.py", "child_atexit_reached"),
    ("metroliza_supervisor_entry.py", "launcher_atexit_reached"),
])
@pytest.mark.parametrize("enabled", [False, True])
def test_entry_atexit_registration_is_gated_and_marker_is_deferred(
    probe_root, monkeypatch, atexit_callbacks, entry_name, phase, enabled,
):
    from types import SimpleNamespace

    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_STARTUP_PROBE", "1" if enabled else "0")
    monkeypatch.setitem(sys.modules, "metroliza.shared.diagnostic_transport", SimpleNamespace(
        attach_child_recorder=lambda: None, supervised_mode_requested=lambda: False,
    ))
    monkeypatch.setitem(sys.modules, "metroliza.app.bootstrap", SimpleNamespace(run_application=lambda: 7))
    monkeypatch.setitem(sys.modules, "metroliza.app.diagnostic_launcher", SimpleNamespace(main=lambda: 7))
    entry = Path(probe.__file__).resolve().parents[3] / "packaging" / entry_name
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(entry), run_name="__main__")
    assert caught.value.code == 7
    assert phase not in qualifier._startup_phases(probe_root)
    callbacks = [args for args in atexit_callbacks if args == (probe.mark, phase)]
    assert len(callbacks) == int(enabled)
    for callback, name in callbacks:
        callback(name)
    assert (phase in qualifier._startup_phases(probe_root)) is enabled


@pytest.mark.parametrize("phase", [
    "child_atexit_reached", "launcher_atexit_reached", "child_wait_all_ones", "launcher_exit_all_ones",
])
def test_finalization_and_all_ones_phases_pass_shared_host_validation(probe_root, phase):
    from scripts import qualify_windows_candidate_core as core

    probe.mark(phase)
    assert qualifier._startup_phases(probe_root) == (phase,)
    assert core._closed_phases([phase]) == [phase]
    core._validate_process_phases({
        scenario: {"observed_process": role, "observed_exit_code": 0, "startup_phases": [phase]}
        for scenario, role in (("core", "requested_launcher_handle"), ("reopen", "fresh_reopen_launcher_handle"))
    })


@pytest.mark.parametrize("entry_name,phase", [
    ("metroliza_package_entry.py", "child_atexit_reached"),
    ("metroliza_supervisor_entry.py", "launcher_atexit_reached"),
])
def test_actual_interpreter_finalization_creates_entry_marker(probe_root, entry_name, phase):
    root = Path(probe.__file__).resolve().parents[3]
    program = '''
import runpy, sys
from types import SimpleNamespace
from metroliza.shared import diagnostic_startup_probe as probe
from pathlib import Path
sys.modules["metroliza.shared.diagnostic_transport"] = SimpleNamespace(
    attach_child_recorder=lambda: None, supervised_mode_requested=lambda: False)
sys.modules["metroliza.app.bootstrap"] = SimpleNamespace(run_application=lambda: 7)
sys.modules["metroliza.app.diagnostic_launcher"] = SimpleNamespace(main=lambda: 7)
try:
    runpy.run_path(sys.argv[1], run_name="__main__")
except SystemExit as error:
    assert error.code == 7
assert not (Path(sys.argv[2]) / probe.PROBE_DIRECTORY / sys.argv[3]).exists()
'''
    completed = subprocess.run(
        [sys.executable, "-c", program, str(root / "packaging" / entry_name), str(probe_root), phase],
        cwd=probe_root, env=dict(os.environ, PYTHONPATH=str(root / "src")),
        capture_output=True, timeout=15, check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert phase in qualifier._startup_phases(probe_root)


def test_probe_records_only_fixed_empty_markers_without_overwriting(probe_root):
    probe.mark("launcher_entry")
    marker = probe_root / probe.PROBE_DIRECTORY / "launcher_entry"
    marker.write_bytes(b"preserve-existing")
    probe.mark("launcher_entry")
    probe.mark("../../private report")
    probe.mark([])
    assert marker.read_bytes() == b"preserve-existing"
    assert tuple(p.name for p in marker.parent.iterdir()) == ("launcher_entry",)
    assert qualifier._startup_phases(probe_root) == ()


def test_probe_does_not_follow_marker_symlink(probe_root, tmp_path):
    target = tmp_path / "untouched"
    target.write_bytes(b"last complete output")
    marker = probe_root / probe.PROBE_DIRECTORY / "launcher_entry"
    try:
        marker.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    probe.mark("launcher_entry")
    assert target.read_bytes() == b"last complete output"
    assert qualifier._startup_phases(probe_root) == ()


def test_probe_never_formats_exception_or_reads_arbitrary_attributes(probe_root):
    class SensitiveError(Exception):
        def __str__(self):
            raise AssertionError("must not format")

        def __getattribute__(self, name):
            raise AssertionError("must not inspect")

    probe.mark_error(SensitiveError("synthetic-private-sentinel"))
    assert qualifier._startup_phases(probe_root) == ("error_other",)


def test_phase_reader_rejects_replaced_directory(probe_root, tmp_path):
    directory = probe_root / probe.PROBE_DIRECTORY
    directory.rmdir()
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    (replacement / "launcher_entry").touch()
    try:
        directory.symlink_to(replacement, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    assert qualifier._startup_phases(probe_root) == ()


@pytest.mark.parametrize("failure", [None, ImportError, RuntimeError])
def test_actual_launcher_entry_preserves_result_and_classifies_boundary(
    probe_root, monkeypatch, failure
):
    entry = Path(__file__).resolve().parents[1] / "packaging/metroliza_supervisor_entry.py"
    module = ModuleType("metroliza.app.diagnostic_launcher")
    error = failure("synthetic-private-sentinel") if failure else None

    def main():
        if failure is RuntimeError:
            raise error
        return 7

    module.main = main
    monkeypatch.setitem(sys.modules, module.__name__, module)
    original_import = builtins.__import__

    def importing(name, *args, **kwargs):
        if failure is ImportError and name == module.__name__:
            raise error
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    with pytest.raises(failure or SystemExit) as caught:
        runpy.run_path(str(entry), run_name="__main__")
    if error is not None:
        assert caught.value is error
    else:
        assert caught.value.code == 7
    phases = qualifier._startup_phases(probe_root)
    assert "launcher_entry" in phases
    assert ("launcher_import_failed" in phases) is (failure is ImportError)
    assert ("launcher_main_failed" in phases) is (failure is RuntimeError)
    assert all(p.stat().st_size == 0 for p in (probe_root / probe.PROBE_DIRECTORY).iterdir())


@pytest.mark.parametrize("phases", [
    ["private sentinel"], ["launcher_entry", "launcher_entry"], [True], "launcher_entry",
])
def test_public_failure_rejects_unclosed_phase_evidence(phases):
    assert not qualifier._valid_failure_detail({
        "stage": "supervised_normal_1", "reason": "process_exited_before_startup",
        "startup_phases": phases,
    })


def test_public_failure_preserves_empty_unknown_observation():
    detail = qualifier._failure_detail(
        "supervised_normal_1", "process_exited_before_startup", None, 1, None, ()
    )
    assert detail["startup_phases"] == []
    assert qualifier._valid_failure_detail(detail)


@pytest.mark.parametrize("status,notice", [
    ("saved", "notice_not_required"),
    ("publish_incomplete", "notice_suppressed"),
    ("io_failed", "notice_suppressed"),
])
def test_concurrent_launcher_records_final_delivery_and_preserves_child_exit(
    probe_root, monkeypatch, status, notice
):
    from types import SimpleNamespace
    from metroliza.app import diagnostic_launcher as launcher
    from metroliza.shared.diagnostic_store import StoreStatus

    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", "concurrent")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(launcher, "IncidentStore", lambda: None)
    delivery = launcher.LaunchDelivery(SimpleNamespace(exit_code=9), StoreStatus(status))
    monkeypatch.setattr(launcher, "run_with_store", lambda *args, **kwargs: delivery)
    assert launcher.main() == 9
    phases = qualifier._startup_phases(probe_root)
    assert [p for p in phases if p.startswith("storage_")] == ["storage_" + status]
    assert [p for p in phases if p.startswith("notice_")] == [notice]


def test_concurrent_probe_marker_failure_does_not_change_launcher_exit(probe_root, monkeypatch):
    from types import SimpleNamespace
    from metroliza.app import diagnostic_launcher as launcher
    from metroliza.shared.diagnostic_store import StoreStatus

    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", "concurrent")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(launcher, "IncidentStore", lambda: None)
    monkeypatch.setattr(launcher, "run_with_store", lambda *args, **kwargs: launcher.LaunchDelivery(
        SimpleNamespace(exit_code=9), StoreStatus.PUBLISH_INCOMPLETE
    ))
    def denied(*args, **kwargs):
        raise PermissionError("PRIVATE_SENTINEL")
    monkeypatch.setattr(Path, "open", denied)
    assert launcher.main() == 9
    assert qualifier._startup_phases(probe_root) == ()


@pytest.mark.parametrize("phases", [(), ("storage_private",), ("storage_saved", "storage_io_failed")])
def test_absent_unknown_or_multiple_storage_markers_are_not_a_status(phases):
    assert qualifier._launcher_storage_status(phases) is None


@pytest.mark.parametrize("phases", [
    [["private sentinel"], []], [["storage_saved", "storage_saved"], []],
    [[True], []], [[], [], []], "private sentinel",
])
def test_public_failure_rejects_unclosed_concurrent_phase_evidence(phases):
    assert not qualifier._valid_failure_detail({
        "stage": "concurrent_1", "reason": "launcher_storage_not_saved", "concurrent_phases": phases,
    })


def test_public_concurrent_failure_preserves_separate_empty_and_observed_roots():
    detail = qualifier._failure_detail(
        "concurrent_2", "launcher_storage_not_saved", None, None, None,
        concurrent_phases=((), ("storage_publish_incomplete", "notice_suppressed")),
    )
    assert detail["concurrent_phases"] == [[], ["storage_publish_incomplete", "notice_suppressed"]]
    assert qualifier._valid_failure_detail(detail)
    detail["stage"] = "normal"
    assert not qualifier._valid_failure_detail(detail)

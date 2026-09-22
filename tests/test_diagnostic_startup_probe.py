from __future__ import annotations

import builtins
import runpy
import sys
from pathlib import Path
from types import ModuleType

import pytest

from metroliza.shared import diagnostic_startup_probe as probe
from scripts import qualify_windows_diagnostics as qualifier


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

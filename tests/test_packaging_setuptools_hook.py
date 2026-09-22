from __future__ import annotations

import ast
import builtins
import hashlib
import importlib.metadata
import importlib.util
from pathlib import Path
import runpy
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK_ROOT = ROOT / "packaging/hooks/windows"
HOOK = HOOK_ROOT / "rthooks/metroliza_rth_setuptools.py"
ORIGINAL = ROOT / "tests/fixtures/packaging/pyi_rth_setuptools_6_22_3.py"


def _common():
    spec = importlib.util.spec_from_file_location("setuptools_hook_packaging", ROOT / "packaging/pyinstaller_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("version", ["59.9.0", "60.0.0", "65.5.0", "80.1.0"])
@pytest.mark.parametrize("override", [None, "local", "stdlib", "other", "LOCAL", ""])
def test_hook_preserves_shim_policy_without_importing_setuptools(monkeypatch, version, override):
    calls = []
    monkeypatch.setattr(importlib.metadata, "version", lambda name: version if name == "setuptools" else pytest.fail())
    monkeypatch.setitem(sys.modules, "_distutils_hack", types.SimpleNamespace(add_shim=lambda: calls.append("shim")))
    if override is None:
        monkeypatch.delenv("SETUPTOOLS_USE_DISTUTILS", raising=False)
    else:
        monkeypatch.setenv("SETUPTOOLS_USE_DISTUTILS", override)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "setuptools" or name.startswith("setuptools."):
            pytest.fail("runtime hook imported compiler integrations")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    runpy.run_path(str(HOOK))
    enabled = override == "local" or override is None and int(version.split(".")[0]) >= 60
    assert calls == (["shim"] if enabled else [])


@pytest.mark.parametrize("failure", ["missing_metadata", "invalid_major", "shim_failure"])
def test_hook_preserves_optional_failure_boundary(monkeypatch, failure):
    def version(_):
        if failure == "missing_metadata":
            raise importlib.metadata.PackageNotFoundError("setuptools")
        return "not-a-version" if failure == "invalid_major" else "65.5.0"

    def add_shim():
        raise RuntimeError("synthetic shim failure")

    monkeypatch.setattr(importlib.metadata, "version", version)
    monkeypatch.setitem(sys.modules, "_distutils_hack", types.SimpleNamespace(add_shim=add_shim))
    monkeypatch.setenv("SETUPTOOLS_USE_DISTUTILS", "local")
    runpy.run_path(str(HOOK))


def test_upstream_causal_control_is_exact_pyinstaller_6_22_3_source():
    assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == "aeb0dc75b5064ae52751e5c3451fc76a5c4cd7e821b4989614880ebce20830fa"
    assert ast.literal_eval((HOOK_ROOT / "rthooks.dat").read_text()) == {"setuptools": [HOOK.name]}


def test_analysis_requires_only_exact_replacement_source(tmp_path):
    module = _common()
    replacement = (HOOK.stem, str(HOOK), "PYSOURCE")
    module.validate_setuptools_runtime_hook([replacement, ("entry", "entry.py", "PYSOURCE")], HOOK_ROOT)
    wrong = (HOOK.stem, str(tmp_path / HOOK.name), "PYSOURCE")
    upstream = ("pyi_rth_setuptools", str(tmp_path / "pyi_rth_setuptools.py"), "PYSOURCE")
    for scripts in ([], [wrong], [upstream], [replacement, upstream], [replacement, replacement]):
        with pytest.raises(RuntimeError, match="hook selection"):
            module.validate_setuptools_runtime_hook(scripts, HOOK_ROOT)


def test_metadata_is_bound_to_analyzed_setuptools_module(monkeypatch, tmp_path):
    module = _common()
    source = tmp_path / "setuptools/__init__.py"
    source.parent.mkdir()
    source.touch()
    package = types.SimpleNamespace(metadata={"Name": "setuptools"}, version="65.5.0", locate_file=lambda _: source)
    monkeypatch.setattr(importlib.metadata, "distribution", lambda _: package)
    monkeypatch.setattr(importlib.util, "find_spec", lambda _: types.SimpleNamespace(origin=str(source)))
    marker = [("setuptools-65.5.0.dist-info", ".")]
    monkeypatch.setattr(module, "copy_metadata", lambda _: marker)
    assert module.collect_setuptools_hook_metadata() == marker
    other = tmp_path / "wrong.py"
    other.touch()
    monkeypatch.setattr(importlib.util, "find_spec", lambda _: types.SimpleNamespace(origin=str(other)))
    with pytest.raises(RuntimeError, match="metadata disagree"):
        module.collect_setuptools_hook_metadata()


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows shell causal control")
@pytest.mark.parametrize("mode", ["original", "corrected"])
def test_native_hook_version_shell_counterfactual(tmp_path, monkeypatch, mode):
    import ctypes
    import subprocess
    import time
    from scripts import qualify_windows_diagnostics as qualification

    api = qualification._WindowsApi()
    original_advapi = api.advapi
    executable = Path(sys.executable).resolve().with_name("pythonw.exe")
    assert qualification._pe_subsystem(executable) == 2
    system_buffer = ctypes.create_unicode_buffer(32768)
    copied = api.kernel.GetSystemDirectoryW(system_buffer, len(system_buffer))
    assert 0 < copied < len(system_buffer)
    system = Path(system_buffer.value)
    api.enable_owned_probe(tmp_path)
    api._owned_probe.images = (("package_application", executable),
                               ("system_cmd", system / "cmd.exe"),
                               ("system_conhost", system / "conhost.exe"))
    command = subprocess.list2cmdline([str(executable), str(ROOT / "tests/fixtures/windows_setuptools_hook_control.py")])

    class FixedHookControl:
        def __getattr__(self, name):
            return getattr(original_advapi, name)

        def CreateProcessAsUserW(self, *arguments):
            values = list(arguments)
            values[2] = ctypes.create_unicode_buffer(command)
            return original_advapi.CreateProcessAsUserW(*values)

        def CreateProcessWithTokenW(self, *arguments):
            values = list(arguments)
            values[3] = ctypes.create_unicode_buffer(command)
            return original_advapi.CreateProcessWithTokenW(*values)

    monkeypatch.setattr(api, "advapi", FixedHookControl())
    environment = qualification._sanitized_environment(tmp_path, tmp_path, tmp_path / "state", "normal")
    environment.update(METROLIZA_TEST_SETUPTOOLS_HOOK=mode, SETUPTOOLS_USE_DISTUTILS="local",
                       PYTHONDONTWRITEBYTECODE="1")
    environment.pop("METROLIZA_DIAGNOSTIC_QUALIFICATION", None)
    owned = []
    complete = False
    try:
        process = api.launch(executable, environment, tmp_path, owned=owned,
                             expected_images=(executable, system / "cmd.exe", system / "conhost.exe"))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            process.observe()
            if process.poll() is not None and process.active_processes() == 0:
                break
            time.sleep(0.005)
        assert process.poll() == 0 and process.active_processes() == 0
        receipt = qualification._bounded_json(tmp_path / "hook-control.json", 4096)
        assigned = process._assigned_processes
        topology = api._owned_probe.receipt()
        complete = True
    finally:
        qualification._close_owned_processes(owned, terminate=not complete)
    count = 1 if mode == "original" else 0
    assert receipt == {"status": "passed", "shim": True, "setuptools_65_5": True, "audit": {
        "cmd_ver": count, "platform_ver": count, "setuptools_windows_support": count, "other": 0,
    }}
    expected_roles = ["package_application"] + (["system_cmd", "system_conhost"] if mode == "original" else [])
    assert assigned == len(expected_roles)
    assert sorted(member["role"] for member in topology["members"]) == sorted(expected_roles)
    assert all(member["identity"] == "fixed_file_verified" for member in topology["members"])
    assert topology["job_empty"] is True
    assert topology["observation_unavailable"] is False
    assert topology["overflow"] is False and topology["unobserved"] == 0
    if mode == "original":
        ordinals = {member["role"]: index for index, member in enumerate(topology["members"])}
        assert topology["members"][ordinals["system_cmd"]]["parent_ordinal_advisory"] == ordinals["package_application"]
        assert topology["members"][ordinals["system_conhost"]]["parent_ordinal_advisory"] == ordinals["system_cmd"]

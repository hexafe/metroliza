"""The one visible EXE must retain the existing verified supervisor boundary."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from metroliza.app.version import VERSION_LABEL
from metroliza.shared.diagnostic_package import COMPONENTS
from scripts.build_diagnostic_manifest import write_supervision_manifest

ENTRY = Path(__file__).resolve().parents[1] / "packaging/metroliza_portable_entry.py"
spec = importlib.util.spec_from_file_location("metroliza_portable_entry", ENTRY)
assert spec and spec.loader
portable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)


@pytest.fixture
def payload(tmp_path):
    root = tmp_path / "payload ze spacjami"
    for name in COMPONENTS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-component")
    (root / COMPONENTS[-1]).write_text(json.dumps({"git_sha": "a" * 40}), encoding="utf-8")
    write_supervision_manifest(root)
    launcher = root / portable.LAUNCHER_NAME
    launcher.write_bytes(b"synthetic-supervisor")
    (root / portable.SIDECAR_NAME).write_text(json.dumps({
        "git_sha": "a" * 40, "release_label": VERSION_LABEL, "dirty": False,
        "artifact": {"name": launcher.name, "size_bytes": launcher.stat().st_size,
                     "sha256": sha256(launcher.read_bytes()).hexdigest()},
    }), encoding="utf-8")
    return root


def test_portable_entry_launches_only_verified_supervisor_and_waits(payload, monkeypatch):
    calls = []

    class Child:
        def wait(self):
            calls.append("wait")
            return 7

    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return Child()

    monkeypatch.setattr(portable.subprocess, "Popen", spawn)
    monkeypatch.setenv("PYTHONPATH", "untrusted")
    monkeypatch.setenv("PYTHONHOME", "untrusted")
    assert portable._launch(payload, ["--example"]) == 7
    argv, options = calls[0]
    assert argv == [str(payload / "metroliza.exe"), "--example"]
    assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "PYTHONPATH" not in options["env"] and "PYTHONHOME" not in options["env"]
    assert options["stdout"] == options["stderr"] == subprocess.DEVNULL
    assert calls[1] == "wait"


@pytest.mark.parametrize("damage", ["launcher", "sidecar", "application", "release"])
def test_portable_entry_refuses_mismatched_payload(payload, monkeypatch, damage):
    if damage == "launcher":
        (payload / portable.LAUNCHER_NAME).write_bytes(b"tampered")
    elif damage == "sidecar":
        (payload / portable.SIDECAR_NAME).unlink()
    elif damage == "application":
        (payload / "metroliza_application.exe").write_bytes(b"tampered")
    else:
        sidecar = payload / portable.SIDECAR_NAME
        value = json.loads(sidecar.read_text())
        value["release_label"] = "stale"
        sidecar.write_text(json.dumps(value))
    monkeypatch.setattr(portable.subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawned"))
    assert portable._launch(payload, []) is None


def test_portable_entry_does_not_import_gui_before_supervisor():
    code = (
        "import runpy,sys; runpy.run_path(sys.argv[1], run_name='import_probe'); "
        "assert not any(n.split('.')[0] in {'PyQt6','numpy','rapidocr','cv2'} for n in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code, str(ENTRY)],
                            capture_output=True, text=True, check=False,
                            env=dict(os.environ, PYTHONPATH=str(ENTRY.parents[1] / "src")))
    assert result.returncode == 0, result.stderr

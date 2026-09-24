import json
from pathlib import Path

import pytest

from metroliza.shared.diagnostic_package import COMPONENTS, MANIFEST_NAME, inspect_package
from scripts.build_diagnostic_manifest import write_supervision_manifest


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "Metroliza próba ze spacjami"
    for name in COMPONENTS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-component")
    (root / COMPONENTS[-1]).write_text(json.dumps({"git_sha": "a" * 40}), encoding="utf-8")
    write_supervision_manifest(root)
    return root


def test_exact_component_manifest_verifies_without_path_lookup(package):
    identity = inspect_package(package)
    assert identity.valid
    assert identity.reason == "verified"
    assert identity.git_sha == "a" * 40


@pytest.mark.parametrize("component", COMPONENTS)
def test_mixed_or_missing_child_runtime_fails_closed(package, component):
    path = package / component
    path.write_bytes(b"different-runtime")
    assert inspect_package(package).reason == "component_mismatch"
    path.unlink()
    assert not inspect_package(package).valid


def test_manifest_cannot_select_an_arbitrary_executable(package):
    path = package / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["components"]["../another.exe"] = "a" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert not inspect_package(package).valid


def test_manifest_cannot_claim_a_different_embedded_commit(package):
    path = package / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["git_sha"] = "b" * 40
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert inspect_package(package).reason == "provenance_mismatch"
    assert inspect_package(package).git_sha == "unknown"


def test_minimal_entry_precedes_application_imports():
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    code = (
        "import runpy,sys; runpy.run_path(sys.argv[1], run_name='import_probe'); "
        "assert not any(n.split('.')[0] in {'PyQt6','numpy','rapidocr','cv2'} for n in sys.modules); "
        "assert 'metroliza.app.bootstrap' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code, str(root / "packaging/metroliza_supervisor_entry.py")],
                   check=True, capture_output=True,
                   env=dict(os.environ, PYTHONPATH=str(root / "src")))


@pytest.mark.parametrize("entry", ["metroliza_supervisor_entry.py", "metroliza_package_entry.py"])
@pytest.mark.parametrize("frozen", [False, True], ids=["source", "frozen-flag"])
def test_frozen_entry_preserves_loader_import_paths(tmp_path, entry, frozen):
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    entry_path = root / "packaging" / entry
    if frozen:
        # A frozen entry resides beside the extracted bundle, independently of
        # the source package used here to simulate the frozen import loader.
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        copied = bundle / entry
        copied.write_bytes(entry_path.read_bytes())
        entry_path = copied
    code = """
import importlib, os, runpy, sys
sys.frozen = sys.argv[2] == '1'
if sys.frozen:
    sys.path = [path for path in sys.path if path not in ('', os.getcwd())]
before = tuple(sys.path)
# This checks the frozen loader's paths, not the native OCR installation.
# The package-entry preload has its own order test and packaged Windows gate.
if sys.frozen and sys.argv[1].endswith('metroliza_package_entry.py'):
    original_import = importlib.import_module
    def import_without_native_ocr(name, package=None):
        if name == 'onnxruntime':
            return object()
        return original_import(name, package)
    importlib.import_module = import_without_native_ocr
runpy.run_path(sys.argv[1], run_name='import_probe')
if sys.frozen:
    assert tuple(sys.path) == before, 'frozen_entry_changed_import_path'
else:
    assert sys.path[0] == sys.argv[3], 'source_entry_missing_owned_source_root'
"""
    subprocess.run(
        [sys.executable, "-c", code, str(entry_path),
         "1" if frozen else "0", str(root / "src")],
        check=True, capture_output=True,
        env=dict(os.environ, PYTHONPATH=str(root / "src")),
    )

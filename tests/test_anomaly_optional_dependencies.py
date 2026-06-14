from __future__ import annotations

import builtins
import importlib
from pathlib import Path
from types import ModuleType

import pytest


MODULE_NAME = "metroliza.industrial.anomaly.optional_dependencies"


def _reload_optional_dependencies():
    import sys

    sys.modules.pop(MODULE_NAME, None)
    return importlib.import_module(MODULE_NAME)


def _requirement_entries(path: str) -> list[str]:
    return [
        line.split("#", maxsplit=1)[0].strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.split("#", maxsplit=1)[0].strip()
    ]


def test_anomaly_requirements_are_optional_and_not_runtime_dependencies():
    optional_entries = _requirement_entries("requirements-anomaly.txt")
    runtime_entries = _requirement_entries("requirements.txt")

    assert any(entry.startswith("scikit-learn") for entry in optional_entries)
    assert any(entry.startswith("river") for entry in optional_entries)
    assert not any(entry.startswith("scikit-learn") for entry in runtime_entries)
    assert not any(entry.startswith("river") for entry in runtime_entries)


def test_module_import_does_not_import_optional_ml_packages(monkeypatch):
    original_import = builtins.__import__
    blocked_roots = {"sklearn", "river"}

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.split(".", 1)[0] in blocked_roots:
            raise AssertionError(f"optional dependency imported at module load: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = _reload_optional_dependencies()

    assert module.ANOMALY_REQUIREMENTS_FILE == "requirements-anomaly.txt"


def test_import_sklearn_loads_package_lazily(monkeypatch):
    module = _reload_optional_dependencies()
    sklearn = ModuleType("sklearn")
    imported: list[str] = []

    def fake_import(name: str):
        imported.append(name)
        return sklearn

    monkeypatch.setattr(module.importlib, "import_module", fake_import)

    assert module.import_sklearn() is sklearn
    assert imported == ["sklearn"]


def test_import_river_loads_package_lazily(monkeypatch):
    module = _reload_optional_dependencies()
    river = ModuleType("river")
    imported: list[str] = []

    def fake_import(name: str):
        imported.append(name)
        return river

    monkeypatch.setattr(module.importlib, "import_module", fake_import)

    assert module.import_river() is river
    assert imported == ["river"]


def test_missing_optional_dependency_error_names_install_command(monkeypatch):
    module = _reload_optional_dependencies()

    def missing_import(name: str):
        raise ModuleNotFoundError(
            "No module named 'fake_missing_ml_backend'",
            name="fake_missing_ml_backend",
        )

    monkeypatch.setattr(module.importlib, "import_module", missing_import)

    with pytest.raises(module.OptionalAnomalyDependencyError) as excinfo:
        module.import_optional_dependency(
            "fake_missing_ml_backend",
            package_name="fake-ml-backend",
            purpose="fake detector coverage",
        )

    message = str(excinfo.value)
    assert "fake-ml-backend" in message
    assert "fake detector coverage" in message
    assert "python -m pip install -r requirements-anomaly.txt" in message
    assert "fake_missing_ml_backend" in message


def test_real_missing_module_uses_optional_dependency_error():
    module = _reload_optional_dependencies()

    with pytest.raises(module.OptionalAnomalyDependencyError) as excinfo:
        module.import_optional_dependency(
            "_metroliza_missing_optional_anomaly_backend_",
            package_name="metroliza-missing-anomaly-backend",
        )

    assert "metroliza-missing-anomaly-backend" in str(excinfo.value)

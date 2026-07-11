from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from metroliza.app import ui_entrypoint


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PACKAGE = REPO_ROOT / "src" / "metroliza" / "app"


def _static_metroliza_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return {name for name in imported if name.startswith("metroliza.")}


def test_app_package_has_no_static_ui_dependency() -> None:
    violations = {
        path.relative_to(REPO_ROOT).as_posix(): sorted(
            name for name in _static_metroliza_imports(path) if name.startswith("metroliza.ui")
        )
        for path in sorted(APP_PACKAGE.glob("*.py"))
    }
    violations = {path: names for path, names in violations.items() if names}

    assert violations == {}


def test_bootstrap_cold_import_does_not_load_ui_package() -> None:
    script = """
import json
import sys
import metroliza.app.bootstrap
print(json.dumps(sorted(name for name in sys.modules if name == "metroliza.ui" or name.startswith("metroliza.ui."))))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": f"{REPO_ROOT / 'src'}{os.pathsep}{REPO_ROOT}"},
        text=True,
        capture_output=True,
    )

    assert json.loads(result.stdout) == []


def test_main_window_factory_is_resolved_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    imported: list[str] = []

    class FakeMainWindow:
        pass

    def import_module(name: str):
        imported.append(name)
        return SimpleNamespace(MainWindow=FakeMainWindow)

    monkeypatch.setattr(ui_entrypoint, "import_module", import_module)

    factory = ui_entrypoint.load_main_window_factory()

    assert factory is FakeMainWindow
    assert imported == ["metroliza.ui.main_window"]


def test_main_window_factory_rejects_invalid_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ui_entrypoint,
        "import_module",
        lambda _name: SimpleNamespace(MainWindow=None),
    )

    with pytest.raises(TypeError, match=r"metroliza\.ui\.main_window\.MainWindow must be callable"):
        ui_entrypoint.load_main_window_factory()

from __future__ import annotations

import ast
from importlib import import_module
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PACKAGE = REPO_ROOT / "src" / "metroliza"


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
    return imports


def _package_edges(source: str, target: str) -> set[tuple[str, str]]:
    target_prefix = f"metroliza.{target}"
    return {
        (path.relative_to(SRC_PACKAGE).as_posix(), imported_module)
        for path in sorted((SRC_PACKAGE / source).rglob("*.py"))
        for imported_module in _absolute_imports(path)
        if imported_module == target_prefix or imported_module.startswith(f"{target_prefix}.")
    }


def _subprocess_env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": f"{SRC_PACKAGE.parent}{os.pathsep}{REPO_ROOT}",
    }


def test_backend_diagnostics_compatibility_paths_share_module_identity() -> None:
    canonical = import_module("metroliza.exporting.backend_diagnostics")
    app_alias = import_module("metroliza.app.backend_diagnostics")
    legacy_alias = import_module("modules" + ".backend_diagnostics")

    assert app_alias is canonical
    assert legacy_alias is canonical
    assert app_alias.build_backend_diagnostic_summary is canonical.build_backend_diagnostic_summary
    assert legacy_alias.format_backend_diagnostic_lines is canonical.format_backend_diagnostic_lines


def test_exporting_package_has_no_static_app_dependency() -> None:
    assert _package_edges("exporting", "app") == set()


def test_export_and_packaging_call_sites_use_canonical_diagnostics_owner() -> None:
    export_thread = (SRC_PACKAGE / "exporting" / "export_data_thread.py").read_text(
        encoding="utf-8"
    )
    package_script = (REPO_ROOT / "packaging" / "build_native_and_package.ps1").read_text(
        encoding="utf-8"
    )

    assert "from metroliza.exporting.backend_diagnostics import" in export_thread
    assert "from metroliza.exporting.backend_diagnostics import" in package_script
    assert "metroliza.app.backend_diagnostics" not in export_thread
    assert "metroliza.app.backend_diagnostics" not in package_script


def test_canonical_backend_diagnostics_cold_import_does_not_load_app_package(
    tmp_path: Path,
) -> None:
    script = """
import sys
import metroliza.exporting.backend_diagnostics

loaded = sorted(
    name
    for name in sys.modules
    if name == "metroliza.app" or name.startswith("metroliza.app.")
)
assert loaded == [], loaded
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=tmp_path,
        env=_subprocess_env(),
    )


def test_bootstrap_cold_import_does_not_load_export_diagnostics(
    tmp_path: Path,
) -> None:
    script = """
import sys
import metroliza.app.bootstrap

blocked = {
    "metroliza.exporting.backend_diagnostics",
    "metroliza.charts.chart_renderer",
    "matplotlib",
}
loaded = sorted(name for name in blocked if name in sys.modules)
assert loaded == [], loaded
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=tmp_path,
        env=_subprocess_env(),
    )

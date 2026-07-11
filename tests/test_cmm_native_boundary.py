from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
from pathlib import Path


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
        elif isinstance(node, ast.ImportFrom) and node.level == 2 and node.module:
            imports.add(f"metroliza.{node.module}")
    return imports


def _package_edges(source: str, target: str) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for path in sorted((SRC_PACKAGE / source).rglob("*.py")):
        for imported_module in _absolute_imports(path):
            if imported_module == f"metroliza.{target}" or imported_module.startswith(
                f"metroliza.{target}."
            ):
                edges.add((path.relative_to(SRC_PACKAGE).as_posix(), imported_module))
    return edges


def test_native_parsing_package_edge_is_one_way() -> None:
    assert _package_edges("native_bridges", "parsing") == set()
    assert _package_edges("parsing", "native_bridges") == {
        (
            "parsing/cmm_report_parser.py",
            "metroliza.native_bridges.cmm_native_parser",
        )
    }


def test_cmm_block_parser_remains_dependency_neutral() -> None:
    imports = _absolute_imports(SRC_PACKAGE / "cmm" / "block_parser.py")

    assert not {module for module in imports if module == "metroliza" or module.startswith("metroliza.")}


def test_native_bridge_cold_import_keeps_parsing_package_unloaded() -> None:
    script = """
import sys

from metroliza.native_bridges import cmm_native_parser

cmm_native_parser.reset_backend_telemetry()
result = cmm_native_parser.parse_blocks_with_backend_and_telemetry(
    ["#COLD IMPORT", "DIM", "X 10 0.2 -0.2 10.1 0.1 0 OK"],
)
assert result.backend == "python"
assert result.blocks
assert cmm_native_parser.get_backend_telemetry_snapshot()["parse"]["python"] == 1
assert not [
    name
    for name in sys.modules
    if name == "metroliza.parsing" or name.startswith("metroliza.parsing.")
]
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "METROLIZA_CMM_PARSER_BACKEND": "python",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": f"{SRC_PACKAGE.parent}{os.pathsep}{REPO_ROOT}",
        },
    )


def test_cmm_parser_compatibility_module_identities_are_preserved() -> None:
    core = importlib.import_module("metroliza.cmm.block_parser")
    canonical = importlib.import_module("metroliza.parsing.cmm_parsing")
    legacy = importlib.import_module("modules.cmm_parsing")

    assert legacy is canonical
    assert canonical.parse_raw_lines_to_blocks is core.parse_raw_lines_to_blocks
    assert canonical.add_tolerances_to_blocks is core.add_tolerances_to_blocks

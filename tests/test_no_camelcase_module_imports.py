from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("modules", "scripts", "tests")


def _camelcase_module_ref(module_path: str | None) -> bool:
    if not module_path or not module_path.startswith("modules."):
        return False
    module_name = module_path.split(".", 1)[1].split(".", 1)[0]
    return module_name[:1].isupper()


def _scan_python_files() -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        files.extend(sorted((REPO_ROOT / scan_dir).rglob("*.py")))
    return files


def test_no_first_party_camelcase_module_imports() -> None:
    violations: list[str] = []

    for file_path in _scan_python_files():
        rel_path = file_path.relative_to(REPO_ROOT)
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(rel_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if _camelcase_module_ref(node.module):
                    violations.append(f"{rel_path}:{node.lineno} from {node.module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _camelcase_module_ref(alias.name):
                        violations.append(f"{rel_path}:{node.lineno} import {alias.name}")

    assert not violations, "Found CamelCase module imports:\n" + "\n".join(violations)

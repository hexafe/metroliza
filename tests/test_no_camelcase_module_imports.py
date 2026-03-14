from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("modules", "scripts", "tests")
ALLOWED_FILES = {
    Path("tests/test_module_naming_compat.py"),
}


def _camelcase_module_ref(module_path: str | None) -> bool:
    if not module_path or not module_path.startswith("modules."):
        return False
    module_name = module_path.split(".", 1)[1].split(".", 1)[0]
    return module_name[:1].isupper()


def test_no_first_party_camelcase_module_imports() -> None:
    violations: list[str] = []

    for scan_dir in SCAN_DIRS:
        for file_path in sorted((REPO_ROOT / scan_dir).glob("*.py")):
            rel_path = file_path.relative_to(REPO_ROOT)
            if rel_path in ALLOWED_FILES:
                continue

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

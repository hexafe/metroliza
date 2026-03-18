"""Guardrails for docstrings on public APIs in high-impact modules."""

from __future__ import annotations

import ast
from pathlib import Path

DOCSTRING_GUARD_FILES = [
    "modules/export_data_thread.py",
    "modules/export_backends.py",
    "modules/cmm_report_parser.py",
    "modules/data_grouping.py",
    "modules/bom_manager.py",
]


def _missing_public_docstrings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    missing: list[str] = []

    if ast.get_docstring(tree) is None:
        missing.append("<module>")

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            if ast.get_docstring(node) is None:
                missing.append(node.name)

            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
                    if ast.get_docstring(child) is None:
                        missing.append(f"{node.name}.{child.name}")

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            if ast.get_docstring(node) is None:
                missing.append(node.name)

    return missing


def test_public_symbols_have_docstrings() -> None:
    failures: list[str] = []

    for relative_path in DOCSTRING_GUARD_FILES:
        path = Path(relative_path)
        missing = _missing_public_docstrings(path)
        if missing:
            failures.append(f"{relative_path}: {', '.join(missing)}")

    assert not failures, "\n".join(failures)

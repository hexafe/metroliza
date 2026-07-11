from __future__ import annotations

import ast
from pathlib import Path


def _module_scope_nodes(node: ast.AST):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _module_scope_nodes(child)


def _is_sys_modules(value: ast.AST) -> bool:
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "modules"
        and isinstance(value.value, ast.Name)
        and value.value.id == "sys"
    )


def test_test_modules_do_not_replace_imports_during_collection() -> None:
    violations: list[str] = []
    for path in sorted(Path("tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for statement in tree.body:
            for node in _module_scope_nodes(statement):
                if isinstance(node, ast.Subscript) and _is_sys_modules(node.value):
                    if isinstance(node.ctx, ast.Store):
                        violations.append(f"{path}:{node.lineno}: assigns sys.modules at collection")
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in {"setdefault", "update"}:
                    continue
                if _is_sys_modules(node.func.value):
                    violations.append(
                        f"{path}:{node.lineno}: mutates sys.modules at collection"
                    )

    assert violations == []


def test_delegated_class_setup_has_matching_class_teardown() -> None:
    violations: list[str] = []
    for path in sorted(Path("tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {
                child.name: child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            setup = methods.get("setUpClass")
            if setup is None or "tearDownClass" in methods:
                continue
            delegates_setup = any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "setUpClass"
                for child in ast.walk(setup)
            )
            if delegates_setup:
                violations.append(
                    f"{path}:{setup.lineno}: delegates setUpClass without matching tearDownClass"
                )

    assert violations == []

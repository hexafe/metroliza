from __future__ import annotations

import ast
from pathlib import Path


SYS_MODULES_MUTATORS = {
    "__delitem__",
    "__setitem__",
    "clear",
    "pop",
    "popitem",
    "setdefault",
    "update",
}


def _module_scope_nodes(node: ast.AST):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _module_scope_nodes(child)


def _name_targets(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in node.elts:
            names.update(_name_targets(element))
        return names
    return set()


def _module_scope_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    sys_names = {"sys"}
    module_cache_names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name == "sys":
                    sys_names.add(alias.asname or alias.name)
        elif isinstance(statement, ast.ImportFrom) and statement.module == "sys":
            for alias in statement.names:
                if alias.name == "modules":
                    module_cache_names.add(alias.asname or alias.name)

    changed = True
    while changed:
        changed = False
        for statement in tree.body:
            for node in _module_scope_nodes(statement):
                targets: set[str] = set()
                value: ast.AST | None = None
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        targets.update(_name_targets(target))
                    value = node.value
                elif isinstance(node, ast.AnnAssign):
                    targets.update(_name_targets(node.target))
                    value = node.value
                if not targets or value is None:
                    continue
                if _is_sys_modules(value, sys_names, module_cache_names):
                    new_names = targets - module_cache_names
                    if new_names:
                        module_cache_names.update(new_names)
                        changed = True
    return sys_names, module_cache_names


def _is_sys_modules(
    value: ast.AST,
    sys_names: set[str],
    module_cache_names: set[str],
) -> bool:
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "modules"
        and isinstance(value.value, ast.Name)
        and value.value.id in sys_names
    ) or (isinstance(value, ast.Name) and value.id in module_cache_names)


def _collection_time_sys_modules_mutations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sys_names, module_cache_names = _module_scope_aliases(tree)
    violations: list[str] = []
    for statement in tree.body:
        for node in _module_scope_nodes(statement):
            if isinstance(node, ast.Subscript) and _is_sys_modules(
                node.value,
                sys_names,
                module_cache_names,
            ):
                if isinstance(node.ctx, (ast.Store, ast.Del)):
                    violations.append(f"{path}:{node.lineno}: mutates sys.modules at collection")
            if isinstance(node, ast.Attribute) and _is_sys_modules(
                node,
                sys_names,
                module_cache_names,
            ):
                if isinstance(node.ctx, (ast.Store, ast.Del)):
                    violations.append(f"{path}:{node.lineno}: replaces sys.modules at collection")
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in SYS_MODULES_MUTATORS:
                continue
            if _is_sys_modules(node.func.value, sys_names, module_cache_names):
                violations.append(f"{path}:{node.lineno}: mutates sys.modules at collection")
    return violations


def test_test_modules_do_not_replace_imports_during_collection() -> None:
    violations: list[str] = []
    for path in sorted(Path("tests").glob("test_*.py")):
        violations.extend(_collection_time_sys_modules_mutations(path))

    assert violations == []


def test_collection_mutation_guard_covers_aliases_pop_clear_and_delete(tmp_path) -> None:
    source_path = tmp_path / "test_synthetic_collection_mutation.py"
    source_path.write_text(
        "import sys as runtime\n"
        "cache = runtime.modules\n"
        "alias = cache\n"
        "cache['assigned'] = object()\n"
        "cache.pop('removed', None)\n"
        "alias.clear()\n"
        "del alias['deleted']\n",
        encoding="utf-8",
    )

    violations = _collection_time_sys_modules_mutations(source_path)

    assert len(violations) == 4
    assert any(":4:" in violation for violation in violations)
    assert any(":5:" in violation for violation in violations)
    assert any(":6:" in violation for violation in violations)
    assert any(":7:" in violation for violation in violations)


def test_required_ui_tests_do_not_hide_first_party_import_failures() -> None:
    violations: list[str] = []
    for path in (
        Path("tests/test_export_dialog_behavior.py"),
        Path("tests/test_dashboard_visual_options_dialog.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Try):
                continue
            imports_first_party = any(
                (
                    isinstance(child, ast.Import)
                    and any(
                        alias.name == "modules"
                        or alias.name.startswith(("modules.", "metroliza."))
                        for alias in child.names
                    )
                )
                or (
                    isinstance(child, ast.ImportFrom)
                    and child.module is not None
                    and child.module.startswith(("modules", "metroliza"))
                )
                for child in node.body
            )
            catches_broad_exception = any(
                handler.type is None
                or (isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"})
                for handler in node.handlers
            )
            if imports_first_party and catches_broad_exception:
                violations.append(f"{path}:{node.lineno}")

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

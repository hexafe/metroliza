from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
REPORTS_PACKAGE = SRC_ROOT / "metroliza" / "reports"


def _static_metroliza_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return {module for module in modules if module.startswith("metroliza.")}


def test_reports_package_has_no_static_dependency_on_parsing() -> None:
    violations: list[str] = []
    for path in sorted(REPORTS_PACKAGE.rglob("*.py")):
        parsing_imports = sorted(
            module
            for module in _static_metroliza_imports(path)
            if module == "metroliza.parsing" or module.startswith("metroliza.parsing.")
        )
        if parsing_imports:
            relative = path.relative_to(REPORTS_PACKAGE).as_posix()
            violations.append(f"{relative}: {', '.join(parsing_imports)}")

    assert not violations, "Reports must not point back to parsing: " + "; ".join(violations)


def test_parser_factory_compatibility_paths_share_registry_identity() -> None:
    canonical = importlib.import_module("metroliza.parsing.report_parser_factory")
    former_canonical = importlib.import_module("metroliza.reports.report_parser_factory")
    legacy = importlib.import_module("modules.report_parser_factory")

    assert former_canonical is canonical
    assert legacy is canonical
    assert former_canonical.PARSER_MAP is canonical.PARSER_MAP
    assert "cmm" in canonical.PARSER_MAP


def test_header_correction_compatibility_paths_share_module_identity() -> None:
    canonical = importlib.import_module("metroliza.reports.header_ocr_corrections")
    former_canonical = importlib.import_module("metroliza.parsing.header_ocr_corrections")
    legacy = importlib.import_module("modules.header_ocr_corrections")

    assert former_canonical is canonical
    assert legacy is canonical
    assert canonical.canonicalize_header_label("PARTNAME") == "PART NAME"


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    roots = [str(SRC_ROOT), str(REPO_ROOT)]
    if existing:
        roots.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(roots)
    return env


def test_report_metadata_cold_import_does_not_load_parsing_package() -> None:
    code = """
import importlib
import sys

importlib.import_module("metroliza.reports.report_metadata_selector")
loaded = sorted(
    name for name in sys.modules
    if name == "metroliza.parsing" or name.startswith("metroliza.parsing.")
)
assert loaded == [], loaded
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_canonical_parser_factory_cold_import_skips_old_alias() -> None:
    code = """
import importlib
import sys

canonical = importlib.import_module("metroliza.parsing.report_parser_factory")
assert "metroliza.reports.report_parser_factory" not in sys.modules
assert canonical.PARSER_MAP["cmm"].__name__ == "CMMReportParser"
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_former_canonical_paths_are_safe_as_first_imports() -> None:
    code = """
import importlib

old_factory = importlib.import_module("metroliza.reports.report_parser_factory")
canonical_factory = importlib.import_module("metroliza.parsing.report_parser_factory")
old_corrections = importlib.import_module("metroliza.parsing.header_ocr_corrections")
canonical_corrections = importlib.import_module("metroliza.reports.header_ocr_corrections")

assert old_factory is canonical_factory
assert old_corrections is canonical_corrections
assert old_factory.PARSER_MAP["cmm"].__name__ == "CMMReportParser"
assert old_corrections.canonicalize_header_label("PARTNAME") == "PART NAME"
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

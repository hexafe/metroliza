from __future__ import annotations

import ast
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_MODULES = REPO_ROOT / "modules"
SRC_PACKAGE = REPO_ROOT / "src" / "metroliza"
IMPLEMENTATION_IMPORT_ROOTS = (
    SRC_PACKAGE,
    REPO_ROOT / "scripts",
    REPO_ROOT / "packaging",
)
TEST_LEGACY_REFERENCE_BUDGET = 991
CYCLIC_CANONICAL_PACKAGE_BUDGET = 4
TEST_LEGACY_REFERENCE_EXCLUDED_FILES = {
    "tests/test_directory_reorganization_architecture.py",
    "tests/test_packaging_spec_hiddenimports.py",
}
POWERSHELL_LEGACY_REFERENCE_ALLOWLIST = {
    "packaging/build_native_and_package.ps1": {
        "modules.chart_renderer",
        "modules.cmm_native_parser",
        "modules.comparison_stats_native",
        "modules.distribution_fit_native",
        "modules.group_stats_native",
    },
    "packaging/build_nuitka.ps1": {
        "modules.cmm_report_parser",
        "modules.header_ocr_backend",
        "modules.header_ocr_corrections",
        "modules.header_ocr_geometry",
        "modules.pdf_backend",
        "modules.report_parser_factory",
    },
}
LEGACY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+modules(?:\.|\s+import)|import\s+modules\.|importlib\.import_module\([\"']modules\.)",
    flags=re.MULTILINE,
)
LEGACY_DOTTED_REFERENCE_RE = re.compile(r"\bmodules\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
SHIM_TARGET_RE = re.compile(r"_alias_module\([^,]+,\s*[\"'](?P<target>metroliza(?:\.[^\"']+)*)[\"']\)")
RUST_LEGACY_IMPORT_RE = re.compile(r"PyModule::import(?:_bound)?\([^,\n]+,\s*[\"']modules\.")
METROLIZA_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+metroliza\.(?P<from_pkg>\w+)|import\s+metroliza\.(?P<import_pkg>\w+))",
    flags=re.MULTILINE,
)
PYQT_IMPORT_RE = re.compile(r"^\s*(?:from\s+PyQt6\b|import\s+PyQt6\b|from\s+PyQt6\.|import\s+PyQt6\.)", re.MULTILINE)

SHARED_FEATURE_IMPORT_ALLOWLIST: set[str] = set()
NON_UI_PACKAGE_UI_COMPATIBILITY_ALIAS_ALLOWLIST = {
    "shared/bom_manager.py",
}
QT_IMPORT_ALLOWLIST = {
    "exporting/export_data_thread.py",
    "industrial/industrial_workers.py",
    "parsing/metadata_enrichment_thread.py",
    "parsing/parse_reports_thread.py",
    "shared/custom_logger.py",
    "shared/list_selection_utils.py",
    "tabular/tabular_column_selection.py",
}


def _legacy_shim_files() -> list[Path]:
    return [
        path
        for path in sorted(LEGACY_MODULES.rglob("*.py"))
        if path.name != "compat.py" and "__pycache__" not in path.parts
    ]


def _canonical_target_exists(canonical_name: str) -> bool:
    relative_parts = canonical_name.removeprefix("metroliza.").split(".")
    candidate = SRC_PACKAGE.joinpath(*relative_parts)
    return candidate.with_suffix(".py").is_file() or (candidate / "__init__.py").is_file()


def _drop_leaked_stub_modules() -> None:
    for module_name in (
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "modules.custom_logger",
        "metroliza.shared.custom_logger",
        "modules.cmm_report_parser",
        "metroliza.parsing.cmm_report_parser",
    ):
        module = sys.modules.get(module_name)
        if module is not None and getattr(module, "__file__", None) is None:
            sys.modules.pop(module_name, None)


def test_canonical_source_package_exists() -> None:
    expected_packages = {
        "analytics",
        "app",
        "charts",
        "cmm",
        "exporting",
        "industrial",
        "integrations",
        "native",
        "native_bridges",
        "parsing",
        "reports",
        "resources",
        "shared",
        "storage",
        "tabular",
        "ui",
        "workers",
    }

    discovered = {path.name for path in SRC_PACKAGE.iterdir() if path.is_dir()}

    assert expected_packages <= discovered


def test_legacy_modules_are_alias_shims_with_existing_canonical_targets() -> None:
    violations: list[str] = []

    for module_file in _legacy_shim_files():
        text = module_file.read_text(encoding="utf-8")
        match = SHIM_TARGET_RE.search(text)
        if match is None:
            violations.append(str(module_file.relative_to(REPO_ROOT)))
            continue
        canonical_name = match.group("target")
        if not _canonical_target_exists(canonical_name):
            violations.append(f"{module_file.relative_to(REPO_ROOT)} -> {canonical_name}")

    assert not violations, "Legacy modules must alias canonical implementations: " + ", ".join(violations)


def test_legacy_imports_resolve_to_canonical_module_objects() -> None:
    _drop_leaked_stub_modules()
    pairs: dict[str, str] = {}
    for module_file in _legacy_shim_files():
        text = module_file.read_text(encoding="utf-8")
        match = SHIM_TARGET_RE.search(text)
        assert match is not None, f"{module_file.relative_to(REPO_ROOT)} is not an alias shim"
        legacy_parts = module_file.relative_to(REPO_ROOT).with_suffix("").parts
        if legacy_parts[-1] == "__init__":
            legacy_parts = legacy_parts[:-1]
        legacy_name = ".".join(legacy_parts)
        pairs[legacy_name] = match.group("target")

    for legacy_name, canonical_name in pairs.items():
        legacy = importlib.import_module(legacy_name)
        canonical = importlib.import_module(canonical_name)
        assert legacy is canonical


def test_canonical_imports_work_from_outside_repository_root(tmp_path) -> None:
    modules_to_import = [
        "metroliza.parsing.parse_reports_thread",
        "metroliza.exporting.export_data_thread",
        "metroliza.reports.report_repository",
        "metroliza.charts.chart_renderer",
        "metroliza.native_bridges.cmm_native_parser",
        "metroliza.native_bridges.group_stats_native",
        "metroliza.native_bridges.comparison_stats_native",
        "metroliza.native_bridges.distribution_fit_native",
    ]
    script = "\n".join(
        [
            "import importlib",
            f"modules = {modules_to_import!r}",
            "for name in modules:",
            "    importlib.import_module(name)",
        ]
    )

    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": f"{REPO_ROOT / 'src'}{os.pathsep}{REPO_ROOT}",
        },
    )


def test_implementation_code_uses_canonical_metroliza_imports() -> None:
    violations: list[str] = []

    for root in IMPLEMENTATION_IMPORT_ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if LEGACY_IMPORT_RE.search(text):
                violations.append(str(path.relative_to(REPO_ROOT)))

    assert not violations, "Implementation code must not import legacy modules.* paths: " + ", ".join(violations)


def test_behavior_test_legacy_module_references_stay_within_burn_down_budget() -> None:
    references: list[str] = []

    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in TEST_LEGACY_REFERENCE_EXCLUDED_FILES:
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in LEGACY_DOTTED_REFERENCE_RE.finditer(line):
                references.append(f"{relative}:{line_number}: {match.group(0)}")

    excess = len(references) - TEST_LEGACY_REFERENCE_BUDGET
    assert excess <= 0, (
        f"Legacy modules.* references in behavior tests increased by {excess}; "
        f"migrate tests to canonical imports or update the reviewed budget. "
        f"Sample references: {references[:20]}"
    )


def _canonical_package_graph() -> dict[str, set[str]]:
    package_names = {
        path.name for path in SRC_PACKAGE.iterdir() if (path / "__init__.py").is_file()
    }
    graph = {package_name: set() for package_name in package_names}
    for path in sorted(SRC_PACKAGE.rglob("*.py")):
        relative = path.relative_to(SRC_PACKAGE)
        if len(relative.parts) < 2:
            continue
        source_package = relative.parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            for module_name in imported_modules:
                parts = module_name.split(".")
                if len(parts) < 2 or parts[0] != "metroliza":
                    continue
                target_package = parts[1]
                if target_package in package_names and target_package != source_package:
                    graph[source_package].add(target_package)
    return graph


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[set[str]]:
    index = 0
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in indexes:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[target])
        if lowlinks[node] != indexes[node]:
            return
        component: set[str] = set()
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.add(member)
            if member == node:
                break
        components.append(component)

    for node in sorted(graph):
        if node not in indexes:
            visit(node)
    return components


def test_canonical_package_cycle_does_not_exceed_reviewed_ratchet() -> None:
    graph = _canonical_package_graph()
    cyclic_components = [component for component in _strongly_connected_components(graph) if len(component) > 1]
    cyclic_package_count = sum(len(component) for component in cyclic_components)

    assert cyclic_package_count <= CYCLIC_CANONICAL_PACKAGE_BUDGET, (
        f"Canonical package cycle grew to {cyclic_package_count} packages: "
        f"{sorted(sorted(component) for component in cyclic_components)}"
    )


def test_shared_package_has_no_static_outbound_package_dependencies() -> None:
    graph = _canonical_package_graph()

    assert graph["shared"] == set(), (
        "The neutral shared package must not import feature packages: "
        f"{sorted(graph['shared'])}"
    )


def test_powershell_packaging_legacy_modules_are_explicitly_allowlisted() -> None:
    violations: list[str] = []

    for path in sorted(REPO_ROOT.rglob("*.ps1")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        discovered = set(LEGACY_DOTTED_REFERENCE_RE.findall(text))
        allowed = POWERSHELL_LEGACY_REFERENCE_ALLOWLIST.get(relative, set())
        unexpected = sorted(discovered - allowed)
        if unexpected:
            violations.append(f"{relative}: {unexpected}")

    assert not violations, "PowerShell legacy modules.* references require an explicit allowlist: " + "; ".join(
        violations
    )


def test_non_ui_packages_do_not_import_ui_package() -> None:
    violations: list[str] = []

    for path in sorted(SRC_PACKAGE.rglob("*.py")):
        relative = path.relative_to(SRC_PACKAGE).as_posix()
        if (
            relative.startswith(("ui/", "app/"))
            or relative in NON_UI_PACKAGE_UI_COMPATIBILITY_ALIAS_ALLOWLIST
        ):
            continue
        text = path.read_text(encoding="utf-8")
        if "metroliza.ui" in text:
            violations.append(relative)

    assert not violations, "Non-UI packages must not depend on metroliza.ui: " + ", ".join(violations)


def test_shared_feature_imports_are_explicit_burn_down_items() -> None:
    violations: list[str] = []

    for path in sorted((SRC_PACKAGE / "shared").glob("*.py")):
        relative = path.relative_to(SRC_PACKAGE).as_posix()
        text = path.read_text(encoding="utf-8")
        imported_packages = {
            match.group("from_pkg") or match.group("import_pkg")
            for match in METROLIZA_IMPORT_RE.finditer(text)
        }
        feature_imports = imported_packages - {"shared", "resources"}
        if feature_imports and relative not in SHARED_FEATURE_IMPORT_ALLOWLIST:
            violations.append(f"{relative}: {sorted(feature_imports)}")

    assert not violations, "New shared package feature imports require explicit architecture review: " + ", ".join(violations)


def test_canonical_features_import_contracts_from_owning_packages() -> None:
    violations = []
    facade_import = "metroliza.shared.contracts"

    for path in sorted(SRC_PACKAGE.rglob("*.py")):
        relative = path.relative_to(SRC_PACKAGE).as_posix()
        if relative == "shared/contracts.py":
            continue
        if facade_import in path.read_text(encoding="utf-8"):
            violations.append(relative)

    assert not violations, (
        "Canonical feature code must import contracts from owning packages: "
        + ", ".join(violations)
    )


def test_qt_imports_are_limited_to_ui_app_or_worker_boundary_allowlist() -> None:
    violations: list[str] = []

    for path in sorted(SRC_PACKAGE.rglob("*.py")):
        relative = path.relative_to(SRC_PACKAGE).as_posix()
        if relative.startswith(("ui/", "app/", "workers/")) or relative in QT_IMPORT_ALLOWLIST:
            continue
        if PYQT_IMPORT_RE.search(path.read_text(encoding="utf-8")):
            violations.append(relative)

    assert not violations, "Qt imports outside UI/app/workers require explicit allowlist: " + ", ".join(violations)


def test_native_rust_code_uses_canonical_metroliza_imports() -> None:
    violations: list[str] = []

    for path in sorted((SRC_PACKAGE / "native").rglob("*.rs")):
        text = path.read_text(encoding="utf-8")
        if RUST_LEGACY_IMPORT_RE.search(text):
            violations.append(str(path.relative_to(REPO_ROOT)))

    assert not violations, "Native Rust code must not import legacy modules.* paths: " + ", ".join(violations)

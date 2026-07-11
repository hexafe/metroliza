#!/usr/bin/env python3
"""Supply-chain and import-surface security audit for Metroliza."""

from __future__ import annotations

import argparse
import ast
from datetime import date
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT_FILES = (
    "requirements.txt",
    "requirements-ocr.txt",
    "requirements-build.txt",
    "requirements-dev.txt",
)
IMPORT_SCAN_DIRS = ("src/metroliza", "modules", "scripts", "tests")
BANDIT_SCAN_DIRS = ("src/metroliza", "modules", "scripts")
PIP_AUDIT_CACHE_DIR = str(Path(tempfile.gettempdir()) / "pip-audit-cache")
BANDIT_BASELINE_PATH = REPO_ROOT / "config" / "security" / "bandit_baseline.json"
MAX_SECRET_SCAN_BYTES = 5 * 1024 * 1024
SECRET_ASSIGNMENT_SUFFIXES = {
    ".bash",
    ".cfg",
    ".conf",
    ".env",
    ".ini",
    ".json",
    ".md",
    ".properties",
    ".ps1",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
    ".zsh",
}
STRICT_SECRET_TEXT_SUFFIXES = SECRET_ASSIGNMENT_SUFFIXES | {".key", ".pem", ".ppk"}
SECRET_SCAN_WAIVERS = {
    "config/google/credentials.example.json": "documented placeholder credential fixture",
}
BLOCKED_SECRET_FILENAMES = {"credentials.json", "token.json"}
CONCRETE_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|glpat-[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)[\"']?\b(password|passwd|pwd|token|api[_-]?key|client[_-]?secret|"
    r"access[_-]?token|refresh[_-]?token)\b[\"']?\s*[:=]\s*"
    r"(?:[\"']([^\"'\n]{1,})[\"']|([^\s#,;\"']{1,}))"
)
PLACEHOLDER_VALUES = {
    "<redacted>",
    "abcdefghijklmnopqrstuvwxyz012345",
    "secret123",
}
PLACEHOLDER_WORDS = {
    "access",
    "another",
    "api",
    "assembly",
    "changeme",
    "client",
    "diagnostic",
    "dict",
    "dummy",
    "dynamic",
    "example",
    "expired",
    "fake",
    "filter",
    "finish",
    "interactive",
    "json",
    "key",
    "legacy",
    "me",
    "metadata",
    "nested",
    "new",
    "not",
    "old",
    "only",
    "password",
    "passwd",
    "payload",
    "persist",
    "placeholder",
    "plain",
    "pwd",
    "query",
    "raw",
    "reauthed",
    "redacted",
    "refresh",
    "remove",
    "replace",
    "sample",
    "secret",
    "should",
    "sql",
    "super",
    "test",
    "testing",
    "token",
    "very",
    "weld",
    "your",
}
PLACEHOLDER_TEMPLATE_RE = re.compile(
    r"^(?:\$\{\{[^{}]+\}\}|\$\{[A-Za-z_][A-Za-z0-9_]*\}|"
    r"\{[A-Za-z_][A-Za-z0-9_.-]*\})$"
)

FIRST_PARTY_IMPORTS = {
    "VersionDate",
    "metroliza",
    "modules",
    "scripts",
    "tests",
}
NATIVE_EXTENSION_IMPORTS = {
    "_metroliza_chart_native",
    "_metroliza_cmm_native",
    "_metroliza_comparison_stats_native",
    "_metroliza_distribution_fit_native",
    "_metroliza_group_stats_native",
}
INTERNAL_GIT_PACKAGES = {
    "hexafe-groupstats": "hexafe-groupstats",
    "hexafe-plotstats": "hexafe-plotstats",
    "oznak": "oznak",
}
IMPORT_TO_PACKAGE = {
    "PIL": "Pillow",
    "PyQt6": "PyQt6",
    "cryptography": "cryptography",
    "cv2": "opencv-python",
    "defusedxml": "defusedxml",
    "fitz": "PyMuPDF",
    "google_auth_oauthlib": "google-auth-oauthlib",
    "hexafe_groupstats": "hexafe-groupstats",
    "hexafe_plotstats": "hexafe-plotstats",
    "matplotlib": "matplotlib",
    "numpy": "numpy",
    "onnxruntime": "onnxruntime",
    "openpyxl": "openpyxl",
    "openvino": "openvino",
    "oznak": "oznak",
    "packaging": "packaging",
    "pandas": "pandas",
    "pymupdf": "PyMuPDF",
    "pyi_splash": "pyinstaller",
    "pytest": "pytest",
    "rapidocr": "rapidocr",
    "scipy": "scipy",
    "seaborn": "seaborn",
    "xlsxwriter": "XlsxWriter",
    "xlrd": "xlrd",
    "yaml": "PyYAML",
}
STD_LIB_IMPORTS = set(getattr(sys, "stdlib_module_names", set())) | {
    "msvcrt",
    "winreg",
}
INTERNAL_DEPENDENCY_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)(?:\[(?P<extras>[^\]]+)\])?\s*@\s*"
    r"git\+https://github\.com/hexafe/(?P<repo>[A-Za-z0-9_.-]+)\.git@(?P<sha>[0-9a-fA-F]+)"
)
REQUIREMENT_NAME_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)(?:\[[^\]]+\])?")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ImportUse:
    name: str
    path: Path
    line: int


@dataclass(frozen=True)
class DynamicImportUse:
    kind: str
    imported_name: str | None
    path: Path
    line: int


@dataclass(frozen=True)
class InternalDependencyPin:
    package: str
    repo: str
    sha: str
    requirement_file: Path
    extras: tuple[str, ...]


@dataclass
class AuditResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: "AuditResult") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


@dataclass(frozen=True)
class BanditBaselineEntry:
    repository: str
    fingerprint: str
    test_id: str
    path: str
    owner: str
    rationale: str
    expires_on: date


def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def iter_python_files(root: Path, directories: Sequence[str]) -> Iterable[Path]:
    skipped_parts = {".git", ".venv", "__pycache__", "artifacts", "build", "dist"}
    for directory in directories:
        base = root / directory
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if skipped_parts.intersection(path.relative_to(root).parts):
                continue
            yield path


def _top_level_name(name: str) -> str:
    return name.split(".", 1)[0]


def collect_imports(root: Path, directories: Sequence[str] = IMPORT_SCAN_DIRS) -> tuple[
    list[ImportUse], list[DynamicImportUse]
]:
    imports: list[ImportUse] = []
    dynamic_imports: list[DynamicImportUse] = []
    for path in iter_python_files(root, directories):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel_path = path.relative_to(root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(ImportUse(_top_level_name(alias.name), rel_path, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                if node.module:
                    imports.append(ImportUse(_top_level_name(node.module), rel_path, node.lineno))
            elif isinstance(node, ast.Call):
                dynamic = _dynamic_import_from_call(node)
                if dynamic:
                    kind, imported_name = dynamic
                    dynamic_imports.append(DynamicImportUse(kind, imported_name, rel_path, node.lineno))
    return imports, dynamic_imports


def _dynamic_import_from_call(node: ast.Call) -> tuple[str, str | None] | None:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "import_module":
        kind = "importlib.import_module"
    elif isinstance(func, ast.Name) and func.id == "__import__":
        kind = "__import__"
    else:
        return None
    if not node.args:
        return kind, None
    first_arg = node.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return kind, _top_level_name(first_arg.value)
    return kind, None


def _strip_requirement_comment(line: str) -> str:
    if " #" not in line:
        return line.strip()
    return line.split(" #", 1)[0].strip()


def declared_packages(
    root: Path,
    requirement_files: Sequence[str] = REQUIREMENT_FILES,
) -> set[str]:
    seen_files: set[Path] = set()
    packages: set[str] = set()

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen_files:
            return
        seen_files.add(resolved)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = _strip_requirement_comment(raw_line)
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r ") or line.startswith("--requirement "):
                include = line.split(maxsplit=1)[1]
                visit((path.parent / include).resolve())
                continue
            if line.startswith("-"):
                continue
            match = REQUIREMENT_NAME_RE.match(line)
            if match:
                packages.add(normalize_package_name(match.group("name")))

    for requirement_file in requirement_files:
        visit(root / requirement_file)
    return packages


def parse_internal_dependency_pins(root: Path) -> list[InternalDependencyPin]:
    pins: list[InternalDependencyPin] = []
    for requirement_file in REQUIREMENT_FILES:
        path = root / requirement_file
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            match = INTERNAL_DEPENDENCY_RE.match(_strip_requirement_comment(raw_line))
            if not match:
                continue
            pins.append(
                InternalDependencyPin(
                    package=match.group("name"),
                    repo=match.group("repo"),
                    sha=match.group("sha").lower(),
                    requirement_file=path.relative_to(root),
                    extras=tuple(
                        extra.strip()
                        for extra in (match.group("extras") or "").split(",")
                        if extra.strip()
                    ),
                )
            )
    return pins


def build_public_audit_requirements(root: Path, sibling_root: Path | None) -> tuple[list[str], list[str]]:
    public_lines: list[str] = []
    warnings: list[str] = []
    seen_requirement_files: set[Path] = set()

    def visit_requirement_file(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen_requirement_files:
            return
        seen_requirement_files.add(resolved)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = _strip_requirement_comment(raw_line)
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r ") or line.startswith("--requirement "):
                include = line.split(maxsplit=1)[1]
                visit_requirement_file((path.parent / include).resolve())
                continue
            if line.startswith("-"):
                continue
            if INTERNAL_DEPENDENCY_RE.match(line):
                continue
            public_lines.append(line)

    for requirement_file in REQUIREMENT_FILES:
        visit_requirement_file(root / requirement_file)

    pins = parse_internal_dependency_pins(root)
    if pins and sibling_root is None:
        warnings.append(
            "Public dependency expansion for internal Hexafe packages skipped: --sibling-root "
            "was not provided"
        )
    elif sibling_root is not None:
        for pin in pins:
            repo_path = sibling_root / pin.repo
            pyproject_path = repo_path / "pyproject.toml"
            if not pyproject_path.exists():
                warnings.append(f"{pin.repo}: pyproject.toml not found; sibling dependency audit skipped")
                continue
            public_lines.extend(_public_dependencies_from_pyproject(pyproject_path, pin.extras))

    return _dedupe_lines(public_lines), warnings


def _public_dependencies_from_pyproject(path: Path, extras: tuple[str, ...]) -> list[str]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    project = payload.get("project", {})
    lines = list(project.get("dependencies", []))
    optional_dependencies = project.get("optional-dependencies", {})
    for extra in extras:
        lines.extend(optional_dependencies.get(extra, []))
    return [line for line in lines if isinstance(line, str) and not line.startswith("git+")]


def _dedupe_lines(lines: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for line in lines:
        normalized = line.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def audit_import_coverage(root: Path) -> AuditResult:
    imports, dynamic_imports = collect_imports(root)
    packages = declared_packages(root)
    errors: list[str] = []
    warnings: list[str] = []
    unresolved: dict[str, list[ImportUse]] = {}

    for import_use in imports:
        name = import_use.name
        if name in STD_LIB_IMPORTS or name in FIRST_PARTY_IMPORTS or name in NATIVE_EXTENSION_IMPORTS:
            continue
        package = IMPORT_TO_PACKAGE.get(name)
        if not package:
            unresolved.setdefault(name, []).append(import_use)
            continue
        if normalize_package_name(package) not in packages:
            errors.append(
                f"{import_use.path}:{import_use.line}: import `{name}` requires "
                f"`{package}` but that package is not declared in requirements*.txt"
            )

    for name, uses in sorted(unresolved.items()):
        sample = ", ".join(f"{use.path}:{use.line}" for use in uses[:3])
        errors.append(
            f"Unclassified import `{name}` is not stdlib, first-party, native, or mapped "
            f"to a declared package. Examples: {sample}"
        )

    for dynamic_import in dynamic_imports:
        if dynamic_import.imported_name is None:
            warnings.append(
                f"{dynamic_import.path}:{dynamic_import.line}: {dynamic_import.kind} uses a "
                "non-literal module name; reviewed as diagnostic/plugin-style dynamic import"
            )
            continue
        name = dynamic_import.imported_name
        package = IMPORT_TO_PACKAGE.get(name)
        if (
            name not in STD_LIB_IMPORTS
            and name not in FIRST_PARTY_IMPORTS
            and name not in NATIVE_EXTENSION_IMPORTS
            and package
            and normalize_package_name(package) not in packages
        ):
            errors.append(
                f"{dynamic_import.path}:{dynamic_import.line}: dynamic import `{name}` "
                f"requires undeclared package `{package}`"
            )

    return AuditResult(errors=errors, warnings=warnings)


def audit_internal_dependency_pins(root: Path, sibling_root: Path | None) -> AuditResult:
    errors: list[str] = []
    warnings: list[str] = []
    pins = parse_internal_dependency_pins(root)
    pinned_packages = {pin.package for pin in pins}

    for package, expected_repo in INTERNAL_GIT_PACKAGES.items():
        matches = [pin for pin in pins if pin.package == package]
        if not matches:
            errors.append(f"Internal dependency `{package}` is not pinned in requirements*.txt")
            continue
        for pin in matches:
            if pin.repo != expected_repo:
                errors.append(
                    f"{pin.requirement_file}: `{package}` points to repo `{pin.repo}`, "
                    f"expected `{expected_repo}`"
                )
            if not FULL_SHA_RE.fullmatch(pin.sha):
                errors.append(
                    f"{pin.requirement_file}: `{package}` must be pinned to a full 40-char SHA"
                )

    extra_pins = pinned_packages - set(INTERNAL_GIT_PACKAGES)
    for package in sorted(extra_pins):
        warnings.append(f"Found unclassified Hexafe git dependency `{package}`")

    if sibling_root is None:
        warnings.append("Sibling repo checkout verification skipped: --sibling-root was not provided")
        return AuditResult(errors=errors, warnings=warnings)

    for pin in pins:
        repo_path = sibling_root / pin.repo
        if not repo_path.exists():
            errors.append(f"Sibling repo `{pin.repo}` was not found under {sibling_root}")
            continue
        head = run_command(["git", "-C", str(repo_path), "rev-parse", "HEAD"], root).stdout.strip()
        if head.lower() != pin.sha:
            errors.append(
                f"Sibling repo `{pin.repo}` is at {head}, but `{pin.package}` pins {pin.sha}"
            )
    return AuditResult(errors=errors, warnings=warnings)


def run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def run_pip_audit(root: Path, sibling_root: Path | None) -> AuditResult:
    public_lines, warnings = build_public_audit_requirements(root, sibling_root)
    if not public_lines:
        return AuditResult(errors=["No public requirements were available for pip-audit"], warnings=warnings)
    with tempfile.TemporaryDirectory(prefix="metroliza-security-audit-") as temp_dir:
        requirements_path = Path(temp_dir) / "public-requirements.txt"
        requirements_path.write_text("\n".join(public_lines) + "\n", encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "pip_audit",
            "--cache-dir",
            PIP_AUDIT_CACHE_DIR,
            "--progress-spinner",
            "off",
            "-r",
            str(requirements_path),
        ]
        completed = run_command(command, root)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part.strip())
    if output:
        print(output)
    if completed.returncode != 0:
        return AuditResult(
            errors=[f"pip-audit failed with exit code {completed.returncode}"],
            warnings=warnings,
        )
    return AuditResult(errors=[], warnings=warnings)


def _relative_result_path(root: Path, result: dict[str, object]) -> str:
    filename = Path(str(result.get("filename", "<unknown>")))
    try:
        return filename.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return filename.as_posix()


def bandit_issue_fingerprint(
    root: Path,
    result: dict[str, object],
    *,
    repository: str,
) -> str:
    code = re.sub(r"(?m)^\s*\d+\s+", "", str(result.get("code", ""))).strip()
    payload = {
        "repository": repository,
        "path": _relative_result_path(root, result),
        "line_number": int(result.get("line_number", 0) or 0),
        "test_id": str(result.get("test_id", "B???")),
        "issue_text": str(result.get("issue_text", "")),
        "code": code,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_bandit_baseline(path: Path) -> tuple[dict[tuple[str, str], BanditBaselineEntry], list[str]]:
    if not path.exists():
        return {}, [f"Bandit baseline not found: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"Bandit baseline is unreadable: {path}: {exc}"]
    if payload.get("version") != 1 or not isinstance(payload.get("entries"), list):
        return {}, [f"Bandit baseline must contain version 1 and an entries list: {path}"]

    entries: dict[tuple[str, str], BanditBaselineEntry] = {}
    errors: list[str] = []
    for index, raw_entry in enumerate(payload["entries"]):
        try:
            entry = BanditBaselineEntry(
                repository=str(raw_entry["repository"]),
                fingerprint=str(raw_entry["fingerprint"]),
                test_id=str(raw_entry["test_id"]),
                path=str(raw_entry["path"]),
                owner=str(raw_entry["owner"]).strip(),
                rationale=str(raw_entry["rationale"]).strip(),
                expires_on=date.fromisoformat(str(raw_entry["expires_on"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"Bandit baseline entry {index} is invalid: {exc}")
            continue
        key = (entry.repository, entry.fingerprint)
        if key in entries:
            errors.append(
                f"Bandit baseline has duplicate fingerprint {entry.fingerprint} "
                f"for {entry.repository}"
            )
        if not entry.owner or not entry.rationale:
            errors.append(
                f"Bandit baseline entry {entry.fingerprint} requires owner and rationale"
            )
        entries[key] = entry
    return entries, errors


def _audit_medium_bandit_results(
    root: Path,
    results: Sequence[dict[str, object]],
    *,
    repository: str,
    baseline_path: Path,
) -> AuditResult:
    baseline, errors = load_bandit_baseline(baseline_path)
    today = date.today()
    matched: set[tuple[str, str]] = set()
    for result in results:
        fingerprint = bandit_issue_fingerprint(root, result, repository=repository)
        key = (repository, fingerprint)
        entry = baseline.get(key)
        if entry is None:
            errors.append(
                f"Unbaselined Bandit medium finding [{fingerprint[:12]}]: "
                f"{_format_bandit_issue(root, result)}"
            )
            continue
        matched.add(key)
        result_path = _relative_result_path(root, result)
        result_test_id = str(result.get("test_id", "B???"))
        if entry.path != result_path or entry.test_id != result_test_id:
            errors.append(
                f"Bandit baseline metadata mismatch for {fingerprint}: "
                f"expected {result_test_id} at {result_path}"
            )
        if entry.expires_on < today:
            errors.append(
                f"Bandit baseline entry expired on {entry.expires_on.isoformat()}: "
                f"{entry.test_id} at {entry.path} (owner: {entry.owner})"
            )
    expired_unmatched = [
        entry
        for key, entry in baseline.items()
        if entry.repository == repository and key not in matched and entry.expires_on < today
    ]
    for entry in expired_unmatched:
        errors.append(
            f"Unused Bandit baseline entry expired on {entry.expires_on.isoformat()}: "
            f"{entry.test_id} at {entry.path} (owner: {entry.owner})"
        )
    warnings = []
    if results and not errors:
        try:
            baseline_display = baseline_path.relative_to(REPO_ROOT)
        except ValueError:
            baseline_display = baseline_path
        warnings.append(
            f"{repository}: accepted {len(results)} reviewed Bandit medium finding(s) "
            f"from {baseline_display}"
        )
    return AuditResult(errors=errors, warnings=warnings)


def run_bandit_report(
    root: Path,
    scan_dirs: Sequence[str],
    *,
    repository: str = "metroliza",
    baseline_path: Path = BANDIT_BASELINE_PATH,
    enforce_medium_baseline: bool = False,
) -> AuditResult:
    existing_dirs = [directory for directory in scan_dirs if (root / directory).exists()]
    if not existing_dirs:
        return AuditResult(errors=[], warnings=[f"No Bandit scan dirs found under {root}"])
    command = [
        sys.executable,
        "-m",
        "bandit",
        "-q",
        "-r",
        *existing_dirs,
        "--severity-level",
        "medium",
        "--format",
        "json",
        "--exit-zero",
    ]
    completed = run_command(command, root)
    if completed.returncode != 0:
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part.strip())
        return AuditResult(
            errors=[f"bandit failed for {root} with exit code {completed.returncode}: {output}"],
            warnings=[],
        )
    try:
        payload = json.loads(_extract_json_object(completed.stdout))
    except json.JSONDecodeError as exc:
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part.strip())
        return AuditResult(
            errors=[f"bandit returned invalid JSON for {root}: {exc}: {output[:1000]}"],
            warnings=[],
        )

    results = payload.get("results", [])
    scan_errors = payload.get("errors", [])
    high_results = [result for result in results if result.get("issue_severity") == "HIGH"]
    medium_results = [result for result in results if result.get("issue_severity") == "MEDIUM"]
    errors = [f"Bandit scan error for {root}: {error}" for error in scan_errors]
    errors.extend(_format_bandit_issue(root, result) for result in high_results)
    warnings: list[str] = []
    if medium_results and enforce_medium_baseline:
        medium_audit = _audit_medium_bandit_results(
            root,
            medium_results,
            repository=repository,
            baseline_path=baseline_path,
        )
        errors.extend(medium_audit.errors)
        warnings.extend(medium_audit.warnings)
    elif medium_results:
        warnings.append(
            f"{root}: Bandit found {len(medium_results)} medium issue(s); report-only baseline"
        )
        for result in medium_results[:10]:
            warnings.append(_format_bandit_issue(root, result))
        if len(medium_results) > 10:
            warnings.append(f"{root}: {len(medium_results) - 10} additional medium issue(s) omitted")
    return AuditResult(errors=errors, warnings=warnings)


def _format_bandit_issue(root: Path, result: dict[str, object]) -> str:
    path = _relative_result_path(root, result)
    return (
        f"{path}:{result.get('line_number', '?')}: "
        f"{result.get('test_id', 'B???')} {result.get('issue_severity', 'UNKNOWN')} "
        f"{result.get('issue_text', '')}"
    )


def _extract_json_object(output: str) -> str:
    stripped = output.strip()
    if not stripped:
        return "{}"
    if stripped.startswith("{"):
        return stripped
    start = stripped.find("{")
    if start == -1:
        return stripped
    return stripped[start:]


def run_sibling_bandit(
    root: Path,
    sibling_root: Path | None,
    *,
    baseline_path: Path = BANDIT_BASELINE_PATH,
    enforce_medium_baseline: bool = False,
) -> AuditResult:
    if sibling_root is None:
        return AuditResult(errors=[], warnings=[])
    result = AuditResult(errors=[], warnings=[])
    for pin in parse_internal_dependency_pins(root):
        repo_path = sibling_root / pin.repo
        if not repo_path.exists():
            continue
        scan_dirs = [directory for directory in ("src", "scripts") if (repo_path / directory).exists()]
        if not scan_dirs:
            result.warnings.append(f"{pin.repo}: no src/scripts dirs found for sibling Bandit scan")
            continue
        result.extend(
            run_bandit_report(
                repo_path,
                scan_dirs,
                repository=pin.repo,
                baseline_path=baseline_path,
                enforce_medium_baseline=enforce_medium_baseline,
            )
        )
    return result


def _is_secret_assignment_candidate(path: Path) -> bool:
    return (
        path.name == ".env"
        or path.name.startswith(".env.")
        or not path.suffix
        or path.suffix.lower() in SECRET_ASSIGNMENT_SUFFIXES
    )


def _requires_text_secret_scan(path: Path) -> bool:
    return _is_secret_assignment_candidate(path) or path.suffix.lower() in STRICT_SECRET_TEXT_SUFFIXES


def _running_in_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"} or os.environ.get(
        "GITHUB_ACTIONS", ""
    ).strip().lower() == "true"


def _is_blocked_secret_filename(path: Path) -> bool:
    name = path.name.lower()
    return name in BLOCKED_SECRET_FILENAMES or name.endswith(
        (".credentials.json", ".token.json")
    )


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered in PLACEHOLDER_VALUES or PLACEHOLDER_TEMPLATE_RE.fullmatch(normalized):
        return True
    words = [word for word in re.split(r"[-_\s]+", lowered) if word]
    return bool(words) and all(word in PLACEHOLDER_WORDS for word in words)


def scan_secret_paths(
    root: Path,
    paths: Iterable[str],
    *,
    waivers: dict[str, str] | None = None,
    fail_on_unreadable: bool = False,
) -> AuditResult:
    waivers = dict(SECRET_SCAN_WAIVERS if waivers is None else waivers)
    errors: list[str] = []
    warnings: list[str] = []
    for waived_path, rationale in waivers.items():
        if "/fixtures/" not in f"/{waived_path}" and ".example." not in waived_path:
            errors.append(
                f"Secret-scan waiver must be fixture/example-only: {waived_path} ({rationale})"
            )

    for raw_path in sorted(set(paths)):
        relative_path = Path(raw_path).as_posix()
        if relative_path in waivers:
            continue
        path = root / relative_path
        if not path.is_file():
            continue
        if _is_blocked_secret_filename(path):
            errors.append(f"{relative_path}: filename is reserved for untracked credentials")
        strict_text_candidate = _requires_text_secret_scan(path)
        try:
            size = path.stat().st_size
        except OSError as exc:
            message = f"{relative_path}: secret scan could not inspect file metadata: {exc}"
            (errors if fail_on_unreadable else warnings).append(message)
            continue
        if size > MAX_SECRET_SCAN_BYTES:
            if strict_text_candidate:
                message = (
                    f"{relative_path}: secret-scan text candidate exceeds "
                    f"{MAX_SECRET_SCAN_BYTES} byte limit"
                )
                (errors if fail_on_unreadable else warnings).append(message)
            continue
        try:
            raw_content = path.read_bytes()
        except OSError as exc:
            message = f"{relative_path}: secret scan could not read file: {exc}"
            (errors if fail_on_unreadable else warnings).append(message)
            continue
        try:
            text = raw_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            if strict_text_candidate:
                message = f"{relative_path}: secret-scan text candidate is not valid UTF-8: {exc}"
                (errors if fail_on_unreadable else warnings).append(message)
            continue
        for pattern in CONCRETE_SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                line_number = text.count("\n", 0, match.start()) + 1
                errors.append(
                    f"{relative_path}:{line_number}: content matches a concrete secret pattern"
                )
        if not _is_secret_assignment_candidate(path):
            continue
        for match in SECRET_ASSIGNMENT_RE.finditer(text):
            quoted_value = match.group(2)
            unquoted_value = match.group(3)
            if unquoted_value is not None and path.suffix.lower() == ".py":
                continue
            value = quoted_value or unquoted_value or ""
            if _looks_like_placeholder(value):
                continue
            line_number = text.count("\n", 0, match.start()) + 1
            errors.append(
                f"{relative_path}:{line_number}: `{match.group(1)}` contains a secret-like value"
            )
    return AuditResult(errors=sorted(set(errors)), warnings=sorted(set(warnings)))


def audit_repository_secrets(
    root: Path,
    *,
    base_ref: str | None = None,
    fail_on_unreadable: bool = False,
) -> AuditResult:
    tracked = run_command(["git", "ls-files"], root)
    if tracked.returncode != 0:
        return AuditResult(errors=[f"git ls-files failed: {tracked.stderr.strip()}"], warnings=[])
    paths = {line.strip() for line in tracked.stdout.splitlines() if line.strip()}
    if base_ref:
        changed = run_command(["git", "diff", "--name-only", f"{base_ref}..HEAD"], root)
        if changed.returncode == 0:
            paths.update(line.strip() for line in changed.stdout.splitlines() if line.strip())
    return scan_secret_paths(root, paths, fail_on_unreadable=fail_on_unreadable)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci", action="store_true", help="Use CI-oriented output and exit codes.")
    parser.add_argument(
        "--sibling-root",
        type=Path,
        help="Directory containing pinned Hexafe sibling repositories for commit verification.",
    )
    parser.add_argument(
        "--skip-pip-audit",
        action="store_true",
        help="Skip external manifest advisory lookup. Intended for offline diagnostics only.",
    )
    parser.add_argument(
        "--skip-bandit",
        action="store_true",
        help="Skip static Bandit analysis. Intended for focused import/dependency diagnostics only.",
    )
    parser.add_argument(
        "--bandit-baseline",
        type=Path,
        default=BANDIT_BASELINE_PATH,
        help="Reviewed Bandit medium-finding baseline used by --ci.",
    )
    parser.add_argument(
        "--secret-scan-only",
        action="store_true",
        help="Scan tracked cross-format text files for credential material and exit.",
    )
    parser.add_argument(
        "--base-ref",
        help="Optional Git base revision whose changed paths are also secret-scanned.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root = REPO_ROOT
    sibling_root = args.sibling_root.resolve() if args.sibling_root else None
    aggregate = AuditResult(errors=[], warnings=[])

    aggregate.extend(
        audit_repository_secrets(
            root,
            base_ref=args.base_ref,
            fail_on_unreadable=args.ci or _running_in_ci(),
        )
    )
    if args.secret_scan_only:
        for warning in aggregate.warnings:
            print(f"SECURITY AUDIT WARNING: {warning}")
        if aggregate.errors:
            print("Secret scan failed:")
            for error in aggregate.errors:
                print(f" - {error}")
            return 1
        print("Secret scan passed.")
        return 0

    aggregate.extend(audit_import_coverage(root))
    aggregate.extend(audit_internal_dependency_pins(root, sibling_root))
    if not args.skip_pip_audit:
        aggregate.extend(run_pip_audit(root, sibling_root))
    if not args.skip_bandit:
        aggregate.extend(
            run_bandit_report(
                root,
                BANDIT_SCAN_DIRS,
                baseline_path=args.bandit_baseline,
                enforce_medium_baseline=args.ci,
            )
        )
        aggregate.extend(
            run_sibling_bandit(
                root,
                sibling_root,
                baseline_path=args.bandit_baseline,
                enforce_medium_baseline=args.ci,
            )
        )

    for warning in aggregate.warnings:
        print(f"SECURITY AUDIT WARNING: {warning}")
    if aggregate.errors:
        print("Security audit failed:")
        for error in aggregate.errors:
            print(f" - {error}")
        return 1
    print("Security audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

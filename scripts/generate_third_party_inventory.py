"""Generate a metadata-derived Python and Rust release dependency inventory."""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import tomllib
from typing import Any, Iterable

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs/release_checks/third_party_inventory_260711.json"


def requirement_roots(paths: Iterable[str | Path]) -> tuple[str, ...]:
    """Return canonical direct distribution names from nested requirement files."""

    roots: set[str] = set()
    visited: set[Path] = set()

    def visit(path_value: str | Path) -> None:
        path = Path(path_value).resolve()
        if path in visited:
            return
        visited.add(path)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith(("-r ", "--requirement ")):
                nested = line.split(maxsplit=1)[1]
                visit(path.parent / nested)
                continue
            if line.startswith("-"):
                continue
            try:
                roots.add(canonicalize_name(Requirement(line).name))
            except InvalidRequirement as exc:
                raise ValueError(f"Unsupported requirement in {path}: {raw_line}") from exc

    for requirement_path in paths:
        visit(requirement_path)
    return tuple(sorted(roots))


def _license_text(metadata: importlib.metadata.PackageMetadata) -> str:
    value = metadata.get("License-Expression") or metadata.get("License") or ""
    normalized = " ".join(str(value).split())
    if normalized and normalized.casefold() != "unknown":
        return normalized[:500]
    classifiers = [
        classifier.removeprefix("License :: ")
        for classifier in metadata.get_all("Classifier", [])
        if classifier.startswith("License :: ")
    ]
    return "; ".join(classifiers) or "UNDECLARED"


def _project_url(metadata: importlib.metadata.PackageMetadata) -> str:
    for entry in metadata.get_all("Project-URL", []):
        _label, separator, url = entry.partition(",")
        if separator and url.strip():
            return url.strip()
    return str(metadata.get("Home-page") or "").strip()


def _installed_distributions() -> dict[str, importlib.metadata.Distribution]:
    return {
        canonicalize_name(distribution.metadata["Name"]): distribution
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }


def build_python_inventory(root_names: Iterable[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve installed dependency closure from the requested direct distributions."""

    installed = _installed_distributions()
    roots = {canonicalize_name(name) for name in root_names}
    pending = deque(sorted(roots))
    included: set[str] = set()
    missing: set[str] = set()
    environment = default_environment()
    environment["extra"] = ""

    while pending:
        name = pending.popleft()
        if name in included:
            continue
        distribution = installed.get(name)
        if distribution is None:
            missing.add(name)
            continue
        included.add(name)
        for raw_requirement in distribution.requires or ():
            try:
                requirement = Requirement(raw_requirement)
            except InvalidRequirement:
                continue
            if requirement.marker is not None and not requirement.marker.evaluate(environment):
                continue
            dependency = canonicalize_name(requirement.name)
            if dependency not in included:
                pending.append(dependency)

    records = []
    for name in sorted(included):
        distribution = installed[name]
        metadata = distribution.metadata
        records.append(
            {
                "name": str(metadata.get("Name") or name),
                "canonical_name": name,
                "version": distribution.version,
                "direct": name in roots,
                "license_metadata": _license_text(metadata),
                "project_url": _project_url(metadata),
            }
        )
    return records, sorted(missing)


def _direct_rust_manifest_record(manifest: Path) -> dict[str, Any]:
    payload = tomllib.loads(manifest.read_text(encoding="utf-8"))
    package = payload.get("package", {})
    dependencies = payload.get("dependencies", {})
    return {
        "name": str(package.get("name") or manifest.parent.name),
        "version": str(package.get("version") or ""),
        "license": str(package.get("license") or "UNDECLARED"),
        "source": "workspace",
        "direct_dependencies": sorted(str(name) for name in dependencies),
        "manifest": str(manifest.relative_to(REPO_ROOT)),
    }


def build_rust_inventory(manifests: Iterable[str | Path]) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve Cargo metadata for native crates, falling back to direct manifest records."""

    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    warnings: list[str] = []
    for manifest_value in manifests:
        manifest = Path(manifest_value).resolve()
        command = [
            "cargo",
            "metadata",
            "--locked",
            "--format-version",
            "1",
            "--manifest-path",
            str(manifest),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
                env={**os.environ, "CARGO_TERM_COLOR": "never"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            warnings.append(f"{manifest}: cargo metadata unavailable ({exc})")
            direct = _direct_rust_manifest_record(manifest)
            records[(direct["name"], direct["version"], direct["source"])] = direct
            continue
        if completed.returncode != 0:
            detail = " ".join(completed.stderr.split())[-500:]
            warnings.append(f"{manifest}: cargo metadata failed ({detail})")
            direct = _direct_rust_manifest_record(manifest)
            records[(direct["name"], direct["version"], direct["source"])] = direct
            continue
        payload = json.loads(completed.stdout)
        for package in payload.get("packages", []):
            source = str(package.get("source") or "workspace")
            record = {
                "name": str(package.get("name") or ""),
                "version": str(package.get("version") or ""),
                "license": str(package.get("license") or "UNDECLARED"),
                "source": source,
                "repository": str(package.get("repository") or ""),
            }
            records[(record["name"], record["version"], source)] = record
    return [records[key] for key in sorted(records)], warnings


def generate_inventory(
    *,
    requirement_paths: Iterable[str | Path],
    cargo_manifests: Iterable[str | Path],
) -> dict[str, Any]:
    roots = requirement_roots(requirement_paths)
    python_packages, missing_python = build_python_inventory(roots)
    rust_packages, rust_warnings = build_rust_inventory(cargo_manifests)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": {
            "requirement_roots": list(roots),
            "packages": python_packages,
            "missing_requirement_roots": missing_python,
        },
        "rust": {"packages": rust_packages, "warnings": rust_warnings},
        "review_status": {
            "metadata_reviewed": False,
            "release_owner_approved": False,
            "legal_review_required_for": ["PyQt6/Qt", "PyMuPDF"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requirements",
        action="append",
        default=[],
        help="Requirement file to include; defaults to runtime and OCR requirements.",
    )
    parser.add_argument("--cargo-manifest", action="append", default=[])
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    requirement_paths = args.requirements or ["requirements.txt", "requirements-ocr.txt"]
    cargo_manifests = args.cargo_manifest or [
        str(path.relative_to(REPO_ROOT))
        for path in sorted((REPO_ROOT / "src/metroliza/native").glob("*/Cargo.toml"))
    ]
    payload = generate_inventory(
        requirement_paths=requirement_paths,
        cargo_manifests=cargo_manifests,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    missing = payload["python"]["missing_requirement_roots"]
    warnings = payload["rust"]["warnings"]
    if missing or warnings:
        print(json.dumps({"missing_python": missing, "rust_warnings": warnings}, indent=2))
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

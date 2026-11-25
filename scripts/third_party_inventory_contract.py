"""Source inputs and validation shared by inventory production and packaging."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from metroliza.shared.release_identity import current_identity


REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = Path("docs/release_checks/third_party_inventory.json")
DEFAULT_REQUIREMENTS = (Path("requirements.txt"), Path("requirements-ocr.txt"))
PACKAGING_INPUTS = (
    Path("requirements-build.txt"),
    Path("requirements-ocr-benchmark.txt"),
    Path("packaging/windows-rc-constraints.txt"),
)
LAUNCHER_MANIFEST = Path("packaging/launcher/Cargo.toml")
SCHEMA_VERSION = 2


def default_cargo_manifests(repo_root: Path = REPO_ROOT) -> list[Path]:
    native = sorted((repo_root / "src/metroliza/native").glob("*/Cargo.toml"))
    return [*native, repo_root / LAUNCHER_MANIFEST]


def _requirement_inputs(roots: Iterable[Path]) -> set[Path]:
    visited: set[Path] = set()
    pending = list(roots)
    while pending:
        path = pending.pop().resolve()
        if path in visited:
            continue
        visited.add(path)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            for option in ("-r ", "--requirement ", "--requirement=", "-c ", "--constraint ", "--constraint="):
                if line.startswith(option):
                    pending.append(path.parent / line.removeprefix(option).strip())
                    break
    return visited


def _input_hashes(
    repo_root: Path, requirement_paths: Iterable[Path], cargo_manifests: Iterable[Path],
) -> dict[str, str]:
    repo_root = repo_root.resolve()
    files = _requirement_inputs([*requirement_paths, *(repo_root / path for path in PACKAGING_INPUTS)])
    for manifest in cargo_manifests:
        manifest = manifest.resolve()
        files.update((manifest, manifest.with_name("Cargo.lock")))
    return {
        path.relative_to(repo_root).as_posix(): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n"),
        ).hexdigest()
        for path in sorted(files)
    }


def inventory_provenance(
    inventory: dict[str, Any],
    repo_root: Path,
    *,
    requirement_paths: Iterable[Path] | None = None,
    cargo_manifests: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Bind the inventory data to a release and the packaging dependency inputs."""

    records = {key: inventory[key] for key in ("python", "rust", "vendored_plotly")}
    records_bytes = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "release_label": current_identity(repo_root).label,
        "dependency_inputs": _input_hashes(
            repo_root,
            [repo_root / path for path in DEFAULT_REQUIREMENTS] if requirement_paths is None else requirement_paths,
            default_cargo_manifests(repo_root) if cargo_manifests is None else cargo_manifests,
        ),
        "records_sha256": hashlib.sha256(records_bytes).hexdigest(),
    }


def validate_inventory(path: Path, repo_root: Path) -> dict[str, Any]:
    """Read the committed inventory and reject an absent or stale source binding."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported third-party inventory schema; regenerate the inventory")
    recorded = payload.get("provenance")
    if not isinstance(recorded, dict):
        raise ValueError("Third-party inventory is missing provenance")
    for key in ("python", "rust", "vendored_plotly"):
        if not isinstance(payload.get(key), dict):
            raise ValueError(f"Third-party inventory is missing {key} records")
    if payload["python"].get("missing_requirement_roots") != [] or payload["rust"].get("warnings") != []:
        raise ValueError("Third-party inventory dependency resolution is incomplete")
    expected = inventory_provenance(payload, repo_root)
    if recorded.get("release_label") != expected["release_label"]:
        raise ValueError("Third-party inventory release mismatch; regenerate the inventory")
    if recorded.get("dependency_inputs") != expected["dependency_inputs"]:
        raise ValueError("Third-party inventory dependency inputs changed; regenerate the inventory")
    if recorded.get("records_sha256") != expected["records_sha256"]:
        raise ValueError("Third-party inventory records changed; regenerate the inventory")
    return payload

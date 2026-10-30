"""Verify the committed third-party inventory against the dependencies of an actual build.

Run it with the build environment's interpreter (``.venv-build``) after the onedir is built.
It regenerates the inventory from that environment: the installed closure of the runtime
requirement roots, plus every distribution whose ``*.dist-info`` the onedir bundles (packagers
pull in some that the requirements do not name), and the Rust packages of the native crates and
the native launcher. The check fails when the committed inventory and the build differ in any
package name or version, or when the onedir bundles metadata of a distribution the build
environment does not explain. ``--generated`` writes the regenerated inventory so a reviewed
update can be committed; this script never edits the committed file.

The comparison is limited to package identities and versions. It is not a legal review: the
``review_status`` block of the inventory is reported, never changed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from packaging.utils import canonicalize_name

try:
    from scripts import generate_third_party_inventory as generator
except ImportError:  # pragma: no cover - direct ``python scripts/...`` execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import generate_third_party_inventory as generator


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUIREMENTS = ("requirements.txt", "requirements-ocr.txt")
LAUNCHER_MANIFEST = Path("packaging/launcher/Cargo.toml")


def default_cargo_manifests(repo_root: Path = REPO_ROOT) -> list[Path]:
    native = sorted((repo_root / "src/metroliza/native").glob("*/Cargo.toml"))
    return [*native, repo_root / LAUNCHER_MANIFEST]


def bundled_distributions(onedir: Path) -> dict[str, str]:
    """Return ``canonical name -> version`` for every ``*.dist-info`` bundled in the onedir."""
    bundled: dict[str, str] = {}
    for metadata_path in sorted(onedir.rglob("*.dist-info/METADATA")):
        name = version = None
        for line in metadata_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line:
                break
            key, _, value = line.partition(":")
            if key == "Name":
                name = value.strip()
            elif key == "Version":
                version = value.strip()
        if name and version:
            bundled[canonicalize_name(name)] = version
    return bundled


def _python_identities(inventory: dict[str, Any]) -> dict[str, str]:
    return {record["canonical_name"]: record["version"] for record in inventory["python"]["packages"]}


def _rust_identities(inventory: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {(record["name"], record["version"], record["source"]) for record in inventory["rust"]["packages"]}


def compare_inventories(
    committed: dict[str, Any], generated: dict[str, Any], bundled: dict[str, str]
) -> dict[str, Any]:
    """Return a receipt describing every difference between the committed and actual inventory."""
    committed_python = _python_identities(committed)
    actual_python = _python_identities(generated)
    committed_rust = _rust_identities(committed)
    actual_rust = _rust_identities(generated)
    python_diff = {
        "missing_from_inventory": sorted(f"{name}=={actual_python[name]}" for name in actual_python.keys() - committed_python.keys()),
        "not_in_build": sorted(f"{name}=={committed_python[name]}" for name in committed_python.keys() - actual_python.keys()),
        "version_differs": sorted(
            f"{name}: inventory {committed_python[name]}, build {actual_python[name]}"
            for name in committed_python.keys() & actual_python.keys()
            if committed_python[name] != actual_python[name]
        ),
        "bundled_metadata_unexplained": sorted(
            f"{name}=={version}" for name, version in bundled.items() if actual_python.get(name) != version
        ),
    }
    rust_diff = {
        "missing_from_inventory": sorted("@".join(key[:2]) + f" ({key[2]})" for key in actual_rust - committed_rust),
        "not_in_build": sorted("@".join(key[:2]) + f" ({key[2]})" for key in committed_rust - actual_rust),
    }
    problems = [
        *(f"python {kind}: {item}" for kind, items in python_diff.items() for item in items),
        *(f"rust {kind}: {item}" for kind, items in rust_diff.items() for item in items),
        *(f"python requirement root not installed: {name}" for name in generated["python"]["missing_requirement_roots"]),
        *(f"rust metadata: {warning}" for warning in generated["rust"]["warnings"]),
    ]
    return {
        "status": "FAIL" if problems else "PASS",
        "problems": problems,
        "python": python_diff | {"build_count": len(actual_python), "inventory_count": len(committed_python)},
        "rust": rust_diff | {"build_count": len(actual_rust), "inventory_count": len(committed_rust)},
        "bundled_dist_info_count": len(bundled),
        "review_status": committed.get("review_status"),
    }


def generate_build_inventory(
    *, onedir: Path, requirement_paths: list[Path], cargo_manifests: list[Path]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Regenerate the inventory of this environment, including bundled-only distributions."""
    bundled = bundled_distributions(onedir)
    payload = generator.generate_inventory(requirement_paths=requirement_paths, cargo_manifests=cargo_manifests)
    roots = list(payload["python"]["requirement_roots"])
    extra = sorted(set(bundled) - {canonicalize_name(name) for name in roots})
    packages, missing = generator.build_python_inventory([*roots, *extra])
    direct = {canonicalize_name(name) for name in roots}
    for record in packages:
        record["direct"] = record["canonical_name"] in direct
    payload["python"]["packages"] = packages
    payload["python"]["bundled_roots"] = extra
    payload["python"]["missing_requirement_roots"] = missing
    return payload, bundled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inventory", required=True, type=Path, help="Committed inventory to verify.")
    parser.add_argument("--onedir", required=True, type=Path, help="The built onedir that ships.")
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--generated", type=Path, help="Write the regenerated inventory here.")
    parser.add_argument("--requirements", action="append", type=Path)
    parser.add_argument("--cargo-manifest", action="append", type=Path)
    args = parser.parse_args(argv)

    if not args.onedir.is_dir():
        print(f"ERROR: onedir not found: {args.onedir}", file=sys.stderr)
        return 1
    committed = json.loads(args.inventory.read_text(encoding="utf-8"))
    generated, bundled = generate_build_inventory(
        onedir=args.onedir,
        requirement_paths=args.requirements or [REPO_ROOT / name for name in DEFAULT_REQUIREMENTS],
        cargo_manifests=args.cargo_manifest or default_cargo_manifests(),
    )
    if args.generated:
        args.generated.parent.mkdir(parents=True, exist_ok=True)
        args.generated.write_text(json.dumps(generated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = compare_inventories(committed, generated, bundled) | {"inventory": args.inventory.as_posix()}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for problem in receipt["problems"]:
        print(f"ERROR: {problem}", file=sys.stderr)
    print(f"Third-party inventory {receipt['status']}: {len(receipt['problems'])} difference(s); receipt {args.receipt}")
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

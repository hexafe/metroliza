"""Stage visible third-party notice bundles beside packaged release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NOTICE = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
DEFAULT_INVENTORY = REPO_ROOT / "docs/release_checks/third_party_inventory_260711.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_notice_bundle(target_dir: Path, *, notice: Path, inventory: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    copied_notice = target_dir / notice.name
    copied_inventory = target_dir / inventory.name
    shutil.copy2(notice, copied_notice)
    shutil.copy2(inventory, copied_inventory)
    manifest = {
        "files": [
            {"name": copied_notice.name, "sha256": _sha256(copied_notice)},
            {"name": copied_inventory.name, "sha256": _sha256(copied_inventory)},
        ]
    }
    manifest_path = target_dir / "NOTICE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def discover_release_artifacts(dist_dir: Path) -> tuple[Path, ...]:
    """Return executable/archive candidates that need a visible sibling notice bundle."""

    candidates: set[Path] = set()
    if not dist_dir.exists():
        return ()
    for pattern in ("*.exe", "*.zip", "*.tar.gz", "metroliza_P_*"):
        candidates.update(path for path in dist_dir.rglob(pattern) if path.is_file())
    return tuple(sorted(candidates))


def stage_release_notices(
    *,
    dist_dir: str | Path,
    artifacts: tuple[str | Path, ...] = (),
    notice_path: str | Path = DEFAULT_NOTICE,
    inventory_path: str | Path = DEFAULT_INVENTORY,
) -> tuple[Path, ...]:
    """Stage one root bundle plus an artifact-specific visible sidecar directory."""

    dist = Path(dist_dir).resolve()
    notice = Path(notice_path).resolve()
    inventory = Path(inventory_path).resolve()
    for required in (notice, inventory):
        if not required.is_file():
            raise FileNotFoundError(f"Required release notice input is missing: {required}")

    manifests = [_copy_notice_bundle(dist / "release-notices", notice=notice, inventory=inventory)]
    candidates = {Path(path).resolve() for path in artifacts}
    if not candidates:
        candidates.update(discover_release_artifacts(dist))
    for artifact in sorted(candidates):
        if not artifact.is_file():
            raise FileNotFoundError(f"Packaged artifact is missing: {artifact}")
        sidecar_dir = artifact.with_name(f"{artifact.name}.licenses")
        manifests.append(_copy_notice_bundle(sidecar_dir, notice=notice, inventory=inventory))
    return tuple(manifests)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", default="dist")
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--notice", default=str(DEFAULT_NOTICE))
    parser.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    args = parser.parse_args(argv)
    manifests = stage_release_notices(
        dist_dir=args.dist_dir,
        artifacts=tuple(args.artifact),
        notice_path=args.notice,
        inventory_path=args.inventory,
    )
    for manifest in manifests:
        print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

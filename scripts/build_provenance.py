"""Generate embedded build provenance and exact artifact hash sidecars."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
for import_root in (REPO_ROOT / "src", REPO_ROOT):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

from metroliza.app.build_provenance import BuildProvenance  # noqa: E402
from metroliza.app.version import VERSION_LABEL  # noqa: E402


BUILD_GIT_SHA_ENV = "METROLIZA_BUILD_GIT_SHA"
BUILD_GIT_DIRTY_ENV = "METROLIZA_BUILD_GIT_DIRTY"
BUILD_TIMESTAMP_ENV = "METROLIZA_BUILD_TIMESTAMP_UTC"
BUILD_PROVENANCE_PATH_ENV = "METROLIZA_BUILD_PROVENANCE_PATH"
_FULL_GIT_SHA = re.compile(r"[0-9a-fA-F]{40,64}")


def _run_git(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def inspect_git_identity(repo_root: str | Path = REPO_ROOT) -> tuple[str, bool]:
    """Return a full commit hash and whether tracked or untracked changes exist."""

    root = Path(repo_root).resolve()
    override_sha = os.getenv(BUILD_GIT_SHA_ENV)
    if override_sha is not None:
        git_sha = override_sha.strip()
    else:
        git_sha = _run_git(root, "rev-parse", "HEAD")
    if _FULL_GIT_SHA.fullmatch(git_sha) is None:
        raise ValueError("Build provenance requires a full hexadecimal Git commit hash")

    override_dirty = os.getenv(BUILD_GIT_DIRTY_ENV)
    if override_dirty is None:
        dirty = bool(_run_git(root, "status", "--porcelain", "--untracked-files=normal"))
    else:
        normalized = override_dirty.strip().lower()
        if normalized not in {"0", "1", "false", "true"}:
            raise ValueError(f"{BUILD_GIT_DIRTY_ENV} must be true/false or 1/0")
        dirty = normalized in {"1", "true"}
    return git_sha.lower(), dirty


def _build_timestamp() -> str:
    override = os.getenv(BUILD_TIMESTAMP_ENV)
    if override:
        return override.strip()
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def generate_build_provenance(
    output_path: str | Path,
    *,
    packager: str,
    repo_root: str | Path = REPO_ROOT,
) -> Path:
    """Create the manifest that is embedded into a packaged application."""

    normalized_packager = str(packager).strip().lower()
    if normalized_packager not in {"pyinstaller", "nuitka"}:
        raise ValueError("Packager must be 'pyinstaller' or 'nuitka'")
    git_sha, dirty = inspect_git_identity(repo_root)
    provenance = BuildProvenance(
        release_label=VERSION_LABEL,
        git_sha=git_sha,
        dirty=dirty,
        built_at_utc=_build_timestamp(),
        packager=normalized_packager,
        python_version=platform.python_version(),
    )
    payload = provenance.to_mapping()
    BuildProvenance.from_mapping(payload)
    return _write_json(Path(output_path).resolve(), payload)


def validate_build_provenance_manifest(
    manifest_path: str | Path,
    *,
    expected_packager: str | None = None,
    expected_release_label: str | None = None,
) -> BuildProvenance:
    """Strictly validate an embedded manifest against the active build contract."""

    manifest = Path(manifest_path).resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Build provenance manifest must contain a JSON object")
    provenance = BuildProvenance.from_mapping(payload)
    if expected_packager is not None and provenance.packager != expected_packager:
        raise ValueError(
            "Build provenance packager mismatch: "
            f"expected {expected_packager!r}, found {provenance.packager!r}"
        )
    if (
        expected_release_label is not None
        and provenance.release_label != expected_release_label
    ):
        raise ValueError(
            "Build provenance release mismatch: "
            f"expected {expected_release_label!r}, found {provenance.release_label!r}"
        )
    return provenance


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest for one exact artifact."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_artifact_provenance(
    manifest_path: str | Path,
    artifacts: Sequence[str | Path],
) -> tuple[Path, ...]:
    """Write one provenance sidecar for each explicitly named packaged binary."""

    manifest = Path(manifest_path).resolve()
    provenance = validate_build_provenance_manifest(manifest)
    payload = provenance.to_mapping()
    if not artifacts:
        raise ValueError("At least one explicit artifact path is required")

    sidecars = []
    for raw_artifact in artifacts:
        artifact = Path(raw_artifact).resolve()
        if not artifact.is_file():
            raise FileNotFoundError(f"Packaged artifact is missing: {artifact}")
        sidecar_payload = dict(payload)
        sidecar_payload["artifact"] = {
            "name": artifact.name,
            "sha256": sha256_file(artifact),
            "size_bytes": artifact.stat().st_size,
        }
        sidecar = artifact.with_name(f"{artifact.name}.provenance.json")
        sidecars.append(_write_json(sidecar, sidecar_payload))
    return tuple(sidecars)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="write an embeddable manifest")
    generate.add_argument("--output", required=True)
    generate.add_argument("--packager", choices=("pyinstaller", "nuitka"), required=True)
    generate.add_argument("--repo-root", default=str(REPO_ROOT))

    validate = subparsers.add_parser("validate", help="validate a manifest for this release")
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--packager", choices=("pyinstaller", "nuitka"), required=True)

    stage = subparsers.add_parser("stage", help="write exact artifact hash sidecars")
    stage.add_argument("--manifest", required=True)
    stage.add_argument("--artifact", action="append", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "generate":
        print(
            generate_build_provenance(
                args.output,
                packager=args.packager,
                repo_root=args.repo_root,
            )
        )
        return 0

    if args.command == "validate":
        provenance = validate_build_provenance_manifest(
            args.manifest,
            expected_packager=args.packager,
            expected_release_label=VERSION_LABEL,
        )
        print(provenance.release_label)
        return 0

    for sidecar in stage_artifact_provenance(args.manifest, args.artifact):
        print(sidecar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

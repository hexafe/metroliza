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
from metroliza.shared.release_identity import current_identity  # noqa: E402


BUILD_GIT_SHA_ENV = "METROLIZA_BUILD_GIT_SHA"
BUILD_GIT_DIRTY_ENV = "METROLIZA_BUILD_GIT_DIRTY"
BUILD_TIMESTAMP_ENV = "METROLIZA_BUILD_TIMESTAMP_UTC"
BUILD_PROVENANCE_PATH_ENV = "METROLIZA_BUILD_PROVENANCE_PATH"
ONEDIR_MANIFEST = Path("_internal/metroliza/app/build_provenance.json")
_FULL_GIT_SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})")


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
    override_dirty = os.getenv(BUILD_GIT_DIRTY_ENV)
    if (root / ".git").exists():
        git_sha = _run_git(root, "rev-parse", "HEAD")
        dirty = bool(_run_git(root, "status", "--porcelain", "--untracked-files=normal"))
        if override_sha is not None and override_sha.strip().lower() != git_sha:
            raise ValueError(f"{BUILD_GIT_SHA_ENV} disagrees with the checkout")
    else:
        if override_sha is None or override_dirty is None:
            raise ValueError("Source snapshots require explicit build Git SHA and dirty state")
        git_sha = override_sha.strip()
        dirty = _parse_dirty(override_dirty)
    if _FULL_GIT_SHA.fullmatch(git_sha) is None:
        raise ValueError("Build provenance requires a full hexadecimal Git commit hash")

    if override_dirty is not None and _parse_dirty(override_dirty) != dirty:
        raise ValueError(f"{BUILD_GIT_DIRTY_ENV} disagrees with the checkout")
    return git_sha.lower(), dirty


def _parse_dirty(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"0", "1", "false", "true"}:
        raise ValueError(f"{BUILD_GIT_DIRTY_ENV} must be true/false or 1/0")
    return normalized in {"1", "true"}


def _build_timestamp() -> str:
    override = os.getenv(BUILD_TIMESTAMP_ENV)
    if override:
        return override.strip()
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


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
        release_label=current_identity(Path(repo_root)).label,
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
    provenance = _decode_provenance(manifest.read_text(encoding="utf-8"))
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


def _decode_provenance(content: str | bytes) -> BuildProvenance:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("Build provenance manifest must contain a JSON object")
    return BuildProvenance.from_mapping(payload)


def validate_active_pyinstaller_provenance(
    manifest_path: str | Path,
    *,
    repo_root: Path = REPO_ROOT,
    require_attempt: bool = True,
) -> BuildProvenance:
    """Compare a new PyInstaller artifact's receipt to its live build inputs."""

    provenance = _validate_pyinstaller_source(manifest_path, repo_root)
    if provenance.python_version != platform.python_version():
        raise ValueError("Build provenance Python version mismatch")
    attempt_timestamp = os.getenv(BUILD_TIMESTAMP_ENV, "").strip()
    if require_attempt and not attempt_timestamp:
        raise ValueError(f"Current PyInstaller build requires {BUILD_TIMESTAMP_ENV}")
    if attempt_timestamp and provenance.built_at_utc != attempt_timestamp:
        raise ValueError("Build provenance timestamp does not match this build attempt")
    return provenance


def _validate_pyinstaller_source(manifest_path: str | Path, repo_root: Path) -> BuildProvenance:
    provenance = validate_build_provenance_manifest(
        manifest_path, expected_packager="pyinstaller",
        expected_release_label=current_identity(repo_root).label,
    )
    git_sha, dirty = inspect_git_identity(repo_root)
    if provenance.git_sha != git_sha:
        raise ValueError("Build provenance Git SHA mismatch")
    if provenance.dirty != dirty:
        raise ValueError("Build provenance dirty state mismatch")
    return provenance


def validate_onedir_provenance(onedir: Path, repo_root: Path = REPO_ROOT) -> BuildProvenance:
    """Read provenance from the exact existing onedir being wrapped."""

    provenance = _validate_pyinstaller_source(onedir / ONEDIR_MANIFEST, repo_root)
    launcher = onedir / "metroliza.exe"
    sidecar = json.loads(launcher.with_suffix(".exe.provenance.json").read_text(encoding="utf-8"))
    if not isinstance(sidecar, dict) or BuildProvenance.from_mapping(sidecar) != provenance:
        raise ValueError("Onedir embedded and sidecar provenance differ")
    if sidecar.get("artifact") != _artifact_identity(launcher):
        raise ValueError("Onedir provenance does not match the launcher bytes")
    return provenance


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest for one exact artifact."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_identity(artifact: Path) -> dict[str, object]:
    return {
        "name": artifact.name,
        "sha256": sha256_file(artifact),
        "size_bytes": artifact.stat().st_size,
    }


def _embedded_provenance(artifact: Path, *, wrapped: bool = False) -> BuildProvenance:
    """Read a PyInstaller onedir or onefile's own manifest before staging."""

    if artifact.stem == "metroliza":
        return validate_build_provenance_manifest(artifact.parent / ONEDIR_MANIFEST)

    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(artifact))
    expected_name = (
        (Path("metroliza_payload") / ONEDIR_MANIFEST).as_posix()
        if wrapped else ONEDIR_MANIFEST.relative_to("_internal").as_posix()
    )
    names = [name for name in archive.toc if name.replace("\\", "/") == expected_name]
    if len(names) != 1:
        raise ValueError(f"Expected one embedded build provenance manifest in {artifact}")
    return _decode_provenance(archive.extract(names[0]))


def stage_artifact_provenance(
    manifest_path: str | Path,
    artifacts: Sequence[str | Path],
    *,
    repo_root: Path = REPO_ROOT,
    onedir: Path | None = None,
) -> tuple[Path, ...]:
    """Write one provenance sidecar for each explicitly named packaged binary."""

    if not artifacts:
        raise ValueError("At least one explicit artifact path is required")
    manifest = Path(manifest_path).resolve()
    if onedir is None:
        # A direct spec invocation generates its own timestamp. Its exact embedded
        # manifest is the independent build-attempt evidence for staging.
        provenance = validate_active_pyinstaller_provenance(
            manifest, repo_root=repo_root, require_attempt=False,
        )
    else:
        if manifest != (onedir / ONEDIR_MANIFEST).resolve():
            raise ValueError("Wrapper provenance must be read from the exact onedir payload")
        provenance = validate_onedir_provenance(onedir, repo_root)
    payload = provenance.to_mapping()

    sidecars = {}
    for raw_artifact in artifacts:
        artifact = Path(raw_artifact).resolve()
        if not artifact.is_file():
            raise FileNotFoundError(f"Packaged artifact is missing: {artifact}")
        is_portable = artifact.name == current_identity(repo_root).portable_name
        if ((onedir is None or is_portable)
                and _embedded_provenance(artifact, wrapped=is_portable) != provenance):
            raise ValueError(f"Manifest does not match the embedded build provenance in {artifact}")
        sidecar_payload = dict(payload)
        sidecar_payload["artifact"] = _artifact_identity(artifact)
        sidecar = artifact.with_name(f"{artifact.name}.provenance.json")
        sidecars[sidecar] = sidecar_payload
    return tuple(_write_json(sidecar, payload) for sidecar, payload in sidecars.items())


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

    validate_onedir = subparsers.add_parser("validate-onedir", help="validate the onedir being wrapped")
    validate_onedir.add_argument("--onedir", type=Path, required=True)

    stage = subparsers.add_parser("stage", help="write exact artifact hash sidecars")
    stage.add_argument("--manifest", required=True)
    stage.add_argument("--artifact", action="append", required=True)
    stage.add_argument("--from-onedir", type=Path, help="Exact existing onedir being wrapped.")
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
        if args.packager == "pyinstaller":
            provenance = validate_active_pyinstaller_provenance(args.manifest)
        else:
            provenance = validate_build_provenance_manifest(
                args.manifest, expected_packager=args.packager,
                expected_release_label=current_identity(REPO_ROOT).label,
            )
        print(provenance.release_label)
        return 0

    if args.command == "validate-onedir":
        print(validate_onedir_provenance(args.onedir).release_label)
        return 0

    for sidecar in stage_artifact_provenance(args.manifest, args.artifact, onedir=args.from_onedir):
        print(sidecar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

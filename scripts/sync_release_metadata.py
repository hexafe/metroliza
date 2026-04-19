#!/usr/bin/env python3
"""Sync release metadata from VersionDate.py into user-facing docs."""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import re
import sys
from dataclasses import dataclass

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION_MODULE = REPO_ROOT / "VersionDate.py"
README_PATH = REPO_ROOT / "README.md"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"


@dataclass(frozen=True)
class ReleaseMetadata:
    release_version: str
    build: str
    version_label: str
    public_version_label: str
    highlight: str


@dataclass(frozen=True)
class UpdateResult:
    path: pathlib.Path
    changed: bool


def load_metadata() -> ReleaseMetadata:
    spec = importlib.util.spec_from_file_location("VersionDate", VERSION_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load VersionDate.py")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    missing = [
        name
        for name in ("RELEASE_VERSION", "VERSION_DATE", "CURRENT_RELEASE_HIGHLIGHT")
        if not hasattr(module, name)
    ]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(f"VersionDate.py missing required release fields: {names}")

    public_release_version = re.sub(r"rc\d+$", "", str(module.RELEASE_VERSION))
    return ReleaseMetadata(
        release_version=str(module.RELEASE_VERSION),
        build=str(module.VERSION_DATE),
        version_label=f"{module.RELEASE_VERSION}({module.VERSION_DATE})",
        public_version_label=f"{public_release_version} (build {module.VERSION_DATE})",
        highlight=str(module.CURRENT_RELEASE_HIGHLIGHT).strip(),
    )


def _replace_one(text: str, pattern: str, replacement: str, path: pathlib.Path) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"Expected one match for pattern in {path}: {pattern}")
    return updated


def sync_readme(meta: ReleaseMetadata, apply: bool) -> UpdateResult:
    text = README_PATH.read_text(encoding="utf-8")
    updated = _replace_one(
        text,
        r"^Current release highlight \(`[^`]+`(?:, build `\d+`)?\): .*$",
        f"Current release highlight (`{meta.public_version_label}`): {meta.highlight}",
        README_PATH,
    )
    updated = _replace_one(
        updated,
        r"^### Changelog highlights \(release `[^`]+`(?:, build `\d+`)?\)$",
        f"### Changelog highlights (release `{meta.public_version_label}`)",
        README_PATH,
    )

    changed = updated != text
    if apply and changed:
        README_PATH.write_text(updated, encoding="utf-8")
    return UpdateResult(path=README_PATH, changed=changed)


def sync_changelog(meta: ReleaseMetadata, apply: bool) -> UpdateResult:
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    updated = _replace_one(
        text,
        r"^## .+ — current version$",
        f"## {meta.public_version_label} — current version",
        CHANGELOG_PATH,
    )

    changed = updated != text
    if apply and changed:
        CHANGELOG_PATH.write_text(updated, encoding="utf-8")
    return UpdateResult(path=CHANGELOG_PATH, changed=changed)


def run_sync(apply: bool) -> int:
    metadata = load_metadata()
    results = [sync_readme(metadata, apply=apply), sync_changelog(metadata, apply=apply)]

    changed_files = [result.path for result in results if result.changed]
    mode = "Updated" if apply else "Out-of-sync"

    if changed_files:
        print(f"{mode} release metadata for:")
        for path in changed_files:
            print(f" - {path.relative_to(REPO_ROOT)}")
        return 1 if not apply else 0

    print("Release metadata is already in sync.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check consistency without writing files (fails if drift is detected).",
    )
    args = parser.parse_args()
    return run_sync(apply=not args.check)


if __name__ == "__main__":
    sys.exit(main())

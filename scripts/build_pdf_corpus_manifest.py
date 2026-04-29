"""Build a reproducible PDF corpus manifest for benchmark runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import strftime
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="PDF files or directories to scan recursively.")
    parser.add_argument("--output", required=True, help="Manifest JSON output path.")
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_pdfs(paths: list[str]) -> tuple[list[Path], list[Path]]:
    roots = [Path(path).expanduser().resolve() for path in paths]
    pdfs: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.lower() == ".pdf":
            pdfs.append(root)
        elif root.is_dir():
            pdfs.extend(sorted(root.rglob("*.pdf")))
    return sorted(dict.fromkeys(pdfs)), roots


def _relative_path(path: Path, roots: list[Path]) -> str:
    for root in roots:
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return path.name


def build_manifest(paths: list[str]) -> dict[str, Any]:
    pdfs, roots = _collect_pdfs(paths)
    entries: list[dict[str, Any]] = []
    sha_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}

    for index, path in enumerate(pdfs):
        stat = path.stat()
        sha = _sha256(path)
        relative = _relative_path(path, roots)
        group = relative.split("/", 1)[0] if "/" in relative else path.parent.name
        sha_counts[sha] = sha_counts.get(sha, 0) + 1
        group_counts[group] = group_counts.get(group, 0) + 1
        entries.append(
            {
                "index": index,
                "path": str(path),
                "relative_path": relative,
                "group": group,
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha,
            }
        )

    duplicate_sha256 = {
        sha: count for sha, count in sorted(sha_counts.items()) if count > 1
    }
    return {
        "created_at": strftime("%Y-%m-%dT%H:%M:%S%z"),
        "repo_root": str(REPO_ROOT),
        "input_paths": [str(root) for root in roots],
        "pdf_count": len(entries),
        "unique_sha256_count": len(sha_counts),
        "duplicate_sha256_count": sum(count - 1 for count in duplicate_sha256.values()),
        "group_counts": dict(sorted(group_counts.items())),
        "duplicate_sha256": duplicate_sha256,
        "entries": entries,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = build_manifest(args.paths)
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

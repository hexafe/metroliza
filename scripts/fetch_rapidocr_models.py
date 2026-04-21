#!/usr/bin/env python3
"""Fetch the vendored RapidOCR Latin model files with SHA256 verification."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.header_ocr_backend import RAPIDOCR_MODEL_ASSET_MANIFEST, default_rapidocr_model_dir


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_model(name: str, *, url: str, expected_sha256: str, output_dir: Path, force: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / name
    if output_path.exists() and not force:
        actual_sha256 = _sha256(output_path)
        if actual_sha256 == expected_sha256:
            print(f"ok existing {output_path}")
            return output_path
        raise SystemExit(
            f"{output_path} exists but has SHA256 {actual_sha256}; expected {expected_sha256}. "
            "Rerun with --force to replace it."
        )

    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    print(f"fetch {name}")
    with urlopen(url, timeout=120) as response, temp_path.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)

    actual_sha256 = _sha256(temp_path)
    if actual_sha256 != expected_sha256:
        temp_path.unlink(missing_ok=True)
        raise SystemExit(f"{name} SHA256 mismatch: got {actual_sha256}, expected {expected_sha256}")

    temp_path.replace(output_path)
    print(f"ok fetched {output_path}")
    return output_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(default_rapidocr_model_dir()),
        help="Destination directory for the vendored model files.",
    )
    parser.add_argument("--force", action="store_true", help="Replace existing model files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    for name, asset in RAPIDOCR_MODEL_ASSET_MANIFEST.items():
        fetch_model(
            name,
            url=str(asset["url"]),
            expected_sha256=str(asset["sha256"]),
            output_dir=output_dir,
            force=args.force,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

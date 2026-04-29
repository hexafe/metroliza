"""Render first-page CMM header OCR crops from a PDF corpus manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from time import strftime
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="PDF corpus manifest JSON.")
    parser.add_argument("--output-dir", required=True, help="Directory for rendered PNG crops.")
    parser.add_argument("--output", required=True, help="Crop manifest JSON output path.")
    parser.add_argument("--zoom", type=float, default=4.0, help="Render zoom. Default: 4.")
    parser.add_argument("--limit", type=int, default=0, help="Max PDFs to process. 0 means all.")
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Write progress to stderr every N PDFs. 0 disables progress.",
    )
    return parser


def _safe_stem(index: int, path: Path) -> str:
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in path.stem)
    return f"{index:05d}_{safe[:120]}"


def _load_entries(manifest_path: Path, limit: int) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries") or []
    if limit > 0:
        entries = entries[:limit]
    return list(entries)


def _render_crop(entry: dict[str, Any], index: int, output_dir: Path, zoom: float) -> dict[str, Any]:
    from modules.cmm_report_parser import CMMReportParser
    from modules.pdf_backend import require_pdf_backend

    pdf_backend = require_pdf_backend()
    pdf_path = Path(entry["path"])
    start = perf_counter()
    try:
        document = pdf_backend.open(str(pdf_path))
        try:
            page = document[0]
            selection = CMMReportParser._header_crop_selection(page)
            if selection is None:
                return {
                    "index": index,
                    "pdf_path": str(pdf_path),
                    "relative_path": entry.get("relative_path"),
                    "sha256": entry.get("sha256"),
                    "ok": False,
                    "error": "no_header_crop_selection",
                    "render_s": round(perf_counter() - start, 4),
                }

            matrix = pdf_backend.Matrix(zoom, zoom)
            clip = pdf_backend.Rect(*selection.bbox)
            pixmap = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
            image_path = output_dir / f"{_safe_stem(index, pdf_path)}.png"
            pixmap.save(str(image_path))
            return {
                "index": index,
                "pdf_path": str(pdf_path),
                "relative_path": entry.get("relative_path"),
                "group": entry.get("group"),
                "sha256": entry.get("sha256"),
                "ok": True,
                "image_path": str(image_path),
                "bbox": list(selection.bbox),
                "crop_source": selection.source,
                "candidate_count": selection.candidate_count,
                "selection_diagnostics": selection.diagnostics,
                "pixel_size": [int(pixmap.width), int(pixmap.height)],
                "zoom": zoom,
                "render_s": round(perf_counter() - start, 4),
            }
        finally:
            document.close()
    except Exception as exc:
        return {
            "index": index,
            "pdf_path": str(pdf_path),
            "relative_path": entry.get("relative_path"),
            "sha256": entry.get("sha256"),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "render_s": round(perf_counter() - start, 4),
        }


def build_crop_manifest(
    manifest_path: Path,
    output_dir: Path,
    zoom: float,
    limit: int,
    progress_every: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = _load_entries(manifest_path, limit)
    started = perf_counter()
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        rows.append(_render_crop(entry, index, output_dir, zoom))
        completed = len(rows)
        if progress_every > 0 and completed % progress_every == 0:
            print(
                f"crop progress: {completed}/{len(entries)} in {perf_counter() - started:.1f}s",
                file=sys.stderr,
                flush=True,
            )

    ok_rows = [row for row in rows if row.get("ok")]
    return {
        "created_at": strftime("%Y-%m-%dT%H:%M:%S%z"),
        "repo_root": str(REPO_ROOT),
        "source_manifest": str(manifest_path),
        "output_dir": str(output_dir),
        "zoom": zoom,
        "summary": {
            "requested_count": len(entries),
            "ok_count": len(ok_rows),
            "error_count": len(rows) - len(ok_rows),
            "total_wall_s": round(perf_counter() - started, 4),
            "sum_render_s": round(sum(float(row.get("render_s") or 0.0) for row in rows), 4),
        },
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_crop_manifest(
        Path(args.manifest).expanduser(),
        Path(args.output_dir).expanduser(),
        args.zoom,
        args.limit,
        args.progress_every,
    )
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

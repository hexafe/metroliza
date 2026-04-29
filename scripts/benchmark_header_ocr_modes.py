"""Benchmark Metroliza CMM metadata parsing modes on a PDF sample.

Examples:
  python scripts/benchmark_header_ocr_modes.py <reports-dir> --limit 5
  python scripts/benchmark_header_ocr_modes.py --manifest <local-corpus-manifest.json> --mode complete --limit 0
  METROLIZA_HEADER_OCR_ENGINE=openvino python scripts/benchmark_header_ocr_modes.py <reports-dir> --mode complete
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import perf_counter
from time import strftime
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the real CMMReportParser metadata path on a bounded PDF sample and "
            "emit JSON timing/metadata diagnostics. Default limit is intentionally "
            "small because complete OCR is slow."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="PDF files or directories to scan recursively for PDFs.",
    )
    parser.add_argument(
        "--manifest",
        help=(
            "Optional corpus manifest JSON with entries[].path. Paths from the manifest "
            "are combined with positional paths before sorting and limiting."
        ),
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=("light", "complete"),
        help="Metadata mode to run. Can be repeated. Defaults to light and complete.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of PDF files to benchmark after sorting. Use 0 for all. Default: 5.",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        help="Optional wall-time budget for the run. The current PDF finishes before stopping.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Write progress to stderr every N completed mode/PDF runs. Use 0 to disable.",
    )
    parser.add_argument(
        "--output",
        help="Optional JSON output path. Defaults to stdout.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON.",
    )
    return parser


def _collect_pdfs(paths: list[str]) -> list[Path]:
    pdfs: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path.is_file() and path.suffix.lower() == ".pdf":
            pdfs.append(path)
        elif path.is_dir():
            pdfs.extend(sorted(path.rglob("*.pdf")))
    return sorted(dict.fromkeys(pdfs))


def _collect_manifest_pdfs(manifest_path: str | None) -> tuple[list[Path], dict[Path, str]]:
    if not manifest_path:
        return [], {}
    manifest = json.loads(Path(manifest_path).expanduser().read_text(encoding="utf-8"))
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"Corpus manifest {manifest_path} does not contain an entries list.")

    pdfs: list[Path] = []
    groups: dict[Path, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        path = Path(str(entry["path"])).expanduser().resolve()
        if path.is_file() and path.suffix.lower() == ".pdf":
            pdfs.append(path)
            group = entry.get("group")
            if group:
                groups[path] = str(group)
    return pdfs, groups


def _manifest_group_counts(pdfs: list[Path], groups: dict[Path, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pdf in pdfs:
        group = groups.get(pdf, pdf.parent.name)
        counts[group] = counts.get(group, 0) + 1
    return dict(sorted(counts.items()))


def _env_snapshot() -> dict[str, str | None]:
    names = (
        "METROLIZA_HEADER_OCR_BACKEND",
        "METROLIZA_HEADER_OCR_ENGINE",
        "METROLIZA_HEADER_OCR_ACCELERATOR",
        "METROLIZA_HEADER_OCR_DEVICE_ID",
        "METROLIZA_HEADER_OCR_CACHE_DIR",
        "METROLIZA_HEADER_OCR_MODEL_DIR",
        "METROLIZA_HEADER_OCR_ZOOM",
        "METROLIZA_HEADER_OCR_THREADS",
    )
    return {name: os.getenv(name) for name in names}


def _runtime_config_summary() -> dict[str, Any]:
    from modules.header_ocr_backend import rapidocr_latin_runtime_config_from_env

    try:
        runtime_config = rapidocr_latin_runtime_config_from_env()
    except Exception as exc:
        return {
            "engine": None,
            "accelerator": None,
            "params": {},
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "engine": runtime_config.engine,
        "accelerator": runtime_config.accelerator,
        "params": runtime_config.params,
        "error": None,
    }


def _metadata_summary(result: Any) -> dict[str, Any]:
    metadata = result.metadata
    return {
        "reference": metadata.reference,
        "report_date": metadata.report_date,
        "report_time": metadata.report_time,
        "part_name": metadata.part_name,
        "revision": metadata.revision,
        "stats_count_raw": metadata.stats_count_raw,
        "stats_count_int": metadata.stats_count_int,
        "sample_number": metadata.sample_number,
        "operator_name": metadata.operator_name,
        "comment": metadata.comment,
        "field_sources": metadata.metadata_json.get("field_sources") or {},
        "warnings": [warning.code for warning in metadata.warnings],
    }


def _run_one(pdf_path: Path, mode: str) -> dict[str, Any]:
    from modules.cmm_report_parser import CMMReportParser

    parser = CMMReportParser(str(pdf_path), ":memory:", metadata_parsing_mode=mode)
    start = perf_counter()
    try:
        parser.open_report()
        result = parser.extract_metadata()
        wall_s = perf_counter() - start
        return {
            "pdf_path": str(pdf_path),
            "file_name": pdf_path.name,
            "mode": mode,
            "ok": True,
            "wall_s": round(wall_s, 4),
            "stage_timings_s": dict(parser.stage_timings_s),
            "header_diagnostics": dict(parser._header_extraction_diagnostics or {}),
            "metadata": _metadata_summary(result),
        }
    except Exception as exc:
        wall_s = perf_counter() - start
        return {
            "pdf_path": str(pdf_path),
            "file_name": pdf_path.name,
            "mode": mode,
            "ok": False,
            "wall_s": round(wall_s, 4),
            "error": f"{type(exc).__name__}: {exc}",
            "stage_timings_s": dict(getattr(parser, "stage_timings_s", {}) or {}),
            "header_diagnostics": dict(getattr(parser, "_header_extraction_diagnostics", {}) or {}),
        }


def _top_level_group(pdf_path: Path, roots: list[Path]) -> str:
    for root in roots:
        try:
            relative = pdf_path.relative_to(root)
        except ValueError:
            continue
        if len(relative.parts) > 1:
            return relative.parts[0]
        return root.name
    return pdf_path.parent.name


def _group_counts(pdfs: list[Path], roots: list[Path]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pdf in pdfs:
        group = _top_level_group(pdf, roots)
        counts[group] = counts.get(group, 0) + 1
    return dict(sorted(counts.items()))


def build_payload(
    paths: list[str],
    modes: list[str],
    limit: int,
    manifest: str | None = None,
    max_seconds: float | None = None,
    progress_every: int = 25,
) -> dict[str, Any]:
    started_at = strftime("%Y-%m-%dT%H:%M:%S%z")
    started = perf_counter()
    input_roots = [Path(path).expanduser().resolve() for path in paths]
    manifest_pdfs, manifest_groups = _collect_manifest_pdfs(manifest)
    pdfs = sorted(dict.fromkeys(_collect_pdfs(paths) + manifest_pdfs))
    selected_pdfs = pdfs if limit == 0 else pdfs[: max(0, limit)]
    results: list[dict[str, Any]] = []
    stopped_due_to_budget = False
    total_requested = len(modes) * len(selected_pdfs)

    for mode in modes:
        for pdf_path in selected_pdfs:
            results.append(_run_one(pdf_path, mode))
            completed = len(results)
            if progress_every > 0 and completed % progress_every == 0:
                elapsed = perf_counter() - started
                print(
                    f"benchmark progress: {completed}/{total_requested} "
                    f"runs in {elapsed:.1f}s",
                    file=sys.stderr,
                    flush=True,
                )
            if max_seconds is not None and perf_counter() - started >= max_seconds:
                stopped_due_to_budget = True
                break
        if stopped_due_to_budget:
            break

    summary: dict[str, Any] = {
        "pdfs_found": len(pdfs),
        "pdfs_selected": len(selected_pdfs),
        "modes": modes,
        "requested_mode_pdf_runs": total_requested,
        "completed_mode_pdf_runs": len(results),
        "ok_count": sum(1 for result in results if result["ok"]),
        "error_count": sum(1 for result in results if not result["ok"]),
        "stopped_due_to_budget": stopped_due_to_budget,
        "total_wall_s": round(perf_counter() - started, 4),
        "selected_group_counts": _manifest_group_counts(selected_pdfs, manifest_groups)
        if manifest_groups
        else _group_counts(selected_pdfs, input_roots),
    }
    by_mode: dict[str, dict[str, Any]] = {}
    for mode in modes:
        mode_results = [result for result in results if result["mode"] == mode]
        total_wall_s = sum(float(result["wall_s"]) for result in mode_results)
        by_mode[mode] = {
            "count": len(mode_results),
            "ok_count": sum(1 for result in mode_results if result["ok"]),
            "total_wall_s": round(total_wall_s, 4),
            "avg_wall_s": round(total_wall_s / len(mode_results), 4) if mode_results else None,
        }
    summary["by_mode"] = by_mode

    return {
        "environment": {
            "python_executable": sys.executable,
            "repo_root": str(REPO_ROOT),
            "started_at": started_at,
            "env": _env_snapshot(),
            "header_ocr_runtime_config": _runtime_config_summary(),
        },
        "input": {
            "paths": paths,
            "manifest": manifest,
            "selected_pdfs": [str(path) for path in selected_pdfs],
            "limit": limit,
            "max_seconds": max_seconds,
        },
        "summary": summary,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.paths and not args.manifest:
        raise SystemExit("Provide at least one PDF/directory path or --manifest.")
    modes = args.mode or ["light", "complete"]
    payload = build_payload(
        args.paths,
        modes,
        args.limit,
        manifest=args.manifest,
        max_seconds=args.max_seconds,
        progress_every=args.progress_every,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=None if args.compact else 2, default=str)
    if args.output:
        Path(args.output).expanduser().write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

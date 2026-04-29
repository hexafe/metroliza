"""Run repeatable OpenVINO CPU OCR tuning benchmarks.

The benchmark output directory is expected to live under ignored local artifact
paths because per-report JSON includes local report paths.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from time import strftime
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_SCRIPT = REPO_ROOT / "scripts" / "benchmark_header_ocr_modes.py"


DEFAULT_VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "name": "openvino_t4_default",
        "env": {
            "METROLIZA_HEADER_OCR_ENGINE": "openvino",
            "METROLIZA_HEADER_OCR_THREADS": "4",
        },
    },
    {
        "name": "openvino_t2_default",
        "env": {
            "METROLIZA_HEADER_OCR_ENGINE": "openvino",
            "METROLIZA_HEADER_OCR_THREADS": "2",
        },
    },
    {
        "name": "openvino_t6_default",
        "env": {
            "METROLIZA_HEADER_OCR_ENGINE": "openvino",
            "METROLIZA_HEADER_OCR_THREADS": "6",
        },
    },
    {
        "name": "openvino_t4_latency",
        "env": {
            "METROLIZA_HEADER_OCR_ENGINE": "openvino",
            "METROLIZA_HEADER_OCR_THREADS": "4",
            "METROLIZA_HEADER_OCR_OPENVINO_PERFORMANCE_HINT": "LATENCY",
        },
    },
    {
        "name": "openvino_t4_throughput",
        "env": {
            "METROLIZA_HEADER_OCR_ENGINE": "openvino",
            "METROLIZA_HEADER_OCR_THREADS": "4",
            "METROLIZA_HEADER_OCR_OPENVINO_PERFORMANCE_HINT": "THROUGHPUT",
        },
    },
    {
        "name": "openvino_t4_latency_streams1",
        "env": {
            "METROLIZA_HEADER_OCR_ENGINE": "openvino",
            "METROLIZA_HEADER_OCR_THREADS": "4",
            "METROLIZA_HEADER_OCR_OPENVINO_PERFORMANCE_HINT": "LATENCY",
            "METROLIZA_HEADER_OCR_OPENVINO_NUM_STREAMS": "1",
        },
    },
    {
        "name": "openvino_t4_throughput_streams2",
        "env": {
            "METROLIZA_HEADER_OCR_ENGINE": "openvino",
            "METROLIZA_HEADER_OCR_THREADS": "4",
            "METROLIZA_HEADER_OCR_OPENVINO_PERFORMANCE_HINT": "THROUGHPUT",
            "METROLIZA_HEADER_OCR_OPENVINO_NUM_STREAMS": "2",
        },
    },
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Corpus manifest JSON with entries[].path.")
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="PDF limit for each variant. Use 0 for the full manifest. Default: 20.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Ignored local output directory for per-variant JSON and summary files.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=5,
        help="Forwarded to benchmark_header_ocr_modes.py. Use 0 to disable progress.",
    )
    parser.add_argument(
        "--variant",
        action="append",
        choices=tuple(variant["name"] for variant in DEFAULT_VARIANTS),
        help="Variant to run. Can be repeated. Defaults to all variants.",
    )
    return parser


def _load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _variant_summary(name: str, payload_path: Path, returncode: int) -> dict[str, Any]:
    row: dict[str, Any] = {
        "variant": name,
        "returncode": returncode,
        "ok": False,
        "output": str(payload_path),
    }
    if returncode != 0 or not payload_path.exists():
        return row

    payload = _load_payload(payload_path)
    complete = ((payload.get("summary") or {}).get("by_mode") or {}).get("complete") or {}
    results = payload.get("results") or []
    ocr_runtime = sum(
        float((result.get("header_diagnostics") or {}).get("header_ocr_runtime_s") or 0.0)
        for result in results
    )
    row.update(
        {
            "ok": (payload.get("summary") or {}).get("error_count") == 0,
            "pdfs_selected": (payload.get("summary") or {}).get("pdfs_selected"),
            "completed_mode_pdf_runs": (payload.get("summary") or {}).get(
                "completed_mode_pdf_runs"
            ),
            "total_wall_s": complete.get("total_wall_s"),
            "avg_wall_s": complete.get("avg_wall_s"),
            "sum_header_ocr_runtime_s": round(ocr_runtime, 4),
            "avg_header_ocr_runtime_s": round(ocr_runtime / len(results), 4)
            if results
            else None,
            "runtime_config": (payload.get("environment") or {}).get(
                "header_ocr_runtime_config"
            ),
        }
    )
    return row


def run_variant(
    *,
    variant: dict[str, Any],
    manifest: str,
    limit: int,
    output_dir: Path,
    progress_every: int,
) -> dict[str, Any]:
    output_path = output_dir / f"{variant['name']}.json"
    env = os.environ.copy()
    env.update({key: str(value) for key, value in variant["env"].items()})
    command = [
        sys.executable,
        str(BENCHMARK_SCRIPT),
        "--manifest",
        manifest,
        "--mode",
        "complete",
        "--limit",
        str(limit),
        "--progress-every",
        str(progress_every),
        "--output",
        str(output_path),
    ]
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env, check=False)
    return _variant_summary(variant["name"], output_path, completed.returncode)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_names = set(args.variant or [variant["name"] for variant in DEFAULT_VARIANTS])
    variants = [variant for variant in DEFAULT_VARIANTS if variant["name"] in selected_names]
    rows = [
        run_variant(
            variant=variant,
            manifest=args.manifest,
            limit=args.limit,
            output_dir=output_dir,
            progress_every=args.progress_every,
        )
        for variant in variants
    ]
    successful = [row for row in rows if row.get("ok") and row.get("total_wall_s") is not None]
    fastest_wall = min(successful, key=lambda row: float(row["total_wall_s"])) if successful else None
    fastest_ocr = (
        min(successful, key=lambda row: float(row["sum_header_ocr_runtime_s"]))
        if successful
        else None
    )
    summary = {
        "created_at": strftime("%Y-%m-%dT%H:%M:%S%z"),
        "manifest": args.manifest,
        "limit": args.limit,
        "variant_count": len(rows),
        "ok_count": sum(1 for row in rows if row.get("ok")),
        "fastest_wall_variant": fastest_wall["variant"] if fastest_wall else None,
        "fastest_ocr_variant": fastest_ocr["variant"] if fastest_ocr else None,
        "rows": rows,
    }
    summary_path = output_dir / "matrix_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(row.get("ok") for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

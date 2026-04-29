"""Benchmark RapidOCR runtime engines on pre-rendered header crop images."""

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crop-manifest", required=True, help="Crop manifest JSON.")
    parser.add_argument("--output", required=True, help="OCR result JSON output path.")
    parser.add_argument("--limit", type=int, default=0, help="Max crop rows. 0 means all.")
    parser.add_argument("--threads", type=int, help="Override OCR thread count.")
    parser.add_argument("--max-seconds", type=float, help="Optional wall-time budget.")
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Write progress to stderr every N OCR runs. 0 disables progress.",
    )
    return parser


def _env_snapshot() -> dict[str, str | None]:
    names = (
        "METROLIZA_HEADER_OCR_ENGINE",
        "METROLIZA_HEADER_OCR_ACCELERATOR",
        "METROLIZA_HEADER_OCR_DEVICE_ID",
        "METROLIZA_HEADER_OCR_CACHE_DIR",
        "METROLIZA_HEADER_OCR_MODEL_DIR",
        "METROLIZA_HEADER_OCR_OPENVINO_PERFORMANCE_HINT",
        "METROLIZA_HEADER_OCR_OPENVINO_NUM_STREAMS",
        "METROLIZA_HEADER_OCR_TENSORRT_FP16",
        "METROLIZA_HEADER_OCR_TENSORRT_INT8",
        "METROLIZA_HEADER_OCR_TENSORRT_FORCE_REBUILD",
    )
    return {name: os.getenv(name) for name in names}


def _module_versions() -> dict[str, Any]:
    modules: dict[str, Any] = {}
    for name in ("rapidocr", "onnxruntime", "openvino", "tensorrt", "cv2", "numpy"):
        try:
            import importlib
            import importlib.util

            spec = importlib.util.find_spec(name)
            if spec is None:
                modules[name] = None
                continue
            module = importlib.import_module(name)
            modules[name] = {
                "origin": spec.origin,
                "version": getattr(module, "__version__", None),
            }
        except Exception as exc:
            modules[name] = {"error": f"{type(exc).__name__}: {exc}"}
    return modules


def _record_payload(record: Any) -> dict[str, Any]:
    return {
        "text": record.text,
        "confidence": record.confidence,
        "box": record.box,
        "source": record.source,
    }


def _load_crop_rows(crop_manifest_path: Path, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads(crop_manifest_path.read_text(encoding="utf-8"))
    rows = [row for row in manifest.get("rows") or [] if row.get("ok")]
    if limit > 0:
        rows = rows[:limit]
    return manifest, rows


def build_payload(
    crop_manifest_path: Path,
    limit: int,
    threads: int | None,
    max_seconds: float | None,
    progress_every: int,
) -> dict[str, Any]:
    from modules.header_ocr_backend import (
        RapidOcrLatinBackendConfig,
        default_rapidocr_latin_model_paths,
        get_cached_rapidocr_latin_backend,
        rapidocr_latin_runtime_config_from_env,
    )

    crop_manifest, crop_rows = _load_crop_rows(crop_manifest_path, limit)
    runtime_config = rapidocr_latin_runtime_config_from_env(ocr_thread_count=threads)
    backend = get_cached_rapidocr_latin_backend(
        RapidOcrLatinBackendConfig(
            model_paths=default_rapidocr_latin_model_paths(
                os.getenv("METROLIZA_HEADER_OCR_MODEL_DIR") or None
            ),
            params=runtime_config.params,
        )
    )

    rows: list[dict[str, Any]] = []
    started = perf_counter()
    stopped_due_to_budget = False
    for crop_row in crop_rows:
        image_path = Path(crop_row["image_path"])
        start = perf_counter()
        try:
            run = backend.recognize(image_path)
            ocr_s = perf_counter() - start
            rows.append(
                {
                    "index": crop_row.get("index"),
                    "pdf_path": crop_row.get("pdf_path"),
                    "relative_path": crop_row.get("relative_path"),
                    "group": crop_row.get("group"),
                    "sha256": crop_row.get("sha256"),
                    "image_path": str(image_path),
                    "ok": True,
                    "ocr_s": round(ocr_s, 4),
                    "record_count": len(run.records),
                    "records": [_record_payload(record) for record in run.records],
                    "diagnostics": run.diagnostics,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "index": crop_row.get("index"),
                    "pdf_path": crop_row.get("pdf_path"),
                    "relative_path": crop_row.get("relative_path"),
                    "group": crop_row.get("group"),
                    "sha256": crop_row.get("sha256"),
                    "image_path": str(image_path),
                    "ok": False,
                    "ocr_s": round(perf_counter() - start, 4),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

        completed = len(rows)
        if progress_every > 0 and completed % progress_every == 0:
            print(
                f"ocr crop progress: {completed}/{len(crop_rows)} in {perf_counter() - started:.1f}s",
                file=sys.stderr,
                flush=True,
            )
        if max_seconds is not None and perf_counter() - started >= max_seconds:
            stopped_due_to_budget = True
            break

    ok_rows = [row for row in rows if row.get("ok")]
    sum_ocr = sum(float(row.get("ocr_s") or 0.0) for row in rows)
    return {
        "created_at": strftime("%Y-%m-%dT%H:%M:%S%z"),
        "repo_root": str(REPO_ROOT),
        "source_crop_manifest": str(crop_manifest_path),
        "crop_manifest_summary": crop_manifest.get("summary"),
        "environment": {
            "python_executable": sys.executable,
            "python_version": sys.version,
            "env": _env_snapshot(),
            "modules": _module_versions(),
            "runtime_config": {
                "engine": runtime_config.engine,
                "accelerator": runtime_config.accelerator,
                "params": runtime_config.params,
            },
        },
        "summary": {
            "requested_count": len(crop_rows),
            "completed_count": len(rows),
            "ok_count": len(ok_rows),
            "error_count": len(rows) - len(ok_rows),
            "stopped_due_to_budget": stopped_due_to_budget,
            "total_wall_s": round(perf_counter() - started, 4),
            "sum_ocr_s": round(sum_ocr, 4),
            "avg_ocr_s": round(sum_ocr / len(rows), 4) if rows else None,
        },
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        Path(args.crop_manifest).expanduser(),
        args.limit,
        args.threads,
        args.max_seconds,
        args.progress_every,
    )
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

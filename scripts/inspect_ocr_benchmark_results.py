"""Summarize benchmark_header_ocr_modes.py JSON output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark_json", help="JSON produced by benchmark_header_ocr_modes.py")
    parser.add_argument("--output", help="Optional summary JSON output path.")
    return parser


def _count_values(results: list[dict[str, Any]], dotted_key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    key_parts = dotted_key.split(".")
    for result in results:
        value: Any = result
        for key in key_parts:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        normalized = str(value) if value not in (None, "") else "<empty>"
        counts[normalized] = counts.get(normalized, 0) + 1
    return dict(sorted(counts.items()))


def _field_null_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    fields = (
        "reference",
        "report_date",
        "report_time",
        "part_name",
        "revision",
        "stats_count_raw",
        "sample_number",
        "operator_name",
        "comment",
    )
    counts = {field: 0 for field in fields}
    for result in results:
        metadata = result.get("metadata") or {}
        for field in fields:
            if metadata.get(field) in (None, ""):
                counts[field] += 1
    return counts


def _warning_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        metadata = result.get("metadata") or {}
        for warning in metadata.get("warnings") or []:
            counts[str(warning)] = counts.get(str(warning), 0) + 1
    return dict(sorted(counts.items()))


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results") or []
    by_mode: dict[str, dict[str, Any]] = {}
    for mode in sorted({str(result.get("mode")) for result in results}):
        mode_results = [result for result in results if str(result.get("mode")) == mode]
        ok_results = [result for result in mode_results if result.get("ok")]
        total_wall = sum(float(result.get("wall_s") or 0.0) for result in mode_results)
        ocr_runtime = sum(
            float((result.get("header_diagnostics") or {}).get("header_ocr_runtime_s") or 0.0)
            for result in mode_results
        )
        by_mode[mode] = {
            "count": len(mode_results),
            "ok_count": len(ok_results),
            "error_count": len(mode_results) - len(ok_results),
            "total_wall_s": round(total_wall, 4),
            "avg_wall_s": round(total_wall / len(mode_results), 4) if mode_results else None,
            "sum_header_ocr_runtime_s": round(ocr_runtime, 4),
            "avg_header_ocr_runtime_s": round(ocr_runtime / len(mode_results), 4)
            if mode_results
            else None,
            "header_extraction_modes": _count_values(
                mode_results, "header_diagnostics.header_extraction_mode"
            ),
            "header_ocr_errors": _count_values(mode_results, "header_diagnostics.header_ocr_error"),
            "field_null_counts": _field_null_counts(mode_results),
            "warning_counts": _warning_counts(mode_results),
        }

    return {
        "source_file": payload.get("input"),
        "environment": payload.get("environment"),
        "summary": payload.get("summary"),
        "by_mode": by_mode,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = json.loads(Path(args.benchmark_json).read_text(encoding="utf-8"))
    summary = summarize(payload)
    text = json.dumps(summary, ensure_ascii=False, indent=2, default=str)
    if args.output:
        Path(args.output).expanduser().write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

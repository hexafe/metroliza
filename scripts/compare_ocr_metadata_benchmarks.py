"""Compare two benchmark_header_ocr_modes.py metadata benchmark JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FIELDS = (
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", required=True, help="Left benchmark JSON, e.g. light.")
    parser.add_argument("--right", required=True, help="Right benchmark JSON, e.g. complete.")
    parser.add_argument("--output", help="Optional comparison JSON output path.")
    return parser


def _load_results(path: str) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    results = payload.get("results") or []
    return {str(result["pdf_path"]): result for result in results if result.get("ok")}


def _value(result: dict[str, Any], field: str) -> Any:
    return (result.get("metadata") or {}).get(field)


def _source(result: dict[str, Any], field: str) -> Any:
    return ((result.get("metadata") or {}).get("field_sources") or {}).get(field)


def compare(left_path: str, right_path: str) -> dict[str, Any]:
    left_results = _load_results(left_path)
    right_results = _load_results(right_path)
    common_paths = sorted(set(left_results).intersection(right_results))
    left_only = sorted(set(left_results).difference(right_results))
    right_only = sorted(set(right_results).difference(left_results))

    field_summary: dict[str, dict[str, int]] = {}
    examples: dict[str, list[dict[str, Any]]] = {field: [] for field in FIELDS}
    for field in FIELDS:
        summary = {
            "same": 0,
            "different": 0,
            "left_empty_right_filled": 0,
            "left_filled_right_empty": 0,
            "both_empty": 0,
            "source_changed": 0,
        }
        for path in common_paths:
            left = left_results[path]
            right = right_results[path]
            left_value = _value(left, field)
            right_value = _value(right, field)
            left_empty = left_value in (None, "")
            right_empty = right_value in (None, "")
            if left_value == right_value:
                summary["same"] += 1
            else:
                summary["different"] += 1
                if len(examples[field]) < 10:
                    examples[field].append(
                        {
                            "pdf_path": path,
                            "left": left_value,
                            "right": right_value,
                            "left_source": _source(left, field),
                            "right_source": _source(right, field),
                        }
                    )
            if left_empty and right_empty:
                summary["both_empty"] += 1
            elif left_empty and not right_empty:
                summary["left_empty_right_filled"] += 1
            elif not left_empty and right_empty:
                summary["left_filled_right_empty"] += 1
            if _source(left, field) != _source(right, field):
                summary["source_changed"] += 1
        field_summary[field] = summary

    return {
        "left": left_path,
        "right": right_path,
        "common_count": len(common_paths),
        "left_only_count": len(left_only),
        "right_only_count": len(right_only),
        "left_only": left_only[:20],
        "right_only": right_only[:20],
        "field_summary": field_summary,
        "examples": examples,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = compare(args.left, args.right)
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.output:
        Path(args.output).expanduser().write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

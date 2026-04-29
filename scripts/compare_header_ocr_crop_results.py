"""Compare two benchmark_header_ocr_crops.py result files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", required=True, help="Left crop OCR result JSON.")
    parser.add_argument("--right", required=True, help="Right crop OCR result JSON.")
    parser.add_argument("--output", help="Optional comparison JSON output path.")
    return parser


def _load_rows(path: str) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    return {str(row["image_path"]): row for row in rows if row.get("ok")}


def _texts(row: dict[str, Any]) -> list[str]:
    return [str(record.get("text") or "") for record in row.get("records") or []]


def compare(left_path: str, right_path: str) -> dict[str, Any]:
    left = _load_rows(left_path)
    right = _load_rows(right_path)
    common = sorted(set(left).intersection(right))
    rows: list[dict[str, Any]] = []
    record_count_diffs = 0
    text_diffs = 0
    left_sum = 0.0
    right_sum = 0.0
    for image_path in common:
        left_row = left[image_path]
        right_row = right[image_path]
        left_sum += float(left_row.get("ocr_s") or 0.0)
        right_sum += float(right_row.get("ocr_s") or 0.0)
        left_texts = _texts(left_row)
        right_texts = _texts(right_row)
        record_count_diff = len(left_texts) != len(right_texts)
        text_diff = left_texts != right_texts
        if record_count_diff:
            record_count_diffs += 1
        if text_diff:
            text_diffs += 1
        if record_count_diff or text_diff:
            rows.append(
                {
                    "image_path": image_path,
                    "pdf_path": left_row.get("pdf_path"),
                    "left_ocr_s": left_row.get("ocr_s"),
                    "right_ocr_s": right_row.get("ocr_s"),
                    "left_record_count": len(left_texts),
                    "right_record_count": len(right_texts),
                    "left_texts": left_texts,
                    "right_texts": right_texts,
                }
            )

    return {
        "left": left_path,
        "right": right_path,
        "common_count": len(common),
        "left_only_count": len(set(left).difference(right)),
        "right_only_count": len(set(right).difference(left)),
        "left_sum_ocr_s": round(left_sum, 4),
        "right_sum_ocr_s": round(right_sum, 4),
        "left_avg_ocr_s": round(left_sum / len(common), 4) if common else None,
        "right_avg_ocr_s": round(right_sum / len(common), 4) if common else None,
        "speedup_ratio": round(left_sum / right_sum, 4) if right_sum else None,
        "record_count_diff_files": record_count_diffs,
        "text_diff_files": text_diffs,
        "diff_examples": rows[:25],
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

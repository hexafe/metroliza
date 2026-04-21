#!/usr/bin/env python3
"""Probe OCR backends on first-page CMM report header crops."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import fitz
except ImportError as exc:  # pragma: no cover - dependency failure path
    raise SystemExit("PyMuPDF is required: python -m pip install PyMuPDF") from exc

from modules.header_ocr_backend import (
    RapidOcrLatinBackend,
    RapidOcrLatinBackendConfig,
    default_rapidocr_latin_model_paths,
    missing_rapidocr_latin_model_paths,
)
from modules.header_ocr_corrections import postprocess_header_ocr_items
from modules.header_ocr_geometry import convert_ocr_records_to_header_items, select_header_crop


DEFAULT_ZOOM = 4.0


@dataclass(frozen=True)
class HeaderCrop:
    pdf_path: Path
    bbox: tuple[float, float, float, float]
    bbox_source: str
    bbox_diagnostics: dict[str, Any]
    zoom: float
    pixmap: Any


def default_report_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "example_reports" / "extracted"


def _bbox_tuple(rect: Any) -> tuple[float, float, float, float]:
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def render_header_crop(pdf_path: Path, zoom: float) -> HeaderCrop:
    doc = fitz.open(pdf_path)
    try:
        if doc.page_count == 0:
            raise ValueError(f"{pdf_path} has no pages")
        page = doc[0]
        selection = select_header_crop(page)
        bbox = fitz.Rect(*selection.bbox)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=bbox, alpha=False)
    finally:
        doc.close()

    return HeaderCrop(
        pdf_path=pdf_path,
        bbox=_bbox_tuple(bbox),
        bbox_source=selection.source,
        bbox_diagnostics=selection.diagnostics,
        zoom=zoom,
        pixmap=pixmap,
    )


def _lines_from_words(words: list[tuple[Any, ...]]) -> list[str]:
    if not words:
        return []

    sorted_words = sorted(words, key=lambda word: (round(float(word[1]), 1), float(word[0])))
    lines: list[list[str]] = []
    current_line: list[str] = []
    current_y: float | None = None

    for word in sorted_words:
        y = float(word[1])
        text = str(word[4]).strip()
        if not text:
            continue
        if current_y is None or abs(y - current_y) <= 4.0:
            current_line.append(text)
            current_y = y if current_y is None else (current_y + y) / 2
            continue
        lines.append(current_line)
        current_line = [text]
        current_y = y

    if current_line:
        lines.append(current_line)

    return [" ".join(line) for line in lines]


def run_pymupdf_tesseract(crop: HeaderCrop, language: str) -> dict[str, Any]:
    ocr_pdf = crop.pixmap.pdfocr_tobytes(language=language)
    ocr_doc = fitz.open(stream=ocr_pdf, filetype="pdf")
    try:
        page = ocr_doc[0]
        words = page.get_text("words")
        lines = _lines_from_words(words)
    finally:
        ocr_doc.close()

    return {
        "engine": "pymupdf-tesseract",
        "language": language,
        "word_count": len(words),
        "lines": lines,
    }


def run_rapidocr(crop: HeaderCrop, *, model_dir: str | None = None) -> dict[str, Any]:
    model_paths = default_rapidocr_latin_model_paths(model_dir)
    missing_model_paths = missing_rapidocr_latin_model_paths(model_paths)
    if missing_model_paths:
        missing_names = ", ".join(path.name for path in missing_model_paths)
        raise RuntimeError(f"RapidOCR LATIN model files are missing: {missing_names}")

    backend = RapidOcrLatinBackend(RapidOcrLatinBackendConfig(model_paths=model_paths))
    with tempfile.TemporaryDirectory(prefix="metroliza_ocr_") as temp_dir:
        image_path = Path(temp_dir) / "header.png"
        crop.pixmap.save(image_path)
        run = backend.recognize(image_path)

    header_items = postprocess_header_ocr_items(
        convert_ocr_records_to_header_items(
            run.records,
            crop_bbox=crop.bbox,
            crop_pixel_size=(float(crop.pixmap.width), float(crop.pixmap.height)),
            source_name="rapidocr_latin",
            header_crop_source=crop.bbox_source,
        )
    )
    records = [
        {
            "text": item.get("text"),
            "score": item.get("confidence"),
            "box": item.get("ocr_box"),
            "page_bbox": [item.get("x0"), item.get("y0"), item.get("x1"), item.get("y1")],
        }
        for item in header_items
    ]
    return {
        "engine": "rapidocr_latin",
        "word_count": len(records),
        "lines": [record["text"] for record in records if record.get("text")],
        "records": records,
        "diagnostics": run.diagnostics,
    }


def iter_pdf_paths(args: argparse.Namespace) -> list[Path]:
    if args.pdf:
        return [Path(item).expanduser().resolve() for item in args.pdf]

    report_dir = Path(args.report_dir).expanduser().resolve()
    iterator = report_dir.rglob("*.pdf") if args.recursive else report_dir.iterdir()
    paths = sorted(path for path in iterator if path.is_file() and path.suffix.lower() == ".pdf")
    return paths[: args.limit] if args.limit else paths


def load_expected(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        items = json.load(handle)
    return {str(item["file"]): item.get("expected", {}) for item in items}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine",
        choices=("pymupdf-tesseract", "rapidocr", "both"),
        default="both",
        help="OCR backend to run.",
    )
    parser.add_argument(
        "--language",
        default=os.environ.get("METROLIZA_HEADER_OCR_LANGUAGE", "eng"),
        help="Tesseract language string for PyMuPDF OCR, for example 'pol+eng'.",
    )
    parser.add_argument(
        "--report-dir",
        default=str(default_report_dir()),
        help="Directory containing example PDFs.",
    )
    parser.add_argument("--pdf", action="append", help="Specific PDF to probe. Repeatable.")
    parser.add_argument("--zoom", default=DEFAULT_ZOOM, type=float, help="Header render zoom.")
    parser.add_argument("--recursive", action="store_true", help="Scan report directory recursively.")
    parser.add_argument("--limit", type=int, help="Maximum number of PDFs to probe.")
    parser.add_argument(
        "--rapidocr-model-dir",
        help="Directory containing the vendored RapidOCR LATIN ONNX model files.",
    )
    parser.add_argument(
        "--rapidocr-rec-lang",
        default="latin",
        choices=("latin",),
        help="Recognition language for production RapidOCR probing. Only 'latin' is supported.",
    )
    parser.add_argument(
        "--expected",
        default=str(Path(__file__).with_name("expected_headers.json")),
        help="Expected header JSON for context in the probe output.",
    )
    parser.add_argument("--output", help="Optional JSON output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engines = (
        ["pymupdf-tesseract", "rapidocr"]
        if args.engine == "both"
        else [args.engine]
    )
    expected_by_file = load_expected(Path(args.expected))
    results: list[dict[str, Any]] = []

    for pdf_path in iter_pdf_paths(args):
        crop = render_header_crop(pdf_path, args.zoom)
        base_payload = {
            "pdf": str(pdf_path),
            "file": pdf_path.name,
            "header_bbox": crop.bbox,
            "header_bbox_source": crop.bbox_source,
            "header_bbox_diagnostics": crop.bbox_diagnostics,
            "zoom": crop.zoom,
            "expected": expected_by_file.get(pdf_path.name, {}),
        }

        for engine in engines:
            try:
                if engine == "pymupdf-tesseract":
                    engine_payload = run_pymupdf_tesseract(crop, args.language)
                else:
                    engine_payload = run_rapidocr(crop, model_dir=args.rapidocr_model_dir)
                results.append({**base_payload, **engine_payload, "ok": True})
            except Exception as exc:  # pragma: no cover - probe should report failures
                results.append(
                    {
                        **base_payload,
                        "engine": engine,
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )

    payload = {"results": results}
    output_text = json.dumps(payload, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)

    return 0 if all(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

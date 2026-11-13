"""Synthetic image-header OCR check for a Windows candidate.

The caller supplies a private scratch directory and the pinned public fixture.
The check resolves the normal CMM parser, runs its configured RapidOCR header
fallback, and returns only fixed-schema synthetic evidence.  A source run is
useful engineering evidence; only ``runtime_context == "packaged"`` binds the
same observation to a packaged candidate.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
FIXTURE_NAME = "image-header-only.pdf"
FIXTURE_SHA256 = "33065d26c788d9394c3e33876f885902ab95d21f5457f4f21fee3f333bf9609a"
EMBEDDED_TEXT_SHA256 = "99c5e7215a5dd0ed6904c452f96b521fdb1559250cc1b97ba93e09d16daa831f"
EXPECTED_METADATA = {
    "reference": "OCR7319",
    "report_date": "2024-08-16",
    "part_name": "OCR WIDGET",
    "revision": "Q7",
    "stats_count_raw": "8",
    "sample_number": "8",
}
EXPECTED_OCR_TOKENS = (
    "PART NAME OCR WIDGET",
    "DATE 2024-08-16",
    "REV NUMBER Q7",
    "SER NUMBER OCR7319",
    "STATS COUNT 8",
)
EXPECTED_FIELD_SOURCES = {
    "reference": "position_cell",
    "report_date": "position_cell",
    "part_name": "position_cell",
    "revision": "position_cell",
    "stats_count_raw": "position_cell",
    "sample_number": "projected_from_stats_count",
}
FACETS = (
    "declared_ocr_model_assets",
    "image_only_header_provenance",
    "rapidocr_header_inference",
    "parser_metadata_selection",
)


class OcrCheckFailure(ValueError):
    """A stable, path-free acceptance failure."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise OcrCheckFailure(code)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _runtime_context() -> str:
    packaged = bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))
    return "packaged" if packaged else "source"


def _verify_model_assets() -> dict[str, str]:
    from metroliza.parsing.header_ocr_backend import (
        RAPIDOCR_MODEL_ASSET_MANIFEST,
        default_rapidocr_latin_model_paths,
    )

    model_paths = default_rapidocr_latin_model_paths()
    paths = (
        Path(model_paths.det_model_path),
        Path(model_paths.cls_model_path),
        Path(model_paths.rec_model_path),
    )
    observed: dict[str, str] = {}
    for path in paths:
        _require(path.is_file() and not path.is_symlink(), "ocr_model_asset_missing")
        manifest = RAPIDOCR_MODEL_ASSET_MANIFEST.get(path.name)
        _require(isinstance(manifest, dict), "ocr_model_asset_undeclared")
        digest = _sha256(path)
        _require(digest == manifest.get("sha256"), "ocr_model_asset_digest_mismatch")
        observed[path.name] = digest
    _require(
        set(observed) == set(RAPIDOCR_MODEL_ASSET_MANIFEST),
        "ocr_model_asset_set_mismatch",
    )
    return dict(sorted(observed.items()))


def _inspect_image_only_fixture(path: Path) -> dict[str, Any]:
    from metroliza.parsing.pdf_backend import require_pdf_backend

    backend = require_pdf_backend()
    with backend.open(str(path)) as document:
        _require(len(document) == 1, "fixture_page_count_mismatch")
        page = document[0]
        embedded_text = page.get_text()
        words = tuple(page.get_text("words"))
        header_limit = float(page.rect.height) * 0.22
        header_words = tuple(word for word in words if float(word[1]) <= header_limit)
        image_count = len(page.get_images(full=True))

    _require(
        hashlib.sha256(embedded_text.encode("utf-8")).hexdigest()
        == EMBEDDED_TEXT_SHA256,
        "fixture_embedded_text_mismatch",
    )
    _require(not header_words, "fixture_header_has_embedded_text")
    _require(image_count == 1, "fixture_header_image_count_mismatch")
    folded_text = embedded_text.upper()
    _require(
        all(token not in folded_text for token in EXPECTED_OCR_TOKENS),
        "fixture_expected_metadata_in_text_layer",
    )
    return {
        "embedded_text_sha256": EMBEDDED_TEXT_SHA256,
        "embedded_header_word_count": 0,
        "header_image_count": image_count,
    }


def _classify_ocr_failure(metadata_json: dict[str, Any]) -> str:
    detail = str(metadata_json.get("header_ocr_error") or "")
    if detail.startswith("header_ocr_models_missing:"):
        return "ocr_model_asset_missing"
    if detail in {"header_ocr_disabled"} or detail.startswith(
        "unsupported_header_ocr_backend:"
    ):
        return "ocr_backend_unavailable"
    if detail == "header_ocr_no_records":
        return "ocr_no_records"
    if detail.startswith(("ImportError:", "ModuleNotFoundError:")):
        return "ocr_runtime_unavailable"
    return "ocr_inference_failed"


def run_ocr_check(
    scratch_directory: str | Path,
    fixture_path: str | Path,
    *,
    stage_recorder: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run real RapidOCR through the public parser factory on a pinned fixture."""

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "facets": {name: "not_run" for name in FACETS},
        "error_codes": [],
        "evidence": {
            "runtime_context": _runtime_context(),
            "fixture_name": FIXTURE_NAME,
            "fixture_sha256": None,
            "embedded_text_sha256": None,
            "embedded_header_word_count": None,
            "header_image_count": None,
            "parser_plugin_id": None,
            "measurement_count": None,
            "header_extraction_mode": None,
            "header_structured_word_count": None,
            "header_ocr_engine": None,
            "header_ocr_runtime_engine": None,
            "header_ocr_runtime_accelerator": None,
            "recognized_header_sha256": None,
            "matched_ocr_tokens": [],
            "selected_metadata": None,
            "field_sources": None,
            "model_asset_sha256": None,
        },
    }
    try:
        if stage_recorder is not None:
            stage_recorder("ocr_fixture_validation")
        scratch = Path(scratch_directory)
        fixture = Path(fixture_path)
        _require(scratch.is_absolute(), "scratch_not_absolute")
        _require(scratch.is_dir() and not scratch.is_symlink(), "scratch_invalid")
        _require(fixture.is_file() and not fixture.is_symlink(), "fixture_invalid")
        _require(fixture.name == FIXTURE_NAME, "fixture_name_mismatch")
        fixture_digest = _sha256(fixture)
        _require(fixture_digest == FIXTURE_SHA256, "fixture_digest_mismatch")
        result["evidence"]["fixture_sha256"] = fixture_digest

        if stage_recorder is not None:
            stage_recorder("ocr_asset_validation")
        model_hashes = _verify_model_assets()
        result["evidence"]["model_asset_sha256"] = model_hashes
        result["facets"]["declared_ocr_model_assets"] = "passed"

        with tempfile.TemporaryDirectory(prefix="ocr-check-", dir=scratch) as child_name:
            staged = Path(child_name) / FIXTURE_NAME
            shutil.copyfile(fixture, staged)
            _require(_sha256(staged) == FIXTURE_SHA256, "staged_fixture_digest_mismatch")
            if stage_recorder is not None:
                stage_recorder("ocr_fixture_inspection")
            fixture_evidence = _inspect_image_only_fixture(staged)
            result["evidence"].update(fixture_evidence)
            result["facets"]["image_only_header_provenance"] = "passed"

            from metroliza.parsing.report_parser_factory import get_parser

            if stage_recorder is not None:
                stage_recorder("ocr_parser_construction")
            parser = get_parser(
                staged,
                database=str(Path(child_name) / "ocr.sqlite"),
                metadata_parsing_mode="complete",
            )
            if stage_recorder is not None:
                stage_recorder("ocr_parser_execution")
            from metroliza.parsing.header_ocr_backend import (
                observe_ocr_qualification_stages,
            )

            with observe_ocr_qualification_stages(stage_recorder):
                parsed = parser.parse_to_v2()
            if stage_recorder is not None:
                stage_recorder("ocr_result_validation")
            metadata = parser.canonical_metadata
            metadata_json = dict(metadata.metadata_json or {})

        mode = metadata_json.get("header_extraction_mode")
        if mode != "ocr":
            raise OcrCheckFailure(_classify_ocr_failure(metadata_json))
        _require(
            metadata_json.get("header_structured_word_count") == 0,
            "structured_header_text_used",
        )
        _require(
            metadata_json.get("header_ocr_engine") == "rapidocr_latin",
            "rapidocr_engine_mismatch",
        )
        runtime_engine = metadata_json.get("header_ocr_runtime_engine")
        _require(
            runtime_engine in {"onnxruntime", "openvino", "tensorrt"},
            "rapidocr_runtime_engine_unverified",
        )
        header_text = " ".join(str(metadata_json.get("header_text") or "").upper().split())
        matched_tokens = [token for token in EXPECTED_OCR_TOKENS if token in header_text]
        _require(
            matched_tokens == list(EXPECTED_OCR_TOKENS),
            "recognized_header_tokens_mismatch",
        )
        result["facets"]["rapidocr_header_inference"] = "passed"

        selected_metadata = {
            field: getattr(metadata, field) for field in EXPECTED_METADATA
        }
        _require(selected_metadata == EXPECTED_METADATA, "selected_metadata_mismatch")
        field_sources = dict(metadata_json.get("field_sources") or {})
        selected_sources = {
            field: field_sources.get(field) for field in EXPECTED_FIELD_SOURCES
        }
        _require(
            selected_sources == EXPECTED_FIELD_SOURCES,
            "metadata_source_mismatch",
        )
        _require(parsed.meta.plugin_id == "cmm", "parser_plugin_mismatch")
        measurement_count = sum(len(block.dimensions) for block in parsed.blocks)
        _require(measurement_count == 1, "measurement_count_mismatch")
        result["facets"]["parser_metadata_selection"] = "passed"

        result["evidence"].update(
            {
                "parser_plugin_id": parsed.meta.plugin_id,
                "measurement_count": measurement_count,
                "header_extraction_mode": mode,
                "header_structured_word_count": 0,
                "header_ocr_engine": metadata_json.get("header_ocr_engine"),
                "header_ocr_runtime_engine": runtime_engine,
                "header_ocr_runtime_accelerator": metadata_json.get(
                    "header_ocr_runtime_accelerator"
                ),
                "recognized_header_sha256": hashlib.sha256(
                    header_text.encode("utf-8")
                ).hexdigest(),
                "matched_ocr_tokens": matched_tokens,
                "selected_metadata": selected_metadata,
                "field_sources": selected_sources,
            }
        )
        result["status"] = "passed"
    except OcrCheckFailure as error:
        result["error_codes"].append(str(error))
    except Exception:
        result["error_codes"].append("unexpected_exception")
    return result

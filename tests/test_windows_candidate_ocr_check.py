from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil

import pytest

from metroliza.app.windows_candidate_ocr_check import (
    EMBEDDED_TEXT_SHA256,
    EXPECTED_FIELD_SOURCES,
    EXPECTED_METADATA,
    EXPECTED_OCR_TOKENS,
    FACETS,
    FIXTURE_NAME,
    FIXTURE_SHA256,
    run_ocr_check,
)
from metroliza.app.windows_candidate_qualification import (
    OCR_FIXTURE_ENV,
    ScenarioFailure,
    _ocr_fixture,
    _run_ocr_slice,
)
from metroliza.parsing.header_ocr_backend import RAPIDOCR_MODEL_ASSET_MANIFEST
from metroliza.parsing.pdf_backend import require_pdf_backend


FIXTURE = Path(__file__).parent / "fixtures" / "windows_candidate_ocr" / FIXTURE_NAME


def test_pinned_fixture_has_only_a_raster_header_and_neutral_filename():
    import hashlib

    assert FIXTURE.name == FIXTURE_NAME
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256
    backend = require_pdf_backend()
    with backend.open(str(FIXTURE)) as document:
        assert len(document) == 1
        page = document[0]
        text = page.get_text()
        header_limit = float(page.rect.height) * 0.22
        header_words = [
            word for word in page.get_text("words") if float(word[1]) <= header_limit
        ]
        assert header_words == []
        assert len(page.get_images(full=True)) == 1

    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == EMBEDDED_TEXT_SHA256
    folded_text = text.upper()
    assert all(token not in folded_text for token in EXPECTED_OCR_TOKENS)
    assert EXPECTED_METADATA["reference"] not in FIXTURE.name.upper()
    assert EXPECTED_METADATA["report_date"] not in FIXTURE.name.upper()


def test_helper_rejects_a_mutated_fixture_before_inference(tmp_path):
    fixture = tmp_path / FIXTURE_NAME
    shutil.copyfile(FIXTURE, fixture)
    fixture.write_bytes(fixture.read_bytes() + b"mutated")

    stages = []
    result = run_ocr_check(tmp_path.resolve(), fixture, stage_recorder=stages.append)

    assert result["status"] == "failed"
    assert stages == ["ocr_fixture_validation"]
    assert result["error_codes"] == ["fixture_digest_mismatch"]
    assert result["facets"] == {name: "not_run" for name in FACETS}
    assert result["evidence"]["fixture_sha256"] is None


def test_qualification_requires_a_separate_absolute_ocr_fixture(monkeypatch, tmp_path):
    monkeypatch.delenv(OCR_FIXTURE_ENV, raising=False)
    with pytest.raises(ScenarioFailure, match="ocr_fixture_missing"):
        _ocr_fixture()

    monkeypatch.setenv(OCR_FIXTURE_ENV, FIXTURE_NAME)
    with pytest.raises(ScenarioFailure, match="ocr_fixture_invalid"):
        _ocr_fixture()

    monkeypatch.setenv(OCR_FIXTURE_ENV, str(FIXTURE.resolve()))
    assert _ocr_fixture() == FIXTURE.resolve()


@pytest.mark.skipif(
    importlib.util.find_spec("rapidocr") is None
    or importlib.util.find_spec("onnxruntime") is None,
    reason="source environment does not have the packaged OCR runtime dependencies",
)
def test_real_rapidocr_parser_path_returns_closed_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("METROLIZA_HEADER_OCR_THREADS", "1")
    receipt = {"packaged": False, "facets": {}}
    stages = []
    _run_ocr_slice(tmp_path.resolve(), FIXTURE, receipt, stage_recorder=stages.append)
    result = receipt["ocr_observation"]

    assert result["status"] == "passed"
    assert result["error_codes"] == []
    assert result["facets"] == {name: "passed" for name in FACETS}
    evidence = result["evidence"]
    assert evidence["runtime_context"] in {"source", "packaged"}
    assert evidence["fixture_sha256"] == FIXTURE_SHA256
    assert evidence["embedded_header_word_count"] == 0
    assert evidence["header_image_count"] == 1
    assert evidence["parser_plugin_id"] == "cmm"
    assert evidence["measurement_count"] == 1
    assert evidence["header_extraction_mode"] == "ocr"
    assert evidence["header_structured_word_count"] == 0
    assert evidence["header_ocr_engine"] == "rapidocr_latin"
    assert evidence["header_ocr_runtime_engine"] in {
        "onnxruntime",
        "openvino",
        "tensorrt",
    }
    assert evidence["matched_ocr_tokens"] == list(EXPECTED_OCR_TOKENS)
    assert evidence["selected_metadata"] == EXPECTED_METADATA
    assert evidence["field_sources"] == EXPECTED_FIELD_SOURCES
    assert all(source != "filename_candidate" for source in evidence["field_sources"].values())
    assert len(evidence["recognized_header_sha256"]) == 64
    assert set(evidence["model_asset_sha256"]) == {
        "ch_PP-OCRv4_det_mobile.onnx",
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "latin_PP-OCRv3_rec_mobile.onnx",
    }
    assert receipt["facets"] == {name: "passed" for name in FACETS}
    assert stages == [
        "ocr_fixture_validation", "ocr_asset_validation", "ocr_fixture_inspection",
        "ocr_parser_construction", "ocr_parser_execution", "ocr_result_validation",
    ]


def test_qualification_rejects_runtime_context_mismatch(tmp_path, monkeypatch):
    from metroliza.app import windows_candidate_ocr_check as ocr_check

    observation = {
        "schema_version": 1,
        "status": "passed",
        "facets": dict.fromkeys(FACETS, "passed"),
        "error_codes": [],
        "evidence": {
            "runtime_context": "source",
            "fixture_name": FIXTURE_NAME,
            "fixture_sha256": FIXTURE_SHA256,
            "embedded_text_sha256": EMBEDDED_TEXT_SHA256,
            "embedded_header_word_count": 0,
            "header_image_count": 1,
            "parser_plugin_id": "cmm",
            "measurement_count": 1,
            "header_extraction_mode": "ocr",
            "header_structured_word_count": 0,
            "header_ocr_engine": "rapidocr_latin",
            "header_ocr_runtime_engine": "onnxruntime",
            "header_ocr_runtime_accelerator": "cpu",
            "recognized_header_sha256": "1" * 64,
            "matched_ocr_tokens": list(EXPECTED_OCR_TOKENS),
            "selected_metadata": EXPECTED_METADATA,
            "field_sources": EXPECTED_FIELD_SOURCES,
            "model_asset_sha256": {
                name: values["sha256"]
                for name, values in RAPIDOCR_MODEL_ASSET_MANIFEST.items()
            },
        },
    }
    monkeypatch.setattr(ocr_check, "run_ocr_check", lambda *_args: observation)
    receipt = {"packaged": True, "facets": {}}

    with pytest.raises(ScenarioFailure, match="ocr_evidence_mismatch"):
        _run_ocr_slice(tmp_path.resolve(), FIXTURE, receipt)

    assert receipt["ocr_observation"] is observation
    assert receipt["facets"] == {}

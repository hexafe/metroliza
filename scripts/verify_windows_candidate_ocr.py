"""Independent, fixed-input OCR receipt oracle; no application imports."""
from __future__ import annotations

import re

FIXTURE_NAME = "image-header-only.pdf"
FIXTURE_SHA256 = "33065d26c788d9394c3e33876f885902ab95d21f5457f4f21fee3f333bf9609a"
FACETS = (
    "declared_ocr_model_assets", "image_only_header_provenance",
    "rapidocr_header_inference", "parser_metadata_selection",
)
MODEL_HASHES = {
    "ch_PP-OCRv4_det_mobile.onnx": "d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    "latin_PP-OCRv3_rec_mobile.onnx": "e9d7a33667e8aaa702862975186adf2012e3f390cc0f9422865957125f8071cf",
}
EXPECTED = {
    "fixture_name": FIXTURE_NAME, "fixture_sha256": FIXTURE_SHA256,
    "embedded_text_sha256": "99c5e7215a5dd0ed6904c452f96b521fdb1559250cc1b97ba93e09d16daa831f",
    "embedded_header_word_count": 0, "header_image_count": 1,
    "parser_plugin_id": "cmm", "measurement_count": 1,
    "header_extraction_mode": "ocr", "header_structured_word_count": 0,
    "header_ocr_engine": "rapidocr_latin",
    "header_ocr_runtime_engine": "onnxruntime", "header_ocr_runtime_accelerator": "cpu",
    "matched_ocr_tokens": ["PART NAME OCR WIDGET", "DATE 2024-08-16", "REV NUMBER Q7",
                           "SER NUMBER OCR7319", "STATS COUNT 8"],
    "selected_metadata": {"reference": "OCR7319", "report_date": "2024-08-16",
                          "part_name": "OCR WIDGET", "revision": "Q7",
                          "stats_count_raw": "8", "sample_number": "8"},
    "field_sources": {"reference": "position_cell", "report_date": "position_cell",
                      "part_name": "position_cell", "revision": "position_cell",
                      "stats_count_raw": "position_cell", "sample_number": "projected_from_stats_count"},
    "model_asset_sha256": MODEL_HASHES,
}


def validate(value: object, *, packaged: bool = False) -> dict:
    """Require real image-only inference and parser selection, never just assets."""
    if (type(value) is not dict
            or set(value) != {"schema_version", "status", "facets", "error_codes", "evidence"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["status"] != "passed" or value["error_codes"] != []
            or value["facets"] != {key: "passed" for key in FACETS}):
        raise ValueError("invalid_ocr_observation")
    evidence = value["evidence"]
    if (type(evidence) is not dict
            or set(evidence) != set(EXPECTED) | {"runtime_context", "recognized_header_sha256"}
            or any(type(evidence[key]) is not type(expected) or evidence[key] != expected
                   for key, expected in EXPECTED.items())
            or evidence["runtime_context"] not in ("source", "packaged")
            or type(evidence["recognized_header_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", evidence["recognized_header_sha256"]) is None):
        raise ValueError("invalid_ocr_observation")
    if packaged and evidence["runtime_context"] != "packaged":
        raise ValueError("source_ocr_is_not_package_evidence")
    return value

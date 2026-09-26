"""Closed core-payload checks used before package-identity rejection."""
from __future__ import annotations

import pytest

from scripts import qualify_windows_candidate_core as driver
from tests.test_windows_candidate_closeout import closeout_observation
from tests.test_windows_candidate_core_protocol import import_guard_evidence, native_observation, ocr_observation, ui_observation


def _payload():
    ui = ui_observation()
    ui["status"] = "partial"
    ui["facets"]["industrial_geometry"] = "not_assessed"
    ui["evidence"]["screen"]["qpa"] = "offscreen"
    ui["evidence"]["dialog_geometry"] = None
    ui["evidence"]["owned_handle_observed"] = None
    return {
        "schema_version": 1,
        "stage": "complete",
        "status": "passed",
        "packaged": False,
        "qpa": "offscreen",
        "ordinary_user": True,
        "source_sha": None,
        "relative_artifact_dir": "core-" + "a" * 32,
        "checks": {"W03": "passed", "W04": "passed", "W05": "passed", "W06": "passed", "W07": "passed"},
        "import_guard_evidence": import_guard_evidence(),
        "closeout_observation": closeout_observation("source"),
        "ui_observation": ui,
        "ocr_observation": ocr_observation("source"),
        "native_observation": native_observation("source"),
        "facets": {
            **{key: "passed" for key in driver.REQUIRED_CHECKS},
            "group_analysis_status": "insufficient_groups",
        },
        "artifacts": {
            key: {"path": key + suffix, "sha256": "2" * 64}
            for key, suffix in zip(
                driver.ARTIFACTS,
                (".sqlite", ".xlsx", ".json", ".json", ".xlsx", ".sqlite", ".json"),
                strict=True,
            )
        },
    }


def test_source_result_validates_all_core_content_before_package_identity_rejection():
    payload = _payload()
    assert driver._validate_core_result(payload) is payload
    with pytest.raises(driver.CandidateFailure, match="source_execution_is_not_package_evidence"):
        driver.validate_runtime_receipt(payload, "1" * 40)


def test_core_validator_rejects_missing_facet_before_source_lane_uses_result():
    payload = _payload()
    del payload["facets"][driver.REQUIRED_CHECKS[0]]
    with pytest.raises(driver.CandidateFailure, match="required_core_check_incomplete"):
        driver._validate_core_result(payload)


@pytest.mark.parametrize("field,value", [
    ("model_asset_sha256", {}), ("matched_ocr_tokens", []),
    ("header_extraction_mode", "text"), ("header_structured_word_count", 1),
    ("header_image_count", True), ("fixture_sha256", "0" * 64),
    ("selected_metadata", {}), ("field_sources", {}),
    ("header_ocr_runtime_engine", "unknown"),
    ("header_ocr_runtime_accelerator", "private-path"),
])
def test_ocr_receipt_cannot_substitute_assets_text_or_metadata_for_inference(field, value):
    payload = _payload()
    payload["ocr_observation"]["evidence"][field] = value
    with pytest.raises(driver.CandidateFailure, match="invalid_ocr_observation"):
        driver._validate_core_result(payload)


def test_complete_core_cannot_omit_ocr_observation():
    payload = _payload()
    del payload["ocr_observation"]
    with pytest.raises(driver.CandidateFailure, match="invalid_ocr_observation"):
        driver._validate_core_result(payload)


def test_source_ocr_observation_cannot_be_promoted_by_outer_package_identity():
    payload = _payload()
    payload.update(packaged=True, qpa="windows", source_sha="1" * 40)
    with pytest.raises(driver.CandidateFailure, match="source_ocr_is_not_package_evidence"):
        driver.validate_runtime_receipt(payload, "1" * 40)


def test_ocr_fixture_staging_preserves_pinned_bytes_and_rejects_mutation(tmp_path):
    from pathlib import Path
    from scripts.verify_windows_candidate_ocr import FIXTURE_NAME, FIXTURE_SHA256

    checkout = Path(__file__).resolve().parents[1]
    private = tmp_path / "private"
    private.mkdir()
    staged = driver._stage_ocr_fixture(checkout, private)
    assert driver._hash(staged) == FIXTURE_SHA256
    shadow = tmp_path / "checkout"
    folder = shadow / "tests" / "fixtures" / "windows_candidate_ocr"
    folder.mkdir(parents=True)
    (folder / FIXTURE_NAME).write_bytes(b"changed synthetic input")
    with pytest.raises(driver.CandidateFailure, match="prepared_ocr_fixture_hash_mismatch"):
        driver._stage_ocr_fixture(shadow, private)

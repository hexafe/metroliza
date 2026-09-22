"""Closed core-payload checks used before package-identity rejection."""
from __future__ import annotations

import pytest

from scripts import qualify_windows_candidate_core as driver
from tests.test_windows_candidate_core_protocol import import_guard_evidence


def _payload():
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

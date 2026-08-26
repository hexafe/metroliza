from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "quality" / "validate_bug_sweep_coverage.py"
LEDGER_PATH = REPO_ROOT / "docs" / "quality" / "bug_sweep" / "coverage.json"

SPEC = importlib.util.spec_from_file_location("validate_bug_sweep_coverage", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
COVERAGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = COVERAGE
SPEC.loader.exec_module(COVERAGE)


def _ledger() -> dict[str, object]:
    return copy.deepcopy(COVERAGE.load_ledger(LEDGER_PATH))


def _tracked_paths() -> list[str]:
    return COVERAGE.git_tracked_paths(REPO_ROOT)


def _rule(ledger: dict[str, object], rule_id: str) -> dict[str, object]:
    return next(rule for rule in ledger["rules"] if rule["id"] == rule_id)


def _assert_invalid(
    ledger: dict[str, object], expected: str, paths: list[str] | None = None
) -> None:
    with pytest.raises(COVERAGE.CoverageValidationError) as exc_info:
        COVERAGE.validate_coverage(ledger, paths if paths is not None else _tracked_paths())
    assert expected in str(exc_info.value)


def test_repository_tree_has_exactly_one_primary_owner_per_path() -> None:
    report = COVERAGE.validate_coverage(_ledger(), _tracked_paths())

    assert report["covered_file_count"] == report["tracked_file_count"]
    assert report["uncovered_count"] == 0
    assert report["duplicate_primary_count"] == 0
    assert set(report["owner_counts"]) == {str(issue) for issue in range(975, 986)}
    assert set(report["class_counts"]) == COVERAGE.PATH_CLASSES


def test_missing_ownership_is_rejected() -> None:
    ledger = _ledger()
    _rule(ledger, "root-application-entrypoint")["include"] = ["removed/metroliza.py"]

    _assert_invalid(ledger, "unassigned tracked path: metroliza.py")


def test_duplicate_primary_ownership_is_rejected() -> None:
    ledger = _ledger()
    duplicate = copy.deepcopy(_rule(ledger, "root-application-entrypoint"))
    duplicate["id"] = "synthetic-duplicate-owner"
    duplicate["primary_owner"] = 978
    duplicate["secondary_owners"] = []
    ledger["rules"].append(duplicate)

    _assert_invalid(ledger, "duplicate primary ownership: metroliza.py")


def test_unknown_issue_owner_is_rejected() -> None:
    ledger = _ledger()
    _rule(ledger, "root-application-entrypoint")["primary_owner"] = 999

    _assert_invalid(ledger, "unknown Issue owner 999")


def test_float_issue_owner_is_rejected() -> None:
    ledger = _ledger()
    _rule(ledger, "root-application-entrypoint")["primary_owner"] = 975.0

    _assert_invalid(ledger, "unknown Issue owner 975.0")


def test_schema_version_boolean_is_rejected() -> None:
    ledger = _ledger()
    ledger["schema_version"] = True

    _assert_invalid(ledger, "schema_version must equal 1")


def test_noncanonical_workstream_key_is_rejected() -> None:
    ledger = _ledger()
    ledger["workstreams"]["0975"] = copy.deepcopy(ledger["workstreams"]["975"])

    _assert_invalid(ledger, "workstreams must define exactly Issues #975-#985")


def test_product_owner_execution_order_cannot_drift() -> None:
    ledger = _ledger()
    ledger["workstreams"]["983"]["execution_order"] = "8"

    _assert_invalid(ledger, "workstream #983: execution_order must equal '2'")


def test_float_compatibility_pr_number_is_rejected() -> None:
    ledger = _ledger()
    ledger["external_compatibility_inputs"][0]["pr"] = 972.0

    _assert_invalid(ledger, "external_compatibility_inputs must contain exactly PRs #972 and #973")


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("class", "mystery runtime", "invalid class 'mystery runtime'"),
        ("audit_status", "looks green", "invalid audit status 'looks green'"),
    ],
)
def test_invalid_class_or_status_is_rejected(field: str, value: str, expected: str) -> None:
    ledger = _ledger()
    _rule(ledger, "root-application-entrypoint")[field] = value

    _assert_invalid(ledger, expected)


def test_completed_rule_without_evidence_and_disposition_is_rejected() -> None:
    ledger = _ledger()
    rule = _rule(ledger, "root-application-entrypoint")
    rule["audit_status"] = "completed"
    rule["evidence_links"] = []
    rule["disposition"] = None

    _assert_invalid(ledger, "completed coverage requires evidence")
    _assert_invalid(ledger, "completed coverage requires a disposition")


@pytest.mark.parametrize("status", ["accepted behavior", "deferred residual risk"])
def test_other_terminal_statuses_require_evidence_and_disposition(status: str) -> None:
    ledger = _ledger()
    rule = _rule(ledger, "root-application-entrypoint")
    rule["audit_status"] = status
    rule["evidence_links"] = []
    rule["disposition"] = None

    _assert_invalid(ledger, f"{status} coverage requires evidence")
    _assert_invalid(ledger, f"{status} coverage requires a disposition")


def test_deferred_residual_risk_requires_structured_deferral_details() -> None:
    ledger = _ledger()
    rule = _rule(ledger, "root-application-entrypoint")
    rule["audit_status"] = "deferred residual risk"
    rule["evidence_links"] = ["https://github.com/hexafe/metroliza/issues/975"]
    rule["disposition"] = "Deferred to a later evidence gate."

    _assert_invalid(ledger, "deferred residual risk requires structured deferral details")


def test_complete_deferred_residual_risk_record_is_accepted() -> None:
    ledger = _ledger()
    rule = _rule(ledger, "root-application-entrypoint")
    rule["audit_status"] = "deferred residual risk"
    rule["evidence_links"] = ["https://github.com/hexafe/metroliza/issues/975"]
    rule["disposition"] = "Deferred to the named gate with the entrypoint preserved."
    rule["deferral_details"] = {
        "reason": "The required clean-machine environment is unavailable.",
        "accountable_owner": "Issue #977 audit coordinator",
        "target_issue_or_phase": "Issue #977",
        "next_gate": "Clean-machine lifecycle evidence at the exact audit SHA.",
        "preserved_seam": "Keep metroliza.py behavior unchanged until that evidence exists.",
    }

    report = COVERAGE.validate_coverage(ledger, _tracked_paths())

    assert report["covered_file_count"] == report["tracked_file_count"]


def test_deferral_accountable_owner_requires_a_non_empty_identity() -> None:
    ledger = _ledger()
    rule = _rule(ledger, "root-application-entrypoint")
    rule["audit_status"] = "deferred residual risk"
    rule["evidence_links"] = ["https://github.com/hexafe/metroliza/issues/975"]
    rule["disposition"] = "Deferred to the named gate with the entrypoint preserved."
    rule["deferral_details"] = {
        "reason": "The required clean-machine environment is unavailable.",
        "accountable_owner": 977,
        "target_issue_or_phase": "Issue #977",
        "next_gate": "Clean-machine lifecycle evidence at the exact audit SHA.",
        "preserved_seam": "Keep metroliza.py behavior unchanged until that evidence exists.",
    }

    _assert_invalid(ledger, "deferral_details.accountable_owner must be non-empty")


def test_completed_rule_with_blank_evidence_is_rejected() -> None:
    ledger = _ledger()
    rule = _rule(ledger, "root-application-entrypoint")
    rule["audit_status"] = "completed"
    rule["evidence_links"] = ["   "]
    rule["disposition"] = "Reviewed at the exact SHA."

    _assert_invalid(ledger, "evidence_links must contain only non-empty strings")


def test_newly_tracked_path_cannot_bypass_all_rules() -> None:
    paths = sorted([*_tracked_paths(), "future_surface/unassigned.py"])

    _assert_invalid(_ledger(), "unassigned tracked path: future_surface/unassigned.py", paths)


def test_legitimate_tracked_path_deletion_does_not_invalidate_baseline_metadata() -> None:
    paths = [path for path in _tracked_paths() if path != "README.md"]

    report = COVERAGE.validate_coverage(_ledger(), paths)

    assert report["tracked_file_count"] == len(_tracked_paths()) - 1
    assert report["covered_file_count"] == report["tracked_file_count"]


def test_current_open_issue_map_cannot_silently_drop_an_issue() -> None:
    ledger = _ledger()
    ledger["existing_issue_map"] = [
        record for record in ledger["existing_issue_map"] if record["issue"] != 971
    ]

    _assert_invalid(ledger, "existing_issue_map is missing current open Issue(s): #971")


def test_baseline_metadata_cannot_self_authorize_an_invented_sha() -> None:
    ledger = _ledger()
    ledger["baseline"]["sha"] = "0" * 40
    for rule in ledger["rules"]:
        rule["baseline_sha"] = "0" * 40

    _assert_invalid(ledger, "baseline.sha must equal the authorized SHA")


def test_baseline_tracked_count_requires_an_integer() -> None:
    ledger = _ledger()
    ledger["baseline"]["tracked_file_count"] = 929.0

    _assert_invalid(
        ledger,
        "baseline.tracked_file_count must equal the verified baseline count 929",
    )


def test_duplicate_json_object_keys_are_rejected(tmp_path: Path) -> None:
    ledger_path = tmp_path / "duplicate-keys.json"
    ledger_path.write_text(
        '{"schema_version": 1, "schema_version": 1}',
        encoding="utf-8",
    )

    with pytest.raises(COVERAGE.CoverageValidationError, match="duplicate JSON object key"):
        COVERAGE.load_ledger(ledger_path)


def test_globstar_matches_zero_or_more_directories() -> None:
    assert COVERAGE.path_matches("docs/**/*.pdf", "docs/future.pdf")
    assert COVERAGE.path_matches("docs/**/*.pdf", "docs/user_manual/future.pdf")


def test_zero_match_rule_is_rejected() -> None:
    ledger = _ledger()
    dead_rule = copy.deepcopy(_rule(ledger, "root-application-entrypoint"))
    dead_rule["id"] = "synthetic-dead-rule"
    dead_rule["include"] = ["retired_surface/**"]
    ledger["rules"].append(dead_rule)

    _assert_invalid(ledger, "ownership rule matches zero tracked paths: synthetic-dead-rule")

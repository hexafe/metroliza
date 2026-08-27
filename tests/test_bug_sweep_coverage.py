from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "quality" / "validate_bug_sweep_coverage.py"
LEDGER_PATH = REPO_ROOT / "docs" / "quality" / "bug_sweep" / "coverage.json"
SYNTHETIC_AUDITED_SHA = "a" * 40

SPEC = importlib.util.spec_from_file_location("validate_bug_sweep_coverage", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
COVERAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COVERAGE)


def _ledger() -> dict[str, object]:
    return copy.deepcopy(COVERAGE.load_ledger(LEDGER_PATH))


def _tracked_paths() -> list[str]:
    return COVERAGE.git_tracked_paths(REPO_ROOT)


def _rule(ledger: dict[str, object], rule_id: str) -> dict[str, object]:
    return next(rule for rule in ledger["rules"] if rule["id"] == rule_id)


def _matched_paths(
    rule: dict[str, object], paths: list[str] | None = None
) -> list[str]:
    return [
        path
        for path in (paths if paths is not None else _tracked_paths())
        if COVERAGE.rule_matches(rule, path)
    ]


def _terminalize_rule(
    ledger: dict[str, object],
    rule_id: str,
    *,
    status: str = "completed",
    paths: list[str] | None = None,
) -> dict[str, object]:
    rule = _rule(ledger, rule_id)
    rule["audit_status"] = status
    rule["evidence_links"] = ["https://github.com/hexafe/metroliza/issues/975"]
    rule["disposition"] = "Synthetic terminal evidence for validator testing."
    rule["terminal_snapshot"] = {
        "audited_commit_sha": SYNTHETIC_AUDITED_SHA,
        "matched_paths": _matched_paths(rule, paths),
    }
    return rule


def _assert_invalid(
    ledger: dict[str, object], expected: str, paths: list[str] | None = None
) -> None:
    with pytest.raises(COVERAGE.CoverageValidationError) as exc_info:
        COVERAGE.validate_coverage(ledger, paths if paths is not None else _tracked_paths())
    assert expected in str(exc_info.value)


def test_repository_tree_has_exactly_one_primary_owner_per_path() -> None:
    ledger = _ledger()
    report = COVERAGE.validate_coverage(ledger, _tracked_paths())

    assert report["covered_file_count"] == report["tracked_file_count"]
    assert report["uncovered_count"] == 0
    assert report["duplicate_primary_count"] == 0
    assert set(report["owner_counts"]) == {str(issue) for issue in range(975, 986)}
    assert set(report["class_counts"]) == COVERAGE.PATH_CLASSES
    assert all(
        "terminal_snapshot" in rule and rule["terminal_snapshot"] is None
        for rule in ledger["rules"]
    )


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

    _assert_invalid(ledger, "schema_version must equal 2")


def test_terminal_snapshot_field_declaration_cannot_drift() -> None:
    ledger = _ledger()
    ledger["terminal_snapshot_fields"].append("tree_digest")

    _assert_invalid(
        ledger,
        "terminal_snapshot_fields must contain exactly the required snapshot fields",
    )


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


@pytest.mark.parametrize(
    "status", ["completed", "accepted behavior", "deferred residual risk"]
)
def test_terminal_rule_without_snapshot_is_rejected(status: str) -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle", status=status)
    rule["terminal_snapshot"] = None

    _assert_invalid(ledger, f"{status} coverage requires a terminal_snapshot")


def test_rule_must_contain_terminal_snapshot_explicitly() -> None:
    ledger = _ledger()
    _rule(ledger, "application-lifecycle").pop("terminal_snapshot")

    _assert_invalid(ledger, "terminal_snapshot must be present explicitly")


@pytest.mark.parametrize("status", ["pending", "in progress", "blocked"])
def test_non_terminal_rule_with_snapshot_is_rejected(status: str) -> None:
    ledger = _ledger()
    rule = _rule(ledger, "application-lifecycle")
    rule["audit_status"] = status
    rule["terminal_snapshot"] = {
        "audited_commit_sha": SYNTHETIC_AUDITED_SHA,
        "matched_paths": _matched_paths(rule),
    }

    _assert_invalid(
        ledger,
        "terminal_snapshot is allowed only for a terminal audit status",
    )


@pytest.mark.parametrize(
    "audited_commit_sha",
    ["a" * 39, "A" * 40, "g" * 40],
)
def test_malformed_terminal_snapshot_sha_is_rejected(audited_commit_sha: str) -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    rule["terminal_snapshot"]["audited_commit_sha"] = audited_commit_sha

    _assert_invalid(
        ledger,
        "terminal_snapshot.audited_commit_sha must be a lowercase 40-character Git SHA",
    )


def test_unexpected_terminal_snapshot_keys_are_rejected() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    rule["terminal_snapshot"]["tree_digest"] = "not-authorized"

    _assert_invalid(
        ledger,
        "terminal_snapshot must contain exactly audited_commit_sha and matched_paths",
    )


@pytest.mark.parametrize("case", ["empty-array", "empty-path", "unsorted", "duplicate"])
def test_invalid_terminal_snapshot_matched_paths_are_rejected(case: str) -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    matched_paths = _matched_paths(rule)
    expected = ""
    if case == "empty-array":
        rule["terminal_snapshot"]["matched_paths"] = []
        expected = "must be a non-empty array of non-empty strings"
    elif case == "empty-path":
        rule["terminal_snapshot"]["matched_paths"] = [""]
        expected = "must be a non-empty array of non-empty strings"
    elif case == "unsorted":
        rule["terminal_snapshot"]["matched_paths"] = list(reversed(matched_paths))
        expected = "terminal_snapshot.matched_paths must be sorted deterministically"
    else:
        rule["terminal_snapshot"]["matched_paths"] = [
            matched_paths[0],
            matched_paths[0],
        ]
        expected = "terminal_snapshot.matched_paths must not contain duplicates"

    _assert_invalid(ledger, expected)


@pytest.mark.parametrize(
    ("matched_path", "expected"),
    [
        ("src/metroliza/app/*.py", "must contain explicit paths, not globs"),
        ("/src/metroliza/app/bootstrap.py", "repository-relative POSIX paths"),
        ("src\\metroliza\\app\\bootstrap.py", "repository-relative POSIX paths"),
        ("src/metroliza/app/../bootstrap.py", "repository-relative POSIX paths"),
    ],
)
def test_terminal_snapshot_paths_must_be_explicit_repository_relative_posix_paths(
    matched_path: str, expected: str
) -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    rule["terminal_snapshot"]["matched_paths"] = [matched_path]

    _assert_invalid(ledger, expected)


def test_valid_terminal_snapshot_is_accepted_and_preserved_in_report() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    expected_snapshot = copy.deepcopy(rule["terminal_snapshot"])

    report = COVERAGE.validate_coverage(ledger, _tracked_paths())

    matching_rows = [
        row for row in report["rows"] if row["rule"] == "application-lifecycle"
    ]
    assert matching_rows
    assert all(row["terminal_snapshot"] == expected_snapshot for row in matching_rows)
    snapshot_record = next(
        record
        for record in report["rule_snapshots"]
        if record["rule"] == "application-lifecycle"
    )
    assert snapshot_record["terminal_snapshot"] == expected_snapshot


def test_json_output_exposes_terminal_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = _ledger()
    expected_snapshot = copy.deepcopy(
        _terminalize_rule(ledger, "application-lifecycle")["terminal_snapshot"]
    )
    ledger_path = tmp_path / "coverage.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    result = COVERAGE.main(
        ["--repo-root", str(REPO_ROOT), "--ledger", str(ledger_path), "--json"]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    snapshot_record = next(
        record
        for record in payload["rule_snapshots"]
        if record["rule"] == "application-lifecycle"
    )
    assert snapshot_record["terminal_snapshot"] == expected_snapshot


def test_newly_matching_path_invalidates_terminal_snapshot() -> None:
    ledger = _ledger()
    _terminalize_rule(ledger, "application-lifecycle")
    paths = sorted([*_tracked_paths(), "src/metroliza/app/new.py"])

    _assert_invalid(
        ledger,
        "newly matched: src/metroliza/app/new.py",
        paths,
    )


def test_removed_matched_path_invalidates_terminal_snapshot() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    removed_path = _matched_paths(rule)[0]
    paths = [path for path in _tracked_paths() if path != removed_path]

    _assert_invalid(ledger, f"no longer matched: {removed_path}", paths)


def test_renamed_matched_path_invalidates_terminal_snapshot() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    removed_path = _matched_paths(rule)[0]
    renamed_path = "src/metroliza/app/renamed_snapshot_probe.py"
    paths = sorted(
        [path for path in _tracked_paths() if path != removed_path] + [renamed_path]
    )

    _assert_invalid(ledger, f"newly matched: {renamed_path}", paths)
    _assert_invalid(ledger, f"no longer matched: {removed_path}", paths)


def test_path_owned_by_another_rule_does_not_invalidate_terminal_snapshot() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    expected_snapshot = copy.deepcopy(rule["terminal_snapshot"])
    paths = sorted([*_tracked_paths(), "src/metroliza/reports/new.py"])

    report = COVERAGE.validate_coverage(ledger, paths)

    assert report["tracked_file_count"] == len(_tracked_paths()) + 1
    synthetic_row = next(
        row for row in report["rows"] if row["path"] == "src/metroliza/reports/new.py"
    )
    assert synthetic_row["rule"] == "report-ingestion-contracts"
    snapshot_record = next(
        record
        for record in report["rule_snapshots"]
        if record["rule"] == "application-lifecycle"
    )
    assert snapshot_record["terminal_snapshot"] == expected_snapshot


def test_deferred_residual_risk_requires_structured_deferral_details() -> None:
    ledger = _ledger()
    rule = _rule(ledger, "root-application-entrypoint")
    rule["audit_status"] = "deferred residual risk"
    rule["evidence_links"] = ["https://github.com/hexafe/metroliza/issues/975"]
    rule["disposition"] = "Deferred to a later evidence gate."

    _assert_invalid(ledger, "deferred residual risk requires structured deferral details")


def test_complete_deferred_residual_risk_record_is_accepted() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(
        ledger,
        "root-application-entrypoint",
        status="deferred residual risk",
    )
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
        '{"schema_version": 2, "schema_version": 2}',
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

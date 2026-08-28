from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "quality" / "validate_bug_sweep_coverage.py"
LEDGER_PATH = REPO_ROOT / "docs" / "quality" / "bug_sweep" / "coverage.json"
SYNTHETIC_AUDITED_SHA = "a" * 40
DIGEST_MISMATCH = (
    "terminal_snapshot.rule_record_sha256 does not match the complete canonical rule record"
)

SPEC = importlib.util.spec_from_file_location("validate_bug_sweep_coverage", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
COVERAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COVERAGE)


def _repository_ledger() -> dict[str, object]:
    """Return the actual evolving repository ledger unchanged."""

    return copy.deepcopy(COVERAGE.load_ledger(LEDGER_PATH))


def _ledger() -> dict[str, object]:
    """Return a phase-independent pending-only fixture for synthetic controls."""

    ledger = _repository_ledger()
    for rule in ledger["rules"]:
        rule["audit_status"] = "pending"
        rule["terminal_snapshot"] = None
        rule["evidence_links"] = []
        rule["finding_links"] = []
        rule["disposition"] = None
        rule.pop("deferral_details", None)
    return ledger


def _tracked_paths() -> list[str]:
    return COVERAGE.git_tracked_paths(REPO_ROOT)


def _git(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _current_commit_sha() -> str:
    return _git(REPO_ROOT, "rev-parse", "HEAD")


def _historical_resolver(
    paths: list[str] | None = None,
) -> COVERAGE.HistoricalPathResolver:
    resolved_paths = list(paths if paths is not None else _tracked_paths())

    def resolve(_audited_commit_sha: str) -> list[str]:
        return list(resolved_paths)

    return resolve


def _validate_coverage(
    ledger: dict[str, object],
    paths: list[str] | None = None,
    historical_path_resolver: COVERAGE.HistoricalPathResolver | None = None,
) -> dict[str, object]:
    return COVERAGE.validate_coverage(
        ledger,
        paths if paths is not None else _tracked_paths(),
        historical_path_resolver=(
            historical_path_resolver
            if historical_path_resolver is not None
            else _historical_resolver()
        ),
    )


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
    audited_commit_sha: str = SYNTHETIC_AUDITED_SHA,
) -> dict[str, object]:
    rule = _rule(ledger, rule_id)
    rule["audit_status"] = status
    rule["evidence_links"] = ["https://github.com/hexafe/metroliza/issues/975"]
    rule["disposition"] = "Synthetic terminal evidence for validator testing."
    if status == "deferred residual risk":
        rule["deferral_details"] = {
            "reason": "The required clean-machine environment is unavailable.",
            "accountable_owner": "Issue #977 audit coordinator",
            "target_issue_or_phase": "Issue #977",
            "next_gate": "Clean-machine lifecycle evidence at the exact audit SHA.",
            "preserved_seam": "Keep the audited behavior unchanged until evidence exists.",
        }
    else:
        rule.pop("deferral_details", None)
    rule["terminal_snapshot"] = {
        "audited_commit_sha": audited_commit_sha,
        "matched_paths": _matched_paths(rule, paths),
    }
    rule["terminal_snapshot"]["rule_record_sha256"] = COVERAGE.rule_record_sha256(rule)
    return rule


def _mutate_terminal_rule_record(rule: dict[str, object], mutation: str) -> None:
    if mutation == "identity":
        rule["id"] = "application-lifecycle-renamed"
    elif mutation == "include":
        rule["include"].append("src/metroliza/app/nonexistent-contract-probe.py")
    elif mutation == "exclude":
        rule["exclude"].append("src/metroliza/app/nonexistent-contract-probe.py")
    elif mutation == "class":
        rule["class"] = "test"
    elif mutation == "primary_owner":
        rule["primary_owner"] = 978
    elif mutation == "secondary_owners":
        rule["secondary_owners"] = list(reversed(rule["secondary_owners"]))
    elif mutation == "consequence_tier":
        rule["consequence_tier"] = "P2"
    elif mutation == "consequence_tags":
        rule["consequence_tags"] = list(reversed(rule["consequence_tags"]))
    elif mutation == "audit_status":
        rule["audit_status"] = "accepted behavior"
    elif mutation == "baseline_sha":
        rule["baseline_sha"] = "b" * 40
    elif mutation == "evidence_links":
        rule["evidence_links"].append("https://github.com/hexafe/metroliza/issues/987")
    elif mutation == "finding_links":
        rule["finding_links"].append("https://github.com/hexafe/metroliza/issues/987")
    elif mutation == "disposition":
        rule["disposition"] = "Changed disposition after evidence was captured."
    elif mutation == "residual_risk":
        rule["residual_risk"] = "Changed residual risk after evidence was captured."
    elif mutation == "unknown_future_field":
        rule["future_metadata"] = {"order": [2, 1], "value": "now bound"}
    else:
        raise AssertionError(f"unknown mutation case: {mutation}")


def _assert_invalid(
    ledger: dict[str, object],
    expected: str,
    paths: list[str] | None = None,
    historical_path_resolver: COVERAGE.HistoricalPathResolver | None = None,
) -> None:
    with pytest.raises(COVERAGE.CoverageValidationError) as exc_info:
        _validate_coverage(ledger, paths, historical_path_resolver)
    assert expected in str(exc_info.value)


@pytest.fixture
def local_git_history(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo_root = tmp_path / "local-history"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "main")
    _git(repo_root, "config", "user.name", "Coverage Validator Test")
    _git(repo_root, "config", "user.email", "coverage-validator@example.invalid")

    source_dir = repo_root / "src" / "metroliza" / "app"
    source_dir.mkdir(parents=True)
    (repo_root / "README.md").write_text("local history\n", encoding="utf-8")
    (source_dir / "first.py").write_text("FIRST = 1\n", encoding="utf-8")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "first tree")
    first_commit = _git(repo_root, "rev-parse", "HEAD")
    object_shas = {
        "blob": _git(repo_root, "rev-parse", f"{first_commit}:src/metroliza/app/first.py"),
        "tree": _git(repo_root, "rev-parse", f"{first_commit}^{{tree}}"),
    }
    _git(repo_root, "tag", "-a", "first-snapshot", "-m", "first snapshot", first_commit)
    object_shas["tag"] = _git(repo_root, "rev-parse", "refs/tags/first-snapshot")

    (source_dir / "second.py").write_text("SECOND = 2\n", encoding="utf-8")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "second tree")
    object_shas["first_commit"] = first_commit
    object_shas["second_commit"] = _git(repo_root, "rev-parse", "HEAD")
    return repo_root, object_shas


def test_repository_tree_has_exactly_one_primary_owner_per_path() -> None:
    ledger = _repository_ledger()
    report = _validate_coverage(
        ledger,
        historical_path_resolver=lambda sha: COVERAGE.git_tracked_paths_at_commit(
            REPO_ROOT, sha
        ),
    )

    assert report["covered_file_count"] == report["tracked_file_count"]
    assert report["uncovered_count"] == 0
    assert report["duplicate_primary_count"] == 0
    assert set(report["owner_counts"]) == {str(issue) for issue in range(975, 986)}
    assert set(report["class_counts"]) == COVERAGE.PATH_CLASSES
    assert len(ledger["rules"]) == 61
    assert [record["rule"] for record in report["rule_snapshots"]] == [
        rule["id"] for rule in ledger["rules"]
    ]
    for rule, snapshot_record in zip(
        ledger["rules"], report["rule_snapshots"], strict=True
    ):
        assert "terminal_snapshot" in rule
        if rule["audit_status"] in COVERAGE.TERMINAL_AUDIT_STATUSES:
            snapshot = rule["terminal_snapshot"]
            assert isinstance(snapshot, dict)
            assert set(snapshot) == COVERAGE.TERMINAL_SNAPSHOT_FIELDS
            assert snapshot["rule_record_sha256"] == COVERAGE.rule_record_sha256(rule)
        else:
            assert rule["terminal_snapshot"] is None
        assert snapshot_record["terminal_snapshot"] == rule["terminal_snapshot"]


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

    _assert_invalid(ledger, "schema_version must equal 4")


def test_terminal_snapshot_field_declaration_cannot_drift() -> None:
    ledger = _ledger()
    ledger["terminal_snapshot_fields"].append("tree_digest")

    _assert_invalid(
        ledger,
        "terminal_snapshot_fields must contain exactly the required snapshot fields",
    )


def test_canonical_rule_record_known_vector() -> None:
    rule = {
        "zeta": {"emoji": "żółć", "nested": [3, 1]},
        "id": "known-vector",
        "terminal_snapshot": {"ignored": True},
        "alpha": ["β", {"z": 0, "a": False}],
    }
    expected = (
        '{"alpha":["β",{"a":false,"z":0}],"id":"known-vector",'
        '"zeta":{"emoji":"żółć","nested":[3,1]}}'
    ).encode("utf-8")

    assert COVERAGE._canonical_rule_record_bytes(rule) == expected
    assert (
        COVERAGE.rule_record_sha256(rule)
        == "afa65e89a33e2dd58a3aea9ab9a02e7f7409a5e750d812f9dec38cdb6cd66fdf"
    )

    rule["terminal_snapshot"] = {"different": ["snapshot", "content"]}
    assert COVERAGE._canonical_rule_record_bytes(rule) == expected
    assert (
        COVERAGE.rule_record_sha256(rule)
        == "afa65e89a33e2dd58a3aea9ab9a02e7f7409a5e750d812f9dec38cdb6cd66fdf"
    )


def test_terminal_rule_record_must_be_deeply_json_compatible() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    rule["future_metadata"] = {"invalid_number": float("nan")}

    _assert_invalid(
        ledger,
        "rule record must be deeply JSON-compatible for canonical serialization",
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


def test_malformed_sha_is_rejected_before_historical_resolver_invocation() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    rule["terminal_snapshot"]["audited_commit_sha"] = "A" * 40
    resolver_calls: list[str] = []

    def resolver(audited_commit_sha: str) -> list[str]:
        resolver_calls.append(audited_commit_sha)
        return _tracked_paths()

    with pytest.raises(COVERAGE.CoverageValidationError, match="lowercase 40-character"):
        COVERAGE.validate_coverage(
            ledger,
            _tracked_paths(),
            historical_path_resolver=resolver,
        )

    assert resolver_calls == []


def test_git_resolver_rejects_malformed_sha_before_git_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_run(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Git must not run for a malformed audited SHA")

    monkeypatch.setattr(COVERAGE.subprocess, "run", unexpected_run)

    with pytest.raises(COVERAGE.CoverageValidationError, match="before historical resolution"):
        COVERAGE.git_tracked_paths_at_commit(REPO_ROOT, "A" * 40)


def test_unexpected_terminal_snapshot_keys_are_rejected() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    rule["terminal_snapshot"]["tree_digest"] = "not-authorized"

    _assert_invalid(
        ledger,
        "terminal_snapshot must contain exactly audited_commit_sha, matched_paths, "
        "and rule_record_sha256",
    )


def test_missing_terminal_snapshot_digest_is_rejected() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    rule["terminal_snapshot"].pop("rule_record_sha256")

    _assert_invalid(
        ledger,
        "terminal_snapshot.rule_record_sha256 must be a lowercase 64-character SHA-256",
    )


@pytest.mark.parametrize("digest", ["a" * 63, "A" * 64, "g" * 64])
def test_malformed_terminal_snapshot_digest_is_rejected(digest: str) -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    rule["terminal_snapshot"]["rule_record_sha256"] = digest

    _assert_invalid(
        ledger,
        "terminal_snapshot.rule_record_sha256 must be a lowercase 64-character SHA-256",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "identity",
        "include",
        "exclude",
        "class",
        "primary_owner",
        "secondary_owners",
        "consequence_tier",
        "consequence_tags",
        "audit_status",
        "baseline_sha",
        "evidence_links",
        "finding_links",
        "disposition",
        "residual_risk",
        "unknown_future_field",
    ],
)
def test_every_rule_metadata_or_evidence_mutation_invalidates_old_evidence(
    mutation: str,
) -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    original_paths = _matched_paths(rule)
    original_digest = rule["terminal_snapshot"]["rule_record_sha256"]

    _mutate_terminal_rule_record(rule, mutation)

    assert _matched_paths(rule) == original_paths
    assert COVERAGE.rule_record_sha256(rule) != original_digest
    _assert_invalid(ledger, DIGEST_MISMATCH)


@pytest.mark.parametrize("field", sorted(COVERAGE.DEFERRED_DETAIL_FIELDS))
def test_every_deferral_detail_mutation_invalidates_old_evidence(field: str) -> None:
    ledger = _ledger()
    rule = _terminalize_rule(
        ledger,
        "application-lifecycle",
        status="deferred residual risk",
    )
    original_digest = rule["terminal_snapshot"]["rule_record_sha256"]
    rule["deferral_details"][field] += " Changed after evidence was captured."

    assert COVERAGE.rule_record_sha256(rule) != original_digest
    _assert_invalid(ledger, DIGEST_MISMATCH)


def test_digest_mismatch_is_rejected_before_historical_resolution() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    rule["disposition"] = "Stale evidence must fail before Git object resolution."
    resolver_calls: list[str] = []

    def resolver(audited_commit_sha: str) -> list[str]:
        resolver_calls.append(audited_commit_sha)
        return _tracked_paths()

    with pytest.raises(COVERAGE.CoverageValidationError, match=DIGEST_MISMATCH):
        COVERAGE.validate_coverage(
            ledger,
            _tracked_paths(),
            historical_path_resolver=resolver,
        )

    assert resolver_calls == []


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


def test_pending_ledger_does_not_invoke_historical_resolver() -> None:
    def unexpected_resolver(_audited_commit_sha: str) -> list[str]:
        pytest.fail("pending-only ledgers must not resolve historical commits")

    report = COVERAGE.validate_coverage(
        _ledger(),
        _tracked_paths(),
        historical_path_resolver=unexpected_resolver,
    )

    assert report["covered_file_count"] == report["tracked_file_count"]


def test_terminal_validation_without_historical_resolver_fails_closed() -> None:
    ledger = _ledger()
    _terminalize_rule(ledger, "application-lifecycle")

    with pytest.raises(
        COVERAGE.CoverageValidationError,
        match="historical validation requires a local commit-tree resolver",
    ):
        COVERAGE.validate_coverage(ledger, _tracked_paths())


def test_unavailable_historical_object_is_rejected() -> None:
    ledger = _ledger()
    _terminalize_rule(
        ledger,
        "application-lifecycle",
        audited_commit_sha="0" * 40,
    )

    _assert_invalid(
        ledger,
        "is unavailable locally; a shallow clone lacking the object is insufficient evidence",
        historical_path_resolver=lambda sha: COVERAGE.git_tracked_paths_at_commit(
            REPO_ROOT, sha
        ),
    )


def test_real_local_git_commits_enumerate_exact_historical_trees(
    local_git_history: tuple[Path, dict[str, str]],
) -> None:
    repo_root, object_shas = local_git_history

    assert COVERAGE.git_tracked_paths_at_commit(
        repo_root, object_shas["first_commit"]
    ) == ["README.md", "src/metroliza/app/first.py"]
    assert COVERAGE.git_tracked_paths_at_commit(
        repo_root, object_shas["second_commit"]
    ) == [
        "README.md",
        "src/metroliza/app/first.py",
        "src/metroliza/app/second.py",
    ]


@pytest.mark.parametrize("object_type", ["blob", "tree", "tag"])
def test_non_commit_git_object_is_rejected_without_tag_peeling(
    local_git_history: tuple[Path, dict[str, str]], object_type: str
) -> None:
    repo_root, object_shas = local_git_history

    with pytest.raises(
        COVERAGE.CoverageValidationError,
        match=rf"names a '{object_type}' object, not a commit",
    ):
        COVERAGE.git_tracked_paths_at_commit(repo_root, object_shas[object_type])


def test_shallow_clone_missing_historical_commit_fails_closed(
    local_git_history: tuple[Path, dict[str, str]], tmp_path: Path
) -> None:
    repo_root, object_shas = local_git_history
    shallow_root = tmp_path / "shallow-history"
    _git(
        tmp_path,
        "clone",
        "--depth",
        "1",
        "--no-tags",
        "--branch",
        "main",
        repo_root.resolve().as_uri(),
        str(shallow_root),
    )

    assert (shallow_root / ".git" / "shallow").is_file()
    with pytest.raises(
        COVERAGE.CoverageValidationError,
        match="is unavailable locally; a shallow clone lacking the object is insufficient",
    ):
        COVERAGE.git_tracked_paths_at_commit(
            shallow_root, object_shas["first_commit"]
        )


@pytest.mark.parametrize(
    ("ls_tree_output", "expected"),
    [
        (b"src/a.py", "malformed NUL-delimited path data"),
        (b"src/\xff.py\0", "non-UTF-8 path data"),
        (b"src/a.py\0src/a.py\0", "duplicate path"),
        (b"../a.py\0", "invalid repository-relative POSIX path"),
    ],
)
def test_historical_git_output_is_validated_strictly(
    monkeypatch: pytest.MonkeyPatch,
    ls_tree_output: bytes,
    expected: str,
) -> None:
    commands: list[list[str]] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        assert kwargs["shell"] is False
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["GIT_NO_LAZY_FETCH"] == "1"
        assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert environment["GIT_TERMINAL_PROMPT"] == "0"
        if command[1] == "cat-file":
            return subprocess.CompletedProcess(command, 0, stdout=b"commit\n", stderr=b"")
        return subprocess.CompletedProcess(command, 0, stdout=ls_tree_output, stderr=b"")

    monkeypatch.setattr(COVERAGE.subprocess, "run", fake_run)

    with pytest.raises(COVERAGE.CoverageValidationError, match=expected):
        COVERAGE.git_tracked_paths_at_commit(REPO_ROOT, SYNTHETIC_AUDITED_SHA)

    assert commands == [
        ["git", "cat-file", "-t", SYNTHETIC_AUDITED_SHA],
        [
            "git",
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            "--full-tree",
            SYNTHETIC_AUDITED_SHA,
        ],
    ]
    assert all("fetch" not in command for command in commands)


def test_historical_git_ls_tree_failure_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        if command[1] == "cat-file":
            return subprocess.CompletedProcess(command, 0, stdout=b"commit\n", stderr=b"")
        return subprocess.CompletedProcess(command, 128, stdout=b"", stderr=b"failed")

    monkeypatch.setattr(COVERAGE.subprocess, "run", fake_run)

    with pytest.raises(COVERAGE.CoverageValidationError, match="git ls-tree failed"):
        COVERAGE.git_tracked_paths_at_commit(REPO_ROOT, SYNTHETIC_AUDITED_SHA)


def test_mixed_pending_and_terminal_ledger_is_accepted_and_preserved() -> None:
    ledger = _ledger()
    audited_commit_sha = _current_commit_sha()
    rule = _terminalize_rule(
        ledger,
        "application-lifecycle",
        audited_commit_sha=audited_commit_sha,
    )
    expected_snapshot = copy.deepcopy(rule["terminal_snapshot"])

    report = _validate_coverage(
        ledger,
        historical_path_resolver=lambda sha: COVERAGE.git_tracked_paths_at_commit(
            REPO_ROOT, sha
        ),
    )

    assert rule["audit_status"] == "completed"
    assert all(
        current_rule["audit_status"] == "pending"
        and current_rule["terminal_snapshot"] is None
        for current_rule in ledger["rules"]
        if current_rule is not rule
    )
    assert report["covered_file_count"] == report["tracked_file_count"]
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


def test_historical_additional_matching_path_invalidates_terminal_snapshot() -> None:
    ledger = _ledger()
    _terminalize_rule(ledger, "application-lifecycle")
    historical_paths = sorted(
        [*_tracked_paths(), "src/metroliza/app/historical_addition.py"]
    )

    _assert_invalid(
        ledger,
        "historical expansion newly contains paths not recorded: "
        "src/metroliza/app/historical_addition.py",
        historical_path_resolver=_historical_resolver(historical_paths),
    )


def test_recorded_path_absent_from_historical_expansion_is_rejected() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    missing_path = _matched_paths(rule)[0]
    historical_paths = [path for path in _tracked_paths() if path != missing_path]

    _assert_invalid(
        ledger,
        f"recorded paths were absent from the audited commit expansion: {missing_path}",
        historical_path_resolver=_historical_resolver(historical_paths),
    )


def test_historical_resolution_is_cached_for_repeated_terminal_sha() -> None:
    ledger = _ledger()
    _terminalize_rule(ledger, "application-lifecycle")
    _terminalize_rule(ledger, "report-ingestion-contracts")
    resolver_calls: list[str] = []
    historical_paths = _tracked_paths()

    def resolver(audited_commit_sha: str) -> list[str]:
        resolver_calls.append(audited_commit_sha)
        return list(historical_paths)

    report = _validate_coverage(ledger, historical_path_resolver=resolver)

    assert report["covered_file_count"] == report["tracked_file_count"]
    assert resolver_calls == [SYNTHETIC_AUDITED_SHA]


def test_json_output_exposes_terminal_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = _ledger()
    expected_snapshot = copy.deepcopy(
        _terminalize_rule(
            ledger,
            "application-lifecycle",
            audited_commit_sha=_current_commit_sha(),
        )["terminal_snapshot"]
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


def test_current_drift_is_reported_even_when_historical_resolution_fails() -> None:
    ledger = _ledger()
    _terminalize_rule(ledger, "application-lifecycle")
    paths = sorted([*_tracked_paths(), "src/metroliza/app/current_drift.py"])

    def unavailable(_audited_commit_sha: str) -> list[str]:
        raise COVERAGE.CoverageValidationError("audited commit unavailable")

    with pytest.raises(COVERAGE.CoverageValidationError) as exc_info:
        COVERAGE.validate_coverage(
            ledger,
            paths,
            historical_path_resolver=unavailable,
        )

    diagnostic = str(exc_info.value)
    assert "audited commit unavailable" in diagnostic
    assert "newly matched: src/metroliza/app/current_drift.py" in diagnostic


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


def test_current_expansion_order_only_mismatch_is_distinguished() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    matching_paths = _matched_paths(rule)
    paths = _tracked_paths()
    first_index = paths.index(matching_paths[0])
    second_index = paths.index(matching_paths[1])
    paths[first_index], paths[second_index] = paths[second_index], paths[first_index]

    _assert_invalid(
        ledger,
        "recorded order differs from current deterministic expansion",
        paths,
    )


def test_path_owned_by_another_rule_does_not_invalidate_terminal_snapshot() -> None:
    ledger = _ledger()
    rule = _terminalize_rule(ledger, "application-lifecycle")
    expected_snapshot = copy.deepcopy(rule["terminal_snapshot"])
    paths = sorted([*_tracked_paths(), "src/metroliza/reports/new.py"])

    report = _validate_coverage(ledger, paths)

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
    rule.pop("deferral_details", None)

    _assert_invalid(ledger, "deferred residual risk requires structured deferral details")


def test_complete_deferred_residual_risk_record_is_accepted() -> None:
    ledger = _ledger()
    _terminalize_rule(
        ledger,
        "root-application-entrypoint",
        status="deferred residual risk",
    )

    report = _validate_coverage(ledger)

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

    report = _validate_coverage(_ledger(), paths)

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
        '{"schema_version": 4, "schema_version": 4}',
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

#!/usr/bin/env python3
"""Validate deterministic repository-wide bug-sweep ownership coverage."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 4
GIT_COMMAND_TIMEOUT_SECONDS = 30
EXPECTED_BASELINE_SHA = "fcb462942e90aeeb64bba84bfe080d556da0efdb"
EXPECTED_BASELINE_TRACKED_FILE_COUNT = 929
EXPECTED_OWNER_ISSUES = frozenset(range(975, 986))
EXPECTED_MAPPED_ISSUES = frozenset({*range(901, 909), *range(912, 958), 971})
EXPECTED_EXECUTION_ORDER = {
    975: "0",
    976: "1",
    983: "2",
    979: "3",
    980: "4",
    978: "5",
    981: "6",
    977: "7",
    982: "8",
    984: "9",
    985: "10",
}
EXPECTED_FOUNDATION_ADDED_PATHS = frozenset(
    {
        "docs/quality/bug_sweep/README.md",
        "docs/quality/bug_sweep/coverage.json",
        "docs/quality/bug_sweep/finding_template.md",
        "docs/quality/bug_sweep/residual_risk_template.md",
        "scripts/quality/validate_bug_sweep_coverage.py",
        "tests/test_bug_sweep_coverage.py",
    }
)
PATH_CLASSES = frozenset(
    {
        "canonical runtime",
        "compatibility runtime",
        "test",
        "fixture",
        "script/tooling",
        "workflow/configuration",
        "packaging/build",
        "active documentation",
        "archive/reference",
        "generated/static asset",
    }
)
AUDIT_STATUSES = frozenset(
    {
        "pending",
        "in progress",
        "completed",
        "blocked",
        "deferred residual risk",
        "accepted behavior",
    }
)
TERMINAL_AUDIT_STATUSES = frozenset(
    {"completed", "accepted behavior", "deferred residual risk"}
)
TERMINAL_SNAPSHOT_FIELDS = frozenset(
    {"audited_commit_sha", "matched_paths", "rule_record_sha256"}
)
DEFERRED_DETAIL_FIELDS = frozenset(
    {"reason", "accountable_owner", "target_issue_or_phase", "next_gate", "preserved_seam"}
)
CONSEQUENCE_TIERS = frozenset({"P0", "P1", "P2", "P3"})
CONSEQUENCE_TAGS = frozenset(
    {
        "audit-control",
        "cancellation",
        "compatibility",
        "confidentiality",
        "data-integrity",
        "dependency-platform",
        "native-parity",
        "numerical-correctness",
        "offline-behavior",
        "output-atomicity",
        "release-evidence",
        "windows-packaging",
    }
)


class CoverageValidationError(ValueError):
    """Raised when the ledger or its expansion is invalid."""


HistoricalPathResolver = Callable[[str], Sequence[str]]


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting ambiguous duplicate keys."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CoverageValidationError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def repository_root() -> Path:
    """Return the repository root containing this validator."""

    return Path(__file__).resolve().parents[2]


def load_ledger(path: Path) -> dict[str, Any]:
    """Load a coverage ledger using only the Python standard library."""

    try:
        raw = path.read_text(encoding="utf-8")
        document = json.loads(raw, object_pairs_hook=_object_without_duplicate_keys)
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageValidationError(f"unable to load coverage ledger {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise CoverageValidationError("coverage ledger root must be a JSON object")
    return document


def _canonical_rule_record_bytes(rule: Mapping[str, Any]) -> bytes:
    """Serialize every rule field except ``terminal_snapshot`` canonically."""

    try:
        rule_record = copy.deepcopy(
            {key: value for key, value in rule.items() if key != "terminal_snapshot"}
        )
        return json.dumps(
            rule_record,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise CoverageValidationError(
            "rule record must be deeply JSON-compatible for canonical serialization"
        ) from exc


def rule_record_sha256(rule: Mapping[str, Any]) -> str:
    """Return the accepted lowercase SHA-256 for a complete rule record."""

    return hashlib.sha256(_canonical_rule_record_bytes(rule)).hexdigest()


def git_tracked_paths(repo_root: Path) -> list[str]:
    """Return the exact tracked Git index as normalized POSIX paths."""

    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise CoverageValidationError(f"git ls-files failed: {stderr or 'unknown error'}")
    return sorted(
        item.decode("utf-8", errors="strict")
        for item in completed.stdout.split(b"\0")
        if item
    )


def _run_local_git(
    repo_root: Path, arguments: Sequence[str], failure_context: str
) -> subprocess.CompletedProcess[bytes]:
    git_environment = os.environ.copy()
    git_environment.update(
        {
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            shell=False,
            timeout=GIT_COMMAND_TIMEOUT_SECONDS,
            env=git_environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CoverageValidationError(
            f"{failure_context}: local Git command failed to execute"
        ) from exc


def _is_repository_relative_posix_path(path: str) -> bool:
    return (
        bool(path)
        and not path.startswith("/")
        and "\\" not in path
        and all(part not in {"", ".", ".."} for part in path.split("/"))
    )


def _git_object_type(repo_root: Path, audited_commit_sha: str) -> str:
    completed = _run_local_git(
        repo_root,
        ["cat-file", "-t", audited_commit_sha],
        f"unable to inspect audited_commit_sha {audited_commit_sha!r}",
    )
    if completed.returncode != 0:
        raise CoverageValidationError(
            f"audited commit {audited_commit_sha!r} is unavailable locally; "
            "a shallow clone lacking the object is insufficient evidence"
        )
    try:
        output = completed.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CoverageValidationError(
            f"git cat-file returned non-UTF-8 object-type data for "
            f"audited_commit_sha {audited_commit_sha!r}"
        ) from exc
    match = re.fullmatch(r"(blob|commit|tag|tree)\n", output)
    if match is None:
        raise CoverageValidationError(
            f"git cat-file returned invalid object-type data for "
            f"audited_commit_sha {audited_commit_sha!r}"
        )
    return match.group(1)


def _decode_historical_tree_paths(output: bytes, audited_commit_sha: str) -> list[str]:
    if output and not output.endswith(b"\0"):
        raise CoverageValidationError(
            f"git ls-tree returned malformed NUL-delimited path data for "
            f"audited commit {audited_commit_sha!r}"
        )
    raw_paths = output[:-1].split(b"\0") if output else []
    if any(not raw_path for raw_path in raw_paths):
        raise CoverageValidationError(
            f"git ls-tree returned malformed NUL-delimited path data for "
            f"audited commit {audited_commit_sha!r}"
        )
    try:
        paths = [raw_path.decode("utf-8", errors="strict") for raw_path in raw_paths]
    except UnicodeDecodeError as exc:
        raise CoverageValidationError(
            f"git ls-tree returned non-UTF-8 path data for "
            f"audited commit {audited_commit_sha!r}"
        ) from exc
    duplicate_paths = sorted(path for path, count in Counter(paths).items() if count > 1)
    if duplicate_paths:
        raise CoverageValidationError(
            f"git ls-tree returned duplicate path(s) for audited commit "
            f"{audited_commit_sha!r}: {', '.join(duplicate_paths)}"
        )
    invalid_paths = sorted(
        path for path in paths if not _is_repository_relative_posix_path(path)
    )
    if invalid_paths:
        raise CoverageValidationError(
            f"git ls-tree returned invalid repository-relative POSIX path(s) for "
            f"audited commit {audited_commit_sha!r}: "
            + ", ".join(repr(path) for path in invalid_paths)
        )
    return sorted(paths)


def git_tracked_paths_at_commit(repo_root: Path, audited_commit_sha: str) -> list[str]:
    """Return tracked paths from an exact locally available Git commit tree."""

    if not isinstance(audited_commit_sha, str) or not re.fullmatch(
        r"[0-9a-f]{40}", audited_commit_sha
    ):
        raise CoverageValidationError(
            "terminal_snapshot.audited_commit_sha must be a lowercase "
            "40-character Git SHA before historical resolution"
        )
    object_type = _git_object_type(repo_root, audited_commit_sha)
    if object_type != "commit":
        raise CoverageValidationError(
            f"audited_commit_sha {audited_commit_sha!r} names a {object_type!r} "
            "object, not a commit"
        )
    completed = _run_local_git(
        repo_root,
        [
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            "--full-tree",
            audited_commit_sha,
        ],
        f"git ls-tree failed for audited commit {audited_commit_sha!r}",
    )
    if completed.returncode != 0:
        raise CoverageValidationError(
            f"git ls-tree failed for audited commit {audited_commit_sha!r}"
        )
    return _decode_historical_tree_paths(completed.stdout, audited_commit_sha)


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Compile a slash-aware glob where ``**`` crosses directory boundaries."""

    chunks: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                if index + 2 < len(pattern) and pattern[index + 2] == "/":
                    chunks.append("(?:.*/)?")
                    index += 3
                else:
                    chunks.append(".*")
                    index += 2
            else:
                chunks.append("[^/]*")
                index += 1
        elif character == "?":
            chunks.append("[^/]")
            index += 1
        else:
            chunks.append(re.escape(character))
            index += 1
    chunks.append("$")
    return re.compile("".join(chunks))


def path_matches(pattern: str, path: str) -> bool:
    """Return whether a repository-relative POSIX path matches a ledger glob."""

    return bool(_glob_regex(pattern).fullmatch(path))


def rule_matches(rule: Mapping[str, Any], path: str) -> bool:
    """Return whether a path is included, and not excluded, by a rule."""

    includes = rule["include"]
    excludes = rule["exclude"]
    return any(path_matches(pattern, path) for pattern in includes) and not any(
        path_matches(pattern, path) for pattern in excludes
    )


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _non_empty_string_list(value: object) -> bool:
    return _string_list(value) and all(item.strip() for item in value)


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _owner_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
        and len(value) == len(set(value))
    )


def _validate_pattern(pattern: str, context: str, errors: list[str]) -> None:
    if not pattern:
        errors.append(f"{context}: glob must not be empty")
    if pattern.startswith("/") or "\\" in pattern:
        errors.append(f"{context}: glob must be a repository-relative POSIX path: {pattern!r}")
    if ".." in Path(pattern).parts:
        errors.append(f"{context}: glob must not traverse above the repository: {pattern!r}")
    try:
        _glob_regex(pattern)
    except re.error as exc:
        errors.append(f"{context}: invalid glob {pattern!r}: {exc}")


def _validate_schema_version(ledger: Mapping[str, Any], errors: list[str]) -> None:
    schema_version = ledger.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != SCHEMA_VERSION
    ):
        errors.append(f"schema_version must equal {SCHEMA_VERSION}")


def _validate_baseline(ledger: Mapping[str, Any], errors: list[str]) -> object:
    baseline = ledger.get("baseline")
    if not isinstance(baseline, dict):
        errors.append("baseline must be an object")
        return None

    baseline_sha = baseline.get("sha")
    if baseline.get("branch") != "develop":
        errors.append("baseline.branch must equal 'develop'")
    if baseline_sha != EXPECTED_BASELINE_SHA:
        errors.append(f"baseline.sha must equal the authorized SHA {EXPECTED_BASELINE_SHA}")
    tracked_count = baseline.get("tracked_file_count")
    if (
        not isinstance(tracked_count, int)
        or isinstance(tracked_count, bool)
        or tracked_count != EXPECTED_BASELINE_TRACKED_FILE_COUNT
    ):
        errors.append(
            "baseline.tracked_file_count must equal the verified baseline count "
            f"{EXPECTED_BASELINE_TRACKED_FILE_COUNT}"
        )
    if baseline.get("tree_source") != "git ls-files":
        errors.append("baseline.tree_source must equal 'git ls-files'")
    return baseline_sha


def _validate_exact_string_set(
    value: object,
    expected: frozenset[str],
    message: str,
    errors: list[str],
) -> None:
    if (
        not _non_empty_string_list(value)
        or len(value) != len(set(value))
        or set(value) != expected
    ):
        errors.append(message)


def _validate_declared_contracts(ledger: Mapping[str, Any], errors: list[str]) -> None:
    _validate_exact_string_set(
        ledger.get("foundation_added_paths"),
        EXPECTED_FOUNDATION_ADDED_PATHS,
        "foundation_added_paths must contain exactly the six authorized new paths",
        errors,
    )
    _validate_exact_string_set(
        ledger.get("path_classes"),
        PATH_CLASSES,
        "path_classes must contain exactly the authorized ten classes",
        errors,
    )
    _validate_exact_string_set(
        ledger.get("audit_statuses"),
        AUDIT_STATUSES,
        "audit_statuses must contain exactly the validator-supported statuses",
        errors,
    )
    _validate_exact_string_set(
        ledger.get("terminal_snapshot_fields"),
        TERMINAL_SNAPSHOT_FIELDS,
        "terminal_snapshot_fields must contain exactly the required snapshot fields",
        errors,
    )
    _validate_exact_string_set(
        ledger.get("deferred_residual_risk_fields"),
        DEFERRED_DETAIL_FIELDS,
        "deferred_residual_risk_fields must contain exactly the required deferral fields",
        errors,
    )
    _validate_exact_string_set(
        ledger.get("consequence_tags"),
        CONSEQUENCE_TAGS,
        "consequence_tags must contain exactly the validator-supported tags",
        errors,
    )


def _validate_workstream_record(issue: int, record: object, errors: list[str]) -> None:
    context = f"workstream #{issue}"
    if not isinstance(record, dict):
        errors.append(f"{context}: record must be an object")
        return
    if record.get("issue_url") != f"https://github.com/hexafe/metroliza/issues/{issue}":
        errors.append(f"{context}: issue_url must reference the authoritative GitHub Issue")
    if not _non_empty_string(record.get("title")):
        errors.append(f"{context}: title must be non-empty")
    if record.get("state") != "open":
        errors.append(f"{context}: captured state must be 'open'")
    if record.get("execution_order") != EXPECTED_EXECUTION_ORDER[issue]:
        errors.append(
            f"{context}: execution_order must equal {EXPECTED_EXECUTION_ORDER[issue]!r}"
        )


def _validate_workstreams(ledger: Mapping[str, Any], errors: list[str]) -> set[int]:
    workstreams = ledger.get("workstreams")
    if not isinstance(workstreams, dict):
        errors.append("workstreams must be an object")
        return set()

    expected_workstream_keys = {str(issue) for issue in EXPECTED_OWNER_ISSUES}
    workstream_keys = set(workstreams)
    workstream_issues = {
        int(key) for key in workstream_keys if key in expected_workstream_keys
    }
    if workstream_keys != expected_workstream_keys:
        errors.append("workstreams must define exactly Issues #975-#985")
    for issue in sorted(EXPECTED_OWNER_ISSUES & workstream_issues):
        _validate_workstream_record(issue, workstreams.get(str(issue)), errors)
    return workstream_issues


def _rule_context(
    rule: Mapping[str, Any],
    position: int,
    rule_ids: set[str],
    errors: list[str],
) -> str:
    context = f"rule[{position}]"
    rule_id = rule.get("id")
    if not _non_empty_string(rule_id):
        errors.append(f"{context}: id must be non-empty")
    elif rule_id in rule_ids:
        errors.append(f"{context}: duplicate rule id {rule_id!r}")
    else:
        rule_ids.add(rule_id)
        context = f"rule {rule_id!r}"
    return context


def _validate_rule_patterns(
    rule: Mapping[str, Any], context: str, errors: list[str]
) -> None:
    includes = rule.get("include")
    excludes = rule.get("exclude")
    if not _string_list(includes) or not includes:
        errors.append(f"{context}: include must be a non-empty string array")
    else:
        for pattern in includes:
            _validate_pattern(pattern, context, errors)
    if not _string_list(excludes):
        errors.append(f"{context}: exclude must be a string array")
    else:
        for pattern in excludes:
            _validate_pattern(pattern, context, errors)


def _validate_rule_ownership(
    rule: Mapping[str, Any],
    context: str,
    workstream_issues: set[int],
    errors: list[str],
) -> None:
    path_class = rule.get("class")
    if path_class not in PATH_CLASSES:
        errors.append(f"{context}: invalid class {path_class!r}")
    primary_owner = rule.get("primary_owner")
    if (
        not isinstance(primary_owner, int)
        or isinstance(primary_owner, bool)
        or primary_owner not in workstream_issues
    ):
        errors.append(f"{context}: unknown Issue owner {primary_owner!r}")
    secondary_owners = rule.get("secondary_owners")
    if not _owner_list(secondary_owners):
        errors.append(f"{context}: secondary_owners must be a unique integer array")
        return
    unknown_secondary = set(secondary_owners) - workstream_issues
    if unknown_secondary:
        errors.append(
            f"{context}: unknown secondary Issue owner(s) "
            + ", ".join(f"#{issue}" for issue in sorted(unknown_secondary))
        )
    if primary_owner in secondary_owners:
        errors.append(f"{context}: primary owner cannot also be a secondary owner")


def _validate_rule_consequence(
    rule: Mapping[str, Any], context: str, errors: list[str]
) -> None:
    consequence_tier = rule.get("consequence_tier")
    if consequence_tier not in CONSEQUENCE_TIERS:
        errors.append(f"{context}: invalid consequence tier {consequence_tier!r}")
    tags = rule.get("consequence_tags")
    if not _string_list(tags) or not tags:
        errors.append(f"{context}: consequence_tags must be a non-empty string array")
        return
    unknown_tags = set(tags) - CONSEQUENCE_TAGS
    if unknown_tags:
        errors.append(
            f"{context}: invalid consequence tag(s) " + ", ".join(sorted(unknown_tags))
        )
    if len(tags) != len(set(tags)):
        errors.append(f"{context}: consequence_tags must not contain duplicates")


def _validate_rule_evidence(
    rule: Mapping[str, Any], context: str, errors: list[str]
) -> object:
    for field in ("evidence_links", "finding_links"):
        if not _non_empty_string_list(rule.get(field)):
            errors.append(f"{context}: {field} must contain only non-empty strings")
    disposition = rule.get("disposition")
    if disposition is not None and not _non_empty_string(disposition):
        errors.append(f"{context}: disposition must be null or a non-empty string")
    if not _non_empty_string(rule.get("residual_risk")):
        errors.append(f"{context}: residual_risk must be non-empty")
    return disposition


def _validate_terminal_rule(
    rule: Mapping[str, Any],
    status: object,
    disposition: object,
    context: str,
    errors: list[str],
) -> None:
    if status not in TERMINAL_AUDIT_STATUSES:
        return
    if not rule.get("evidence_links"):
        errors.append(f"{context}: {status} coverage requires evidence")
    if not _non_empty_string(disposition):
        errors.append(f"{context}: {status} coverage requires a disposition")


def _validate_terminal_snapshot_path(
    path: str, context: str, errors: list[str]
) -> None:
    parts = path.split("/")
    if path.startswith("/") or "\\" in path or any(
        part in {"", ".", ".."} for part in parts
    ):
        errors.append(
            f"{context}: terminal_snapshot.matched_paths must contain only "
            f"repository-relative POSIX paths: {path!r}"
        )
    if "*" in path or "?" in path:
        errors.append(
            f"{context}: terminal_snapshot.matched_paths must contain explicit paths, "
            f"not globs: {path!r}"
        )


def _validate_rule_record_digest(
    rule: Mapping[str, Any], digest: object, context: str, errors: list[str]
) -> None:
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        errors.append(
            f"{context}: terminal_snapshot.rule_record_sha256 must be a lowercase "
            "64-character SHA-256"
        )
        return
    try:
        expected_digest = rule_record_sha256(rule)
    except CoverageValidationError as exc:
        errors.append(f"{context}: {exc}")
        return
    if digest != expected_digest:
        errors.append(
            f"{context}: terminal_snapshot.rule_record_sha256 does not match the "
            "complete canonical rule record"
        )


def _validate_terminal_snapshot_record(
    rule: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    context: str,
    errors: list[str],
) -> None:
    if set(snapshot) != TERMINAL_SNAPSHOT_FIELDS:
        errors.append(
            f"{context}: terminal_snapshot must contain exactly "
            "audited_commit_sha, matched_paths, and rule_record_sha256"
        )
    audited_commit_sha = snapshot.get("audited_commit_sha")
    if not isinstance(audited_commit_sha, str) or not re.fullmatch(
        r"[0-9a-f]{40}", audited_commit_sha
    ):
        errors.append(
            f"{context}: terminal_snapshot.audited_commit_sha must be a lowercase "
            "40-character Git SHA"
        )
    _validate_rule_record_digest(
        rule, snapshot.get("rule_record_sha256"), context, errors
    )
    matched_paths = snapshot.get("matched_paths")
    if not _non_empty_string_list(matched_paths) or not matched_paths:
        errors.append(
            f"{context}: terminal_snapshot.matched_paths must be a non-empty array "
            "of non-empty strings"
        )
        return
    if matched_paths != sorted(matched_paths):
        errors.append(
            f"{context}: terminal_snapshot.matched_paths must be sorted deterministically"
        )
    if len(matched_paths) != len(set(matched_paths)):
        errors.append(
            f"{context}: terminal_snapshot.matched_paths must not contain duplicates"
        )
    for path in matched_paths:
        _validate_terminal_snapshot_path(path, context, errors)


def _validate_terminal_snapshot(
    rule: Mapping[str, Any], status: object, context: str, errors: list[str]
) -> None:
    if "terminal_snapshot" not in rule:
        errors.append(f"{context}: terminal_snapshot must be present explicitly")
        return
    snapshot = rule.get("terminal_snapshot")
    if status in TERMINAL_AUDIT_STATUSES:
        if not isinstance(snapshot, dict):
            errors.append(f"{context}: {status} coverage requires a terminal_snapshot")
            return
        _validate_terminal_snapshot_record(rule, snapshot, context, errors)
    elif snapshot is not None:
        errors.append(
            f"{context}: terminal_snapshot is allowed only for a terminal audit status"
        )


def _validate_deferred_detail_record(
    details: Mapping[str, Any], context: str, errors: list[str]
) -> None:
    if set(details) != DEFERRED_DETAIL_FIELDS:
        errors.append(f"{context}: deferral_details must contain exactly the required fields")
    for field in DEFERRED_DETAIL_FIELDS:
        if not _non_empty_string(details.get(field)):
            errors.append(f"{context}: deferral_details.{field} must be non-empty")


def _validate_deferral_details(
    status: object, details: object, context: str, errors: list[str]
) -> None:
    if status == "deferred residual risk":
        if not isinstance(details, dict):
            errors.append(
                f"{context}: deferred residual risk requires structured deferral details"
            )
            return
        _validate_deferred_detail_record(details, context, errors)
    elif details is not None:
        errors.append(f"{context}: deferral_details is allowed only for deferred residual risk")


def _validate_rule_audit(
    rule: Mapping[str, Any], baseline_sha: object, context: str, errors: list[str]
) -> None:
    status = rule.get("audit_status")
    if status not in AUDIT_STATUSES:
        errors.append(f"{context}: invalid audit status {status!r}")
    if rule.get("baseline_sha") != baseline_sha:
        errors.append(f"{context}: baseline_sha must equal baseline.sha")
    disposition = _validate_rule_evidence(rule, context, errors)
    _validate_terminal_rule(rule, status, disposition, context, errors)
    _validate_terminal_snapshot(rule, status, context, errors)
    _validate_deferral_details(status, rule.get("deferral_details"), context, errors)


def _validate_rule(
    rule: Mapping[str, Any],
    position: int,
    rule_ids: set[str],
    baseline_sha: object,
    workstream_issues: set[int],
    errors: list[str],
) -> None:
    context = _rule_context(rule, position, rule_ids, errors)
    _validate_rule_patterns(rule, context, errors)
    _validate_rule_ownership(rule, context, workstream_issues, errors)
    _validate_rule_consequence(rule, context, errors)
    _validate_rule_audit(rule, baseline_sha, context, errors)


def _validate_rules(
    ledger: Mapping[str, Any],
    baseline_sha: object,
    workstream_issues: set[int],
    errors: list[str],
) -> bool:
    rules = ledger.get("rules")
    if not isinstance(rules, list) or not rules:
        errors.append("rules must be a non-empty array")
        return False

    rule_ids: set[str] = set()
    for position, rule in enumerate(rules):
        context = f"rule[{position}]"
        if not isinstance(rule, dict):
            errors.append(f"{context}: rule must be an object")
            continue
        _validate_rule(
            rule,
            position,
            rule_ids,
            baseline_sha,
            workstream_issues,
            errors,
        )
    return True


def _validate_audit_owners(
    record: Mapping[str, Any],
    context: str,
    workstream_issues: set[int],
    errors: list[str],
) -> None:
    owners = record.get("audit_owners")
    if not _owner_list(owners) or not owners:
        errors.append(f"{context}: audit_owners must be a non-empty unique integer array")
    elif set(owners) - workstream_issues:
        errors.append(f"{context}: audit_owners contains an unknown workstream")


def _validate_mapped_issue_identity(
    record: object,
    context: str,
    mapped_issues: set[int],
    errors: list[str],
) -> int | None:
    if not isinstance(record, dict):
        errors.append(f"{context}: record must be an object")
        return None
    issue = record.get("issue")
    if not isinstance(issue, int) or isinstance(issue, bool):
        errors.append(f"{context}: issue must be an integer")
        return None
    if issue in mapped_issues:
        errors.append(f"{context}: duplicate Issue #{issue}")
    mapped_issues.add(issue)
    if not (901 <= issue <= 957 or issue == 971):
        errors.append(f"{context}: Issue #{issue} is outside the required current map")
    return issue


def _validate_mapped_issue_record(
    record: Mapping[str, Any],
    context: str,
    workstream_issues: set[int],
    errors: list[str],
) -> None:
    if record.get("state") != "open":
        errors.append(f"{context}: mapped Issue state must be 'open'")
    if not _non_empty_string(record.get("title")):
        errors.append(f"{context}: title must be non-empty")
    if not _non_empty_string(record.get("surface")):
        errors.append(f"{context}: surface must be non-empty")
    _validate_audit_owners(record, context, workstream_issues, errors)


def _validate_mapped_issue_set(mapped_issues: set[int], errors: list[str]) -> None:
    if mapped_issues == EXPECTED_MAPPED_ISSUES:
        return
    missing = EXPECTED_MAPPED_ISSUES - mapped_issues
    unexpected = mapped_issues - EXPECTED_MAPPED_ISSUES
    if missing:
        errors.append(
            "existing_issue_map is missing current open Issue(s): "
            + ", ".join(f"#{issue}" for issue in sorted(missing))
        )
    if unexpected:
        errors.append(
            "existing_issue_map contains unexpected Issue(s): "
            + ", ".join(f"#{issue}" for issue in sorted(unexpected))
        )


def _validate_issue_map(
    ledger: Mapping[str, Any], workstream_issues: set[int], errors: list[str]
) -> None:
    issue_map = ledger.get("existing_issue_map")
    if not isinstance(issue_map, list):
        errors.append("existing_issue_map must be an array")
        return

    mapped_issues: set[int] = set()
    for position, record in enumerate(issue_map):
        context = f"existing_issue_map[{position}]"
        issue = _validate_mapped_issue_identity(record, context, mapped_issues, errors)
        if issue is None:
            continue
        _validate_mapped_issue_record(record, context, workstream_issues, errors)
    _validate_mapped_issue_set(mapped_issues, errors)


def _compatibility_input_numbers_valid(inputs: Sequence[object]) -> bool:
    input_numbers = [item.get("pr") for item in inputs if isinstance(item, dict)]
    return (
        len(input_numbers) == 2
        and all(
            isinstance(number, int) and not isinstance(number, bool)
            for number in input_numbers
        )
        and len(input_numbers) == len(set(input_numbers))
        and set(input_numbers) == {972, 973}
    )


def _validate_compatibility_input_record(
    record: object,
    position: int,
    workstream_issues: set[int],
    errors: list[str],
) -> None:
    context = f"external_compatibility_inputs[{position}]"
    if not isinstance(record, dict):
        errors.append(f"{context}: record must be an object")
        return
    if record.get("treatment") != "compatibility input only; no edit, merge, or acceptance":
        errors.append(f"{context}: treatment must preserve the no-mutation boundary")
    if record.get("state") != "open" or record.get("base") != "develop":
        errors.append(f"{context}: captured PR state/base must be open/develop")
    head_sha = record.get("head_sha")
    if not isinstance(head_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        errors.append(f"{context}: head_sha must be a lowercase 40-character Git SHA")
    _validate_audit_owners(record, context, workstream_issues, errors)


def _validate_compatibility_inputs(
    ledger: Mapping[str, Any], workstream_issues: set[int], errors: list[str]
) -> None:
    compatibility_inputs = ledger.get("external_compatibility_inputs")
    if not isinstance(compatibility_inputs, list):
        errors.append("external_compatibility_inputs must be an array")
        return
    if not _compatibility_input_numbers_valid(compatibility_inputs):
        errors.append("external_compatibility_inputs must contain exactly PRs #972 and #973")
    for position, record in enumerate(compatibility_inputs):
        _validate_compatibility_input_record(record, position, workstream_issues, errors)


def _validate_ledger_schema(ledger: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    _validate_schema_version(ledger, errors)
    baseline_sha = _validate_baseline(ledger, errors)
    _validate_declared_contracts(ledger, errors)
    workstream_issues = _validate_workstreams(ledger, errors)
    if not _validate_rules(ledger, baseline_sha, workstream_issues, errors):
        return errors
    _validate_issue_map(ledger, workstream_issues, errors)
    _validate_compatibility_inputs(ledger, workstream_issues, errors)
    return errors


def _validate_tracked_paths(paths: list[str], errors: list[str]) -> None:
    if paths != sorted(paths):
        errors.append("tracked paths must be sorted deterministically")
    if len(paths) != len(set(paths)):
        errors.append("tracked paths must not contain duplicates")
    for path in paths:
        if not path or path.startswith("/") or "\\" in path:
            errors.append(f"invalid tracked repository path: {path!r}")
    missing_foundation_paths = EXPECTED_FOUNDATION_ADDED_PATHS - set(paths)
    if missing_foundation_paths:
        errors.append(
            "tracked tree is missing authorized foundation path(s): "
            + ", ".join(sorted(missing_foundation_paths))
        )


def _copy_terminal_snapshot(rule: Mapping[str, Any]) -> dict[str, Any] | None:
    snapshot = rule["terminal_snapshot"]
    if snapshot is None:
        return None
    return {
        "audited_commit_sha": snapshot["audited_commit_sha"],
        "matched_paths": list(snapshot["matched_paths"]),
        "rule_record_sha256": snapshot["rule_record_sha256"],
    }


def _coverage_row(path: str, rule: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": path,
        "rule": rule["id"],
        "class": rule["class"],
        "primary_owner": rule["primary_owner"],
        "secondary_owners": list(rule["secondary_owners"]),
        "consequence_tier": rule["consequence_tier"],
        "consequence_tags": list(rule["consequence_tags"]),
        "audit_status": rule["audit_status"],
        "terminal_snapshot": _copy_terminal_snapshot(rule),
        "baseline_sha": rule["baseline_sha"],
        "evidence_links": list(rule["evidence_links"]),
        "finding_links": list(rule["finding_links"]),
        "disposition": rule["disposition"],
        "residual_risk": rule["residual_risk"],
        "deferral_details": rule.get("deferral_details"),
    }


def _expand_coverage(
    rules: Sequence[Mapping[str, Any]], paths: Sequence[str]
) -> tuple[
    list[tuple[str, Mapping[str, Any]]],
    list[str],
    list[tuple[str, list[str]]],
    Counter[str],
    dict[str, list[str]],
]:
    assignments: list[tuple[str, Mapping[str, Any]]] = []
    uncovered: list[str] = []
    duplicate_primary: list[tuple[str, list[str]]] = []
    rule_match_counts: Counter[str] = Counter()
    rule_matched_paths = {str(rule["id"]): [] for rule in rules}
    for path in paths:
        matches = [rule for rule in rules if rule_matches(rule, path)]
        for rule in matches:
            rule_id = str(rule["id"])
            rule_match_counts[rule_id] += 1
            rule_matched_paths[rule_id].append(path)
        if not matches:
            uncovered.append(path)
            continue
        if len(matches) > 1:
            duplicate_primary.append((path, [str(rule["id"]) for rule in matches]))
            continue
        assignments.append((path, matches[0]))
    return (
        assignments,
        uncovered,
        duplicate_primary,
        rule_match_counts,
        rule_matched_paths,
    )


def _append_expansion_errors(
    rules: Sequence[Mapping[str, Any]],
    assignments: Sequence[tuple[str, Mapping[str, Any]]],
    uncovered: Sequence[str],
    duplicate_primary: Sequence[tuple[str, list[str]]],
    rule_match_counts: Counter[str],
    errors: list[str],
) -> Counter[int]:
    for path in uncovered:
        errors.append(f"unassigned tracked path: {path}")
    for path, rule_ids in duplicate_primary:
        errors.append(
            f"duplicate primary ownership: {path} matched rules {', '.join(rule_ids)}"
        )
    for rule in rules:
        if rule_match_counts[str(rule["id"])] == 0:
            errors.append(f"ownership rule matches zero tracked paths: {rule['id']}")

    owner_counts = Counter(rule["primary_owner"] for _, rule in assignments)
    missing_workstreams = EXPECTED_OWNER_ISSUES - set(owner_counts)
    if missing_workstreams:
        errors.append(
            "workstream(s) with zero primary paths: "
            + ", ".join(f"#{issue}" for issue in sorted(missing_workstreams))
        )
    return owner_counts


def _validate_resolved_historical_paths(
    audited_commit_sha: str, resolved_paths: Sequence[str]
) -> list[str]:
    if isinstance(resolved_paths, (str, bytes)):
        raise CoverageValidationError(
            f"historical resolver for audited commit {audited_commit_sha!r} "
            "must return only repository-relative path strings"
        )
    paths = list(resolved_paths)
    if not all(isinstance(path, str) for path in paths):
        raise CoverageValidationError(
            f"historical resolver for audited commit {audited_commit_sha!r} "
            "must return only repository-relative path strings"
        )
    if paths != sorted(paths):
        raise CoverageValidationError(
            f"historical resolver for audited commit {audited_commit_sha!r} "
            "returned paths that are not sorted deterministically"
        )
    if len(paths) != len(set(paths)):
        raise CoverageValidationError(
            f"historical resolver for audited commit {audited_commit_sha!r} "
            "returned duplicate paths"
        )
    invalid_paths = [
        path for path in paths if not _is_repository_relative_posix_path(path)
    ]
    if invalid_paths:
        raise CoverageValidationError(
            f"historical resolver for audited commit {audited_commit_sha!r} returned "
            "invalid repository-relative POSIX path(s): "
            + ", ".join(repr(path) for path in invalid_paths)
        )
    return paths


def _resolve_historical_paths(
    audited_commit_sha: str,
    historical_path_resolver: HistoricalPathResolver | None,
) -> tuple[list[str] | None, str | None]:
    if historical_path_resolver is None:
        return (
            None,
            "terminal snapshot historical validation requires a local "
            "commit-tree resolver",
        )
    try:
        resolved_paths = historical_path_resolver(audited_commit_sha)
        return (
            _validate_resolved_historical_paths(audited_commit_sha, resolved_paths),
            None,
        )
    except CoverageValidationError as exc:
        return None, str(exc)
    except Exception:
        return (
            None,
            f"historical resolver failed for audited commit {audited_commit_sha!r}",
        )


def _terminal_historical_resolutions(
    rules: Sequence[Mapping[str, Any]],
    historical_path_resolver: HistoricalPathResolver | None,
) -> dict[str, tuple[list[str] | None, str | None]]:
    audited_commit_shas = sorted(
        {
            rule["terminal_snapshot"]["audited_commit_sha"]
            for rule in rules
            if rule["audit_status"] in TERMINAL_AUDIT_STATUSES
        }
    )
    return {
        audited_commit_sha: _resolve_historical_paths(
            audited_commit_sha, historical_path_resolver
        )
        for audited_commit_sha in audited_commit_shas
    }


def _snapshot_expansion_details(
    recorded_paths: Sequence[str], actual_paths: Sequence[str], expansion: str
) -> list[str]:
    newly_matched = sorted(set(actual_paths) - set(recorded_paths))
    no_longer_matched = sorted(set(recorded_paths) - set(actual_paths))
    if expansion == "historical":
        details = (
            [
                "historical expansion newly contains paths not recorded: "
                + ", ".join(newly_matched)
            ]
            if newly_matched
            else []
        )
        if no_longer_matched:
            details.append(
                "recorded paths were absent from the audited commit expansion: "
                + ", ".join(no_longer_matched)
            )
        order_message = "recorded order differs from historical deterministic expansion"
    else:
        details = (
            ["newly matched: " + ", ".join(newly_matched)]
            if newly_matched
            else []
        )
        if no_longer_matched:
            details.append("no longer matched: " + ", ".join(no_longer_matched))
        order_message = "recorded order differs from current deterministic expansion"
    return details or [order_message]


def _append_snapshot_expansion_error(
    rule: Mapping[str, Any],
    recorded_paths: Sequence[str],
    actual_paths: Sequence[str],
    expansion: str,
    errors: list[str],
) -> None:
    if recorded_paths == actual_paths:
        return
    details = _snapshot_expansion_details(recorded_paths, actual_paths, expansion)
    if expansion == "historical":
        audited_commit_sha = rule["terminal_snapshot"]["audited_commit_sha"]
        target = (
            "the historical deterministic expansion at audited_commit_sha "
            f"{audited_commit_sha!r}"
        )
    else:
        target = "the current deterministic expansion"
    errors.append(
        f"rule {rule['id']!r}: terminal_snapshot.matched_paths does not equal "
        f"{target} ({'; '.join(details)})"
    )


def _append_terminal_snapshot_errors(
    rules: Sequence[Mapping[str, Any]],
    rule_matched_paths: Mapping[str, list[str]],
    historical_path_resolver: HistoricalPathResolver | None,
    errors: list[str],
) -> None:
    resolutions = _terminal_historical_resolutions(rules, historical_path_resolver)
    for rule in rules:
        if rule["audit_status"] not in TERMINAL_AUDIT_STATUSES:
            continue
        snapshot = rule["terminal_snapshot"]
        audited_commit_sha = snapshot["audited_commit_sha"]
        recorded_paths = snapshot["matched_paths"]
        historical_paths, resolution_error = resolutions[audited_commit_sha]
        if resolution_error is not None:
            errors.append(f"rule {rule['id']!r}: {resolution_error}")
        elif historical_paths is not None:
            historical_matches = [
                path for path in historical_paths if rule_matches(rule, path)
            ]
            _append_snapshot_expansion_error(
                rule,
                recorded_paths,
                historical_matches,
                "historical",
                errors,
            )
        _append_snapshot_expansion_error(
            rule,
            recorded_paths,
            rule_matched_paths[str(rule["id"])],
            "current",
            errors,
        )


def _coverage_report(
    ledger: Mapping[str, Any],
    paths: Sequence[str],
    rows: list[dict[str, Any]],
    owner_counts: Counter[int],
) -> dict[str, Any]:
    class_counts = Counter(row["class"] for row in rows)
    rules: Sequence[Mapping[str, Any]] = ledger["rules"]
    return {
        "baseline_sha": ledger["baseline"]["sha"],
        "baseline_tracked_file_count": ledger["baseline"]["tracked_file_count"],
        "tracked_file_count": len(paths),
        "covered_file_count": len(rows),
        "uncovered_count": 0,
        "duplicate_primary_count": 0,
        "owner_counts": {str(key): owner_counts[key] for key in sorted(owner_counts)},
        "class_counts": {key: class_counts[key] for key in sorted(class_counts)},
        "rule_snapshots": [
            {
                "rule": rule["id"],
                "terminal_snapshot": _copy_terminal_snapshot(rule),
            }
            for rule in rules
        ],
        "rows": rows,
    }


def validate_coverage(
    ledger: Mapping[str, Any],
    tracked_paths: Iterable[str],
    historical_path_resolver: HistoricalPathResolver | None = None,
) -> dict[str, Any]:
    """Validate the ledger and expand every tracked path to one primary rule."""

    errors = _validate_ledger_schema(ledger)
    if errors:
        raise CoverageValidationError("\n".join(errors))

    paths = list(tracked_paths)
    _validate_tracked_paths(paths, errors)
    rules: Sequence[Mapping[str, Any]] = ledger["rules"]
    (
        assignments,
        uncovered,
        duplicate_primary,
        rule_match_counts,
        rule_matched_paths,
    ) = _expand_coverage(rules, paths)
    owner_counts = _append_expansion_errors(
        rules,
        assignments,
        uncovered,
        duplicate_primary,
        rule_match_counts,
        errors,
    )
    _append_terminal_snapshot_errors(
        rules,
        rule_matched_paths,
        historical_path_resolver,
        errors,
    )
    if errors:
        raise CoverageValidationError("\n".join(errors))
    rows = [_coverage_row(path, rule) for path, rule in assignments]
    return _coverage_report(ledger, paths, rows, owner_counts)


def _print_human_summary(report: Mapping[str, Any]) -> None:
    print(
        "Bug-sweep coverage valid: "
        f"{report['covered_file_count']}/{report['tracked_file_count']} tracked paths covered; "
        "0 uncovered; 0 duplicate-primary."
    )
    print("Primary owners:")
    for issue, count in report["owner_counts"].items():
        print(f"  #{issue}: {count}")
    print("Path classes:")
    for path_class, count in report["class_counts"].items():
        print(f"  {path_class}: {count}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repository_root(),
        help="repository root used for git ls-files",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="coverage ledger path (default: docs/quality/bug_sweep/coverage.json)",
    )
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    ledger_path = (
        args.ledger.resolve()
        if args.ledger is not None
        else repo_root / "docs" / "quality" / "bug_sweep" / "coverage.json"
    )
    try:
        report = validate_coverage(
            load_ledger(ledger_path),
            git_tracked_paths(repo_root),
            historical_path_resolver=lambda audited_commit_sha: (
                git_tracked_paths_at_commit(repo_root, audited_commit_sha)
            ),
        )
    except CoverageValidationError as exc:
        print(f"Bug-sweep coverage invalid:\n{exc}", file=sys.stderr)
        return 1

    if args.json:
        compact_report = {key: value for key, value in report.items() if key != "rows"}
        print(json.dumps(compact_report, indent=2, sort_keys=True))
    else:
        _print_human_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

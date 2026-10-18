"""Safety boundaries for Tier-0 selection; all inputs are synthetic."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

import pytest

from scripts import ci_change_classifier as classifier


def raw_change(path, status="M", old="100644", new="100644"):
    return f":{old} {new} abc1234 def5678 {status}\0{path}\0".encode()


@pytest.mark.parametrize(("paths", "expected"), [
    (["docs/project/architecture.md", "AGENTS.md"], True),  # docs-only
    (["src/metroliza/app/main.py"], False),  # code
    (["docs/ci-policy.md", "src/metroliza/app/main.py"], False),  # mixed
    ([".github/workflows/ci.yml"], False),  # workflow
    (["scripts/ci_change_classifier.py"], False),
    (["README.md"], False), (["CHANGELOG.md"], False),
    (["THIRD_PARTY_NOTICES.md"], False),
    (["tests/fixtures/edge_fixture_manifest.md"], False),
    (["src/metroliza/templates/prompt.md"], False),
    (["templates/prompt.md"], False),
    (["docs/project/templates/input.md"], False),
    (["docs/project/Templates/input.md"], False),
    (["docs/project/feature_catalog.md"], False),  # read by tests/test_feature_catalog.py
    (["docs/quality/bug_sweep/README.md"], False),  # required by the bug-sweep validator
    (["docs/generated/report.md"], False),
    (["docs/project/generated/report.md"], False),
    (["docs/assets/diagram.svg"], False),
    (["docs/project/diagram.png"], False),
    (["docs/quality/bug_sweep/coverage.json"], False),
    (["docs/user_manual/main_window.md"], False),
    (["requirements-dev.txt"], False), (["pyproject.toml"], False),
    (["docs/new-subsystem/input.md"], False),
    (["unknown.md"], False),
    ([".github/pull_request_template.md", "CONTRIBUTING.md"], True),
    (["docs/engineering/codex-task-packet-template.md"], True),
    (["docs/project/name with\tspaces\nand unicode-ą.md"], True),
    (["docs/project/../input.md"], False),
    (["docs//project/architecture.md"], False),
    (["/docs/project/architecture.md"], False),
    (["docs/project\\input.md"], False),
    ([], False),
])
def test_change_classes(paths, expected):
    assert classifier.docs_only_from_raw(b"".join(map(raw_change, paths))) is expected


@pytest.mark.parametrize(("old_path", "new_path", "expected"), [
    ("docs/project/old.md", "docs/project/new.md", True),
    ("tests/fixtures/input.md", "docs/project/new.md", False),
    ("docs/project/old.md", "src/template.md", False),
    ("README.md", "docs/project/new.md", False),
])
def test_rename_checks_both_paths_without_similarity_detection(old_path, new_path, expected):
    raw = raw_change(old_path, "D", new="000000") + raw_change(new_path, "A", old="000000")
    assert classifier.docs_only_from_raw(raw) is expected


@pytest.mark.parametrize(("path", "expected"), [
    ("docs/project/deleted.md", True), ("tests/fixtures/deleted.md", False),
    ("src/deleted.py", False), ("CHANGELOG.md", False),
])
def test_deletions_use_the_old_path_and_mode(path, expected):
    assert classifier.docs_only_from_raw(raw_change(path, "D", new="000000")) is expected


@pytest.mark.parametrize(("status", "old", "new"), [
    ("M", "100644", "100755"), ("D", "100755", "000000"),
    ("A", "000000", "120000"), ("T", "100644", "120000"),
    ("M", "160000", "160000"), ("U", "000000", "000000"),
])
def test_executable_symlink_submodule_and_unmerged_docs_run_full(status, old, new):
    assert not classifier.docs_only_from_raw(raw_change("docs/project/input.md", status, old, new))


@pytest.mark.parametrize("raw", [b"", b"bad\0docs/a.md\0", b"M\tdocs/a.md\n",
                                 raw_change("docs/a.md")[:-1], b"\0", b"\0\0"])
def test_malformed_diff_never_grants_docs_only(raw):
    assert not classifier.docs_only_from_raw(raw)


def event(name, base="a" * 40, head="b" * 40):
    if name == "pull_request":
        return {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
    return {"before": base, "after": head}


def test_pull_request_uses_the_complete_merge_base_range_and_local_git_flags(monkeypatch):
    calls = []

    def git(*args):
        calls.append(args)
        return b"c" * 40 + b"\n" if args[0] == "merge-base" else raw_change("docs/ci-policy.md")

    monkeypatch.setattr(classifier, "git_output", git)
    assert classifier.classify_event("pull_request", event("pull_request"))
    assert calls == [("merge-base", "a" * 40, "b" * 40),
                     ("diff", "--raw", "-z", "--no-renames", "--no-ext-diff",
                      "--no-textconv", "c" * 40, "b" * 40, "--")]


@pytest.mark.parametrize(("name", "payload"), [
    ("workflow_dispatch", {}), ("merge_group", {}), ("push", {}),
    # A docs-only push still runs the full lane: same-SHA push and PR runs must not
    # disagree, and integration pushes back up the PR classification.
    ("push", event("push")),
    ("pull_request", {"pull_request": None}), ("push", None),
    ("push", event("push", base="0" * 40)),  # new branch
    ("push", event("push", head="0" * 40)),  # deleted branch
    ("push", event("push", base="--bad-option")),
    ("pull_request", event("pull_request", head=None)),
])
def test_dispatch_new_branch_and_invalid_events_run_full_without_git(monkeypatch, name, payload):
    monkeypatch.setattr(classifier, "git_output", lambda *_: pytest.fail("unexpected Git command"))
    assert not classifier.classify_event(name, payload)


@pytest.mark.parametrize("error", [subprocess.CalledProcessError(128, "git"),
                                 subprocess.TimeoutExpired("git", 60), OSError("unavailable")])
def test_missing_history_or_git_failure_runs_full(monkeypatch, error):
    def fail(*_args):
        raise error

    monkeypatch.setattr(classifier, "git_output", fail)
    assert not classifier.classify_event("pull_request", event("pull_request"))


def test_large_diff_is_not_truncated_to_a_docs_only_page(monkeypatch):
    raw = raw_change("docs/ci-policy.md") * 500 + raw_change("src/last.py")
    monkeypatch.setattr(classifier, "git_output", lambda *_: raw)
    assert not classifier.classify_event("pull_request", event("pull_request"))


@pytest.mark.parametrize(("payload", "expected"), [("{}", "false"), ("not-json", "false"),
                                                  (json.dumps(event("pull_request")), "true")])
def test_cli_writes_only_boolean_output(tmp_path, monkeypatch, capsys, payload, expected):
    event_path, output = tmp_path / "event.json", tmp_path / "output"
    event_path.write_text(payload)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(classifier, "git_output",
                        lambda *args: b"c" * 40 + b"\n" if args[0] == "merge-base"
                        else raw_change("docs/ci-policy.md"))
    classifier.main()
    assert output.read_text() == f"docs_only={expected}\n"
    assert f"docs_only={expected}" in capsys.readouterr().out


# Tests that the docs-only lane itself runs may read prose; everything else must not.
TIER0_TESTS = {
    "tests/test_docs_markdown_links.py", "tests/test_docs_policy_repo_metrics_hygiene.py",
    "tests/test_ci_policy_sync.py", "tests/test_ci_change_classifier.py",
    "tests/test_release_metadata_sync.py", "tests/test_release_hygiene.py",
}
MARKDOWN_REFERENCE = re.compile(
    r"docs/[\w./ -]*?\.md|AGENTS\.md|CONTRIBUTING\.md|\.github/pull_request_template\.md")
SCANNED_SUFFIXES = {".py", ".rs", ".ps1", ".sh", ".toml", ".yml", ".yaml", ".json", ".txt", ".cfg"}


def test_markdown_read_by_code_is_never_docs_only():
    root = Path(__file__).resolve().parents[1]
    consumed = {}
    for top in ("tests", "scripts", "src", "packaging"):
        for path in (root / top).rglob("*"):
            relative = path.relative_to(root).as_posix()
            if (path.suffix not in SCANNED_SUFFIXES or not path.is_file()
                    or relative in TIER0_TESTS or relative == "scripts/ci_change_classifier.py"):
                continue
            for reference in MARKDOWN_REFERENCE.findall(path.read_text(encoding="utf-8", errors="ignore")):
                if (root / reference).is_file() and classifier.is_prose(reference):
                    consumed.setdefault(reference, []).append(relative)
    assert consumed == {}, "add these to EXECUTABLE_INPUT_DOCS (or move the reader into Tier 0)"


def test_ci_tier0_test_list_matches_the_workflow():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text()
    step = workflow.split("Focused documentation and policy checks", 1)[1].split("- name:", 1)[0]
    assert set(re.findall(r"tests/test_\w+\.py", step)) == TIER0_TESTS

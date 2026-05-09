#!/usr/bin/env python3
"""Guard against generated release artifacts and local data entering Git."""

from __future__ import annotations

import subprocess
from pathlib import Path


BLOCKED_PREFIXES = (
    "benchmark_results/",
    "artifacts/parser_plugin_workspace_ci/",
    "logs/release_checks/",
    "smoke-artifacts/",
)
BLOCKED_FILENAMES = {
    "nuitka-build-report.xml",
}
BLOCKED_SUFFIXES = (
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".pdf",
    ".csv",
    ".xls",
    ".xlsx",
    ".xlsm",
)
ALLOWED_TRACKED_PATHS = {
    "config/google/credentials.example.json",
    "docs/user_manual/group_analysis/user_manual.pdf",
    "tests/fixtures/pdf/cmm_smoke_fixture.pdf",
}


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_blocked(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    if normalized in ALLOWED_TRACKED_PATHS:
        return None
    if Path(normalized).name in BLOCKED_FILENAMES:
        return "generated release report"
    if any(normalized.startswith(prefix) for prefix in BLOCKED_PREFIXES):
        return "generated release or benchmark artifact path"
    if normalized.lower().endswith(BLOCKED_SUFFIXES):
        return "local data or generated evidence file type"
    return None


def _collect_violations(paths: list[str], *, label: str) -> list[str]:
    violations: list[str] = []
    for path in paths:
        if not Path(path).exists():
            continue
        reason = _is_blocked(path)
        if reason:
            violations.append(f"{label}: {path} ({reason})")
    return violations


def main() -> int:
    tracked = _git_lines("ls-files")
    untracked = _git_lines("ls-files", "--others", "--exclude-standard")
    violations = [
        *_collect_violations(tracked, label="tracked"),
        *_collect_violations(untracked, label="untracked-not-ignored"),
    ]
    if violations:
        print("Release hygiene check failed:")
        for violation in violations:
            print(f" - {violation}")
        return 1
    print("Release hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

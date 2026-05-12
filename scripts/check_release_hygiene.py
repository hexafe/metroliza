#!/usr/bin/env python3
"""Guard against generated release artifacts and local data entering Git."""

from __future__ import annotations

import subprocess
from pathlib import Path


BLOCKED_PREFIXES = (
    "benchmark_results/",
    "artifacts/parser_plugin_workspace_ci/",
    "artifacts/industrial/",
    "logs/release_checks/",
    "industrial_artifacts/",
    "industrial_exports/",
    "smoke-artifacts/",
    "htmlcov/",
)
BLOCKED_PREFIXES_LOWER = tuple(prefix.lower() for prefix in BLOCKED_PREFIXES)
BLOCKED_FILENAMES = {
    ".env",
    "connection_dump.json",
    "databases.yaml",
    "databases.yml",
    "industrial_sources.yaml",
    "industrial_sources.yml",
    "industrial_connection_dump.json",
    ".coverage",
    "coverage.xml",
    "nuitka-build-report.xml",
    "odbc.ini",
    "token.json",
}
BLOCKED_FILENAMES_LOWER = {filename.lower() for filename in BLOCKED_FILENAMES}
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
ALLOWED_TRACKED_PATHS_LOWER = {path.lower() for path in ALLOWED_TRACKED_PATHS}


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
    normalized_lower = normalized.lower()
    if normalized_lower in ALLOWED_TRACKED_PATHS_LOWER:
        return None
    if Path(normalized_lower).name in BLOCKED_FILENAMES_LOWER:
        return "generated release report"
    if any(normalized_lower.startswith(prefix) for prefix in BLOCKED_PREFIXES_LOWER):
        return "generated release or benchmark artifact path"
    if normalized_lower.endswith(BLOCKED_SUFFIXES):
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

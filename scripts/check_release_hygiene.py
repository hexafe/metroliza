#!/usr/bin/env python3
"""Guard against generated release artifacts and local data entering Git."""

from __future__ import annotations

import hashlib
import stat
import subprocess
from pathlib import Path


BLOCKED_PREFIXES = (
    "benchmark_results/",
    "artifacts/parser_plugin_workspace_ci/",
    "artifacts/parser_profile_self_service_ci/",
    "artifacts/parser_profile_self_service_home/",
    "artifacts/security_siblings/",
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
    "tests/fixtures/industrial_realtime/gradual_drift.csv",
    "tests/fixtures/industrial_realtime/gradual_drift_upward.csv",
    "tests/fixtures/industrial_realtime/low_sample_count.csv",
    "tests/fixtures/industrial_realtime/missing_stale_data.csv",
    "tests/fixtures/industrial_realtime/normal_stable_process.csv",
    "tests/fixtures/industrial_realtime/single_high_outlier.csv",
    "tests/fixtures/industrial_realtime/single_low_outlier.csv",
    "tests/fixtures/industrial_realtime/single_point_outlier.csv",
    "tests/fixtures/industrial_realtime/spec_limit_breach.csv",
    "tests/fixtures/industrial_realtime/stable_normal_process.csv",
    "tests/fixtures/industrial_realtime/station_segment_baselines.csv",
    "tests/fixtures/industrial_realtime/stuck_sensor.csv",
    "tests/fixtures/industrial_realtime/stuck_value.csv",
    "tests/fixtures/industrial_realtime/sudden_step_change.csv",
    "tests/fixtures/industrial_realtime/usl_lsl_breach.csv",
    "tests/fixtures/industrial_realtime/warning_limit_breach.csv",
}
ALLOWED_TRACKED_PATHS_LOWER = {path.lower() for path in ALLOWED_TRACKED_PATHS}

# Public synthetic #1047 inputs are admitted only with their reviewed bytes.
# A neighboring file or changed fixture remains blocked by the normal data guard.
PINNED_SYNTHETIC_FIXTURES = {
    "tests/fixtures/windows_candidate_ocr/image-header-only.pdf": "33065d26c788d9394c3e33876f885902ab95d21f5457f4f21fee3f333bf9609a",
    "tests/fixtures/windows_candidate/finite-source.csv": "de2724bd3b6b55d362016423a2f78168235d3833d7a89298a7fdf4a5ec747938",
    "tests/fixtures/windows_candidate/integer-precision.csv": "8e2c837472d6465d319b37b4afe09998f9c45680edc27d1a169f33e145a70508",
    "tests/fixtures/windows_candidate/reports/report-0.pdf": "183b46650a7e37113927f7a99eb6a66484d07126d3134b3a6056defaef21af3f",
    "tests/fixtures/windows_candidate/reports/report-1.pdf": "315032987a656191260945242c89996976640f3629c4499c428f44ac9b3679ad",
    "tests/fixtures/windows_candidate/reports/report-2.pdf": "7a6fe37457385188f9b466a8f9c3061bf7d118290b0c8e74583dba5e76f29048",
    "tests/fixtures/windows_candidate/reports/report-3.pdf": "cb801c452d9608c227606a4c10325d19d7d8a095fe80976fa60338fd6bfd0849",
    "tests/fixtures/windows_candidate/reports/report-4.pdf": "b9f83ee23a191eccfa3515594e6ba85ede670a2163444cd0daf7b9bb5edd83d9",
    "tests/fixtures/windows_candidate_protocol/literal-measurement-labels.xlsx": "ec39dfd2b969b283d7f6086aad612661d8bdc9e1bdeb328f8dd3e2d0d8ba6ca4",
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


def _matches_pinned_fixture(path: Path, expected: str) -> bool:
    try:
        if any(not stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents):
            return False
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return False
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == expected
    except OSError:
        return False


def _collect_violations(paths: list[str], *, label: str) -> list[str]:
    violations: list[str] = []
    for path in paths:
        expected = PINNED_SYNTHETIC_FIXTURES.get(path.replace("\\", "/"))
        if expected is not None:
            if not _matches_pinned_fixture(Path(path), expected):
                violations.append(f"{label}: {path} (synthetic fixture bytes differ from reviewed hash)")
            continue
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

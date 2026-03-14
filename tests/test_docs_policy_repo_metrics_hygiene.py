from __future__ import annotations

import re
from pathlib import Path


DOC_PATHS = [
    Path('docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md'),
    Path('docs/roadmaps/test_ci_audit_execution.md'),
    Path('docs/release_checks/release_candidate_checklist.md'),
    Path('docs/release_checks/release_status.md'),
    Path('docs/release_checks/open_testing_runbook.md'),
]

# Guardrail: operational docs should avoid hardcoded repository-scale metrics
# (for example, "46 test modules") because those values quickly drift.
STALE_REPO_METRIC_PATTERNS = [
    re.compile(r'\b\d+\s+test modules?\b', re.IGNORECASE),
    re.compile(r'\b\d+\s+test files?\b', re.IGNORECASE),
    re.compile(r'\b\d+\s+(?:parser\s+)?fixtures?\b', re.IGNORECASE),
]


def test_operational_docs_avoid_brittle_hardcoded_repo_metrics() -> None:
    matches: list[str] = []

    for path in DOC_PATHS:
        text = path.read_text(encoding='utf-8')
        for pattern in STALE_REPO_METRIC_PATTERNS:
            for hit in pattern.finditer(text):
                snippet = text[max(0, hit.start() - 40) : min(len(text), hit.end() + 40)]
                matches.append(f'{path}: `{hit.group(0)}` in "...{snippet}..."')

    assert not matches, (
        'Found hardcoded repository-scale metrics likely to drift over time. '
        'Prefer non-numeric wording or computed/synced values.\n- '
        + '\n- '.join(matches)
    )

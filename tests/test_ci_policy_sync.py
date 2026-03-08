from __future__ import annotations

from pathlib import Path


CI_WORKFLOW_PATH = Path('.github/workflows/ci.yml')
CI_POLICY_PATH = Path('docs/ci-policy.md')
RC_CHECKLIST_PATH = Path('docs/release_checks/release_candidate_checklist.md')


def test_ci_workflow_keeps_coverage_visibility_contract() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')

    assert '--cov=.' in workflow
    assert '--cov-report=term' in workflow
    assert '--cov-report=xml:coverage.xml' in workflow
    assert 'name: unit-test-coverage' in workflow
    assert 'coverage.xml' in workflow


def test_docs_remain_aligned_with_coverage_visibility_contract() -> None:
    ci_policy = CI_POLICY_PATH.read_text(encoding='utf-8')
    checklist = RC_CHECKLIST_PATH.read_text(encoding='utf-8')

    assert 'Coverage reporting is **visibility-only**' in ci_policy
    assert 'There is intentionally no fail-under threshold configured yet.' in ci_policy
    assert 'unit-test-coverage' in ci_policy
    assert 'coverage.xml' in ci_policy

    assert 'Coverage visibility output from `unit-tests` is reviewed' in checklist
    assert '`unit-test-coverage` artifact `coverage.xml`' in checklist

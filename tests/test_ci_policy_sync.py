from __future__ import annotations

from pathlib import Path


CI_WORKFLOW_PATH = Path('.github/workflows/ci.yml')
CI_POLICY_PATH = Path('docs/ci-policy.md')
RC_CHECKLIST_PATH = Path('docs/release_checks/release_candidate_checklist.md')
RELEASE_STATUS_PATH = Path('docs/release_checks/release_status.md')
OPEN_TESTING_RUNBOOK_PATH = Path('docs/release_checks/open_testing_runbook.md')


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


def test_ci_workflow_keeps_manual_smoke_gates_non_blocking() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')

    assert "name: Packaging smoke (manual/opt-in)" in workflow
    assert "if: github.event_name == 'workflow_dispatch' && inputs.run_packaging_smoke == '1'" in workflow
    assert "name: Google conversion smoke (manual/opt-in)" in workflow
    assert (
        "if: github.event_name == 'workflow_dispatch' && inputs.run_google_conversion_smoke == '1'"
        in workflow
    )
    assert 'METROLIZA_STARTUP_SMOKE: \"1\"' in workflow or "METROLIZA_STARTUP_SMOKE: '1'" in workflow
    assert 'timeout 60s ./dist/metroliza' in workflow
    assert 'name: packaging-smoke-artifacts' in workflow


def test_ci_workflow_keeps_manual_smoke_inputs_opt_in_by_default() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')

    assert 'run_packaging_smoke:' in workflow
    assert 'description: "Set to 1 to run manual packaging smoke build"' in workflow
    assert 'run_google_conversion_smoke:' in workflow
    assert 'description: "Set to 1 to run release-only Google conversion smoke check"' in workflow
    assert workflow.count('default: "0"') >= 2


def test_ci_policy_keeps_manual_smoke_lane_semantics_explicit() -> None:
    ci_policy = CI_POLICY_PATH.read_text(encoding='utf-8')

    assert 'Optional/manual checks (non-blocking)' in ci_policy
    assert '| Packaging smoke build + startup launch check (release-only) | `packaging-smoke` |' in ci_policy
    assert '| Google conversion smoke (release-only) | `google-conversion-smoke` |' in ci_policy
    assert '**Non-blocking** for regular PRs and pushes' in ci_policy
    assert 'Packaging smoke startup semantics' in ci_policy


def test_release_status_and_runbook_keep_gate_semantics_aligned() -> None:
    release_status = RELEASE_STATUS_PATH.read_text(encoding='utf-8')
    open_testing_runbook = OPEN_TESTING_RUNBOOK_PATH.read_text(encoding='utf-8')

    assert '**PR-blocking CI gates** are defined in [`../ci-policy.md`](../ci-policy.md)' in release_status
    assert (
        '**Release-blocking manual evidence gates** are defined in '
        '[`release_candidate_checklist.md`](./release_candidate_checklist.md)'
    ) in release_status
    assert (
        'Optional/manual workflow-dispatch lanes (`packaging-smoke`, `google-conversion-smoke`) are non-blocking '
        'for normal PR CI'
    ) in release_status

    assert (
        'optional manual smoke evidence collection (`packaging-smoke`, `google-conversion-smoke`)'
        in open_testing_runbook
    )

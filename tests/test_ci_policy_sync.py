from __future__ import annotations

from pathlib import Path

CI_WORKFLOW_PATH = Path('.github/workflows/ci.yml')
CI_POLICY_PATH = Path('docs/ci-policy.md')
NATIVE_BUILD_DISTRIBUTION_PATH = Path('docs/native_build_distribution.md')
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

    assert 'Coverage threshold staged policy' in ci_policy
    assert 'Soft threshold warning stage (current enforcement mode)' in ci_policy
    assert 'Blocking threshold stage (future)' in ci_policy
    assert 'unit-test-coverage' in ci_policy
    assert 'coverage.xml' in ci_policy

    assert 'Coverage visibility output from `unit-tests` is reviewed' in checklist
    assert '`unit-test-coverage` artifact `coverage.xml`' in checklist




def test_ci_workflow_emits_non_blocking_coverage_threshold_status() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')

    assert 'COVERAGE_WARNING_THRESHOLD' in workflow
    assert 'Report coverage threshold status (non-blocking)' in workflow
    assert 'Coverage threshold status (non-blocking)' in workflow
    assert '::warning title=Coverage below warning threshold::' in workflow
    assert 'This does not fail CI in the current staged policy.' in workflow


def test_ci_policy_keeps_coverage_threshold_governance_self_contained() -> None:
    ci_policy = CI_POLICY_PATH.read_text(encoding='utf-8')

    assert 'Coverage threshold staged policy' in ci_policy
    assert 'Coverage threshold governance remains staged' in ci_policy
    assert 'release owner records a dated go/no-go decision' in ci_policy
    assert 'docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md' not in ci_policy

def test_ci_workflow_keeps_manual_smoke_gates_non_blocking() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')

    assert "name: Packaging smoke (manual/opt-in)" in workflow
    assert "if: github.event_name == 'workflow_dispatch' && inputs.run_packaging_smoke == '1'" in workflow
    assert "name: Google conversion smoke (manual/opt-in)" in workflow
    assert (
        "if: github.event_name == 'workflow_dispatch' && inputs.run_google_conversion_smoke == '1'"
        in workflow
    )
    assert 'METROLIZA_PDF_PARSER_SMOKE_FIXTURE: tests/fixtures/pdf/cmm_smoke_fixture.pdf' in workflow
    assert 'METROLIZA_PDF_PARSER_SMOKE_EXPECTED_TEXT: METROLIZA PDF PARSER SMOKE' in workflow
    assert 'timeout 60s ./dist/metroliza' in workflow
    assert 'name: packaging-smoke-artifacts' in workflow


def test_ci_workflow_keeps_native_chart_planner_parity_smoke_step() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    ci_policy = CI_POLICY_PATH.read_text(encoding='utf-8')
    native_build_distribution = NATIVE_BUILD_DISTRIBUTION_PATH.read_text(encoding='utf-8')

    assert 'name: Native chart planner parity smoke' in workflow
    assert 'name: Export runtime native fast-path contract smoke' in workflow
    assert 'planner_built_resolved_specs_match_checked_in_parity_references' in workflow
    assert 'tests/test_native_chart_parity_fixtures.py' in workflow
    assert 'tests/test_export_data_thread_group_analysis.py -k runtime_native_fast_path_contract_is_behavioral' in workflow
    assert 'native chart planner/parity smoke checks' in ci_policy
    assert 'export-runtime fast-path contract smoke for extended summary charts' in ci_policy
    assert 'native chart planner parity smoke passes against the checked-in chart fixtures' in native_build_distribution
    assert 'export runtime fast-path contract is smoke-validated for the extended summary-sheet chart path' in native_build_distribution
    assert 'distribution scatter, distribution violin, IQR, and trend dispatch' in native_build_distribution


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
    assert '| Packaging smoke build + packaged PDF parser check (release-only) | `packaging-smoke` |' in ci_policy
    assert '| Google conversion smoke (release-only) | `google-conversion-smoke` |' in ci_policy
    assert '**Non-blocking** for regular PRs and pushes' in ci_policy
    assert 'Packaging smoke parser semantics' in ci_policy


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


def test_release_status_keeps_current_release_line_metadata() -> None:
    release_status = RELEASE_STATUS_PATH.read_text(encoding='utf-8')

    assert 'Release line metadata is canonical in `VersionDate.py`' in release_status
    assert '`RELEASE_VERSION`' in release_status
    assert '`VERSION_DATE`' in release_status
    assert '`CURRENT_RELEASE_HIGHLIGHT`' in release_status

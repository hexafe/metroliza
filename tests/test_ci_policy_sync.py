from __future__ import annotations

from pathlib import Path
import re

CI_WORKFLOW_PATH = Path('.github/workflows/ci.yml')
CI_POLICY_PATH = Path('docs/ci-policy.md')
NATIVE_BUILD_DISTRIBUTION_PATH = Path('docs/native_build_distribution.md')
RC_CHECKLIST_PATH = Path('docs/release_checks/release_candidate_checklist.md')
RELEASE_STATUS_PATH = Path('docs/release_checks/release_status.md')
OPEN_TESTING_RUNBOOK_PATH = Path('docs/release_checks/open_testing_runbook.md')
BRANCHING_STRATEGY_PATH = Path('docs/release_checks/branching_strategy.md')
RELEASE_BRANCHING_PLAYBOOK_PATH = Path('docs/release_checks/release_branching_playbook.md')
BEGINNER_RELEASE_PLAYBOOK_PATH = Path('docs/release_checks/release_playbook_beginner.md')
GOOGLE_SMOKE_LOG_PATH = Path('docs/release_checks/google_conversion_smoke.md')
GOOGLE_SMOKE_RUNBOOK_PATH = Path('docs/google_conversion_smoke_runbook.md')


def test_ci_workflow_keeps_coverage_visibility_contract() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')

    assert '--cov=src/metroliza' in workflow
    assert '--cov=modules' in workflow
    assert '--cov=scripts' in workflow
    assert 'COVERAGE_MINIMUM_THRESHOLD: \'80\'' in workflow
    assert '--cov-append' in workflow
    assert 'python -m coverage report --fail-under="${COVERAGE_MINIMUM_THRESHOLD:-80}"' in workflow
    assert 'python -m coverage xml -o coverage.xml' in workflow
    assert 'QT_QPA_PLATFORM: offscreen' in workflow
    assert 'Install Qt runtime system libraries' in workflow
    assert 'libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0' in workflow
    assert 'name: unit-test-coverage' in workflow
    assert 'coverage.xml' in workflow


def test_docs_remain_aligned_with_coverage_visibility_contract() -> None:
    ci_policy = CI_POLICY_PATH.read_text(encoding='utf-8')
    checklist = RC_CHECKLIST_PATH.read_text(encoding='utf-8')

    assert 'Coverage Threshold Policy' in ci_policy
    assert 'Blocking threshold stage' in ci_policy
    assert 'unit-test-coverage' in ci_policy
    assert 'coverage.xml' in ci_policy

    assert 'Coverage threshold from `unit-tests` passes' in checklist
    assert '`unit-test-coverage` artifact `coverage.xml`' in checklist


def test_ci_workflow_enforces_coverage_threshold_status() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')

    assert 'COVERAGE_MINIMUM_THRESHOLD' in workflow
    assert 'Report coverage threshold status' in workflow
    assert 'Coverage threshold status' in workflow
    assert 'Canonical source line coverage' in workflow
    assert 'src/metroliza/' in workflow
    assert "pathlib.Path('src/metroliza') / filename" in workflow
    assert '::error title=Canonical coverage below threshold::' in workflow
    assert '::error title=Coverage below threshold::' in workflow
    assert 'sys.exit(1)' in workflow


def test_ci_policy_keeps_coverage_threshold_governance_self_contained() -> None:
    ci_policy = CI_POLICY_PATH.read_text(encoding='utf-8')

    assert 'Coverage Threshold Policy' in ci_policy
    assert 'Coverage threshold changes require an explicit threshold update' in ci_policy
    assert 'coverage threshold is blocking' in ci_policy
    assert 'canonical `src/metroliza` line coverage' in ci_policy
    assert 'Qt runtime system libraries' in ci_policy


def test_active_docs_use_canonical_test_pythonpath() -> None:
    active_docs = [
        Path('CONTRIBUTING.md'),
        RC_CHECKLIST_PATH,
    ]

    for doc_path in active_docs:
        text = doc_path.read_text(encoding='utf-8')
        assert 'PYTHONPATH=. python -m pytest tests -q' not in text
        assert 'PYTHONPATH=src:. python -m pytest tests -q' in text


def test_ci_workflow_keeps_packaging_manual_and_google_local_only() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')

    assert "name: Packaging smoke (manual/opt-in)" in workflow
    assert "if: github.event_name == 'workflow_dispatch' && inputs.run_packaging_smoke == '1'" in workflow
    assert "name: Google conversion smoke (manual/opt-in)" not in workflow
    assert 'run_google_conversion_smoke' not in workflow
    assert 'name: Windows core smoke' in workflow
    assert 'METROLIZA_PDF_PARSER_SMOKE_FIXTURE: tests/fixtures/pdf/cmm_smoke_fixture.pdf' in workflow
    assert 'METROLIZA_PDF_PARSER_SMOKE_EXPECTED_TEXT: METROLIZA PDF PARSER SMOKE' in workflow
    assert 'requirements-ocr.txt' in workflow
    assert 'python scripts/validate_packaged_pdf_parser.py --require-header-ocr' in workflow
    assert "find dist -maxdepth 1 -type f -name 'metroliza_P_*'" in workflow
    assert 'timeout 60s "${{ steps.packaged-artifact.outputs.path }}"' in workflow
    assert 'name: packaging-smoke-artifacts' in workflow
    assert 'name: packaging-smoke-release-artifact' in workflow
    assert 'python scripts/stage_release_notices.py' in workflow
    assert 'third_party_inventory_260711.json' in workflow
    assert 'NOTICE_MANIFEST.json' in workflow


def test_ci_and_precommit_run_release_hygiene_scan() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    precommit_config = Path('.pre-commit-config.yaml').read_text(encoding='utf-8')
    gitignore = Path('.gitignore').read_text(encoding='utf-8')

    assert 'name: Release hygiene scan' in workflow
    assert 'python scripts/check_release_hygiene.py' in workflow
    assert 'id: release-hygiene' in precommit_config
    assert 'logs/release_checks/' in gitignore
    release_hygiene = Path('scripts/check_release_hygiene.py').read_text(encoding='utf-8')
    assert 'artifacts/parser_plugin_workspace_ci/' in gitignore
    assert 'artifacts/parser_profile_self_service_ci/' in gitignore
    assert 'artifacts/parser_profile_self_service_home/' in gitignore
    assert '"artifacts/parser_profile_self_service_ci/"' in release_hygiene
    assert '"artifacts/parser_profile_self_service_home/"' in release_hygiene
    assert 'smoke-artifacts/' in gitignore
    assert 'nuitka-build-report.xml' in gitignore
    assert 'src/metroliza/native/**/target/' in gitignore
    assert 'src/metroliza/native/**/Cargo.lock' not in gitignore
    assert '.coverage' in gitignore
    assert 'coverage.xml' in gitignore
    assert 'htmlcov/' in gitignore


def test_precommit_security_tools_match_ci_and_development_policy() -> None:
    precommit_config = Path('.pre-commit-config.yaml').read_text(encoding='utf-8')
    requirements_dev = Path('requirements-dev.txt').read_text(encoding='utf-8')
    ruff_pin = next(
        line.split('==', 1)[1].strip()
        for line in requirements_dev.splitlines()
        if line.startswith('ruff==')
    )

    assert f'rev: v{ruff_pin}' in precommit_config
    assert 'id: security-secret-scan' in precommit_config
    assert 'entry: python scripts/security_audit.py --secret-scan-only' in precommit_config
    assert 'pass_filenames: false' in precommit_config
    assert 'id: detect-basic-credential-patterns' not in precommit_config


def test_ci_workflow_runs_declarative_parser_profile_self_service_smoke() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    ci_policy = CI_POLICY_PATH.read_text(encoding='utf-8')

    assert 'name: Parser profile self-service smoke' in workflow
    assert 'scripts/parser_plugin_self_service.py init' in workflow
    assert 'scripts/parser_plugin_self_service.py validate' in workflow
    assert 'scripts/parser_plugin_self_service.py diagnose' in workflow
    assert 'scripts/parser_plugin_self_service.py --home "${home_dir}" install' in workflow
    assert 'scripts/parser_plugin_self_service.py --home "${home_dir}" evidence ci_smoke' in workflow
    assert '--source-format csv' in workflow
    assert 'sample_report_01.csv' in workflow
    assert 'artifacts/parser_profile_self_service_ci' in workflow
    assert 'artifacts/parser_profile_self_service_home' in workflow
    assert 'Parser profile self-service smoke' in ci_policy
    assert 'synthetic CSV sample' in ci_policy
    assert 'data-only' in ci_policy


def test_ci_workflow_keeps_static_typing_narrow_and_blocking() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    requirements_dev = Path('requirements-dev.txt').read_text(encoding='utf-8')

    assert 'mypy==2.2.0' in requirements_dev
    assert 'name: Narrow static type boundary' in workflow
    assert 'src/metroliza/integrations/google_credentials_hygiene.py' in workflow
    assert 'src/metroliza/industrial/anomaly/contracts.py' in workflow
    assert 'src/metroliza/industrial/realtime/stream_contracts.py' in workflow


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
    assert 'run_google_conversion_smoke:' not in workflow
    assert 'run_windows_startup_benchmark:' in workflow
    assert workflow.count('default: "0"') >= 2


def test_ci_workflow_pins_actions_and_uses_least_privilege_defaults() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    action_refs = re.findall(r'^\s*uses:\s+([^\s#]+)', workflow, flags=re.MULTILINE)

    assert action_refs
    assert all(re.fullmatch(r'[^@]+@[0-9a-f]{40}', ref) for ref in action_refs)
    assert 'permissions:\n  contents: read' in workflow
    assert 'concurrency:' in workflow
    assert 'cancel-in-progress: true' in workflow
    assert workflow.count('uses: actions/checkout@') == workflow.count(
        'persist-credentials: false'
    )
    assert workflow.count('runs-on:') == workflow.count('timeout-minutes:')
    assert 'toolchain: 1.95.0' in workflow
    maturin_builds = [line for line in workflow.splitlines() if 'maturin build' in line]
    assert maturin_builds
    assert all('--locked' in line for line in maturin_builds)


def test_ci_workflow_runs_blocking_windows_core_smoke() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    ci_policy = CI_POLICY_PATH.read_text(encoding='utf-8')

    assert 'windows-core-smoke:' in workflow
    assert 'name: Windows core smoke' in workflow
    assert 'runs-on: windows-latest' in workflow
    assert 'tests/test_db_utils.py' in workflow
    assert 'tests/test_packaging_spec_hiddenimports.py' in workflow
    assert '| Windows core smoke | `windows-core-smoke` |' in ci_policy


def test_perf_benchmark_trend_filters_to_baseline_backed_scenarios() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    ci_policy = CI_POLICY_PATH.read_text(encoding='utf-8')

    assert 'name: Performance benchmark trend check (non-blocking)' in workflow
    assert 'name: Trend comparison against checked-in baseline\n        continue-on-error: true' in workflow
    assert '--require-baselines' in workflow
    assert '--require-observed' in workflow
    assert '--export-stage-metrics' in workflow
    assert (
        '--scenarios pdf_parse_path cmm_parser_backend_compare excel_export_path '
        'excel_export_high_header_cardinality_compare csv_summary_export_path '
        'distribution_fit_monte_carlo_path distribution_fit_batch_compare '
        'group_preprocess_mixed_types_compare comparison_stats_ci_flow '
        'comparison_stats_pairwise_flow'
    ) in workflow
    assert 'trend comparison is scoped to scenario keys that have checked-in baseline' in ci_policy
    assert 'scenarios without baselines' in ci_policy
    assert 'not treated as trend rows' in ci_policy
    assert 'Export stage metrics remain advisory' in ci_policy


def test_ci_policy_keeps_manual_smoke_lane_semantics_explicit() -> None:
    ci_policy = CI_POLICY_PATH.read_text(encoding='utf-8')

    assert 'Optional/manual checks (non-blocking)' in ci_policy
    assert '| Packaging smoke build + packaged PDF parser check (release-only) | `packaging-smoke` |' in ci_policy
    assert '| Google conversion smoke (release-only) | Local secure workstation command' in ci_policy
    assert 'Not a hosted CI job; **release-blocking** evidence' in ci_policy
    assert '**Non-blocking** for regular PRs and pushes' in ci_policy
    assert 'Packaging smoke parser semantics' in ci_policy


def test_release_status_and_runbook_keep_gate_semantics_aligned() -> None:
    release_status = RELEASE_STATUS_PATH.read_text(encoding='utf-8')
    open_testing_runbook = OPEN_TESTING_RUNBOOK_PATH.read_text(encoding='utf-8')
    release_checklist = RC_CHECKLIST_PATH.read_text(encoding='utf-8')
    google_runbook = GOOGLE_SMOKE_RUNBOOK_PATH.read_text(encoding='utf-8')
    google_log = GOOGLE_SMOKE_LOG_PATH.read_text(encoding='utf-8')

    assert '**PR-blocking CI gates** are defined in [`../ci-policy.md`](../ci-policy.md)' in release_status
    assert (
        '**Release-blocking manual evidence gates** are defined in '
        '[`release_candidate_checklist.md`](./release_candidate_checklist.md)'
    ) in release_status
    assert 'Google conversion smoke is intentionally local-only' in release_status

    assert 'local secure-workstation Google conversion smoke' in open_testing_runbook
    assert 'Google conversion smoke is release-blocking for promoted RC artifacts' in release_checklist
    assert 'green CI does not satisfy that gate' in release_checklist
    assert 'does **not** count as smoke evidence' in google_runbook
    assert 'not executed / promotion blocked' in google_runbook
    assert 'green CI run does not satisfy this gate' in google_log


def test_active_release_docs_use_master_as_current_production_branch() -> None:
    docs = {
        BRANCHING_STRATEGY_PATH: BRANCHING_STRATEGY_PATH.read_text(encoding='utf-8'),
        RELEASE_BRANCHING_PLAYBOOK_PATH: RELEASE_BRANCHING_PLAYBOOK_PATH.read_text(encoding='utf-8'),
        BEGINNER_RELEASE_PLAYBOOK_PATH: BEGINNER_RELEASE_PLAYBOOK_PATH.read_text(encoding='utf-8'),
        RC_CHECKLIST_PATH: RC_CHECKLIST_PATH.read_text(encoding='utf-8'),
    }

    for path, text in docs.items():
        assert 'git checkout main' not in text, f'{path} still uses main checkout commands'
        assert 'origin main' not in text, f'{path} still pulls or pushes origin main'
        assert 'merge into `main`' not in text, f'{path} still documents main as merge target'
        assert 'release/2026.03-rc1' not in text, f'{path} still uses stale 2026.03 RC examples'

    assert '`master`: current production-ready branch' in docs[BRANCHING_STRATEGY_PATH]
    assert 'git checkout master' in docs[RC_CHECKLIST_PATH]
    assert 'git checkout master' in docs[RELEASE_BRANCHING_PLAYBOOK_PATH]
    assert 'git checkout master' in docs[BEGINNER_RELEASE_PLAYBOOK_PATH]


def test_release_status_keeps_current_release_line_metadata() -> None:
    release_status = RELEASE_STATUS_PATH.read_text(encoding='utf-8')

    assert 'Release line metadata is canonical in `src/metroliza/app/version.py`' in release_status
    assert '`RELEASE_VERSION`' in release_status
    assert '`VERSION_DATE`' in release_status
    assert '`CURRENT_RELEASE_HIGHLIGHT`' in release_status

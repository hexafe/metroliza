from __future__ import annotations

from pathlib import Path
import re

import pytest

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


def test_native_windows_report_planner_step_preserves_real_platform_and_scope() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    policy = CI_POLICY_PATH.read_text(encoding='utf-8')
    name = 'Run native Windows report planner tests'
    step = workflow.split(f'- name: {name}', 1)[1].split('- name:', 1)[0]
    assert 'QT_QPA_PLATFORM: windows' in step
    assert 'METROLIZA_EXPECT_QT_PLATFORM: windows' in step
    assert 'Set-DisplayResolution -Width 1920 -Height 1080 -Force' in step
    assert 'METROLIZA_EXPECT_PLANNER_SCREEN: 1920x1080' in step
    for test in ('model', 'integration', 'geometry'):
        assert f'tests/test_report_planner_{test}.py' in step
    assert name in policy
    assert 'scale factors 1, 1.25, 1.5 and 2' in policy
    assert 'do not qualify a packaged EXE' in policy


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
    assert (
        "cancel-in-progress: ${{ !(github.event_name == 'workflow_dispatch' && "
        "inputs.run_windows_wrapper_diagnostics == '1') }}"
    ) in workflow
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


def test_windows_wrapper_discriminator_is_exclusively_manual_and_bounded() -> None:
    import yaml

    workflow = yaml.load(CI_WORKFLOW_PATH.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    job = workflow['jobs']['windows-wrapper-diagnostics']
    gate = job['if']
    assert "github.event_name == 'workflow_dispatch'" in gate
    assert "inputs.run_windows_wrapper_diagnostics == '1'" in gate
    assert 'github.actor == github.repository_owner' in gate
    assert 'github.event.repository.private == false' in gate
    assert workflow['on']['workflow_dispatch']['inputs']['run_windows_wrapper_diagnostics'][
        'default'
    ] == '0'
    assert job['runs-on'] == 'windows-latest'
    assert int(job['timeout-minutes']) <= 30
    assert job['concurrency']['cancel-in-progress'] == 'false'
    assert job['concurrency']['group'] == 'windows-wrapper-discriminator-${{ github.repository }}'
    assert workflow['permissions'] == {'contents': 'read'}
    assert workflow['concurrency']['group'] == (
        "ci-${{ github.workflow }}-${{ github.ref }}"
        "${{ github.event_name == 'workflow_dispatch' && "
        "inputs.run_windows_wrapper_diagnostics == '1' && '-wrapper' || '' }}"
    )  # Only the opted-in experiment gets a separate group; ordinary CI keeps its key.
    assert workflow['concurrency']['cancel-in-progress'] == (
        "${{ !(github.event_name == 'workflow_dispatch' && "
        "inputs.run_windows_wrapper_diagnostics == '1') }}"
    )
    for step in job['steps']:
        assert 'actions/upload-artifact@' not in step.get('uses', '')
        assert 'actions/cache@' not in step.get('uses', '')
        assert 'cache' not in step.get('with', {})
        if step.get('uses', '').startswith('actions/checkout@'):
            assert step['with']['persist-credentials'] == 'false'
    invocation = job['steps'][-1]['run']
    assert 'timeout=1500' in invocation  # Five minutes remain for owner/job cleanup.
    assert 'stdout=subprocess.DEVNULL' in invocation
    assert 'stderr=subprocess.DEVNULL' in invocation
    assert 'TemporaryDirectory(' in invocation
    assert "'--basetemp=' + str(root / 'fixtures')" in invocation
    assert 'sys.exit(result)' in invocation
    assert "'-x'" in invocation
    assert invocation.index("'tests/test_windows_ocr_wrapper_completion.py'") < invocation.index(
        "'tests/test_windows_ocr_powershell.py'"
    )
    for path in ('test_windows_ocr_runtime_diagnostics.py',
                 'test_header_ocr_diagnostics_script.py', 'test_windows_ocr_invoke.py'):
        assert path in invocation
    assert 'METROLIZA_WINDOWS_WRAPPER_BASELINE' not in invocation


@pytest.mark.parametrize('mutation', ['valid', 'extra', 'domain', 'boolean', 'huge', 'missing',
                                    'invoke_reason', 'invoke_cleanup', 'invoke_process_exit_code',
                                    'fixture_phase'])
def test_windows_wrapper_receipts_reject_uncontrolled_fields(tmp_path, mutation) -> None:
    import ast
    import json

    import yaml

    workflow = yaml.load(CI_WORKFLOW_PATH.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    code = workflow['jobs']['windows-wrapper-diagnostics']['steps'][-1]['run']
    function = next(node for node in ast.parse(code).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'safe_receipts')
    namespace = {'json': json}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<receipt-validator>', 'exec'),
         namespace)
    value = {'schema_version': 1, 'shell': 'pwsh', 'scenario': 'retained_pipes',
             'stage': 'completion', 'result': 'bounded_failure', 'reason': 'timeout',
             'elapsed_ms': 1500, 'shell_exited_before_timeout': True,
             'stdout_pipe': True, 'stderr_pipe': False,
             'shell_state': 'exited', 'fixture_stage': 'child_ready',
             'fixture_phase': 'child_created',
             'invoke_state': 'unobserved', 'invoke_reason': 'unobserved',
             'invoke_cleanup': 'unobserved', 'invoke_process_exit_code': None,
             'cleanup_complete': True, 'outer_exit_code': 1, 'invoke_exit_code': None}
    if mutation == 'extra':
        value['raw_output'] = 'SYNTHETIC_PRIVATE_CANARY'
    elif mutation == 'domain':
        value['shell'] = 'SYNTHETIC_PRIVATE_CANARY'
    elif mutation == 'boolean':
        value['elapsed_ms'] = True
    elif mutation in {'invoke_reason', 'invoke_cleanup', 'fixture_phase'}:
        value[mutation] = 'SYNTHETIC_PRIVATE_CANARY'
    elif mutation == 'invoke_process_exit_code':
        value[mutation] = True
    path = tmp_path / 'windows-ocr-wrapper-receipts.jsonl'
    if mutation != 'missing':
        path.write_text('x' * 32769 if mutation == 'huge' else json.dumps(value), encoding='utf-8')
    if mutation == 'valid':
        assert namespace['safe_receipts'](tmp_path) == [value]
    else:
        with pytest.raises(ValueError) as caught:
            namespace['safe_receipts'](tmp_path)
        assert 'SYNTHETIC_PRIVATE_CANARY' not in str(caught.value)


@pytest.mark.parametrize('failure', ['cleanup', 'timeout'])
def test_windows_wrapper_lane_never_prints_private_failure_context(
    tmp_path, monkeypatch, capsys, failure
) -> None:
    import subprocess
    import tempfile
    from types import SimpleNamespace

    import yaml

    workflow = yaml.load(CI_WORKFLOW_PATH.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    code = workflow['jobs']['windows-wrapper-diagnostics']['steps'][-1]['run']

    class PrivateScope:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return str(tmp_path)

        def __exit__(self, *_args):
            if failure == 'cleanup':
                raise PermissionError('SYNTHETIC_PRIVATE_CANARY')

    def runner(*_args, **_kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(['SYNTHETIC_PRIVATE_CANARY'], 1500)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(tempfile, 'TemporaryDirectory', PrivateScope)
    monkeypatch.setattr(subprocess, 'run', runner)
    with pytest.raises(SystemExit) as caught:
        exec(compile(code, '<native-lane>', 'exec'), {})
    assert caught.value.code == 1
    output = capsys.readouterr()
    assert 'SYNTHETIC_PRIVATE_CANARY' not in output.out + output.err
    assert 'private_cleanup_failed' in output.out if failure == 'cleanup' else 'outer_timeout' in output.out


@pytest.mark.parametrize('stage,code,expected', [
    ('invoke_returned', 1, 'bounded_failure'),
    ('invoke_failed', None, 'bounded_failure'),
    ('timeout_returned', None, 'bounded_failure'),
    ('invoke_returned', 0, 'completed'),
])
def test_windows_wrapper_receipt_cannot_hide_inner_failure(
    tmp_path, monkeypatch, stage, code, expected
):
    import json

    from tests.test_windows_ocr_wrapper_completion import _record
    from tests.windows_ocr_process import OwnedProcessResult

    monkeypatch.setenv('METROLIZA_WRAPPER_RECEIPTS', str(tmp_path))
    _record('pwsh', 'live_shell', OwnedProcessResult(0, 'completed', True, True, False, 2),
            ready={'stage': 'shell_ready'}, outcome=[{
                'stage': stage, 'returncode': code, 'reason': 'completed',
                'cleanup_complete': True, 'tree_empty': True, 'process_returncode': code,
                'output_limited': False,
            }], phase='shell_initialized')
    row = json.loads((tmp_path / 'windows-ocr-wrapper-receipts.jsonl').read_text())
    assert row['result'] == expected
    assert row['outer_exit_code'] == 0 and row['invoke_exit_code'] == code


@pytest.mark.parametrize('contradiction', [
    {'process_returncode': 17}, {'output_limited': True},
    {'cleanup_complete': False}, {'tree_empty': False},
])
def test_windows_wrapper_receipt_rejects_contradictory_success(
    tmp_path, monkeypatch, contradiction
):
    import json

    from tests.test_windows_ocr_wrapper_completion import _record
    from tests.windows_ocr_process import OwnedProcessResult

    monkeypatch.setenv('METROLIZA_WRAPPER_RECEIPTS', str(tmp_path))
    outcome = {
        'stage': 'invoke_returned', 'returncode': 0, 'reason': 'completed',
        'process_returncode': 0, 'output_limited': False,
        'cleanup_complete': True, 'tree_empty': True, **contradiction,
    }
    _record('pwsh', 'live_shell', OwnedProcessResult(0, 'completed', True, True, False, 2),
            ready={'stage': 'shell_ready'}, outcome=[outcome], phase='shell_initialized')
    row = json.loads((tmp_path / 'windows-ocr-wrapper-receipts.jsonl').read_text())
    assert row['result'] == 'bounded_failure'


def test_windows_wrapper_real_receipt_producer_matches_private_lane(tmp_path, monkeypatch):
    import ast
    import json

    import yaml

    from tests.test_windows_ocr_wrapper_completion import _record
    from tests.windows_ocr_process import OwnedProcessResult

    monkeypatch.setenv('METROLIZA_WRAPPER_RECEIPTS', str(tmp_path))
    _record(
        'pwsh', 'retained_pipes',
        OwnedProcessResult(1, 'timeout', True, True, False, 2.0),
        ready={'stage': 'SYNTHETIC_PRIVATE_CANARY', 'stdout_pipe': True, 'stderr_pipe': False},
        probe=[{'stage': 'timeout_before_kill', 'shell_state': 'SYNTHETIC_PRIVATE_CANARY'}],
        outcome=[{'stage': 'SYNTHETIC_PRIVATE_CANARY'}],
    )
    workflow = yaml.load(CI_WORKFLOW_PATH.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    code = workflow['jobs']['windows-wrapper-diagnostics']['steps'][-1]['run']
    function = next(node for node in ast.parse(code).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'safe_receipts')
    namespace = {'json': json}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<receipt-validator>', 'exec'),
         namespace)
    rows = namespace['safe_receipts'](tmp_path)
    assert len(rows) == 1
    assert rows[0]['stdout_pipe'] is True and rows[0]['stderr_pipe'] is False
    assert rows[0]['shell_state'] == rows[0]['fixture_stage'] == rows[0]['invoke_state'] == 'unobserved'
    assert 'SYNTHETIC_PRIVATE_CANARY' not in json.dumps(rows)


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

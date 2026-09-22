from __future__ import annotations

from pathlib import Path
import re

import pytest

CI_WORKFLOW_PATH = Path('.github/workflows/ci.yml')
CI_POLICY_PATH = Path('docs/ci-policy.md')
FEATURE_CATALOG_PATH = Path('docs/project/feature_catalog.md')
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


def test_native_windows_report_workspace_step_keeps_one_real_owner_and_dpi_gate() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    policy = CI_POLICY_PATH.read_text(encoding='utf-8')
    name = 'Run native Windows report workspace tests'
    step = workflow.split(f'- name: {name}', 1)[1].split('- name:', 1)[0]
    assert 'QT_QPA_PLATFORM: windows' in step
    assert 'METROLIZA_EXPECT_QT_PLATFORM: windows' in step
    assert 'METROLIZA_EXPECT_WORKSPACE_SCREEN: 1920x1080' in step
    assert 'Set-DisplayResolution -Width 1920 -Height 1080 -Force' in step
    assert 'pytest -vv -s' in step
    for test in ('report_workspace_shell', 'report_workspace_geometry', 'main_window_metadata_ui', 'active_dialog_close_guards'):
        assert f'tests/test_{test}.py' in step
    assert name in policy


def test_native_windows_realtime_step_keeps_the_complete_dialog_contract() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    policy = CI_POLICY_PATH.read_text(encoding='utf-8')
    name = 'Run native Windows realtime dashboard scheduling tests'
    step = workflow.split(f'- name: {name}', 1)[1].split('- name:', 1)[0]
    assert 'QT_QPA_PLATFORM: windows' in step
    assert 'METROLIZA_EXPECT_QT_PLATFORM: windows' in step
    assert 'python -m pytest -vv -s --tb=short --show-capture=no' in step
    assert 'tests/test_realtime_monitoring_dialog.py' in step
    parent_node = 'tests/test_main_window_metadata_ui.py::TestMainWindowMetadataUi::'
    assert parent_node + 'test_realtime_private_cleanup_failure_keeps_parent_and_correct_retry_notice' in step
    assert parent_node + 'test_realtime_deferred_private_cleanup_failure_notifies_parent_and_retries' in step
    assert parent_node + 'test_dirty_realtime_source_cancel_never_arms_automatic_root_close' in step
    assert ' -k ' not in step
    assert 'continue-on-error' not in step
    assert 'METROLIZA_EXPECT_PRIVACY_PYTHON: 3.11.9' in step
    windows = workflow.split('  windows-core-smoke:', 1)[1].split('  windows-startup-benchmark:', 1)[0]
    assert "python-version: '3.11.9'" in windows
    assert 'Windows owner/DACL/effective access' in policy
    assert 'restricted_current_user' in policy
    assert name in policy
    assert 'controlled deferred-dispatch' in policy
    assert 'real QThread/SQLite/HTML' in policy


def test_native_windows_grouping_preview_step_keeps_complete_file_and_order() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding='utf-8')
    policy = CI_POLICY_PATH.read_text(encoding='utf-8')
    name = 'Run native Windows grouping-preview lifecycle tests'
    ocr_name = 'Run safe OCR diagnostics and native PowerShell contract tests'
    step = workflow.split(f'- name: {name}', 1)[1].split('- name:', 1)[0]
    assert 'QT_QPA_PLATFORM: windows' in step
    assert 'METROLIZA_EXPECT_QT_PLATFORM: windows' in step
    assert 'python -m pytest -vv -s --tb=short --show-capture=no' in step
    assert 'tests/test_tabular_analytics_grouping_dialog.py' in step
    assert ' -k ' not in step
    assert 'continue-on-error' not in step
    assert 'if:' not in step
    assert workflow.index(f'- name: {name}') < workflow.index(f'- name: {ocr_name}')
    assert name in policy
    assert 'complete `tests/test_tabular_analytics_grouping_dialog.py` file' in policy
    assert 'independent OCR/PowerShell contract step' in policy



"""Closed-schema checks for the synthetic packaged bug report journey."""
from __future__ import annotations

import pytest

from scripts import verify_windows_candidate_uiux as verifier


def observation():
    return {
        'schema_version': 1,
        'status': 'passed',
        'facets': dict.fromkeys(('help_action', 'preview', 'clipboard', 'history_restore',
                                 'privacy_guards', 'cleanup'), 'passed'),
        'error_codes': [],
        'evidence': {
            'execution': 'packaged',
            'platform': 'windows',
            'history_state': 'available',
            'actions': ['app_opened', 'csv_opened', 'option_workbook', 'option_html'],
            'option_states': {'workbook': True, 'html': False},
            'category': 'wrong_output',
            'reproduction_status': 'NOT_RUN',
            'preview_sha256': 'a' * 64,
            'clipboard_match': True,
            'excluded_sentinels_absent': True,
            'dialog_closed': True,
        },
    }


def test_bugreport_leaf_accepts_only_complete_synthetic_journey():
    assert verifier.bugreport_leaf(observation(), packaged=True, qpa='windows')['clipboard_match'] is True


@pytest.mark.parametrize(('field', 'value'), [
    ('history_state', 'unknown'),
    ('actions', ['app_opened', 'SYNTHETIC_CONFIDENTIAL_PATH_7F3A']),
    ('option_states', {'workbook': True, 'html': 'true'}),
    ('preview_sha256', '../customer-report.txt'),
    ('clipboard_match', False),
    ('excluded_sentinels_absent', False),
    ('dialog_closed', False),
])
def test_bugreport_leaf_rejects_incomplete_or_open_ended_evidence(field, value):
    record = observation()
    record['evidence'][field] = value
    with pytest.raises(verifier.UiuxVerificationFailure):
        verifier.bugreport_leaf(record, packaged=True, qpa='windows')


def test_bugreport_artifact_contains_no_report_text_or_path_fields():
    record = observation()
    assert set(record['evidence']) == {
        'execution', 'platform', 'history_state', 'actions', 'option_states', 'category',
        'reproduction_status', 'preview_sha256', 'clipboard_match',
        'excluded_sentinels_absent', 'dialog_closed',
    }
    assert all('path' not in key and 'text' not in key for key in record['evidence'])


def test_synthetic_source_journey_restores_history_previews_and_copies(qapplication_session, tmp_path, monkeypatch):
    from metroliza.app.windows_candidate_uiux_bugreport import run_bugreport_checks

    monkeypatch.setenv('METROLIZA_STARTUP_SMOKE', '1')
    monkeypatch.setenv('METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION', '1')
    result = run_bugreport_checks(tmp_path)
    assert result['status'] == 'passed', result['error_codes']
    assert result['evidence']['execution'] == 'source'
    verifier.bugreport_leaf(result, packaged=False, qpa=qapplication_session.platformName())
    assert result['facets'] == dict.fromkeys(
        ('help_action', 'preview', 'clipboard', 'history_restore', 'privacy_guards', 'cleanup'), 'passed')
    assert not (tmp_path / 'bugreport-synthetic-history').exists()
    assert not (tmp_path / 'bugreport-synthetic-settings.ini').exists()


@pytest.mark.parametrize('mutation', ['drop_app_opened', 'claim_reproduced'])
def test_journey_rejects_incomplete_or_false_reproduction_preview(qapplication_session, tmp_path, monkeypatch, mutation):
    from metroliza.ui import safe_bugreport_dialog
    from metroliza.app.windows_candidate_uiux_bugreport import run_bugreport_checks

    monkeypatch.setenv('METROLIZA_STARTUP_SMOKE', '1')
    monkeypatch.setenv('METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION', '1')
    original = safe_bugreport_dialog.build_bug_report_markdown

    def tampered(*args, **kwargs):
        report = original(*args, **kwargs)
        if mutation == 'drop_app_opened':
            return report.replace('- `app_opened`\n', '', 1)
        return report.replace('Reproduction status: `NOT_RUN`', 'Reproduction status: `PASSED`', 1)

    monkeypatch.setattr(safe_bugreport_dialog, 'build_bug_report_markdown', tampered)
    result = run_bugreport_checks(tmp_path)
    assert result['status'] == 'failed'
    assert result['error_codes'] == ['bugreport_preview_invalid']
    verifier.bugreport_diagnostic_leaf(result, packaged=False, qpa=qapplication_session.platformName())
    assert result['facets']['preview'] == 'failed'
    assert result['facets']['privacy_guards'] == 'failed'
    assert not (tmp_path / 'bugreport-synthetic-history').exists()
    assert not (tmp_path / 'bugreport-synthetic-settings.ini').exists()


def test_privacy_failure_cannot_claim_privacy_facet_passed():
    record = observation()
    record.update(status='failed', error_codes=['bugreport_privacy_invalid'])
    record['facets']['privacy_guards'] = 'passed'
    with pytest.raises(verifier.UiuxVerificationFailure):
        verifier.bugreport_diagnostic_leaf(record, packaged=True, qpa='windows')

"""Closed-schema checks for the synthetic packaged bug report journey."""
from __future__ import annotations

import json
import platform
import sys

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
            'actions': list(verifier.BUGREPORT_ACTIONS),
            'option_states': {'report_review_ocr': True, 'workbook': True, 'html': False},
            'category': 'wrong_output',
            'reproduction_status': 'NOT_RUN',
            'preview_sha256': 'a' * 64,
            'clipboard_match': True,
            'excluded_sentinels_absent': True,
            'dialog_closed': True,
            'report_schema': 2,
            'detailed_context_validated': True,
            'frozen_preview': True,
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
    ('report_schema', None),
    ('report_schema', True),
    ('report_schema', '2'),
    ('detailed_context_validated', False),
    ('detailed_context_validated', 1),
    ('frozen_preview', False),
    ('frozen_preview', 'true'),
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
        'excluded_sentinels_absent', 'dialog_closed', 'report_schema',
        'detailed_context_validated', 'frozen_preview',
    }
    assert all(key not in record['evidence'] for key in ('path', 'text', 'preview', 'context'))


def test_synthetic_source_journey_restores_history_previews_and_copies(qapplication_session, tmp_path, monkeypatch):
    from metroliza.app.windows_candidate_uiux_bugreport import run_bugreport_checks

    monkeypatch.setenv('METROLIZA_STARTUP_SMOKE', '1')
    monkeypatch.setenv('METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION', '1')
    result = run_bugreport_checks(tmp_path)
    assert result['status'] == 'passed', result['error_codes']
    assert result['evidence']['execution'] == 'source'
    assert result['evidence']['report_schema'] == 2
    assert result['evidence']['detailed_context_validated'] is True
    assert result['evidence']['frozen_preview'] is True
    verifier.bugreport_leaf(result, packaged=False, qpa=qapplication_session.platformName())
    assert result['facets'] == dict.fromkeys(
        ('help_action', 'preview', 'clipboard', 'history_restore', 'privacy_guards', 'cleanup'), 'passed')
    assert not (tmp_path / 'bugreport-synthetic-history').exists()
    assert not (tmp_path / 'bugreport-synthetic-settings.ini').exists()


def _raw_preview():
    """Independent fixture: no product context builder/parser supplies expected data."""
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    from metroliza.app.version import RELEASE_VERSION

    session = '00112233-4455-4677-8899-aabbccddeeff'
    request = '11112233-4455-4677-8899-aabbccddeeff'
    states = {4: True, 18: True, 19: False}
    actions = [dict(action=action, enabled=states.get(index))
               for index, action in enumerate(verifier.BUGREPORT_ACTIONS)]
    stamps = {sequence: sequence * 10 for sequence in range(1, 27)}
    events = [dict(session_id=session, sequence=index + 1, relative_ms=stamps[index + 1],
                   kind='action', **action) for index, action in enumerate(actions)]
    for sequence, outcome, duration in ((23, 'started', None), (24, 'completed', 10)):
        events.append(dict(session_id=session, sequence=sequence, relative_ms=stamps[sequence],
                           kind='request', request=dict(operation_id=request, kind='report_export',
                                                       outcome=outcome, duration_ms=duration)))
    events.append(dict(session_id=session, sequence=25, relative_ms=250, kind='exception',
                       category='permission', site='report_export'))
    events.append(dict(session_id=session, sequence=26, relative_ms=260, kind='output_verification',
                       output_verification=dict(kind='report_workbook', passed=True, operation_id=request)))
    raw = dict(schema=2, release_version=RELEASE_VERSION, category='wrong_output',
        activity=dict(events=actions, events_lost=False, previous_session_state='available'),
        context=dict(events=events, options=[dict(session_id=session, sequence=22, relative_ms=220,
            kind='report_export', options={'workbook': True, 'html': False}, operation_id=request)],
            events_lost=False, snapshots_lost=False, snapshot_state='available'),
        selection=dict(module='tabular', symptom='wrong_output',
                       expected='all_requested_outputs', observed='wrong_output'),
        provenance=dict(platform={'win32': 'windows', 'linux': 'linux', 'darwin': 'macos'}.get(sys.platform, 'unknown'),
            arch={'AMD64': 'x86_64', 'amd64': 'x86_64', 'x86_64': 'x86_64',
                  'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine(), 'unknown'),
            python='.'.join(map(str, sys.version_info[:3])), qt=QT_VERSION_STR, pyqt=PYQT_VERSION_STR,
            runtime='source', packager='source', git_sha='unknown', dirty=None))
    return raw, dict(request_id=request, session_id=session, stamps=stamps)


# Keep literal framing here too: tests must detect accidental oracle-guidance edits.
PREFIX = (
    '# Metroliza bug report v2\n\n'
    'Privacy: fixed codes, boolean options, runtime tokens and vetted build facts only.\n'
    'Missing context: unknown. Option observations do not imply operation association.\n'
    'Recent activity is queued asynchronously and may not survive forced exit.\n'
    'Reproduction status: `NOT_RUN`\nExternal input data: `not included`\n\n```json\n'
)
SUFFIX = (
    '\n```\n\n## Reproduction\nReproduction not performed. Input data was not captured.\n'
    "Use synthetic inputs only; a reference scenario cannot reproduce the user's issue.\n"
    '\n## Instructions for a coding agent\n'
    'Inspect the source for the recorded actions, results and options; investigate the reported category.\n'
    'Use synthetic inputs only. Do not request or infer confidential files, values, paths or names.\n'
    'Attempt a relevant reproduction where possible; distinguish evidence, hypotheses and unverified behavior.\n'
)


def _render(raw):
    return PREFIX + json.dumps(raw, ensure_ascii=True, sort_keys=True, indent=2) + SUFFIX


def test_independent_oracle_admits_complete_v2_seed():
    from metroliza.app import windows_candidate_uiux_bugreport as checks

    raw, seed = _raw_preview()
    checks._validate_preview(_render(raw), **seed)


@pytest.mark.parametrize('mutation', [
    'schema', 'version', 'category', 'missing_action', 'altered_action', 'action_bool',
    'option_bool', 'option_key', 'selection', 'unknown_top', 'unknown_context',
    'unknown_event', 'unknown_snapshot', 'unknown_request', 'unknown_provenance',
    'missing_context_event', 'order', 'session', 'uuid', 'sequence_bool', 'relative_ms',
    'duration', 'request_kind', 'request_outcome', 'request_uuid', 'snapshot_uuid',
    'exception', 'exception_site', 'output_kind', 'output_passed', 'output_uuid',
    'events_lost', 'snapshot_state', 'snapshots_lost',
    'provenance_platform', 'provenance_arch', 'provenance_python', 'provenance_qt',
    'provenance_pyqt', 'provenance_runtime', 'provenance_packager', 'provenance_sha',
    'provenance_dirty',
])
def test_independent_oracle_rejects_context_and_provenance_mutations(mutation):
    from metroliza.app import windows_candidate_uiux_bugreport as checks

    raw, seed = _raw_preview()
    context = raw['context']
    events, option = context['events'], context['options'][0]
    if mutation == 'schema':
        raw['schema'] = True
    elif mutation in ('version', 'category'):
        raw['release_version' if mutation == 'version' else 'category'] = 'unknown'
    elif mutation == 'missing_action':
        raw['activity']['events'].pop()
    elif mutation == 'altered_action':
        raw['activity']['events'][0]['action'] = 'unknown_event'
    elif mutation == 'action_bool':
        raw['activity']['events'][4]['enabled'] = 1
    elif mutation == 'option_bool':
        option['options']['workbook'] = 1
    elif mutation == 'option_key':
        option['options']['data'] = True
    elif mutation == 'selection':
        raw['selection']['module'] = 'unknown'
    elif mutation.startswith('unknown_'):
        target = {'unknown_top': raw, 'unknown_context': context, 'unknown_event': events[0],
                  'unknown_snapshot': option, 'unknown_request': events[21]['request'],
                  'unknown_provenance': raw['provenance']}[mutation]
        target['data'] = 'SYNTHETIC_INPUT_VALUE_62DE'
    elif mutation == 'missing_context_event':
        events.pop()
    elif mutation == 'order':
        events[0], events[1] = events[1], events[0]
    elif mutation == 'session':
        events[1]['session_id'] = seed['request_id']
    elif mutation == 'uuid':
        events[0]['session_id'] = 'invalid'
    elif mutation == 'sequence_bool':
        events[0]['sequence'] = True
    elif mutation == 'relative_ms':
        events[1]['relative_ms'] = 0
    elif mutation == 'duration':
        events[22]['request']['duration_ms'] = -1
    elif mutation in ('request_kind', 'request_outcome', 'request_uuid'):
        events[22]['request'][{'request_kind': 'kind', 'request_outcome': 'outcome',
                               'request_uuid': 'operation_id'}[mutation]] = 'unknown'
    elif mutation == 'snapshot_uuid':
        option['operation_id'] = seed['session_id']
    elif mutation in ('exception', 'exception_site'):
        events[23]['category' if mutation == 'exception' else 'site'] = 'unknown'
    elif mutation.startswith('output_'):
        events[24]['output_verification'][{'output_kind': 'kind', 'output_passed': 'passed',
                                           'output_uuid': 'operation_id'}[mutation]] = None
    elif mutation in ('events_lost', 'snapshots_lost'):
        context[mutation] = True
    elif mutation == 'snapshot_state':
        context['snapshot_state'] = 'unknown'
    else:
        key = mutation.removeprefix('provenance_')
        raw['provenance']['git_sha' if key == 'sha' else key] = 'altered'
    with pytest.raises(checks.BugReportChecksFailure, match='^bugreport_preview_invalid$'):
        checks._validate_preview(_render(raw), **seed)


@pytest.mark.parametrize('mutation', [
    'missing_privacy', 'changed_privacy', 'missing_guidance', 'changed_guidance',
    'claim_reproduced', 'missing_reproduction', 'unknown_text', 'duplicate_json_key',
    'unknown_suffix', 'oversized',
])
def test_independent_oracle_rejects_changed_literal_framing_and_json(mutation):
    from metroliza.app import windows_candidate_uiux_bugreport as checks

    raw, seed = _raw_preview()
    preview = _render(raw)
    if mutation == 'missing_privacy':
        preview = preview.replace('Privacy: fixed codes, boolean options, runtime tokens and vetted build facts only.\n', '')
    elif mutation == 'changed_privacy':
        preview = preview.replace('fixed codes, boolean options', 'input data')
    elif mutation == 'missing_guidance':
        preview = preview.replace('## Instructions for a coding agent\n', '')
    elif mutation == 'changed_guidance':
        preview = preview.replace('Use synthetic inputs only.', 'Use user inputs.')
    elif mutation == 'claim_reproduced':
        preview = preview.replace('Reproduction status: `NOT_RUN`', 'Reproduction status: `PASSED`')
    elif mutation == 'missing_reproduction':
        preview = preview.replace('Reproduction not performed. Input data was not captured.\n', '')
    elif mutation == 'unknown_text':
        preview = preview.replace('```json\n', 'unapproved text\n```json\n')
    elif mutation == 'duplicate_json_key':
        preview = preview.replace('"schema": 2,', '"schema": 2, "schema": 2,')
    elif mutation == 'unknown_suffix':
        preview += 'unapproved text'
    else:
        preview += 'x' * (128 * 1024)
    with pytest.raises(checks.BugReportChecksFailure, match='^bugreport_preview_invalid$'):
        checks._validate_preview(preview, **seed)


@pytest.mark.parametrize('mutation', ['action', 'context', 'provenance', 'framing'])
def test_real_dialog_journey_rejects_tampered_v2_preview(
        qapplication_session, tmp_path, monkeypatch, mutation):
    from metroliza.ui import safe_bugreport_dialog
    from metroliza.app.windows_candidate_uiux_bugreport import run_bugreport_checks

    monkeypatch.setenv('METROLIZA_STARTUP_SMOKE', '1')
    monkeypatch.setenv('METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION', '1')
    original = safe_bugreport_dialog.build_bug_report_markdown

    def tampered(*args, **kwargs):
        preview = original(*args, **kwargs)
        if mutation == 'framing':
            return preview.replace('Reproduction status: `NOT_RUN`', 'Reproduction status: `PASSED`')
        raw = json.loads(preview[len(PREFIX):-len(SUFFIX)])
        if mutation == 'action':
            raw['activity']['events'].pop()
        elif mutation == 'context':
            raw['context']['options'][0]['options']['workbook'] = False
        else:
            raw['provenance']['runtime'] = 'frozen'
        return _render(raw)

    monkeypatch.setattr(safe_bugreport_dialog, 'build_bug_report_markdown', tampered)
    result = run_bugreport_checks(tmp_path)
    assert result['status'] == 'failed'
    assert result['error_codes'] == ['bugreport_preview_invalid']
    verifier.bugreport_diagnostic_leaf(result, packaged=False, qpa=qapplication_session.platformName())
    assert result['facets']['preview'] == 'failed'
    assert result['evidence']['report_schema'] is None
    assert result['evidence']['detailed_context_validated'] is False
    assert not (tmp_path / 'bugreport-synthetic-history').exists()
    assert not (tmp_path / 'bugreport-synthetic-settings.ini').exists()


def test_privacy_negative_control_rejects_and_does_not_receipt_a_sentinel(
        qapplication_session, tmp_path, monkeypatch):
    from metroliza.ui import safe_bugreport_dialog
    from metroliza.app import windows_candidate_uiux_bugreport as checks

    monkeypatch.setenv('METROLIZA_STARTUP_SMOKE', '1')
    monkeypatch.setenv('METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION', '1')
    original = safe_bugreport_dialog.build_bug_report_markdown

    def contaminated(*args, **kwargs):
        return original(*args, **kwargs).replace('## Reproduction\n',
            'SYNTHETIC_CONFIDENTIAL_PATH_7F3A\n\n## Reproduction\n', 1)

    monkeypatch.setattr(safe_bugreport_dialog, 'build_bug_report_markdown', contaminated)
    # Isolate the independent privacy guard after deliberately bypassing structural admission.
    monkeypatch.setattr(checks, '_validate_preview', lambda *_args, **_kwargs: None)

    result = checks.run_bugreport_checks(tmp_path)
    assert result['status'] == 'failed'
    assert result['error_codes'] == ['bugreport_privacy_invalid']
    assert result['facets']['preview'] == 'passed'
    assert result['facets']['privacy_guards'] == 'failed'
    assert 'SYNTHETIC_CONFIDENTIAL_PATH_7F3A' not in repr(result)
    verifier.bugreport_diagnostic_leaf(result, packaged=False, qpa=qapplication_session.platformName())
    assert not (tmp_path / 'bugreport-synthetic-history').exists()
    assert not (tmp_path / 'bugreport-synthetic-settings.ini').exists()


def test_privacy_failure_cannot_claim_privacy_facet_passed():
    record = observation()
    record.update(status='failed', error_codes=['bugreport_privacy_invalid'])
    record['facets']['privacy_guards'] = 'passed'
    with pytest.raises(verifier.UiuxVerificationFailure):
        verifier.bugreport_diagnostic_leaf(record, packaged=True, qpa='windows')


def test_diagnostic_accepts_initial_unknown_v2_evidence_without_preview():
    record = observation()
    record.update(status='failed', error_codes=['bugreport_route_missing'])
    record['facets'] = dict.fromkeys(record['facets'], 'failed')
    record['evidence'].update(report_schema=None, detailed_context_validated=False,
        frozen_preview=False, preview_sha256=None, clipboard_match=False,
        excluded_sentinels_absent=False)
    verifier.bugreport_diagnostic_leaf(record, packaged=True, qpa='windows')


@pytest.mark.parametrize(('field', 'invalid'), [
    ('report_schema', True), ('report_schema', '2'), ('report_schema', 1),
    ('detailed_context_validated', 1), ('detailed_context_validated', False),
    ('frozen_preview', 1), ('frozen_preview', False),
])
def test_diagnostic_rejects_invalid_or_inconsistent_v2_evidence(field, invalid):
    record = observation()
    record.update(status='failed', error_codes=['bugreport_privacy_invalid'])
    record['facets']['privacy_guards'] = 'failed'
    record['evidence'][field] = invalid
    with pytest.raises(verifier.UiuxVerificationFailure):
        verifier.bugreport_diagnostic_leaf(record, packaged=True, qpa='windows')


@pytest.mark.parametrize('leaf', ['success', 'diagnostic'])
def test_receipts_reject_raw_report_fields(leaf):
    record = observation()
    if leaf == 'diagnostic':
        record.update(status='failed', error_codes=['bugreport_privacy_invalid'])
        record['facets']['privacy_guards'] = 'failed'
    record['evidence']['raw_preview'] = 'SYNTHETIC_INPUT_VALUE_62DE'
    validator = verifier.bugreport_leaf if leaf == 'success' else verifier.bugreport_diagnostic_leaf
    with pytest.raises(verifier.UiuxVerificationFailure):
        validator(record, packaged=True, qpa='windows')


@pytest.mark.parametrize('mutation', [None, 'unknown_sha', 'changed_sha', 'unknown_packager',
                                      'unknown_dirty', 'changed_dirty', 'unknown_field'])
def test_frozen_provenance_is_bound_to_embedded_manifest(tmp_path, monkeypatch, mutation):
    from metroliza.app import windows_candidate_uiux_bugreport as checks
    from metroliza.app.version import RELEASE_VERSION

    raw, seed = _raw_preview()
    manifest = dict(schema_version=1, release_label=RELEASE_VERSION, git_sha='a' * 40,
        dirty=False, built_at_utc='2026-11-15T00:00:00Z', packager='pyinstaller',
        python_version='.'.join(map(str, sys.version_info[:3])))
    (tmp_path / 'build_provenance.json').write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setattr(checks, '__file__', str(tmp_path / 'windows_candidate_uiux_bugreport.py'))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    provenance = raw['provenance']
    provenance.update(runtime='frozen', packager='pyinstaller', git_sha='a' * 40, dirty=False)
    if mutation is not None:
        field, value = {
            'unknown_sha': ('git_sha', 'unknown'), 'changed_sha': ('git_sha', 'b' * 40),
            'unknown_packager': ('packager', 'unknown'), 'unknown_dirty': ('dirty', None),
            'changed_dirty': ('dirty', True), 'unknown_field': ('data', 'private'),
        }[mutation]
        provenance[field] = value
        with pytest.raises(checks.BugReportChecksFailure, match='^bugreport_preview_invalid$'):
            checks._validate_preview(_render(raw), **seed)
    else:
        checks._validate_preview(_render(raw), **seed)


def test_copy_recapturing_later_activity_fails_frozen_snapshot_qualification(
        qapplication_session, tmp_path, monkeypatch):
    from metroliza.ui.safe_bugreport_dialog import SafeBugReportDialog
    from metroliza.app.windows_candidate_uiux_bugreport import run_bugreport_checks

    monkeypatch.setenv('METROLIZA_STARTUP_SMOKE', '1')
    monkeypatch.setenv('METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION', '1')
    original = SafeBugReportDialog.copy_report

    def recapturing(dialog):
        dialog.refresh_snapshot()
        original(dialog)

    monkeypatch.setattr(SafeBugReportDialog, 'copy_report', recapturing)
    result = run_bugreport_checks(tmp_path)
    assert result['status'] == 'failed'
    assert result['error_codes'] == ['bugreport_clipboard_invalid']
    assert result['evidence']['frozen_preview'] is False
    verifier.bugreport_diagnostic_leaf(result, packaged=False, qpa=qapplication_session.platformName())
    assert not (tmp_path / 'bugreport-synthetic-history').exists()

"""Protocol/capture checks plus one independent real controls journey; no packaged claim."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from metroliza.app import windows_candidate_uiux_controls as checks

FIXTURES = Path(__file__).parent / 'fixtures'


def _gates(monkeypatch):
    for key in ('METROLIZA_STARTUP_SMOKE', 'METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION'):
        monkeypatch.setenv(key, '1')


def _closed(result):
    assert set(result) == {'schema_version', 'status', 'facets', 'error_codes', 'evidence'}
    assert result['schema_version'] == 1 and result['status'] in ('passed', 'failed')
    assert set(result['facets']) == set(checks.FACETS)
    assert set(result['facets'].values()) <= {'passed', 'failed'}
    assert set(result['error_codes']) <= set(checks.ERROR_CODES)
    assert set(result['evidence']) == {'context', 'routes', 'owners', 'report_tab', 'text_guards',
                                      'modal_keys', 'compact_dialogs', 'captures', 'cleanup', 'failure'}


def test_lazy_import_and_missing_gate_do_not_load_qt_or_make_scratch(tmp_path):
    script = '''import json,sys
from metroliza.app import windows_candidate_uiux_controls as c
assert not any(name.startswith(('PyQt6','metroliza.ui.')) for name in sys.modules)
r=c.run_controls_checks(sys.argv[1],sys.argv[1],expected_dpr=1,capture=lambda *args: None)
assert r['status']=='failed' and r['error_codes']==['controls_gate_missing']
assert not any(name.startswith(('PyQt6','metroliza.ui.')) for name in sys.modules)
print(json.dumps(r))
'''
    env = os.environ.copy()
    for key in ('METROLIZA_STARTUP_SMOKE', 'METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION'):
        env.pop(key, None)
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], env=env,
                            text=True, capture_output=True, timeout=10, check=True)
    _closed(json.loads(result.stdout))
    assert not list(tmp_path.iterdir())


def test_capture_states_match_frozen_producers_and_literal_tenth_name():
    from metroliza.app import windows_candidate_uiux_reports as reports
    from metroliza.app import windows_candidate_uiux_tabular as tabular
    assert len(checks.CAPTURE_STATES) == 10
    assert {key: checks.CAPTURE_STATES[key] for key in reports.CAPTURE_STATES} == reports.CAPTURE_STATES
    assert {key: checks.CAPTURE_STATES[key] for key in tabular.CAPTURE_STATES} == tabular.CAPTURE_STATES
    assert checks.CAPTURE_STATES['active-child-modal'] == {
        'surface': 'csv-metrics', 'owner': 'csv-summary', 'selected_metrics': 1,
        'parent_no_start': True, 'modal': True,
    }
    assert len(checks.TAB_IDS) == 24 and len(set(checks.TAB_IDS)) == 24
    assert checks.TAB_IDS[:7] == ('directory_path', 'directory', 'archive', 'database_path',
                                 'database', 'metadata_mode', 'review')
    assert checks.TAB_IDS[-3:] == ('modify', 'mapping', 'export')


def test_fractional_capture_dimensions_follow_qt_tie_rounding():
    from PyQt6.QtCore import QSize
    actual = QSize(626, 402) * 1.25
    assert (actual.width(), actual.height()) == (783, 503)
    assert (round(626 * 1.25), round(402 * 1.25)) == (782, 502)


@pytest.mark.parametrize('missing', ['METROLIZA_STARTUP_SMOKE', 'METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION'])
def test_missing_each_gate_is_closed_for_leaf_and_factory(tmp_path, monkeypatch, missing):
    _gates(monkeypatch)
    monkeypatch.delenv(missing)
    result = checks.run_controls_checks(tmp_path, tmp_path, expected_dpr=1, capture=lambda *args: None)
    _closed(result)
    assert result['error_codes'] == ['controls_gate_missing']
    assert result['facets'] == dict.fromkeys(checks.FACETS, 'failed')
    with pytest.raises(checks.ControlsChecksFailure, match='^controls_gate_missing$'):
        checks.make_capture(tmp_path, expected_dpr=1)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('semantic_failure', [False, True])
def test_actual_capture_keeps_known_png_when_later_state_fails(
    qapplication_session, tmp_path, monkeypatch, semantic_failure,
):
    from PyQt6.QtCore import Qt, QSettings
    from metroliza.app.ui_entrypoint import load_main_window_factory
    from metroliza.app.windows_candidate_native_check import close_report_owner
    from metroliza.ui.ui_preferences import UiPreferences
    from metroliza.tabular.tabular_analytics_service import load_tabular_analytics_file, cleanup_tabular_load_result
    from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog, MetricSelectionDialog, SOURCE_TABULAR_FILE
    _gates(monkeypatch)
    settings = QSettings(str(tmp_path / 'capture-settings.ini'), QSettings.Format.IniFormat)
    owner = load_main_window_factory()('capture protocol', None, ui_preferences=UiPreferences(settings))
    owner.show()
    loaded = load_tabular_analytics_file(FIXTURES / 'windows_uiux/tabular/analysis.csv', force_sqlite=True)
    parent = IndustrialAnalyticsDialog(owner, source_kind=SOURCE_TABULAR_FILE, tabular_load_result=loaded)
    parent.show()
    child = MetricSelectionDialog(parent, metrics=tuple(metric.to_selection() for metric in loaded.metric_candidates), selected_fields={'value'})
    child.setModal(True)
    child.show()
    qapplication_session.processEvents()
    session = checks.make_capture(tmp_path, expected_dpr=qapplication_session.primaryScreen().devicePixelRatio())
    try:
        assert qapplication_session.activeModalWidget() is child
        if semantic_failure:
            child.clear_button.click()  # Actual UI state contradicts the fixed one-metric oracle.
            with pytest.raises(checks.ControlsChecksFailure, match='^capture_state_failed$'):
                session('active-child-modal', child, dict(checks.CAPTURE_STATES['active-child-modal']))
        else:
            metadata = session('active-child-modal', child, dict(checks.CAPTURE_STATES['active-child-modal']))
            assert set(metadata) == {'path', 'sha256', 'width', 'height', 'dpr'}
            assert metadata['width'] == (child.size() * metadata['dpr']).width()
            assert metadata['height'] == (child.size() * metadata['dpr']).height()
        snapshot = session.snapshot(require_complete=False)
        assert set(snapshot) == {'status', 'metadata', 'observations', 'error_codes'}
        assert snapshot['status'] == 'failed'  # The other nine pipeline captures were not run.
        assert set(snapshot['metadata']) == set(snapshot['observations']) == {'active-child-modal'}
        meta = snapshot['metadata']['active-child-modal']
        path = tmp_path / meta['path']
        assert path.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == meta['sha256']
        row = snapshot['observations']['active-child-modal']
        assert set(row) == {'status', 'expected_state', 'observed_state', 'window', 'controls', 'error_codes'}
        assert row['status'] == ('failed' if semantic_failure else 'passed')
        assert row['observed_state']['selected_metrics'] == (0 if semantic_failure else 1)
        assert {control['id'] for control in row['controls']} == {'apply', 'cancel', 'search', 'metrics'}
        assert snapshot['error_codes'] == (['capture_state_failed'] if semantic_failure else [])
        snapshot['metadata'].clear()
        assert set(session.metadata) == {'active-child-modal'}  # Defensive projection.
        with pytest.raises(checks.ControlsChecksFailure, match='^capture_state_failed$'):
            session.snapshot()
        assert parent.analytics_thread is None and parent.tabular_load_thread is None
        child.select_all_button.click()
        assert child.metrics_list.item(0).checkState() == Qt.CheckState.Checked
        child.cancel_button.click()
    finally:
        child.hide()
        parent.close()
        qapplication_session.processEvents()
        cleanup_tabular_load_result(loaded)
        close_report_owner(owner, qapplication_session)


def _stage(tmp_path):
    root = tmp_path / 'staged'
    root.mkdir()
    for path in (FIXTURES / 'windows_candidate').glob('*.csv'):
        shutil.copyfile(path, root / path.name)
    for path in (FIXTURES / 'windows_candidate/reports').glob('*.pdf'):
        shutil.copyfile(path, root / path.name)
    shutil.copytree(FIXTURES / 'windows_uiux', root / 'uiux')
    return root


def test_post_owner_admission_failure_closes_real_owner_and_joins_worker(
    qapplication_session, tmp_path, monkeypatch,
):
    from threading import Event
    from PyQt6 import sip
    from metroliza.app import windows_candidate_native_check as native
    from metroliza.parsing.preflight import ParsePreflightService
    _gates(monkeypatch)
    fixtures = _stage(tmp_path)
    root = tmp_path / 'negative-output'
    root.mkdir()
    started, closed, created, workers = Event(), [], [], []
    original_start = checks._Journey.start
    original_scan = ParsePreflightService.scan_source
    original_close = native.close_report_owner
    active = []

    def delegated(service, **kwargs):
        started.set()
        if not active[0].release.wait(5):
            raise RuntimeError('owned negative scan barrier deadline')
        return original_scan(service, **kwargs)

    def fail_after_real_start(journey):
        original_start(journey)
        active.append(journey)
        assert journey.window.isVisible() and journey.workspace is not None
        created.append(journey.window)
        assert journey.window.set_directory(str(journey.child / 'pdf'))
        assert journey.window.set_db_file(str(journey.child / 'admission.sqlite'))
        journey.workspace.scan_button.click()
        journey.wait(started.is_set, 4)
        worker = journey.workspace.preflight_thread
        assert worker is not None and worker.isRunning()
        workers.append(worker)
        raise checks.ControlsChecksFailure('controls_fixture_invalid')

    def canonical_close(window, app):
        closed.append(window)
        return original_close(window, app)

    monkeypatch.setattr(ParsePreflightService, 'scan_source', delegated)
    monkeypatch.setattr(checks._Journey, 'start', fail_after_real_start)
    monkeypatch.setattr(native, 'close_report_owner', canonical_close)
    capture = checks.make_capture(root, expected_dpr=qapplication_session.primaryScreen().devicePixelRatio())
    result = checks.run_controls_checks(root, fixtures,
        expected_dpr=qapplication_session.primaryScreen().devicePixelRatio(), capture=capture)
    _closed(result)
    assert result['status'] == 'failed' and result['error_codes'] == ['controls_fixture_invalid']
    assert result['evidence']['failure'] == dict(phase='admission', code='controls_fixture_invalid', callback_errors=[])
    assert len(created) == len(workers) == 1 and closed == created
    assert sip.isdeleted(created[0])
    assert all(sip.isdeleted(worker) or not worker.isRunning() for worker in workers)
    assert qapplication_session.activeModalWidget() is None
    assert result['facets']['controls_cleanup'] == 'passed'
    assert result['evidence']['cleanup'] == dict(joined=True, closed=True, temporary_data_removed=True, sources_unchanged=True, observer_errors=[])
    assert not (root / 'controls-uiux').exists() and not capture.metadata


def test_real_controls_and_shared_capture_leaf(qapplication_session, tmp_path, monkeypatch):
    _gates(monkeypatch)
    fixtures = _stage(tmp_path)
    root = tmp_path / 'output'
    root.mkdir()
    session = checks.make_capture(root, expected_dpr=qapplication_session.primaryScreen().devicePixelRatio())
    result = checks.run_controls_checks(root, fixtures,
                                       expected_dpr=qapplication_session.primaryScreen().devicePixelRatio(), capture=session)
    (root / 'controls-observation.json').write_text(json.dumps(result, indent=2)+'\n')
    (root / 'capture-observation.json').write_text(json.dumps(session.snapshot(require_complete=False), indent=2)+'\n')
    _closed(result)
    assert result['status'] == 'passed', result
    assert result['facets'] == dict.fromkeys(checks.FACETS, 'passed')
    assert result['error_codes'] == [] and result['evidence']['failure'] is None
    evidence = result['evidence']
    assert evidence['routes'] == {'pages': ['home', 'reports', 'csv_summary', 'industrial_data', 'realtime_monitor'], 'same_csv': True}
    assert evidence['owners'] == dict(csv=True, industrial=True, realtime=True, profiles=True)
    assert set(evidence['report_tab']) == {'initial', 'ready', 'busy', 'review', 'result', 'import'}
    for stage in ('initial', 'ready', 'busy', 'review', 'result'):
        row = evidence['report_tab'][stage]
        assert set(row) == {'forward', 'reverse', 'controls', 'worker_running'}
        assert tuple(control['id'] for control in row['controls']) == checks.TAB_IDS
        assert row['forward'] == list(checks.TAB_CHAINS[stage])
        assert row['forward'] == [control['id'] for control in row['controls'] if control['enabled'] and control['visible']]
        assert row['reverse'] == list(reversed(['navigation'] + row['forward'][:-1]))
        assert row['worker_running'] == (stage == 'busy')
    assert evidence['report_tab']['import']['name'] == 'REF001_0001.pdf'
    assert evidence['report_tab']['import']['reports'] == 1 and evidence['report_tab']['import']['measurements'] == 144
    assert evidence['text_guards']['columns'] == [[], ['line'], [], ['line'], []]
    assert evidence['modal_keys'] == dict(parent_enabled_before=True, save='accepted', close='rejected',
                                          parent_starts=0, parent_closes=0, return_focus=True, selected_metrics=['value'])
    assert evidence['compact_dialogs']['reports_filter']['size'] == [720, 480]
    assert evidence['compact_dialogs']['parser_profiles']['size'] == [620, 560]
    assert len(evidence['compact_dialogs']['reports_filter']['tabs']) == 3
    assert len(evidence['compact_dialogs']['parser_profiles']['tabs']) == 2
    assert set(session.metadata) == set(evidence['captures']) == {'active-child-modal'}
    assert session.observations['active-child-modal']['status'] == 'passed'
    assert evidence['cleanup'] == dict(joined=True, closed=True, temporary_data_removed=True, sources_unchanged=True, observer_errors=[])
    assert not (root / 'controls-uiux').exists()
    assert len(json.dumps(result).encode()) + len(json.dumps(session.snapshot(require_complete=False)).encode()) <= 48 * 1024

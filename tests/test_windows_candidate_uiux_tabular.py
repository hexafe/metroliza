"""Closed tabular acceptance contracts; the functional case uses real Qt/workers/files."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from metroliza.app import windows_candidate_uiux_tabular as checks

FIXTURES = Path(__file__).parent / 'fixtures/windows_uiux/tabular'
EXPECTED_FACETS = {
    'csv_single_owner', 'csv_busy_resume', 'csv_db_independence', 'csv_outputs', 'filter_scope',
    'grouping_identity', 'grouping_apply_cancel_reset', 'bounded_reads', 'cleanup', 'captures',
}
EXPECTED_CAPTURES = {'csv-busy', 'csv-resumed', 'grouping-members', 'filter-scope', 'output-summary'}


def _closed(observation):
    assert set(observation) == {'schema_version', 'status', 'facets', 'error_codes', 'evidence'}
    assert observation['schema_version'] == 1 and observation['status'] in {'PASS', 'FAIL'}
    assert set(observation['facets']) == EXPECTED_FACETS
    assert all(value in {'passed', 'failed'} for value in observation['facets'].values())
    assert all(code in checks.ERROR_CODES for code in observation['error_codes'])
    evidence = observation['evidence']
    assert set(evidence) == {'fixture_hashes', 'csv', 'filter', 'grouping', 'captures', 'cleanup', 'failure'}
    if evidence['failure'] is not None:
        assert set(evidence['failure']) == {'phase', 'type', 'callback_errors'}
    if observation['status'] != 'PASS':
        assert observation['error_codes']
        return
    assert not observation['error_codes'] and evidence['failure'] is None
    assert all(value == 'passed' for value in observation['facets'].values())
    assert set(evidence['captures']) == EXPECTED_CAPTURES
    for name, capture in evidence['captures'].items():
        assert set(capture) == {'path', 'sha256', 'width', 'height', 'dpr'}
        assert capture['path'] == f'uiux-{name}.png'
    assert set(evidence['csv']) == {
        'source_rows', 'rows', 'values', 'identifiers', 'dates', 'metric_summary', 'same_owner', 'same_worker',
        'same_request', 'database_independent', 'database_hashes', 'request', 'outputs',
    }
    assert set(evidence['csv']['request']) == {
        'source', 'reference_column', 'timestamp_column', 'metrics', 'filter_column', 'selected_values',
        'filter_expression', 'grouping_count',
    }
    assert set(evidence['csv']['metric_summary']) == {'n', 'mean', 'min', 'max'}
    assert set(evidence['csv']['outputs']) == {'html', 'xlsx'}
    assert all(set(record) == {'path', 'sha256'} for record in evidence['csv']['outputs'].values())
    assert set(evidence['filter']) == {'row_counts', 'selected_values', 'hidden_selected', 'cancel_preserved', 'reset_applied'}
    assert set(evidence['grouping']) == {
        'removed', 'unassigned', 'assigned_g1', 'assigned_g0', 'counts', 'source_rows',
        'applied_assignment_sha256', 'cancel_preserved', 'reset_preserved', 'no_date', 'member_reads',
    }
    assert all(set(row) == {'columns', 'filter_columns', 'limit', 'keys', 'rows'} for row in evidence['grouping']['member_reads'])
    assert set(evidence['cleanup']) == {'joined', 'stores_removed', 'closed', 'source_hashes_unchanged', 'observer_errors'}


def test_tabular_acceptance_import_and_missing_gate_are_lazy(tmp_path):
    code = '''
import json, sys
from metroliza.app.windows_candidate_uiux_tabular import run_tabular_checks
r = run_tabular_checks('.', '.', expected_dpr=1, capture=None)
assert r['status'] == 'FAIL' and r['error_codes'] == ['tabular_gate_missing']
assert not any(n == 'PyQt6' or n.startswith('PyQt6.') or n.startswith('metroliza.ui.') for n in sys.modules)
print(json.dumps(r))
'''
    environment = os.environ.copy()
    environment.pop('METROLIZA_STARTUP_SMOKE', None)
    environment.pop('METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION', None)
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([sys.executable, '-c', code], env=environment, cwd=Path(__file__).parents[1],
                            capture_output=True, text=True, timeout=10, check=True)
    observation = json.loads(result.stdout)
    _closed(observation)
    assert observation['evidence']['captures'] == {}


def test_prepared_tabular_fixture_and_literal_oracles_are_independent():
    assert set(path.name for path in FIXTURES.iterdir()) == {'analysis.csv', 'grouping.csv', 'saved-groups.csv', 'oracles.json'}
    actual = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in FIXTURES.iterdir()}
    assert actual == checks.FIXTURE_HASHES
    oracle = json.loads((FIXTURES / 'oracles.json').read_text())
    assert oracle['schema_version'] == 1
    assert oracle['files'] == {name: actual[name] for name in ('analysis.csv', 'grouping.csv', 'saved-groups.csv')}
    with (FIXTURES / 'analysis.csv').open(newline='') as stream:
        small = list(csv.DictReader(stream))
    assert len(small) == 8
    east = [row for row in small if row['Line'] == 'East']
    assert [row['Operator lot code'] for row in east] == oracle['small']['identifiers'] == ['LOT-1', 'LOT-3', 'LOT-5', 'LOT-7']
    assert [row['Captured at'] for row in east] == oracle['small']['dates'] == ['2026-01-01', '2026-01-03', '2026-01-05', '2026-01-07']
    assert [int(row['Value']) for row in east] == oracle['small']['values'] == [10, 30, 50, 70]
    with (FIXTURES / 'grouping.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3000
    assert rows[0]['Operator lot code'] == rows[12]['Operator lot code'] == 'DUP-1212'
    assert rows[24]['Operator lot code'] == '' and rows[12]['Captured at'] == ''
    assert rows[0]['Captured at'] == '2026-01-01' and rows[24]['Captured at'] == '2026-01-03'
    with (FIXTURES / 'saved-groups.csv').open(newline='') as stream:
        groups = list(csv.DictReader(stream))
    assert [int(row['REPORT_ID']) for row in groups] == list(range(1, 3001))
    assert all(sum(row['GROUP'] == f'G-{i:03d}' for row in groups) == 250 for i in range(12))
    applied = [[int(row['REPORT_ID']), 'G-001' if int(row['REPORT_ID']) in (1, 13) else row['GROUP']] for row in groups]
    assert hashlib.sha256(json.dumps(applied, separators=(',', ':')).encode()).hexdigest() == oracle['grouping']['applied_assignment_sha256']
    assert oracle['grouping']['applied_assignment_sha256'] == 'c2a4e82a66f2784c6d820d6ccf6cf8bbd67ae5b20a8313fc345c11cedb83646e'
    assert not any(token in (FIXTURES / 'grouping.csv').read_text() for token in ('/home/', '\\Users\\'))


def _gates(monkeypatch):
    monkeypatch.setenv('METROLIZA_STARTUP_SMOKE', '1')
    monkeypatch.setenv('METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION', '1')


def test_capture_is_required_without_loading_ui(tmp_path, monkeypatch):
    _gates(monkeypatch)
    result = checks.run_tabular_checks(tmp_path, FIXTURES, expected_dpr=1, capture=None)
    _closed(result)
    assert result['error_codes'] == ['tabular_capture_failed']


def test_modified_fixture_is_closed_failure_before_ui_or_capture(tmp_path, monkeypatch):
    _gates(monkeypatch)
    fixtures = tmp_path / 'altered'
    shutil.copytree(FIXTURES, fixtures)
    with (fixtures / 'analysis.csv').open('a') as stream:
        stream.write('WRONG,2026-01-09,East,999\n')
    def unreachable(*_args):
        pytest.fail('Corrupt fixture must fail before capture')
    result = checks.run_tabular_checks(tmp_path, fixtures, expected_dpr=1, capture=unreachable)
    _closed(result)
    assert result['error_codes'] == ['tabular_fixture_invalid']


def test_unjoined_native_exit_is_not_swallowed_by_closed_projection(tmp_path, monkeypatch):
    from metroliza.app.windows_candidate_native_check import _UnjoinedNativeOwner
    _gates(monkeypatch)
    cleanup = []
    class AbortOnly:
        """Protocol fault injection only: creates no UI, worker or business outcome."""
        def __init__(self, *_args):
            pass
        def csv_journey(self):
            raise _UnjoinedNativeOwner()
        def cleanup(self):
            cleanup.append(True)
    monkeypatch.setattr(checks, '_Journey', AbortOnly)
    with pytest.raises(SystemExit) as result:
        checks.run_tabular_checks(tmp_path, FIXTURES, expected_dpr=1, capture=lambda *_args: None)
    assert result.value.code == 22 and cleanup == [True]


def test_actual_tabular_journeys_and_real_source_capture_contract(qapplication_session, tmp_path, monkeypatch):
    _gates(monkeypatch)
    states = {}
    dpr = qapplication_session.primaryScreen().devicePixelRatio()
    def capture(name, widget, expected_state):
        assert name in EXPECTED_CAPTURES and name not in states and widget.isVisible()
        states[name] = expected_state
        image = widget.grab()  # Actual synthetic owned QWidget, never desktop/mock bitmap.
        path = tmp_path / f'uiux-{name}.png'
        assert image.save(str(path))
        return {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'width': image.width(), 'height': image.height(), 'dpr': image.devicePixelRatio()}
    result = checks.run_tabular_checks(tmp_path, FIXTURES, expected_dpr=dpr, capture=capture)
    (tmp_path / 'tabular-observation.json').write_text(json.dumps(result, indent=2)+'\n')
    (tmp_path / 'capture-scope.json').write_text(json.dumps({'implementation': 'real source-test QWidget.grab',
                                                          'shared_capture_host_integration': 'NOT_RUN'}, indent=2)+'\n')
    _closed(result)
    assert result['status'] == 'PASS', {key: result[key] for key in ('status', 'facets', 'error_codes', 'evidence')}
    evidence = result['evidence']
    assert evidence['csv']['source_rows'] == 8 and evidence['csv']['rows'] == 4
    assert evidence['csv']['values'] == [10, 30, 50, 70]
    assert evidence['csv']['identifiers'] == ['LOT-1', 'LOT-3', 'LOT-5', 'LOT-7']
    assert evidence['csv']['dates'] == ['2026-01-01', '2026-01-03', '2026-01-05', '2026-01-07']
    assert evidence['csv']['metric_summary'] == {'n': 4, 'mean': 40, 'min': 10, 'max': 70}
    assert evidence['csv']['request'] == {
        'source': 'analysis.csv', 'reference_column': 'operator_lot_code', 'timestamp_column': 'captured_at',
        'metrics': ['value'], 'filter_column': 'line', 'selected_values': ['East'], 'filter_expression': '', 'grouping_count': 0,
    }
    assert evidence['filter']['row_counts'] == [8, 4, 4, 8, 4]
    assert evidence['grouping']['removed'] == [1, 25, 37, 49, 61]
    assert evidence['grouping']['unassigned'] == [13]
    assert evidence['grouping']['assigned_g0'] == [25, 37, 49, 61, 73]
    assert evidence['grouping']['assigned_g1'] == [1, 2, 13, 14, 26]
    assert evidence['grouping']['counts'] == {f'G-{i:03d}': 248 if i == 0 else 252 if i == 1 else 250 for i in range(12)}
    assert set(states) == EXPECTED_CAPTURES and evidence['cleanup'] == {
        'joined': True, 'stores_removed': True, 'closed': True, 'source_hashes_unchanged': True, 'observer_errors': [],
    }
    for record in evidence['captures'].values():
        assert hashlib.sha256((tmp_path / record['path']).read_bytes()).hexdigest() == record['sha256']
    from openpyxl import load_workbook
    workbook = load_workbook(tmp_path / 'tabular/analysis.xlsx', read_only=True, data_only=True)
    try:
        rows = list(workbook['Table Data'].values)
        assert [row[list(rows[0]).index('value')] for row in rows[1:]] == [10, 30, 50, 70]
    finally:
        workbook.close()

"""Exercise the real synthetic qualification workloads and fail-closed oracles."""

from contextlib import closing
import json
import shutil
import zipfile

import pytest

from metroliza.app import compute_worker_qualification as workload
from scripts import qualify_windows_compute_workers as host


def test_large_real_import_and_extended_export_match_with_workers_on_and_off(tmp_path, monkeypatch):
    workload.write_reports(tmp_path / 'reports')
    results = []
    for enabled in (False, True):
        trial = tmp_path / str(enabled)
        trial.mkdir()
        monkeypatch.setenv('METROLIZA_IMPORT_PREPARE_WORKERS', '2' if enabled else '0')
        monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MP', '1' if enabled else '0')
        imported = workload.run_import(tmp_path / 'reports', trial / 'result.sqlite3')
        assert set(imported['stage_seconds']) == {'preflight', 'prepare', 'persist', 'other_pipeline'}
        assert all(value >= 0 for value in imported['stage_seconds'].values())
        assert imported['stage_seconds']['preflight'] > 0
        assert imported['stage_seconds']['prepare'] > 0
        assert imported['stage_seconds']['persist'] > 0
        assert imported['total_seconds'] >= imported['seconds']
        exported = workload.run_export(trial / 'result.sqlite3', trial / 'result.xlsx')
        payload = {'import': imported, 'export': exported, 'packaged': True}
        host.validate_usage(payload, enabled)
        results.append((host.database_rows(trial / 'result.sqlite3'), host.workbook_parts(trial / 'result.xlsx')))
    assert results[0] == results[1]
    rows, parts = results[0]
    assert len(rows['parsed_reports']) == 200
    assert sum(name.endswith('.png') for name in parts) >= 40
    # Both content comparisons must detect a real change, not merely matching counts.
    database = tmp_path / 'False/result.sqlite3'
    import sqlite3
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('UPDATE report_measurements SET meas=meas+1 WHERE id=1')
    assert host.database_rows(database) != rows
    workbook = tmp_path / 'False/result.xlsx'
    copy = tmp_path / 'changed.xlsx'
    shutil.copyfile(workbook, copy)
    with zipfile.ZipFile(copy, 'a') as archive:
        archive.writestr('unexpected-part', b'changed')
    assert host.workbook_parts(copy) != parts


def test_usage_rejects_silent_serial_fallback_and_unfrozen_results():
    good = {'packaged': True, 'import': {'imported': 200, 'hydrated': 200, 'seconds': 1.0},
            'export': {'seconds': 1.0, 'pool': {'mode': 'spawn', 'workers': 2, 'completed': 39}}}
    host.validate_usage(good, True)
    for changed in (
        {**good, 'packaged': False},
        {**good, 'import': {**good['import'], 'hydrated': 199}},
        {**good, 'export': {**good['export'], 'pool': {'mode': 'serial_pool_failure'}}},
    ):
        with pytest.raises(ValueError):
            host.validate_usage(changed, True)
    with pytest.raises(ValueError):
        host.validate_usage(good, False)


def test_runner_retains_failure_receipt_off_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(host.sys, 'platform', 'linux')
    receipt = tmp_path / 'receipt.json'
    assert host.main(['--artifact-dir', str(tmp_path), '--receipt', str(receipt)]) == 1
    payload = json.loads(receipt.read_text())
    assert payload['passed'] is False and 'native_windows_required' in payload['failure']
    assert payload['failure_stage'] == 'platform'


def test_workload_requires_explicit_smoke_gate(monkeypatch):
    monkeypatch.delenv('METROLIZA_STARTUP_SMOKE', raising=False)
    with pytest.raises(ValueError, match='gate_required'):
        workload.run_qualification()


def test_read_only_database_oracle_quotes_schema_identifiers(tmp_path):
    import sqlite3

    database = tmp_path / 'synthetic.sqlite3'
    hostile = 'x"; DROP TABLE parsed_reports; --'
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('CREATE TABLE parsed_reports (id INTEGER PRIMARY KEY)')
        connection.executemany('INSERT INTO parsed_reports VALUES (?)', [(index,) for index in range(200)])
        connection.execute('CREATE TABLE report_measurements (header TEXT, ax TEXT)')
        connection.executemany('INSERT INTO report_measurements VALUES (?, ?)', [(str(index), 'X') for index in range(40)])
        # The name is a fixed adversarial fixture. The production oracle must
        # read it as one quoted identifier rather than executing its SQL text.
        connection.execute('CREATE TABLE "x""; DROP TABLE parsed_reports; --" (value TEXT)')
        connection.execute('INSERT INTO "x""; DROP TABLE parsed_reports; --" VALUES (?)', ('synthetic',))
    rows = host.database_rows(database)
    assert len(rows['parsed_reports']) == 200
    assert rows[hostile] == [('synthetic',)]


def test_import_observation_measures_stages_and_restores_hooks_on_failure(monkeypatch):
    from metroliza.parsing.cmm_report_parser import CMMReportParser
    from metroliza.parsing.import_prepare_pool import ImportPreparePool
    from metroliza.parsing import parse_reports_thread as pipeline

    now = [0.0]

    def advance(seconds):
        now[0] += seconds

    def parse(*args, **kwargs):
        kwargs['parser_factory']()
        CMMReportParser.prepare_for_two_stage_pipeline(None)
        ImportPreparePool.apply_to(None, None, None)
        CMMReportParser.apply_prepared_state(None, None)
        kwargs['persist_report'](None)
        raise ValueError('synthetic_failure')

    monkeypatch.setattr(workload.time, 'perf_counter', lambda: now[0])
    monkeypatch.setattr(CMMReportParser, 'prepare_for_two_stage_pipeline', lambda parser: advance(2))
    monkeypatch.setattr(ImportPreparePool, 'apply_to', lambda *args: advance(3))
    def original_apply(*args):
        return None
    monkeypatch.setattr(CMMReportParser, 'apply_prepared_state', original_apply)
    monkeypatch.setattr(pipeline, 'parse_new_reports', parse)
    timings, hydrated = {'prepare': 0.0, 'persist': 0.0}, []
    with pytest.raises(ValueError, match='synthetic_failure'), workload._observe_import(timings, hydrated):
        pipeline.parse_new_reports(parser_factory=lambda: advance(1), persist_report=lambda parser: advance(4))
    assert timings == {'prepare': 6, 'persist': 4}
    assert hydrated == [True]
    assert pipeline.parse_new_reports is parse
    assert CMMReportParser.apply_prepared_state is original_apply


def test_topology_failure_retains_run_stage_workload_and_audit_before_cleanup(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from scripts import qualify_windows_diagnostics as diagnostics
    from scripts import windows_owned_process_probe as probe

    event = {'caller': 'other', 'kind': 'other_command', 'phase': 'after_ready'}
    closed = []
    proof = {'events': [event], 'owned': {'job_empty': True}}

    class Evidence:
        def __init__(self, *args, **kwargs):
            pass

        def proof(self):
            assert not closed
            return proof

    def reject_topology(*args, **kwargs):
        raise diagnostics.QualificationFailure('output_failed')

    process = SimpleNamespace(poll=lambda: 0, topology=reject_topology, close=lambda **kwargs: closed.append(True))
    monkeypatch.setattr(probe, 'RuntimeEvidence', Evidence)
    monkeypatch.setattr(diagnostics, '_WindowsApi', lambda: SimpleNamespace(launch=lambda *args, **kwargs: process))
    monkeypatch.setattr(host, '_wait_for_trial', lambda *args: None)
    monkeypatch.setattr(host, 'validate_usage', lambda *args: None)
    monkeypatch.setattr(host, 'build_environment', lambda *args, **kwargs: {})

    def qualify(artifact, receipt):
        trial = tmp_path / 'trial'
        run = {'index': 0, 'enabled': True}
        receipt.update(stage='trial', runs=[run])
        # launch_trial creates the directory. Supply the completed app payload
        # at the launch boundary, just as the real supervised app does.
        def launch(*args, **kwargs):
            (trial / 'compute.json').write_text(json.dumps({'import': {'seconds': 72.6}}))
            return process
        monkeypatch.setattr(diagnostics, '_WindowsApi', lambda: SimpleNamespace(launch=launch))
        host.launch_trial(artifact, trial, tmp_path, tmp_path, True, result=run)

    monkeypatch.setattr(host, 'qualify', qualify)
    monkeypatch.setattr(host.sys, 'platform', 'win32')
    receipt_path = tmp_path / 'receipt.json'
    assert host.main(['--artifact-dir', str(tmp_path), '--receipt', str(receipt_path)]) == 1
    receipt = json.loads(receipt_path.read_text())
    assert receipt['failure'] == 'QualificationFailure:output_failed'
    assert receipt['failure_stage'] == 'topology'
    assert receipt['failure_run'] == {'index': 0, 'enabled': True}
    run = receipt['runs'][0]
    assert run['import']['seconds'] == 72.6
    assert run['runtime_audit'] == {'status': 'observed', 'events': [event]}
    assert run['runtime_evidence']['owned']['job_empty'] is True
    assert closed == [True]
    printed = capsys.readouterr().out
    assert '"failure_stage": "topology"' in printed and 'other_command' in printed


def test_failure_receipt_omits_uncontrolled_exception_text():
    receipt = {'stage': 'fixture', 'runs': []}
    host._record_failure(receipt, ValueError('private synthetic path C:/private'))
    assert receipt['failure'] == 'ValueError'
    assert receipt['failure_stage'] == 'fixture'


def test_qualify_registers_failed_trial_before_launch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from metroliza.shared import diagnostic_package

    monkeypatch.setattr(diagnostic_package, 'inspect_package', lambda artifact: SimpleNamespace(valid=True, git_sha='a' * 40))
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    (tmp_path / 'supervision_manifest.json').write_text('{}')
    monkeypatch.setattr(host, 'write_reports', lambda source: None)
    receipt = {'passed': False, 'runs': []}

    def fail(*args, result, **kwargs):
        assert receipt['runs'] == [result]
        result['stage'] = 'workload'
        result['runtime_audit'] = {'status': 'unavailable'}
        raise ValueError('compute_timeout')

    monkeypatch.setattr(host, 'launch_trial', fail)
    with pytest.raises(ValueError) as caught:
        host.qualify(tmp_path, receipt)
    host._record_failure(receipt, caught.value)
    assert receipt['passed'] is False
    assert receipt['failure_stage'] == 'workload'
    assert receipt['failure_run'] == {'index': 0, 'enabled': False}
    assert receipt['runs'][0]['runtime_audit']['status'] == 'unavailable'


# run_qualification() creates the process' QApplication in a local variable when none exists;
# the session fixture keeps one alive so a later module never sees a second application (#1119).
@pytest.mark.usefixtures("qapplication_session")
def test_qualification_uses_parent_version_policy_without_harness_override(tmp_path, monkeypatch):
    from metroliza.shared import compute_worker, diagnostic_runtime_audit

    calls = []
    monkeypatch.setenv('METROLIZA_STARTUP_SMOKE', '1')
    monkeypatch.setenv(workload.GATE, str(tmp_path))
    monkeypatch.setattr(compute_worker, 'use_native_windows_version', lambda: pytest.fail('qualification must use the production parent policy'))
    monkeypatch.setattr(diagnostic_runtime_audit, 'wait_for_host_ready', lambda **kwargs: None)

    def imported(*args):
        assert calls == []
        calls.append('import')
        return {'seconds': 1}

    def exported(*args):
        assert calls == ['import']
        calls.append('export')
        return {'seconds': 2}

    monkeypatch.setattr(workload, 'run_import', imported)
    monkeypatch.setattr(workload, 'run_export', exported)
    assert workload.run_qualification() == 0
    assert calls == ['import', 'export']
    assert json.loads((tmp_path / 'compute.json').read_text())['import']['seconds'] == 1

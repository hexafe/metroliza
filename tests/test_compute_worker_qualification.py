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

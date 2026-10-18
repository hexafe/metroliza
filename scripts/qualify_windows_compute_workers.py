"""Qualify both pools in the real supervised onedir, forced on/off, three times.

The existing launcher/envelope qualification remains a separate CI gate. This
runner uses the same built onedir (metroliza.exe -> application -> compute),
restricted token, kill-on-close Job, native image probe and runtime journal.
Only aggregate synthetic evidence is retained; temporary reports/DBs are removed.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import statistics
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from metroliza.app.compute_worker_qualification import GROUPS, REPORTS, write_reports  # noqa: E402
from scripts.measure_windows_startup_routes import build_environment  # noqa: E402

# Persistence wall clocks only; source signatures, IDs, metadata, paths and hashes
# are deliberately included. This is the same exclusion as the import-pool oracle.
WALL_CLOCK_COLUMNS = {
    'parsed_reports': {'parse_started_at', 'parse_finished_at', 'created_at', 'updated_at'},
    'report_metadata_candidates': {'created_at'}, 'report_metadata_warnings': {'created_at'},
    'report_parse_state': {'updated_at'}, 'source_files': {'discovered_at', 'ingested_at'},
    'source_file_locations': {'discovered_at'},
}


def database_rows(database: Path) -> dict:
    with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        result = {}
        for (table,) in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info({quoted})')
                       if row[1] not in WALL_CLOCK_COLUMNS.get(table, set())]
            selected = ', '.join('"' + column.replace('"', '""') + '"' for column in columns)
            result[table] = connection.execute(f'SELECT {selected} FROM {quoted} ORDER BY rowid').fetchall()
        groups = connection.execute(
            'SELECT COUNT(*) FROM (SELECT header, ax FROM report_measurements GROUP BY header, ax)').fetchone()[0]
        if groups < GROUPS or len(result['parsed_reports']) != REPORTS:
            raise ValueError('compute_fixture_size_invalid')
    return result


def workbook_parts(workbook: Path) -> dict:
    with zipfile.ZipFile(workbook) as archive:
        result = {}
        for name in archive.namelist():
            data = archive.read(name)
            if name == 'docProps/core.xml':
                data = re.sub(rb'<dcterms:(created|modified)[^>]*>.*?</dcterms:\1>', b'', data)
            result[name] = hashlib.sha256(data).hexdigest()
        if sum(name.endswith('.png') for name in result) < GROUPS:
            raise ValueError('compute_workbook_images_missing')
    return result


def validate_usage(payload: dict, enabled: bool) -> None:
    imported, pool = payload['import'], payload['export']['pool']
    if payload.get('packaged') is not True or imported['imported'] != REPORTS:
        raise ValueError('compute_packaged_import_required')
    if enabled:
        if (imported['hydrated'] != REPORTS or pool.get('mode') != 'spawn'
                or pool.get('workers') != 2 or pool.get('completed', 0) < GROUPS - 1):
            raise ValueError('compute_workers_not_used')
    elif imported['hydrated'] != 0 or pool.get('workers') != 0 or pool.get('completed') != 0:
        raise ValueError('compute_serial_not_used')
    for value in (imported['seconds'], payload['export']['seconds']):
        if type(value) not in (float, int) or not 0 < value < 900:
            raise ValueError('compute_timing_invalid')


def launch_trial(artifact: Path, trial: Path, state: Path, temp: Path, enabled: bool) -> dict:
    from scripts.qualify_windows_diagnostics import _WindowsApi, QualificationFailure, _topology_record
    from scripts.windows_owned_process_probe import RuntimeEvidence

    trial.mkdir()
    environment = build_environment(state, temp, trial / 'unused-profile', offscreen=True)
    environment.pop('METROLIZA_STARTUP_UI_SMOKE', None)
    environment.pop('METROLIZA_STARTUP_PROFILE', None)
    environment.update({
        'METROLIZA_STARTUP_SMOKE': '1', 'METROLIZA_COMPUTE_QUALIFICATION_ROOT': str(trial),
        'METROLIZA_IMPORT_PREPARE_WORKERS': '2' if enabled else '0',
        'METROLIZA_IMPORT_PREPARE_MIN_REPORTS': '200',
        'METROLIZA_EXPORT_GROUP_MP': '1' if enabled else '0',
        'METROLIZA_EXPORT_GROUP_MIN_GROUPS': '40', 'METROLIZA_EXPORT_GROUP_WORKERS': '2',
    })
    api = _WindowsApi()
    evidence = RuntimeEvidence(api, artifact, trial, environment,
                              lambda: QualificationFailure('output_failed'), compute_workers=4 if enabled else 0)
    images = (artifact / 'metroliza.exe', artifact / 'metroliza_application.exe')
    if enabled:
        images += (artifact / 'metroliza_compute_worker.exe',)
    process = None
    started = time.monotonic()
    try:
        process = api.launch(images[0], environment, trial, expected_images=images, runtime_evidence=evidence)
        deadline = started + 900
        while time.monotonic() < deadline:
            process.observe()
            if (trial / 'compute-ready').is_file():
                process.mark_runtime_ready()
            if process.poll() is not None and process.active_processes() == 0:
                break
            time.sleep(0.01)
        else:
            raise ValueError('compute_timeout')
        if process.poll() != 0:
            raise ValueError('compute_application_failed')
        topology = _topology_record(process.topology(artifact, all_exited=True))
        payload = json.loads((trial / 'compute.json').read_text(encoding='utf-8'))
        validate_usage(payload, enabled)
        payload.update(topology=topology, wall_seconds=time.monotonic() - started)
        return payload
    finally:
        if process is not None:
            process.close(terminate=True)
        else:
            # API launch owns cleanup after it starts; this close is idempotent
            # only for successful root ownership still present before launch.
            if evidence.root.exists():
                evidence.close()


def qualify(artifact: Path, receipt: dict) -> None:
    from metroliza.shared.diagnostic_package import inspect_package

    identity = inspect_package(artifact)
    if not identity.valid:
        raise ValueError('compute_package_identity_invalid')
    receipt.update(git_sha=identity.git_sha,
                   manifest_sha256=hashlib.sha256((artifact / 'supervision_manifest.json').read_bytes()).hexdigest())
    with tempfile.TemporaryDirectory(prefix='metroliza-compute-') as directory:
        root = Path(directory)
        state, temp = root / 'state', root / 'temp'
        (state / 'Roaming').mkdir(parents=True)
        temp.mkdir()
        write_reports(root / 'reports')
        expected_rows = expected_parts = None
        for index in range(3):
            for enabled in ((False, True) if index % 2 == 0 else (True, False)):
                trial = root / f'{index}-{int(enabled)}'
                payload = launch_trial(artifact, trial, state, temp, enabled)
                receipt['runs'].append(dict(index=index, enabled=enabled, **payload))
                rows = database_rows(trial / 'result.sqlite3')
                parts = workbook_parts(trial / 'result.xlsx')
                if expected_rows is None:
                    expected_rows, expected_parts = rows, parts
                if rows != expected_rows or parts != expected_parts:
                    raise ValueError('compute_outputs_differ')
                if any(path.name.startswith('_MEI') for path in temp.iterdir()):
                    raise ValueError('compute_extraction_remained')
    receipt['comparison'] = 'all_database_rows_and_workbook_parts_equal_except_persistence_and_document_clocks'
    receipt['medians_seconds'] = {
        mode: {stage: statistics.median(run[stage]['seconds'] for run in receipt['runs'] if run['enabled'] == enabled)
               for stage in ('import', 'export')}
        for mode, enabled in (('serial', False), ('workers', True))}
    receipt['speedup'] = {stage: receipt['medians_seconds']['serial'][stage] / receipt['medians_seconds']['workers'][stage]
                          for stage in ('import', 'export')}
    receipt['windows_default_measurement'] = {'groups': GROUPS, 'reports': REPORTS, 'workers': 2,
                                             'scope': 'hosted_runner_boundary_workloads_only'}
    receipt['passed'] = True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = {'schema_version': 1, 'passed': False, 'runs': [],
               'load_average': list(os.getloadavg()) if hasattr(os, 'getloadavg') else 'unavailable_on_windows',
               'processor_count': os.cpu_count()}
    try:
        if sys.platform != 'win32':
            raise ValueError('native_windows_required')
        qualify(args.artifact_dir.resolve(), receipt)
    except Exception as error:
        receipt['failure'] = type(error).__name__ + ':' + str(error) if isinstance(error, ValueError) else type(error).__name__
    finally:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Independent UIUX oracle/retention protocol controls, never UI/EXE proof."""
from __future__ import annotations

import binascii
from contextlib import closing
import hashlib
from functools import lru_cache
from tempfile import TemporaryDirectory
from pathlib import Path
import shutil
import sqlite3
import struct
import zipfile
import zlib

import pytest

from scripts import verify_windows_candidate_uiux as uiux

FIXTURES = Path(__file__).parent / 'fixtures/windows_uiux'


def png_bytes(width=64, height=64):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', binascii.crc32(kind + body) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + b'\0' * width * 4) * height)) + chunk(b'IEND', b''))


def test_authored_png_structure_and_exact_half_pixel_size(tmp_path):
    path = tmp_path / 'uiux-reports-saved-top.png'
    path.write_bytes(png_bytes(783, 503))
    metadata = dict(path=path.name, sha256=uiux.sha(path), width=783, height=503, dpr=1.25)
    uiux.png(path, metadata, 1.25)
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.png(path, dict(metadata, width=782, height=502), 1.25)


@pytest.mark.parametrize('defect', ['signature', 'crc', 'trailing', 'missing_iend', 'bool_width', 'bool_dpr', 'wrong_sha', 'extra'])
def test_png_manifest_or_bytes_cannot_claim_validity(tmp_path, defect):
    path = tmp_path / 'uiux-reports-saved-top.png'
    data = png_bytes()
    if defect == 'signature':
        data = b'badstart' + data[8:]
    elif defect == 'crc':
        data = data[:30] + bytes([data[30] ^ 1]) + data[31:]
    elif defect == 'trailing':
        data += b'unknown'
    elif defect == 'missing_iend':
        data = data[:-12]
    path.write_bytes(data)
    metadata = dict(path=path.name, sha256=uiux.sha(path), width=64, height=64, dpr=1.0)
    change = {'bool_width': ('width', True), 'bool_dpr': ('dpr', True),
              'wrong_sha': ('sha256', '0' * 64), 'extra': ('ignored', True)}.get(defect)
    if change is not None:
        metadata[change[0]] = change[1]
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.png(path, metadata, 1.0)


def _create_report_databases(root):
    """Real authored PDF parsing; numeric expectations remain the independent oracle."""
    from metroliza.parsing.cmm_report_parser import CMMReportParser
    from scripts import qualify_windows_candidate_core as core
    pdf = root / 'pdf'
    pdf.mkdir()
    oracle = uiux.load_json(FIXTURES / 'reports/oracles.json')
    with zipfile.ZipFile(FIXTURES / 'reports/reports-12.zip') as archive:
        for member in oracle['members']:
            data = archive.read(member['name'])
            assert hashlib.sha256(data).hexdigest() == member['sha256']
            (pdf / member['name']).write_bytes(data)
    databases = {}
    for case in ('A', 'B', 'C'):
        path = root / (case + '.sqlite')
        names = [item['name'] for item in oracle['members'] if
                 not (case == 'B' and item['name'] == 'REF006_0006.pdf')
                 and not (case == 'C' and item['name'] != 'REF001_0001.pdf')]
        for name in names:
            CMMReportParser(str(pdf / name), str(path), metadata_parsing_mode='light').import_report_if_absent()
        core._inert_import_guard_sidecars(path, 'unexpected_fixture_sidecars')
        retained = root / ('retained-' + case + '.sqlite')
        shutil.copyfile(path, retained)
        databases[case] = retained, names
    return oracle, databases


@pytest.fixture(scope='module')
def real_report_databases(tmp_path_factory):
    return _create_report_databases(tmp_path_factory.mktemp('uiux-real-sql'))


def test_independent_sql_oracle_reads_all_actual_reports_and_preserves_bytes(real_report_databases):
    oracle, databases = real_report_databases
    for path, names in databases.values():
        before = path.read_bytes()
        logical = uiux.database(path, oracle, set(names))
        assert len(logical) == 64 and path.read_bytes() == before
        assert not any(path.with_name(path.name + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))


@pytest.mark.parametrize('defect', ['measurement', 'metadata', 'source_identity', 'extra_measurement', 'orphan_source', 'active_sidecar'])
def test_actual_sql_mutation_rejects_even_if_producer_claims_passed(tmp_path, real_report_databases, defect):
    oracle, databases = real_report_databases
    original, names = databases['A']
    path = tmp_path / 'reports.sqlite'
    shutil.copyfile(original, path)
    if defect == 'active_sidecar':
        path.with_name(path.name + '-wal').write_bytes(b'not inert')
    else:
        with closing(sqlite3.connect(path)) as connection:
            if defect == 'measurement':
                connection.execute('UPDATE report_measurements SET meas=999 WHERE id=(SELECT MIN(id) FROM report_measurements)')
            elif defect == 'metadata':
                connection.execute("UPDATE report_metadata SET reference='changed' WHERE report_id=1")
            elif defect == 'source_identity':
                connection.execute("UPDATE source_files SET sha256=? WHERE id=1", ('0' * 64,))
            elif defect == 'extra_measurement':
                connection.execute('INSERT INTO report_measurements(report_id,row_order) VALUES(1,999)')
            else:
                connection.execute("INSERT INTO source_files(sha256,source_format,discovered_at) VALUES(?,'pdf','2026')", ('a' * 64,))
            connection.commit()
    before = path.read_bytes()
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.database(path, oracle, set(names))
    assert path.read_bytes() == before


@pytest.mark.parametrize('payload', ['{"a":1,"a":2}', '{"number":NaN}', '{"number":Infinity}'])
def test_duplicate_or_nonfinite_json_rejected(tmp_path, payload):
    path = tmp_path / 'observation.json'
    path.write_text(payload)
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.load_json(path)


def reports_observation(*, packaged=True, dpr=1.0):
    """Complete authored protocol fixture; not a claimed application execution."""
    oracle = uiux.load_json(FIXTURES / 'reports/oracles.json')
    evidence = {'fixture_hashes': {Path(n).name: h for n, h in uiux.FIXTURES.items() if n.startswith('reports/')},
        'context': {'execution': 'packaged' if packaged else 'source', 'platform': 'windows' if packaged else 'offscreen',
                    'dpr': dpr, 'screen': [1920, 1080], 'available_screen': [1920, 1032]},
        'summaries': {}, 'captures': {},
        'cleanup': {'joined': True, 'closed': True, 'sources_unchanged': True, 'callback_errors': []}, 'failure': None}
    for case in 'ABC':
        expected = oracle['scenarios'][case]
        rows, receipts, digests = [], {}, {}
        for report in sorted(oracle['expected']['reports'].values(), key=lambda item: item['name']):
            name = report['name']
            state = 'failed' if case == 'B' and name == 'REF006_0006.pdf' else (
                'unknown' if case == 'C' and name != 'REF001_0001.pdf' else 'saved')
            rows.append(dict(name=name, occurrence_id=name, state=state, readonly=True, attention=state != 'saved'))
            if state != 'unknown':
                receipts[name] = state
            if state == 'saved':
                digests[name] = report['measurements_sha256']
        context = dict.fromkeys(('same_owner', 'same_result', 'approval_invalidated', 'worker_running_at_cancel',
            'first_accepted', 'cancel_clicked', 'cancel_flag', 'released', 'terminal', 'barrier_expired'), False)
        context.update(first_accepted=None, released=True, terminal=True)
        if case == 'A':
            context.update(same_owner=True, same_result=True, approval_invalidated=True)
        if case == 'C':
            context.update(worker_running_at_cancel=True, first_accepted='REF001_0001.pdf', cancel_clicked=True, cancel_flag=True)
        evidence[case] = {'review_counts': {'ready': 12, 'duplicate': 0, 'selected': 12},
            'batch_counts': {'saved': expected['saved'], 'failed': expected['failed'], 'cancelled': expected['cancelled'], 'total': 12},
            'row_facts': rows, 'receipt_states': receipts,
            'database_counts': {'parsed_reports': expected['saved'], 'report_metadata': expected['saved'], 'report_measurements': 144 * expected['saved']},
            'numeric_digests': digests, 'rereview_counts': {'ready': 12 - expected['saved'], 'duplicate': expected['saved'], 'selected': 12 - expected['saved']},
            'context': context, 'preservation': {'destination_logical_sha256': 'a' * 64, 'rereview_unchanged': True, 'seed_unchanged': True, 'sources_unchanged': True}}
        snapshot = dict(width=752, height=28, hfw=28, minimum_hint=14, word_wrap=True,
                        contained=True, overlap=False, visible=True, window_size=[768, 740])
        evidence['summaries'][case] = {'immediate': dict(snapshot, height=14), 'queued': snapshot}
    evidence['captures'] = {name: dict(path='uiux-' + name + '.png', sha256='b' * 64, width=768, height=740, dpr=dpr)
                            for name in uiux.CAPTURES[:4]}
    return {'schema_version': 1, 'status': 'passed',
            'facets': {'reports_' + name: 'passed' for name in uiux.REPORT_FACETS}, 'error_codes': [], 'evidence': evidence}


def test_independent_reports_schema_accepts_only_declared_complete_facts():
    value = reports_observation()
    oracle = uiux.load_json(FIXTURES / 'reports/oracles.json')
    assert uiux.reports(value, oracle, packaged=True, dpr=1.0, qpa='windows') is value['evidence']


@pytest.mark.parametrize('defect', ['missing', 'extra', 'not_assessed', 'bool_count', 'wrong_count', 'identity',
    'receipt', 'digest', 'saved_database', 'cancel', 'readonly', 'summary', 'source_lane', 'wrong_dpr', 'failure'])
def test_literal_reports_facts_reject_mutation_despite_passed_string(defect):
    value = reports_observation()
    evidence = value['evidence']
    if defect == 'missing':
        del evidence['A']['context']['same_owner']
    elif defect == 'extra':
        evidence['A']['ignored'] = True
    elif defect == 'not_assessed':
        value['facets']['reports_twelve_import'] = 'not_assessed'
    elif defect == 'bool_count':
        evidence['C']['batch_counts']['saved'] = True
    elif defect == 'wrong_count':
        evidence['B']['batch_counts']['failed'] = 0
    elif defect == 'identity':
        evidence['A']['row_facts'][0]['occurrence_id'] = 'REF002_0002.pdf'
    elif defect == 'receipt':
        evidence['C']['receipt_states']['REF002_0002.pdf'] = 'saved'
    elif defect == 'digest':
        evidence['A']['numeric_digests']['REF001_0001.pdf'] = '0' * 64
    elif defect == 'saved_database':
        evidence['B']['database_counts']['report_measurements'] = 1728
    elif defect == 'cancel':
        evidence['C']['context']['cancel_clicked'] = False
    elif defect == 'readonly':
        evidence['A']['row_facts'][0]['readonly'] = False
    elif defect == 'summary':
        evidence['summaries']['A']['queued']['height'] = 14
    elif defect == 'source_lane':
        evidence['context']['execution'] = 'source'
    elif defect == 'wrong_dpr':
        evidence['context']['dpr'] = 1.25
    else:
        evidence['failure'] = {'phase': 'A', 'type': 'unexpected_exception'}
    oracle = uiux.load_json(FIXTURES / 'reports/oracles.json')
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.reports(value, oracle, packaged=True, dpr=1.0, qpa='windows')


@pytest.mark.parametrize('defect', ['extra', 'missing', 'changed', 'symlink'])
def test_separate_uiux_staging_never_relaxes_known_fixture_set(tmp_path, defect):
    from scripts import qualify_windows_candidate_core as core
    checkout = tmp_path / 'checkout'
    source = checkout / 'tests/fixtures/windows_uiux'
    shutil.copytree(FIXTURES, source)
    if defect == 'extra':
        (source / 'reports/unowned.pdf').write_bytes(b'unknown')
    elif defect == 'missing':
        (source / 'tabular/analysis.csv').unlink()
    elif defect == 'changed':
        (source / 'tabular/analysis.csv').write_bytes(b'changed')
    else:
        (source / 'reports/reports-12.zip').unlink()
        (source / 'reports/reports-12.zip').symlink_to(FIXTURES.resolve() / 'reports/reports-12.zip')
    staged = tmp_path / 'staged'
    staged.mkdir()
    with pytest.raises(core.CandidateFailure, match='^prepared_uiux_fixture_invalid$'):
        core._stage_uiux_fixtures(checkout, staged)
    assert not (staged / 'uiux').exists()


def test_separate_uiux_staging_preserves_all_six_inputs_and_old_w13_set(tmp_path):
    from scripts import qualify_windows_candidate_core as core
    old = dict(core.PUBLIC_FIXTURE_HASHES)
    staged = tmp_path / 'staged'
    staged.mkdir()
    core._stage_uiux_fixtures(Path(__file__).resolve().parents[1], staged)
    assert core.PUBLIC_FIXTURE_HASHES == old and len(old) == 7
    assert {p.relative_to(staged / 'uiux').as_posix() for p in (staged / 'uiux').rglob('*') if p.is_file()} == set(uiux.FIXTURES)
    assert {name: uiux.sha(staged / 'uiux' / name) for name in uiux.FIXTURES} == uiux.FIXTURES


def _authored_workbook(path):
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = 'Table Data'
    sheet.append(['operator_lot_code', 'captured_at', 'line', 'value'])
    for identifier, day, value in zip(('LOT-1', 'LOT-3', 'LOT-5', 'LOT-7'), (1, 3, 5, 7), (10, 30, 50, 70), strict=True):
        sheet.append([identifier, f'2026-01-{day:02d}', 'East', value])
    metrics = book.create_sheet('Metrics')
    metrics.append(['n', 'mean', 'min', 'max'])
    metrics.append([4, 40, 10, 70])
    book.save(path)
    book.close()


def test_authored_workbook_oracle_preserves_input_bytes(tmp_path):
    path = tmp_path / 'analysis.xlsx'
    _authored_workbook(path)
    before = path.read_bytes()
    uiux.workbook(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize('defect', ['identity', 'date', 'value', 'mean', 'extra_row'])
def test_workbook_readback_rejects_wrong_actual_cells(tmp_path, defect):
    from openpyxl import load_workbook
    path = tmp_path / 'analysis.xlsx'
    _authored_workbook(path)
    book = load_workbook(path)
    try:
        if defect == 'identity':
            book['Table Data']['A2'] = 'LOT-2'
        elif defect == 'date':
            book['Table Data']['B2'] = '2026-01-02'
        elif defect == 'value':
            book['Table Data']['D2'] = 999
        elif defect == 'mean':
            book['Metrics']['B2'] = 999
        else:
            book['Table Data'].append(['LOT-extra', '2026-01-01', 'East', 10])
        book.save(path)
    finally:
        book.close()
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.workbook(path)


def _partial_capture_assets(root):
    name = 'reports-saved-top'
    path = root / ('uiux-' + name + '.png')
    path.write_bytes(png_bytes())
    captures = {name: dict(path=path.name, sha256=uiux.sha(path), width=64, height=64, dpr=1.0)}
    return captures, dict.fromkeys(uiux.DATA)


def test_bounded_partial_asset_snapshot_is_not_success_manifest(tmp_path):
    captures, data = _partial_capture_assets(tmp_path)
    snapshot = uiux.snapshot_assets(tmp_path, captures, data, dpr=1.0, diagnostic=True)
    assert set(snapshot) == {'uiux-reports-saved-top.png'}
    assert snapshot['uiux-reports-saved-top.png'] == png_bytes()
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.manifest(captures, data, dpr=1.0)


@pytest.mark.parametrize('defect', ['extra_capture', 'unsafe_path', 'duplicate_path', 'bool_size', 'total_bound'])
def test_partial_retention_never_accepts_arbitrary_or_unbounded_asset(tmp_path, monkeypatch, defect):
    captures, data = _partial_capture_assets(tmp_path)
    if defect == 'extra_capture':
        captures['unowned'] = dict(captures['reports-saved-top'])
    elif defect == 'unsafe_path':
        data['csv_html'] = {'path': '../unowned.html', 'sha256': 'a' * 64, 'size': 1}
    elif defect == 'duplicate_path':
        captures['reports-saved-bottom'] = dict(captures['reports-saved-top'])
    elif defect == 'bool_size':
        data['csv_html'] = {'path': 'tabular/analysis.html', 'sha256': 'a' * 64, 'size': True}
    else:
        assert uiux.MAX_TOTAL == 32 * 1024 * 1024
        monkeypatch.setattr(uiux, 'MAX_TOTAL', len(png_bytes()) - 1)
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.snapshot_assets(tmp_path, captures, data, dpr=1.0, diagnostic=True)


def test_oversized_xlsx_declaration_is_rejected_before_openpyxl(tmp_path, monkeypatch):
    import openpyxl
    path = tmp_path / 'oversized.xlsx'
    _authored_workbook(path)
    contents = bytearray(path.read_bytes())
    offset = contents.index(b'PK\x01\x02')
    struct.pack_into('<I', contents, offset + 24, 8 * 1024 * 1024 + 1)
    path.write_bytes(contents)
    opened = []
    def forbidden(*_args, **_kwargs):
        opened.append(True)
        raise AssertionError('Unbounded XLSX must not reach XML parsing')
    monkeypatch.setattr(openpyxl, 'load_workbook', forbidden)
    with pytest.raises(uiux.UiuxVerificationFailure, match='^uiux_xlsx_container$'):
        uiux.workbook(path)
    assert opened == []


def _authored_html():
    charts = ''.join(f'<section id="chart-{name}-value"></section>' for name in ('time-series', 'histogram', 'violin', 'box'))
    return ('<!doctype html><html><head><title>Metroliza CSV Summary Dashboard</title>'
            '<script src="analysis_assets/plotly-2.27.0.min.js"></script></head><body>'
            '<header id="dashboard-start">analysis.csv</header><details id="run-notes">'
            'Rows rendered 4 Metrics 1 Filters Applied CSV/Excel row filter reduced rows from 8 to 4.'
            ' Min 10.000 Max 70.000 Mean 40.000 Samples 4</details>' + charts + '</body></html>')


def test_static_html_oracle_preserves_authored_input(tmp_path):
    path = tmp_path / 'analysis.html'
    path.write_text(_authored_html())
    before = path.read_bytes()
    uiux.html(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize('defect', ['row_count', 'mean', 'hidden_markers', 'external_script', 'missing_chart', 'extra_chart'])
def test_html_requires_literal_text_outside_scripts_and_known_local_resources(tmp_path, defect):
    path = tmp_path / 'analysis.html'
    text = _authored_html()
    if defect == 'row_count':
        text = text.replace('Rows rendered 4', 'Rows rendered 5')
    elif defect == 'mean':
        text = text.replace('Mean 40.000', 'Mean 999.000')
    elif defect == 'hidden_markers':
        text = text.replace('Rows rendered 4', '<script>Rows rendered 4</script>')
    elif defect == 'external_script':
        text = text.replace('analysis_assets/plotly-2.27.0.min.js', 'https://invalid.example/plotly.js')
    elif defect == 'missing_chart':
        text = text.replace('id="chart-box-value"', 'id="missing-box"')
    else:
        text += '<section id="chart-extra-value"></section>'
    path.write_text(text)
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.html(path)


def capture_observation_fixture(dpr=1.25):
    """Typed protocol fixture, not a real QWidget capture or package proof."""
    metadata, observations = {}, {}
    for name, state in uiux.CAPTURE_STATES.items():
        if name.startswith('reports-'):
            ids = ['navigation', 'summary', 'table', 'outcome']
        elif name in ('csv-busy', 'csv-resumed', 'output-summary'):
            ids = ['start', 'close', 'metrics', 'dashboard_path', 'workbook_path']
        elif name == 'grouping-members':
            ids = ['apply', 'cancel', 'member-row-1', 'member-row-13', 'member-row-25']
        elif name == 'filter-scope':
            ids = ['apply', 'cancel', 'matching', 'selection_summary']
        else:
            ids = ['apply', 'cancel', 'search', 'metrics']
        physical = [783, 503]
        metadata[name] = dict(path='uiux-' + name + '.png', sha256='a' * 64,
                              width=physical[0], height=physical[1], dpr=dpr)
        controls = [dict(id=identifier, bounds=[0, index * 40, 100, 36], visible=True, enabled=True,
                        focusable=True, in_window=True, in_viewport=True) for index, identifier in enumerate(ids)]
        observations[name] = dict(status='passed', expected_state=dict(state), observed_state=dict(state),
            window=dict(logical_rect=[0, 0, 626, 402], physical_size=physical, dpr=dpr), controls=controls, error_codes=[])
    return dict(status='passed', metadata=metadata, observations=observations, error_codes=[])


def test_capture_session_protocol_accepts_qt_half_pixel_scaling():
    value = capture_observation_fixture()
    assert uiux.capture_session(value, dpr=1.25) is value


@pytest.mark.parametrize('defect', ['missing_image', 'extra_image', 'failed_state', 'expected_mismatch', 'observed_mismatch',
    'python_round', 'off_window', 'off_viewport', 'small_target', 'bool_dimension', 'unknown_control', 'error_code'])
def test_capture_session_rejects_semantic_and_geometry_waivers(defect):
    value = capture_observation_fixture()
    record = value['observations']['active-child-modal']
    if defect == 'missing_image':
        del value['metadata']['csv-busy']
    elif defect == 'extra_image':
        value['metadata']['arbitrary'] = dict(value['metadata']['csv-busy'])
    elif defect == 'failed_state':
        record['status'] = 'failed'
    elif defect == 'expected_mismatch':
        record['expected_state']['selected_metrics'] = 2
    elif defect == 'observed_mismatch':
        record['observed_state']['parent_no_start'] = False
    elif defect == 'python_round':
        record['window']['physical_size'] = [782, 502]
    elif defect == 'off_window':
        record['controls'][0]['bounds'][0] = 999
    elif defect == 'off_viewport':
        record['controls'][0]['in_viewport'] = False
    elif defect == 'small_target':
        record['controls'][0]['bounds'][3] = 20
    elif defect == 'bool_dimension':
        record['window']['logical_rect'][2] = True
    elif defect == 'unknown_control':
        record['controls'][0]['id'] = 'unowned'
    else:
        record['error_codes'] = ['capture_state_failed']
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.capture_session(value, dpr=1.25)


def tabular_observation(dpr=1.0):
    capture = capture_observation_fixture(dpr)['metadata']
    return dict(schema_version=1, status='passed', facets=dict.fromkeys(uiux.TABULAR_FACETS, 'passed'), error_codes=[],
        evidence=dict(fixture_hashes={Path(n).name: h for n, h in uiux.FIXTURES.items() if n.startswith('tabular/')},
            csv=dict(source_rows=8, rows=4, values=[10, 30, 50, 70], identifiers=['LOT-1', 'LOT-3', 'LOT-5', 'LOT-7'],
                dates=['2026-01-01', '2026-01-03', '2026-01-05', '2026-01-07'],
                metric_summary=dict(n=4, mean=40., min=10., max=70.), same_owner=True, same_worker=True,
                same_request=True, database_independent=True, database_hashes=['a' * 64, 'a' * 64],
                request=dict(source='analysis.csv', reference_column='operator_lot_code', timestamp_column='captured_at',
                    metrics=['value'], filter_column='line', selected_values=['East'], filter_expression='', grouping_count=0),
                outputs={ext: dict(path='tabular/analysis.' + ext, sha256='a' * 64) for ext in ('html', 'xlsx')}),
            filter=dict(row_counts=[8, 4, 4, 8, 4], selected_values=['East'], hidden_selected=1, cancel_preserved=True, reset_applied=True),
            grouping=dict(removed=[1, 25, 37, 49, 61], unassigned=[13], assigned_g1=[1, 2, 13, 14, 26],
                assigned_g0=[25, 37, 49, 61, 73], source_rows=3000,
                counts={f'G-{i:03d}': 248 if i == 0 else 252 if i == 1 else 250 for i in range(12)},
                applied_assignment_sha256='c2a4e82a66f2784c6d820d6ccf6cf8bbd67ae5b20a8313fc345c11cedb83646e',
                cancel_preserved=True, reset_preserved=True, no_date=True,
                member_reads=[dict(columns=['source_row_number', 'operator_lot_code', 'captured_at'],
                                   filter_columns=['source_row_number'], limit=1000, keys=250, rows=250)]),
            captures={name: capture[name] for name in uiux.CAPTURES[4:9]},
            cleanup=dict(joined=True, stores_removed=True, closed=True, source_hashes_unchanged=True, observer_errors=[]), failure=None))


def controls_observation(dpr=1.0):
    report = uiux.load_json(FIXTURES / 'reports/oracles.json')
    compact = {}
    for name, definition in uiux.COMPACT_ORACLE.items():
        tabs = []
        for spec in definition['tabs']:
            tab = dict(index=spec['index'], vertical=dict(minimum=0, maximum=0, before=0, after=0), horizontal_max=0)
            for field in ('pinned', 'body'):
                tab[field] = [dict(id=identifier, bounds=[0, index * 40, 100, 36], visible=True, enabled=True,
                                  focusable=True, in_window=index * 40 + 36 <= definition['size'][1], in_viewport=True)
                              for index, identifier in enumerate(spec[field])]
            tab['wrapped'] = [dict(id=identifier, height=28, required=28) for identifier in spec['wrapped']]
            tabs.append(tab)
        compact[name] = dict(size=list(definition['size']), tabs=tabs)
    tab = {name: dict(forward=list(value['forward']), reverse=list(value['reverse']), worker_running=name == 'busy',
                     controls=[dict(id=identifier, visible=visible, enabled=enabled)
                        for identifier, visible, enabled in zip(uiux.TAB_IDS, value['visible'], value['enabled'], strict=True)])
           for name, value in uiux.TAB_ORACLE.items()}
    report = next(r for r in report['expected']['reports'].values() if r['name'] == 'REF001_0001.pdf')
    tab['import'] = dict(name=report['name'], reports=1, measurements=144, measurements_sha256=report['measurements_sha256'])
    return dict(schema_version=1, status='passed', facets=dict.fromkeys(uiux.CONTROL_FACETS, 'passed'), error_codes=[],
        evidence=dict(context=dict(execution='packaged', qpa='windows', dpr=dpr, screen=[1920, 1080], available_screen=[1920, 1032]),
            routes=dict(pages=['home', 'reports', 'csv_summary', 'industrial_data', 'realtime_monitor'], same_csv=True),
            owners=dict.fromkeys(('csv', 'industrial', 'realtime', 'profiles'), True), report_tab=tab,
            text_guards=dict(editing=dict(select_all='er', after_copy='er', after_cut='', after_paste='er',
                after_undo_paste='', after_undo_cut='er', literal='er'), columns=[[], ['line'], [], ['line'], []],
                modifier_unchanged=True, repeat_unchanged=True, composition_unchanged=True, parent_unchanged=True),
            modal_keys=dict(parent_enabled_before=True, save='accepted', close='rejected', parent_starts=0,
                            parent_closes=0, return_focus=True, selected_metrics=['value']),
            compact_dialogs=compact, captures={'active-child-modal': capture_observation_fixture(dpr)['metadata']['active-child-modal']},
            cleanup=dict(joined=True, closed=True, temporary_data_removed=True, sources_unchanged=True, observer_errors=[]), failure=None))


def wrapper_observation(source='1' * 40, dpr=1.0):
    session = capture_observation_fixture(dpr)
    for record in session['metadata'].values():
        record['width'], record['height'] = [int(n * dpr + .5) for n in (626, 402)]
    for record in session['observations'].values():
        record['window']['physical_size'] = [int(n * dpr + .5) for n in (626, 402)]
    reports = reports_observation(dpr=dpr)
    reports['evidence']['captures'] = {name: session['metadata'][name] for name in uiux.CAPTURES[:4]}
    tabular, controls = tabular_observation(dpr), controls_observation(dpr)
    tabular['evidence']['captures'] = {name: session['metadata'][name] for name in uiux.CAPTURES[4:9]}
    controls['evidence']['captures'] = {'active-child-modal': session['metadata']['active-child-modal']}
    return dict(schema_version=1, status='passed', runtime_context='packaged', error_codes=[],
        facets=dict.fromkeys(('reports', 'tabular', 'controls', 'captures'), 'passed'),
        evidence=dict(context=dict(source_sha=source, qpa='windows', dpr=dpr), reports=reports,
                      tabular=tabular, controls=controls, captures=session,
                      data={name: dict(path=relative, sha256='a' * 64, size=1) for name, relative in uiux.DATA.items()}))


def test_wrapper_schema_requires_all_original_leaf_facts_and_frozen_tab_vectors():
    oracle = uiux.load_json(FIXTURES / 'reports/oracles.json')
    value = wrapper_observation()
    uiux.validate(value, oracle, source='1' * 40, packaged=True, dpr=1.0, qpa='windows')
    # Independent semantic expectations, rather than accepting arbitrary observed flags.
    ready = value['evidence']['controls']['evidence']['report_tab']['ready']
    assert ready['forward'] == ['directory_path', 'directory', 'archive', 'database_path', 'database', 'metadata_mode',
        'review', 'search', 'status', 'parser', 'attention', 'table', 'details_button', 'modify', 'mapping', 'export']
    assert ready['controls'][6] == dict(id='review', visible=True, enabled=True)
    assert ready['controls'][18] == dict(id='import', visible=True, enabled=False)


@pytest.mark.parametrize('defect', ['source', 'qpa', 'dpr', 'extra', 'summary', 'missing_capture', 'tab_flag', 'tab_order',
    'modifier', 'editing', 'parent_start', 'compact_id', 'compact_clip', 'wrapped', 'group_id', 'request', 'metric'])
def test_wrapper_rejects_closed_identity_and_literal_control_mutations(defect):
    value = wrapper_observation()
    controls = value['evidence']['controls']['evidence']
    if defect in ('source', 'qpa', 'dpr'):
        value['evidence']['context'][{'source': 'source_sha', 'qpa': 'qpa', 'dpr': 'dpr'}[defect]] = {'source': '2' * 40, 'qpa': 'offscreen', 'dpr': 1.25}[defect]
    elif defect == 'extra':
        value['unknown'] = True
    elif defect == 'summary':
        value['evidence']['controls'] = dict(kind='failure_summary', phase='keys', code='unexpected_exception', error_codes=['unexpected_exception'])
    elif defect == 'missing_capture':
        del value['evidence']['captures']['metadata']['csv-busy']
    elif defect == 'tab_flag':
        controls['report_tab']['ready']['controls'][18]['enabled'] = True
    elif defect == 'tab_order':
        controls['report_tab']['result']['reverse'].reverse()
    elif defect == 'modifier':
        controls['text_guards']['modifier_unchanged'] = False
    elif defect == 'editing':
        controls['text_guards']['editing']['after_undo_cut'] = ''
    elif defect == 'parent_start':
        controls['modal_keys']['parent_starts'] = 1
    elif defect == 'compact_id':
        controls['compact_dialogs']['reports_filter']['tabs'][0]['pinned'][0]['id'] = 'unknown'
    elif defect == 'compact_clip':
        controls['compact_dialogs']['parser_profiles']['tabs'][1]['pinned'][-1]['in_viewport'] = False
    elif defect == 'wrapped':
        controls['compact_dialogs']['parser_profiles']['tabs'][1]['wrapped'][0]['height'] = 14
    elif defect == 'group_id':
        value['evidence']['tabular']['evidence']['grouping']['unassigned'] = [1]
    elif defect == 'request':
        value['evidence']['tabular']['evidence']['csv']['request']['selected_values'] = ['West']
    else:
        value['evidence']['tabular']['evidence']['csv']['metric_summary']['mean'] = 999.
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.validate(value, uiux.load_json(FIXTURES / 'reports/oracles.json'), source='1' * 40, packaged=True, dpr=1.0, qpa='windows')


def diagnostic_observation():
    value = wrapper_observation()
    value.update(status='failed', error_codes=['uiux_reports_failed'])
    value['facets'] = dict.fromkeys(value['facets'], 'failed')
    value['evidence'].update(reports=dict(kind='failure_summary', phase='B', code='reports_invariant_failed',
        error_codes=['reports_invariant_failed']), tabular=None, controls=None, data=dict.fromkeys(uiux.DATA),
        captures=dict(status='failed', metadata={}, observations={}, error_codes=[]))
    return value


@pytest.mark.parametrize('defect', ['phase', 'code', 'keys'])
def test_diagnostic_summary_rejects_unknown_details_and_never_satisfies_success(defect):
    value = diagnostic_observation()
    oracle = uiux.load_json(FIXTURES / 'reports/oracles.json')
    uiux.diagnostic(value, oracle, source='1' * 40, packaged=True, dpr=1.0, qpa='windows')
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.validate(value, oracle, source='1' * 40, packaged=True, dpr=1.0, qpa='windows')
    summary = value['evidence']['reports']
    summary[{'phase': 'phase', 'code': 'code', 'keys': 'raw'}[defect]] = 'PRIVATE_PATH'
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.diagnostic(value, oracle, source='1' * 40, packaged=True, dpr=1.0, qpa='windows')




@lru_cache(maxsize=1)
def _protocol_data_bytes():
    """One real parse, then bounded immutable protocol bytes reused across four-run fixtures."""
    with TemporaryDirectory(prefix='uiux-protocol-') as temporary:
        root = Path(temporary)
        oracle, databases = _create_report_databases(root)
        assets, logical = {}, {}
        for case, (path, names) in databases.items():
            assets['reports_' + case] = path.read_bytes()
            logical[case] = uiux.database(path, oracle, set(names))
        assets['reports_seed'] = assets['reports_A']
        workbook = root / 'analysis.xlsx'
        _authored_workbook(workbook)
        assets['csv_xlsx'] = workbook.read_bytes()
        assets['csv_html'] = _authored_html().encode()
        assets['csv_plotly'] = (Path(__file__).resolve().parents[1] /
            'src/metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js').read_bytes()
        assert hashlib.sha256(assets['csv_plotly']).hexdigest() == '7f4930eba8f8541dbec28dca5bd5f787f8eef1cde0369ac9657b70bed230b3e0'
        return assets, logical


def write_complete_uiux(root, *, source='1' * 40, dpr=1.0):
    """Authored protocol/real SQL fixture only; never real UI or package proof."""
    import json
    value = wrapper_observation(source, dpr)
    assets, logical = _protocol_data_bytes()
    for name, content in assets.items():
        path = root / uiux.DATA[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        value['evidence']['data'][name] = dict(path=uiux.DATA[name], sha256=uiux.sha(path), size=len(content))
    for case in 'ABC':
        value['evidence']['reports']['evidence'][case]['preservation']['destination_logical_sha256'] = logical[case]
    for name, record in value['evidence']['captures']['metadata'].items():
        path = root / record['path']
        path.write_bytes(png_bytes(record['width'], record['height']))
        record['sha256'] = uiux.sha(path)
        leaf = 'reports' if name in uiux.CAPTURES[:4] else 'tabular' if name in uiux.CAPTURES[4:9] else 'controls'
        value['evidence'][leaf]['evidence']['captures'][name] = dict(record)
    for ext in ('html', 'xlsx'):
        record = value['evidence']['data']['csv_' + ext]
        value['evidence']['tabular']['evidence']['csv']['outputs'][ext] = {key: record[key] for key in ('path', 'sha256')}
    (root / 'uiux-observation.json').write_text(json.dumps(value), encoding='utf-8')
    return value


def test_complete_retained_assets_are_independently_read_and_hash_preserved(tmp_path):
    value = write_complete_uiux(tmp_path)
    before = {path: (tmp_path / path).read_bytes() for path in uiux.manifest(value['evidence']['captures']['metadata'], value['evidence']['data'], dpr=1.0)}
    uiux.verify(tmp_path, value, uiux.load_json(FIXTURES / 'reports/oracles.json'),
                source='1' * 40, packaged=True, dpr=1.0, qpa='windows')
    assert all((tmp_path / path).read_bytes() == contents for path, contents in before.items())
    assert len(before) == 17


@pytest.mark.parametrize('defect', ['plotly', 'png', 'workbook', 'database', 'data_path', 'missing_data'])
def test_complete_retained_assets_cannot_be_replaced_by_passed_strings(tmp_path, defect):
    value = write_complete_uiux(tmp_path)
    data = value['evidence']['data']
    if defect == 'data_path':
        data['csv_html']['path'] = '../analysis.html'
    elif defect == 'missing_data':
        del data['csv_plotly']
    elif defect == 'png':
        (tmp_path / 'uiux-active-child-modal.png').write_bytes(b'changed')
    else:
        name = dict(plotly='csv_plotly', workbook='csv_xlsx', database='reports_A')[defect]
        path = tmp_path / data[name]['path']
        if defect == 'database':
            with closing(sqlite3.connect(path)) as writer:
                writer.execute('UPDATE report_measurements SET meas=999 WHERE id=1')
                writer.commit()
        else:
            path.write_bytes(b'changed')
        data[name].update(sha256=uiux.sha(path), size=path.stat().st_size)
    with pytest.raises((uiux.UiuxVerificationFailure, zipfile.BadZipFile)):
        uiux.verify(tmp_path, value, uiux.load_json(FIXTURES / 'reports/oracles.json'),
                    source='1' * 40, packaged=True, dpr=1.0, qpa='windows')


def _producer_protocol(monkeypatch, root, *, failed=None):
    import sys
    from types import SimpleNamespace
    from metroliza.app import windows_candidate_qualification as producer
    from metroliza.app import windows_candidate_uiux_reports as report_module
    from metroliza.app import windows_candidate_uiux_tabular as tabular_module
    import PyQt6.QtWidgets
    value = write_complete_uiux(root)
    session = SimpleNamespace(snapshot=lambda **_kw: value['evidence']['captures'])
    session.__call__ = lambda *_args: None
    def result(name):
        record = value['evidence'][name]
        if name == failed:
            record.update(status='failed', error_codes=[name + '_invariant_failed'])
            record['evidence']['failure'] = dict(phase='B' if name == 'reports' else 'keys', code=name + '_invariant_failed')
        return record
    monkeypatch.setattr(report_module, 'run_reports_checks', lambda *_a, **_kw: result('reports'))
    monkeypatch.setattr(tabular_module, 'run_tabular_checks', lambda *_a, **_kw: result('tabular'))
    monkeypatch.setitem(sys.modules, 'metroliza.app.windows_candidate_uiux_controls', SimpleNamespace(
        make_capture=lambda *_a, **_kw: session, run_controls_checks=lambda *_a, **_kw: result('controls'),
        ERROR_CODES=uiux.LEAF_ERRORS['controls']))
    monkeypatch.setattr(PyQt6.QtWidgets, 'QApplication', SimpleNamespace(platformName=lambda: 'windows'))
    monkeypatch.setenv('METROLIZA_WINDOWS_CANDIDATE_DPR', '1.0')
    return producer, value


def test_producer_bridge_adds_exact_one_artifact_and_four_facets(monkeypatch, tmp_path):
    producer, _value = _producer_protocol(monkeypatch, tmp_path)
    receipt = dict(packaged=True, source_sha='1' * 40, artifacts={}, facets={})
    producer._run_uiux_slice(tmp_path, FIXTURES.parent, receipt)
    assert receipt['facets'] == dict.fromkeys(('uiux_reports', 'uiux_tabular', 'uiux_controls', 'uiux_captures'), 'passed')
    assert receipt['artifacts'] == {'uiux_evidence': dict(path='uiux-observation.json', sha256=uiux.sha(tmp_path / 'uiux-observation.json'))}
    uiux.verify(tmp_path, uiux.load_json(tmp_path / 'uiux-observation.json'), uiux.load_json(FIXTURES / 'reports/oracles.json'),
                source='1' * 40, packaged=True, dpr=1.0, qpa='windows')


def test_failed_producer_atomically_retains_closed_phase_and_never_marks_uiux_passed(monkeypatch, tmp_path):
    producer, _value = _producer_protocol(monkeypatch, tmp_path, failed='reports')
    receipt = dict(packaged=True, source_sha='1' * 40, artifacts={}, facets={})
    with pytest.raises(producer.ScenarioFailure, match='^uiux_checks_failed$'):
        producer._run_uiux_slice(tmp_path, FIXTURES.parent, receipt)
    assert receipt['artifacts'] == receipt['facets'] == {}
    value = uiux.load_json(tmp_path / 'uiux-observation.json')
    assert value['status'] == 'failed' and value['error_codes'] == ['uiux_reports_failed']
    assert value['evidence']['reports'] == dict(kind='failure_summary', phase='B', code='reports_invariant_failed', error_codes=['reports_invariant_failed'])
    assert value['evidence']['tabular'] is value['evidence']['controls'] is None
    uiux.diagnostic(value, uiux.load_json(FIXTURES / 'reports/oracles.json'), source='1' * 40, packaged=True, dpr=1.0, qpa='windows')


def test_failed_host_retains_known_png_only_after_joined_cleanup_and_stays_failed(tmp_path):
    import json
    from types import SimpleNamespace
    from scripts import qualify_windows_candidate_core as core
    work, output = tmp_path / 'work', tmp_path / 'output'
    work.mkdir()
    child = work / ('core-' + 'a' * 32)
    child.mkdir()
    value = diagnostic_observation()
    captures, _ = _partial_capture_assets(child)
    value['evidence']['captures']['metadata'] = captures
    (child / 'uiux-observation.json').write_text(json.dumps(value))
    args = SimpleNamespace(source_checkout=Path(__file__).resolve().parents[1], expected_source_sha='1' * 40, dpi_scale='1.0')
    observation = {'owned_cleanup': 'complete'}
    core._snapshot_failed_uiux(work, args, observation)
    assert set(observation['uiux_snapshot']) == {'uiux-reports-saved-top.png', 'uiux-observation.json'}
    shutil.rmtree(work)
    output.mkdir()
    core._restore_failed_uiux(output, observation['uiux_snapshot'])
    assert (output / 'uiux-reports-saved-top.png').read_bytes() == png_bytes()
    assert not (output / 'core-driver-receipt.json').exists()
    with pytest.raises(uiux.UiuxVerificationFailure):
        uiux.validate(uiux.load_json(output / 'uiux-observation.json'), uiux.load_json(FIXTURES / 'reports/oracles.json'),
                      source='1' * 40, packaged=True, dpr=1.0, qpa='windows')


@pytest.mark.parametrize('cleanup', ['not_attempted', 'failed'])
def test_unproven_cleanup_does_not_read_or_retain_uiux(tmp_path, cleanup):
    from types import SimpleNamespace
    from scripts import qualify_windows_candidate_core as core
    observation = dict(owned_cleanup=cleanup)
    core._snapshot_failed_uiux(tmp_path / 'absent', SimpleNamespace(), observation)
    assert observation == dict(owned_cleanup=cleanup, uiux_snapshot=None)


def test_invalid_failed_child_path_or_manifest_is_not_retained(tmp_path, capsys):
    import json
    from types import SimpleNamespace
    from scripts import qualify_windows_candidate_core as core
    child = tmp_path / ('core-' + 'a' * 32)
    child.mkdir()
    value = diagnostic_observation()
    value['evidence']['data']['csv_html'] = dict(path='../PRIVATE.html', sha256='a' * 64, size=1)
    (child / 'uiux-observation.json').write_text(json.dumps(value))
    observation = dict(owned_cleanup='complete')
    args = SimpleNamespace(source_checkout=Path(__file__).resolve().parents[1], expected_source_sha='1' * 40, dpi_scale='1.0')
    core._snapshot_failed_uiux(tmp_path, args, observation)
    assert observation['uiux_snapshot'] is None
    assert capsys.readouterr().out == 'uiux_retention=invalid_or_unavailable\n'


def test_uiux_copy_failure_restores_only_original_closed_core_failure(tmp_path, monkeypatch, capsys):
    from scripts import qualify_windows_candidate_core as core
    from tests.test_windows_candidate_exit_evidence import _inventory
    # The original native failure envelope remains the single authority.
    payload = core._failed_diagnostic_payload(dict(owned_cleanup='complete', private_cleanup='complete',
        exit_inventory=_inventory()), {'name': 'uiux_retention'}, core.CandidateFailure('independent_uiux_verification_failed'), '1' * 40)
    core._write_failed_diagnostic(tmp_path, payload)
    def failed_write(output, _snapshot):
        (output / 'partial.json').write_text('{}')
        raise OSError('PRIVATE_PATH')
    monkeypatch.setattr(core, '_write_uiux_snapshot', failed_write)
    core._restore_failed_uiux(tmp_path, {'uiux-observation.json': b'{}'})
    assert {path.name for path in tmp_path.iterdir()} == {core.FAILED_DIAGNOSTIC_FILE}
    assert core._json(tmp_path / core.FAILED_DIAGNOSTIC_FILE) == payload
    assert capsys.readouterr().out == 'uiux_retention=restore_failed\n'


def test_each_reports_flag_is_independently_required_before_any_tab_claim():
    import copy
    oracle = uiux.load_json(FIXTURES / 'reports/oracles.json')
    original = controls_observation()
    for stage in ('initial', 'ready', 'busy', 'review', 'result'):
        for index in range(24):
            for flag in ('visible', 'enabled'):
                value = copy.deepcopy(original)
                record = value['evidence']['report_tab'][stage]['controls'][index]
                record[flag] = not record[flag]
                with pytest.raises(uiux.UiuxVerificationFailure):
                    uiux.controls(value, oracle, packaged=True, dpr=1.0, qpa='windows')


def test_actual_private_inert_sidecars_are_verified_without_changing_bytes(tmp_path):
    value = write_complete_uiux(tmp_path)
    before = {}
    for name in ('reports_A', 'reports_B', 'reports_C', 'reports_seed'):
        path = tmp_path / uiux.DATA[name]
        for suffix, content in (('-wal', b''), ('-shm', b'\0' * 32768)):
            sidecar = path.with_name(path.name + suffix)
            sidecar.write_bytes(content)
            before[sidecar] = content
    oracle = uiux.load_json(FIXTURES / 'reports/oracles.json')
    uiux.verify_assets(tmp_path, value['evidence'], oracle, dpr=1.0, inert=True)
    assert all(path.read_bytes() == content for path, content in before.items())
    with pytest.raises(uiux.UiuxVerificationFailure, match='^uiux_database_active$'):
        uiux.verify_assets(tmp_path, value['evidence'], oracle, dpr=1.0)


@pytest.mark.parametrize('change', ['phase', 'code', 'raised'])
def test_producer_unknown_failure_detail_is_closed_without_losing_reached_leaf(monkeypatch, tmp_path, change):
    from metroliza.app import windows_candidate_uiux_reports as reports
    producer, value = _producer_protocol(monkeypatch, tmp_path)
    record = value['evidence']['reports']
    record.update(status='failed', error_codes=['reports_invariant_failed'])
    record['evidence']['failure'] = dict(phase='B', type='reports_invariant_failed')
    if change == 'phase':
        record['evidence']['failure']['phase'] = 'PRIVATE_PATH'
    elif change == 'code':
        record['error_codes'] = ['PRIVATE_PATH']
    else:
        def unexpected(*_args, **_kwargs):
            raise OSError('PRIVATE_PATH')
        monkeypatch.setattr(reports, 'run_reports_checks', unexpected)
    with pytest.raises(producer.ScenarioFailure, match='^uiux_checks_failed$'):
        producer._run_uiux_slice(tmp_path, FIXTURES.parent, dict(packaged=True, source_sha='1' * 40, artifacts={}, facets={}))
    observed = uiux.load_json(tmp_path / 'uiux-observation.json')
    summary = observed['evidence']['reports']
    assert summary['kind'] == 'failure_summary' and summary['code'] == 'unexpected_exception'
    assert 'PRIVATE_PATH' not in str(observed)
    uiux.diagnostic(observed, uiux.load_json(FIXTURES / 'reports/oracles.json'), source='1' * 40, packaged=True, dpr=1.0, qpa='windows')


def test_completed_component_bytes_survive_failed_host_without_becoming_host_pass(tmp_path):
    from types import SimpleNamespace
    from scripts import qualify_windows_candidate_core as core
    work = tmp_path / 'work'
    child = work / ('core-' + 'a' * 32)
    child.mkdir(parents=True)
    write_complete_uiux(child)
    original = (child / 'uiux-observation.json').read_bytes()
    observation = dict(owned_cleanup='complete')
    args = SimpleNamespace(source_checkout=Path(__file__).resolve().parents[1], expected_source_sha='1' * 40, dpi_scale='1.0')
    core._snapshot_failed_uiux(work, args, observation)
    assert observation['uiux_snapshot']['uiux-observation.json'] == original
    assert len(observation['uiux_snapshot']) == 18  # Exact17assets plus observation, not global artifact keys.
    shutil.rmtree(work)
    output = tmp_path / 'failed'
    output.mkdir()
    payload = core._failed_diagnostic_payload(observation, {'name': 'uiux_retention'}, core.CandidateFailure('independent_uiux_verification_failed'), '1' * 40)
    core._write_failed_diagnostic(output, payload)
    core._restore_failed_uiux(output, observation['uiux_snapshot'])
    assert (output / 'uiux-observation.json').read_bytes() == original
    assert uiux.load_json(output / 'uiux-observation.json')['status'] == 'passed'  # Component only.
    assert core._json(output / core.FAILED_DIAGNOSTIC_FILE)['status'] == 'failed'  # Host remains failed.
    assert not (output / 'core-driver-receipt.json').exists()

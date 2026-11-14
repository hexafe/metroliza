"""Independent, bounded UIUX observations and retained synthetic-data checks.

No application/test imports. A producer's passed string never replaces reading
its retained SQLite databases, workbook and PNG bytes against authored oracles.
"""
from __future__ import annotations

import binascii
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import struct
import zipfile

MAX_JSON = 128 * 1024
MAX_ASSET = 8 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
FIXTURES = {
    'reports/reports-12.zip': '99f2a0af7269e52e82ac60a784e29aa82153a37b72357dc3844019d487c22041',
    'reports/oracles.json': '2ebad1ab90578f926f608e40652c516f36aaa5c55de918228ffd0b735551e1d4',
    'tabular/analysis.csv': '764c2776b85b24c373b094b5095c7e043dee3fa2f3af48fb063781f5f4bbaef0',
    'tabular/grouping.csv': 'b04ea4ba08ee70e6a12e5fd709467ebf3049f21cd252ceea77a738bb9b07fb4e',
    'tabular/saved-groups.csv': '02770298bcb61b07fbc9bee9f0c38b4a86e2a0d8be8815e09ebdf9b31be7e54d',
    'tabular/oracles.json': '0530ba3857abf24863fd4c6faadb5c0a325bbdddd1c4030b0856e68240de451f',
}
DATA = {'reports_A': 'reports-uiux/A.sqlite', 'reports_B': 'reports-uiux/B.sqlite',
        'reports_C': 'reports-uiux/C.sqlite', 'reports_seed': 'reports-uiux/seed.sqlite',
        'csv_html': 'tabular/analysis.html', 'csv_xlsx': 'tabular/analysis.xlsx',
        'csv_plotly': 'tabular/analysis_assets/plotly-2.27.0.min.js'}
PLOTLY_SHA = '7f4930eba8f8541dbec28dca5bd5f787f8eef1cde0369ac9657b70bed230b3e0'
CAPTURES = ('reports-saved-top', 'reports-saved-bottom', 'reports-partial-error',
            'reports-partial-cancel', 'csv-busy', 'csv-resumed', 'grouping-members',
            'filter-scope', 'output-summary', 'active-child-modal')
REPORT_FACETS = ('twelve_import', 'duplicate_rereview', 'database_switch', 'partial_persistence_failure',
                 'cancel_after_first_acceptance', 'historical_identity_readonly', 'summary_layout',
                 'source_preservation', 'captures', 'cleanup')
TABULAR_FACETS = ('csv_single_owner', 'csv_busy_resume', 'csv_db_independence', 'csv_outputs',
                  'filter_scope', 'grouping_identity', 'grouping_apply_cancel_reset', 'bounded_reads',
                  'cleanup', 'captures')
FIELDS = ('row_order', 'header', 'section_name', 'feature_label', 'characteristic_name',
          'characteristic_family', 'description', 'ax', 'nominal', 'tol_plus', 'tol_minus',
          'bonus', 'meas', 'dev', 'outtol', 'is_nok', 'status_code')


class UiuxVerificationFailure(ValueError):
    """Only path-free identifiers leave this verifier."""


def require(condition, code='uiux_invalid_observation'):
    if not condition:
        raise UiuxVerificationFailure(code)


def keys(value, names):
    require(type(value) is dict and set(value) == set(names))
    return value


def literal(value, expected):
    if type(expected) is float:
        require(type(value) in (float, int) and math.isfinite(value) and value == expected)
    else:
        require(type(value) is type(expected))
        if type(expected) is dict:
            keys(value, expected)
            for key in expected:
                literal(value[key], expected[key])
        elif type(expected) in (tuple, list):
            require(len(value) == len(expected))
            for observed, wanted in zip(value, expected, strict=True):
                literal(observed, wanted)
        else:
            require(value == expected)


def digest(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None)


def regular(path):
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and not path.is_symlink()
            and not getattr(metadata, 'st_file_attributes', 0) & 0x400, 'uiux_unsafe_path')
    return metadata.st_size


def asset_path(root, relative):
    require(type(relative) is str and relative in {*DATA.values(), *(f'uiux-{name}.png' for name in CAPTURES)},
            'uiux_unsafe_path')
    path = root
    for part in Path(relative).parts:
        path = path / part
        require(not path.is_symlink() and not getattr(path.lstat(), 'st_file_attributes', 0) & 0x400,
                'uiux_unsafe_path')
    require(0 < regular(path) <= MAX_ASSET, 'uiux_asset_size')
    return path


def sha(path):
    require(0 < regular(path) <= MAX_ASSET, 'uiux_asset_size')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'uiux_duplicate_json_key')
        result[key] = value
    return result


def load_json(path):
    require(0 < regular(path) <= MAX_JSON, 'uiux_json_size')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda _value: require(False))


def load_inputs(root):
    require(root.is_dir() and not root.is_symlink()
            and not getattr(root.lstat(), 'st_file_attributes', 0) & 0x400, 'uiux_fixture_invalid')
    require({p.name for p in root.iterdir()} == {'reports', 'tabular'}, 'uiux_fixture_invalid')
    for leaf in ('reports', 'tabular'):
        require(not (root / leaf).is_symlink()
                and not getattr((root / leaf).lstat(), 'st_file_attributes', 0) & 0x400 and {p.name for p in (root / leaf).iterdir()}
                == {Path(name).name for name in FIXTURES if name.startswith(leaf + '/')}, 'uiux_fixture_invalid')
    require(all(sha(root / name) == value for name, value in FIXTURES.items()), 'uiux_fixture_invalid')
    return load_json(root / 'reports/oracles.json'), load_json(root / 'tabular/oracles.json')


def png(path, metadata, dpr):
    keys(metadata, ('path', 'sha256', 'width', 'height', 'dpr'))
    require(type(metadata['width']) is int and type(metadata['height']) is int
            and 64 <= metadata['width'] <= 8192 and 64 <= metadata['height'] <= 8192)
    literal(metadata['dpr'], float(dpr))
    require(sha(path) == metadata['sha256'], 'uiux_asset_hash')
    data = path.read_bytes()
    require(data[:8] == b'\x89PNG\r\n\x1a\n', 'uiux_png_invalid')
    offset, names = 8, []
    while offset < len(data):
        require(offset + 12 <= len(data), 'uiux_png_invalid')
        length, kind = struct.unpack('>I4s', data[offset:offset + 8])
        require(length <= MAX_ASSET and offset + length + 12 <= len(data), 'uiux_png_invalid')
        chunk = data[offset + 8:offset + 8 + length]
        crc = struct.unpack('>I', data[offset + 8 + length:offset + 12 + length])[0]
        require(binascii.crc32(kind + chunk) & 0xffffffff == crc, 'uiux_png_invalid')
        names.append(kind)
        require(len(names) <= 4096, 'uiux_png_invalid')
        if len(names) == 1:
            require(kind == b'IHDR' and length == 13, 'uiux_png_invalid')
            width, height = struct.unpack('>II', chunk[:8])
            require((width, height) == (metadata['width'], metadata['height']), 'uiux_png_invalid')
        offset += length + 12
        if kind == b'IEND':
            require(length == 0 and offset == len(data), 'uiux_png_invalid')
            break
    require(names.count(b'IHDR') == names.count(b'IEND') == 1 and b'IDAT' in names, 'uiux_png_invalid')


def _database_sidecars(path, inert):
    files = {suffix: path.with_name(path.name + suffix) for suffix in ('-wal', '-shm', '-journal')
             if path.with_name(path.name + suffix).exists() or path.with_name(path.name + suffix).is_symlink()}
    if not files:
        return {}
    require(inert and set(files) == {'-wal', '-shm'}
            and regular(files['-wal']) == 0 and regular(files['-shm']) == 32768, 'uiux_database_active')
    return {name: hashlib.sha256(file.read_bytes()).hexdigest() for name, file in files.items()}


def database(path, oracle, names, *, inert=False):
    """Read committed immutable pages, preserving any admitted inert sidecars."""
    before = sha(path)
    sidecars = _database_sidecars(path, inert)
    expected = {key: value for key, value in oracle['expected']['reports'].items() if value['name'] in names}
    observed = {}
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True, timeout=0.1)) as connection:
        with closing(connection.cursor()) as cursor:
            counts = {'parsed_reports': cursor.execute('SELECT COUNT(*) FROM parsed_reports').fetchone()[0],
                      'report_metadata': cursor.execute('SELECT COUNT(*) FROM report_metadata').fetchone()[0],
                      'report_measurements': cursor.execute('SELECT COUNT(*) FROM report_measurements').fetchone()[0]}
            literal(counts, {'parsed_reports': len(names), 'report_metadata': len(names), 'report_measurements': 144 * len(names)})
            require(cursor.execute('SELECT COUNT(*) FROM source_files').fetchone()[0] == len(names)
                    and cursor.execute('SELECT COUNT(*) FROM source_file_locations').fetchone()[0] == len(names),
                    'uiux_sql_mismatch')
            rows = cursor.execute('''SELECT pr.id,sf.sha256,sfl.file_name,pr.measurement_count,pr.has_nok,
                rm.reference,rm.report_date,rm.sample_number,rm.sample_number_kind FROM parsed_reports pr
                JOIN source_files sf ON sf.id=pr.source_file_id JOIN source_file_locations sfl
                ON sfl.source_file_id=sf.id AND sfl.is_active=1
                JOIN report_metadata rm ON rm.report_id=pr.id ORDER BY sf.sha256''').fetchall()
            require(len(rows) == len(names) <= 12, 'uiux_sql_mismatch')
            for identifier, source, name, declared, nok, *metadata in rows:
                values = cursor.execute('''SELECT row_order,header,section_name,feature_label,
                    characteristic_name,characteristic_family,description,ax,nominal,tol_plus,
                    tol_minus,bonus,meas,dev,outtol,is_nok,status_code FROM report_measurements
                    WHERE report_id=? ORDER BY row_order,id''', (identifier,)).fetchall()
                require(source not in observed and len(values) == 144, 'uiux_sql_mismatch')
                observed[source] = dict(name=name, declared=declared, actual=len(values), has_nok=nok,
                    metadata=metadata, measurements_sha256=hashlib.sha256(json.dumps(
                        values, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest())
            logical = hashlib.sha256('\n'.join(connection.iterdump()).encode()).hexdigest()
    literal(observed, expected)
    require(sha(path) == before and _database_sidecars(path, inert) == sidecars, 'uiux_database_changed')
    return logical


def xlsx_container(path):
    """Bound XML/styles expansion before any openpyxl parsing."""
    require(0 < regular(path) <= MAX_ASSET, 'uiux_xlsx_container')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        require(0 < len(entries) <= 128, 'uiux_xlsx_container')
        names, total = set(), 0
        for entry in entries:
            name = entry.filename
            require(name == entry.orig_filename and 0 < len(name) <= 256
                    and name not in names and not entry.is_dir()
                    and not entry.flag_bits & 1 and not stat.S_ISLNK(entry.external_attr >> 16)
                    and not name.startswith('/') and '\\' not in name and ':' not in name
                    and all(part not in ('', '.', '..') for part in name.split('/'))
                    and PurePosixPath(name).as_posix() == name
                    and 0 <= entry.file_size <= 8 * 1024 * 1024, 'uiux_xlsx_container')
            names.add(name)
            total += entry.file_size
            require(total <= 16 * 1024 * 1024, 'uiux_xlsx_container')


def workbook(path):
    xlsx_container(path)
    from openpyxl import load_workbook
    before = sha(path)
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book['Table Data']
        require(sheet.max_row == 5 and sheet.max_column <= 16, 'uiux_workbook_mismatch')
        rows = list(sheet.values)
        headings = list(rows[0])
        for field, expected in {'operator_lot_code': ['LOT-1', 'LOT-3', 'LOT-5', 'LOT-7'],
                                'value': [10, 30, 50, 70],
                                'captured_at': ['2026-01-01', '2026-01-03', '2026-01-05', '2026-01-07']}.items():
            require(headings.count(field) == 1, 'uiux_workbook_mismatch')
            values = [row[headings.index(field)] for row in rows[1:]]
            if field == 'captured_at':
                values = [str(value)[:10] for value in values]
            literal(values, expected)
        require(book['Metrics'].max_row == 2 and book['Metrics'].max_column <= 128, 'uiux_workbook_mismatch')
        metrics = list(book['Metrics'].values)
        for key, expected in {'n': 4, 'mean': 40.0, 'min': 10.0, 'max': 70.0}.items():
            require(list(metrics[0]).count(key) == 1, 'uiux_workbook_mismatch')
            literal(metrics[1][list(metrics[0]).index(key)], expected)
    finally:
        book.close()
    require(sha(path) == before, 'uiux_asset_changed')


class _HtmlFacts(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden, self.parts, self.ids, self.resources = 0, [], {}, []
        self.tags = {}

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        for key, value in attrs:
            if key == 'id':
                require(type(value) is str and len(value) <= 256 and len(self.ids) < 2048)
                self.ids[value] = self.ids.get(value, 0) + 1
                self.tags[value] = tag
            if key in ('src', 'href') and value and not value.startswith(('data:', '#')):
                require(len(self.resources) < 16)
                self.resources.append((tag, key, value))

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html(path):
    before = sha(path)
    text = path.read_text(encoding='utf-8')
    require(text.lstrip().lower().startswith('<!doctype html>'), 'uiux_html_mismatch')
    facts = _HtmlFacts()
    facts.feed(text)
    visible = ' '.join(' '.join(facts.parts).split())
    for phrase in ('Metroliza CSV Summary Dashboard', 'analysis.csv', 'Rows rendered 4',
                   'Metrics 1', 'Filters Applied', 'CSV/Excel row filter reduced rows from 8 to 4.',
                   'Min 10.000', 'Max 70.000', 'Mean 40.000', 'Samples 4'):
        require(phrase in visible, 'uiux_html_mismatch')
    charts = {name: count for name, count in facts.ids.items() if name.startswith('chart-')}
    elements = {name: 'section' for name in ('chart-time-series-value', 'chart-histogram-value',
                                             'chart-violin-value', 'chart-box-value')}
    elements.update({'chart-lightbox': 'dialog', 'chart-lightbox-title': 'div',
                     'chart-lightbox-close': 'button', 'chart-lightbox-plotly': 'div'})
    literal(charts, dict.fromkeys(elements, 1))
    literal({name: facts.tags[name] for name in charts}, elements)
    require(facts.ids.get('dashboard-start') == facts.ids.get('run-notes') == 1, 'uiux_html_mismatch')
    literal(facts.resources, [('script', 'src', 'analysis_assets/plotly-2.27.0.min.js')])
    require(sha(path) == before, 'uiux_asset_changed')


def _leaf(value, facets):
    keys(value, ('schema_version', 'status', 'facets', 'error_codes', 'evidence'))
    literal(value['schema_version'], 1)
    literal(value['status'], 'passed')
    literal(value['facets'], dict.fromkeys(facets, 'passed'))
    literal(value['error_codes'], [])
    return value['evidence']


def _capture_map(records, names, dpr):
    keys(records, names)
    for name in names:
        record = keys(records[name], ('path', 'sha256', 'width', 'height', 'dpr'))
        literal(record['path'], f'uiux-{name}.png')
        digest(record['sha256'])
        require(type(record['width']) is int and type(record['height']) is int
                and 64 <= record['width'] <= 8192 and 64 <= record['height'] <= 8192)
        literal(record['dpr'], float(dpr))


def reports(value, oracle, *, packaged, dpr, qpa):
    evidence = _leaf(value, ['reports_' + name for name in REPORT_FACETS])
    keys(evidence, ('fixture_hashes', 'context', 'A', 'B', 'C', 'summaries', 'captures', 'cleanup', 'failure'))
    literal(evidence['fixture_hashes'], {Path(n).name: h for n, h in FIXTURES.items() if n.startswith('reports/')})
    context = keys(evidence['context'], ('execution', 'platform', 'dpr', 'screen', 'available_screen'))
    literal(context['execution'], 'packaged' if packaged else 'source')
    literal(context['platform'], qpa)
    literal(context['dpr'], float(dpr))
    for field in ('screen', 'available_screen'):
        require(type(context[field]) is list and len(context[field]) == 2
                and all(type(n) is int and 1 <= n <= 16384 for n in context[field]))
    keys(evidence['summaries'], 'ABC')
    for case in 'ABC':
        expected = oracle['scenarios'][case]
        row = keys(evidence[case], ('review_counts', 'batch_counts', 'row_facts', 'receipt_states',
            'database_counts', 'numeric_digests', 'rereview_counts', 'context', 'preservation'))
        literal(row['review_counts'], {'ready': 12, 'duplicate': 0, 'selected': 12})
        literal(row['batch_counts'], {'saved': expected['saved'], 'failed': expected['failed'],
                                     'cancelled': expected['cancelled'], 'total': 12})
        literal(row['database_counts'], {'parsed_reports': expected['saved'],
                'report_metadata': expected['saved'], 'report_measurements': 144 * expected['saved']})
        literal(row['rereview_counts'], {'ready': 12 - expected['saved'], 'duplicate': expected['saved'],
                                       'selected': 12 - expected['saved']})
        wanted_rows, wanted_receipts, wanted_digests = [], {}, {}
        for name in sorted(item['name'] for item in oracle['expected']['reports'].values()):
            state = 'failed' if case == 'B' and name == 'REF006_0006.pdf' else (
                'unknown' if case == 'C' and name != 'REF001_0001.pdf' else 'saved')
            wanted_rows.append(dict(name=name, occurrence_id=name, state=state, readonly=True, attention=state != 'saved'))
            if state != 'unknown':
                wanted_receipts[name] = state
            if state == 'saved':
                wanted_digests[name] = next(v['measurements_sha256'] for v in oracle['expected']['reports'].values() if v['name'] == name)
        literal(row['row_facts'], wanted_rows)
        literal(row['receipt_states'], wanted_receipts)
        literal(row['numeric_digests'], wanted_digests)
        wanted_context = dict.fromkeys(('same_owner', 'same_result', 'approval_invalidated',
            'worker_running_at_cancel', 'first_accepted', 'cancel_clicked', 'cancel_flag',
            'released', 'terminal', 'barrier_expired'), False)
        wanted_context.update(first_accepted=None, released=True, terminal=True)
        if case == 'A':
            wanted_context.update(same_owner=True, same_result=True, approval_invalidated=True)
        if case == 'C':
            wanted_context.update(worker_running_at_cancel=True, first_accepted='REF001_0001.pdf',
                                  cancel_clicked=True, cancel_flag=True)
        literal(row['context'], wanted_context)
        preservation = keys(row['preservation'], ('destination_logical_sha256', 'rereview_unchanged',
                                                  'seed_unchanged', 'sources_unchanged'))
        digest(preservation['destination_logical_sha256'])
        for key in ('rereview_unchanged', 'seed_unchanged', 'sources_unchanged'):
            literal(preservation[key], True)
    _report_summaries(evidence['summaries'])
    _capture_map(evidence['captures'], CAPTURES[:4], dpr)
    literal(evidence['cleanup'], {'joined': True, 'closed': True, 'sources_unchanged': True, 'callback_errors': []})
    literal(evidence['failure'], None)
    return evidence


def _report_summaries(summaries):
    for case in 'ABC':
        snapshots = keys(summaries[case], ('immediate', 'queued'))
        for phase, snapshot in snapshots.items():
            keys(snapshot, ('width', 'height', 'hfw', 'minimum_hint', 'word_wrap',
                            'contained', 'overlap', 'visible', 'window_size'))
            require(all(type(snapshot[key]) is int and 0 <= snapshot[key] <= 16384
                        for key in ('width', 'height', 'hfw', 'minimum_hint')))
            require(type(snapshot['window_size']) is list and len(snapshot['window_size']) == 2
                    and all(type(n) is int and 1 <= n <= 16384 for n in snapshot['window_size']))
            literal({key: snapshot[key] for key in ('word_wrap', 'contained', 'overlap', 'visible')},
                    {'word_wrap': True, 'contained': True, 'overlap': False, 'visible': True})
            if phase == 'queued':
                require(snapshot['height'] >= snapshot['hfw'], 'uiux_summary_clipped')

def tabular(value, *, dpr):
    evidence = _leaf(value, TABULAR_FACETS)
    keys(evidence, ('fixture_hashes', 'csv', 'filter', 'grouping', 'captures', 'cleanup', 'failure'))
    literal(evidence['fixture_hashes'], {Path(n).name: h for n, h in FIXTURES.items() if n.startswith('tabular/')})
    csv = keys(evidence['csv'], ('source_rows', 'rows', 'values', 'identifiers', 'dates', 'metric_summary',
          'same_owner', 'same_worker', 'same_request', 'database_independent', 'database_hashes', 'request', 'outputs'))
    for key, expected in {'source_rows': 8, 'rows': 4, 'values': [10, 30, 50, 70],
            'identifiers': ['LOT-1', 'LOT-3', 'LOT-5', 'LOT-7'],
            'dates': ['2026-01-01', '2026-01-03', '2026-01-05', '2026-01-07'],
            'metric_summary': {'n': 4, 'mean': 40.0, 'min': 10.0, 'max': 70.0},
            'same_owner': True, 'same_worker': True, 'same_request': True, 'database_independent': True}.items():
        literal(csv[key], expected)
    require(type(csv['database_hashes']) is list and len(csv['database_hashes']) == 2)
    for value in csv['database_hashes']:
        digest(value)
    literal(csv['request'], {'source': 'analysis.csv', 'reference_column': 'operator_lot_code',
        'timestamp_column': 'captured_at', 'metrics': ['value'], 'filter_column': 'line',
        'selected_values': ['East'], 'filter_expression': '', 'grouping_count': 0})
    keys(csv['outputs'], ('html', 'xlsx'))
    for suffix, record in csv['outputs'].items():
        keys(record, ('path', 'sha256'))
        literal(record['path'], DATA['csv_' + suffix])
        digest(record['sha256'])
    literal(evidence['filter'], {'row_counts': [8, 4, 4, 8, 4], 'selected_values': ['East'],
                                'hidden_selected': 1, 'cancel_preserved': True, 'reset_applied': True})
    grouping = keys(evidence['grouping'], ('removed', 'unassigned', 'assigned_g1', 'assigned_g0', 'counts',
        'source_rows', 'applied_assignment_sha256', 'cancel_preserved', 'reset_preserved', 'no_date', 'member_reads'))
    for key, expected in {'removed': [1, 25, 37, 49, 61], 'unassigned': [13],
            'assigned_g1': [1, 2, 13, 14, 26], 'assigned_g0': [25, 37, 49, 61, 73], 'source_rows': 3000,
            'counts': {f'G-{i:03d}': 248 if i == 0 else 252 if i == 1 else 250 for i in range(12)},
            'applied_assignment_sha256': 'c2a4e82a66f2784c6d820d6ccf6cf8bbd67ae5b20a8313fc345c11cedb83646e',
            'cancel_preserved': True, 'reset_preserved': True, 'no_date': True}.items():
        literal(grouping[key], expected)
    reads = grouping['member_reads']
    require(type(reads) is list and 1 <= len(reads) <= 64)
    for read in reads:
        keys(read, ('columns', 'filter_columns', 'limit', 'keys', 'rows'))
        require(read['columns'] in (['source_row_number', 'operator_lot_code', 'captured_at'],
                                    ['source_row_number', 'operator_lot_code']))
        literal(read['filter_columns'], ['source_row_number'])
        literal(read['limit'], 1000)
        require(type(read['keys']) is int and type(read['rows']) is int and 0 <= read['rows'] <= read['keys'] <= 252
                and read['keys'] > 0)
    _capture_map(evidence['captures'], CAPTURES[4:9], dpr)
    literal(evidence['cleanup'], {'joined': True, 'stores_removed': True, 'closed': True,
                                'source_hashes_unchanged': True, 'observer_errors': []})
    literal(evidence['failure'], None)
    return evidence


def verify_assets(root, evidence, oracle, *, dpr, inert=False):
    """Verify the fixed retained paths; no arbitrary attachment or alternate path."""
    data = keys(evidence['data'], DATA)
    captures = keys(evidence['captures']['metadata'], CAPTURES)
    total, paths = 0, {}
    for name, relative in DATA.items():
        record = keys(data[name], ('path', 'sha256', 'size'))
        literal(record['path'], relative)
        digest(record['sha256'])
        path = asset_path(root, relative)
        require(type(record['size']) is int and record['size'] == regular(path), 'uiux_asset_size')
        require(sha(path) == record['sha256'], 'uiux_asset_hash')
        total += record['size']
        paths[name] = path
    for name, record in captures.items():
        literal(record['path'], 'uiux-' + name + '.png')
        path = asset_path(root, record['path'])
        total += regular(path)
        require(total <= MAX_TOTAL, 'uiux_asset_size')
        png(path, record, dpr)
    require(total <= MAX_TOTAL, 'uiux_asset_size')
    names = {v['name'] for v in oracle['expected']['reports'].values()}
    for case in 'ABC':
        saved = names - {'REF006_0006.pdf'} if case == 'B' else {'REF001_0001.pdf'} if case == 'C' else names
        logical = database(paths['reports_' + case], oracle, saved, inert=inert)
        literal(logical, evidence['reports']['evidence'][case]['preservation']['destination_logical_sha256'])
    database(paths['reports_seed'], oracle, names, inert=inert)
    _output_links(evidence)
    workbook(paths['csv_xlsx'])
    html(paths['csv_html'])
    require(sha(paths['csv_plotly']) == PLOTLY_SHA, 'uiux_offline_asset_mismatch')
    return paths


def manifest(captures, data, *, dpr, diagnostic=False):
    keys(data, DATA)
    require(type(captures) is dict and set(captures) <= set(CAPTURES))
    if not diagnostic:
        keys(captures, CAPTURES)
    records = {}
    for name, record in data.items():
        if record is None:
            require(diagnostic)
            continue
        keys(record, ('path', 'sha256', 'size'))
        literal(record['path'], DATA[name])
        digest(record['sha256'])
        require(type(record['size']) is int and 0 < record['size'] <= MAX_ASSET, 'uiux_asset_size')
        records[record['path']] = record
    _capture_map(captures, tuple(captures), dpr)
    for record in captures.values():
        require(record['path'] not in records)
        records[record['path']] = record
    return records


def snapshot_assets(root, captures, data, *, dpr, diagnostic=False):
    """Bound bytes in memory only after the owning host has joined its Job."""
    records = manifest(captures, data, dpr=dpr, diagnostic=diagnostic)
    snapshot, total = {}, 0
    for relative, record in records.items():
        path = asset_path(root, relative)
        content = path.read_bytes()
        total += len(content)
        require(total <= MAX_TOTAL and len(content) == regular(path), 'uiux_asset_size')
        require(hashlib.sha256(content).hexdigest() == record['sha256'], 'uiux_asset_hash')
        if relative.endswith('.png'):
            png(path, record, dpr)
        else:
            require(len(content) == record['size'], 'uiux_asset_size')
        require(sha(path) == record['sha256'], 'uiux_asset_changed')
        snapshot[relative] = content
    return snapshot


CAPTURE_STATES = {
    'reports-saved-top': dict(rows=12, saved=12, failed=0, unknown=0, attention=0, viewport='top'),
    'reports-saved-bottom': dict(rows=12, saved=12, failed=0, unknown=0, attention=0, viewport='bottom'),
    'reports-partial-error': dict(rows=12, saved=11, failed=1, unknown=0, attention=1, viewport='top'),
    'reports-partial-cancel': dict(rows=12, saved=1, failed=0, unknown=11, attention=11, viewport='top'),
    'csv-busy': dict(worker_running=True, modal_blocker=False, source_rows=8, selected_rows=4),
    'csv-resumed': dict(completed=True, rows=4, formats=['html', 'xlsx']),
    'grouping-members': dict(source_rows=3000, ids=[1, 13, 25], date_field='captured_at'),
    'filter-scope': dict(column='line', selected=['East'], hidden_selected=1, rows=4),
    'output-summary': dict(rows=4, formats=['html', 'xlsx'], scope='Line=East'),
    'active-child-modal': dict(surface='csv-metrics', owner='csv-summary', selected_metrics=1, parent_no_start=True, modal=True),
}


def _control(record, window, *, pinned=False):
    keys(record, ('id', 'bounds', 'visible', 'enabled', 'focusable', 'in_window', 'in_viewport'))
    require(type(record['id']) is str and len(record['id']) <= 64)
    bounds = record['bounds']
    require(type(bounds) is list and len(bounds) == 4
            and all(type(n) is int and -16384 <= n <= 16384 for n in bounds)
            and bounds[2] >= 0 and bounds[3] >= 0)
    for key in ('visible', 'enabled', 'focusable', 'in_window', 'in_viewport'):
        require(type(record[key]) is bool)
    x, y, width, height = bounds
    literal(record['in_window'], x >= 0 and y >= 0 and x + width <= window[0] and y + height <= window[1])
    if pinned:
        require(record['visible'] and record['in_window'] and record['in_viewport'] and width > 0 and height > 0)
        if record['id'] in {'apply', 'cancel', 'start', 'close', 'apply_button', 'cancel_button',
                            'reset_button', 'select_today_button', 'select_beginning_button', 'has_nok_button',
                            'close_button', 'refresh_button', 'next_button'}:
            require(height >= 36)


def capture_session(value, *, dpr):
    keys(value, ('status', 'metadata', 'observations', 'error_codes'))
    literal(value['status'], 'passed')
    literal(value['error_codes'], [])
    _capture_map(value['metadata'], CAPTURES, dpr)
    keys(value['observations'], CAPTURES)
    for name, observation in value['observations'].items():
        keys(observation, ('status', 'expected_state', 'observed_state', 'window', 'controls', 'error_codes'))
        literal(observation['status'], 'passed')
        literal(observation['error_codes'], [])
        literal(observation['expected_state'], CAPTURE_STATES[name])
        literal(observation['observed_state'], CAPTURE_STATES[name])
        window = keys(observation['window'], ('logical_rect', 'physical_size', 'dpr'))
        logical = window['logical_rect']
        require(type(logical) is list and len(logical) == 4 and logical[:2] == [0, 0]
                and all(type(n) is int for n in logical) and all(1 <= n <= 8192 for n in logical[2:]))
        literal(window['dpr'], float(dpr))
        # Positive QSize scaling uses qRound; unlike Python round it rounds half up.
        physical = [int(n * dpr + 0.5) for n in logical[2:]]
        literal(window['physical_size'], physical)
        literal([value['metadata'][name]['width'], value['metadata'][name]['height']], physical)
        if name.startswith('reports-'):
            ids, pinned = ['navigation', 'summary', 'table', 'outcome'], {'summary', 'table'}
        elif name in ('csv-busy', 'csv-resumed', 'output-summary'):
            ids, pinned = ['start', 'close', 'metrics', 'dashboard_path', 'workbook_path'], {'start', 'close'}
            if name == 'output-summary':
                pinned |= {'dashboard_path', 'workbook_path'}
        elif name == 'grouping-members':
            ids = ['apply', 'cancel', 'member-row-1', 'member-row-13', 'member-row-25']
            pinned = set(ids)
        elif name == 'filter-scope':
            ids, pinned = ['apply', 'cancel', 'matching', 'selection_summary'], {'apply', 'cancel', 'selection_summary'}
        else:
            ids, pinned = ['apply', 'cancel', 'search', 'metrics'], {'apply', 'cancel', 'search'}
        records = observation['controls']
        require(type(records) is list and len(records) == len(ids) and all(type(record) is dict for record in records))
        literal([record.get('id') for record in records], ids)
        for record in records:
            _control(record, logical[2:], pinned=record['id'] in pinned)
    return value


# Frozen authored P3 oracle; never derived from observed flags or focus chains.
TAB_IDS = ['directory_path', 'directory', 'archive', 'database_path', 'database', 'metadata_mode', 'review', 'search',
 'status', 'parser', 'attention', 'select_ready', 'clear', 'table', 'details_button', 'details', 'ocr',
 'metadata', 'import', 'outcome_button', 'outcome', 'modify', 'mapping', 'export']
TAB_ORACLE = {'busy': {'enabled': [True, False, False, True, False, False, False, True, True, True, True, False, False,
                      False, True, True, False, False, False, True, True, False, False, False],
          'forward': ['directory_path', 'database_path', 'search', 'status', 'parser', 'attention',
                      'details_button'],
          'reverse': ['attention', 'parser', 'status', 'search', 'database_path', 'directory_path',
                      'navigation'],
          'visible': [True, True, True, True, True, True, True, True, True, True, True, True, True, True, True,
                      False, True, True, True, False, False, True, True, True]},
 'initial': {'enabled': [True, True, True, True, False, True, False, True, True, True, True, False, False, True,
                         True, True, False, False, False, True, True, False, False, False],
             'forward': ['directory_path', 'directory', 'archive', 'database_path', 'metadata_mode', 'search',
                         'status', 'parser', 'attention', 'table', 'details_button'],
             'reverse': ['table', 'attention', 'parser', 'status', 'search', 'metadata_mode', 'database_path',
                         'archive', 'directory', 'directory_path', 'navigation'],
             'visible': [True, True, True, True, True, True, True, True, True, True, True, True, True, True,
                         True, False, True, True, True, False, False, True, True, True]},
 'ready': {'enabled': [True, True, True, True, True, True, True, True, True, True, True, False, False, True,
                       True, True, False, False, False, True, True, True, True, True],
           'forward': ['directory_path', 'directory', 'archive', 'database_path', 'database', 'metadata_mode',
                       'review', 'search', 'status', 'parser', 'attention', 'table', 'details_button', 'modify',
                       'mapping', 'export'],
           'reverse': ['mapping', 'modify', 'details_button', 'table', 'attention', 'parser', 'status',
                       'search', 'review', 'metadata_mode', 'database', 'database_path', 'archive', 'directory',
                       'directory_path', 'navigation'],
           'visible': [True, True, True, True, True, True, True, True, True, True, True, True, True, True, True,
                       False, True, True, True, False, False, True, True, True]},
 'result': {'enabled': [True, True, True, True, True, True, True, True, True, True, True, False, False, True,
                        True, True, False, False, False, True, True, True, True, True],
            'forward': ['directory_path', 'directory', 'archive', 'database_path', 'database', 'metadata_mode',
                        'review', 'search', 'status', 'parser', 'attention', 'table', 'details_button',
                        'outcome_button', 'outcome', 'modify', 'mapping', 'export'],
            'reverse': ['mapping', 'modify', 'outcome', 'outcome_button', 'details_button', 'table',
                        'attention', 'parser', 'status', 'search', 'review', 'metadata_mode', 'database',
                        'database_path', 'archive', 'directory', 'directory_path', 'navigation'],
            'visible': [True, True, True, True, True, True, True, True, True, True, True, True, True, True,
                        True, False, True, True, True, True, True, True, True, True]},
 'review': {'enabled': [True, True, True, True, True, True, True, True, True, True, True, True, True, True,
                        True, True, True, True, True, True, True, True, True, True],
            'forward': ['directory_path', 'directory', 'archive', 'database_path', 'database', 'metadata_mode',
                        'review', 'search', 'status', 'parser', 'attention', 'select_ready', 'clear', 'table',
                        'details_button', 'ocr', 'metadata', 'import', 'modify', 'mapping', 'export'],
            'reverse': ['mapping', 'modify', 'import', 'metadata', 'ocr', 'details_button', 'table', 'clear',
                        'select_ready', 'attention', 'parser', 'status', 'search', 'review', 'metadata_mode',
                        'database', 'database_path', 'archive', 'directory', 'directory_path', 'navigation'],
            'visible': [True, True, True, True, True, True, True, True, True, True, True, True, True, True,
                        True, False, True, True, True, False, False, True, True, True]}}
CONTROL_FACETS = ('workspace_routes', 'launcher_single_owner', 'reports_tab_initial_ready',
    'reports_tab_review_result', 'reports_tab_busy', 'text_modifier_guards', 'modal_shared_key_owner',
    'reports_filter_geometry', 'parser_profiles_geometry', 'active_child_capture', 'controls_cleanup')
UIUX_FACETS = ('uiux_reports', 'uiux_tabular', 'uiux_controls', 'uiux_captures', 'uiux_bugreport')
WRAPPER_ERRORS = ('uiux_reports_failed', 'uiux_tabular_failed', 'uiux_controls_failed',
                  'uiux_captures_failed', 'uiux_bugreport_failed', 'uiux_deadline',
                  'uiux_data_failed', 'uiux_unexpected')
CAPTURE_ERRORS = ('capture_name_invalid', 'capture_owner_invalid', 'capture_pixels_failed', 'capture_state_failed')


def _context(value, *, packaged, dpr, qpa):
    keys(value, ('execution', 'qpa', 'dpr', 'screen', 'available_screen'))
    literal(value['execution'], 'packaged' if packaged else 'source')
    literal(value['qpa'], qpa)
    literal(value['dpr'], float(dpr))
    for key in ('screen', 'available_screen'):
        require(type(value[key]) is list and len(value[key]) == 2
                and all(type(n) is int and 1 <= n <= 16384 for n in value[key]))


COMPACT_ORACLE = {'parser_profiles': {'size': [620, 560],
                     'tabs': [{'body': ['profile_list'],
                               'index': 0,
                               'pinned': ['close_button', 'manage_status_label', 'refresh_button'],
                               'wrapped': ['manage_status_label']},
                              {'body': ['plugin_id_edit', 'display_name_edit', 'source_format_combo',
                                        'create_button'],
                               'index': 1,
                               'pinned': ['close_button', 'stage_label', 'validation_status_label',
                                          'next_action_label', 'result_label', 'next_button'],
                               'wrapped': ['next_action_label', 'result_label']}]},
 'reports_filter': {'size': [720, 480],
                    'tabs': [{'body': ['ax_search_input', 'ax_list', 'reference_search_input', 'reference_list',
                                       'header_search_input', 'header_list', 'selected_headers_list',
                                       'status_code_search_input', 'status_code_list'],
                              'index': 0,
                              'pinned': ['apply_button', 'cancel_button', 'reset_button', 'select_today_button',
                                         'select_beginning_button', 'has_nok_button'],
                              'wrapped': ['draft_status_label', 'filter_summary_label']},
                             {'body': ['part_name_search_input', 'part_name_list', 'revision_search_input',
                                       'revision_list', 'template_variant_search_input',
                                       'template_variant_list', 'sample_number_search_input',
                                       'sample_number_list', 'operator_name_search_input', 'operator_name_list',
                                       'sample_number_kind_search_input', 'sample_number_kind_list'],
                              'index': 1,
                              'pinned': ['apply_button', 'cancel_button', 'reset_button', 'select_today_button',
                                         'select_beginning_button', 'has_nok_button'],
                              'wrapped': ['draft_status_label', 'filter_summary_label']},
                             {'body': ['filename_search_input', 'filename_list', 'parser_id_search_input',
                                       'parser_id_list', 'template_family_search_input',
                                       'template_family_list'],
                              'index': 2,
                              'pinned': ['apply_button', 'cancel_button', 'reset_button', 'select_today_button',
                                         'select_beginning_button', 'has_nok_button'],
                              'wrapped': ['draft_status_label', 'filter_summary_label']}]}}


def _compact(value):
    keys(value, ('reports_filter', 'parser_profiles'))
    for name, wanted, count in (('reports_filter', [720, 480], 3), ('parser_profiles', [620, 560], 2)):
        record = keys(value[name], ('size', 'tabs'))
        literal(record['size'], wanted)
        require(type(record['tabs']) is list and len(record['tabs']) == count)
        for index, tab in enumerate(record['tabs']):
            keys(tab, ('index', 'pinned', 'body', 'vertical', 'horizontal_max', 'wrapped'))
            literal(tab['index'], index)
            literal(tab['horizontal_max'], 0)
            for field in ('pinned', 'body'):
                expected_ids = COMPACT_ORACLE[name]['tabs'][index][field]
                require(type(tab[field]) is list and len(tab[field]) == len(expected_ids))
                literal([item.get('id') for item in tab[field]], expected_ids)
                for item in tab[field]:
                    _control(item, wanted, pinned=field == 'pinned')
            _no_overlap(tab['body'])
            vertical = keys(tab['vertical'], ('minimum', 'maximum', 'before', 'after'))
            require(all(type(n) is int and 0 <= n <= 100000 for n in vertical.values())
                    and vertical['minimum'] <= vertical['before'] <= vertical['after'] <= vertical['maximum'])
            require(vertical['before'] == vertical['maximum'] or vertical['after'] > vertical['before'])
            require(type(tab['wrapped']) is list)
            literal([item.get('id') for item in tab['wrapped']], COMPACT_ORACLE[name]['tabs'][index]['wrapped'])
            for label in tab['wrapped']:
                keys(label, ('id', 'height', 'required'))
                require(type(label['id']) is str and len(label['id']) <= 64
                        and type(label['height']) is int and type(label['required']) is int
                        and 0 <= label['required'] <= label['height'] <= 16384)


def controls(value, oracle, *, packaged, dpr, qpa):
    evidence = _leaf(value, CONTROL_FACETS)
    keys(evidence, ('context', 'routes', 'owners', 'report_tab', 'text_guards', 'modal_keys',
                    'compact_dialogs', 'captures', 'cleanup', 'failure'))
    _context(evidence['context'], packaged=packaged, dpr=dpr, qpa=qpa)
    literal(evidence['routes'], {'pages': ['home', 'reports', 'csv_summary', 'industrial_data', 'realtime_monitor'], 'same_csv': True})
    literal(evidence['owners'], dict.fromkeys(('csv', 'industrial', 'realtime', 'profiles'), True))
    tabs = keys(evidence['report_tab'], (*TAB_ORACLE, 'import'))
    for name, expected in TAB_ORACLE.items():
        stage = keys(tabs[name], ('forward', 'reverse', 'controls', 'worker_running'))
        literal(stage['forward'], expected['forward'])
        literal(stage['reverse'], expected['reverse'])
        literal(stage['worker_running'], name == 'busy')
        literal(stage['controls'], [dict(id=identifier, visible=visible, enabled=enabled)
            for identifier, visible, enabled in zip(TAB_IDS, expected['visible'], expected['enabled'], strict=True)])
    report = next(r for r in oracle['expected']['reports'].values() if r['name'] == 'REF001_0001.pdf')
    literal(tabs['import'], dict(name='REF001_0001.pdf', reports=1, measurements=144,
                                measurements_sha256=report['measurements_sha256']))
    literal(evidence['text_guards'], {'editing': {'select_all': 'er', 'after_copy': 'er', 'after_cut': '',
        'after_paste': 'er', 'after_undo_paste': '', 'after_undo_cut': 'er', 'literal': 'er'},
        'columns': [[], ['line'], [], ['line'], []], 'modifier_unchanged': True,
        'repeat_unchanged': True, 'composition_unchanged': True, 'parent_unchanged': True})
    literal(evidence['modal_keys'], dict(parent_enabled_before=True, save='accepted', close='rejected',
        parent_starts=0, parent_closes=0, return_focus=True, selected_metrics=['value']))
    _compact(evidence['compact_dialogs'])
    _capture_map(evidence['captures'], ('active-child-modal',), dpr)
    literal(evidence['cleanup'], dict(joined=True, closed=True, temporary_data_removed=True,
                                     sources_unchanged=True, observer_errors=[]))
    literal(evidence['failure'], None)
    return evidence


def _wrapper(value, *, source, packaged, dpr, qpa):
    keys(value, ('schema_version', 'status', 'runtime_context', 'facets', 'error_codes', 'evidence'))
    literal(value['schema_version'], 1)
    literal(value['runtime_context'], 'packaged' if packaged else 'source')
    evidence = keys(value['evidence'], ('context', 'reports', 'tabular', 'controls', 'bugreport', 'captures', 'data'))
    literal(evidence['context'], dict(source_sha=source, qpa=qpa, dpr=float(dpr)))
    require(type(source) is str and re.fullmatch('[0-9a-f]{40}', source) is not None
            and type(dpr) in (int, float) and dpr in (1, 1.25, 1.5))
    if packaged:
        literal(qpa, 'windows')
    return evidence


def bugreport_leaf(value, *, packaged, qpa):
    """Admit only the fixed synthetic Help/preview/clipboard observation."""
    keys(value, ('schema_version', 'status', 'facets', 'error_codes', 'evidence'))
    literal(value['schema_version'], 1)
    literal(value['status'], 'passed')
    literal(value['facets'], dict.fromkeys(('help_action', 'preview', 'clipboard',
                                            'history_restore', 'privacy_guards', 'cleanup'), 'passed'))
    literal(value['error_codes'], [])
    evidence = keys(value['evidence'], ('execution', 'platform', 'history_state', 'actions',
        'option_states', 'category', 'reproduction_status', 'preview_sha256', 'clipboard_match',
        'excluded_sentinels_absent', 'dialog_closed'))
    literal(evidence['execution'], 'packaged' if packaged else 'source')
    literal(evidence['platform'], qpa)
    literal(evidence['history_state'], 'available')
    literal(evidence['actions'], BUGREPORT_ACTIONS)
    literal(evidence['option_states'], {'report_review_ocr': True, 'workbook': True, 'html': False})
    literal(evidence['category'], 'wrong_output')
    literal(evidence['reproduction_status'], 'NOT_RUN')
    digest(evidence['preview_sha256'])
    literal(evidence['clipboard_match'], True)
    literal(evidence['excluded_sentinels_absent'], True)
    literal(evidence['dialog_closed'], True)
    return evidence


BUGREPORT_ERRORS = ('bugreport_gate_missing', 'bugreport_application_missing',
    'bugreport_route_missing', 'bugreport_preview_invalid', 'bugreport_clipboard_invalid',
    'bugreport_history_invalid', 'bugreport_privacy_invalid', 'bugreport_cleanup_failed',
    'unexpected_exception')
BUGREPORT_ACTIONS = [
    'app_opened', 'workspace_reports_opened',
    'workflow_report_import_started', 'workflow_report_import_completed',
    'option_report_review_ocr', 'workspace_database_opened',
    'workflow_database_edit_opened', 'workflow_database_edit_completed',
    'workspace_industrial_opened', 'industrial_sync_started', 'industrial_sync_finished',
    'workspace_realtime_opened', 'realtime_source_config_apply_started',
    'realtime_source_config_apply_finished', 'workspace_parser_profiles_opened',
    'parser_profile_validation_started', 'parser_profile_validation_finished',
    'csv_opened', 'option_workbook', 'option_html', 'log_error_reports',
]


def bugreport_diagnostic_leaf(value, *, packaged, qpa):
    """Validate partial failure evidence while retaining only closed, typed fields."""
    keys(value, ('schema_version', 'status', 'facets', 'error_codes', 'evidence'))
    literal(value['schema_version'], 1)
    literal(value['status'], 'failed')
    facets = keys(value['facets'], ('help_action', 'preview', 'clipboard',
                                    'history_restore', 'privacy_guards', 'cleanup'))
    require(all(status in ('passed', 'failed') for status in facets.values()))
    require(type(value['error_codes']) is list and len(value['error_codes']) == 1
            and value['error_codes'][0] in BUGREPORT_ERRORS)
    evidence = keys(value['evidence'], ('execution', 'platform', 'history_state', 'actions',
        'option_states', 'category', 'reproduction_status', 'preview_sha256', 'clipboard_match',
        'excluded_sentinels_absent', 'dialog_closed'))
    literal(evidence['execution'], 'packaged' if packaged else 'source')
    literal(evidence['platform'], qpa)
    require(evidence['history_state'] in ('unknown', 'loading', 'available', 'not_available'))
    actions = evidence['actions']
    require(type(actions) is list and len(actions) <= len(BUGREPORT_ACTIONS)
            and actions == BUGREPORT_ACTIONS[:len(actions)])
    expected_options = {}
    for action, key, state in (
        ('option_report_review_ocr', 'report_review_ocr', True),
        ('option_workbook', 'workbook', True),
        ('option_html', 'html', False),
    ):
        if action in actions:
            expected_options[key] = state
    literal(evidence['option_states'], expected_options)
    literal(evidence['category'], 'wrong_output')
    literal(evidence['reproduction_status'], 'NOT_RUN')
    if evidence['preview_sha256'] is not None:
        digest(evidence['preview_sha256'])
    for field in ('clipboard_match', 'excluded_sentinels_absent', 'dialog_closed'):
        require(type(evidence[field]) is bool)
    required_failure_facet = {
        'bugreport_route_missing': 'help_action',
        'bugreport_preview_invalid': 'preview',
        'bugreport_clipboard_invalid': 'clipboard',
        'bugreport_history_invalid': 'history_restore',
        'bugreport_privacy_invalid': 'privacy_guards',
        'bugreport_cleanup_failed': 'cleanup',
    }.get(value['error_codes'][0])
    if required_failure_facet is not None:
        literal(facets[required_failure_facet], 'failed')
    return evidence


def validate(value, oracle, *, source, packaged, dpr, qpa):
    evidence = _wrapper(value, source=source, packaged=packaged, dpr=dpr, qpa=qpa)
    literal(value['status'], 'passed')
    literal(value['facets'], dict.fromkeys(('reports', 'tabular', 'controls', 'captures', 'bugreport'), 'passed'))
    literal(value['error_codes'], [])
    reports(evidence['reports'], oracle, packaged=packaged, dpr=dpr, qpa=qpa)
    tabular(evidence['tabular'], dpr=dpr)
    controls(evidence['controls'], oracle, packaged=packaged, dpr=dpr, qpa=qpa)
    bugreport_leaf(evidence['bugreport'], packaged=packaged, qpa=qpa)
    capture_session(evidence['captures'], dpr=dpr)
    for name in ('reports', 'tabular', 'controls'):
        for key, record in evidence[name]['evidence']['captures'].items():
            literal(record, evidence['captures']['metadata'][key])
    manifest(evidence['captures']['metadata'], evidence['data'], dpr=dpr)
    return evidence


def verify(root, value, oracle, *, source, packaged, dpr, qpa):
    evidence = validate(value, oracle, source=source, packaged=packaged, dpr=dpr, qpa=qpa)
    verify_assets(root, evidence, oracle, dpr=dpr)
    return value


def _diagnostic_state(value, expected):
    """Retain only typed, path-free values from the fixed named state schema."""
    if value is None:
        return
    if type(expected) is dict:
        keys(value, expected)
        for key, item in expected.items():
            _diagnostic_state(value[key], item)
    elif type(expected) is list:
        require(type(value) is list and len(value) == len(expected))
        for observed, item in zip(value, expected, strict=True):
            _diagnostic_state(observed, item)
    elif type(expected) is int:
        require(type(value) is int and 0 <= value <= 3000)
    else:
        literal(value, expected)


def diagnostic(value, oracle, *, source, packaged, dpr, qpa):
    """Separate failure admission; never a successful artifact/receipt validator."""
    evidence = _wrapper(value, source=source, packaged=packaged, dpr=dpr, qpa=qpa)
    literal(value['status'], 'failed')
    keys(value['facets'], ('reports', 'tabular', 'controls', 'captures', 'bugreport'))
    require(all(v in ('passed', 'failed') for v in value['facets'].values()))
    require(type(value['error_codes']) is list and 1 <= len(value['error_codes']) <= 8
            and all(type(code) is str and code in WRAPPER_ERRORS for code in value['error_codes']))
    _diagnostic_leaves(evidence, oracle, packaged=packaged, dpr=dpr, qpa=qpa)
    for name in ('reports', 'tabular', 'controls'):
        literal(value['facets'][name], 'passed' if type(evidence[name]) is dict
                and evidence[name].get('status') == 'passed' else 'failed')
    if evidence['bugreport'] is None:
        literal(value['facets']['bugreport'], 'failed')
    elif type(evidence['bugreport']) is dict and evidence['bugreport'].get('status') == 'passed':
        bugreport_leaf(evidence['bugreport'], packaged=packaged, qpa=qpa)
        literal(value['facets']['bugreport'], 'passed')
    else:
        bugreport_diagnostic_leaf(evidence['bugreport'], packaged=packaged, qpa=qpa)
        literal(value['facets']['bugreport'], 'failed')
    session = keys(evidence['captures'], ('status', 'metadata', 'observations', 'error_codes'))
    require(session['status'] in ('passed', 'failed') and type(session['error_codes']) is list
            and len(session['error_codes']) <= 16 and all(type(code) is str and code in LEAF_ERRORS['controls'] for code in session['error_codes']))
    literal(value['facets']['captures'], session['status'])
    manifest(session['metadata'], evidence['data'], dpr=dpr, diagnostic=True)
    require(type(session['observations']) is dict and set(session['observations']) <= set(session['metadata']))
    for name, record in session['observations'].items():
        keys(record, ('status', 'expected_state', 'observed_state', 'window', 'controls', 'error_codes'))
        require(record['status'] in ('passed', 'failed') and type(record['controls']) is list and len(record['controls']) <= 8)
        literal(record['expected_state'], CAPTURE_STATES[name])
        _diagnostic_state(record['observed_state'], CAPTURE_STATES[name])
        require(type(record['error_codes']) is list and len(record['error_codes']) <= 16
                and all(type(code) is str and code in LEAF_ERRORS['controls'] for code in record['error_codes']))
        window = keys(record['window'], ('logical_rect', 'physical_size', 'dpr'))
        require(type(window['logical_rect']) is list and len(window['logical_rect']) == 4
                and all(type(n) is int and 0 <= n <= 8192 for n in window['logical_rect']))
        literal(window['dpr'], float(dpr))
        literal(window['physical_size'], [int(n * dpr + .5) for n in window['logical_rect'][2:]])
        for control in record['controls']:
            identifier = control.get('id') if type(control) is dict else None
            require(type(identifier) is str and (identifier in DIAGNOSTIC_IDS
                    or re.fullmatch(r'member-row-[0-9]{1,4}', identifier) is not None
                    and 1 <= int(identifier[11:]) <= 3000))
            _control(control, window['logical_rect'][2:])
    return evidence


def _diagnostic_leaves(evidence, oracle, *, packaged, dpr, qpa):
    for name, operation in (('reports', lambda v: reports(v, oracle, packaged=packaged, dpr=dpr, qpa=qpa)),
                            ('tabular', lambda v: tabular(v, dpr=dpr)),
                            ('controls', lambda v: controls(v, oracle, packaged=packaged, dpr=dpr, qpa=qpa))):
        if evidence[name] is not None:
            if type(evidence[name]) is dict and evidence[name].get('kind') == 'failure_summary':
                failure_summary(evidence[name], name)
            else:
                operation(evidence[name])
                for key, record in evidence[name]['evidence']['captures'].items():
                    literal(record, evidence['captures']['metadata'].get(key))
                if name == 'tabular':
                    _output_links(evidence)


def input_identity():
    return {'uiux_fixture_sha256': dict(FIXTURES), 'uiux_plotly_sha256': PLOTLY_SHA}


LEAF_PHASES = {'reports': ('admission', 'A', 'B', 'C', 'cleanup'),
               'tabular': ('admission', 'csv', 'filter', 'grouping', 'cleanup'),
               'controls': ('admission', 'reports', 'routes', 'dialogs', 'keys', 'cleanup')}
LEAF_ERRORS = {
    'reports': ('reports_gate_missing', 'reports_fixture_invalid', 'reports_application_missing',
        'reports_invariant_failed', 'reports_phase_deadline', 'reports_callback_failed',
        'reports_capture_failed', 'reports_summary_clipped', 'reports_worker_join_deadline', 'reports_cleanup_failed', 'unexpected_exception'),
    'tabular': ('tabular_gate_missing', 'tabular_fixture_invalid', 'tabular_application_missing',
        'tabular_invariant_failed', 'tabular_phase_deadline', 'tabular_callback_failed',
        'tabular_capture_failed', 'tabular_worker_join_deadline', 'tabular_cleanup_failed', 'unexpected_exception'),
    'controls': ('controls_gate_missing', 'controls_fixture_invalid', 'controls_application_missing',
        'controls_invariant_failed', 'controls_phase_deadline', 'controls_callback_failed',
        'controls_geometry_clipped', 'controls_worker_join_deadline', 'controls_cleanup_failed',
        *CAPTURE_ERRORS, 'unexpected_exception'),
}


def failure_summary(value, name):
    keys(value, ('kind', 'phase', 'code', 'error_codes'))
    literal(value['kind'], 'failure_summary')
    require(type(value['phase']) is str and value['phase'] in LEAF_PHASES[name]
            and type(value['code']) is str and value['code'] in LEAF_ERRORS[name])
    require(type(value['error_codes']) is list and 1 <= len(value['error_codes']) <= 8
            and all(type(code) is str and code in LEAF_ERRORS[name] for code in value['error_codes'])
            and value['code'] == value['error_codes'][0])


DIAGNOSTIC_IDS = {'navigation', 'summary', 'table', 'outcome', 'start', 'close', 'metrics',
                  'dashboard_path', 'workbook_path', 'apply', 'cancel', 'search', 'matching', 'selection_summary'}


def _no_overlap(records):
    for i, first in enumerate(records):
        x, y, w, h = first['bounds']
        for second in records[i + 1:]:
            sx, sy, sw, sh = second['bounds']
            require(x + w <= sx or sx + sw <= x or y + h <= sy or sy + sh <= y, 'uiux_body_overlap')


def _output_links(evidence):
    data = evidence['data']
    require(type(data['csv_plotly']) is dict and data['csv_plotly']['sha256'] == PLOTLY_SHA)
    for suffix in ('html', 'xlsx'):
        require(type(data['csv_' + suffix]) is dict)
        literal(evidence['tabular']['evidence']['csv']['outputs'][suffix],
                {key: data['csv_' + suffix][key] for key in ('path', 'sha256')})

"""Closed qualification protocol controls; source exports are not EXE proof."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import binascii
import html
from io import BytesIO
import json
from pathlib import Path
import zipfile
import struct
import zlib

import pytest

from scripts import verify_windows_candidate_main_html as verifier
from scripts.verify_windows_candidate_uiux import UiuxVerificationFailure

REPO = Path(__file__).resolve().parents[1]
SHA = '1' * 40
SIX_CASES = ('normal_html', 'normal_xlsx_html', 'long_html', 'long_xlsx_html',
             'target_html', 'target_xlsx_html')


def _workbook(label):
    entries = {
        '[Content_Types].xml': b'<Types/>', 'xl/workbook.xml': b'<workbook/>',
        'xl/sharedStrings.xml': ('<sst><si><t>' + label + '</t></si></sst>').encode(),
        'xl/worksheets/sheet1.xml': b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>10.02</v></c><c r="B1"><v>10.02</v></c></row></sheetData></worksheet>',
    }
    return _zip(entries)


def _zip(entries):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return stream.getvalue()


def _png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', binascii.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 64, 64, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(bytes((64 * 3 + 1) * 64))) + chunk(b'IEND', b'')


@lru_cache(maxsize=8)
def _protocol_archive(source=SHA, packaged=True):
    files, cases = {}, {}
    plotly = (REPO / 'src/metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js').read_bytes()
    for case in verifier.CASES:
        workbook = case.endswith('xlsx_html')
        dashboard, workbook_name, asset_base = verifier._case_names(case)
        stem = Path(dashboard).stem
        label = 'L' * 240 if case.startswith('long_') else 'SMOKE FEATURE'
        assets = asset_base + '.generation-' + 'a' * 32
        spec = html.escape(json.dumps({'data': [{'x': [1, 2], 'y': [10.02, 10.02]}]}), quote=True)
        contents = {
            case + '/' + stem + '.html': f'<!doctype html><h2>{label} - X</h2><script src="{assets}/plotly-2.27.0.min.js"></script><img src="{assets}/section_001_chart.png"><div data-plotly-spec-light="{spec}"></div>'.encode(),
            case + '/' + assets + '/plotly-2.27.0.min.js': plotly,
            case + '/' + assets + '/section_001_chart.png': _png(),
        }
        if workbook:
            contents[case + '/' + workbook_name] = _workbook(label)
        files.update(contents)
        cases[case] = dict(status='complete', files={name: hashlib.sha256(data).hexdigest() for name, data in contents.items()})
    files['receipt.json'] = json.dumps(dict(schema_version=2, source_sha=source,
        runtime_context='packaged' if packaged else 'source', cases=cases)).encode()
    return _zip(files)


def write_main_html_archive(path, *, source=SHA, packaged=True):
    path.write_bytes(_protocol_archive(source, packaged))


def test_closed_case_contract_requires_both_full_length_selected_targets():
    from metroliza.app import windows_candidate_main_html as producer

    assert producer.CASES == verifier.CASES == SIX_CASES
    assert producer.LONG_TARGET_STEM == 't' * 245
    assert producer.FACETS == verifier.FACETS
    html_name, _, html_assets = verifier._case_names('target_html')
    dashboard, workbook, workbook_assets = verifier._case_names('target_xlsx_html')
    assert html_name == 't' * 245 + '.html'
    assert workbook == 't' * 245 + '.xlsx'
    digest = hashlib.sha256(('t' * 245 + '_dashboard').encode()).hexdigest()[:24]
    assert dashboard == 't' * 150 + '-' + digest + '.html'
    assert len(html_name.encode()) == len(workbook.encode()) == 250
    assert len(dashboard.encode()) == 180
    assert len(html_assets.encode()) == len(workbook_assets.encode()) == 136


def test_closed_archive_reads_all_six_cases(tmp_path):
    path = tmp_path / 'main-html.zip'
    write_main_html_archive(path)
    assert verifier.verify(path, source=SHA, packaged=True) == dict.fromkeys(verifier.FACETS, 'passed')


@pytest.mark.parametrize('case', ('target_html', 'target_xlsx_html'))
@pytest.mark.parametrize('mutation', ('omit', 'shorten_selected', 'sidecar', 'generation', 'numeric'))
def test_long_target_evidence_is_mandatory_and_keeps_canonical_names(tmp_path, case, mutation):
    files = verifier._members(_protocol_archive())
    receipt = json.loads(files['receipt.json'])
    record = receipt['cases'][case]
    dashboard, workbook, _ = verifier._case_names(case)
    dashboard_path = case + '/' + dashboard
    if mutation == 'omit':
        del receipt['cases'][case]
    elif mutation in {'shorten_selected', 'sidecar'}:
        chosen = workbook if workbook and mutation == 'shorten_selected' else dashboard
        old = case + '/' + chosen
        replacement = case + '/shortened' + Path(chosen).suffix
        files[replacement] = files.pop(old)
        del record['files'][old]
        record['files'][replacement] = hashlib.sha256(files[replacement]).hexdigest()
    elif mutation == 'generation':
        for old in tuple(record['files']):
            if '.generation-' in old:
                replacement = old.replace('.generation-', 'x.generation-')
                files[replacement] = files.pop(old)
                del record['files'][old]
                record['files'][replacement] = hashlib.sha256(files[replacement]).hexdigest()
                files[dashboard_path] = files[dashboard_path].replace(old.split('/', 1)[1].encode(), replacement.split('/', 1)[1].encode())
    elif workbook:
        path = case + '/' + workbook
        entries = verifier._members(files[path])
        entries['xl/worksheets/sheet1.xml'] = entries['xl/worksheets/sheet1.xml'].replace(b'10.02', b'10.03', 1)
        files[path] = _zip(entries)
    else:
        files[dashboard_path] = files[dashboard_path].replace(b'10.02', b'10.03', 1)
    for name in record['files']:
        record['files'][name] = hashlib.sha256(files[name]).hexdigest()
    files['receipt.json'] = json.dumps(receipt).encode()
    path = tmp_path / 'main-html.zip'
    path.write_bytes(_zip(files))
    with pytest.raises((UiuxVerificationFailure, ValueError, KeyError)):
        verifier.verify(path, source=SHA, packaged=True)


def test_archive_rejects_previous_schema_even_with_all_six_cases(tmp_path):
    files = verifier._members(_protocol_archive())
    receipt = json.loads(files['receipt.json'])
    receipt['schema_version'] = 1
    files['receipt.json'] = json.dumps(receipt).encode()
    path = tmp_path / 'main-html.zip'
    path.write_bytes(_zip(files))
    with pytest.raises(UiuxVerificationFailure):
        verifier.verify(path, source=SHA, packaged=True)


@pytest.mark.parametrize('mutation', [
    'missing_case', 'extra_case', 'omission', 'source', 'runtime', 'missing_png',
    'missing_plotly', 'changed_plotly', 'changed_png', 'label', 'external', 'css_external', 'numeric',
    'path', 'extra_file', 'hash', 'long_component', 'duplicate_json',
])
def test_archive_rejects_missing_or_false_qualification_evidence(tmp_path, mutation):
    files = verifier._members(_protocol_archive())
    receipt = json.loads(files['receipt.json'])
    case = 'long_xlsx_html'
    record = receipt['cases'][case]
    png = next(name for name in record['files'] if name.endswith('.png'))
    script = next(name for name in record['files'] if name.endswith('.js'))
    dashboard = case + '/report_dashboard.html'
    if mutation == 'missing_case':
        del receipt['cases'][case]
    elif mutation == 'extra_case':
        receipt['cases']['arbitrary'] = record
    elif mutation == 'omission':
        record['status'] = 'complete_with_omissions'
    elif mutation == 'source':
        receipt['source_sha'] = '0' * 40
    elif mutation == 'runtime':
        receipt['runtime_context'] = 'source'
    elif mutation in {'missing_png', 'missing_plotly'}:
        del files[png if mutation == 'missing_png' else script]
    elif mutation == 'changed_plotly':
        files[script] += b'changed'
    elif mutation == 'changed_png':
        files[png] += b'changed'
    elif mutation == 'label':
        files[dashboard] = files[dashboard].replace(('L' * 240).encode(), b'L')
    elif mutation == 'external':
        files[dashboard] = files[dashboard].replace(png.split('/', 1)[1].encode(), b'https://invalid.example/chart.png')
    elif mutation == 'css_external':
        files[dashboard] += b'<style>body {background:url(https://invalid.example/x)}</style>'
    elif mutation == 'numeric':
        entries = verifier._members(files[case + '/report.xlsx'])
        entries['xl/worksheets/sheet1.xml'] = entries['xl/worksheets/sheet1.xml'].replace(b'10.02', b'10.03', 1)
        files[case + '/report.xlsx'] = _zip(entries)
    elif mutation == 'path':
        files['../outside.html'] = b'unsafe'
    elif mutation == 'extra_file':
        files['unlisted.txt'] = b'extra'
    elif mutation == 'hash':
        record['files'][png] = '0' * 64
    elif mutation == 'long_component':
        renamed = png.rsplit('/', 1)[0] + '/' + 'p' * 181 + '.png'
        files[renamed] = files.pop(png)
        del record['files'][png]
        record['files'][renamed] = hashlib.sha256(files[renamed]).hexdigest()
        files[dashboard] = files[dashboard].replace(png.split('/', 1)[1].encode(), renamed.split('/', 1)[1].encode())
    for name in record['files']:
        if name in files and mutation != 'hash':
            record['files'][name] = hashlib.sha256(files[name]).hexdigest()
    files['receipt.json'] = json.dumps(receipt).encode()
    if mutation == 'duplicate_json':
        files['receipt.json'] = files['receipt.json'].replace(b'"schema_version": 2', b'"schema_version": 2, "schema_version": 2')
    path = tmp_path / 'main-html.zip'
    path.write_bytes(_zip(files))
    with pytest.raises((UiuxVerificationFailure, ValueError, KeyError)):
        verifier.verify(path, source=SHA, packaged=True)


def test_real_imported_public_fixture_exports_both_main_presets(tmp_path, qapplication_session):
    from metroliza.app import windows_candidate_qualification as core

    receipt = dict(source_sha=SHA, packaged=False)
    core._run_core(tmp_path, REPO / 'tests/fixtures/windows_candidate/reports', receipt, qapplication_session)
    child = tmp_path / receipt['relative_artifact_dir']
    before = hashlib.sha256((child / 'reports.sqlite').read_bytes()).hexdigest()
    core._run_main_html_slice(child, receipt)
    artifact = child / receipt['artifacts']['main_html']['path']
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == receipt['artifacts']['main_html']['sha256']
    assert verifier.verify(artifact, source=SHA, packaged=False) == dict.fromkeys(verifier.FACETS, 'passed')
    files = verifier._members(artifact.read_bytes())
    assert 'target_html/' + 't' * 245 + '.html' in files
    assert 'target_xlsx_html/' + 't' * 245 + '.xlsx' in files
    assert hashlib.sha256((child / 'reports.sqlite').read_bytes()).hexdigest() == before
    assert all(receipt['facets'][name] == 'passed' for name in verifier.FACETS)

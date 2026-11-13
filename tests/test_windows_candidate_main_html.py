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
        stem = 'report_dashboard' if workbook else 'dashboard'
        label = 'L' * 240 if case.startswith('long_') else 'SMOKE FEATURE'
        assets = stem + '_assets.generation-' + 'a' * 32
        spec = html.escape(json.dumps({'data': [{'x': [1, 2], 'y': [10.02, 10.02]}]}), quote=True)
        contents = {
            case + '/' + stem + '.html': f'<!doctype html><h2>{label} - X</h2><script src="{assets}/plotly-2.27.0.min.js"></script><img src="{assets}/section_001_chart.png"><div data-plotly-spec-light="{spec}"></div>'.encode(),
            case + '/' + assets + '/plotly-2.27.0.min.js': plotly,
            case + '/' + assets + '/section_001_chart.png': _png(),
        }
        if workbook:
            contents[case + '/report.xlsx'] = _workbook(label)
        files.update(contents)
        cases[case] = dict(status='complete', files={name: hashlib.sha256(data).hexdigest() for name, data in contents.items()})
    files['receipt.json'] = json.dumps(dict(schema_version=1, source_sha=source,
        runtime_context='packaged' if packaged else 'source', cases=cases)).encode()
    return _zip(files)


def write_main_html_archive(path, *, source=SHA, packaged=True):
    path.write_bytes(_protocol_archive(source, packaged))


def test_closed_archive_reads_all_four_cases(tmp_path):
    path = tmp_path / 'main-html.zip'
    write_main_html_archive(path)
    assert verifier.verify(path, source=SHA, packaged=True) == dict.fromkeys(verifier.FACETS, 'passed')


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
        files['receipt.json'] = files['receipt.json'].replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')
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
    assert hashlib.sha256((child / 'reports.sqlite').read_bytes()).hexdigest() == before
    assert all(receipt['facets'][name] == 'passed' for name in verifier.FACETS)

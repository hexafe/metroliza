"""Independent closed synthetic main HTML archive verifier; no app imports.

Retained bytes, not producer claims, establish local resources, literal labels
and workbook parity. The existing core driver supplies source/package identity
and regular-file checks; downloaded receipts run this verifier again.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import struct
import tempfile
from urllib.parse import urlsplit
import zipfile

from defusedxml import ElementTree as ET
from scripts.verify_windows_candidate_uiux import PLOTLY_SHA, keys, literal, png, regular, require

CASES = ("normal_html", "normal_xlsx_html", "long_html", "long_xlsx_html",
         "target_html", "target_xlsx_html")
FACETS = ("main_html_both_presets", "main_html_long_header", "main_html_offline_assets", "main_html_workbook_numeric_parity")
MAX_TOTAL = 32 * 1024 * 1024
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _case_names(case):
    """Closed fixture names, independently derived without product helpers."""
    workbook = case.endswith("xlsx_html")
    if not case.startswith("target_"):
        stem = 'report_dashboard' if workbook else 'dashboard'
        return stem + '.html', 'report.xlsx' if workbook else None, stem + '_assets'
    selected_stem = 't' * 245
    if workbook:
        digest = hashlib.sha256((selected_stem + '_dashboard').encode()).hexdigest()[:24]
        stem = 't' * 150 + '-' + digest
    else:
        stem = selected_stem
    # The generated base reserves 44 bytes for .generation- plus UUID32.
    asset_input = stem + '_assets'
    asset_digest = hashlib.sha256(asset_input.encode()).hexdigest()[:24]
    asset_base = asset_input[:111] + '-' + asset_digest
    return stem + '.html', selected_stem + '.xlsx' if workbook else None, asset_base


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "main_html_duplicate_field")
        result[key] = value
    return result


def _members(data):
    require(0 < len(data) <= MAX_TOTAL, "main_html_archive_bound")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        entries, names, total = archive.infolist(), set(), 0
        require(0 < len(entries) <= 128, "main_html_archive_bound")
        for entry in entries:
            name = entry.filename
            require(name == entry.orig_filename and 0 < len(name) <= 512
                    and name not in names and not entry.is_dir() and not entry.flag_bits & 1
                    and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
                    and not name.startswith('/') and '\\' not in name and ':' not in name
                    and all(part not in ('', '.', '..') for part in name.split('/'))
                    and PurePosixPath(name).as_posix() == name
                    and 0 < entry.file_size <= 8 * 1024 * 1024, "main_html_archive_entry")
            names.add(name)
            total += entry.file_size
            require(total <= MAX_TOTAL, "main_html_archive_bound")
        return {entry.filename: archive.read(entry) for entry in entries}


class _Html(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references, self.headings, self.specs = [], [], []
        self.heading = False
        self.code, self.code_tag = [], None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.code_tag = tag
        if tag in {"h1", "h2", "h3", "h4"}:
            self.heading = True
        for name, value in attrs:
            if name in {"src", "href"} and value and not value.startswith('#'):
                self.references.append(value)
            if name == "data-plotly-spec-light" and value:
                self.specs.append(json.loads(value, object_pairs_hook=_unique))

    def handle_endtag(self, tag):
        if tag == self.code_tag:
            self.code_tag = None
        if tag in {"h1", "h2", "h3", "h4"}:
            self.heading = False

    def handle_data(self, data):
        if self.code_tag:
            self.code.append(data)
        if self.heading:
            self.headings.append(data)


def _png(data):
    require(len(data) >= 24 and data[:8] == b'\x89PNG\r\n\x1a\n', "main_html_png")
    width, height = struct.unpack('>II', data[16:24])
    # Reuse the retained-image validator (chunk bounds/CRCs, IDAT and IEND).
    # No archive path is extracted: only bounded bytes reach this fixed file.
    with tempfile.TemporaryDirectory(prefix='metroliza-main-html-') as scratch:
        path = Path(scratch) / 'chart.png'
        path.write_bytes(data)
        png(path, dict(path=path.name, sha256=hashlib.sha256(data).hexdigest(),
                       width=width, height=height, dpr=1.0), 1.0)


def _html(files, case, names):
    workbook = case.endswith("xlsx_html")
    dashboard_name, workbook_name, asset_base = _case_names(case)
    dashboard = case + '/' + dashboard_name
    require(dashboard in names, "main_html_missing_dashboard")
    parsed = _Html()
    parsed.feed(files[dashboard].decode('utf-8'))
    require(not re.search(r'fetch\s*\(|xmlhttprequest|@import\b|\burl\s*\(|https?://',
                          '\n'.join(parsed.code), re.I), "main_html_external_code")
    label = 'L' * 240 if case.startswith('long_') else 'SMOKE FEATURE'
    require(any(label in heading for heading in parsed.headings), "main_html_label")
    resources = set()
    for reference in parsed.references:
        url = urlsplit(reference)
        require(not url.scheme and not url.netloc and not url.query and not url.fragment
                and '\\' not in reference and '%' not in reference
                and all(part not in ('', '.', '..') for part in reference.split('/')),
                "main_html_external_reference")
        resolved = posixpath.join(case, reference)
        require(resolved in names, "main_html_missing_resource")
        resources.add(resolved)
    pngs = {name for name in names if name.endswith('.png')}
    scripts = {name for name in names if name.endswith('.js')}
    require(1 <= len(pngs) <= 4 and len(scripts) == 1 and pngs | scripts == resources,
            "main_html_resource_set")
    for name in pngs | scripts:
        parts = name.split('/')
        require(len(parts) == 3 and re.fullmatch(re.escape(asset_base) + r'\.generation-[0-9a-f]{32}', parts[1])
                and len(parts[1].encode()) <= 180
                and re.fullmatch(r'[A-Za-z0-9_.-]+', parts[2])
                and len(parts[2].encode()) <= 180, "main_html_asset_component")
    for name in pngs:
        _png(files[name])
    script = next(iter(scripts))
    require(script.endswith('/plotly-2.27.0.min.js') and hashlib.sha256(files[script]).hexdigest() == PLOTLY_SHA,
            "main_html_plotly")
    require(parsed.specs and any(10.02 in trace.get('y', []) or 10.02 in trace.get('x', [])
                                for spec in parsed.specs for trace in spec.get('data', [])),
            "main_html_plot_data")
    expected = {dashboard, *resources}
    if workbook:
        expected.add(case + '/' + workbook_name)
    require(names == expected, "main_html_case_file_set")
    return [(trace.get('x'), trace.get('y')) for spec in parsed.specs for trace in spec.get('data', [])]


def _workbook(data, label):
    members = _members(data)
    require('[Content_Types].xml' in members and 'xl/workbook.xml' in members, "main_html_xlsx")
    strings = ET.fromstring(members['xl/sharedStrings.xml'])
    text = [''.join(node.itertext()) for node in strings]
    require(label in text, "main_html_workbook_label")
    numeric = []
    for name, value in sorted(members.items()):
        if name.startswith('xl/worksheets/') and name.endswith('.xml'):
            for cell in ET.fromstring(value).findall('.//m:c', NS):
                number = cell.find('m:v', NS)
                if cell.get('t') in (None, 'n') and number is not None:
                    numeric.append((name, cell.get('r'), number.text))
    require(sum(value == '10.02' for _, _, value in numeric) >= 2, "main_html_measurements")
    return numeric


def verify(path, *, source, packaged):
    require(0 < regular(path) <= MAX_TOTAL, "main_html_archive_bound")
    files = _members(path.read_bytes())
    require('receipt.json' in files and len(files['receipt.json']) <= 64 * 1024, "main_html_receipt")
    receipt = json.loads(files['receipt.json'], object_pairs_hook=_unique)
    keys(receipt, ('schema_version', 'source_sha', 'runtime_context', 'cases'))
    literal(receipt['schema_version'], 2)
    literal(receipt['source_sha'], source)
    literal(receipt['runtime_context'], 'packaged' if packaged else 'source')
    keys(receipt['cases'], CASES)
    seen = {'receipt.json'}
    plot_data = []
    for case in CASES:
        record = keys(receipt['cases'][case], ('status', 'files'))
        literal(record['status'], 'complete')
        require(type(record['files']) is dict and 3 <= len(record['files']) <= 7, "main_html_manifest")
        names = set(record['files'])
        require(all(name.startswith(case + '/') and name not in seen and name in files for name in names),
                "main_html_manifest")
        for name, digest in record['files'].items():
            require(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest)
                    and hashlib.sha256(files[name]).hexdigest() == digest, "main_html_asset_hash")
        plot_data.append(_html(files, case, names))
        seen.update(names)
    require(set(files) == seen and len({name.casefold() for name in files}) == len(files), "main_html_archive_file_set")
    require(all(data == plot_data[0] for data in plot_data), "main_html_plot_numeric_parity")
    workbooks = [_workbook(files[case + '/' + _case_names(case)[1]],
                           'L' * 240 if case == 'long_xlsx_html' else 'SMOKE FEATURE')
                 for case in CASES if case.endswith('xlsx_html')]
    require(workbooks[0] and all(data == workbooks[0] for data in workbooks), "main_html_numeric_parity")
    return dict.fromkeys(FACETS, 'passed')

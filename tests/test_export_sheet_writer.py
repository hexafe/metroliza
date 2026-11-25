import unittest
from unittest.mock import patch
import weakref
from defusedxml import ElementTree
from zipfile import ZipFile

import pandas as pd
import pytest
from openpyxl import load_workbook
from xlsxwriter.worksheet import Worksheet

from metroliza.analytics.row_table import RowTable
from metroliza.exporting.export_backends import ExcelExportBackend
from metroliza.exporting.export_sheet_writer import _measurement_formula_cache, create_measurement_formats

from modules.export_sheet_writer import (
    build_measurement_header_block_plan,
    build_measurement_summary_row_layout,
    build_measurement_write_bundle,
    build_measurement_write_bundle_cached,
    build_summary_panel_write_plan,
    write_measurement_block,
    write_measurement_summary_rows,
)
import xlsxwriter
import tempfile


# Ordered fingerprints of valid measurement workbooks, including the cached USL, LSL, AVG and COUNT.
VALID_MEASUREMENT_XLSX_FINGERPRINTS = (
    '2cc67becbc7984036fa12b7ce7f563982113185c2c86ac0b965292e839274253',
    'b3d12c8cced4f806756a1b5f4dc535cc433935f4dc801ee3181ab90a97780a18',
    'dff2fe716ed85cf23c7029f9e1abdce957e65bfb43c361ac4566e7499e7529c7',
    '9879eb6c23b5ef9e53b10a3514c209017b74bbb46193d82c3fa091a2d9ee5418',
    '5c6e2a0b6f1e208c36db95a674b41f276f770a0839e047418aa8080751cd3926',
    'c32e9aa02ff492f986f561f1dfeb9d25e0730e7f6a6039f35473cc9bd39b53bc',
    '9ffb5ae9dea37946e308e062532c20d43d35e53a34111ffca1d2c86f8969374e',
    'd83158acc62efd5e25949eb2de4e9df92319c93db19561de6a9137ab02d3109e',
    '42014c4b94834764aab1ae0a01902e8c46c0489e4d69146077ba2a64d26d0a8f',
    'a283a47e36ee7e563169e0f1c4be652f1f29b5ce2e74a3856cce48048a88099b',
    '7250c5238d9267d3e512f33d0cd5125a9197f2f9a13b2bdf7d9e46d2f1c0d624',
    '3d67b123a40fc61020cc3739f15b5127d189a0529f37c8e65d5e9ae672d5c311',
    'b531aa76c305ac1b5e6efd5a6114b8864e0d3d99c5741888011f88ada1665e88',
    'ad32aef15800759d7371d01e7e7a68d843144a48599f5d8cc7dbab40094892bc',
    '75fb77d3c867b14b25720002d7463ae86e4a3c4ef4efc8c834c77c4e2c18ef5b',
    'da77e5359102a0c9bf793a93823891b0ef327952a636538a83e7979cd2df036b',
    '24ee0aa597b658e55c9e1e4b32d93a6185b0668500622e944a5265d65f529e39',
    '524d9d90ea90fe84b67a2b1a57e214e3374f6982b9f1c400b5e734d013775c2e',
    '37adc6475eba36392245b5b2494491e81406ef6e167d65eaba87a2be0d552767',
    'e915b8097a7cecd059adcb932c84605143bb9fccdef3b060707db43a41079692',
    '7705c6078a6d44515441fbaa82f42707d6e5aca67ba5e123474ee39ad0272232',
    '21cd2a5a08e2fea1794626c8d5925ac686de609d133ff73ac748594f26b32526',
    '4437526cf3675abdc7c0ca461c61c7c1272799eedcc85cfa9562e9344c92f835',
    '0c979bd6f1c0c06bb2ca3dda495e452c3c796ea759d09e732ea1053fac7fced7',
    '1ccc8519b159accc72757bc0d7dbd2a29fbf65fcb4ac877256fc80ce9cf5b0fa',
    'b65465176dbbf710a6371233c2a6ba00199c86bbd75b9c6403df311492a38846',
    '5829c00422c1114178ea3dc2f500139967727910598481778f9a06be7814647d',
    '34f9aa288f79f76a8e82bbc86070883e03b154906f5cefb318e7f29b2dc4021c',
    '87a78a0ed0e016637bae58ba1f5f7d1c350b1b0eecab0244d244defce5914d8e',
    'bdf1241e7d1f08f11bd32a5c24584829acd279bb527036fc5f38d3bba7c113e1',
    '459bca6780a1b82e5c85ae11a3601d1d7771dea397f6a4d42476f6db748fa140',
    '4678aabb6f9bbc4d98316246db1bf082c6026cc63a907b76b4581ca147d47950',
    '283159df4093c4cacbee5d0b8f6e60033a855cb1d2a4cf98b7c40a9a9ac0b25f',
    '6faacbb01d9458fd1aa9dcacc2acfe3952be0dbc26bcbaca085d67a703820373',
    '73dec723b1a5d8d82b13ea96a06b7cf27b17982690a301282e6828fbeec46c05',
)


def _measurement_workbook_fingerprint(path):
    import hashlib
    import json
    from zipfile import ZipFile
    import zlib
    from scripts.compare_export_outputs import _core_without_times

    digest = hashlib.sha256()
    with ZipFile(path) as package:
        for member in package.infolist():
            data = package.read(member.filename)
            crc = member.CRC
            if member.filename == 'docProps/core.xml':
                data = _core_without_times(data)
                crc = zlib.crc32(data)
            digest.update(json.dumps((member.filename, crc, len(data))).encode() + b'\0' + data)
    return digest.hexdigest()


class DummyWorksheet:
    def __init__(self):
        self.writes = []
        self.formulas = []
        self.columns = []
        self.conditional_formats = []

    def write(self, row, col, value, *args, **kwargs):
        self.writes.append((row, col, value))

    def write_formula(self, row, col, formula, *args, **kwargs):
        self.formulas.append((row, col, formula))

    def write_column(self, row, col, values):
        self.columns.append((row, col, list(values)))

    def conditional_format(self, *args):
        self.conditional_formats.append(args)


def _write_formula_cache_workbook(tmp_path, readings, *, qualified_worksheet=True, limits=(1.0, 0.5, -0.5)):
    column_names = ('DATE', 'SAMPLE_NUMBER', 'MEAS', 'NOM', '+TOL', '-TOL')
    group = RowTable(
        rows=tuple((None, str(index), value, *limits) for index, value in enumerate(readings, start=1)),
        columns=column_names,
    )
    path = tmp_path / 'measurements.xlsx'
    backend = ExcelExportBackend()
    writer = backend.create_writer(str(path))
    try:
        if not qualified_worksheet:
            writer.book.worksheet_class = Worksheet
        workbook = backend.get_workbook(writer)
        sheet = workbook.add_worksheet('READINGS')
        write_measurement_block(
            sheet, build_measurement_write_bundle('Feature - X', group, 0),
            create_measurement_formats(workbook), base_col=0,
        )
    finally:
        backend.close_writer(writer)
    return path


@pytest.mark.parametrize(
    ('readings', 'stored', 'expected'),
    [
        ((1.0011, 1.0016), (1.001, 1.002), (1.002, 2)),
        ((-1.0011, -1.0016), (-1.001, -1.002), (-1.002, 2)),
        ((1.002, 1.003), (1.002, 1.003), (1.003, 2)),
        ((-1.002, -1.003), (-1.002, -1.003), (-1.003, 2)),
        ((-0.001, None, 0.002), (-0.001, None, 0.002), (0.001, 2)),
        ((-0.002, 0.001), (-0.002, 0.001), (-0.001, 2)),
        ((-0.001, 0.001), (-0.001, 0.001), (0, 2)),
        ((999.001, -999.0), (999.001, -999.0), (None, 2)),
        ((-999.001, 999.0), (-999.001, 999.0), (None, 2)),
        ((9_999_999_999.001, -9_999_999_999.0), (9_999_999_999.001, -9_999_999_999.0), (None, 2)),
        ((-9_999_999_999.001, 9_999_999_999.0), (-9_999_999_999.001, 9_999_999_999.0), (None, 2)),
        ((999.003, -999.0, 0), (999.003, -999.0, 0), (0.001, 3)),
        ((1, 1, 0.002, -1), (1, 1, 0.002, -1), (None, 4)),
        ((1_000_000_000_000, 2), (1_000_000_000_000, 2), (None, 2)),
        ((1, 'unknown'), (1, 'unknown'), (None, 1)),
        ((1, '=2'), (1, '=2'), (None, 1)),
        ((1, '{=2'), (1, '{=2'), (None, 1)),
        ((1, '{=2}'), (1, '{=2}'), (None, 1)),
        ((1, float('nan')), (1, '#NUM!'), (None, 1)),
        ((1, float('inf')), (1, '#DIV/0!'), (None, 1)),
    ],
)
def test_measurement_formula_caches_follow_written_cells(tmp_path, readings, stored, expected):
    path = _write_formula_cache_workbook(tmp_path, readings)
    formulas = load_workbook(path)
    cached = load_workbook(path, data_only=True)
    try:
        assert formulas['READINGS']['D2'].value == f'=ROUND(AVERAGE(C22:C{21 + len(stored)}), 3)'
        assert formulas['READINGS']['D7'].value == f'=COUNT(C22:C{21 + len(stored)})'
        assert tuple(cached['READINGS'].cell(row, 3).value for row in range(22, 22 + len(stored))) == stored
        assert (cached['READINGS']['D2'].value, cached['READINGS']['D7'].value) == expected
        assert formulas['READINGS']['D1'].value == f'=ROUND(MIN(C22:C{21 + len(stored)}), 3)'
        assert cached['READINGS']['D1'].value is None
    finally:
        formulas.close()
        cached.close()


@pytest.mark.parametrize(('limits', 'expected'), [
    ((0, 0.1, None), (0.1, 0)),
    ((1.234, 0.12, -0.2), (1.354, 1.034)),
    ((1, float('nan'), -0.5), (None, 0.5)),
    ((1, float('inf'), -0.5), (None, 0.5)),
    ((1_000_000_000_000, 0.22, -0.11), (None, None)),
])
def test_limit_previews_use_only_reliable_worksheet_operands(tmp_path, limits, expected):
    path = _write_formula_cache_workbook(tmp_path, (0.05, 0.07), limits=limits)
    formulas = load_workbook(path)
    cached = load_workbook(path, data_only=True)
    try:
        sheet = cached['READINGS']
        for tolerance, result, value in zip(('B2', 'B3'), ('B4', 'B5'), expected, strict=True):
            assert formulas['READINGS'][result].value == f'=(B1+{tolerance})'
            if value is None:
                assert sheet[result].value is None
            else:
                assert sheet[result].value == pytest.approx(value)
                assert sheet[result].value == pytest.approx(sheet['B1'].value + sheet[tolerance].value)
    finally:
        formulas.close()
        cached.close()


def test_measurement_formula_caches_fall_back_for_unqualified_worksheet(tmp_path):
    path = _write_formula_cache_workbook(tmp_path, (1, '{=2}'), qualified_worksheet=False)
    namespace = {'sheet': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(path) as archive:
        sheet = ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))
    array_formula = sheet.find(".//sheet:c[@r='C23']/sheet:f", namespace)
    assert array_formula is not None
    assert array_formula.attrib == {'t': 'array', 'ref': 'C23'}
    assert array_formula.text == '2'

    cached = load_workbook(path, data_only=True)
    try:
        assert cached['READINGS']['C22'].value == 1
        assert (cached['READINGS']['D2'].value, cached['READINGS']['D7'].value) == (None, None)
    finally:
        cached.close()


@pytest.mark.parametrize(
    ('values', 'count'),
    [
        ((1, float('nan')), 1),
        ((1, float('inf')), 1),
        ((1.000001, 1.002), 2),
        ((700_000_000_000, -700_000_000_000), 2),
        ((1, True), 1),
        ((1, object()), None),
    ],
)
def test_formula_cache_preserves_fallback_for_uncertain_averages(values, count):
    assert _measurement_formula_cache(values) == (None, count)


class TestExportSheetWriter(unittest.TestCase):
    def _write_valid_measurement_corpus_case(self, path, index, owners):
        nominal = (0.0, 10.0, -3.0, 1000000.0, 0.125)[index % 5]
        tolerance = (0.5, 0.125, 2.0, 5.0, 0.005)[index % 5]
        row_count, block_count = 1 + index % 7, 1 + index % 3
        measurements = [round(nominal + (row % 5 - 2) * tolerance, 3) for row in range(row_count)]
        frame = pd.DataFrame({'DATE': [f'2026-01-{row + 1:02d}' for row in range(row_count)],
                              'SAMPLE_NUMBER': [f'S-{index}-{row}' for row in range(row_count)],
                              'MEAS': measurements, 'NOM': [nominal] * row_count,
                              '+TOL': [tolerance] * row_count, '-TOL': [-tolerance] * row_count})
        backend = ExcelExportBackend()
        writer = backend.create_writer(str(path))
        owner = backend.get_workbook(writer)
        # Keep distinct owners alive for this valid-output corpus; do not alter the cache or id().
        owners.append(owner)
        try:
            formats = create_measurement_formats(owner)
            worksheet = owner.add_worksheet('MEASUREMENTS')
            worksheet.set_column(0, block_count * 5 - 1, 12, formats['default'])
            for block in range(block_count):
                column = block * 5
                header = f'Feature {index} / Δ-{block}'
                bundle = build_measurement_write_bundle(header, frame, column)
                write_measurement_block(worksheet, bundle, formats, base_col=column)
                worksheet.set_column(column + 4, column + 4, None, formats['border'])
                chart = owner.add_chart({'type': 'line'})
                chart.add_series({'name': header,
                                  'categories': ['MEASUREMENTS', 21, column, 20 + row_count, column],
                                  'values': ['MEASUREMENTS', 21, column + 2, 20 + row_count, column + 2]})
                worksheet.insert_chart(7, column, chart)
        finally:
            backend.close_writer(writer)
        workbook = load_workbook(path)
        try:
            sheet = workbook['MEASUREMENTS']
            self.assertEqual(len(sheet._charts), block_count)
            for block in range(block_count):
                column = block * 5
                self.assertEqual(sheet.cell(1, column + 2).value, nominal)
                self.assertEqual(sheet.cell(21, column + 3).value, f'Feature {index} / Δ-{block}')
                self.assertEqual(sheet.cell(7, column + 2).number_format, '0.00%')
                self.assertTrue(sheet.cell(7, column + 2).value.startswith('='))
                self.assertEqual([sheet.cell(22 + row, column + 3).value for row in range(row_count)],
                                 measurements)
        finally:
            workbook.close()

    def test_valid_measurement_output_corpus_matches_reviewed_packages(self):
        from pathlib import Path

        self.assertEqual(len(VALID_MEASUREMENT_XLSX_FINGERPRINTS), 35)
        owners = []
        with tempfile.TemporaryDirectory() as directory:
            for index, expected in enumerate(VALID_MEASUREMENT_XLSX_FINGERPRINTS):
                with self.subTest(case=index):
                    path = Path(directory) / f'case-{index:02d}.xlsx'
                    self._write_valid_measurement_corpus_case(path, index, owners)
                    self.assertEqual(_measurement_workbook_fingerprint(path), expected)

    def test_build_measurement_write_bundle_includes_limit_columns_contract(self):
        header_group = pd.DataFrame(
            {
                'DATE': ['2024-01-01', '2024-01-02', '2024-01-03'],
                'SAMPLE_NUMBER': ['1', '2', '3'],
                'MEAS': [10.1, 10.2, 10.3],
                'NOM': [10.0, 10.0, 10.0],
                '+TOL': [0.5, 0.5, 0.5],
                '-TOL': [-0.5, -0.5, -0.5],
            }
        )

        bundle = build_measurement_write_bundle('Diameter - X', header_group, 0)

        labels = [column[2] for column in bundle['data_columns']]
        self.assertEqual(labels, ['Date', 'Sample #', 'Diameter - X', 'USL', 'LSL'])

        usl_values = bundle['data_columns'][3][3]
        lsl_values = bundle['data_columns'][4][3]
        self.assertEqual(usl_values, [10.5, 10.5, 10.5])
        self.assertEqual(lsl_values, [9.5, 9.5, 9.5])
        self.assertTrue(all(value is not None for value in usl_values))
        self.assertTrue(all(value is not None for value in lsl_values))

        measurement_plan = bundle['measurement_plan']
        self.assertIn('usl_column', measurement_plan)
        self.assertIn('lsl_column', measurement_plan)

    def test_write_measurement_block_applies_three_conditional_rules(self):
        header_group = pd.DataFrame(
            {
                'DATE': ['2024-01-01', '2024-01-02'],
                'SAMPLE_NUMBER': ['1', '2'],
                'MEAS': [10.1, 10.2],
                'NOM': [10.0, 10.0],
                '+TOL': [0.5, 0.5],
                '-TOL': [-0.5, -0.5],
            }
        )
        bundle = build_measurement_write_bundle('Diameter - X', header_group, 0)
        worksheet = DummyWorksheet()
        formats = {'percent': object(), 'wrap': object(), 'red': object()}

        measurement_plan = write_measurement_block(worksheet, bundle, formats, base_col=0)

        self.assertEqual(measurement_plan['data_start_row'], 21)
        self.assertEqual(measurement_plan['chart_insert_row'], 7)
        self.assertEqual(len(worksheet.conditional_formats), 3)
        self.assertEqual(worksheet.conditional_formats[0][4]['value'], '=($B$1+$B$2)')
        self.assertEqual(worksheet.conditional_formats[1][4]['value'], '=($B$1+$B$3)')
        self.assertTrue(any(w[2] == 'NOK %' for w in worksheet.writes if isinstance(w[2], str)))
        self.assertTrue(any((w[0], w[1], w[2]) == (0, 2, 'MIN') for w in worksheet.writes))

    def test_write_measurement_block_skips_lower_conditional_rule_for_one_sided_gdt(self):
        header_group = pd.DataFrame(
            {
                'DATE': ['2024-01-01', '2024-01-02'],
                'SAMPLE_NUMBER': ['1', '2'],
                'MEAS': [0.02, 0.12],
                'NOM': [0.0, 0.0],
                '+TOL': [0.1, 0.1],
                '-TOL': [0.0, 0.0],
            }
        )
        bundle = build_measurement_write_bundle('A-V3 - TP', header_group, 0)
        worksheet = DummyWorksheet()
        formats = {'percent': object(), 'wrap': object(), 'red': object()}

        write_measurement_block(worksheet, bundle, formats, base_col=0)

        self.assertEqual(len(worksheet.conditional_formats), 2)
        self.assertEqual(worksheet.conditional_formats[0][4]['value'], '=($B$1+$B$2)')
        self.assertFalse(
            any(item[4].get('value') == '=($B$1+$B$3)' for item in worksheet.conditional_formats)
        )

    def test_build_measurement_summary_row_layout_keeps_legacy_coordinates(self):
        stat_rows = [
            ('MIN', '=MIN(C22:C30)', None),
            ('NOK %', '=10%', 'percent'),
        ]

        layout = build_measurement_summary_row_layout(base_col=6, stat_rows=stat_rows)

        self.assertEqual(layout[0]['row'], 3)
        self.assertEqual(layout[0]['label_col'], 6)
        self.assertEqual(layout[0]['value_col'], 7)
        self.assertEqual(layout[1]['row'], 4)
        self.assertEqual(layout[1]['style'], 'percent')

    def test_write_measurement_summary_rows_writes_formula_and_percent_style(self):
        worksheet = DummyWorksheet()
        summary_rows = [
            {'row': 3, 'label_col': 0, 'value_col': 1, 'label': 'MIN', 'formula': '=MIN(C22:C30)', 'style': None},
            {'row': 4, 'label_col': 0, 'value_col': 1, 'label': 'NOK %', 'formula': '=10%', 'style': 'percent'},
        ]

        write_measurement_summary_rows(worksheet, summary_rows, formats={'percent': object()})

        self.assertIn((3, 0, 'MIN'), worksheet.writes)
        self.assertIn((4, 0, 'NOK %'), worksheet.writes)
        self.assertEqual(worksheet.formulas[0], (3, 1, '=MIN(C22:C30)'))
        self.assertEqual(worksheet.formulas[1], (4, 1, '=10%'))


    def test_build_summary_panel_write_plan_maps_header_and_image_slots(self):
        anchors = {
            'header': (40, 0),
            'distribution': (41, 1),
            'iqr': (41, 11),
            'histogram': (41, 21),
            'trend': (41, 35),
        }

        plan = build_summary_panel_write_plan(anchors, 'DIA - X')

        self.assertEqual(plan['header_cell'], {'row': 40, 'col': 0, 'value': 'DIA - X'})
        self.assertEqual(plan['image_slots']['distribution'], {'row': 41, 'col': 1})
        self.assertEqual(plan['image_slots']['iqr'], {'row': 41, 'col': 11})
        self.assertEqual(plan['image_slots']['histogram'], {'row': 41, 'col': 21})
        self.assertEqual(plan['image_slots']['trend'], {'row': 41, 'col': 35})


    def test_cached_write_bundle_matches_uncached_contract(self):
        header_group = pd.DataFrame(
            {
                'DATE': ['2024-01-01', '2024-01-02'],
                'SAMPLE_NUMBER': ['1', '2'],
                'MEAS': [10.1, 10.2],
                'NOM': [10.0, 10.0],
                '+TOL': [0.5, 0.5],
                '-TOL': [-0.5, -0.5],
            }
        )

        uncached = build_measurement_write_bundle('Diameter - X', header_group, 0)
        cache = {}
        cached = build_measurement_write_bundle_cached('Diameter - X', header_group, 0, cache=cache)

        self.assertEqual(cached['static_rows'], uncached['static_rows'])
        self.assertEqual(cached['header_plan']['stat_rows'], uncached['header_plan']['stat_rows'])
        self.assertEqual(cached['measurement_plan'], uncached['measurement_plan'])
        self.assertIn('usl_column', cached['measurement_plan'])
        self.assertIn('lsl_column', cached['measurement_plan'])

    def test_cached_header_plan_matches_uncached_output(self):
        header_group = pd.DataFrame(
            {
                'DATE': ['2024-01-01', '2024-01-02'],
                'SAMPLE_NUMBER': ['1', '2'],
                'MEAS': [10.1, 10.2],
                'NOM': [10.0, 10.0],
                '+TOL': [0.5, 0.5],
                '-TOL': [-0.5, -0.5],
            }
        )

        uncached = build_measurement_header_block_plan(header_group, 0)
        cache = {}
        cached_first = build_measurement_header_block_plan(header_group, 0, cache=cache)
        cached_second = build_measurement_header_block_plan(header_group, 0, cache=cache)

        self.assertEqual(cached_first, uncached)
        self.assertEqual(cached_second, uncached)
        self.assertEqual(len(cache.get('measurement_block_templates', {})), 1)

    def test_header_plan_exposes_cached_limit_formulas(self):
        header_group = pd.DataFrame(
            {
                'DATE': ['2024-01-01', '2024-01-02'],
                'SAMPLE_NUMBER': ['1', '2'],
                'MEAS': [10.1, 10.2],
                'NOM': [10.0, 10.0],
                '+TOL': [0.5, 0.5],
                '-TOL': [-0.5, -0.5],
            }
        )

        plan = build_measurement_header_block_plan(header_group, 0, cache={})
        self.assertEqual(plan['usl_formula'], '=(B1+B2)')
        self.assertEqual(plan['lsl_formula'], '=(B1+B3)')

    def test_create_measurement_formats_reuses_workbook_cache(self):
        from modules.export_sheet_writer import create_measurement_formats

        with tempfile.NamedTemporaryFile(suffix='.xlsx') as tmp:
            workbook = xlsxwriter.Workbook(tmp.name)
            try:
                first = create_measurement_formats(workbook)
                second = create_measurement_formats(workbook)
            finally:
                workbook.close()

        self.assertIs(first, second)


    def _write_owner_scoped_formats_workbook(self, path):
        from metroliza.exporting import export_sheet_writer as module
        from metroliza.exporting.export_backends import XlsxWorkbookAdapter

        with xlsxwriter.Workbook(str(path)) as workbook:
            adapter = XlsxWorkbookAdapter(workbook)
            adapter_ref = weakref.ref(adapter)
            formats = module.create_measurement_formats(adapter)
            owns_formats = all(value.xf_format_indices is workbook.xf_format_indices
                               for value in formats.values())
            worksheet = workbook.add_worksheet('MEASUREMENTS')
            worksheet.set_column(0, 3, 12, formats['default'])
            worksheet.write(0, 0, 'NOM')
            worksheet.write_number(1, 0, 0.25, formats['percent'])
            worksheet.write_string(0, 1, 'Date', formats['wrap'])
            worksheet.conditional_format(1, 0, 1, 0,
                                         {'type': 'cell', 'criteria': '>', 'value': 0,
                                          'format': formats['red']})
            del adapter
            self.assertIsNone(adapter_ref(), 'format cache must not retain ephemeral adapters')
        return formats, owns_formats

    def _assert_workbook_style_references_are_valid(self, path):
        from openpyxl import load_workbook

        namespace = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(path) as package:
            styles = ElementTree.fromstring(package.read('xl/styles.xml'))
            count = len(styles.find('s:cellXfs', namespace))
            for member in package.namelist():
                if member.startswith('xl/worksheets/') and member.endswith('.xml'):
                    worksheet = ElementTree.fromstring(package.read(member))
                    for cell in worksheet.findall('.//s:c', namespace):
                        self.assertLess(int(cell.get('s', '0')), count, (member, cell.get('r')))
        workbook = load_workbook(path)
        try:
            self.assertEqual(workbook['MEASUREMENTS']['A1'].value, 'NOM')
        finally:
            workbook.close()

    def test_measurement_formats_do_not_alias_for_nonoverlapping_adapter_ids(self):
        from pathlib import Path
        from metroliza.exporting import export_sheet_writer as module

        # Force only the legacy cache key; no dependence on CPython allocation or explicit GC.
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(module, 'id', lambda _owner: 41, create=True), \
                patch.object(module, '_MEASUREMENT_FORMATS_CACHE', {}, create=True):
            first, first_owned = self._write_owner_scoped_formats_workbook(Path(directory) / 'first.xlsx')
            second, second_owned = self._write_owner_scoped_formats_workbook(Path(directory) / 'second.xlsx')
            self.assertTrue(first_owned and second_owned)
            self.assertIsNot(first, second)
            self.assertIsNot(first['default'], second['default'])

    def test_measurement_styles_remain_valid_across_nonoverlapping_adapter_ids(self):
        from pathlib import Path
        from metroliza.exporting import export_sheet_writer as module

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(module, 'id', lambda _owner: 41, create=True), \
                patch.object(module, '_MEASUREMENT_FORMATS_CACHE', {}, create=True):
            paths = [Path(directory) / name for name in ('first.xlsx', 'second.xlsx')]
            for path in paths:
                self._write_owner_scoped_formats_workbook(path)
            for path in paths:
                self._assert_workbook_style_references_are_valid(path)

    def test_measurement_formats_reuse_raw_owner_across_recreated_adapters(self):
        from pathlib import Path
        from metroliza.exporting import export_sheet_writer as module
        from metroliza.exporting.export_backends import XlsxWorkbookAdapter

        with tempfile.TemporaryDirectory() as directory, \
                xlsxwriter.Workbook(str(Path(directory) / 'owner.xlsx')) as workbook:
            first = module.create_measurement_formats(workbook)
            format_count = len(workbook.formats)
            for _index in range(3):
                adapter = XlsxWorkbookAdapter(workbook)
                self.assertIs(module.create_measurement_formats(adapter), first)
                del adapter
            self.assertIs(module.create_measurement_formats(workbook), first)
            self.assertEqual(len(workbook.formats), format_count)

    def test_measurement_formats_fall_back_without_attributes_hashing_or_weakrefs(self):
        from metroliza.exporting import export_sheet_writer as module

        calls = []

        class RestrictedWorkbook:
            __slots__ = ()
            __hash__ = None

            def add_format(self, properties):
                calls.append(dict(properties))
                return object()

        workbook = RestrictedWorkbook()
        first = module.create_measurement_formats(workbook)
        second = module.create_measurement_formats(workbook)
        self.assertIsNot(first, second)
        self.assertEqual(set(first), {'default', 'border', 'wrap', 'percent', 'red'})
        self.assertEqual(len(calls), 10)

    def test_measurement_format_cache_does_not_retain_released_owner_formats(self):
        from metroliza.exporting import export_sheet_writer as module

        class FormatToken:
            pass

        class WorkbookOwner:
            def add_format(self, _properties):
                return FormatToken()

        def create_references():
            owner = WorkbookOwner()
            formats = module.create_measurement_formats(owner)
            return weakref.ref(owner), weakref.ref(formats['default'])

        with patch.object(module, '_MEASUREMENT_FORMATS_CACHE', {}, create=True):
            owner_ref, format_ref = create_references()
            self.assertIsNone(owner_ref())
            self.assertIsNone(format_ref())


if __name__ == '__main__':
    unittest.main()

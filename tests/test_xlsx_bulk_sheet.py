"""Equivalence tests for the bulk worksheet path (#1124).

Every case writes the same rows twice -- cell by cell through
``write_untrusted_xlsx_cell`` and through ``BulkRowsWorksheet.write_bulk_block``
-- and requires byte-identical workbook parts.
"""

import math
import random
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import xlsxwriter

from metroliza.exporting import xlsx_bulk_sheet
from metroliza.exporting.export_backends import _is_blank_cell
from metroliza.exporting.xlsx_bulk_sheet import (
    BULK_WRITE_ENV,
    BulkRowsWorksheet,
    bulk_write_enabled,
    enable_bulk_rows,
    plan_bulk_rows,
)
from metroliza.exporting.xlsx_writer_policy import write_untrusted_xlsx_cell, xlsxwriter_workbook_options

_VOLATILE = {'docProps/core.xml'}


def _read_parts(path):
    with zipfile.ZipFile(path) as package:
        return {name: package.read(name) for name in package.namelist() if name not in _VOLATILE}


def _write_classic(worksheet, columns, rows):
    for column_index, name in enumerate(columns):
        write_untrusted_xlsx_cell(worksheet, 0, column_index, name)
    for row_index, row in enumerate(rows, start=1):
        for column_index, value in enumerate(row):
            write_untrusted_xlsx_cell(worksheet, row_index, column_index, None if _is_blank_cell(value) else value)


def _write_bulk(worksheet, columns, rows):
    plan = plan_bulk_rows(columns, rows)
    if plan is None:
        raise AssertionError('rows were expected to be bulk-writable')
    for column_index, name in enumerate(columns):
        write_untrusted_xlsx_cell(worksheet, 0, column_index, name)
    if not worksheet.write_bulk_block(1, plan):
        raise AssertionError('bulk block was refused')


class BulkEquivalenceCase(unittest.TestCase):
    def build(self, path, *, bulk, columns, rows, extra=None, prelude=None):
        book = xlsxwriter.Workbook(str(path), xlsxwriter_workbook_options())
        if bulk:
            self.assertTrue(enable_bulk_rows(book))
        if prelude is not None:
            prelude(book)
        sheet = book.add_worksheet('Data')
        (_write_bulk if bulk else _write_classic)(sheet, columns, rows)
        if extra is not None:
            extra(book, sheet)
        book.close()

    def assert_same(self, columns, rows, *, extra=None, prelude=None):
        with tempfile.TemporaryDirectory() as tmp:
            classic = Path(tmp) / 'classic.xlsx'
            bulk = Path(tmp) / 'bulk.xlsx'
            self.build(classic, bulk=False, columns=columns, rows=rows, extra=extra, prelude=prelude)
            self.build(bulk, bulk=True, columns=columns, rows=rows, extra=extra, prelude=prelude)
            classic_parts, bulk_parts = _read_parts(classic), _read_parts(bulk)
        self.assertEqual(sorted(classic_parts), sorted(bulk_parts))
        for name in classic_parts:
            self.assertEqual(classic_parts[name], bulk_parts[name], name)
        return classic_parts


class TestBulkWorksheetEquivalence(BulkEquivalenceCase):
    COLUMNS = ['id', 'name', 'value', 'note', 'empty', 'flag']

    def test_mixed_columns_blanks_and_literal_text(self):
        rows = [
            (1, 'alpha', 1.5, '=1+1', None, 'x'),
            (2, 'beta', float('nan'), None, None, '+SUM(A1)'),
            (3, 'alpha', -0.0, '@cmd', None, ''),
            (4, None, 2.25e-10, 'https://example.test/a', None, 'x'),
            (5, 'gamma', 12345678.901234567, '{=A1}', None, None),
            (2**60, 'delta', 1e300, '-2+3', None, 'long ' * 10),
        ]
        parts = self.assert_same(self.COLUMNS, rows)
        sheet_xml = parts['xl/worksheets/sheet1.xml'].decode('utf-8')
        self.assertNotIn('<f>', sheet_xml)
        self.assertNotIn('hyperlink', sheet_xml)

    def test_long_strings_are_truncated_like_write_string(self):
        rows = [(1, 'a' * 40000, 1.0, 'a' * 40000, None, 'b' * 32767)]
        self.assert_same(self.COLUMNS, rows)

    def test_shared_string_order_is_row_major_across_columns(self):
        rows = [
            (1, 'b', 1.0, 'a', None, 'c'),
            (2, 'a', 2.0, 'z', None, 'b'),
            (3, 'c', 3.0, 'b', None, 'q'),
        ]
        self.assert_same(self.COLUMNS, rows)

    def test_sparse_first_and_last_columns_change_row_spans(self):
        rows = []
        for index in range(40):
            first = 'f' if index % 7 == 0 else None
            middle = float(index)
            last = 'l' if index % 5 == 0 else None
            rows.append((first, middle, last))
        self.assert_same(['a', 'b', 'c'], rows)

    def test_fully_blank_rows_and_columns_write_nothing(self):
        rows = [(None, None, None), (None, 1.0, None), (None, None, None)] * 10
        self.assert_same(['a', 'b', 'c'], rows)

    def test_randomised_tables_match_cell_by_cell(self):
        generator = random.Random(1124)
        for table_index in range(6):
            width = generator.randint(1, 9)
            height = generator.randint(1, 70)
            kinds = [generator.choice(['text', 'float', 'int', 'mixednum']) for _ in range(width)]
            pool = ['', 'x', 'y z', '=A1', ' lead', 'trail ', 'ünï', 'a&b<c>', '"q"']
            rows = []
            for _ in range(height):
                row = []
                for kind in kinds:
                    if generator.random() < 0.2:
                        row.append(None)
                    elif kind == 'text':
                        row.append(generator.choice(pool))
                    elif kind == 'float':
                        row.append(generator.choice([0.0, -1.5, 3.14159, 1e-7, 123456789.125, float('nan')]))
                    elif kind == 'int':
                        row.append(generator.randint(-5, 10**12))
                    else:
                        row.append(generator.choice([1, 2.5, 3, 1e22]))
                rows.append(tuple(row))
            with self.subTest(table=table_index):
                self.assert_same([f'c{i}' for i in range(width)], rows)

    def test_column_format_set_after_the_bulk_write_is_applied(self):
        rows = [(1, 'a', 1.5), (2, 'b', 2.5), (3, 'c', None)]

        def extra(book, sheet):
            sheet.set_column(0, 0, 14, book.add_format({'align': 'center'}))
            sheet.set_column(1, 2, 20)
            sheet.autofilter(0, 0, 3, 2)
            sheet.freeze_panes(1, 0)

        self.assert_same(['a', 'b', 'c'], rows, extra=extra)

    def test_later_cell_writes_into_bulk_rows_win_and_keep_output_identical(self):
        rows = [(1, 'a'), (2, 'b'), (3, 'c'), (4, 'd')]

        def extra(book, sheet):
            sheet.write(2, 1, 'overwritten')
            sheet.write_number(3, 0, 99.5)
            sheet.write_url(1, 1, 'https://example.test/x', string='link')

        self.assert_same(['a', 'b'], rows, extra=extra)

    def test_row_level_formatting_inside_the_block_is_honoured(self):
        rows = [(1.0, 'a'), (2.0, 'b'), (3.0, 'c')]

        def extra(book, sheet):
            sheet.set_row(2, 30, book.add_format({'bold': True}))

        self.assert_same(['a', 'b'], rows, extra=extra)

    def test_chart_over_a_bulk_range_has_identical_cached_data(self):
        rows = [(float(index), f'cat{index % 3}') for index in range(12)]

        def extra(book, sheet):
            chart = book.add_chart({'type': 'line'})
            chart.add_series({'categories': '=Data!$B$2:$B$13', 'values': '=Data!$A$2:$A$13'})
            sheet.insert_chart('E2', chart)

        self.assert_same(['v', 'cat'], rows, extra=extra)

    def test_default_row_height_changes_force_the_classic_row_markup(self):
        rows = [(1.0, 'a'), (2.0, 'b')]

        def extra(book, sheet):
            sheet.set_default_row(24)

        self.assert_same(['a', 'b'], rows, extra=extra)

    def test_two_bulk_sheets_share_one_string_table(self):
        rows = [(1.0, 'shared'), (2.0, 'unique-a')]

        def extra(book, sheet):
            second = book.add_worksheet('Second')
            writer = _write_bulk if isinstance(second, BulkRowsWorksheet) else _write_classic
            writer(second, ['x', 'y'], [(5.0, 'shared'), (6.0, 'unique-b')])

        self.assert_same(['a', 'b'], rows, extra=extra)


class TestBulkPlanning(unittest.TestCase):
    def test_unsupported_values_use_the_per_cell_path(self):
        class Marker(float):
            pass

        columns = ['a', 'b']
        self.assertIsNone(plan_bulk_rows(columns, [(True, 'x')]))
        self.assertIsNone(plan_bulk_rows(columns, [(float('inf'), 'x')]))
        self.assertIsNone(plan_bulk_rows(columns, [(float('-inf'), 'x')]))
        self.assertIsNone(plan_bulk_rows(columns, [(1.0, 'x'), ('text', 'y')]))
        self.assertIsNone(plan_bulk_rows(columns, [(Marker(1.0), 'x')]))
        self.assertIsNone(plan_bulk_rows(columns, [(10**400, 'x')]))
        self.assertIsNone(plan_bulk_rows(columns, [(1.0, b'bytes')]))
        self.assertIsNone(plan_bulk_rows(columns, [(1.0, 'x'), (2.0,)]))
        self.assertIsNone(plan_bulk_rows(columns, []))
        self.assertIsNone(plan_bulk_rows([], [()]))
        self.assertIsNotNone(plan_bulk_rows(columns, [(1, 'x'), (None, None), (float('nan'), 'y')]))

    def test_unsupported_tables_still_produce_literal_output_via_the_backend(self):
        from metroliza.exporting.export_backends import ExcelExportBackend

        backend = ExcelExportBackend()
        with tempfile.TemporaryDirectory() as tmp:
            outputs = {}
            for label, flag in (('bulk', '1'), ('classic', '0')):
                with patch.dict('os.environ', {BULK_WRITE_ENV: flag}):
                    writer = backend.create_writer(str(Path(tmp) / f'{label}.xlsx'))
                    backend.write_dataframe(
                        writer,
                        ([('=1+1', float('inf'), True, '@cmd'), ('+2', 1.0, False, 'https://x.test')], ['a', 'b', 'c', 'd']),
                        'Data',
                    )
                    backend.close_writer(writer)
                outputs[label] = _read_parts(Path(tmp) / f'{label}.xlsx')
        self.assertEqual(outputs['bulk'], outputs['classic'])


class TestBulkSwitches(unittest.TestCase):
    def test_environment_switch_disables_the_bulk_path(self):
        with patch.dict('os.environ', {BULK_WRITE_ENV: '0'}):
            self.assertFalse(bulk_write_enabled())
            book = types.SimpleNamespace(worksheet_class=xlsxwriter.worksheet.Worksheet)
            self.assertFalse(enable_bulk_rows(book))
            self.assertIsNot(book.worksheet_class, BulkRowsWorksheet)
        with patch.dict('os.environ', {BULK_WRITE_ENV: '1'}):
            self.assertTrue(bulk_write_enabled())

    def test_unverified_xlsxwriter_versions_use_the_classic_path(self):
        with patch.object(xlsx_bulk_sheet.xlsxwriter, '__version__', '3.9.0'):
            self.assertFalse(bulk_write_enabled())
        with patch.object(xlsx_bulk_sheet.xlsxwriter, '__version__', 'weird'):
            self.assertFalse(bulk_write_enabled())

    def test_numeric_values_round_trip_like_the_classic_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'numbers.xlsx'
            book = xlsxwriter.Workbook(str(path), xlsxwriter_workbook_options())
            enable_bulk_rows(book)
            sheet = book.add_worksheet('Data')
            values = [0.1 + 0.2, 1 / 3, 2**53 + 1, -1e-300]
            _write_bulk(sheet, ['v'], [(value,) for value in values])
            book.close()
            import openpyxl

            read_back = [cell.value for cell in openpyxl.load_workbook(path)['Data']['A'][1:]]
        for original, stored in zip(values, read_back):
            self.assertTrue(math.isclose(float(original), stored, rel_tol=1e-15))


if __name__ == '__main__':
    unittest.main()

"""Tests for the snapshot streaming helpers of the raw MEASUREMENTS sheet (#1124)."""

import random
import sqlite3
import unittest

from metroliza.exporting.measurement_stream import (
    ColumnWidthSample,
    column_width_for_values,
    iter_row_chunks,
)
from metroliza.exporting.xlsx_bulk_sheet import BulkPlanBuilder, plan_bulk_rows
from test_export_workbook_equivalence import _load_export_thread_type

SAMPLE_LIMIT = 2048


def _classic_width(thread_type, values):
    """Width exactly as ``ExportDataThread.calculate_column_width`` computes it."""
    sample = thread_type._sample_column_for_width(values, sample_limit=SAMPLE_LIMIT)
    return column_width_for_values(sample)


class TestColumnWidthSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.thread_type = _load_export_thread_type()

    def test_sample_matches_the_classic_sampler_for_all_row_counts(self):
        generator = random.Random(7)
        for row_count in (1, 2, 1023, 1024, 1025, 2047, 2048, 2049, 3000, 5000):
            rows = [(index, 'x' * generator.randint(0, 60), None if index % 3 == 0 else float(index)) for index in range(row_count)]
            for chunk_size in (1, 700, 20000):
                sample = ColumnWidthSample(SAMPLE_LIMIT)
                for start in range(0, row_count, chunk_size):
                    sample.add(rows[start:start + chunk_size])
                expected = [
                    _classic_width(self.thread_type, [row[column] for row in rows]) for column in range(3)
                ]
                with self.subTest(rows=row_count, chunk=chunk_size):
                    self.assertEqual(sample.column_widths(3), expected)

    def test_sample_keeps_the_same_rows_as_the_classic_sampler(self):
        rows = [(index,) for index in range(5000)]
        sample = ColumnWidthSample(SAMPLE_LIMIT)
        sample.add(rows)
        classic = self.thread_type._sample_column_for_width([row[0] for row in rows], sample_limit=SAMPLE_LIMIT)
        self.assertEqual([row[0] for row in sample.sample_rows()], classic)


class TestRowChunks(unittest.TestCase):
    def _cursor(self, row_count):
        connection = sqlite3.connect(':memory:')
        connection.execute('CREATE TABLE t (a INTEGER, b TEXT, c REAL)')
        connection.executemany(
            'INSERT INTO t VALUES (?, ?, ?)',
            [(index, None if index % 4 == 0 else f'v{index % 7}', index / 3 if index % 5 else None) for index in range(row_count)],
        )
        cursor = connection.cursor()
        cursor.execute('SELECT a, b, c FROM t ORDER BY a')
        return connection, cursor

    def test_chunks_cover_all_rows_in_order_and_feed_the_sample(self):
        connection, cursor = self._cursor(105)
        try:
            sample = ColumnWidthSample(SAMPLE_LIMIT)
            chunks = list(iter_row_chunks(cursor, sample, lambda: False, chunk_rows=10))
        finally:
            connection.close()
        self.assertEqual([len(chunk) for chunk in chunks], [10] * 10 + [5])
        self.assertEqual(sample.row_count, 105)
        self.assertEqual([row[0] for chunk in chunks for row in chunk], list(range(105)))

    def test_chunking_stops_when_cancelled(self):
        connection, cursor = self._cursor(50)
        try:
            calls = []

            def should_stop():
                calls.append(1)
                return len(calls) > 2

            chunks = list(iter_row_chunks(cursor, ColumnWidthSample(SAMPLE_LIMIT), should_stop, chunk_rows=10))
        finally:
            connection.close()
        self.assertEqual(len(chunks), 2)

    def test_chunked_plan_equals_single_pass_plan(self):
        connection, cursor = self._cursor(333)
        try:
            rows = cursor.fetchall()
        finally:
            connection.close()
        single = plan_bulk_rows(['a', 'b', 'c'], rows)
        for chunk_size in (1, 7, 100, 1000):
            builder = BulkPlanBuilder(['a', 'b', 'c'])
            for start in range(0, len(rows), chunk_size):
                self.assertTrue(builder.add_rows(rows[start:start + chunk_size]))
            plan = builder.build()
            self.assertEqual(plan.n_rows, single.n_rows)
            for chunked, whole in zip(plan.columns, single.columns):
                self.assertEqual(chunked.texts, whole.texts)
                for attribute in ('numbers', 'codes', 'first_rows'):
                    left, right = getattr(chunked, attribute), getattr(whole, attribute)
                    if left is None:
                        self.assertIsNone(right)
                    else:
                        self.assertEqual(left.tolist() if attribute != 'numbers' else repr(left.tolist()),
                                         right.tolist() if attribute != 'numbers' else repr(right.tolist()))

    def test_mixed_kinds_across_chunks_are_rejected(self):
        builder = BulkPlanBuilder(['a'])
        self.assertTrue(builder.add_rows([('text',), (None,)]))
        self.assertFalse(builder.add_rows([(1.5,)]))
        self.assertIsNone(builder.build())
        self.assertFalse(builder.add_rows([('more',)]))

    def test_all_missing_leading_chunks_keep_row_alignment(self):
        builder = BulkPlanBuilder(['a', 'b'])
        self.assertTrue(builder.add_rows([(None, 1.0), (None, 2.0)]))
        self.assertTrue(builder.add_rows([('late', 3.0)]))
        plan = builder.build()
        self.assertEqual(plan.columns[0].codes.tolist(), [-1, -1, 0])
        self.assertEqual(plan.columns[0].first_rows.tolist(), [2])


if __name__ == '__main__':
    unittest.main()

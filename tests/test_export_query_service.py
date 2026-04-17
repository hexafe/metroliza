import unittest

import pandas as pd

from modules.export_query_service import (
    build_export_dataframe,
    build_measurement_export_dataframe,
    ensure_sample_number_column,
    execute_export_query,
    fetch_partition_header_counts,
    fetch_sql_measurement_summaries,
)
from modules.report_query_service import build_measurement_export_query


class TestExportQueryService(unittest.TestCase):
    def test_execute_export_query_uses_reader_contract(self):
        def fake_reader(db_file, query):
            self.assertEqual(db_file, 'db.sqlite')
            self.assertEqual(query, 'SELECT 1')
            return [(1,)], ['VALUE']

        rows, columns = execute_export_query('db.sqlite', 'SELECT 1', select_reader=fake_reader)
        self.assertEqual(rows, [(1,)])
        self.assertEqual(columns, ['VALUE'])

    def test_build_measurement_export_dataframe_adds_header_ax_and_sample_number(self):
        df = pd.DataFrame(
            {
                'HEADER': ['H1'],
                'AX': ['A'],
                'MEAS': [1.23],
            }
        )

        result = build_measurement_export_dataframe(df)

        self.assertEqual(result.loc[0, 'HEADER - AX'], 'H1 - A')
        self.assertEqual(result.loc[0, 'SAMPLE_NUMBER'], '1')

    def test_ensure_sample_number_column_keeps_existing(self):
        df = pd.DataFrame({'SAMPLE_NUMBER': ['42']})
        self.assertEqual(ensure_sample_number_column(df).loc[0, 'SAMPLE_NUMBER'], '42')

    def test_build_export_dataframe_preserves_columns(self):
        df = build_export_dataframe([(1, 'A')], ['ID', 'LABEL'])
        self.assertEqual(list(df.columns), ['ID', 'LABEL'])

    def test_fetch_partition_header_counts_uses_sqlite_literal_delimiter(self):
        captured = {}

        def fake_read_sql_query(_db_file, query, *, params=(), connection=None):
            captured['query'] = query
            self.assertEqual(params, ())
            self.assertIsNone(connection)
            return pd.DataFrame(
                {
                    'partition_value': ['REF_A'],
                    'header_count': [2],
                }
            )

        from modules import export_query_service as service

        previous_reader = service._read_sql_query
        try:
            service._read_sql_query = fake_read_sql_query
            counts = fetch_partition_header_counts('db.sqlite', 'SELECT * FROM vw_measurement_export')
        finally:
            service._read_sql_query = previous_reader

        self.assertEqual(counts, {'REF_A': 2})
        self.assertIn("HEADER || ' - ' || AX", captured['query'])

    def test_fetch_sql_measurement_summaries_groups_rows_by_reference_header_and_axis(self):
        captured = {}

        def fake_read_sql_query(_db_file, query, *, params=(), connection=None):
            captured['query'] = query
            captured['params'] = params
            self.assertIsNone(connection)
            return pd.DataFrame(
                {
                    'REFERENCE': ['REF_A'],
                    'HEADER': ['H1'],
                    'AX': ['AX1'],
                    'sample_size': [3],
                    'average': [1.5],
                    'minimum': [1.0],
                    'maximum': [2.0],
                    'nok_count': [1],
                    'sigma': [0.5],
                }
            )

        from modules import export_query_service as service

        previous_reader = service._read_sql_query
        try:
            service._read_sql_query = fake_read_sql_query
            summaries = fetch_sql_measurement_summaries('db.sqlite', 'SELECT * FROM vw_measurement_export', reference='REF_A')
        finally:
            service._read_sql_query = previous_reader

        self.assertEqual(captured['params'], ('REF_A',))
        self.assertIn('GROUP BY REFERENCE, HEADER, AX', captured['query'])
        self.assertIn('MEAS > (NOM + "+TOL")', captured['query'])
        self.assertEqual(
            summaries[('REF_A', 'H1', 'AX1')]['sample_size'],
            3,
        )

    def test_build_measurement_export_query_keeps_workbook_alias_columns(self):
        query = build_measurement_export_query()

        self.assertIn('directory_path AS FILELOC', query)
        self.assertIn('file_name AS FILENAME', query)


if __name__ == '__main__':
    unittest.main()

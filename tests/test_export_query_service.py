import unittest

import pandas as pd

from modules.export_query_service import (
    build_export_dataframe,
    build_measurement_export_dataframe,
    ensure_sample_number_column,
    execute_export_query,
)


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


if __name__ == '__main__':
    unittest.main()

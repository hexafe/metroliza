import tempfile
import unittest
from pathlib import Path

import pandas as pd

from modules.csv_summary_utils import (
    compute_column_summary_stats,
    load_csv_with_fallbacks,
    resolve_default_data_columns,
)


class CsvSummaryUtilsTests(unittest.TestCase):
    def test_load_csv_with_semicolon_decimal_comma(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / 'sample.csv'
            csv_path.write_text('PART;LENGTH;WIDTH\nA;10,5;2,0\nB;11,0;2,1\n', encoding='utf-8')

            df, config = load_csv_with_fallbacks(csv_path)

            self.assertEqual(['PART', 'LENGTH', 'WIDTH'], list(df.columns))
            self.assertEqual(';', config['delimiter'])
            self.assertEqual(',', config['decimal'])

    def test_resolve_default_data_columns_prefers_numeric(self):
        df = pd.DataFrame(
            {
                'SERIAL': ['A', 'B', 'C'],
                'MATERIAL': ['X', 'Y', 'Z'],
                'THICKNESS': ['1.1', '1.2', '1.3'],
                'WEIGHT': ['5', '6', '7'],
            }
        )

        selected = resolve_default_data_columns(df, ['SERIAL'])

        self.assertEqual(['THICKNESS', 'WEIGHT'], selected)


    def test_compute_column_summary_stats_uses_spec_limits(self):
        stats = compute_column_summary_stats(
            pd.Series([9.8, 10.0, 10.2]),
            nom=10.0,
            usl=0.5,
            lsl=-0.5,
        )

        self.assertEqual(3, stats['sample_size'])
        self.assertEqual(10.0, stats['nom'])
        self.assertEqual(0.5, stats['usl'])
        self.assertEqual(-0.5, stats['lsl'])
        self.assertNotEqual('N/A', stats['cp'])
        self.assertNotEqual('N/A', stats['cpk'])

    def test_compute_column_summary_stats_handles_empty_series(self):
        stats = compute_column_summary_stats(pd.Series(['x', None]))

        self.assertEqual(0, stats['sample_size'])
        self.assertEqual('N/A', stats['cp'])
        self.assertEqual('N/A', stats['cpk'])


if __name__ == '__main__':
    unittest.main()

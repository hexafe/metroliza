import unittest

import pandas as pd

from modules.export_group_comparison_writer import (
    prepare_group_comparison_payload,
    write_group_comparison_sheet,
)


class FakeWorksheet:
    def __init__(self):
        self.writes = []
        self.conditional_formats = []
        self.columns = []
        self.frozen = None

    def write(self, row, col, value, *args, **kwargs):
        self.writes.append((row, col, value))

    def conditional_format(self, first_row, first_col, last_row, last_col, options):
        self.conditional_formats.append((first_row, first_col, last_row, last_col, options))

    def set_column(self, first_col, last_col, width, *args, **kwargs):
        self.columns.append((first_col, last_col, width))

    def freeze_panes(self, row, col):
        self.frozen = (row, col)


class TestExportGroupComparisonSheet(unittest.TestCase):
    def test_writer_renders_expected_sections_and_layout(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['DIA - X', 'DIA - X', 'DIA - X', 'DIA - X'],
                'MEAS': [10.0, 10.5, 11.1, 11.4],
                'GROUP': ['A', 'A', 'B', 'B'],
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        titles = [value for _, _, value in worksheet.writes if isinstance(value, str)]
        self.assertIn('Group Comparison - Interpretation Guide', titles)
        self.assertIn('Metadata', titles)
        self.assertIn('Overall Test Summary', titles)
        self.assertIn('Recommended Statistical Tests', titles)
        self.assertIn('Pairwise Tables', titles)
        self.assertIn('Significance Heatmap (p-values)', titles)
        self.assertIn('Effect Size Heatmap (|d|)', titles)
        self.assertIn('Insights', titles)
        self.assertEqual(len(worksheet.conditional_formats), 2)
        self.assertEqual(worksheet.frozen, (1, 0))

    def test_writer_handles_empty_payload(self):
        payload = prepare_group_comparison_payload(pd.DataFrame())
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        self.assertTrue(any(value == 'No rows' for _, _, value in worksheet.writes))
        self.assertTrue(any(value == 'No heatmap data' for _, _, value in worksheet.writes))


if __name__ == '__main__':
    unittest.main()

import unittest

import pandas as pd

from modules.export_group_comparison_writer import (
    _build_insights,
    _build_pairwise_group_matrices,
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
                'HEADER - AX': ['DIA - X'] * 6,
                'MEAS': [10.0, 10.5, 11.1, 11.4, 12.0, 12.2],
                'GROUP': ['A', 'A', 'B', 'B', 'C', 'C'],
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        titles = [value for _, _, value in worksheet.writes if isinstance(value, str)]
        self.assertIn('How to interpret these results', titles)
        self.assertIn('Metadata', titles)
        self.assertIn('Overall Test Summary', titles)
        self.assertIn('Recommended Statistical Tests', titles)
        self.assertIn('Pairwise Tables', titles)
        self.assertIn('Significance Matrix (adjusted p-values)', titles)
        self.assertIn('Effect Size Matrix (|d|)', titles)
        self.assertIn('Insights', titles)
        self.assertEqual(len(worksheet.conditional_formats), 6)
        self.assertEqual(worksheet.frozen, (1, 0))

    def test_writer_registers_conditional_format_thresholds(self):
        matrix = pd.DataFrame([[0.0, 0.03], [0.03, 0.0]], index=['A', 'B'], columns=['A', 'B'])
        payload = {
            'metadata': [],
            'overall_summary': [],
            'overall_test_rows': [],
            'pairwise_rows': [],
            'significance_matrices': {'M1': matrix},
            'effect_matrices': {'M1': matrix},
            'insights': [],
        }
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        self.assertEqual(len(worksheet.conditional_formats), 6)
        significance_rules = [fmt for fmt in worksheet.conditional_formats[:3]]
        effect_rules = [fmt for fmt in worksheet.conditional_formats[3:]]
        self.assertEqual(significance_rules[0][4]['criteria'], '>=')
        self.assertEqual(significance_rules[0][4]['value'], 0.05)
        self.assertEqual(significance_rules[1][4]['criteria'], 'between')
        self.assertEqual(significance_rules[1][4]['minimum'], 0.01)
        self.assertEqual(significance_rules[2][4]['criteria'], '<')
        self.assertEqual(significance_rules[2][4]['value'], 0.01)
        self.assertEqual(effect_rules[0][4]['value'], 0.2)
        self.assertEqual(effect_rules[1][4]['maximum'], 0.5)
        self.assertEqual(effect_rules[2][4]['value'], 0.5)

    def test_pairwise_matrix_construction_uses_adjusted_p_and_absolute_effect(self):
        pairwise_df = pd.DataFrame(
            [
                {
                    'Metric': 'DIA - X',
                    'Group A': 'A',
                    'Group B': 'B',
                    'Adjusted p-value': 0.012,
                    'Effect size': -0.6,
                }
            ]
        )

        significance_matrices, effect_matrices = _build_pairwise_group_matrices(pairwise_df)

        sig = significance_matrices['DIA - X']
        effect = effect_matrices['DIA - X']
        self.assertEqual(sig.loc['A', 'B'], 0.012)
        self.assertEqual(sig.loc['B', 'A'], 0.012)
        self.assertEqual(sig.loc['A', 'A'], 0.0)
        self.assertEqual(effect.loc['A', 'B'], 0.6)
        self.assertEqual(effect.loc['B', 'A'], 0.6)

    def test_insights_are_deterministic_and_cover_scaffold_topics(self):
        working = pd.DataFrame(
            {
                'GROUP': ['A', 'A', 'B', 'B'],
                'MEAS': [10.0, 10.0, 8.0, 8.0],
            }
        )
        pairwise_df = pd.DataFrame(
            [
                {
                    'Metric': 'DIA - X',
                    'Group A': 'A',
                    'Group B': 'B',
                    'Adjusted p-value': 0.03,
                    'n(A)': 2,
                    'n(B)': 2,
                }
            ]
        )
        overall_test_rows = [
            {
                'Metric': 'DIA - X',
                'Selected test': 'Mann-Whitney U',
                'Assumptions / warnings': 'Small sample size',
            }
        ]

        insights = _build_insights(working, pairwise_df, overall_test_rows)

        self.assertEqual(len(insights), 5)
        self.assertEqual(
            insights[0],
            'Central tendency: highest mean=A (10.000), lowest mean=B (8.000).',
        )
        self.assertIn('Significant pairwise findings:', insights[1])
        self.assertIn('No-difference outcomes:', insights[2])
        self.assertIn('Small-sample warning (n < 5):', insights[3])
        self.assertIn('Assumption/test-choice notes:', insights[4])



    def test_prepare_payload_counts_samples_after_nan_filtering(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['DIA - X'] * 5,
                'MEAS': [10.0, None, float('nan'), 'bad', 11.0],
                'GROUP': ['A', 'A', 'A', 'B', 'B'],
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)

        self.assertIn(('Rows', 2), payload['metadata'])
        pairwise_row = payload['pairwise_rows'][0]
        self.assertEqual(pairwise_row['n(A)'], 1)
        self.assertEqual(pairwise_row['n(B)'], 1)


    def test_integration_workbook_contains_group_comparison_sheet_and_headers(self):
        import tempfile
        import zipfile

        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['DIA - X'] * 6,
                'MEAS': [10.0, 10.5, 11.1, 11.4, 12.0, 12.2],
                'GROUP': ['A', 'A', 'B', 'B', 'C', 'C'],
            }
        )
        payload = prepare_group_comparison_payload(grouped_df)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = f"{tmpdir}/group_comparison.xlsx"
            import xlsxwriter
            workbook = xlsxwriter.Workbook(workbook_path)
            worksheet = workbook.add_worksheet('Group Comparison')
            write_group_comparison_sheet(worksheet, payload)
            workbook.close()

            with zipfile.ZipFile(workbook_path, 'r') as archive:
                workbook_xml = archive.read('xl/workbook.xml').decode('utf-8')
                shared_strings = archive.read('xl/sharedStrings.xml').decode('utf-8')

        self.assertIn('Group Comparison', workbook_xml)
        for title in [
            'How to interpret these results',
            'Metadata',
            'Overall Test Summary',
            'Recommended Statistical Tests',
            'Pairwise Tables',
            'Significance Matrix (adjusted p-values)',
            'Effect Size Matrix (|d|)',
            'Insights',
        ]:
            self.assertIn(title, shared_strings)

    def test_writer_handles_empty_payload(self):
        payload = prepare_group_comparison_payload(pd.DataFrame())
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        self.assertTrue(any(value == 'No rows' for _, _, value in worksheet.writes))
        self.assertTrue(any(value == 'No heatmap data' for _, _, value in worksheet.writes))


if __name__ == '__main__':
    unittest.main()

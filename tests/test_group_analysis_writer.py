import unittest

from modules.group_analysis_writer import (
    write_group_analysis_diagnostics_sheet,
    write_group_analysis_sheet,
)


class FakeWorksheet:
    def __init__(self):
        self.writes = []
        self.frozen = None

    def write(self, row, col, value, *args, **kwargs):
        self.writes.append((row, col, value))

    def freeze_panes(self, row, col):
        self.frozen = (row, col)


class TestGroupAnalysisWriter(unittest.TestCase):
    def test_group_analysis_sheet_smoke(self):
        worksheet = FakeWorksheet()
        payload = {
            'status': 'ready',
            'effective_scope': 'single_reference',
            'metric_rows': [
                {
                    'metric': 'M1',
                    'reference': 'R1',
                    'group_count': 2,
                    'spec_status': 'complete',
                    'capability': {'cp': 1.1, 'cpk': 1.0},
                    'descriptive_stats': [
                        {'group': 'A', 'n': 2, 'mean': 10.1, 'std': 0.1, 'min': 10.0, 'max': 10.2},
                        {'group': 'B', 'n': 2, 'mean': 9.7, 'std': 0.1, 'min': 9.6, 'max': 9.8},
                    ],
                    'pairwise_rows': [
                        {
                            'group_a': 'A',
                            'group_b': 'B',
                            'adjusted_p_value': 0.03,
                            'effect_size': 0.7,
                            'test_used': 'Welch t-test',
                            'significant': True,
                        }
                    ],
                }
            ],
        }

        write_group_analysis_sheet(worksheet, payload)

        values = [value for _, _, value in worksheet.writes]
        self.assertIn('Group Analysis', values)
        self.assertIn('Metric: M1', values)
        self.assertIn('Descriptive stats', values)
        self.assertIn('Pairwise comparisons', values)
        self.assertEqual(worksheet.frozen, (1, 0))

    def test_group_analysis_diagnostics_sheet_smoke(self):
        worksheet = FakeWorksheet()
        payload = {
            'requested_scope': 'auto',
            'effective_scope': 'single_reference',
            'reference_count': 1,
            'metric_count': 1,
            'skipped_metric_count': 1,
            'skip_reason': None,
            'metrics': [
                {
                    'metric': 'M1',
                    'reference': 'R1',
                    'group_count': 2,
                    'spec_status': 'complete',
                    'pairwise_rows': [{'group_a': 'A', 'group_b': 'B'}],
                }
            ],
            'skipped_metrics': [{'metric': 'M2', 'reason': 'insufficient_groups'}],
        }

        write_group_analysis_diagnostics_sheet(worksheet, payload)

        values = [value for _, _, value in worksheet.writes]
        self.assertIn('Group Analysis Diagnostics', values)
        self.assertIn('Analyzed metrics', values)
        self.assertIn('Skipped metrics', values)
        self.assertIn('M2', values)
        self.assertEqual(worksheet.frozen, (1, 0))


if __name__ == '__main__':
    unittest.main()

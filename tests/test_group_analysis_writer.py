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
                    'spec_status': 'EXACT_MATCH',
                    'comparability_summary': {
                        'status': 'EXACT_MATCH',
                        'interpretation_limits': 'none',
                        'summary': 'Specs are aligned',
                    },
                    'capability': {'cp': 1.1, 'cpk': 1.0},
                    'descriptive_stats': [
                        {
                            'group': 'A',
                            'n': 2,
                            'mean': 10.1,
                            'std': 0.1,
                            'median': 10.1,
                            'iqr': 0.1,
                            'min': 10.0,
                            'max': 10.2,
                            'cp': 1.0,
                            'capability': 0.9,
                            'capability_type': 'Cpk',
                            'flags': 'none',
                        },
                        {
                            'group': 'B',
                            'n': 2,
                            'mean': 9.7,
                            'std': 0.1,
                            'median': 9.7,
                            'iqr': 0.1,
                            'min': 9.6,
                            'max': 9.8,
                            'cp': 1.0,
                            'capability': 0.8,
                            'capability_type': 'Cpk',
                            'flags': 'none',
                        },
                    ],
                    'pairwise_rows': [
                        {
                            'group_a': 'A',
                            'group_b': 'B',
                            'delta_mean': 0.4,
                            'adjusted_p_value': 0.03,
                            'effect_size': 0.7,
                            'difference': 'YES',
                            'comment': 'DIFFERENCE',
                        }
                    ],
                    'insights': ['Line 1', 'Line 2'],
                }
            ],
        }

        write_group_analysis_sheet(worksheet, payload)

        values = [value for _, _, value in worksheet.writes]
        self.assertIn('Group Analysis', values)
        self.assertIn('Metric: M1', values)
        self.assertIn('Descriptive stats', values)
        self.assertIn('Spec status', values)
        self.assertIn('Exact match', values)
        self.assertIn('Pairwise comparisons', values)
        self.assertIn('Comment', values)
        self.assertIn('adj p-value', values)
        self.assertIn('Delta mean', values)
        self.assertIn('Difference', values)
        self.assertIn('YES', values)
        self.assertIn('DIFFERENCE', values)
        text_values = [str(value).upper() for value in values]
        self.assertNotIn('TRUE', text_values)
        self.assertNotIn('FALSE', text_values)
        self.assertEqual(worksheet.frozen, (1, 0))

    def test_group_analysis_diagnostics_sheet_smoke(self):
        worksheet = FakeWorksheet()
        payload = {
            'requested_scope': 'auto',
            'requested_level': 'standard',
            'execution_status': 'ran',
            'effective_scope': 'single_reference',
            'reference_count': 1,
            'group_count': 2,
            'metric_count': 1,
            'skipped_metric_count': 1,
            'warning_summary': {
                'count': 2,
                'messages': ['M1: pairwise disabled'],
                'skip_reason_counts': {'nom_mismatch': 1},
            },
            'histogram_skip_summary': {'applies': True, 'count': 1, 'reason_counts': {'nom_mismatch': 1}},
            'unmatched_metrics_summary': {
                'count': 1,
                'metrics': [
                    {'metric': 'M2', 'present_references': ['R1'], 'missing_references': ['R2']},
                ],
            },
            'skip_reason': None,
            'metrics': [
                {
                    'metric': 'M1',
                    'reference': 'R1',
                    'group_count': 2,
                    'spec_status': 'EXACT_MATCH',
                    'pairwise_rows': [{'group_a': 'A', 'group_b': 'B'}],
                }
            ],
            'skipped_metrics': [{'metric': 'M2', 'reason': 'insufficient_groups'}],
        }

        write_group_analysis_diagnostics_sheet(worksheet, payload)

        values = [value for _, _, value in worksheet.writes]
        self.assertIn('Group Analysis Diagnostics', values)
        self.assertIn('Warning summary', values)
        self.assertIn('Histogram skip summary', values)
        self.assertIn('Possible unmatched metrics across references', values)
        self.assertIn('standard', values)
        self.assertIn('ran', values)
        self.assertIn('Metric coverage', values)
        self.assertIn('Groups', values)
        self.assertIn('Spec status', values)
        self.assertIn('Pairwise comparisons', values)
        self.assertIn('Included in Light', values)
        self.assertIn('Included in Standard', values)
        self.assertIn('Comment', values)
        self.assertIn('M2', values)
        self.assertIn('M1: pairwise disabled', values)
        self.assertIn('nom_mismatch=1', values)
        self.assertEqual(worksheet.frozen, (1, 0))


if __name__ == '__main__':
    unittest.main()

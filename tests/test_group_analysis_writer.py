import unittest

from modules.group_analysis_writer import (
    write_group_analysis_diagnostics_sheet,
    write_group_analysis_sheet,
)


class FakeWorkbook:
    def __init__(self):
        self.formats = []

    def add_format(self, props):
        fmt = {'props': dict(props)}
        self.formats.append(fmt)
        return fmt


class FakeWorksheet:
    def __init__(self):
        self.writes = []
        self.frozen = None
        self.book = FakeWorkbook()
        self.conditional_formats = []

    def write(self, row, col, value, *args, **kwargs):
        self.writes.append((row, col, value))

    def freeze_panes(self, row, col):
        self.frozen = (row, col)

    def conditional_format(self, first_row, first_col, last_row, last_col, options):
        self.conditional_formats.append((first_row, first_col, last_row, last_col, dict(options)))


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
                            'comment': 'USE CAUTION',
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
        self.assertIn('USE CAUTION', values)
        text_values = [str(value).upper() for value in values]
        self.assertNotIn('TRUE', text_values)
        self.assertNotIn('FALSE', text_values)
        self.assertEqual(worksheet.frozen, (1, 0))

        pairwise_rules = [
            rule
            for rule in worksheet.conditional_formats
            if rule[1] in {2, 3, 6, 7}
        ]
        self.assertGreaterEqual(len(pairwise_rules), 6)
        self.assertTrue(any(r[4].get('criteria') == 'containing' and r[4].get('value') == 'YES' for r in pairwise_rules))
        self.assertTrue(any(r[4].get('criteria') == '<' and r[4].get('value') == 0.01 for r in pairwise_rules))

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
            'status_counts': {
                'EXACT_MATCH': 3,
                'LIMIT_MISMATCH': 2,
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
        self.assertIn('Spec status counts', values)
        self.assertIn('Status key', values)
        self.assertIn('Status', values)
        self.assertIn('Count', values)
        self.assertIn('EXACT_MATCH', values)
        self.assertIn('LIMIT_MISMATCH', values)
        self.assertIn('NOM_MISMATCH', values)
        self.assertIn('INVALID_SPEC', values)
        self.assertIn('Exact match', values)
        self.assertIn('Limits differ', values)
        self.assertIn('Nominal differs', values)
        self.assertIn('Spec missing / Invalid spec.', values)
        self.assertIn(3, values)
        self.assertIn(2, values)
        status_count_by_key = {
            key_value: next(
                value
                for write_row, write_col, value in worksheet.writes
                if write_row == row and write_col == 2
            )
            for row, col, key_value in worksheet.writes
            if col == 0 and key_value in {'EXACT_MATCH', 'LIMIT_MISMATCH', 'NOM_MISMATCH', 'INVALID_SPEC'}
        }
        self.assertEqual(
            status_count_by_key,
            {
                'EXACT_MATCH': 3,
                'LIMIT_MISMATCH': 2,
                'NOM_MISMATCH': 0,
                'INVALID_SPEC': 0,
            },
        )
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

        coverage_rules = [rule for rule in worksheet.conditional_formats if rule[1] in {2, 4, 5, 6}]
        self.assertGreaterEqual(len(coverage_rules), 13)
        self.assertTrue(any(r[1] == 4 and r[4].get('value') == 'YES' for r in coverage_rules))
        self.assertTrue(any(r[1] == 5 and r[4].get('value') == 'NO' for r in coverage_rules))
        self.assertTrue(any(r[1] == 2 and r[4].get('value') == 'Spec missing' for r in coverage_rules))


if __name__ == '__main__':
    unittest.main()

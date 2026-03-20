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
        self.write_formats = {}
        self.frozen = None
        self.book = FakeWorkbook()
        self.conditional_formats = []
        self.images = []
        self.charts = []
        self.columns = []
        self.rows = []
        self.gridlines_hidden = None
        self.autofilters = []
        self.merges = []
        self.urls = []
        self.formulas = []

    def write(self, row, col, value, *args, **kwargs):
        self.writes.append((row, col, value))
        if args:
            self.write_formats[(row, col)] = args[0]

    def freeze_panes(self, row, col):
        self.frozen = (row, col)

    def conditional_format(self, first_row, first_col, last_row, last_col, options):
        self.conditional_formats.append((first_row, first_col, last_row, last_col, dict(options)))

    def set_column(self, first_col, last_col, width=None, cell_format=None, options=None):
        self.columns.append((first_col, last_col, width, cell_format, dict(options or {})))

    def set_row(self, row, height=None, cell_format=None, options=None):
        self.rows.append((row, height, cell_format, dict(options or {})))

    def hide_gridlines(self, option):
        self.gridlines_hidden = option

    def autofilter(self, first_row, first_col, last_row, last_col):
        self.autofilters.append((first_row, first_col, last_row, last_col))

    def insert_image(self, row, col, path, options=None):
        self.images.append((row, col, path, dict(options or {})))

    def insert_chart(self, row, col, chart):
        self.charts.append((row, col, chart))

    def merge_range(self, first_row, first_col, last_row, last_col, value, cell_format=None):
        self.merges.append((first_row, first_col, last_row, last_col, value, cell_format))
        self.writes.append((first_row, first_col, value))
        if cell_format is not None:
            self.write_formats[(first_row, first_col)] = cell_format

    def write_url(self, row, col, url, cell_format=None, string=None, tip=None):
        self.urls.append((row, col, url, string, tip))
        self.writes.append((row, col, string or url))
        if cell_format is not None:
            self.write_formats[(row, col)] = cell_format

    def write_formula(self, row, col, formula, cell_format=None, value=None):
        self.formulas.append((row, col, formula, value))
        self.writes.append((row, col, value if value is not None else formula))
        if cell_format is not None:
            self.write_formats[(row, col)] = cell_format


class TestGroupAnalysisWriter(unittest.TestCase):
    def test_group_analysis_sheet_smoke(self):
        worksheet = FakeWorksheet()
        payload = {
            'status': 'ready',
            'analysis_level': 'standard',
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
                            'comment': 'caution',
                            'takeaway': 'These groups show a reliable difference after correction. The practical gap looks moderate.',
                            'suggested_action': 'Review process differences, then confirm the gap matters operationally before changing settings.',
                            'flags': 'LOW N; IMBALANCED N',
                            'test_rationale': 'Chosen because only two groups are compared.',
                        }
                    ],
                    'metric_note': 'Shape note: spread or pattern differs across groups, not just the average.',
                    'recommended_action': 'Recommended action: start with A vs B and verify likely process drivers before changing settings.',
                    'plot_eligibility': {
                        'violin': {'eligible': True, 'skip_reason': ''},
                        'histogram': {'eligible': False, 'skip_reason': 'low_total_samples'},
                    },
                    'insights': ['Line 1', 'Line 2', 'Distribution shape: Distinct tails across groups.'],
                }
            ],
        }

        write_group_analysis_sheet(worksheet, payload)

        values = [value for _, _, value in worksheet.writes]
        self.assertIn('Group Analysis', values)
        self.assertIn('Metric index', values)
        self.assertIn('Metric: M1', values)
        self.assertIn('Metric overview', values)
        self.assertIn('Descriptive stats', values)
        self.assertIn('Spec status', values)
        self.assertIn('Exact match', values)
        self.assertIn('Pairwise comparisons', values)
        self.assertIn('Why this test', values)
        self.assertIn('adj p-value', values)
        self.assertIn('Delta mean', values)
        self.assertIn('difference', values)
        self.assertIn('DIFFERENCE', values)
        self.assertIn('caution', values)
        self.assertIn('Takeaway', values)
        self.assertIn('Suggested action', values)
        self.assertIn('Recommended action', values)
        self.assertIn('Shape note: spread or pattern differs across groups, not just the average.', values)
        self.assertIn('Recommended action: start with A vs B and verify likely process drivers before changing settings.', values)
        self.assertIn('These groups show a reliable difference after correction. The practical gap looks moderate.', values)
        self.assertIn('Review process differences, then confirm the gap matters operationally before changing settings.', values)
        self.assertIn('Flags', values)
        self.assertIn('LOW N; IMBALANCED N', values)
        self.assertIn('Chosen because only two groups are compared.', values)
        self.assertIn('Plots', values)
        self.assertIn('Violin', values)
        self.assertIn('Histogram', values)
        self.assertIn('Not enough total samples to show this plot.', values)

        text_values = [str(value).upper() for value in values]
        self.assertNotIn('TRUE', text_values)
        self.assertNotIn('FALSE', text_values)
        self.assertIsNone(worksheet.frozen)
        self.assertEqual(worksheet.gridlines_hidden, 2)
        self.assertEqual(worksheet.columns[0][:3], (0, 0, 18))
        self.assertEqual(worksheet.columns[-1][:3], (14, 14, 16))
        self.assertTrue(any(row == 0 and height == 28 for row, height, *_ in worksheet.rows))
        metric_row = next(row for row, col, value in worksheet.writes if col == 0 and value == 'Metric: M1')
        self.assertFalse(worksheet.write_formats[(metric_row, 0)].get('props', {}).get('text_wrap'))
        self.assertTrue(any(merge[:5] == (metric_row, 0, metric_row, 14, 'Metric: M1') for merge in worksheet.merges))
        take_row = next(
            row
            for row, col, value in worksheet.writes
            if col == 1 and isinstance(value, str) and value.startswith('A vs B: DIFFERENCE.')
        )
        self.assertTrue(worksheet.write_formats[(take_row, 1)].get('props', {}).get('text_wrap'))
        note_row_heights = [
            height
            for row, height, *_ in worksheet.rows
            if row == take_row
        ]
        self.assertTrue(note_row_heights)
        self.assertGreaterEqual(note_row_heights[-1], 30)
        self.assertTrue(any(row == metric_row and height >= 28 for row, height, *_ in worksheet.rows))
        self.assertGreaterEqual(len(worksheet.autofilters), 2)
        self.assertTrue(
            any("HYPERLINK(" in formula[2] for formula in worksheet.formulas)
            or any(url[2].startswith("internal:'Group Analysis'!A") for url in worksheet.urls)
        )

        pairwise_rules = [
            rule
            for rule in worksheet.conditional_formats
            if rule[1] in {2, 3, 6, 7, 10}
        ]
        self.assertGreaterEqual(len(pairwise_rules), 10)
        self.assertTrue(any(r[4].get('criteria') == 'containing' and r[4].get('value') == 'YES' for r in pairwise_rules))
        self.assertTrue(any(r[4].get('criteria') == '<' and r[4].get('value') == 0.01 for r in pairwise_rules))
        self.assertTrue(any(r[4].get('criteria') == 'containing' and r[4].get('value') == 'LOW N' for r in pairwise_rules))
        delta_mean_rules = [
            rule
            for rule in worksheet.conditional_formats
            if rule[1] == 5 and rule[3] == 5 and rule[4].get('type') == 'no_blanks'
        ]
        self.assertTrue(delta_mean_rules)
        self.assertEqual(delta_mean_rules[0][4].get('format', {}).get('props', {}).get('num_format'), '0.000')

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
        self.assertIn('Group Analysis Internal Diagnostics', values)
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

    def test_standard_level_inserts_images_for_eligible_plots_and_keeps_row_progression(self):
        worksheet = FakeWorksheet()
        payload = {
            'status': 'ready',
            'analysis_level': 'standard',
            'effective_scope': 'single_reference',
            'metric_rows': [
                {
                    'metric': 'M1',
                    'group_count': 2,
                    'spec_status': 'EXACT_MATCH',
                    'descriptive_stats': [],
                    'pairwise_rows': [],
                    'insights': ['M1 insight'],
                    'plot_eligibility': {
                        'violin': {'eligible': True, 'skip_reason': ''},
                        'histogram': {'eligible': True, 'skip_reason': ''},
                    },
                },
                {
                    'metric': 'M2',
                    'group_count': 2,
                    'spec_status': 'EXACT_MATCH',
                    'descriptive_stats': [],
                    'pairwise_rows': [],
                    'insights': ['M2 insight'],
                    'plot_eligibility': {
                        'violin': {'eligible': False, 'skip_reason': 'low_group_samples'},
                        'histogram': {'eligible': True, 'skip_reason': ''},
                    },
                },
            ],
        }
        plot_assets = {
            'metrics': {
                'M1': {
                    'violin': {'path': 'violin.png', 'row_span': 4},
                    'histogram': {'path': 'histogram.png', 'row_span': 3},
                }
            }
        }

        write_group_analysis_sheet(worksheet, payload, plot_assets=plot_assets)

        inserted_paths = [entry[2] for entry in worksheet.images]
        self.assertEqual(inserted_paths, ['violin.png', 'histogram.png'])
        self.assertEqual(len(worksheet.charts), 0)

        values = [value for _, _, value in worksheet.writes]
        self.assertNotIn('Shown', values)
        self.assertNotIn('Shown below.', values)

        m2_metric_row = next(
            row
            for row, col, value in worksheet.writes
            if col == 0 and value == 'Metric: M2'
        )
        self.assertGreaterEqual(m2_metric_row, 30)

        values = [value for _, _, value in worksheet.writes]
        self.assertIn('Plot could not be shown because the image asset is unavailable.', values)
        self.assertIn('Not enough samples in one or more groups.', values)

    def test_standard_level_ineligible_plots_emit_explicit_skip_reasons(self):
        worksheet = FakeWorksheet()
        payload = {
            'status': 'ready',
            'analysis_level': 'standard',
            'effective_scope': 'single_reference',
            'metric_rows': [
                {
                    'metric': 'M1',
                    'group_count': 2,
                    'spec_status': 'EXACT_MATCH',
                    'descriptive_stats': [],
                    'pairwise_rows': [],
                    'insights': ['M1 insight'],
                    'plot_eligibility': {
                        'violin': {'eligible': False, 'skip_reason': 'low_group_samples'},
                        'histogram': {'eligible': False, 'skip_reason': 'low_total_samples'},
                    },
                }
            ],
        }

        write_group_analysis_sheet(worksheet, payload, plot_assets={'metrics': {'M1': {}}})

        self.assertEqual(worksheet.images, [])
        self.assertEqual(worksheet.charts, [])

        note_rows = {
            label: next(
                value
                for write_row, write_col, value in worksheet.writes
                if write_row == row + 1 and write_col == 1
            )
            for row, col, label in worksheet.writes
            if col == 0 and label in {'Violin', 'Histogram'}
        }
        self.assertEqual(note_rows['Violin'], 'Not enough samples in one or more groups.')
        self.assertEqual(note_rows['Histogram'], 'Not enough total samples to show this plot.')


if __name__ == '__main__':
    unittest.main()

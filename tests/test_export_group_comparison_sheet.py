import unittest
from tempfile import TemporaryDirectory

import pandas as pd

from modules.characteristic_alias_service import ensure_characteristic_alias_schema, upsert_characteristic_alias
from modules.export_group_comparison_writer import (
    _build_insights,
    _build_pairwise_display_rows,
    _build_pairwise_group_matrices,
    _write_matrix,
    prepare_group_comparison_payload,
    write_group_comparison_sheet,
)


class FakeChart:
    def __init__(self, spec):
        self.spec = spec
        self.series = []
        self.legend = None
        self.size = None
        self.title = None

    def add_series(self, spec):
        self.series.append(spec)

    def set_title(self, title):
        self.title = title

    def set_legend(self, legend):
        self.legend = legend

    def set_size(self, size):
        self.size = size

    def set_x_axis(self, axis):
        self.x_axis = axis

    def set_y_axis(self, axis):
        self.y_axis = axis


class FakeWorkbook:
    def __init__(self):
        self.charts = []

    def add_chart(self, spec):
        chart = FakeChart(spec)
        self.charts.append(chart)
        return chart


class FakeWorksheet:
    def __init__(self):
        self.writes = []
        self.conditional_formats = []
        self.columns = []
        self.frozen = None
        self.name = 'Group Comparison'
        self.book = FakeWorkbook()
        self.inserted_charts = []

    def write(self, row, col, value, *args, **kwargs):
        self.writes.append((row, col, value))

    def conditional_format(self, first_row, first_col, last_row, last_col, options):
        self.conditional_formats.append((first_row, first_col, last_row, last_col, dict(options)))

    def set_column(self, first_col, last_col, width, *args, **kwargs):
        self.columns.append((first_col, last_col, width))

    def freeze_panes(self, row, col):
        self.frozen = (row, col)

    def insert_chart(self, row, col, chart, options=None):
        self.inserted_charts.append((row, col, chart, options or {}))


class TestExportGroupComparisonSheet(unittest.TestCase):
    def test_prepare_payload_resolves_metric_aliases_before_grouping(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['REF-1', 'REF-1', 'REF-1', 'REF-1'],
                'HEADER - AX': ['DIA - X'] * 4,
                'MEAS': [10.0, 10.1, 9.8, 9.9],
                'GROUP': ['A', 'A', 'B', 'B'],
            }
        )

        with TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='DIAMETER - X',
                scope_type='reference',
                scope_value='REF-1',
            )
            payload = prepare_group_comparison_payload(grouped_df, alias_db_path=db_path)

        self.assertEqual(payload['pairwise_rows'][0]['Metric'], 'DIAMETER - X')

    def test_prepare_payload_prefers_reference_alias_over_global_alias(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['REF-1', 'REF-1', 'REF-1', 'REF-1'],
                'HEADER - AX': ['DIA - X'] * 4,
                'MEAS': [10.0, 10.1, 9.8, 9.9],
                'GROUP': ['A', 'A', 'B', 'B'],
            }
        )

        with TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='GLOBAL DIA',
                scope_type='global',
            )
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='REF DIA',
                scope_type='reference',
                scope_value='REF-1',
            )
            payload = prepare_group_comparison_payload(grouped_df, alias_db_path=db_path)

        self.assertEqual(payload['pairwise_rows'][0]['Metric'], 'REF DIA')


    def test_prepare_payload_keeps_original_metric_when_no_alias_mapping_exists(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['REF-2', 'REF-2', 'REF-2', 'REF-2'],
                'HEADER - AX': ['CYL - Y'] * 4,
                'MEAS': [5.0, 5.1, 5.2, 5.3],
                'GROUP': ['A', 'A', 'B', 'B'],
            }
        )

        payload = prepare_group_comparison_payload(grouped_df, alias_db_path=None)

        self.assertEqual(payload['pairwise_rows'][0]['Metric'], 'CYL - Y')

    def test_writer_renders_top_down_sections_summary_and_freeze_target(self):
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
        expected_order = [
            'Summary Block',
            'Location / Central-Tendency Tests',
            'Location / Central-Tendency Summary',
            'Location / Central-Tendency Test Details',
            'Location / Central-Tendency Pairwise Comparison Table',
            'Distribution Shape Section',
            'Distribution Shape Profile By Group',
            'Distribution Shape Summary',
            'Distribution Shape Pairwise Table',
            'Matrices',
            'Location Significance Matrix (Adjusted P-Values)',
            "Pairwise Cliff's delta Matrix (|δ|)",
            'Notes',
        ]
        order_positions = [titles.index(title) for title in expected_order]
        self.assertEqual(order_positions, sorted(order_positions))

        writes_by_cell = {(row, col): value for row, col, value in worksheet.writes}
        self.assertEqual(writes_by_cell[(1, 0)], 'Metric counts')
        self.assertEqual(writes_by_cell[(2, 0)], 'Groups analyzed')
        self.assertEqual(writes_by_cell[(3, 0)], 'Correction method')
        self.assertEqual(writes_by_cell[(4, 0)], 'Correction policy')
        self.assertEqual(writes_by_cell[(5, 0)], 'Per-metric omnibus test / p-value')
        self.assertEqual(writes_by_cell[(6, 0)], 'Significant adjusted pairwise location findings')
        self.assertEqual(writes_by_cell[(7, 0)], 'Strongest practical location effect')
        self.assertEqual(writes_by_cell[(8, 0)], 'Warnings / assumptions')

        pairwise_header_row = next(
            row for row, col, value in worksheet.writes
            if value == 'Metric' and writes_by_cell.get((row - 1, 0)) == 'Location / Central-Tendency Pairwise Comparison Table'
        )
        self.assertEqual(worksheet.frozen, (pairwise_header_row, 0))
        self.assertEqual(len(worksheet.conditional_formats), 2)

        pairwise_headers = [
            writes_by_cell[(pairwise_header_row, col)] for col in range(10)
        ]
        self.assertEqual(
            pairwise_headers,
            [
                'Metric',
                'Group A',
                'Group B',
                'Pairwise test',
                'Adjusted p-value',
                'Pairwise effect size',
                'Effect type',
                'Delta mean or median',
                'Practical interpretation',
                'Flags / comments',
            ],
        )

    def test_non_parametric_two_group_labels_use_cliffs_delta_metadata(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['DIA - X'] * 10,
                'MEAS': [0.0, 0.0, 0.0, 10.0, 10.0, 1.0, 1.0, 1.0, 11.0, 11.0],
                'GROUP': ['A'] * 5 + ['B'] * 5,
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        titles = [value for _, _, value in worksheet.writes if isinstance(value, str)]
        self.assertIn("Pairwise Cliff's delta Matrix (|δ|)", titles)
        self.assertIn(('Large effects (|δ| >= 0.474)', 1), payload['overall_summary'])
        self.assertIn('pairwise_effect_type', payload['pairwise_rows'][0])
        self.assertEqual(payload['pairwise_rows'][0]['pairwise_effect_type'], 'cliffs_delta')
        self.assertTrue(any("Cliff's delta" in value for value in titles if value.startswith('• ')))

    def test_multi_group_labels_include_pairwise_and_omnibus_effect_metadata(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['DIA - X'] * 15,
                'MEAS': [
                    0.0, 0.1, -0.1, 0.05, -0.05,
                    0.4, 0.5, 0.45, 0.55, 0.5,
                    2.0, 2.1, 1.9, 2.05, 1.95,
                ],
                'GROUP': ['A'] * 5 + ['B'] * 5 + ['C'] * 5,
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        titles = [value for _, _, value in worksheet.writes if isinstance(value, str)]
        self.assertIn("Pairwise Cohen's d Matrix (|d|)", titles)
        self.assertIn(('Large effects (|d| >= 0.8)', 3), payload['overall_summary'])
        self.assertEqual(payload['effect_reporting']['pairwise_effect_types'], ['cohen_d'])
        self.assertEqual(payload['effect_reporting']['omnibus_effect_types'], ['eta_squared'])
        self.assertIn('pairwise_effect_type', payload['pairwise_rows'][0])
        self.assertIn('omnibus_effect_type', payload['pairwise_rows'][0])
        note_lines = [value for _, _, value in worksheet.writes if isinstance(value, str) and value.startswith('• ')]
        self.assertTrue(any("Cohen's d" in value for value in note_lines))
        self.assertTrue(any('eta squared' in value for value in note_lines))

    def test_writer_registers_visible_conditional_format_palettes(self):
        matrix = pd.DataFrame([[float('nan'), 0.03], [0.03, float('nan')]], index=['A', 'B'], columns=['A', 'B'])
        payload = {
            'metadata': [],
            'overall_summary': [],
            'overall_test_rows': [],
            'pairwise_rows': [],
            'distribution_profile_rows': [],
            'distribution_difference_rows': [],
            'distribution_pairwise_rows': [],
            'significance_matrices': {'M1': matrix},
            'effect_matrices': {'M1': matrix},
            'effect_reporting': {'pairwise_effect_bands': (0.2, 0.5)},
            'insights': [],
        }
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        self.assertEqual(len(worksheet.conditional_formats), 2)
        significance_rule = worksheet.conditional_formats[0][4]
        effect_rule = worksheet.conditional_formats[1][4]

        self.assertEqual(significance_rule['type'], '3_color_scale')
        self.assertEqual(significance_rule['min_value'], 0)
        self.assertEqual(significance_rule['mid_value'], 0.01)
        self.assertEqual(significance_rule['max_value'], 0.05)
        self.assertIn('min_color', significance_rule)
        self.assertIn('mid_color', significance_rule)
        self.assertIn('max_color', significance_rule)

        self.assertEqual(effect_rule['type'], '3_color_scale')
        self.assertEqual(effect_rule['min_value'], 0)
        self.assertEqual(effect_rule['mid_value'], 0.2)
        self.assertEqual(effect_rule['max_value'], 0.5)
        self.assertIn('min_color', effect_rule)
        self.assertIn('mid_color', effect_rule)
        self.assertIn('max_color', effect_rule)
        self.assertNotEqual(
            (significance_rule['min_color'], significance_rule['mid_color'], significance_rule['max_color']),
            (effect_rule['min_color'], effect_rule['mid_color'], effect_rule['max_color']),
        )


    def test_write_matrix_sanitizes_non_finite_values(self):
        matrix = pd.DataFrame(
            [[0.25, float("nan")], [float("inf"), float("-inf")]],
            index=["A", "B"],
            columns=["A", "B"],
        )
        worksheet = FakeWorksheet()

        end_row = _write_matrix(worksheet, 0, 'Metric: M1', matrix, matrix_type='effect')

        writes_by_cell = {(row, col): value for row, col, value in worksheet.writes}
        self.assertEqual(writes_by_cell[(2, 1)], 0.25)
        self.assertIsNone(writes_by_cell[(2, 2)])
        self.assertIsNone(writes_by_cell[(3, 1)])
        self.assertIsNone(writes_by_cell[(3, 2)])
        self.assertEqual(end_row, 6)
        self.assertEqual(len(worksheet.conditional_formats), 1)

    def test_write_matrix_with_non_finite_values_is_deterministic(self):
        matrix = pd.DataFrame(
            [[0.5, float("nan")], [float("inf"), float("-inf")]],
            index=["A", "B"],
            columns=["A", "B"],
        )

        worksheet_first = FakeWorksheet()
        worksheet_second = FakeWorksheet()

        _write_matrix(worksheet_first, 0, 'Metric: M1', matrix, matrix_type='significance')
        _write_matrix(worksheet_second, 0, 'Metric: M1', matrix, matrix_type='significance')

        self.assertEqual(worksheet_first.writes, worksheet_second.writes)
        self.assertEqual(worksheet_first.conditional_formats, worksheet_second.conditional_formats)

    def test_pairwise_matrix_construction_uses_adjusted_p_and_absolute_effect(self):
        pairwise_df = pd.DataFrame(
            [
                {
                    'Metric': 'DIA - X',
                    'Group A': 'A',
                    'Group B': 'B',
                    'adjusted p-value': 0.012,
                    'effect size': -0.6,
                }
            ]
        )

        significance_matrices, effect_matrices = _build_pairwise_group_matrices(pairwise_df)

        sig = significance_matrices['DIA - X']
        effect = effect_matrices['DIA - X']
        self.assertEqual(sig.loc['A', 'B'], 0.012)
        self.assertEqual(sig.loc['B', 'A'], 0.012)
        self.assertTrue(pd.isna(sig.loc['A', 'A']))
        self.assertTrue(pd.isna(sig.loc['B', 'B']))
        self.assertEqual(effect.loc['A', 'B'], 0.6)
        self.assertEqual(effect.loc['B', 'A'], 0.6)
        self.assertTrue(pd.isna(effect.loc['A', 'A']))
        self.assertTrue(pd.isna(effect.loc['B', 'B']))


    def test_prepare_payload_uses_pairwise_effects_for_rows_and_matrices_in_multi_group_case(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['DIA - X'] * 15,
                'MEAS': [
                    0.0, 0.1, -0.1, 0.05, -0.05,
                    0.4, 0.5, 0.45, 0.55, 0.5,
                    2.0, 2.1, 1.9, 2.05, 1.95,
                ],
                'GROUP': ['A'] * 5 + ['B'] * 5 + ['C'] * 5,
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)

        rows_by_pair = {
            (row['Group A'], row['Group B']): row
            for row in payload['pairwise_rows']
            if row['Metric'] == 'DIA - X'
        }
        self.assertEqual(set(rows_by_pair), {('A', 'B'), ('A', 'C'), ('B', 'C')})

        ab = rows_by_pair[('A', 'B')]
        ac = rows_by_pair[('A', 'C')]
        bc = rows_by_pair[('B', 'C')]

        self.assertNotEqual(ab['effect size'], ac['effect size'])
        self.assertNotEqual(ab['effect size'], bc['effect size'])
        self.assertEqual(ab['effect type'], 'cohen_d')
        self.assertEqual(ab['omnibus effect type'], 'eta_squared')
        self.assertIsNotNone(ab['omnibus effect size'])
        self.assertEqual(ab['omnibus effect size'], ac['omnibus effect size'])
        self.assertEqual(ab['omnibus effect size'], bc['omnibus effect size'])

        effect_matrix = payload['effect_matrices']['DIA - X']
        self.assertEqual(effect_matrix.loc['A', 'B'], abs(ab['effect size']))
        self.assertEqual(effect_matrix.loc['A', 'C'], abs(ac['effect size']))
        self.assertEqual(effect_matrix.loc['B', 'C'], abs(bc['effect size']))
        self.assertNotEqual(effect_matrix.loc['A', 'B'], effect_matrix.loc['A', 'C'])

    def test_write_matrix_renders_nan_diagonal_as_blank_cells(self):
        matrix = pd.DataFrame(
            [[float('nan'), 0.2], [0.2, float('nan')]],
            index=['A', 'B'],
            columns=['A', 'B'],
        )
        worksheet = FakeWorksheet()

        _write_matrix(worksheet, 0, 'Metric: M1', matrix, matrix_type='significance')

        writes_by_cell = {(row, col): value for row, col, value in worksheet.writes}
        self.assertIsNone(writes_by_cell[(2, 1)])
        self.assertEqual(writes_by_cell[(2, 2)], 0.2)
        self.assertEqual(writes_by_cell[(3, 1)], 0.2)
        self.assertIsNone(writes_by_cell[(3, 2)])

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
                    'adjusted p-value': 0.03,
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

        self.assertEqual(len(insights), 6)
        self.assertEqual(
            insights[0],
            'Central tendency: highest mean=A (10.000), lowest mean=B (8.000).',
        )
        self.assertIn('Significant pairwise findings:', insights[1])
        self.assertIn('difference:', insights[2])
        self.assertIn('caution (n < 5):', insights[3])
        self.assertIn('Assumption/test-choice notes:', insights[4])
        self.assertIn('distribution shape:', insights[5])


    def test_insights_include_distribution_shape_when_pairwise_rows_are_empty(self):
        working = pd.DataFrame(
            {
                'GROUP': ['A', 'A', 'B', 'B'],
                'MEAS': [10.0, 10.0, 8.0, 8.0],
            }
        )
        pairwise_df = pd.DataFrame()
        overall_test_rows = []
        distribution_summary_rows = [
            {
                'Metric': 'DIA - X',
                'Test used': 'K-S',
                'raw p-value': 0.0123,
                'significant?': 'YES',
            }
        ]

        insights = _build_insights(working, pairwise_df, overall_test_rows, distribution_summary_rows)

        self.assertIn('no pairwise location comparisons available', insights[1])
        self.assertIn('no pairwise location comparisons available', insights[2])
        self.assertIn('no pairwise location comparisons available', insights[3])
        self.assertEqual(
            insights[5],
            'Distribution-shape findings: significant differences detected for DIA - X (K-S, p=0.0123).',
        )


    def test_insights_skip_nan_adjusted_p_values_without_errors(self):
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
                    'adjusted p-value': None,
                    'n(A)': 2,
                    'n(B)': 2,
                },
                {
                    'Metric': 'DIA - Y',
                    'Group A': 'A',
                    'Group B': 'C',
                    'adjusted p-value': 0.031,
                    'n(A)': 2,
                    'n(B)': 2,
                },
                {
                    'Metric': 'DIA - Z',
                    'Group A': 'B',
                    'Group B': 'C',
                    'adjusted p-value': 0.52,
                    'n(A)': 2,
                    'n(B)': 2,
                },
            ]
        )
        overall_test_rows = []

        insights = _build_insights(working, pairwise_df, overall_test_rows)

        self.assertEqual(len(insights), 6)
        self.assertEqual(
            insights[1],
            'Significant pairwise findings: DIA - Y (A vs C, adj p=0.0310).',
        )
        self.assertEqual(
            insights[2],
            'difference: DIA - Z (B vs C, adj p=0.5200).',
        )
        self.assertIn('distribution shape:', insights[5])



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
        self.assertIn(('Alpha', 0.05), payload['metadata'])
        self.assertIn(('Correction method', 'Holm'), payload['metadata'])
        self.assertIn(('Correction policy', 'Strict family-wise error control (Holm)'), payload['metadata'])
        self.assertIn(('Group sample sizes', 'A:1, B:1'), payload['metadata'])
        pairwise_row = payload['pairwise_rows'][0]
        self.assertEqual(pairwise_row['n(A)'], 1)
        self.assertEqual(pairwise_row['n(B)'], 1)



    def test_prepare_payload_includes_method_traceability_fields(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['DIA - X'] * 6,
                'MEAS': [10.0, 10.5, 11.1, 11.4, 12.0, 12.2],
                'GROUP': ['A', 'A', 'B', 'B', 'C', 'C'],
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)

        self.assertTrue(payload['overall_test_rows'])
        per_metric = payload['overall_test_rows'][0]
        self.assertEqual(per_metric['normality check used'], 'Shapiro-Wilk')
        self.assertIn(per_metric['variance test used'], {'Levene', 'Brown-Forsythe'})
        self.assertIn(
            per_metric['post-hoc strategy'],
            {
                'pairwise t-tests + Holm',
                'pairwise Welch t-tests + Holm',
                'pairwise Mann-Whitney + Holm',
            },
        )
        self.assertEqual(per_metric['correction method'], 'Holm')
        self.assertEqual(per_metric['correction policy'], 'Strict family-wise error control (Holm)')
        self.assertIn('omnibus test name', per_metric)
        self.assertIn('assumption outcomes', per_metric)

        self.assertTrue(payload['pairwise_rows'])
        pairwise = payload['pairwise_rows'][0]
        for required in ['Group A', 'Group B', 'test used', 'p-value', 'adjusted p-value', 'effect size', 'significant']:
            self.assertIn(required, pairwise)
        self.assertEqual(pairwise['correction method'], 'Holm')
        self.assertEqual(pairwise['correction policy'], 'Strict family-wise error control (Holm)')
        self.assertIn('pairwise test name', pairwise)
        self.assertIn('omnibus test name', pairwise)
        self.assertIn('assumption outcomes', pairwise)

    def test_prepare_payload_supports_bh_correction_policy_labels(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['M1'] * 15,
                'MEAS': [
                    0.0, 0.1, -0.1, 0.05, -0.05,
                    0.4, 0.5, 0.45, 0.55, 0.5,
                    2.0, 2.1, 1.9, 2.05, 1.95,
                ],
                'GROUP': ['A'] * 5 + ['B'] * 5 + ['C'] * 5,
            }
        )

        payload = prepare_group_comparison_payload(grouped_df, correction_method='bh')
        summary_rows = dict(payload['metadata'])
        display_rows = _build_pairwise_display_rows(payload['pairwise_rows'])

        self.assertEqual(summary_rows['Correction method'], 'Benjamini-Hochberg')
        self.assertEqual(
            summary_rows['Correction policy'],
            'Exploratory false-discovery-rate control (Benjamini-Hochberg/FDR)',
        )
        self.assertTrue(display_rows)
        self.assertTrue(
            all(
                'Correction: Exploratory false-discovery-rate control (Benjamini-Hochberg/FDR)' in row['Flags / comments']
                for row in display_rows
            )
        )

    def test_prepare_payload_surfaces_selection_details_for_tiny_sample_and_constant_groups(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['M1'] * 7,
                'MEAS': [1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 3.0],
                'GROUP': ['A', 'A', 'A', 'B', 'B', 'B', 'C'],
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)

        self.assertEqual(payload['overall_test_rows'][0]['assumption outcomes']['selection_mode'], 'unavailable')
        self.assertIn('fewer than 2 values', payload['overall_test_rows'][0]['assumption outcomes']['selection_detail'])
        self.assertTrue(payload['pairwise_rows'])
        display_rows = _build_pairwise_display_rows(payload['pairwise_rows'])
        self.assertTrue(
            all('Correction: Strict family-wise error control (Holm)' in row['Flags / comments'] for row in display_rows)
        )

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
            'Summary Block',
            'Location / Central-Tendency Tests',
            'Location / Central-Tendency Summary',
            'Location / Central-Tendency Test Details',
            'Location / Central-Tendency Pairwise Comparison Table',
            'Distribution Shape Section',
            'Distribution Shape Profile By Group',
            'Distribution Shape Summary',
            'Distribution Shape Pairwise Table',
            'Matrices',
            'Location Significance Matrix (Adjusted P-Values)',
            "Pairwise Cliff's delta Matrix (|δ|)",
            'Notes',
        ]:
            self.assertIn(title, shared_strings)

    def test_writer_handles_empty_payload(self):
        payload = prepare_group_comparison_payload(pd.DataFrame())
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        self.assertTrue(any(value == 'No rows' for _, _, value in worksheet.writes))
        self.assertTrue(any(value == 'No heatmap data' for _, _, value in worksheet.writes))

    def test_writer_section_names_and_notes_make_location_vs_shape_distinction_explicit(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['M1'] * 8,
                'MEAS': [0.1, 0.2, 0.3, 0.4, 1.5, 1.7, 1.9, 2.2],
                'GROUP': ['A', 'A', 'A', 'A', 'B', 'B', 'B', 'B'],
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        titles = [value for _, _, value in worksheet.writes if isinstance(value, str)]
        self.assertIn('Location / Central-Tendency Pairwise Comparison Table', titles)
        self.assertIn('Distribution Shape Pairwise Table', titles)
        self.assertIn('Location Significance Matrix (Adjusted P-Values)', titles)

        note_lines = [value for _, _, value in worksheet.writes if isinstance(value, str) and value.startswith('• ')]
        self.assertTrue(any('Shape differences can be statistically significant even when mean/median comparisons are not' in value for value in note_lines))
        self.assertTrue(any('adjusted p-values and Wasserstein distance' in value for value in note_lines))
        self.assertTrue(any('Wasserstein practical severity labels' in value for value in note_lines))

    def test_prepare_payload_includes_distribution_sections(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['DIA - X'] * 8,
                'MEAS': [0.1, 0.2, 0.3, 0.4, 1.5, 1.7, 1.9, 2.2],
                'GROUP': ['A', 'A', 'A', 'A', 'B', 'B', 'B', 'B'],
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)

        self.assertTrue(payload['distribution_profile_rows'])
        self.assertTrue(payload['distribution_difference_rows'])
        self.assertTrue(payload['distribution_pairwise_rows'])
        profile = payload['distribution_profile_rows'][0]
        for key in ['Metric', 'Group', 'n', 'best fit model', 'fit quality', 'AD p-value', 'KS p-value', 'GOF acceptable?', 'Support mode', 'Warning / notes summary']:
            self.assertIn(key, profile)

        pairwise = payload['distribution_pairwise_rows'][0]
        self.assertIn('adjusted p-value', pairwise)
        self.assertIn('Wasserstein distance', pairwise)
        self.assertIn('Practical severity', pairwise)

    def test_insights_do_not_claim_no_difference_when_only_shape_differs(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['M1'] * 400,
                'GROUP': ['A'] * 200 + ['B'] * 200,
                'MEAS': [1.0] * 100 + [-1.0] * 100 + [0.0] * 200,
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)
        insights_text = ' '.join(payload['insights'])

        self.assertIn('distribution shape:', insights_text)
        self.assertNotIn('no differences', insights_text.lower())


    def test_writer_renders_group_comparison_chart_section_with_dynamic_anchor(self):
        grouped_df = pd.DataFrame(
            {
                'HEADER - AX': ['DIA - X'] * 6 + ['CYL - Y'] * 6,
                'MEAS': [10.0, 10.2, 9.8, 9.9, 10.4, 10.6, 5.0, 5.3, 5.4, 5.8, 6.0, 6.1],
                'GROUP': ['A', 'A', 'B', 'B', 'C', 'C'] * 2,
            }
        )

        payload = prepare_group_comparison_payload(grouped_df)
        worksheet = FakeWorksheet()

        write_group_comparison_sheet(worksheet, payload)

        titles = [value for _, _, value in worksheet.writes if isinstance(value, str)]
        self.assertIn('Comparison Charts', titles)
        self.assertIn('Ranked Pairwise Effects', titles)
        self.assertIn('Effect vs Adjusted p', titles)
        self.assertEqual(len(worksheet.inserted_charts), 2)
        ranked_anchor = worksheet.inserted_charts[0][0]
        scatter_anchor = worksheet.inserted_charts[1][0]
        shape_section_row = next(row for row, col, value in worksheet.writes if value == 'Distribution Shape Section')
        self.assertLess(ranked_anchor, shape_section_row)
        self.assertLess(scatter_anchor, shape_section_row)
        self.assertEqual(worksheet.inserted_charts[1][2].legend, {'position': 'bottom'})


if __name__ == '__main__':
    unittest.main()

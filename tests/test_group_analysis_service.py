import unittest
from unittest.mock import patch

import pandas as pd

from modules.group_analysis_service import (
    build_group_analysis_payload,
    build_pairwise_rows,
    classify_spec_status,
    classify_metric_spec_status,
    compute_capability_payload,
    normalize_metric_identity,
    normalize_spec_limits,
    evaluate_group_analysis_readiness,
    resolve_group_analysis_scope,
)


class TestGroupAnalysisService(unittest.TestCase):
    @patch('modules.group_analysis_service.compute_pairwise_rows')
    def test_build_pairwise_rows_emits_difference_and_standardized_comment(self, mock_compute_pairwise_rows):
        mock_compute_pairwise_rows.return_value = [
            {
                'group_a': 'A',
                'group_b': 'B',
                'adjusted_p_value': 0.01,
                'effect_size': 0.8,
                'p_value': 0.01,
                'test_used': 'welch_t',
                'significant': True,
            },
            {
                'group_a': 'A',
                'group_b': 'C',
                'adjusted_p_value': 0.4,
                'effect_size': 0.1,
                'p_value': 0.4,
                'test_used': 'welch_t',
                'significant': False,
            },
            {
                'group_a': 'B',
                'group_b': 'C',
                'adjusted_p_value': None,
                'effect_size': None,
                'p_value': None,
                'test_used': 'welch_t',
                'significant': True,
            },
        ]

        rows = build_pairwise_rows(
            'M1',
            {'A': [10.0, 10.1], 'B': [9.7, 9.8], 'C': [9.9, 10.0]},
            pairwise_eligible=True,
        )

        self.assertEqual(rows[0]['difference'], 'YES')
        self.assertEqual(rows[0]['comment'], 'DIFFERENCE')
        self.assertEqual(rows[1]['difference'], 'NO')
        self.assertEqual(rows[1]['comment'], 'NO DIFFERENCE')
        self.assertEqual(rows[2]['difference'], 'YES')
        self.assertEqual(rows[2]['comment'], 'USE CAUTION')
        self.assertNotIn('significant', rows[0])

    @patch('modules.group_analysis_service.compute_pairwise_rows')
    def test_build_pairwise_rows_marks_descriptive_only_when_pairwise_is_ineligible(self, mock_compute_pairwise_rows):
        mock_compute_pairwise_rows.return_value = [
            {
                'group_a': 'A',
                'group_b': 'B',
                'adjusted_p_value': 0.01,
                'effect_size': 0.8,
                'p_value': 0.01,
                'test_used': 'welch_t',
                'significant': True,
            }
        ]

        rows = build_pairwise_rows('M1', {'A': [10.0], 'B': [9.0]}, pairwise_eligible=False)

        self.assertEqual(rows[0]['difference'], 'NO')
        self.assertEqual(rows[0]['comment'], 'DESCRIPTIVE ONLY')

    def test_auto_scope_resolution_uses_reference_cardinality(self):
        self.assertEqual(resolve_group_analysis_scope('auto', 1), 'single_reference')
        self.assertEqual(resolve_group_analysis_scope('auto', 2), 'multi_reference')

    def test_forced_scope_mismatch_returns_canonical_skip_reason(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R2'],
                'GROUP': ['A', 'B'],
                'MEAS': [1.0, 2.0],
                'HEADER': ['M1', 'M1'],
            }
        )

        result = evaluate_group_analysis_readiness(grouped_df, requested_scope='single_reference')

        self.assertFalse(result['runnable'])
        self.assertEqual(result['skip_reason']['code'], 'forced_single_reference_scope_mismatch')
        self.assertEqual(
            result['skip_reason']['message'],
            'Single-reference group analysis skipped: grouped rows span multiple references.',
        )

    def test_forced_multi_reference_scope_mismatch_returns_canonical_skip_reason(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1'],
                'GROUP': ['A', 'B'],
                'MEAS': [1.0, 2.0],
                'HEADER': ['M1', 'M1'],
            }
        )

        result = evaluate_group_analysis_readiness(grouped_df, requested_scope='multi_reference')

        self.assertFalse(result['runnable'])
        self.assertEqual(result['skip_reason']['code'], 'forced_multi_reference_scope_mismatch')
        self.assertEqual(
            result['skip_reason']['message'],
            'Multi-reference group analysis skipped: grouped rows span only one reference.',
        )

    def test_metric_identity_includes_reference_for_multi_scope(self):
        self.assertEqual(
            normalize_metric_identity('DIA - X', 'REF-A', scope='multi_reference'),
            'REF-A :: DIA - X',
        )
        self.assertEqual(normalize_metric_identity('DIA - X', 'REF-A', scope='single_reference'), 'DIA - X')

    def test_spec_normalization_and_status_classification(self):
        spec = normalize_spec_limits('1.23456', 2, '3.4567')
        self.assertEqual(spec, {'lsl': 1.235, 'nominal': 2.0, 'usl': 3.457})
        self.assertEqual(classify_spec_status(spec), 'EXACT_MATCH')
        self.assertEqual(classify_spec_status({'lsl': None, 'nominal': None, 'usl': None}), 'INVALID_SPEC')
        self.assertEqual(classify_spec_status({'lsl': 1.0, 'nominal': None, 'usl': 3.0}), 'INVALID_SPEC')

    def test_classify_metric_spec_status_detects_mismatch_types(self):
        metric_rows_df = pd.DataFrame(
            {
                'LSL': [1.0, 1.0],
                'NOMINAL': [2.0, 2.2],
                'USL': [3.0, 3.0],
            }
        )
        status, _ = classify_metric_spec_status(
            metric_rows_df,
            {'lsl': 'LSL', 'nominal': 'NOMINAL', 'usl': 'USL'},
        )
        self.assertEqual(status, 'NOM_MISMATCH')

        metric_rows_df['NOMINAL'] = [2.0, 2.0]
        metric_rows_df['USL'] = [3.0, 3.1]
        status, _ = classify_metric_spec_status(
            metric_rows_df,
            {'lsl': 'LSL', 'nominal': 'NOMINAL', 'usl': 'USL'},
        )
        self.assertEqual(status, 'LIMIT_MISMATCH')

    def test_capability_payload_marks_not_applicable_without_valid_spec(self):
        payload = compute_capability_payload([1.0, 1.1, 1.2], {'lsl': None, 'nominal': None, 'usl': None})
        self.assertEqual(payload['status'], 'not_applicable')
        self.assertIsNone(payload['cp'])
        self.assertIsNone(payload['capability'])
        self.assertIsNone(payload['cpk'])

    def test_capability_payload_bilateral_mode_returns_cp_and_cpk(self):
        payload = compute_capability_payload([9.9, 10.0, 10.1, 10.2], {'lsl': 9.0, 'nominal': 10.0, 'usl': 11.0})

        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['capability_mode'], 'bilateral')
        self.assertEqual(payload['capability_type'], 'Cpk')
        self.assertIsNotNone(payload['cp'])
        self.assertIsNotNone(payload['capability'])
        self.assertIsNotNone(payload['cpk'])

    def test_capability_payload_upper_only_mode_returns_cpk_plus(self):
        payload = compute_capability_payload([9.9, 10.0, 10.1, 10.2], {'lsl': None, 'nominal': 10.0, 'usl': 11.0})

        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['capability_mode'], 'upper_only')
        self.assertEqual(payload['capability_type'], 'Cpk+')
        self.assertIsNone(payload['cp'])
        self.assertIsNotNone(payload['capability'])
        self.assertEqual(payload['capability'], payload['cpk'])

    def test_capability_payload_lower_only_mode_returns_cpk_minus(self):
        payload = compute_capability_payload([9.9, 10.0, 10.1, 10.2], {'lsl': 9.0, 'nominal': 10.0, 'usl': None})

        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['capability_mode'], 'lower_only')
        self.assertEqual(payload['capability_type'], 'Cpk-')
        self.assertIsNone(payload['cp'])
        self.assertIsNotNone(payload['capability'])
        self.assertEqual(payload['capability'], payload['cpk'])

    def test_capability_payload_forces_not_applicable_for_non_positive_sigma(self):
        payload = compute_capability_payload([1.0, 1.0, 1.0], {'lsl': 0.0, 'nominal': 1.0, 'usl': 2.0})

        self.assertEqual(payload['status'], 'not_applicable')
        self.assertEqual(payload['capability_mode'], 'bilateral')
        self.assertIsNone(payload['cp'])
        self.assertIsNone(payload['capability'])
        self.assertIsNone(payload['cpk'])

    def test_capability_payload_forces_not_applicable_for_invalid_limit_order(self):
        payload = compute_capability_payload([1.0, 1.1, 1.2], {'lsl': 3.0, 'nominal': 2.0, 'usl': 1.0})

        self.assertEqual(payload['status'], 'not_applicable')
        self.assertEqual(payload['capability_mode'], 'bilateral')
        self.assertIsNone(payload['cp'])
        self.assertIsNone(payload['capability'])
        self.assertIsNone(payload['cpk'])

    def test_build_payload_includes_descriptive_pairwise_and_diagnostics(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1', 'R1', 'R1'],
                'HEADER - AX': ['M1', 'M1', 'M1', 'M1'],
                'GROUP': ['A', 'A', 'B', 'B'],
                'MEAS': [10.0, 10.2, 9.7, 9.6],
                'LSL': [9.0, 9.0, 9.0, 9.0],
                'NOMINAL': [10.0, 10.0, 10.0, 10.0],
                'USL': [11.0, 11.0, 11.0, 11.0],
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='light')

        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(payload['effective_scope'], 'single_reference')
        self.assertEqual(len(payload['metric_rows']), 1)
        metric = payload['metric_rows'][0]
        self.assertEqual(metric['metric'], 'M1')
        self.assertEqual(metric['spec_status'], 'EXACT_MATCH')
        self.assertEqual(len(metric['descriptive_stats']), 2)
        self.assertEqual(len(metric['pairwise_rows']), 1)
        self.assertIn('comparability_summary', metric)
        self.assertGreaterEqual(len(metric.get('insights', [])), 1)
        self.assertIn('median', metric['descriptive_stats'][0])
        self.assertIn('iqr', metric['descriptive_stats'][0])
        self.assertIn('flags', metric['descriptive_stats'][0])
        self.assertIn('delta_mean', metric['pairwise_rows'][0])
        self.assertIn('difference', metric['pairwise_rows'][0])
        self.assertIn('comment', metric['pairwise_rows'][0])
        self.assertNotIn('significant', metric['pairwise_rows'][0])
        self.assertEqual(payload['diagnostics']['metric_count'], 1)
        self.assertEqual(payload['diagnostics']['status_counts']['EXACT_MATCH'], 1)
        self.assertEqual(payload['diagnostics']['requested_level'], 'light')
        self.assertEqual(payload['diagnostics']['execution_status'], 'ran')
        self.assertEqual(payload['diagnostics']['group_count'], 2)
        self.assertEqual(payload['diagnostics']['warning_summary']['count'], 0)
        self.assertEqual(payload['diagnostics']['histogram_skip_summary']['applies'], False)
        self.assertEqual(payload['diagnostics']['unmatched_metrics_summary']['count'], 0)

    def test_standard_level_skips_non_exact_match_metrics(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1', 'R1', 'R1'],
                'HEADER - AX': ['M1', 'M1', 'M1', 'M1'],
                'GROUP': ['A', 'A', 'B', 'B'],
                'MEAS': [10.0, 10.2, 9.7, 9.6],
                'LSL': [9.0, 9.0, 9.0, 9.0],
                'NOMINAL': [10.0, 10.0, 10.1, 10.1],
                'USL': [11.0, 11.0, 11.0, 11.0],
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='standard')

        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(len(payload['metric_rows']), 0)
        self.assertEqual(payload['diagnostics']['skipped_metric_count'], 1)
        self.assertEqual(payload['diagnostics']['status_counts']['EXACT_MATCH'], 0)
        self.assertEqual(payload['diagnostics']['requested_level'], 'standard')
        self.assertEqual(payload['diagnostics']['execution_status'], 'ran')
        self.assertEqual(payload['diagnostics']['histogram_skip_summary']['applies'], True)
        self.assertEqual(payload['diagnostics']['histogram_skip_summary']['count'], 1)
        self.assertEqual(payload['diagnostics']['histogram_skip_summary']['reason_counts'], {'nom_mismatch': 1})

    def test_diagnostics_include_warning_and_unmatched_reference_summaries(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1', 'R1', 'R2', 'R2'],
                'HEADER - AX': ['M1', 'M1', 'M2', 'M1', 'M1'],
                'GROUP': ['A', 'B', 'A', 'A', 'B'],
                'MEAS': [10.0, 10.2, 9.5, 10.1, 10.3],
                'LSL': [9.0, 9.1, 9.0, 9.0, 9.0],
                'NOMINAL': [10.0, 10.0, 10.0, 10.0, 10.0],
                'USL': [11.0, 11.0, 11.0, 11.0, 11.0],
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='light')
        diagnostics = payload['diagnostics']

        self.assertEqual(diagnostics['warning_summary']['count'], 2)
        self.assertEqual(len(diagnostics['warning_summary']['messages']), 1)
        self.assertEqual(diagnostics['warning_summary']['skip_reason_counts'], {'insufficient_groups': 1})
        self.assertEqual(diagnostics['unmatched_metrics_summary']['count'], 1)
        self.assertEqual(diagnostics['unmatched_metrics_summary']['metrics'][0]['metric'], 'M2')
        self.assertEqual(diagnostics['unmatched_metrics_summary']['metrics'][0]['missing_references'], ['R2'])


if __name__ == '__main__':
    unittest.main()

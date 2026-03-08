import unittest

import pandas as pd

from modules.group_analysis_service import (
    build_group_analysis_payload,
    classify_spec_status,
    compute_capability_payload,
    normalize_metric_identity,
    normalize_spec_limits,
    evaluate_group_analysis_readiness,
    resolve_group_analysis_scope,
)


class TestGroupAnalysisService(unittest.TestCase):
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
        self.assertIn('single_reference', result['skip_reason']['message'])

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
        self.assertIn('multi_reference', result['skip_reason']['message'])

    def test_metric_identity_includes_reference_for_multi_scope(self):
        self.assertEqual(
            normalize_metric_identity('DIA - X', 'REF-A', scope='multi_reference'),
            'REF-A :: DIA - X',
        )
        self.assertEqual(normalize_metric_identity('DIA - X', 'REF-A', scope='single_reference'), 'DIA - X')

    def test_spec_normalization_and_status_classification(self):
        spec = normalize_spec_limits('1.23456', 2, '3.4567')
        self.assertEqual(spec, {'lsl': 1.235, 'nominal': 2.0, 'usl': 3.457})
        self.assertEqual(classify_spec_status(spec), 'complete')
        self.assertEqual(classify_spec_status({'lsl': None, 'nominal': None, 'usl': None}), 'missing')
        self.assertEqual(classify_spec_status({'lsl': 1.0, 'nominal': None, 'usl': 3.0}), 'partial')

    def test_capability_payload_marks_not_applicable_without_valid_spec(self):
        payload = compute_capability_payload([1.0, 1.1, 1.2], {'lsl': None, 'nominal': None, 'usl': None})
        self.assertEqual(payload['status'], 'not_applicable')
        self.assertIsNone(payload['cp'])
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

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto')

        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(payload['effective_scope'], 'single_reference')
        self.assertEqual(len(payload['metric_rows']), 1)
        metric = payload['metric_rows'][0]
        self.assertEqual(metric['metric'], 'M1')
        self.assertEqual(metric['spec_status'], 'complete')
        self.assertEqual(len(metric['descriptive_stats']), 2)
        self.assertEqual(len(metric['pairwise_rows']), 1)
        self.assertEqual(payload['diagnostics']['metric_count'], 1)


if __name__ == '__main__':
    unittest.main()

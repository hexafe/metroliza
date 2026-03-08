import unittest

import pandas as pd

from modules.group_analysis_service import (
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


if __name__ == '__main__':
    unittest.main()

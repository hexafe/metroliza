import unittest
import warnings
from unittest.mock import patch

import numpy as np

from modules.distribution_shape_analysis import (
    build_distribution_profile_rows,
    build_distribution_profile_rows_compact,
    compute_distribution_difference,
)


class TestDistributionShapeAnalysis(unittest.TestCase):
    def test_same_mean_different_shape_flags_difference(self):
        grouped_values = {
            'A': np.array([-1.0] * 80 + [1.0] * 80),
            'B': np.array([0.0] * 160),
        }
        result = compute_distribution_difference('M1', grouped_values)
        omnibus = result['omnibus_row']

        self.assertEqual(omnibus['significant?'], 'YES')
        self.assertTrue(
            'difference' in omnibus['comment / verdict'].lower()
            or 'caution' in omnibus['comment / verdict'].lower()
        )

    def test_same_family_can_still_show_distribution_difference(self):
        rng = np.random.default_rng(7)
        grouped_values = {
            'A': rng.normal(loc=0.0, scale=0.6, size=180),
            'B': rng.normal(loc=0.0, scale=1.4, size=180),
        }

        result = compute_distribution_difference('M2', grouped_values)
        pair = result['pairwise_rows'][0]

        self.assertGreater(pair['distance metric'], 0.1)
        self.assertEqual(pair['distance metric'], pair['Wasserstein distance'])
        self.assertIn(pair['Practical severity'], {'Low', 'Moderate', 'High'})
        self.assertIn(pair['verdict'], {'difference', 'caution'})

    def test_unreliable_fit_does_not_overclaim(self):
        grouped_values = {
            'A': np.array([1.0, 1.0, 1.0, 1.0]),
            'B': np.array([1.0, 1.2, 1.4, 1.6]),
        }

        result = compute_distribution_difference('M3', grouped_values)
        pair = result['pairwise_rows'][0]

        self.assertNotEqual(pair['verdict'], 'difference')
        self.assertIn(pair['verdict'], {'caution', 'descriptive only', 'no difference'})

    def test_low_sample_inputs_degrade_gracefully(self):
        grouped_values = {'A': np.array([1.0]), 'B': np.array([2.0])}
        result = compute_distribution_difference('M4', grouped_values)

        pair = result['pairwise_rows'][0]
        self.assertEqual(pair['verdict'], 'descriptive only')
        self.assertIn('insufficient data', pair['comment'])


    def test_build_distribution_profile_rows_accepts_precleaned_arrays(self):
        grouped_values = {
            'A': np.array([1.0, 2.0, 3.0], dtype=float),
            'B': np.array([4.0, 5.0, 6.0], dtype=float),
        }

        baseline = build_distribution_profile_rows('M-clean', grouped_values)
        precleaned = build_distribution_profile_rows('M-clean', grouped_values, values_are_clean=True)

        self.assertEqual(baseline, precleaned)

    def test_skip_large_export_policy_preserves_pairwise_nonparametric_comparison(self):
        grouped_values = {
            'A': np.array([0.0] * 40 + [1.0] * 40),
            'B': np.array([0.5] * 80),
        }

        result = compute_distribution_difference(
            'M-policy',
            grouped_values,
            fit_policy={'mode': 'skip_large_exports', 'max_fit_samples_per_metric': 100},
        )

        profile_row = result['profile_rows'][0]
        pairwise_row = result['pairwise_rows'][0]
        self.assertEqual(profile_row['_fit_status'], 'skipped_policy')
        self.assertEqual(profile_row['best fit model'], 'Skipped by policy')
        self.assertIsNotNone(pairwise_row['raw p-value'])
        self.assertIsNotNone(pairwise_row['Wasserstein distance'])

    def test_omnibus_anderson_ksamp_uses_supported_keyword_and_suppresses_known_user_warnings(self):
        grouped_values = {
            'A': np.array([1.0, 2.0, 3.0]),
            'B': np.array([2.0, 3.0, 4.0]),
            'C': np.array([3.0, 4.0, 5.0]),
        }

        with patch('modules.distribution_shape_analysis._anderson_ksamp_supports_variant', return_value=False), \
             patch('modules.distribution_shape_analysis.anderson_ksamp') as mock_anderson:
            def fake_anderson(samples, **kwargs):
                warnings.warn(
                    'p-value floored: true value smaller than 0.001. Consider specifying `method` (e.g. `method=stats.PermutationMethod()`.)',
                    UserWarning,
                )

                class Result:
                    pvalue = 0.0005

                return Result()

            mock_anderson.side_effect = fake_anderson

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                result = compute_distribution_difference('M5', grouped_values)

        self.assertEqual(mock_anderson.call_args.kwargs, {'midrank': True})
        self.assertEqual(result['omnibus_row']['significant?'], 'YES')
        self.assertFalse(any('p-value floored' in str(item.message) for item in caught))



    def test_build_distribution_profile_rows_compact_preserves_worksheet_projection(self):
        grouped_values = {
            'A': np.array([1.0, 2.0, 3.0], dtype=float),
            'B': np.array([4.0, 5.0, 6.0], dtype=float),
        }

        compact = build_distribution_profile_rows_compact('M-compact', grouped_values, values_are_clean=True)
        expanded = build_distribution_profile_rows('M-compact', grouped_values, values_are_clean=True)

        self.assertEqual(len(compact), len(expanded))
        self.assertEqual([entry[0] for entry in compact], [row['Metric'] for row in expanded])
        self.assertEqual([entry[1] for entry in compact], [row['Group'] for row in expanded])

    def test_profile_rows_calls_single_fit_per_group_with_precomputed_signatures(self):
        grouped_values = {
            'A': np.array([1.0, 1.1, 1.2, 1.3], dtype=float),
            'B': np.array([2.0, 2.1, 2.2, 2.3], dtype=float),
        }

        fit_payload = {
            'fit_quality': {'label': 'strong'},
            'gof_metrics': {},
            'selected_model': {'display_name': 'Normal'},
            'inferred_support_mode': 'bilateral_signed',
            'status': 'ok',
            'warning': None,
            'notes': [],
        }

        with patch('modules.distribution_shape_analysis.fit_measurement_distribution', return_value=fit_payload) as mock_fit:
            rows = build_distribution_profile_rows('M-batch', grouped_values, values_are_clean=True)

        self.assertEqual(mock_fit.call_count, 2)
        for call in mock_fit.call_args_list:
            self.assertIn('measurement_signature', call.kwargs)
            self.assertIsNotNone(call.kwargs['measurement_signature'])
        self.assertEqual(len(rows), 2)

if __name__ == '__main__':
    unittest.main()

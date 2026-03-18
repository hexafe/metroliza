import unittest

import numpy as np

from modules.distribution_shape_analysis import compute_distribution_difference


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


if __name__ == '__main__':
    unittest.main()

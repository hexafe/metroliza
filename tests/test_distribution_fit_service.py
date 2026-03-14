import unittest

from modules.distribution_fit_service import fit_measurement_distribution


class TestDistributionFitService(unittest.TestCase):
    def test_fit_measurement_distribution_returns_model_and_metrics(self):
        result = fit_measurement_distribution(
            [9.8, 10.0, 10.1, 9.9, 10.2, 10.05, 9.95, 10.15],
            lsl=9.6,
            usl=10.4,
            nom=10.0,
            monte_carlo_gof_samples=10,
            monte_carlo_seed=42,
        )

        self.assertEqual(result['status'], 'ok')
        self.assertIsNotNone(result['selected_model'])
        self.assertIsNotNone(result['selected_model_pdf'])
        self.assertIsNotNone(result['selected_model_cdf'])
        self.assertIsNotNone(result['gof_metrics'])
        self.assertGreaterEqual(len(result['ranking_metrics']), 1)
        self.assertIn('risk_label', result['risk_estimates'])
        self.assertIn(result['fit_quality']['label'], {'strong', 'medium', 'weak', 'unreliable'})

    def test_fit_measurement_distribution_returns_failed_payload_for_constant_data(self):
        result = fit_measurement_distribution([4.2, 4.2, 4.2], lsl=4.0, usl=4.4, nom=4.2)

        self.assertEqual(result['status'], 'failed')
        self.assertIsNotNone(result['warning'])
        self.assertIsNone(result['selected_model_pdf'])
        self.assertIsNone(result['selected_model_cdf'])

    def test_fit_measurement_distribution_can_skip_kde_reference(self):
        result = fit_measurement_distribution(
            [1.0, 1.2, 1.1, 1.3, 0.9, 1.05, 1.15],
            lsl=0.8,
            usl=1.4,
            nom=1.1,
            include_kde_reference=False,
        )

        self.assertEqual(result['status'], 'ok')
        self.assertIsNone(result['kde_reference_pdf'])

    def test_support_mode_inference_and_positive_constraints(self):
        result = fit_measurement_distribution([0.0, 0.2, 0.5, 0.7, 1.1, 1.4, 2.0], usl=2.2)

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['inferred_support_mode'], 'one_sided_zero_bound_positive')
        self.assertIn(result['selected_model']['name'], {'halfnorm', 'foldnorm', 'gamma', 'weibull_min', 'lognorm'})

        for candidate in result['model_candidates']:
            if candidate['model'] in {'halfnorm', 'foldnorm', 'gamma', 'weibull_min', 'lognorm'}:
                # scipy continuous parameter order is (*shape, loc, scale)
                self.assertAlmostEqual(candidate['params'][-2], 0.0, places=7)

    def test_tail_risk_spec_types(self):
        bilateral = fit_measurement_distribution([-2, -1, -0.2, 0.1, 0.6, 1.3, 2.1], lsl=-1.5, usl=1.5)
        upper_only = fit_measurement_distribution([0.0, 0.1, 0.2, 0.4, 0.9, 1.2], usl=1.0)
        lower_only = fit_measurement_distribution([-2.0, -1.1, -0.4, -0.2, 0.0, 0.5], lsl=-1.0)

        self.assertEqual(bilateral['risk_estimates']['spec_type'], 'bilateral')
        self.assertEqual(upper_only['risk_estimates']['spec_type'], 'upper_only')
        self.assertEqual(lower_only['risk_estimates']['spec_type'], 'lower_only')


if __name__ == '__main__':
    unittest.main()

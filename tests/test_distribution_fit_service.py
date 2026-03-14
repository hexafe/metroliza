import unittest

from modules.distribution_fit_service import fit_measurement_distribution


class TestDistributionFitService(unittest.TestCase):
    def test_fit_measurement_distribution_returns_model_and_metrics(self):
        result = fit_measurement_distribution(
            [9.8, 10.0, 10.1, 9.9, 10.2, 10.05, 9.95, 10.15],
            lsl=9.6,
            usl=10.4,
            nom=10.0,
        )

        self.assertEqual(result['status'], 'ok')
        self.assertIsNotNone(result['selected_model'])
        self.assertIsNotNone(result['selected_model_pdf'])
        self.assertIsNotNone(result['gof_metrics'])
        self.assertGreaterEqual(len(result['ranking_metrics']), 1)
        self.assertIn('risk_label', result['risk_estimates'])

    def test_fit_measurement_distribution_returns_failed_payload_for_constant_data(self):
        result = fit_measurement_distribution([4.2, 4.2, 4.2], lsl=4.0, usl=4.4, nom=4.2)

        self.assertEqual(result['status'], 'failed')
        self.assertIsNotNone(result['warning'])
        self.assertIsNone(result['selected_model_pdf'])

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


if __name__ == '__main__':
    unittest.main()

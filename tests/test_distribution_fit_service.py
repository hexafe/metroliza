import unittest
from unittest import mock

import numpy as np
from scipy.stats import foldnorm, gamma, halfnorm, lognorm, norm, skewnorm, weibull_min

import modules.distribution_fit_service as distribution_fit_service
from modules.distribution_fit_service import (
    _BILATERAL_CANDIDATES,
    _POSITIVE_CANDIDATES,
    _candidate_pool_for_mode,
    _compute_tail_risk,
    build_fit_curve_payload,
    compute_estimated_tail_metrics,
    fit_measurement_distribution,
)


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

    def test_candidate_selection_pool_matches_support_mode(self):
        self.assertEqual(_candidate_pool_for_mode('bilateral_signed'), _BILATERAL_CANDIDATES)
        self.assertEqual(
            _candidate_pool_for_mode('one_sided_zero_bound_positive'),
            _POSITIVE_CANDIDATES,
        )

    def test_synthetic_signed_families_fit_with_bilateral_candidates(self):
        rng = np.random.default_rng(42)
        normal_sample = norm.rvs(loc=0.0, scale=1.0, size=180, random_state=rng)
        skew_sample = skewnorm.rvs(a=7.0, loc=0.0, scale=1.0, size=180, random_state=rng)

        normal_result = fit_measurement_distribution(normal_sample)
        skew_result = fit_measurement_distribution(skew_sample)

        for result in (normal_result, skew_result):
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['inferred_support_mode'], 'bilateral_signed')
            self.assertIn(result['selected_model']['name'], {'norm', 'skewnorm', 'johnsonsu'})

    def test_synthetic_positive_families_fit_with_positive_support_candidates(self):
        rng = np.random.default_rng(7)
        samples = [
            halfnorm.rvs(loc=0.0, scale=1.0, size=220, random_state=rng),
            foldnorm.rvs(1.5, loc=0.0, scale=0.7, size=220, random_state=rng),
            gamma.rvs(2.5, loc=0.0, scale=0.8, size=220, random_state=rng),
            weibull_min.rvs(1.8, loc=0.0, scale=1.2, size=220, random_state=rng),
            lognorm.rvs(0.45, loc=0.0, scale=1.1, size=220, random_state=rng),
        ]

        for sample in samples:
            sample_with_zero_anchor = np.concatenate(([0.0, 0.0], np.asarray(sample, dtype=float)))
            result = fit_measurement_distribution(sample_with_zero_anchor, usl=3.5)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['inferred_support_mode'], 'one_sided_zero_bound_positive')
            self.assertIn(result['selected_model']['name'], {'halfnorm', 'foldnorm', 'gamma', 'weibull_min', 'lognorm'})

    def test_tail_risk_formulas_bilateral_upper_only_lower_only(self):
        params = (0.0, 1.0)
        bilateral = _compute_tail_risk(norm, params, -1.0, 1.0)
        upper_only = _compute_tail_risk(norm, params, None, 1.0)
        lower_only = _compute_tail_risk(norm, params, -1.0, None)

        expected_one_tail = float(1.0 - norm.cdf(1.0, *params))
        self.assertAlmostEqual(bilateral['outside_probability'], expected_one_tail * 2.0, places=6)
        self.assertAlmostEqual(upper_only['outside_probability'], expected_one_tail, places=6)
        self.assertAlmostEqual(lower_only['outside_probability'], expected_one_tail, places=6)

    def test_tail_risk_treats_zero_lsl_positive_support_as_upper_only(self):
        params = (0.0, 1.0)

        result = _compute_tail_risk(
            norm,
            params,
            0.0,
            1.0,
            inferred_support_mode='one_sided_zero_bound_positive',
        )

        expected_upper_tail = float(1.0 - norm.cdf(1.0, *params))
        self.assertEqual(result['spec_type'], 'upper_only')
        self.assertEqual(result['below_lsl_probability'], 0.0)
        self.assertAlmostEqual(result['outside_probability'], expected_upper_tail, places=6)

    def test_build_fit_curve_payload_matches_fit_overlay_payload_for_selected_model_and_kde(self):
        measurements = [0.0, 0.0, 0.1, 0.2, 0.4, 3.0, 7.0]
        fit_result = fit_measurement_distribution(measurements, usl=7.5)

        model_curve = build_fit_curve_payload(
            measurements,
            point_count=100,
            distribution_fit_result=fit_result,
        )
        kde_curve = build_fit_curve_payload(
            measurements,
            point_count=100,
            mode='kde',
            distribution_fit_result=fit_result,
        )

        np.testing.assert_allclose(model_curve['x'], fit_result['selected_model_pdf']['x'])
        np.testing.assert_allclose(model_curve['y'], fit_result['selected_model_pdf']['y'])
        np.testing.assert_allclose(kde_curve['x'], fit_result['kde_reference_pdf']['x'])
        np.testing.assert_allclose(kde_curve['y'], fit_result['kde_reference_pdf']['y'])

    def test_compute_estimated_tail_metrics_matches_selected_model_risk_estimates(self):
        fit_result = fit_measurement_distribution([-2, -1, -0.2, 0.1, 0.6, 1.3, 2.1], lsl=-1.5, usl=1.5)

        metrics = compute_estimated_tail_metrics(fit_result, lsl=-1.5, usl=1.5)

        self.assertAlmostEqual(metrics['estimated_nok_pct'], fit_result['risk_estimates']['outside_probability'])
        self.assertAlmostEqual(metrics['estimated_nok_ppm'], fit_result['risk_estimates']['ppm_nok'])
        self.assertAlmostEqual(
            metrics['estimated_tail_below_lsl'],
            fit_result['risk_estimates']['below_lsl_probability'],
        )
        self.assertAlmostEqual(
            metrics['estimated_tail_above_usl'],
            fit_result['risk_estimates']['above_usl_probability'],
        )

    def test_fit_measurement_distribution_memoizes_identical_requests_within_cache(self):
        measurements = [1.0, 1.2, 1.1, 1.3, 0.9, 1.05, 1.15]
        memo = {}

        with mock.patch.object(distribution_fit_service, '_fit_candidate', wraps=distribution_fit_service._fit_candidate) as wrapped_fit:
            first = fit_measurement_distribution(measurements, usl=1.4, memoization_cache=memo)
            second = fit_measurement_distribution(measurements, usl=1.4, memoization_cache=memo)

        self.assertEqual(first['status'], 'ok')
        self.assertEqual(second['status'], 'ok')
        self.assertEqual(wrapped_fit.call_count, len(_BILATERAL_CANDIDATES))
        self.assertEqual(len(memo), 1)
        self.assertIsNot(first, second)
        self.assertIsNot(first['selected_model_pdf'], second['selected_model_pdf'])

    def test_one_sided_zero_bound_forces_loc_zero_for_positive_candidates(self):
        result = fit_measurement_distribution([0.0, 0.05, 0.2, 0.4, 0.8, 1.1, 1.5, 2.0], usl=2.5)

        self.assertEqual(result['status'], 'ok')
        for candidate in result['model_candidates']:
            self.assertAlmostEqual(candidate['params'][-2], 0.0, places=7)

    def test_failure_mode_for_tiny_samples(self):
        result = fit_measurement_distribution([1.0, 1.2])

        self.assertEqual(result['status'], 'failed')
        self.assertIn('at least 3 valid measurements', result['warning'])

    def test_failure_mode_for_identical_values(self):
        result = fit_measurement_distribution([2.2, 2.2, 2.2, 2.2])

        self.assertEqual(result['status'], 'failed')
        self.assertIn('effectively constant', result['warning'])

    def test_failure_mode_when_all_candidate_fits_raise(self):
        with mock.patch.object(distribution_fit_service, '_fit_candidate', side_effect=RuntimeError('boom')):
            result = fit_measurement_distribution([0.5, 0.8, 1.1, 1.4, 1.8])

        self.assertEqual(result['status'], 'failed')
        self.assertIn('failed for all candidate models', result['warning'])
        self.assertTrue(any(note.startswith('Skipped') for note in result['notes']))

    def test_poor_fit_path_downgrades_quality_when_no_acceptable_gof(self):
        values = np.linspace(-1.0, 1.0, 60)

        def _poor_candidate(_candidate, _values):
            return {
                'model': 'norm',
                'display_name': 'Normal',
                'params': (0.0, 1.0),
                'metrics': {'nll': 10.0, 'aic': 24.0, 'bic': 26.0},
                'gof': {
                    'ad_statistic': 1.0,
                    'ad_pvalue': None,
                    'ad_pvalue_method': 'not_estimated',
                    'ks_statistic': 0.3,
                    'ks_pvalue': 0.0001,
                },
            }

        with mock.patch.object(distribution_fit_service, '_fit_candidate', side_effect=_poor_candidate):
            result = fit_measurement_distribution(values, gof_acceptance_alpha=0.05)

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['fit_quality']['label'], 'unreliable')
        self.assertIn('No model met GOF threshold', ' '.join(result['notes']))


if __name__ == '__main__':
    unittest.main()

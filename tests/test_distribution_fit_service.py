import unittest
from types import SimpleNamespace
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
    fit_measurement_distribution_batch,
    measurement_fingerprint,
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

        def _poor_candidate(_candidate, _values, **_kwargs):
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



    def test_fit_measurement_distribution_batch_accepts_numpy_arrays_and_matches_single_fit(self):
        grouped = {
            'A': np.ascontiguousarray(np.array([1.0, 1.1, 1.2, 1.3, 1.4], dtype=float)),
            'B': np.ascontiguousarray(np.array([-0.4, -0.2, 0.0, 0.2, 0.5, 0.8], dtype=float)),
        }

        batch = fit_measurement_distribution_batch(grouped, usl_by_group={'A': 1.5, 'B': 1.0})
        single_a = fit_measurement_distribution(grouped['A'], usl=1.5)
        single_b = fit_measurement_distribution(grouped['B'], usl=1.0)

        self.assertEqual(batch['A']['selected_model']['name'], single_a['selected_model']['name'])
        self.assertEqual(batch['B']['selected_model']['name'], single_b['selected_model']['name'])
        self.assertAlmostEqual(batch['A']['risk_estimates']['outside_probability'], single_a['risk_estimates']['outside_probability'])
        self.assertAlmostEqual(batch['B']['risk_estimates']['outside_probability'], single_b['risk_estimates']['outside_probability'])

    def test_fit_measurement_distribution_batch_converts_lists_and_zero_copies_contiguous_ndarrays(self):
        contiguous_array = np.ascontiguousarray(np.array([1.0, 1.1, 1.2], dtype=np.float64))
        grouped = {
            'FROM_LIST': [0.1, 0.2, 0.3],
            'FROM_ARRAY': contiguous_array,
        }
        captured_values = {}

        def _stub_fit_measurement_distribution(values, **kwargs):
            del kwargs
            captured_values[len(captured_values)] = values
            return {
                'status': 'ok',
                'selected_model': {'name': 'norm'},
                'risk_estimates': {'outside_probability': 0.0},
                'ranking_metrics': [],
            }

        with mock.patch.object(distribution_fit_service, '_fit_candidates_batch_native', return_value={}), mock.patch.object(
            distribution_fit_service,
            'fit_measurement_distribution',
            side_effect=_stub_fit_measurement_distribution,
        ):
            fit_measurement_distribution_batch(grouped)

        list_values = captured_values[0]
        ndarray_values = captured_values[1]
        self.assertIsInstance(list_values, np.ndarray)
        self.assertEqual(list_values.dtype, np.float64)
        self.assertTrue(list_values.flags['C_CONTIGUOUS'])
        self.assertIsNot(list_values, grouped['FROM_LIST'])

        self.assertIs(ndarray_values, contiguous_array)

    def test_batch_candidate_kernel_mode_parity_preserves_full_ranking_for_deterministic_fixture(self):
        rng = np.random.default_rng(20260325)
        grouped = {
            'G_POS': np.ascontiguousarray(rng.gamma(shape=2.3, scale=0.9, size=90).astype(float)),
            'G_BI': np.ascontiguousarray(rng.normal(loc=0.0, scale=1.0, size=90).astype(float)),
        }

        baseline = fit_measurement_distribution_batch(grouped, candidate_kernel_mode='python')
        candidate = fit_measurement_distribution_batch(grouped, candidate_kernel_mode='auto')

        for group_name in grouped:
            left = baseline[group_name]['ranking_metrics']
            right = candidate[group_name]['ranking_metrics']
            self.assertEqual([row['model'] for row in left], [row['model'] for row in right])
            self.assertEqual([row['rank'] for row in left], [row['rank'] for row in right])
            for lhs, rhs in zip(left, right, strict=False):
                for metric_key in ('nll', 'aic', 'bic', 'ad_statistic', 'ks_statistic'):
                    self.assertAlmostEqual(lhs[metric_key], rhs[metric_key], places=9)

    def test_batch_native_dispatch_parity_matches_python_baseline_for_ranking_selection_and_risk(self):
        rng = np.random.default_rng(20260326)
        grouped = {
            'G_POS': np.ascontiguousarray(rng.gamma(shape=2.8, scale=0.6, size=120).astype(float)),
            'G_BI': np.ascontiguousarray(rng.normal(loc=-0.1, scale=0.9, size=120).astype(float)),
        }

        baseline = fit_measurement_distribution_batch(
            grouped,
            usl_by_group={'G_POS': 2.2, 'G_BI': 1.8},
            lsl_by_group={'G_BI': -1.8},
            candidate_kernel_mode='python',
        )

        def _fake_native_batch(kernel_input):
            nll = []
            aic = []
            bic = []
            ad = []
            ks = []
            flags = []
            for distribution, params, sample in zip(
                kernel_input.distributions,
                kernel_input.fitted_params_batch,
                kernel_input.sample_values_batch,
                strict=False,
            ):
                dist = distribution_fit_service._DISTRIBUTION_BY_NAME[distribution]
                params_tuple = tuple(float(v) for v in params)
                values = np.asarray(sample, dtype=float)
                logpdf = dist.logpdf(values, *params_tuple)
                nll_value = float(-np.sum(logpdf))
                k = len(params_tuple)
                n = values.size
                nll.append(nll_value)
                aic.append(float(2 * k + 2 * nll_value))
                bic.append(float(k * np.log(n) + 2 * nll_value))
                ad.append(float(distribution_fit_service._ad_statistic(values, lambda x: dist.cdf(x, *params_tuple))))
                ks.append(float(distribution_fit_service.kstest(values, dist.cdf, args=params_tuple).statistic))
                flags.append(0)
            return SimpleNamespace(
                nll=tuple(nll),
                aic=tuple(aic),
                bic=tuple(bic),
                ad_statistic=tuple(ad),
                ks_statistic=tuple(ks),
                error_flags=tuple(flags),
            )

        with mock.patch.object(distribution_fit_service, 'compute_candidate_metrics_batch_native', side_effect=_fake_native_batch) as batch_stub:
            candidate = fit_measurement_distribution_batch(
                grouped,
                usl_by_group={'G_POS': 2.2, 'G_BI': 1.8},
                lsl_by_group={'G_BI': -1.8},
                candidate_kernel_mode='auto',
            )

        self.assertGreater(batch_stub.call_count, 0)
        for group_name in grouped:
            baseline_rank = baseline[group_name]['ranking_metrics']
            candidate_rank = candidate[group_name]['ranking_metrics']
            self.assertEqual([row['model'] for row in baseline_rank], [row['model'] for row in candidate_rank])
            self.assertEqual(baseline[group_name]['selected_model']['name'], candidate[group_name]['selected_model']['name'])
            self.assertAlmostEqual(
                baseline[group_name]['risk_estimates']['outside_probability'],
                candidate[group_name]['risk_estimates']['outside_probability'],
                places=12,
            )

    def test_fit_measurement_distribution_uses_provided_measurement_signature_for_cache_key(self):
        measurements = np.ascontiguousarray(np.array([1.0, 1.2, 1.1, 1.3, 0.9, 1.05, 1.15], dtype=float))
        memo = {}
        signature = measurement_fingerprint(measurements)

        with mock.patch.object(distribution_fit_service, '_measurement_fingerprint', side_effect=AssertionError('fingerprint should not be recomputed')):
            first = fit_measurement_distribution(measurements, usl=1.4, memoization_cache=memo, measurement_signature=signature)
            second = fit_measurement_distribution(measurements, usl=1.4, memoization_cache=memo, measurement_signature=signature)

        self.assertEqual(first['status'], 'ok')
        self.assertEqual(second['status'], 'ok')
        self.assertEqual(len(memo), 1)

if __name__ == '__main__':
    unittest.main()

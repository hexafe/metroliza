import unittest
import json
from unittest import mock
from pathlib import Path

import numpy as np
from scipy.stats import gamma, lognorm, norm, weibull_min

import modules.distribution_fit_native as native_bridge
import modules.distribution_fit_candidate_native as candidate_native_bridge
import modules.distribution_fit_service as service

FIXTURE_PATH = Path('tests/fixtures/distribution_fit/native_kernel_edge_cases.json')


def _load_native_kernel_edge_fixtures():
    return json.loads(FIXTURE_PATH.read_text())


class TestDistributionFitNativeParity(unittest.TestCase):
    def test_candidate_kernel_bridge_auto_fallback_returns_none_without_backend(self):
        kernel_input = candidate_native_bridge.build_kernel_input(
            distribution='norm',
            fitted_params=[0.0, 1.0],
            sample_values=[-1.0, 0.0, 1.0],
        )
        with mock.patch.object(candidate_native_bridge, '_native_compute_candidate_metrics', None):
            self.assertIsNone(candidate_native_bridge.compute_candidate_metrics(kernel_input, mode='auto'))
            native_forced = candidate_native_bridge.compute_candidate_metrics(kernel_input, mode='native')
            self.assertIsNotNone(native_forced)
            self.assertGreater(native_forced.error_flags, 0)

    def test_candidate_kernel_bridge_normalizes_to_contiguous_float64(self):
        with mock.patch.object(
            candidate_native_bridge,
            '_native_compute_candidate_metrics',
            return_value=(1.0, 2.0, 3.0, 4.0, 5.0, 0),
        ) as kernel_stub:
            kernel_input = candidate_native_bridge.build_kernel_input(
                distribution='norm',
                fitted_params=np.array([0, 1], dtype=np.float32),
                sample_values=np.array([-1, 0, 1], dtype=np.float32),
            )
            output = candidate_native_bridge.compute_candidate_metrics(kernel_input, mode='native')
            self.assertEqual(output.error_flags, 0)
            for arr in kernel_stub.call_args.args[1:]:
                self.assertIsInstance(arr, np.ndarray)
                self.assertEqual(arr.dtype, np.float64)
                self.assertTrue(arr.flags['C_CONTIGUOUS'])

    def test_candidate_kernel_batch_bridge_normalizes_to_contiguous_float64(self):
        with mock.patch.object(
            candidate_native_bridge,
            '_native_compute_candidate_metrics_batch',
            return_value=([1.0], [2.0], [3.0], [4.0], [5.0], [0]),
        ) as kernel_stub:
            kernel_input = candidate_native_bridge.build_batch_kernel_input(
                distributions=['norm'],
                fitted_params_batch=[np.array([0, 1], dtype=np.float32)],
                sample_values_batch=[np.array([-1, 0, 1], dtype=np.float32)],
            )
            output = candidate_native_bridge.compute_candidate_metrics_batch_native(kernel_input)
            self.assertEqual(output.error_flags, (0,))
            for arr in kernel_stub.call_args.args[1]:
                self.assertIsInstance(arr, np.ndarray)
                self.assertEqual(arr.dtype, np.float64)
                self.assertTrue(arr.flags['C_CONTIGUOUS'])
            for arr in kernel_stub.call_args.args[2]:
                self.assertIsInstance(arr, np.ndarray)
                self.assertEqual(arr.dtype, np.float64)
                self.assertTrue(arr.flags['C_CONTIGUOUS'])

    def test_native_wrapper_normalizes_list_and_ndarray_inputs_equivalently(self):
        with mock.patch.object(
            native_bridge,
            '_native_estimate_ad_pvalue_monte_carlo',
            return_value=(0.42, 100),
        ) as monte_carlo_stub, mock.patch.object(
            native_bridge,
            '_native_compute_ad_ks_statistics',
            return_value=(0.1, 0.2),
        ) as stats_stub:
            list_result = native_bridge.estimate_ad_pvalue_monte_carlo_native(
                distribution='norm',
                fitted_params=[0, 1],
                sample_size=40,
                observed_stat=0.65,
                iterations=100,
                seed=123,
            )
            array_result = native_bridge.estimate_ad_pvalue_monte_carlo_native(
                distribution='norm',
                fitted_params=np.array([0, 1], dtype=np.float32),
                sample_size=40,
                observed_stat=0.65,
                iterations=100,
                seed=123,
            )
            self.assertEqual(list_result, array_result)

            list_stats = native_bridge.compute_ad_ks_statistics_native(
                distribution='norm',
                fitted_params=[0, 1],
                sample_values=[-1, 0, 1],
            )
            array_stats = native_bridge.compute_ad_ks_statistics_native(
                distribution='norm',
                fitted_params=np.array([0, 1], dtype=np.float32),
                sample_values=np.array([-1, 0, 1], dtype=np.float32),
            )
            self.assertEqual(list_stats, array_stats)

            monte_call_params = monte_carlo_stub.call_args_list[0].args[1]
            stats_call_params = stats_stub.call_args_list[0].args[1]
            stats_call_values = stats_stub.call_args_list[0].args[2]
            for arr in (monte_call_params, stats_call_params, stats_call_values):
                self.assertIsInstance(arr, np.ndarray)
                self.assertEqual(arr.dtype, np.float64)
                self.assertTrue(arr.flags['C_CONTIGUOUS'])

    @unittest.skipUnless(native_bridge.native_backend_available(), 'native distribution-fit extension is unavailable')
    def test_native_seeded_runs_are_exactly_reproducible(self):
        p1, valid1 = native_bridge.estimate_ad_pvalue_monte_carlo_native(
            distribution='norm',
            fitted_params=(0.0, 1.0),
            sample_size=40,
            observed_stat=0.65,
            iterations=400,
            seed=123,
        )
        p2, valid2 = native_bridge.estimate_ad_pvalue_monte_carlo_native(
            distribution='norm',
            fitted_params=(0.0, 1.0),
            sample_size=40,
            observed_stat=0.65,
            iterations=400,
            seed=123,
        )

        self.assertEqual(valid1, valid2)
        self.assertEqual(p1, p2)

    @unittest.skipUnless(native_bridge.native_backend_available(), 'native distribution-fit extension is unavailable')
    def test_python_and_native_paths_match_for_seeded_runs(self):
        native_result = service._estimate_ad_pvalue_monte_carlo(
            dist=norm,
            distribution_name='norm',
            params=(0.0, 1.0),
            sample_size=40,
            observed_stat=0.65,
            iterations=500,
            random_seed=77,
        )

        with mock.patch.object(service, 'estimate_ad_pvalue_monte_carlo_native', return_value=None):
            python_result = service._estimate_ad_pvalue_monte_carlo(
                dist=norm,
                distribution_name='norm',
                params=(0.0, 1.0),
                sample_size=40,
                observed_stat=0.65,
                iterations=500,
                random_seed=77,
            )

        self.assertIsNotNone(native_result)
        self.assertIsNotNone(python_result)
        self.assertAlmostEqual(native_result, python_result, places=2)

    @unittest.skipUnless(native_bridge.native_backend_available(), 'native distribution-fit extension is unavailable')
    def test_python_and_native_paths_are_close_for_unseeded_runs(self):
        native_result = service._estimate_ad_pvalue_monte_carlo(
            dist=gamma,
            distribution_name='gamma',
            params=(2.0, 0.0, 1.2),
            sample_size=35,
            observed_stat=0.7,
            iterations=700,
            random_seed=None,
        )

        with mock.patch.object(service, 'estimate_ad_pvalue_monte_carlo_native', return_value=None):
            python_result = service._estimate_ad_pvalue_monte_carlo(
                dist=gamma,
                distribution_name='gamma',
                params=(2.0, 0.0, 1.2),
                sample_size=35,
                observed_stat=0.7,
                iterations=700,
                random_seed=None,
            )

        self.assertIsNotNone(native_result)
        self.assertIsNotNone(python_result)
        self.assertLess(abs(native_result - python_result), 0.12)



    @unittest.skipUnless(native_bridge.native_backend_available(), 'native distribution-fit extension is unavailable')
    def test_native_ad_ks_statistics_kernel_matches_python_reference(self):
        sample = [-1.2, -0.3, 0.0, 0.4, 0.8, 1.1, 1.4]
        native_ad, native_ks = native_bridge.compute_ad_ks_statistics_native(
            distribution='norm',
            fitted_params=(0.0, 1.0),
            sample_values=sample,
        )

        ad_py = service._ad_statistic(np.asarray(sample, dtype=float), lambda x: norm.cdf(x, 0.0, 1.0))
        ks_py = service.kstest(sample, norm.cdf, args=(0.0, 1.0)).statistic

        self.assertAlmostEqual(native_ad, ad_py, places=10)
        self.assertAlmostEqual(native_ks, ks_py, places=10)

    @unittest.skipUnless(native_bridge.native_backend_available(), 'native distribution-fit extension is unavailable')
    def test_native_ad_ks_statistics_kernel_near_boundary_parameters(self):
        for fixture in _load_native_kernel_edge_fixtures():
            distribution = fixture['distribution']
            params = tuple(float(value) for value in fixture['fitted_params'])
            sample = [float(value) for value in fixture['sample_values']]

            native_ad, native_ks = native_bridge.compute_ad_ks_statistics_native(
                distribution=distribution,
                fitted_params=params,
                sample_values=sample,
            )

            if distribution == 'norm':
                ad_py = service._ad_statistic(np.asarray(sample, dtype=float), lambda x: norm.cdf(x, *params))
                ks_py = service.kstest(sample, norm.cdf, args=params).statistic
            elif distribution == 'gamma':
                ad_py = service._ad_statistic(np.asarray(sample, dtype=float), lambda x: gamma.cdf(x, *params))
                ks_py = service.kstest(sample, gamma.cdf, args=params).statistic
            elif distribution == 'weibull_min':
                ad_py = service._ad_statistic(np.asarray(sample, dtype=float), lambda x: weibull_min.cdf(x, *params))
                ks_py = service.kstest(sample, weibull_min.cdf, args=params).statistic
            elif distribution == 'lognorm':
                ad_py = service._ad_statistic(np.asarray(sample, dtype=float), lambda x: lognorm.cdf(x, *params))
                ks_py = service.kstest(sample, lognorm.cdf, args=params).statistic
            else:
                self.fail(f"Unsupported distribution fixture: {distribution}")

            self.assertAlmostEqual(
                native_ad,
                ad_py,
                delta=float(fixture['ad_abs_tol']),
                msg=fixture['rationale'],
            )
            self.assertAlmostEqual(
                native_ks,
                ks_py,
                delta=float(fixture['ks_abs_tol']),
                msg=fixture['rationale'],
            )

if __name__ == '__main__':
    unittest.main()

import unittest
import json
from unittest import mock
from pathlib import Path

import numpy as np
from scipy.stats import gamma, lognorm, norm, weibull_min

import modules.distribution_fit_native as native_bridge
import modules.distribution_fit_candidate_native as candidate_native_bridge
import modules.distribution_fit_service as service
import scripts.benchmark_distribution_fit_batch as benchmark_distribution_fit_batch

FIXTURE_PATH = Path('tests/fixtures/distribution_fit/native_kernel_edge_cases.json')


def _load_native_kernel_edge_fixtures():
    return json.loads(FIXTURE_PATH.read_text())


class TestDistributionFitNativeParity(unittest.TestCase):
    def test_native_backend_status_true_when_monte_carlo_symbol_present_and_adks_missing(self):
        with mock.patch.object(native_bridge, '_native_estimate_ad_pvalue_monte_carlo', return_value=(0.5, 10)), mock.patch.object(
            native_bridge,
            '_native_compute_ad_ks_statistics',
            None,
        ):
            self.assertTrue(native_bridge.native_backend_available())
            monte_carlo = native_bridge.estimate_ad_pvalue_monte_carlo_native(
                distribution='norm',
                fitted_params=(0.0, 1.0),
                sample_size=20,
                observed_stat=0.2,
                iterations=10,
                seed=1,
            )
            ad_ks = native_bridge.compute_ad_ks_statistics_native(
                distribution='norm',
                fitted_params=(0.0, 1.0),
                sample_values=[-1.0, 0.0, 1.0],
            )
            self.assertEqual(monte_carlo, (0.5, 10))
            self.assertIsNone(ad_ks)

    def test_native_backend_status_false_when_only_adks_symbol_present(self):
        with mock.patch.object(native_bridge, '_native_estimate_ad_pvalue_monte_carlo', None), mock.patch.object(
            native_bridge,
            '_native_compute_ad_ks_statistics',
            return_value=(0.1, 0.2),
        ):
            self.assertFalse(native_bridge.native_backend_available())
            monte_carlo = native_bridge.estimate_ad_pvalue_monte_carlo_native(
                distribution='norm',
                fitted_params=(0.0, 1.0),
                sample_size=20,
                observed_stat=0.2,
                iterations=10,
                seed=1,
            )
            ad_ks = native_bridge.compute_ad_ks_statistics_native(
                distribution='norm',
                fitted_params=(0.0, 1.0),
                sample_values=[-1.0, 0.0, 1.0],
            )
            self.assertIsNone(monte_carlo)
            self.assertEqual(ad_ks, (0.1, 0.2))

    def test_resolve_kernel_mode_defaults_to_auto_when_unset(self):
        with mock.patch.dict(candidate_native_bridge.os.environ, {}, clear=True):
            self.assertEqual(candidate_native_bridge.resolve_kernel_mode(None), 'auto')

    def test_resolve_kernel_mode_honors_env_values(self):
        with mock.patch.dict(
            candidate_native_bridge.os.environ,
            {'METROLIZA_DISTRIBUTION_FIT_KERNEL': 'python'},
            clear=True,
        ):
            self.assertEqual(candidate_native_bridge.resolve_kernel_mode(None), 'python')

        with mock.patch.dict(
            candidate_native_bridge.os.environ,
            {'METROLIZA_DISTRIBUTION_FIT_KERNEL': 'native'},
            clear=True,
        ):
            self.assertEqual(candidate_native_bridge.resolve_kernel_mode(None), 'native')

        with mock.patch.dict(
            candidate_native_bridge.os.environ,
            {'METROLIZA_DISTRIBUTION_FIT_KERNEL': 'auto'},
            clear=True,
        ):
            self.assertEqual(candidate_native_bridge.resolve_kernel_mode(None), 'auto')

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

    def test_native_wrapper_uses_zero_copy_for_contiguous_float64_ndarrays(self):
        contiguous_params = np.ascontiguousarray(np.array([0.0, 1.0], dtype=np.float64))
        contiguous_sample = np.ascontiguousarray(np.array([-1.0, 0.0, 1.0], dtype=np.float64))
        with mock.patch.object(
            native_bridge,
            '_native_estimate_ad_pvalue_monte_carlo',
            return_value=(0.42, 100),
        ) as monte_carlo_stub, mock.patch.object(
            native_bridge,
            '_native_compute_ad_ks_statistics',
            return_value=(0.1, 0.2),
        ) as stats_stub:
            native_bridge.estimate_ad_pvalue_monte_carlo_native(
                distribution='norm',
                fitted_params=contiguous_params,
                sample_size=40,
                observed_stat=0.65,
                iterations=100,
                seed=123,
            )
            native_bridge.compute_ad_ks_statistics_native(
                distribution='norm',
                fitted_params=contiguous_params,
                sample_values=contiguous_sample,
            )

            self.assertIs(monte_carlo_stub.call_args.args[1], contiguous_params)
            self.assertIs(stats_stub.call_args.args[1], contiguous_params)
            self.assertIs(stats_stub.call_args.args[2], contiguous_sample)

    def test_native_monte_carlo_throughput_metric_scales_with_high_iteration_runs(self):
        iterations = 200_000
        reps = 3
        throughput = benchmark_distribution_fit_batch._native_monte_carlo_throughput(
            iterations=iterations,
            reps=reps,
            elapsed_seconds=1.5,
        )
        self.assertAlmostEqual(throughput, (iterations * reps) / 1.5)
        self.assertGreater(throughput, 100_000.0)

    @unittest.skipUnless(
        native_bridge.native_monte_carlo_backend_available(),
        'native distribution-fit Monte Carlo kernel is unavailable',
    )
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

    @unittest.skipUnless(
        native_bridge.native_monte_carlo_backend_available(),
        'native distribution-fit Monte Carlo kernel is unavailable',
    )
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

    @unittest.skipUnless(
        native_bridge.native_monte_carlo_backend_available(),
        'native distribution-fit Monte Carlo kernel is unavailable',
    )
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



    @unittest.skipUnless(
        native_bridge.native_ad_ks_backend_available(),
        'native distribution-fit AD+KS kernel is unavailable',
    )
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

    @unittest.skipUnless(
        native_bridge.native_ad_ks_backend_available(),
        'native distribution-fit AD+KS kernel is unavailable',
    )
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

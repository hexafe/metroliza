import unittest
import json
from unittest import mock
from pathlib import Path

import numpy as np
from scipy.stats import gamma, norm

import modules.distribution_fit_native as native_bridge
import modules.distribution_fit_service as service

FIXTURE_PATH = Path('tests/fixtures/distribution_fit/native_kernel_edge_cases.json')


def _load_native_kernel_edge_fixtures():
    return json.loads(FIXTURE_PATH.read_text())


class TestDistributionFitNativeParity(unittest.TestCase):
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

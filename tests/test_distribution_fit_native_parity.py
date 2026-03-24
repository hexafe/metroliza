import unittest
from unittest import mock

import numpy as np
from scipy.stats import gamma, norm

import modules.distribution_fit_native as native_bridge
import modules.distribution_fit_service as service


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
        # Native and SciPy Monte Carlo paths use different RNG/distribution implementations;
        # seeded runs should remain close, but not bit-for-bit identical.
        self.assertLess(abs(native_result - python_result), 0.03)

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

if __name__ == '__main__':
    unittest.main()

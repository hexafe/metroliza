import unittest

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

from modules.distribution_fit_service import fit_measurement_distribution

from modules.export_summary_utils import (
    apply_shared_x_axis_label_strategy,
    build_trend_plot_payload,
    build_histogram_density_curve_payload,
    compute_measurement_summary,
    compute_estimated_tail_metrics,
    resolve_nominal_and_limits,
)


class TestExportSummaryUtils(unittest.TestCase):
    def test_resolve_nominal_and_limits_applies_nominal_offsets(self):
        header_group = pd.DataFrame({'NOM': [10.0], '+TOL': [0.2], '-TOL': [-0.1]})

        limits = resolve_nominal_and_limits(header_group)

        self.assertEqual(limits['nom'], 10.0)
        self.assertEqual(limits['usl'], 10.2)
        self.assertEqual(limits['lsl'], 9.9)

    def test_compute_measurement_summary_handles_out_of_tolerance_and_ratios(self):
        header_group = pd.DataFrame(
            {
                'MEAS': [9.8, 10.0, 10.25],
            }
        )

        summary = compute_measurement_summary(header_group, usl=10.2, lsl=9.9, nom=10.0)

        self.assertEqual(summary['sample_size'], 3)
        self.assertEqual(summary['nok_count'], 2)
        self.assertAlmostEqual(summary['nok_pct'], 2 / 3)
        self.assertEqual(summary['minimum'], 9.8)
        self.assertEqual(summary['maximum'], 10.25)



    def test_compute_estimated_tail_metrics_uses_bilateral_cdf_tails(self):
        distribution_fit_result = {
            'selected_model': {
                'model': 'norm',
                'params': (0.0, 1.0),
            },
        }

        metrics = compute_estimated_tail_metrics(distribution_fit_result, lsl=-1.0, usl=2.0)

        self.assertAlmostEqual(metrics['estimated_nok_pct'], 0.181405, places=4)
        self.assertAlmostEqual(metrics['estimated_yield_pct'], 0.818595, places=4)
        self.assertAlmostEqual(metrics['estimated_nok_ppm'], 181405.0, delta=2.0)


    def test_compute_estimated_tail_metrics_ignores_impossible_lower_tail_for_zero_bound_positive_support(self):
        distribution_fit_result = {
            'inferred_support_mode': 'one_sided_zero_bound_positive',
            'selected_model': {
                'model': 'norm',
                'params': (0.0, 1.0),
            },
        }

        metrics = compute_estimated_tail_metrics(distribution_fit_result, lsl=0.0, usl=2.0)

        self.assertEqual(metrics['estimated_tail_below_lsl'], 0.0)
        self.assertAlmostEqual(metrics['estimated_nok_pct'], 0.022750, places=4)
        self.assertAlmostEqual(metrics['estimated_yield_pct'], 0.977250, places=4)
        self.assertAlmostEqual(metrics['estimated_nok_ppm'], 22750.0, delta=2.0)

    def test_histogram_density_curve_adapter_matches_canonical_fit_payload(self):
        measurements = [0.0, 0.0, 0.1, 0.2, 0.4, 3.0, 7.0]
        fit_result = fit_measurement_distribution(measurements, usl=7.5)

        payload = build_histogram_density_curve_payload(
            measurements,
            point_count=100,
            mode='kde',
            distribution_fit_result=fit_result,
        )

        self.assertIsNotNone(payload)
        np.testing.assert_allclose(payload['x'], fit_result['kde_reference_pdf']['x'])
        np.testing.assert_allclose(payload['y'], fit_result['kde_reference_pdf']['y'])

    def test_build_trend_plot_payload_keeps_repeated_sample_labels_dense(self):
        header_group = pd.DataFrame(
            {
                'MEAS': ['1.0', '1.1', '1.2', '1.3'],
                'SAMPLE_NUMBER': ['1', '1', '2', '2'],
            }
        )

        payload = build_trend_plot_payload(header_group)

        self.assertEqual(payload['x'], [0, 1, 2, 3])
        self.assertEqual(payload['labels'], ['1', '1', '2', '2'])

    def test_apply_shared_x_axis_label_strategy_can_disable_thinning(self):
        fig, ax = plt.subplots()
        try:
            labels = [f'Label-{index:02d}' for index in range(30)]
            positions = list(range(len(labels)))

            apply_shared_x_axis_label_strategy(
                ax,
                labels,
                positions=positions,
                thinning_threshold=10,
                target_tick_count=5,
                allow_thinning=False,
            )

            rendered = ax.get_xticklabels()
            self.assertEqual(len(rendered), len(labels))
            self.assertEqual(int(rendered[0].get_rotation()), 90)
        finally:
            plt.close(fig)


if __name__ == '__main__':
    unittest.main()

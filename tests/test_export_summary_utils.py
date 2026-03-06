import unittest

import matplotlib.pyplot as plt
import pandas as pd

from modules.export_summary_utils import (
    apply_shared_x_axis_label_strategy,
    build_trend_plot_payload,
    compute_measurement_summary,
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

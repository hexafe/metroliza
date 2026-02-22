import unittest

import pandas as pd

from modules.export_summary_utils import compute_measurement_summary, resolve_nominal_and_limits


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


if __name__ == '__main__':
    unittest.main()

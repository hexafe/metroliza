import unittest
import warnings

import matplotlib.pyplot as plt
import numpy as np

from modules.distribution_fit_service import fit_measurement_distribution


from modules.export_query_service import RowTable
from modules.export_summary_utils import (
    apply_shared_x_axis_label_strategy,
    build_trend_plot_payload,
    build_histogram_density_curve_payload,
    compute_measurement_summary,
    compute_estimated_tail_metrics,
    resolve_shared_x_axis_label_layout,
    resolve_nominal_and_limits,
)


class TestExportSummaryUtils(unittest.TestCase):
    def test_resolve_nominal_and_limits_applies_nominal_offsets(self):
        header_group = RowTable(rows=((10.0, 0.2, -0.1),), columns=('NOM', '+TOL', '-TOL'))

        limits = resolve_nominal_and_limits(header_group)

        self.assertEqual(limits['nom'], 10.0)
        self.assertEqual(limits['usl'], 10.2)
        self.assertEqual(limits['lsl'], 9.9)

    def test_compute_measurement_summary_handles_out_of_tolerance_and_ratios(self):
        header_group = RowTable(rows=((9.8,), (10.0,), (10.25,)), columns=('MEAS',))

        summary = compute_measurement_summary(header_group, usl=10.2, lsl=9.9, nom=10.0)

        self.assertEqual(summary['sample_size'], 3)
        self.assertEqual(summary['nok_count'], 2)
        self.assertAlmostEqual(summary['nok_pct'], 2 / 3)
        self.assertEqual(summary['minimum'], 9.8)
        self.assertEqual(summary['maximum'], 10.25)


    def test_compute_measurement_summary_ignores_inactive_lower_side_for_gdt_zero_bound(self):
        header_group = RowTable(rows=((-0.01,), (0.02,), (0.12,)), columns=('MEAS',))

        summary = compute_measurement_summary(header_group, usl=0.1, lsl=0.0, nom=0.0)

        self.assertEqual(summary['spec_type'], 'one_sided_upper')
        self.assertEqual(summary['nok_count'], 1)
        self.assertEqual(summary['observed_nok_below_lsl_count'], 0)
        self.assertEqual(summary['observed_nok_above_usl_count'], 1)
        self.assertAlmostEqual(summary['nok_pct'], 1 / 3)


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
        header_group = RowTable(
            rows=(('1.0', '1'), ('1.1', '1'), ('1.2', '2'), ('1.3', '2')),
            columns=('MEAS', 'SAMPLE_NUMBER'),
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

    def test_resolve_shared_x_axis_label_layout_matches_sparse_tick_contract(self):
        labels = [f'Label-{index:02d}' for index in range(30)]
        positions = list(range(len(labels)))

        layout = resolve_shared_x_axis_label_layout(
            labels,
            positions=positions,
            thinning_threshold=10,
            target_tick_count=5,
            force_sparse=True,
        )

        self.assertIsInstance(layout, dict)
        self.assertEqual(layout['display_positions'], [0, 6, 12, 18, 24, 29])
        self.assertEqual(len(layout['display_labels']), len(layout['display_positions']))


if __name__ == '__main__':
    unittest.main()

def test_to_numeric_array_literal_conversion_and_copy_contract():
    from decimal import Decimal
    from metroliza.exporting.export_summary_utils import _is_missing_value, _to_numeric_array

    cases = [[], [None, '', 'bad', '0.30000000000000004', Decimal('1.25'), -0., np.inf],
             np.array(1.), np.array([[1., 2.], [3., np.nan]]),
             np.array([0x7ff0000000000001, 0xfff8000000000001], dtype=np.uint64).view(np.float64),
             np.array([0x7f800001, 0xffc00001], dtype=np.uint32).view(np.float32),
             np.array([True, False]), np.array([1, 2]),
             np.array(['1.5\x00', 'nan', '1.25']), np.array([None, Decimal('2')], dtype=object)]
    for dtype in (np.float16, np.float32, np.float64, np.longdouble):
        cases.extend([np.array([1., -0., np.nan, np.inf, -np.inf], dtype=dtype),
                      np.array([1., 2., 3., 4.], dtype=dtype)[::2], np.array([], dtype=dtype)])
    for values in cases:
        results = []
        for reference in (True, False):
            with warnings.catch_warnings(record=True) as emitted:
                warnings.simplefilter('always')
                try:
                    if reference:
                        numeric = []
                        for value in values:
                            if _is_missing_value(value):
                                continue
                            try:
                                value = float(value)
                            except (TypeError, ValueError):
                                continue
                            if np.isfinite(value):
                                numeric.append(value)
                        result = np.asarray(numeric, dtype=float)
                    else:
                        result = _to_numeric_array(values)
                    assert not isinstance(values, np.ndarray) or not np.shares_memory(result, values)
                    outcome = (result.dtype.str, result.shape, result.tobytes())
                except (TypeError, ValueError) as exc:
                    outcome = (type(exc), str(exc))
                results.append((outcome, [(type(w.message), str(w.message)) for w in emitted]))
        assert results[0] == results[1]


def test_to_numeric_array_fast_path_and_scalar_fallback():
    from unittest import mock
    from metroliza.exporting import export_summary_utils as module

    for dtype in (np.float16, np.float32, np.float64):
        values = np.array([1., -0., np.nan, np.inf, -np.inf], dtype=dtype)
        values.flags.writeable = False
        with mock.patch.object(module, '_is_missing_value', side_effect=AssertionError('scalar conversion')):
            assert module._to_numeric_array(values).tobytes() == np.array([1., -0.]).tobytes()
    with mock.patch.object(module, '_is_missing_value', wraps=module._is_missing_value) as scalar:
        module._to_numeric_array(np.array([1., 2.], dtype=np.longdouble))
        module._to_numeric_array([None, '2'])
        assert scalar.call_count == 4

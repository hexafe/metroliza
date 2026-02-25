import sys
import types
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


qtcore_stub = types.ModuleType('PyQt6.QtCore')


class _DummyThread:
    def __init__(self, *args, **kwargs):
        pass


class _DummyCoreApp:
    @staticmethod
    def processEvents():
        return None


def _dummy_signal(*args, **kwargs):
    class _Signal:
        def emit(self, *a, **k):
            return None

    return _Signal()


qtcore_stub.QCoreApplication = _DummyCoreApp
qtcore_stub.QThread = _DummyThread
qtcore_stub.pyqtSignal = _dummy_signal
sys.modules['PyQt6.QtCore'] = qtcore_stub

custom_logger_stub = types.ModuleType('modules.CustomLogger')


class _DummyLogger:
    def __init__(self, *args, **kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyLogger
sys.modules['modules.CustomLogger'] = custom_logger_stub

from modules.ExportDataThread import (  # noqa: E402
    build_measurement_block_plan,
    build_measurement_chart_series_specs,
    build_measurement_stat_row_specs,
    build_histogram_density_curve_payload,
    build_measurement_stat_formulas,
    build_violin_group_stats_rows,
    compute_scaled_y_limits,
    render_iqr_boxplot,
)


class TestExportPlotHelpers(unittest.TestCase):
    def test_compute_scaled_y_limits_expands_symmetrically(self):
        y_min, y_max = compute_scaled_y_limits((10.0, 20.0), 0.4)

        self.assertEqual(y_min, 8.0)
        self.assertEqual(y_max, 22.0)

    def test_build_histogram_density_curve_payload_builds_curve_for_variable_data(self):
        payload = build_histogram_density_curve_payload([1.0, 1.5, 2.0, 2.5])

        self.assertIsNotNone(payload)
        self.assertEqual(len(payload['x']), 100)
        self.assertEqual(len(payload['y']), 100)

    def test_build_histogram_density_curve_payload_returns_none_for_constant_data(self):
        payload = build_histogram_density_curve_payload([3.0, 3.0, 3.0])

        self.assertIsNone(payload)

    def test_build_measurement_stat_formulas_uses_single_sided_cpk_when_nominal_and_lsl_are_zero(self):
        formulas = build_measurement_stat_formulas(
            summary_col='B',
            data_range_y='C22:C30',
            nom_cell='$B$1',
            usl_cell='$B$2',
            lsl_cell='$B$3',
            nom_value=0,
            lsl_value=0,
        )

        self.assertEqual(formulas['min'], '=ROUND(MIN(C22:C30), 3)')
        self.assertEqual(formulas['sample_size'], '=COUNT(C22:C30)')
        self.assertIn('(B1 + B2)', formulas['cpk'])
        self.assertNotIn('MIN(', formulas['cpk'])

    def test_build_measurement_stat_formulas_uses_dual_sided_cpk_otherwise(self):
        formulas = build_measurement_stat_formulas(
            summary_col='D',
            data_range_y='E22:E40',
            nom_cell='$D$1',
            usl_cell='$D$2',
            lsl_cell='$D$3',
            nom_value=5.0,
            lsl_value=-0.2,
        )

        self.assertIn('MIN(', formulas['cpk'])
        self.assertEqual(formulas['nok_total'], '=COUNTIF(E22:E40, ">"&($D$1+$D$2))+COUNTIF(E22:E40, "<"&($D$1+$D$3))')


    def test_build_measurement_stat_row_specs_returns_expected_order_and_styles(self):
        formulas = {
            'min': '=MIN(C22:C30)',
            'avg': '=AVERAGE(C22:C30)',
            'max': '=MAX(C22:C30)',
            'std': '=STDEV(C22:C30)',
            'cp': '=1.11',
            'cpk': '=1.02',
            'nok_total': '=2',
            'nok_percent': '=10%',
            'sample_size': '=20',
        }

        rows = build_measurement_stat_row_specs(formulas)

        self.assertEqual([row[0] for row in rows], [
            'MIN', 'AVG', 'MAX', 'STD', 'Cp', 'Cpk', 'NOK number', 'NOK %', 'Sample size'
        ])
        self.assertEqual(rows[7][2], 'percent')
        self.assertTrue(all(style is None for _, _, style in rows[:7]))
        self.assertIsNone(rows[8][2])


    def test_build_measurement_block_plan_returns_expected_coordinates(self):
        plan = build_measurement_block_plan(base_col=6, sample_size=10)

        self.assertEqual(plan['data_header_row'], 20)
        self.assertEqual(plan['data_start_row'], 21)
        self.assertEqual(plan['last_data_row'], 30)
        self.assertEqual(plan['summary_column'], 7)
        self.assertEqual(plan['y_column'], 8)
        self.assertEqual(plan['data_range_y'], 'I22:I31')

    def test_build_measurement_block_plan_rejects_empty_sample_size(self):
        with self.assertRaises(ValueError):
            build_measurement_block_plan(base_col=4, sample_size=0)

    def test_build_measurement_chart_series_specs_uses_range_backed_series(self):
        series = build_measurement_chart_series_specs(
            header='DIA',
            sheet_name='REF_PART_A',
            first_data_row=21,
            last_data_row=30,
            x_column=4,
            y_column=5,
        )

        self.assertEqual(len(series), 3)
        self.assertEqual(series[0]['name'], 'DIA')
        self.assertEqual(series[0]['categories'], '=REF_PART_A!$E22:E31')
        self.assertEqual(series[0]['values'], '=REF_PART_A!$F22:F31')

        self.assertEqual(series[1]['name'], 'USL')
        self.assertEqual(series[1]['values'], '=REF_PART_A!$F1:F2')

        self.assertEqual(series[2]['name'], 'LSL')
        self.assertEqual(series[2]['values'], '=REF_PART_A!$F3:F4')

    def test_build_violin_group_stats_rows_marks_reference_and_computes_pvalues(self):
        labels = ['A', 'B']
        values = [[1.0, 1.2, 0.8], [1.5, 1.6, 1.4]]

        rows = build_violin_group_stats_rows(labels, values)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], 'A')
        self.assertEqual(rows[0][-1], 'Ref')
        self.assertEqual(rows[1][0], 'B')
        self.assertNotEqual(rows[1][-1], 'Ref')

    def test_build_violin_group_stats_rows_uses_population_reference_for_single_group(self):
        rows = build_violin_group_stats_rows(['Only'], [[2.0, 2.1, 1.9]])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 'Only')
        self.assertNotEqual(rows[0][-1], 'Ref')

    def test_build_violin_group_stats_rows_returns_na_for_nearly_identical_groups(self):
        labels = ['A', 'B']
        values = [[1.0, 1.0, 1.0], [1.2, 1.2, 1.2]]

        rows = build_violin_group_stats_rows(labels, values)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][-1], 'Ref')
        self.assertEqual(rows[1][-1], 'N/A')

    def test_render_iqr_boxplot_sets_labels(self):
        fig, ax = plt.subplots()

        render_iqr_boxplot(ax, [[1.0, 1.1, 1.2], [2.0, 2.1, 3.5]], ['G1', 'G2'])

        rendered_labels = [tick.get_text() for tick in ax.get_xticklabels()]
        self.assertEqual(rendered_labels, ['G1', 'G2'])
        plt.close(fig)


if __name__ == '__main__':
    unittest.main()

import sys
import types
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE


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
    build_histogram_annotation_specs,
    build_measurement_chart_format_policy,
    build_measurement_block_plan,
    build_measurement_chart_range_specs,
    build_measurement_chart_series_specs,
    build_horizontal_limit_line_specs,
    build_measurement_header_block_plan,
    build_measurement_write_bundle,
    build_measurement_stat_row_specs,
    build_summary_image_anchor_plan,
    build_summary_sheet_position_plan,
    build_histogram_density_curve_payload,
    build_measurement_stat_formulas,
    build_violin_group_stats_rows,
    compute_scaled_y_limits,
    render_iqr_boxplot,
    build_iqr_legend_handles,
    add_iqr_boxplot_legend,
    apply_shared_x_axis_label_strategy,
    classify_capability_status,
    classify_nok_severity,
    build_summary_panel_subtitle_text,
    build_histogram_table_data,
    style_histogram_stats_table,
    resolve_violin_annotation_style,
    annotate_violin_group_stats,
    render_violin,
)


class TestExportPlotHelpers(unittest.TestCase):

    def test_resolve_violin_annotation_style_auto_full_keeps_minmax_and_sigma(self):
        style = resolve_violin_annotation_style(
            group_count=3,
            x_limits=(-0.5, 2.5),
            figure_size=(6, 4),
            mode='auto',
            readability_scale=0.2,
        )

        self.assertEqual(style['mode'], 'full')
        self.assertTrue(style['show_minmax'])
        self.assertTrue(style['show_sigma'])
        self.assertGreaterEqual(style['font_size'], 6.8)

    def test_resolve_violin_annotation_style_auto_compact_can_hide_sigma_for_dense_groups(self):
        style = resolve_violin_annotation_style(
            group_count=13,
            x_limits=(-0.5, 12.5),
            figure_size=(6, 4),
            mode='auto',
            readability_scale=0.0,
        )

        self.assertEqual(style['mode'], 'compact')
        self.assertFalse(style['show_minmax'])
        self.assertFalse(style['show_sigma'])
        self.assertGreaterEqual(style['font_size'], 6.8)

    def test_resolve_violin_annotation_style_compact_respects_readability_scaling(self):
        base = resolve_violin_annotation_style(
            group_count=8,
            x_limits=(-0.5, 7.5),
            figure_size=(6, 4),
            mode='compact',
            readability_scale=0.0,
        )
        scaled = resolve_violin_annotation_style(
            group_count=8,
            x_limits=(-0.5, 7.5),
            figure_size=(8, 4),
            mode='compact',
            readability_scale=0.6,
        )

        self.assertEqual(base['mode'], 'compact')
        self.assertEqual(scaled['mode'], 'compact')
        self.assertGreaterEqual(base['font_size'], 6.8)
        self.assertGreater(scaled['font_size'], base['font_size'])
        self.assertGreater(scaled['mean_marker_size'], base['mean_marker_size'])

    def test_build_summary_sheet_position_plan_matches_legacy_three_column_block_math(self):
        first = build_summary_sheet_position_plan(3)
        second = build_summary_sheet_position_plan(6)

        self.assertEqual(first, {'row': 0, 'column': 0, 'header_row': 0, 'image_row': 1})
        self.assertEqual(second, {'row': 20, 'column': 0, 'header_row': 20, 'image_row': 21})

    def test_build_summary_image_anchor_plan_returns_stable_panel_coordinates(self):
        anchors = build_summary_image_anchor_plan(9)

        self.assertEqual(anchors['header'], (40, 0))
        self.assertEqual(anchors['distribution'], (41, 0))
        self.assertEqual(anchors['iqr'], (41, 9))
        self.assertEqual(anchors['histogram'], (41, 19))
        self.assertEqual(anchors['trend'], (41, 29))

    def test_build_histogram_annotation_specs_returns_ordered_mean_usl_lsl_labels(self):
        annotations = build_histogram_annotation_specs(average=10.1234, usl=10.6, lsl=9.8, y_max=2.0)

        self.assertEqual(len(annotations), 3)
        self.assertEqual(annotations[0]['text'], 'μ=10.123')
        self.assertEqual(annotations[0]['x'], 10.1234)
        self.assertEqual(annotations[0]['y'], 1.9)
        self.assertEqual(annotations[1]['text'], 'USL=10.600')
        self.assertEqual(annotations[1]['ha'], 'right')
        self.assertEqual(annotations[2]['text'], 'LSL=9.800')
        self.assertEqual(annotations[2]['ha'], 'left')

    def test_summary_palette_keeps_annotation_emphasis_alias_for_backward_compatibility(self):
        self.assertEqual(
            SUMMARY_PLOT_PALETTE['annotation_emphasis'],
            SUMMARY_PLOT_PALETTE['central_tendency'],
        )

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




    def test_classify_capability_status_maps_threshold_tiers(self):
        self.assertEqual(classify_capability_status(1.7, 1.7)['palette_key'], 'quality_capable')
        self.assertEqual(classify_capability_status(1.4, 1.35)['palette_key'], 'quality_good')
        self.assertEqual(classify_capability_status(1.1, 1.0)['palette_key'], 'quality_marginal')
        self.assertEqual(classify_capability_status(0.9, 0.8)['palette_key'], 'quality_risk')
        self.assertEqual(classify_capability_status('N/A', 'N/A')['palette_key'], 'quality_unknown')

    def test_classify_nok_severity_maps_scan_friendly_levels(self):
        self.assertEqual(classify_nok_severity(0.0)['palette_key'], 'quality_capable')
        self.assertEqual(classify_nok_severity(0.01)['palette_key'], 'quality_good')
        self.assertEqual(classify_nok_severity(0.03)['palette_key'], 'quality_marginal')
        self.assertEqual(classify_nok_severity(0.08)['palette_key'], 'quality_risk')

    def test_build_summary_panel_subtitle_text_formats_samples_and_nok_percent(self):
        subtitle = build_summary_panel_subtitle_text({'sample_size': 12, 'nok_pct': 0.083333})

        self.assertEqual(subtitle, 'n=12 • NOK=8.3%')

    def test_build_histogram_table_data_formats_nok_as_percent_string(self):
        table = build_histogram_table_data(
            {
                'minimum': 1.0,
                'maximum': 2.0,
                'average': 1.5,
                'median': 1.5,
                'sigma': 0.1,
                'cp': 1.2,
                'cpk': 1.1,
                'sample_size': 10,
                'nok_count': 2,
                'nok_pct': 0.083333,
            }
        )

        self.assertEqual(table[-1], ('NOK %', '8.33%'))

    def test_style_histogram_stats_table_applies_capability_badge_to_cp_rows(self):
        fig, ax = plt.subplots(figsize=(4, 3))
        table_data = [('Cp', 1.45), ('Cpk', 1.4), ('NOK %', 2.5)]
        ax_table = ax.table(cellText=table_data, colLabels=['Statistic', 'Value'], cellLoc='center')

        style_histogram_stats_table(
            ax_table,
            table_data,
            capability_badge={'label': 'Cp/Cpk good', 'palette_key': 'quality_good'},
        )

        self.assertEqual(ax_table.get_celld()[(1, 1)].get_text().get_text(), '1.45')
        self.assertEqual(ax_table.get_celld()[(2, 1)].get_text().get_text(), '1.4')
        self.assertEqual(ax_table.get_celld()[(1, 0)].get_text().get_text(), 'Cp')
        self.assertEqual(ax_table.get_celld()[(2, 0)].get_text().get_text(), 'Cpk')
        plt.close(fig)

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

    def test_build_horizontal_limit_line_specs_matches_summary_render_contract(self):
        line_specs = build_horizontal_limit_line_specs(10.6, 9.8)

        self.assertEqual(line_specs[0]['y'], 10.6)
        self.assertEqual(line_specs[1]['y'], 9.8)
        self.assertEqual(line_specs[0]['linestyle'], '--')
        self.assertEqual(line_specs[1]['color'], '#9b1c1c')

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

    def test_build_measurement_chart_range_specs_returns_backend_agnostic_ranges(self):
        ranges = build_measurement_chart_range_specs(
            sheet_name='REF_PART_A',
            first_data_row=21,
            last_data_row=30,
            x_column=4,
            y_column=5,
        )

        self.assertEqual(
            ranges,
            {
                'data_x': '=REF_PART_A!$E22:E31',
                'data_y': '=REF_PART_A!$F22:F31',
                'usl_x': '=REF_PART_A!$E1:E2',
                'usl_y': '=REF_PART_A!$F1:F2',
                'lsl_x': '=REF_PART_A!$E3:E4',
                'lsl_y': '=REF_PART_A!$F3:F4',
            },
        )

    def test_build_measurement_header_block_plan_keeps_legacy_row_math(self):
        import pandas as pd

        header_group = pd.DataFrame(
            {
                'NOM': [10.0, 10.0, 10.0],
                '+TOL': [0.5, 0.5, 0.5],
                '-TOL': [-0.2, -0.2, -0.2],
                'MEAS': [10.1, 10.3, 9.95],
            }
        )

        plan = build_measurement_header_block_plan(header_group, base_col=3)

        self.assertEqual(plan['nom'], 10.0)
        self.assertEqual(plan['plus_tol'], 0.5)
        self.assertEqual(plan['minus_tol'], -0.2)
        self.assertEqual(plan['usl'], 10.5)
        self.assertEqual(plan['lsl'], 9.8)
        self.assertEqual(plan['first_data_row'], 21)
        self.assertEqual(plan['last_data_row'], 23)
        self.assertEqual(plan['nom_cell'], '$E$1')
        self.assertEqual(plan['usl_cell'], '$E$2')
        self.assertEqual(plan['lsl_cell'], '$E$3')
        self.assertEqual(plan['spec_limit_rows'][0], ('USL_MAX', 10.5))
        self.assertEqual(plan['spec_limit_rows'][2], ('LSL_MAX', 9.8))
        self.assertEqual(plan['stat_rows'][0][1], '=ROUND(MIN(F22:F24), 3)')

    def test_build_measurement_write_bundle_keeps_per_header_layout_contract(self):
        import pandas as pd

        header_group = pd.DataFrame(
            {
                'NOM': [10.0, 10.0],
                '+TOL': [0.5, 0.5],
                '-TOL': [-0.2, -0.2],
                'MEAS': [10.125, 9.995],
                'DATE': ['2026-02-25', '2026-02-26'],
                'SAMPLE_NUMBER': ['1', '2'],
            }
        )

        bundle = build_measurement_write_bundle('DIA - X', header_group, base_col=6)

        self.assertEqual(bundle['static_rows'], [(0, 'NOM', 10.0), (1, '+TOL', 0.5), (2, '-TOL', -0.2)])
        self.assertEqual(bundle['measurement_plan']['data_start_row'], 21)

        self.assertEqual(bundle['data_columns'][0][0:3], (20, 6, 'Date'))
        pd.testing.assert_series_equal(bundle['data_columns'][0][3], header_group['DATE'])

        self.assertEqual(bundle['data_columns'][1][0:3], (20, 7, 'Sample #'))
        pd.testing.assert_series_equal(bundle['data_columns'][1][3], header_group['SAMPLE_NUMBER'])

        self.assertEqual(bundle['data_columns'][2][0:3], (20, 8, 'DIA - X'))
        self.assertEqual(bundle['data_columns'][2][4], 'wrap')
        self.assertEqual(list(bundle['data_columns'][2][3]), [10.125, 9.995])

    def test_build_measurement_chart_format_policy_returns_expected_defaults(self):
        policy = build_measurement_chart_format_policy('DIA - X')

        self.assertEqual(policy['title']['name'], 'DIA - X')
        self.assertEqual(policy['title']['name_font']['size'], 10)
        self.assertEqual(policy['y_axis']['major_gridlines']['visible'], False)
        self.assertEqual(policy['legend']['position'], 'none')
        self.assertEqual(policy['size'], {'width': 240, 'height': 160})

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


    def test_shared_x_axis_label_strategy_uses_zero_rotation_for_short_labels(self):
        fig, ax = plt.subplots()

        apply_shared_x_axis_label_strategy(ax, ['A', 'B', 'C'])

        labels = ax.get_xticklabels()
        self.assertEqual([tick.get_text() for tick in labels], ['A', 'B', 'C'])
        self.assertTrue(all(int(tick.get_rotation()) == 0 for tick in labels))
        self.assertTrue(all(tick.get_ha() == 'center' for tick in labels))
        plt.close(fig)

    def test_shared_x_axis_label_strategy_truncates_and_thins_dense_labels(self):
        fig, ax = plt.subplots()
        positions = list(range(30))
        labels = [f'LONG_LABEL_{idx:02d}_ABCDEFGHIJ' for idx in positions]

        apply_shared_x_axis_label_strategy(
            ax,
            labels,
            positions=positions,
            max_label_chars=10,
            thinning_threshold=20,
            target_tick_count=10,
            tick_padding=11,
        )

        rendered = ax.get_xticklabels()
        self.assertLess(len(rendered), len(labels))
        self.assertTrue(all(tick.get_text().endswith('…') for tick in rendered[:-1]))
        self.assertEqual(int(rendered[0].get_rotation()), 90)
        self.assertTrue(all(tick.get_ha() == 'right' for tick in rendered))
        self.assertEqual(ax.xaxis.majorTicks[0].get_pad(), 11)
        self.assertEqual(ax.get_xticks()[-1], 29)
        plt.close(fig)


    def test_build_iqr_legend_handles_uses_stable_labels(self):
        handles = build_iqr_legend_handles()

        self.assertEqual(len(handles), 4)
        self.assertEqual([handle.get_label() for handle in handles], [
            'IQR range (Q1-Q3)',
            'Median',
            'Whiskers (1.5 IQR rule)',
            'Outliers',
        ])

    def test_add_iqr_boxplot_legend_attaches_expected_legend(self):
        fig, ax = plt.subplots()

        render_iqr_boxplot(ax, [[1.0, 1.1, 1.2], [2.0, 2.1, 3.5]], ['G1', 'G2'])
        add_iqr_boxplot_legend(ax)

        legend = ax.get_legend()
        self.assertIsNotNone(legend)
        self.assertEqual([text.get_text() for text in legend.get_texts()], [
            'IQR range (Q1-Q3)',
            'Median',
            'Whiskers (1.5 IQR rule)',
            'Outliers',
        ])
        plt.close(fig)

    def test_render_iqr_boxplot_sets_labels(self):
        fig, ax = plt.subplots()

        render_iqr_boxplot(ax, [[1.0, 1.1, 1.2], [2.0, 2.1, 3.5]], ['G1', 'G2'])

        rendered_labels = [tick.get_text() for tick in ax.get_xticklabels()]
        self.assertEqual(rendered_labels, ['G1', 'G2'])
        plt.close(fig)

    def test_annotate_violin_group_stats_does_not_emit_plus_minus_three_sigma_text(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.set_xlim(-0.5, 1.5)

        annotate_violin_group_stats(
            ax,
            ['A', 'B'],
            [[1.0, 1.2, 0.8], [1.5, 1.7, 1.4]],
            annotation_mode='full',
        )

        texts = [text.get_text() for text in ax.texts]
        self.assertFalse(any(label.startswith('-3σ=') or label.startswith('+3σ=') for label in texts))
        self.assertTrue(any('μ=' in label for label in texts))
        plt.close(fig)

    def test_render_violin_adds_legend_entries_for_annotation_symbols(self):
        fig, ax = plt.subplots(figsize=(6, 4))

        render_violin(
            ax,
            [[1.0, 1.2, 0.8], [1.5, 1.7, 1.4]],
            ['A', 'B'],
            readability_scale=0.3,
        )

        legend = ax.get_legend()
        self.assertIsNotNone(legend)
        legend_labels = [text.get_text() for text in legend.get_texts()]
        self.assertIn('Mean marker (μ)', legend_labels)
        self.assertIn('Min marker', legend_labels)
        self.assertIn('Max marker', legend_labels)
        self.assertIn('±3σ span (visual)', legend_labels)
        self.assertIn('Text box: value annotation', legend_labels)
        plt.close(fig)

    def test_annotation_collision_resolution_is_deterministic_for_dense_groups(self):
        values = [[1.0, 1.0, 1.0], [1.01, 1.01, 1.01], [1.02, 1.02, 1.02], [1.03, 1.03, 1.03]]
        labels = ['G1', 'G2', 'G3', 'G4']

        fig_one, ax_one = plt.subplots(figsize=(6, 4))
        ax_one.set_xlim(-0.5, len(labels) - 0.5)
        annotate_violin_group_stats(ax_one, labels, values, annotation_mode='full')
        positions_one = [(round(text.xyann[0], 2), round(text.xyann[1], 2), text.get_text()) for text in ax_one.texts]

        fig_two, ax_two = plt.subplots(figsize=(6, 4))
        ax_two.set_xlim(-0.5, len(labels) - 0.5)
        annotate_violin_group_stats(ax_two, labels, values, annotation_mode='full')
        positions_two = [(round(text.xyann[0], 2), round(text.xyann[1], 2), text.get_text()) for text in ax_two.texts]

        self.assertEqual(positions_one, positions_two)
        base_offsets = {(4.0, -10.0), (4.0, 2.0)}
        self.assertTrue(any((x, y) not in base_offsets for x, y, _ in positions_one))
        plt.close(fig_one)
        plt.close(fig_two)


if __name__ == '__main__':
    unittest.main()

import sys
import types
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE, EMPHASIS_TABLE_ROWS
from modules.export_summary_utils import compute_normality_status


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
    build_histogram_mean_line_style,
    compute_histogram_font_sizes,
    render_histogram_annotations,
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
    add_violin_annotation_legend,
    move_legend_to_figure,
    build_wrapped_chart_title,
    render_tolerance_band,
    render_spec_reference_lines,
    build_tolerance_reference_legend_handles,
    apply_shared_x_axis_label_strategy,
    classify_capability_status,
    classify_nok_severity,
    build_summary_panel_subtitle_text,
    build_histogram_table_data,
    style_histogram_stats_table,
    adjust_histogram_stats_table_geometry,
    classify_normality_status,
    resolve_violin_annotation_style,
    annotate_violin_group_stats,
    render_violin,
    render_scatter_numeric,
    render_histogram,
    resolve_summary_annotation_strategy,
)


class TestExportPlotHelpers(unittest.TestCase):


    def test_resolve_summary_annotation_strategy_prefers_static_for_dense_axes(self):
        sparse = resolve_summary_annotation_strategy(x_point_count=80)
        medium = resolve_summary_annotation_strategy(x_point_count=30)
        dynamic = resolve_summary_annotation_strategy(x_point_count=10)

        self.assertEqual(sparse['label_mode'], 'sparse')
        self.assertEqual(sparse['annotation_mode'], 'static_compact')
        self.assertFalse(sparse['show_violin_legend'])

        self.assertEqual(medium['label_mode'], 'adaptive')
        self.assertEqual(medium['annotation_mode'], 'static_compact')
        self.assertTrue(medium['show_violin_legend'])

        self.assertEqual(dynamic['annotation_mode'], 'dynamic')

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
        self.assertTrue(style['show_minmax'])
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

    def test_build_summary_sheet_position_plan_matches_five_column_block_math(self):
        first = build_summary_sheet_position_plan(5)
        second = build_summary_sheet_position_plan(10)

        self.assertEqual(first, {'row': 0, 'column': 0, 'header_row': 0, 'image_row': 1})
        self.assertEqual(second, {'row': 20, 'column': 0, 'header_row': 20, 'image_row': 21})

    def test_build_summary_image_anchor_plan_returns_stable_panel_coordinates(self):
        anchors = build_summary_image_anchor_plan(15)

        self.assertEqual(anchors['header'], (40, 0))
        self.assertEqual(anchors['distribution'], (41, 0))
        self.assertEqual(anchors['iqr'], (41, 9))
        self.assertEqual(anchors['histogram'], (41, 19))
        self.assertEqual(anchors['trend'], (41, 29))

    def test_build_summary_sheet_position_plan_stacks_sequential_headers_without_gaps(self):
        rows = [build_summary_sheet_position_plan(base_col)['row'] for base_col in (5, 10, 15, 20)]

        self.assertEqual(rows, [0, 20, 40, 60])

    def test_build_summary_image_anchor_plan_stacks_header_rows_without_gaps(self):
        header_rows = [
            build_summary_image_anchor_plan(base_col)['header'][0]
            for base_col in (5, 10, 15, 20)
        ]

        self.assertEqual(header_rows, [0, 20, 40, 60])

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

    def test_emphasis_table_rows_include_normality(self):
        self.assertIn('Normality', EMPHASIS_TABLE_ROWS)

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



    def test_adjust_histogram_stats_table_geometry_scales_rows_and_stat_column(self):
        fig, ax = plt.subplots()
        ax_table = plt.table(
            cellText=[['Min', '1.0'], ['Max', '2.0']],
            colLabels=['Statistic', 'Value'],
            cellLoc='center',
            loc='right',
            bbox=[1, 0, 0.3, 1],
        )

        base_stat_width = ax_table.get_celld()[(1, 0)].get_width()
        base_value_width = ax_table.get_celld()[(1, 1)].get_width()
        base_height = ax_table.get_celld()[(1, 0)].get_height()

        adjust_histogram_stats_table_geometry(
            ax_table,
            statistic_col_width_ratio=0.56,
            row_height_scale=1.15,
        )

        self.assertAlmostEqual(ax_table.get_celld()[(0, 0)].get_width(), 0.56)
        self.assertAlmostEqual(ax_table.get_celld()[(0, 1)].get_width(), 0.44)
        self.assertGreater(ax_table.get_celld()[(1, 0)].get_height(), base_height)
        self.assertGreater(ax_table.get_celld()[(1, 0)].get_width(), base_stat_width)
        self.assertLess(ax_table.get_celld()[(1, 1)].get_width(), base_value_width)

        plt.close(fig)
    def test_build_histogram_density_curve_payload_accepts_numeric_string_measurements(self):
        payload = build_histogram_density_curve_payload(['1.0', '1.5', '2.0', '2.5'])

        self.assertIsNotNone(payload)
        self.assertEqual(len(payload['x']), 100)
        self.assertEqual(len(payload['y']), 100)

    def test_classify_normality_status_maps_all_quality_paths(self):
        self.assertEqual(classify_normality_status('normal')['palette_key'], 'quality_good')
        self.assertEqual(classify_normality_status('not_normal')['palette_key'], 'quality_risk')
        self.assertEqual(classify_normality_status('unknown')['palette_key'], 'quality_unknown')

    def test_compute_normality_status_returns_unknown_for_small_or_constant_samples(self):
        self.assertEqual(compute_normality_status([1.0, 2.0])['text'], 'Unknown')
        self.assertEqual(compute_normality_status([3.0, 3.0, 3.0])['text'], 'Unknown')

    def test_compute_normality_status_returns_normal_for_gaussian_like_series(self):
        result = compute_normality_status([-1.2, -0.4, -0.1, 0.0, 0.2, 0.5, 1.1, 1.4])

        self.assertEqual(result['status'], 'normal')
        self.assertIn('Shapiro p=', result['text'])
        self.assertTrue(result['text'].endswith('→ Normal'))

    def test_compute_normality_status_returns_not_normal_for_skewed_series(self):
        result = compute_normality_status([0.0, 0.0, 0.0, 0.1, 0.2, 0.3, 4.0, 8.0])

        self.assertEqual(result['status'], 'not_normal')
        self.assertIn('Shapiro p=', result['text'])
        self.assertTrue(result['text'].endswith('→ Not normal'))

    def test_render_histogram_handles_numeric_strings_without_matplotlib_warnings(self):
        import pandas as pd
        import warnings

        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                render_histogram(ax, pd.DataFrame({'MEAS': ['1.0', '2.5', '2.0', '3.2']}))

            matplotlib_warnings = [
                item for item in caught
                if 'matplotlib' in str(item.category).lower() or 'converter' in str(item.message).lower()
            ]
            self.assertEqual(matplotlib_warnings, [])
        finally:
            plt.close(fig)

    def test_build_measurement_stat_formulas_uses_single_sided_cpk_when_nominal_and_lsl_are_zero(self):
        formulas = build_measurement_stat_formulas(
            summary_col='B',
            stats_col='D',
            data_range_y='C22:C30',
            nom_cell='$B$1',
            usl_cell='$B$2',
            lsl_cell='$B$3',
            nom_value=0,
            lsl_value=0,
        )

        self.assertEqual(formulas['min'], '=ROUND(MIN(C22:C30), 3)')
        self.assertEqual(formulas['sample_size'], '=COUNT(C22:C30)')
        self.assertEqual(formulas['cp'], '="N/A"')
        self.assertIn('(B1 + B2)', formulas['cpk'])
        self.assertNotIn('MIN(', formulas['cpk'])

    def test_build_measurement_stat_formulas_uses_single_sided_cpk_when_nominal_and_lsl_are_near_zero(self):
        formulas = build_measurement_stat_formulas(
            summary_col='B',
            stats_col='D',
            data_range_y='C22:C30',
            nom_cell='$B$1',
            usl_cell='$B$2',
            lsl_cell='$B$3',
            nom_value=1e-13,
            lsl_value=-1e-13,
        )

        self.assertEqual(formulas['cp'], '="N/A"')
        self.assertIn('(B1 + B2)', formulas['cpk'])
        self.assertNotIn('MIN(', formulas['cpk'])

    def test_build_measurement_stat_formulas_uses_dual_sided_cpk_otherwise(self):
        formulas = build_measurement_stat_formulas(
            summary_col='D',
            stats_col='F',
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
        self.assertEqual(classify_capability_status(0.99, 0.8)['palette_key'], 'quality_risk')
        self.assertEqual(classify_capability_status(1.0, 1.0)['palette_key'], 'quality_marginal')
        self.assertEqual(classify_capability_status(1.33, 1.33)['palette_key'], 'quality_marginal')
        self.assertEqual(classify_capability_status(1.34, 1.34)['palette_key'], 'quality_good')
        self.assertEqual(classify_capability_status(1.66, 1.5)['palette_key'], 'quality_good')
        self.assertEqual(classify_capability_status(1.67, 1.67)['palette_key'], 'quality_capable')
        self.assertEqual(classify_capability_status('N/A', 'N/A')['palette_key'], 'quality_unknown')

    def test_classify_nok_severity_maps_scan_friendly_levels(self):
        self.assertEqual(classify_nok_severity(0.003)['palette_key'], 'quality_capable')
        self.assertEqual(classify_nok_severity(0.0031)['palette_key'], 'quality_marginal')
        self.assertEqual(classify_nok_severity(0.0499)['palette_key'], 'quality_marginal')
        self.assertEqual(classify_nok_severity(0.05)['palette_key'], 'quality_marginal')
        self.assertEqual(classify_nok_severity(0.0501)['palette_key'], 'quality_risk')


    def test_build_histogram_mean_line_style_uses_dashed_lower_alpha_policy(self):
        style = build_histogram_mean_line_style()

        self.assertEqual(style['linestyle'], '--')
        self.assertLess(style['alpha'], 0.8)

    def test_render_histogram_annotations_renders_mean_usl_lsl_and_offsets_mean_right(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.set_xlim(0.0, 10.0)
        annotation_specs = build_histogram_annotation_specs(average=4.0, usl=8.0, lsl=2.0, y_max=1.0)

        rendered = render_histogram_annotations(
            ax,
            annotation_specs,
            annotation_fontsize=8.5,
            annotation_box={'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': '#cccccc', 'alpha': 0.94},
        )

        self.assertEqual(len(rendered), 3)
        self.assertEqual([text.get_text() for text in rendered], ['μ=4.000', 'USL=8.000', 'LSL=2.000'])
        self.assertGreater(rendered[0].get_position()[0], 4.0)
        self.assertEqual(rendered[1].get_position()[0], 8.0)
        self.assertEqual(rendered[2].get_position()[0], 2.0)
        plt.close(fig)

    def test_histogram_annotations_include_usl_lsl_even_when_fontsize_is_compact(self):
        font_sizes = compute_histogram_font_sizes((6, 4), has_table=True)
        self.assertLess(font_sizes['annotation_fontsize'], 8.2)

        fig, ax = plt.subplots(figsize=(6, 4))
        annotation_specs = build_histogram_annotation_specs(average=10.0, usl=10.5, lsl=9.5, y_max=1.0)
        rendered = render_histogram_annotations(
            ax,
            annotation_specs,
            annotation_fontsize=font_sizes['annotation_fontsize'],
            annotation_box={'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': '#cccccc', 'alpha': 0.94},
        )

        texts = {text.get_text() for text in rendered}
        self.assertIn('USL=10.500', texts)
        self.assertIn('LSL=9.500', texts)
        plt.close(fig)

    def test_histogram_annotation_fontsize_contract_is_shared_for_mean_usl_lsl(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        annotation_specs = build_histogram_annotation_specs(average=1.0, usl=1.2, lsl=0.8, y_max=1.0)

        rendered = render_histogram_annotations(
            ax,
            annotation_specs,
            annotation_fontsize=9.1,
            annotation_box={'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': '#cccccc', 'alpha': 0.94},
        )

        self.assertEqual({text.get_fontsize() for text in rendered}, {9.1})
        plt.close(fig)

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

        self.assertEqual(table[-2], ('NOK %', '8.33%'))
        self.assertEqual(table[-1], ('Normality', 'Unknown'))


    def test_style_histogram_stats_table_applies_normality_badges_for_each_status(self):
        scenarios = [
            ('Normal', 'normal', 'quality_good_bg'),
            ('Non-normal', 'not_normal', 'quality_risk_bg'),
            ('Not sure', 'unknown', 'quality_unknown_bg'),
        ]

        for normality_text, status, palette_bg in scenarios:
            fig, ax = plt.subplots(figsize=(4, 3))
            table_data = [('Normality', normality_text), ('', ''), ('', '')]
            ax_table = ax.table(cellText=table_data, colLabels=['Statistic', 'Value'], cellLoc='center')

            style_histogram_stats_table(
                ax_table,
                table_data,
                capability_row_badges={'Normality': classify_normality_status(status)},
            )

            self.assertEqual(
                ax_table.get_celld()[(1, 0)].get_facecolor(),
                matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE[palette_bg]),
            )
            self.assertEqual(
                ax_table.get_celld()[(1, 1)].get_facecolor(),
                matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE[palette_bg]),
            )
            self.assertFalse(ax_table.get_celld()[(2, 0)].get_visible())
            self.assertFalse(ax_table.get_celld()[(2, 1)].get_visible())
            self.assertFalse(ax_table.get_celld()[(3, 0)].get_visible())
            self.assertFalse(ax_table.get_celld()[(3, 1)].get_visible())
            self.assertEqual(ax_table.get_celld()[(1, 0)].get_text().get_text(), 'Normality')
            self.assertIn(ax_table.get_celld()[(1, 1)].get_text().get_text(), {'Normal', 'Non-normal', 'Not sure'})
            plt.close(fig)


    def test_move_legend_to_figure_reparents_axis_legend_and_adjusts_top(self):
        fig, ax = plt.subplots(figsize=(4, 3))

        add_iqr_boxplot_legend(ax)
        self.assertIsNotNone(ax.get_legend())
        self.assertEqual(len(fig.legends), 0)

        move_legend_to_figure(ax)

        self.assertIsNone(ax.get_legend())
        self.assertEqual(len(fig.legends), 1)
        figure_legend = fig.legends[0]
        self.assertEqual(1, figure_legend._loc)
        bbox = figure_legend.get_bbox_to_anchor()._bbox
        self.assertAlmostEqual(0.99, bbox.x0, places=2)
        self.assertAlmostEqual(0.975, bbox.y0, places=2)
        self.assertAlmostEqual(0.82, fig.subplotpars.top, places=2)
        plt.close(fig)

    def test_move_legend_to_figure_keeps_iqr_legend_labels(self):
        fig, ax = plt.subplots()

        render_iqr_boxplot(ax, [[1.0, 1.1, 1.2], [2.0, 2.1, 3.5]], ['G1', 'G2'])
        add_iqr_boxplot_legend(ax)
        move_legend_to_figure(ax)

        self.assertEqual([text.get_text() for text in fig.legends[0].get_texts()], [
            'IQR range (Q1-Q3)',
            'Median',
            'Whiskers (1.5 IQR rule)',
            'Outliers',
        ])
        plt.close(fig)

    def test_move_legend_to_figure_keeps_violin_annotation_legend_labels(self):
        fig, ax = plt.subplots(figsize=(6, 4))

        render_violin(
            ax,
            [[1.0, 1.2, 0.8], [1.5, 1.7, 1.4]],
            ['A', 'B'],
            readability_scale=0.3,
        )
        move_legend_to_figure(ax)

        legend_labels = [text.get_text() for text in fig.legends[0].get_texts()]
        self.assertIn('Mean marker (μ)', legend_labels)
        self.assertIn('Min marker', legend_labels)
        self.assertIn('Max marker', legend_labels)
        self.assertIn('±3σ span (visual)', legend_labels)
        self.assertAlmostEqual(0.82, fig.subplotpars.top, places=2)
        plt.close(fig)


    def test_build_wrapped_chart_title_wraps_and_truncates(self):
        wrapped = build_wrapped_chart_title(
            'A very long violin summary title that should wrap cleanly across multiple lines without breaking words',
            width=30,
            max_lines=2,
        )

        lines = wrapped.split('\n')
        self.assertEqual(2, len(lines))
        self.assertTrue(lines[-1].endswith('…'))

    def test_add_iqr_boxplot_legend_uses_top_right_anchor(self):
        fig, ax = plt.subplots(figsize=(4, 3))

        add_iqr_boxplot_legend(ax)

        legend = ax.get_legend()
        self.assertIsNotNone(legend)
        self.assertEqual(2, legend._loc)
        bbox = legend.get_bbox_to_anchor()._bbox
        self.assertAlmostEqual(1.0, bbox.x0, places=2)
        self.assertAlmostEqual(1.0, bbox.y0, places=2)
        plt.close(fig)

    def test_add_violin_annotation_legend_uses_plot_edge_anchor(self):
        fig, ax = plt.subplots(figsize=(4, 3))

        add_violin_annotation_legend(ax, {'font_size': 7.0, 'show_minmax': True, 'show_sigma': True, 'sigma_line_width': 0.8})

        legend = ax.get_legend()
        self.assertIsNotNone(legend)
        self.assertEqual(2, legend._loc)
        bbox = legend.get_bbox_to_anchor()._bbox
        self.assertAlmostEqual(1.0, bbox.x0, places=2)
        self.assertAlmostEqual(1.0, bbox.y0, places=2)
        plt.close(fig)

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

    def test_style_histogram_stats_table_applies_nok_badge_for_low_severity(self):
        fig, ax = plt.subplots(figsize=(4, 3))
        table_data = [('Cp', 1.45), ('Cpk', 1.4), ('NOK %', '0.20%')]
        ax_table = ax.table(cellText=table_data, colLabels=['Statistic', 'Value'], cellLoc='center')

        capability_row_badges = {
            'Cp': {'label': 'Cp good', 'palette_key': 'quality_good'},
            'Cpk': {'label': 'Cpk good', 'palette_key': 'quality_good'},
            'NOK %': classify_nok_severity(0.002),
        }

        style_histogram_stats_table(
            ax_table,
            table_data,
            capability_badge={'label': 'Cp/Cpk good', 'palette_key': 'quality_good'},
            capability_row_badges=capability_row_badges,
        )

        self.assertEqual(
            ax_table.get_celld()[(3, 0)].get_facecolor(),
            matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE['quality_capable_bg']),
        )
        self.assertEqual(
            ax_table.get_celld()[(3, 1)].get_facecolor(),
            matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE['quality_capable_bg']),
        )
        plt.close(fig)

    def test_style_histogram_stats_table_applies_nok_badge_for_watch_severity(self):
        fig, ax = plt.subplots(figsize=(4, 3))
        table_data = [('Cp', 1.45), ('Cpk', 1.4), ('NOK %', '3.00%')]
        ax_table = ax.table(cellText=table_data, colLabels=['Statistic', 'Value'], cellLoc='center')

        capability_row_badges = {
            'Cp': {'label': 'Cp good', 'palette_key': 'quality_good'},
            'Cpk': {'label': 'Cpk good', 'palette_key': 'quality_good'},
            'NOK %': classify_nok_severity(0.03),
        }

        style_histogram_stats_table(
            ax_table,
            table_data,
            capability_badge={'label': 'Cp/Cpk good', 'palette_key': 'quality_good'},
            capability_row_badges=capability_row_badges,
        )

        self.assertEqual(
            ax_table.get_celld()[(3, 0)].get_facecolor(),
            matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE['quality_marginal_bg']),
        )
        self.assertEqual(
            ax_table.get_celld()[(3, 1)].get_facecolor(),
            matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE['quality_marginal_bg']),
        )
        plt.close(fig)

    def test_style_histogram_stats_table_applies_nok_badge_for_high_severity(self):
        fig, ax = plt.subplots(figsize=(4, 3))
        table_data = [('Cp', 1.45), ('Cpk', 1.4), ('NOK %', '8.00%')]
        ax_table = ax.table(cellText=table_data, colLabels=['Statistic', 'Value'], cellLoc='center')

        capability_row_badges = {
            'Cp': {'label': 'Cp good', 'palette_key': 'quality_good'},
            'Cpk': {'label': 'Cpk good', 'palette_key': 'quality_good'},
            'NOK %': classify_nok_severity(0.08),
        }

        style_histogram_stats_table(
            ax_table,
            table_data,
            capability_badge={'label': 'Cp/Cpk good', 'palette_key': 'quality_good'},
            capability_row_badges=capability_row_badges,
        )

        self.assertEqual(
            ax_table.get_celld()[(3, 0)].get_facecolor(),
            matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE['quality_risk_bg']),
        )
        self.assertEqual(
            ax_table.get_celld()[(3, 1)].get_facecolor(),
            matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE['quality_risk_bg']),
        )
        plt.close(fig)


    def test_build_measurement_block_plan_returns_expected_coordinates(self):
        plan = build_measurement_block_plan(base_col=6, sample_size=10)

        self.assertEqual(plan['data_header_row'], 20)
        self.assertEqual(plan['data_start_row'], 21)
        self.assertEqual(plan['last_data_row'], 30)
        self.assertEqual(plan['summary_column'], 7)
        self.assertEqual(plan['y_column'], 8)
        self.assertEqual(plan['data_range_y'], 'I22:I31')
        self.assertEqual(plan['usl_column'], 9)
        self.assertEqual(plan['lsl_column'], 10)

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
        self.assertEqual(series[1]['values'], '=REF_PART_A!$F22:F31')

        self.assertEqual(series[2]['name'], 'LSL')
        self.assertEqual(series[2]['values'], '=REF_PART_A!$F22:F31')

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
                'usl_x': '=REF_PART_A!$E22:E31',
                'usl_y': '=REF_PART_A!$F22:F31',
                'lsl_x': '=REF_PART_A!$E22:E31',
                'lsl_y': '=REF_PART_A!$F22:F31',
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

        self.assertEqual(bundle['data_columns'][3][0:3], (20, 9, 'USL'))
        self.assertEqual(list(bundle['data_columns'][3][3]), [10.5, 10.5])
        self.assertEqual(bundle['data_columns'][4][0:3], (20, 10, 'LSL'))
        self.assertEqual(list(bundle['data_columns'][4][3]), [9.8, 9.8])

    def test_build_measurement_chart_format_policy_returns_expected_defaults(self):
        policy = build_measurement_chart_format_policy('DIA - X')

        self.assertEqual(policy['title']['name'], 'DIA - X')
        self.assertEqual(policy['title']['name_font']['size'], 10)
        self.assertEqual(policy['y_axis']['major_gridlines']['visible'], False)
        self.assertEqual(policy['legend']['position'], 'none')
        self.assertEqual(policy['size'], {'width': 419, 'height': 240})

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




    def test_render_scatter_numeric_plots_points_without_categorical_dependency(self):
        fig, ax = plt.subplots()

        render_scatter_numeric(ax, [0, 2, 4], [1.0, 1.2, 0.9])

        self.assertEqual(len(ax.collections), 1)
        offsets = ax.collections[0].get_offsets()
        self.assertEqual(offsets[:, 0].tolist(), [0.0, 2.0, 4.0])
        self.assertEqual(offsets[:, 1].tolist(), [1.0, 1.2, 0.9])
        plt.close(fig)

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

    def test_shared_x_axis_label_strategy_force_sparse_thins_even_small_sets(self):
        fig, ax = plt.subplots()
        positions = list(range(12))
        labels = [f'L{idx}' for idx in positions]

        apply_shared_x_axis_label_strategy(
            ax,
            labels,
            positions=positions,
            force_sparse=True,
            target_tick_count=4,
        )

        rendered_labels = ax.get_xticklabels()
        self.assertLess(len(rendered_labels), len(labels))
        self.assertEqual(ax.get_xticks()[-1], 11)
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

    def test_annotate_violin_group_stats_two_sided_sigma_segment_spans_both_directions(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.set_xlim(-0.5, 0.5)

        values = [[1.0, 2.0, 3.0, 4.0]]
        style = annotate_violin_group_stats(ax, ['A'], values, annotation_mode='full', nom=1.0, lsl=0.5)

        sigma_collection = ax.collections[-1]
        segment = sigma_collection.get_segments()[0]
        y_start = float(segment[0][1])
        y_end = float(segment[1][1])
        mean_val = float(sum(values[0]) / len(values[0]))

        self.assertFalse(style['one_sided_sigma_mode'])
        self.assertLess(y_start, mean_val)
        self.assertGreater(y_end, mean_val)
        plt.close(fig)

    def test_annotate_violin_group_stats_one_sided_sigma_segment_starts_at_mean(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.set_xlim(-0.5, 0.5)

        values = [[1.0, 2.0, 3.0, 4.0]]
        style = annotate_violin_group_stats(ax, ['A'], values, annotation_mode='full', nom=0.0, lsl=0.0)

        sigma_collection = ax.collections[-1]
        segment = sigma_collection.get_segments()[0]
        y_start = float(segment[0][1])
        y_end = float(segment[1][1])
        mean_val = float(sum(values[0]) / len(values[0]))

        self.assertTrue(style['one_sided_sigma_mode'])
        self.assertAlmostEqual(y_start, mean_val, places=7)
        self.assertGreater(y_end, mean_val)
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
        plt.close(fig)

    def test_render_violin_uses_one_sided_sigma_legend_label_for_gdt_mode(self):
        fig, ax = plt.subplots(figsize=(6, 4))

        render_violin(
            ax,
            [[1.0, 1.2, 0.8], [1.5, 1.7, 1.4]],
            ['A', 'B'],
            nom=0.0,
            lsl=0.0,
            readability_scale=0.3,
        )

        legend = ax.get_legend()
        self.assertIsNotNone(legend)
        legend_labels = [text.get_text() for text in legend.get_texts()]
        self.assertIn('+3σ span (visual)', legend_labels)
        self.assertNotIn('±3σ span (visual)', legend_labels)
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


    def test_render_tolerance_band_adds_horizontal_patch(self):
        fig, ax = plt.subplots(figsize=(4, 3))

        band = render_tolerance_band(ax, nom=10.0, lsl=9.5, usl=10.5)

        self.assertIsNotNone(band)
        self.assertEqual(len(ax.patches), 1)
        self.assertEqual(matplotlib.colors.to_hex(band.get_facecolor()), matplotlib.colors.to_hex(SUMMARY_PLOT_PALETTE['sigma_band']))
        plt.close(fig)

    def test_render_tolerance_band_one_sided_vertical_starts_at_zero(self):
        fig, ax = plt.subplots(figsize=(4, 3))

        band = render_tolerance_band(ax, nom=0.0, lsl=0.0, usl=0.2, one_sided=True, orientation='vertical')

        xy = band.get_xy()
        if isinstance(xy, tuple):
            x_min = float(xy[0])
            x_max = float(xy[0] + band.get_width())
        else:
            x_values = [point[0] for point in xy]
            x_min = float(min(x_values))
            x_max = float(max(x_values))

        self.assertAlmostEqual(0.0, x_min, places=6)
        self.assertAlmostEqual(0.2, x_max, places=6)
        plt.close(fig)

    def test_render_spec_reference_lines_adds_lsl_usl_nominal(self):
        fig, ax = plt.subplots(figsize=(4, 3))

        render_spec_reference_lines(ax, nom=10.0, lsl=9.5, usl=10.5)

        labels = [line.get_label() for line in ax.lines]
        self.assertEqual(len(labels), 3)
        self.assertEqual(ax.lines[-1].get_linestyle(), '--')
        y_values = [line.get_ydata()[0] for line in ax.lines]
        self.assertEqual(y_values, [9.5, 10.5, 10.0])
        plt.close(fig)

    def test_render_spec_reference_lines_can_omit_nominal(self):
        fig, ax = plt.subplots(figsize=(4, 3))

        render_spec_reference_lines(ax, nom=10.0, lsl=9.5, usl=10.5, include_nominal=False)

        self.assertEqual(len(ax.lines), 2)
        y_values = [line.get_ydata()[0] for line in ax.lines]
        self.assertEqual(y_values, [9.5, 10.5])
        self.assertTrue(all(line.get_linestyle() == '-' for line in ax.lines))
        plt.close(fig)

    def test_build_tolerance_reference_legend_handles_contains_required_labels(self):
        labels = [handle.get_label() for handle in build_tolerance_reference_legend_handles()]

        self.assertEqual(labels, ['Tolerance band', 'LSL', 'USL', 'Nominal'])

    def test_violin_legend_excludes_tolerance_reference_labels(self):
        fig, ax = plt.subplots(figsize=(6, 4))

        render_violin(
            ax,
            [[1.0, 1.2, 0.8], [1.5, 1.7, 1.4]],
            ['A', 'B'],
            nom=1.2,
            lsl=0.9,
            usl=1.8,
            readability_scale=0.3,
        )
        move_legend_to_figure(ax)

        legend_labels = [text.get_text() for text in fig.legends[0].get_texts()]
        self.assertNotIn('Tolerance band', legend_labels)
        self.assertNotIn('LSL', legend_labels)
        self.assertNotIn('USL', legend_labels)
        self.assertNotIn('Nominal', legend_labels)
        plt.close(fig)

    def test_iqr_legend_excludes_tolerance_reference_labels(self):
        fig, ax = plt.subplots(figsize=(6, 4))

        render_iqr_boxplot(ax, [[1.0, 1.1, 1.2], [2.0, 2.1, 3.5]], ['G1', 'G2'])
        add_iqr_boxplot_legend(ax, include_tolerance_refs=False)
        move_legend_to_figure(ax)

        legend_labels = [text.get_text() for text in fig.legends[0].get_texts()]
        self.assertNotIn('Tolerance band', legend_labels)
        self.assertNotIn('LSL', legend_labels)
        self.assertNotIn('USL', legend_labels)
        self.assertNotIn('Nominal', legend_labels)
        plt.close(fig)

    def test_histogram_legend_can_include_tolerance_reference_labels(self):
        fig, ax = plt.subplots(figsize=(6, 4))

        mean_style = build_histogram_mean_line_style()
        ax.legend(handles=[matplotlib.lines.Line2D([0], [0], **mean_style, label='Mean'), *build_tolerance_reference_legend_handles()])
        move_legend_to_figure(ax)

        legend_labels = [text.get_text() for text in fig.legends[0].get_texts()]
        self.assertIn('Tolerance band', legend_labels)
        self.assertIn('LSL', legend_labels)
        self.assertIn('USL', legend_labels)
        self.assertIn('Nominal', legend_labels)
        plt.close(fig)


if __name__ == '__main__':
    unittest.main()

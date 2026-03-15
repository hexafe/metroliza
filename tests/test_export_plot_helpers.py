import sys
import types
import unittest
from unittest import mock

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from modules.export_histogram_layout import (
    HISTOGRAM_OUTER_PADDING_TOP,
    assert_non_overlapping_rectangles,
)

from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE, EMPHASIS_TABLE_ROWS
from modules.export_summary_utils import (
    compute_normality_status,
    resolve_density_curve_sampling,
    resolve_histogram_bin_count,
)


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

custom_logger_stub = types.ModuleType('modules.custom_logger')


class _DummyLogger:
    def __init__(self, *args, **kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyLogger
sys.modules['modules.custom_logger'] = custom_logger_stub

from modules.export_data_thread import (  # noqa: E402
    ExportDataThread,
    build_histogram_annotation_specs,
    build_histogram_mean_line_style,
    compute_histogram_annotation_rows,
    compute_histogram_font_sizes,
    compute_histogram_panel_layout,
    compute_histogram_plot_with_right_info_layout,
    compute_histogram_table_layout,
    render_histogram_annotations,
    render_histogram_title,
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
    build_histogram_table_render_data,
    style_histogram_stats_table,
    adjust_histogram_stats_table_geometry,
    classify_normality_status,
    resolve_violin_annotation_style,
    annotate_violin_group_stats,
    render_violin,
    render_scatter_numeric,
    render_histogram,
    render_density_line,
    render_panel_table,
    render_panel_table_in_panel_axes,
    render_histogram_note_panel,
    resolve_summary_annotation_strategy,
    apply_summary_plot_theme,
    apply_minimal_axis_style,
    _build_distribution_fit_info_note,
    _build_distribution_fit_table_rows,
    _apply_non_normal_cpk_reference_label,
    _build_compact_histogram_note_lines,
    resolve_selected_model_curve_style,
    resolve_histogram_x_view,
)


class TestExportPlotHelpers(unittest.TestCase):

    def test_render_panel_table_applies_alignment_rules(self):
        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            meta = render_panel_table(
                ax=ax,
                fig=fig,
                title='Statistic',
                rows=[('Average', '10.23'), ('Std dev', '0.42')],
                rect={'x': 0.05, 'y': 0.05, 'width': 0.45, 'height': 0.5},
                style_options={'fontsize': 8.0},
            )

            self.assertFalse(meta['overflow'])
            table = meta['table']
            self.assertEqual(table.get_celld()[(1, 0)].get_text().get_ha(), 'left')
            self.assertEqual(table.get_celld()[(1, 1)].get_text().get_ha(), 'right')
        finally:
            plt.close(fig)

    def test_render_panel_table_fallback_chain_defers_low_priority_rows_before_overlap(self):
        fig, ax = plt.subplots(figsize=(3.0, 2.2))
        try:
            rows = [
                ('Critical A', '123.45'),
                ('Critical B', '123.45'),
                ('Optional Long Row 1', '123.45'),
                ('Optional Long Row 2', '123.45'),
                ('Optional Long Row 3', '123.45'),
            ]
            meta = render_panel_table(
                ax=ax,
                fig=fig,
                title='Very Long Header Title',
                rows=rows,
                rect={'x': 0.05, 'y': 0.05, 'width': 0.42, 'height': 0.20},
                style_options={
                    'fontsize': 9.0,
                    'min_fontsize': 6.6,
                    'compact_label_mapping': {'Optional Long Row 1': 'Opt 1', 'Optional Long Row 2': 'Opt 2', 'Optional Long Row 3': 'Opt 3'},
                    'low_priority_labels': {'Optional Long Row 1', 'Optional Long Row 2', 'Optional Long Row 3'},
                },
            )

            self.assertTrue(meta['overflow'])
            self.assertTrue(meta['deferred_rows'])
            self.assertIn('reduced_fontsize', meta['fallbacks_applied'])
            self.assertIn('defer_low_priority_rows', meta['fallbacks_applied'])
        finally:
            plt.close(fig)

    def test_render_panel_table_compacts_long_labels_before_deferred_row_reduction(self):
        fig, ax = plt.subplots(figsize=(3.3, 2.3))
        try:
            rows = [
                ('Estimated NOK (PPM)', '12,345'),
                ('Model fit quality', 'Medium'),
                ('Goodness of fit p-value', '0.0421'),
            ]
            meta = render_panel_table(
                ax=ax,
                fig=fig,
                title='Distribution fit summary',
                rows=rows,
                rect={'x': 0.05, 'y': 0.05, 'width': 0.42, 'height': 0.15},
                style_options={
                    'fontsize': 8.8,
                    'min_fontsize': 6.4,
                    'compact_label_mapping': {
                        'Estimated NOK (PPM)': 'Est. PPM',
                        'Model fit quality': 'Fit qual.',
                        'Goodness of fit p-value': 'GOF p',
                    },
                    'low_priority_labels': set(),
                },
            )

            self.assertTrue(meta['used_compact_labels'])
            self.assertIn('compact_label_mapping', meta['fallbacks_applied'])
            rendered_labels = [label for label, _ in meta['rendered_rows']]
            self.assertIn('Est. PPM', rendered_labels)
            self.assertNotIn('Estimated NOK (PPM)', rendered_labels)
            self.assertTrue(meta['overflow'])
        finally:
            plt.close(fig)

    def test_render_histogram_note_panel_switches_to_compact_variant_for_long_context_text(self):
        fig, ax = plt.subplots(figsize=(3.0, 2.2))
        try:
            note_items = [
                {
                    'label': 'Candidate family',
                    'compact_label': 'Family',
                    'value': 'Positive-support one-sided family with extended context text for validation',
                    'compact_value': 'One-sided +',
                    'priority': 90,
                },
                {
                    'label': 'Model',
                    'compact_label': 'Model',
                    'value': 'Gamma (3-parameter, constrained support)',
                    'compact_value': 'Gamma',
                    'priority': 80,
                },
                {
                    'label': 'Context',
                    'compact_label': 'Context',
                    'value': 'Deferred row: Estimated NOK (PPM) with additional explanatory narrative text.',
                    'compact_value': 'Deferred rows present',
                    'priority': 20,
                    'expanded_only': True,
                },
            ]

            meta = render_histogram_note_panel(
                ax=ax,
                note_items=note_items,
                style_options={'fontsize': 7.2, 'min_fontsize': 6.2, 'max_fontsize': 8.8},
                available_height_px=10.0,
            )

            self.assertEqual(meta['variant'], 'compact')
            rendered_text = '\n'.join(meta['rendered_lines'])
            self.assertIn('Family: One-sided +', rendered_text)
            self.assertNotIn('Context:', rendered_text)
            self.assertNotIn('extended context text for validation', rendered_text)
            self.assertIn('text_artist', meta)
            self.assertFalse(hasattr(meta.get('text_artist'), 'get_celld'))
        finally:
            plt.close(fig)

    def test_render_panel_table_in_panel_axes_uses_content_height_bounds(self):
        fig = plt.figure(figsize=(4.0, 3.0))
        panel_ax = fig.add_axes([0.1, 0.1, 0.35, 0.6])
        try:
            meta = render_panel_table_in_panel_axes(
                ax=panel_ax,
                title='Statistic',
                rows=[('A', '1'), ('B', '2')],
                style_options={'fontsize': 8.0},
            )

            self.assertEqual(meta['used_bounds']['x'], 0.0)
            self.assertEqual(meta['used_bounds']['width'], 1.0)
            self.assertLess(meta['used_bounds']['height'], 1.0)
            self.assertGreater(meta['used_bounds']['y'], 0.0)
            self.assertEqual(len(meta['rendered_rows']), 2)
        finally:
            plt.close(fig)

    def test_histogram_panel_layout_rendering_smoke_with_dedicated_axes(self):
        fig = plt.figure(figsize=(8.4, 4.0))
        try:
            measurements = pd.DataFrame(
                {'MEAS': np.concatenate([np.linspace(9.8, 10.2, 40), np.linspace(10.25, 10.5, 16)])}
            )
            fit_rows = [
                ('Model', 'Johnson SU'),
                ('GOF p', '0.0712'),
                ('P(<LSL)', '0.011%'),
                ('P(>USL)', '0.108%'),
                ('Est. NOK %', '0.123%'),
                ('Est. PPM', '1,230'),
                ('Model fit quality', 'Medium'),
            ]
            stats_rows = [
                ('Average', '10.102'),
                ('Std dev', '0.085'),
                ('Cp', '1.34'),
                ('Cpk (normal ref)', '1.19'),
            ]
            rects = compute_histogram_plot_with_right_info_layout(
                (8.4, 4.0),
                table_fontsize=8.8,
                fit_row_count=len(fit_rows),
                stats_row_count=len(stats_rows),
                note_line_count=0,
                right_container_width_hint=0.34,
            )
            assert_non_overlapping_rectangles({
                'plot_rect': rects['plot_rect'],
                'fit_table_rect': rects['fit_table_rect'],
                'stats_table_rect': rects['stats_table_rect'],
                'footer_rect': rects['footer_rect'],
            })

            fit_ax = fig.add_axes([rects['fit_table_rect']['x'], rects['fit_table_rect']['y'], rects['fit_table_rect']['width'], rects['fit_table_rect']['height']])
            plot_ax = fig.add_axes([rects['plot_rect']['x'], rects['plot_rect']['y'], rects['plot_rect']['width'], rects['plot_rect']['height']])
            stats_ax = fig.add_axes([rects['stats_table_rect']['x'], rects['stats_table_rect']['y'], rects['stats_table_rect']['width'], rects['stats_table_rect']['height']])
            fit_ax.set_axis_off()
            stats_ax.set_axis_off()

            render_histogram(plot_ax, measurements, lsl=9.9, usl=10.4)
            fit_meta = render_panel_table_in_panel_axes(ax=fit_ax, title='Distribution Fit', rows=fit_rows, style_options={'fontsize': 8.2})
            stats_meta = render_panel_table_in_panel_axes(ax=stats_ax, title='Statistics', rows=stats_rows, style_options={'fontsize': 8.2})
            self.assertEqual(len(fig.axes), 3)
            self.assertGreater(rects['plot_rect']['width'], rects['fit_table_rect']['width'])
            self.assertEqual(rects['footer_rect']['height'], 0.0)
            self.assertGreaterEqual(len(fit_meta['rendered_rows']), 1)
            self.assertGreaterEqual(len(stats_meta['rendered_rows']), 1)
        finally:
            plt.close(fig)


    def test_distribution_fit_table_rows_include_expected_payload_and_ordering_for_bilateral_specs(self):
        rows = _build_distribution_fit_table_rows(
            {
                'selected_model': {'display_name': 'Weibull (Min)'},
                'gof_metrics': {'ad_pvalue': 0.07342},
                'fit_quality': {'label': 'medium'},
                'risk_estimates': {
                    'spec_type': 'bilateral',
                    'below_lsl_probability': 0.0012,
                    'above_usl_probability': 0.0023,
                    'nok_percent': 0.1234,
                    'ppm_nok': 1234.0,
                },
            },
            lsl=9.5,
            usl=10.5,
        )

        self.assertEqual([label for label, _ in rows], [
            'Model',
            'GOF p',
            'P(<LSL)',
            'P(>USL)',
            'Est. NOK %',
            'Est. PPM',
            'Fit quality',
            'Capability',
            'Family',
        ])
        self.assertEqual(rows[0][1], 'Weibull (Min)')
        self.assertEqual(rows[1][1], '0.073')
        self.assertEqual(rows[2][1], '0.120%')
        self.assertEqual(rows[3][1], '0.230%')
        self.assertEqual(rows[4][1], '0.123%')
        self.assertEqual(rows[5][1], '1,234')
        self.assertEqual(rows[6][1], 'Medium')
        self.assertEqual(rows[7][1], 'Risk')
        self.assertEqual(rows[8][1], 'unknown')

    def test_distribution_fit_table_rows_follow_upper_only_contract(self):
        rows = _build_distribution_fit_table_rows(
            {
                'risk_estimates': {
                    'spec_type': 'upper_only',
                    'above_usl_probability': 0.01234,
                    'nok_percent': 1.234,
                    'ppm_nok': 12340.0,
                },
            },
            lsl=None,
            usl=10.0,
        )

        self.assertEqual([label for label, _ in rows], ['Model', 'GOF p', 'P(>USL)', 'Est. NOK %', 'Est. PPM', 'Fit quality', 'Capability', 'Family'])

    def test_distribution_fit_table_rows_follow_lower_only_contract(self):
        rows = _build_distribution_fit_table_rows(
            {
                'risk_estimates': {
                    'spec_type': 'lower_only',
                    'below_lsl_probability': 0.0456,
                    'nok_percent': 4.56,
                    'ppm_nok': 45600.0,
                },
            },
            lsl=2.0,
            usl=None,
        )

        self.assertEqual([label for label, _ in rows], ['Model', 'GOF p', 'P(<LSL)', 'Est. NOK %', 'Est. PPM', 'Fit quality', 'Capability', 'Family'])

    def test_distribution_fit_table_rows_omit_zero_bound_lower_tail_for_positive_support(self):
        rows = _build_distribution_fit_table_rows(
            {
                'inferred_support_mode': 'one_sided_zero_bound_positive',
                'risk_estimates': {
                    'spec_type': 'lower_only',
                    'below_lsl_probability': 0.0,
                    'nok_percent': 0.0,
                    'ppm_nok': 0.0,
                },
            },
            lsl=0.0,
            usl=None,
        )

        self.assertNotIn('P(<LSL)', [label for label, _ in rows])

    def test_distribution_fit_table_rows_fallback_to_na_when_fit_unreliable(self):
        rows = _build_distribution_fit_table_rows(
            {
                'fit_quality': {'label': 'unreliable'},
                'risk_estimates': {
                    'nok_percent': None,
                    'ppm_nok': None,
                },
            }
        )

        self.assertEqual(rows[0], ('Model', 'N/A'))
        self.assertEqual(rows[1], ('GOF p', 'N/A'))
        self.assertEqual(rows[2], ('Est. NOK %', 'N/A'))
        self.assertEqual(rows[3], ('Est. PPM', 'N/A'))
        self.assertEqual(rows[4], ('Fit quality', 'Unreliable'))
        self.assertEqual(rows[5], ('Capability', 'N/A'))
        self.assertEqual(rows[6], ('Family', 'unknown'))
        self.assertEqual(rows[7], ('Warning', 'fit unreliable'))

    def test_left_and_right_panel_tables_share_fontsize_and_row_height_policy(self):
        fig = plt.figure(figsize=(6.2, 4.0))
        try:
            left_ax = fig.add_axes([0.05, 0.08, 0.24, 0.84])
            right_ax = fig.add_axes([0.72, 0.28, 0.22, 0.64])
            left_ax.set_axis_off()
            right_ax.set_axis_off()

            left_meta = render_panel_table_in_panel_axes(
                ax=left_ax,
                title='Distribution Fit',
                rows=[('Model', 'Johnson SU'), ('GOF p', '0.0712'), ('Est. NOK %', '0.123%'), ('Est. PPM', '1,230'), ('Model fit quality', 'Medium')],
                style_options={'fontsize': 8.3},
                row_height=0.060,
                pad_y=0.02,
            )
            right_meta = render_panel_table_in_panel_axes(
                ax=right_ax,
                title='Statistic',
                rows=[('Average', '10.10'), ('Std dev', '0.08'), ('Cp', '1.33'), ('Cpk', '1.22')],
                style_options={'fontsize': 8.3},
                row_height=0.060,
                pad_y=0.02,
            )

            self.assertEqual(left_meta['font_size'], right_meta['font_size'])
            left_cells = left_meta['table'].get_celld()
            right_cells = right_meta['table'].get_celld()
            self.assertAlmostEqual(left_cells[(1, 0)].get_height(), right_cells[(1, 0)].get_height(), delta=0.03)
            self.assertLess(left_meta['used_bounds']['height'], 1.0)
        finally:
            plt.close(fig)

    def test_distribution_fit_table_value_column_wraps_long_model_without_overlap(self):
        fig = plt.figure(figsize=(4.8, 3.2))
        try:
            ax = fig.add_axes([0.05, 0.08, 0.9, 0.84])
            ax.set_axis_off()
            meta = render_panel_table_in_panel_axes(
                ax=ax,
                title='Distribution Fit',
                rows=[('Model', 'Johnson SU Extended Variant Name'), ('Est. PPM', '123,456,789')],
                style_options={'fontsize': 8.3, 'value_wrap_width': 12, 'min_label_fraction': 0.42, 'min_value_fraction': 0.44},
                row_height=0.074,
                pad_y=0.02,
            )

            rendered = dict(meta['rendered_rows'])
            self.assertIn('\n', rendered['Model'])
            self.assertFalse(meta['overflow'])
        finally:
            plt.close(fig)

    def test_histogram_export_ticks_and_xaxis_label_remain_inside_figure_bounds(self):
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        try:
            values = pd.DataFrame({'MEAS': np.linspace(9.8, 10.5, 40)})
            render_histogram(ax, values, lsl=9.9, usl=10.4)
            ax.set_xlabel('Measurement')
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            fig_bbox = fig.bbox

            for text in [*ax.get_xticklabels(), ax.xaxis.label]:
                if not text.get_text():
                    continue
                bbox = text.get_window_extent(renderer=renderer)
                self.assertGreaterEqual(bbox.y0, fig_bbox.y0 - 0.5)
                self.assertLessEqual(bbox.y1, fig_bbox.y1 + 0.5)
        finally:
            plt.close(fig)

    def test_distribution_fit_note_panel_avoids_model_and_fit_quality_duplication(self):
        note_items, _poor_fit = _build_distribution_fit_info_note(
            {
                'inferred_support_mode': 'signed',
                'selected_model': {'display_name': 'Johnson SU'},
                'fit_quality': {'label': 'medium'},
            },
            summary_stats={'normality_text': 'Shapiro non-normal'},
        )
        labels = [item.get('label') for item in note_items]
        self.assertNotIn('Model', labels)
        self.assertNotIn('Fit quality', labels)
        self.assertIn('Spec handling', labels)
        self.assertIn('Family (debug)', labels)

    def test_histogram_annotation_rendering_keeps_mean_and_spec_labels_without_tail_probability_text(self):
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        try:
            values = pd.DataFrame({'MEAS': np.linspace(9.7, 10.5, 60)})
            render_histogram(ax, values, lsl=9.9, usl=10.3)

            annotation_specs = build_histogram_annotation_specs(average=10.1, usl=10.3, lsl=9.9, y_max=1.0)
            annotation_specs, _ = compute_histogram_annotation_rows(
                annotation_specs,
                distance_threshold=0.04,
                threshold_mode='axis_fraction',
                x_span=0.8,
                base_text_y_axes=1.01,
                row_step=0.025,
            )
            render_histogram_annotations(
                ax,
                annotation_specs,
                annotation_fontsize=8.2,
                annotation_box={'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': '#cccccc', 'alpha': 0.94},
            )

            rendered_texts = [text.get_text() for text in ax.texts]
            self.assertTrue(any(text.startswith('Mean =') for text in rendered_texts))
            self.assertTrue(any(text.startswith('USL=') for text in rendered_texts))
            self.assertTrue(any(text.startswith('LSL=') for text in rendered_texts))
            self.assertFalse(any('P(X < LSL)' in text for text in rendered_texts))
            self.assertFalse(any('P(X > USL)' in text for text in rendered_texts))
        finally:
            plt.close(fig)

    def test_apply_summary_plot_theme_sets_lighter_grid_alpha_and_linewidth(self):
        apply_summary_plot_theme()

        self.assertEqual(plt.rcParams['grid.color'], SUMMARY_PLOT_PALETTE['grid'])
        self.assertAlmostEqual(float(plt.rcParams['grid.alpha']), 0.4)
        self.assertAlmostEqual(float(plt.rcParams['grid.linewidth']), 0.5)

    def test_histogram_axis_style_uses_subtle_y_grid_policy(self):
        import pandas as pd

        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            render_histogram(ax, pd.DataFrame({'MEAS': [1.0, 1.5, 2.0, 2.5, 3.0]}))
            apply_minimal_axis_style(ax, grid_axis='y')

            y_gridlines = ax.get_ygridlines()
            x_gridlines = ax.get_xgridlines()
            self.assertTrue(any(line.get_visible() for line in y_gridlines))
            self.assertFalse(any(line.get_visible() for line in x_gridlines))

            first_visible = next(line for line in y_gridlines if line.get_visible())
            self.assertEqual(first_visible.get_linestyle(), '-')
            self.assertAlmostEqual(float(first_visible.get_alpha()), 0.4)
            self.assertAlmostEqual(float(first_visible.get_linewidth()), 0.5)
            self.assertEqual(first_visible.get_color(), SUMMARY_PLOT_PALETTE['grid'])
        finally:
            plt.close(fig)


    def test_histogram_y_axis_tracks_bar_counts_not_overlay_curve(self):
        import pandas as pd

        values = [1.0] * 14 + [1.25] * 12 + [1.5] * 10 + [1.75] * 8 + [2.0] * 6

        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            render_histogram(ax, pd.DataFrame({'MEAS': values}))
            bar_ylim_before_overlay = ax.get_ylim()

            x_values = np.linspace(min(values), max(values), 50)
            exaggerated_curve = np.linspace(80.0, 120.0, 50)
            render_density_line(ax, x_values, exaggerated_curve)

            bar_ylim_after_overlay = ax.get_ylim()
            self.assertEqual(bar_ylim_after_overlay, bar_ylim_before_overlay)

            max_bar_height = max((patch.get_height() for patch in ax.patches), default=0.0)
            self.assertGreater(max_bar_height, 0.0)
            self.assertGreaterEqual(bar_ylim_after_overlay[1], max_bar_height)
            self.assertLessEqual(bar_ylim_after_overlay[1], max_bar_height * 1.2)
        finally:
            plt.close(fig)

    def test_render_density_line_uses_hidden_secondary_y_axis(self):
        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            x_values = np.linspace(0.0, 1.0, 20)
            density_values = np.linspace(0.2, 2.0, 20)

            render_density_line(ax, x_values, density_values)

            self.assertEqual(len(fig.axes), 2)
            secondary_axis = fig.axes[1]
            self.assertFalse(secondary_axis.yaxis.get_visible())
            self.assertEqual(list(secondary_axis.get_yticks()), [])
            self.assertFalse(secondary_axis.spines['right'].get_visible())
            self.assertEqual(len(secondary_axis.lines), 1)
        finally:
            plt.close(fig)

    def test_render_density_line_reuses_secondary_axis_for_multiple_overlays(self):
        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            x_values = np.linspace(0.0, 1.0, 20)
            density_values = np.linspace(0.2, 2.0, 20)

            render_density_line(ax, x_values, density_values)
            render_density_line(ax, x_values, density_values * 0.8, linestyle='--', alpha=0.3)

            self.assertEqual(len(fig.axes), 2)
            secondary_axis = fig.axes[1]
            self.assertEqual(len(secondary_axis.lines), 2)
        finally:
            plt.close(fig)

    def test_render_violin_draws_horizontal_spec_reference_lines(self):
        values = [[-1.89, -1.88, -1.90], [-1.87, -1.86, -1.88]]
        labels = ['A', 'B']

        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            render_violin(ax, values, labels, lsl=-1.90, usl=-1.82)

            horizontal_candidates = []
            vertical_candidates = []
            for line in ax.lines:
                x_data = np.asarray(line.get_xdata(), dtype=float)
                y_data = np.asarray(line.get_ydata(), dtype=float)
                if x_data.size < 2 or y_data.size < 2:
                    continue
                if np.allclose(y_data, y_data[0], atol=1e-9):
                    horizontal_candidates.append(line)
                if np.allclose(x_data, x_data[0], atol=1e-9):
                    vertical_candidates.append(line)

            self.assertGreaterEqual(len(horizontal_candidates), 2)
            self.assertEqual(len(vertical_candidates), 0)
        finally:
            plt.close(fig)

    def test_render_histogram_ignores_grouped_mode_for_summary_histograms(self):
        histogram_frame = pd.DataFrame(
            {
                'GROUP': ['A'] * 8 + ['B'] * 6,
                'MEAS': [1.01, 1.02, 1.03, 1.04, 1.02, 1.01, 1.05, 1.03, 1.08, 1.09, 1.07, 1.08, 1.10, 1.09],
            }
        )

        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            meta = render_histogram(ax, histogram_frame, group_column='GROUP')

            self.assertFalse(meta['is_grouped'])
            self.assertEqual(meta['group_labels'], [])
            self.assertEqual(len(fig.axes), 1)
            self.assertIsNone(ax.get_legend())
        finally:
            plt.close(fig)

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
        by_kind = {item['kind']: item for item in annotations}

        self.assertEqual(len(annotations), 3)
        self.assertEqual(annotations[0]['text'], 'Mean = 10.123')
        self.assertEqual(annotations[0]['x'], 10.1234)
        self.assertEqual(annotations[1]['text'], 'USL=10.600')
        self.assertEqual(annotations[1]['ha'], 'center')
        self.assertEqual(annotations[2]['text'], 'LSL=9.800')
        self.assertEqual(annotations[2]['ha'], 'center')
        self.assertEqual(by_kind['mean']['preferred_slot'], 'mean_primary')
        self.assertEqual(by_kind['usl']['preferred_slot'], 'spec_primary')
        self.assertEqual(by_kind['lsl']['preferred_slot'], 'spec_secondary')

    def test_compute_histogram_annotation_rows_top_band_slots_keep_mean_above_specs(self):
        annotation_specs = build_histogram_annotation_specs(average=10.2, usl=10.5, lsl=9.8, y_max=1.0)

        resolved, _ = compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.04,
            threshold_mode='axis_fraction',
            x_span=1.0,
            base_text_y_axes=1.01,
            row_step=0.025,
        )
        by_kind = {item['kind']: item for item in resolved}

        self.assertGreater(by_kind['mean']['text_y_axes'], by_kind['usl']['text_y_axes'])
        self.assertGreater(by_kind['mean']['text_y_axes'], by_kind['lsl']['text_y_axes'])

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
        self.assertEqual(len(payload['x']), 40)
        self.assertEqual(len(payload['y']), 40)

    def test_build_histogram_density_curve_payload_returns_none_for_constant_data(self):
        payload = build_histogram_density_curve_payload([3.0, 3.0, 3.0])

        self.assertIsNone(payload)

    def test_render_histogram_sets_xlim_beyond_variable_data_min_max(self):
        fig, ax = plt.subplots()
        values = [10.0, 12.5, 15.0, 20.0]

        render_histogram(ax, {'MEAS': values})

        x_min, x_max = ax.get_xlim()
        self.assertLess(x_min, min(values))
        self.assertGreater(x_max, max(values))
        plt.close(fig)

    def test_render_histogram_sets_deterministic_xlim_padding_for_zero_range_data(self):
        fig, ax = plt.subplots()
        values = [7.0, 7.0, 7.0]

        render_histogram(ax, {'MEAS': values})

        x_min, x_max = ax.get_xlim()
        self.assertLess(x_min, 7.0)
        self.assertGreater(x_max, 7.0)
        self.assertGreater(x_max - x_min, 0.07)
        self.assertLess(x_max - x_min, 0.09)
        plt.close(fig)

    def test_render_histogram_xlim_includes_spec_limits_with_margin(self):
        fig, ax = plt.subplots()
        values = [8.274, 8.28, 8.288]
        lsl = 8.15
        usl = 8.23

        render_histogram(ax, {'MEAS': values}, lsl=lsl, usl=usl)

        x_min, x_max = ax.get_xlim()
        self.assertLess(x_min, lsl)
        self.assertGreater(x_max, max(values))
        self.assertGreater(x_max, usl)
        plt.close(fig)

    def test_resolve_histogram_x_view_restores_spec_aware_full_range_with_10_percent_margin(self):
        values = [10.0000, 10.0006, 10.0012, 10.0016]

        resolved = resolve_histogram_x_view(values, lsl=9.95, usl=10.05)

        raw_span = 10.05 - 9.95
        min_span = 10.05 * 0.01
        span = max(raw_span, min_span)
        margin = span * 0.10
        center = (9.95 + 10.05) / 2.0
        self.assertEqual(resolved['mode'], 'full')
        self.assertAlmostEqual(resolved['x_min'], center - (span / 2.0) - margin)
        self.assertAlmostEqual(resolved['x_max'], center + (span / 2.0) + margin)

    def test_resolve_histogram_x_view_uses_full_mode_for_regular_spread(self):
        values = [8.2, 9.0, 9.7, 10.2]

        resolved = resolve_histogram_x_view(values, lsl=8.0, usl=10.5)

        self.assertEqual(resolved['mode'], 'full')
        self.assertLess(resolved['x_min'], 8.0)
        self.assertGreater(resolved['x_max'], 10.5)

    def test_resolve_histogram_x_view_uses_min_span_guard_for_ultra_narrow_data_without_specs(self):
        values = [10.0, 10.0 + 1e-9]

        resolved = resolve_histogram_x_view(values)

        self.assertEqual(resolved['mode'], 'full')
        self.assertGreater(resolved['x_max'] - resolved['x_min'], 0.09)
        self.assertLess(resolved['x_max'] - resolved['x_min'], 0.2)

    def test_render_histogram_ignores_invalid_spec_limits(self):
        fig, ax = plt.subplots()
        values = [1.0, 2.0, 3.0]

        render_histogram(ax, {'MEAS': values}, lsl=float('nan'), usl='bad')

        x_min, x_max = ax.get_xlim()
        self.assertLess(x_min, min(values))
        self.assertGreater(x_max, max(values))
        plt.close(fig)


    def test_adjust_histogram_stats_table_geometry_scales_rows_and_uses_three_column_width_contract(self):
        fig, ax = plt.subplots()
        render_data = build_histogram_table_render_data([('Min', '1.0'), ('Max', '2.0')], three_column=True)
        ax_table = plt.table(
            cellText=render_data,
            colLabels=['Statistic', ' ', 'Value'],
            cellLoc='center',
            loc='right',
            bbox=[1, 0, 0.3, 1],
        )

        base_value_width = ax_table.get_celld()[(1, 2)].get_width()
        base_height = ax_table.get_celld()[(1, 0)].get_height()

        style_histogram_stats_table(ax_table, render_data)
        adjust_histogram_stats_table_geometry(
            ax_table,
            statistic_col_width_ratio=0.56,
            row_height_scale=1.15,
        )
        fig.canvas.draw()

        header_w0 = ax_table.get_celld()[(0, 0)].get_width()
        header_w1 = ax_table.get_celld()[(0, 1)].get_width()
        header_w2 = ax_table.get_celld()[(0, 2)].get_width()
        header_total = header_w0 + header_w1 + header_w2
        self.assertAlmostEqual(header_w0 / header_total, 0.4368, places=3)
        self.assertAlmostEqual(header_w1 / header_total, 0.1232, places=3)
        self.assertAlmostEqual(header_w2 / header_total, 0.44, places=3)
        self.assertTrue(ax_table.get_celld()[(1, 1)].get_visible())
        self.assertGreater(ax_table.get_celld()[(1, 0)].get_height(), base_height)
        self.assertLess(ax_table.get_celld()[(1, 2)].get_width(), base_value_width)
        self.assertEqual(
            ax_table.get_celld()[(0, 0)].get_facecolor(),
            matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE['table_header_bg']),
        )
        self.assertEqual(ax_table.get_celld()[(1, 2)].get_text().get_ha(), 'right')

        edge_color = matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE['annotation_box_edge'])
        self.assertEqual(ax_table.get_celld()[(1, 0)].get_edgecolor(), edge_color)
        self.assertEqual(ax_table.get_celld()[(1, 2)].get_edgecolor(), edge_color)
        self.assertAlmostEqual(ax_table.get_celld()[(1, 0)].get_linewidth(), 0.45)
        self.assertAlmostEqual(ax_table.get_celld()[(1, 2)].get_linewidth(), 0.45)
        self.assertGreater(ax_table.get_celld()[(1, 0)].PAD, 0.08)
        self.assertGreater(ax_table.get_celld()[(1, 2)].PAD, 0.08)

        plt.close(fig)

    def test_adjust_histogram_stats_table_geometry_keeps_two_column_rows_unmerged(self):
        fig, ax = plt.subplots()
        table_rows = [('Min', '1.0'), ('Max', '2.0')]
        ax_table = plt.table(
            cellText=table_rows,
            colLabels=['Statistic', 'Value'],
            cellLoc='center',
            loc='right',
            bbox=[1, 0, 0.3, 1],
        )

        adjust_histogram_stats_table_geometry(
            ax_table,
            row_height_scale=1.1,
        )
        fig.canvas.draw()

        last_row_index = len(table_rows)
        left = ax_table.get_celld()[(last_row_index, 0)]
        right = ax_table.get_celld()[(last_row_index, 1)]

        self.assertTrue(right.get_visible())
        self.assertEqual(left.get_text().get_text(), 'Max')
        self.assertEqual(right.get_text().get_text(), '2.0')
        plt.close(fig)

    def test_adjust_histogram_stats_table_geometry_two_column_keeps_rows_unmerged_when_normality_missing(self):
        fig, ax = plt.subplots()
        table_rows = [('Min', '1.0'), ('Max', '2.0')]
        ax_table = plt.table(
            cellText=table_rows,
            colLabels=['Statistic', 'Value'],
            cellLoc='center',
            loc='right',
            bbox=[1, 0, 0.3, 1],
        )

        final_row_index = len(table_rows)
        adjust_histogram_stats_table_geometry(ax_table)
        fig.canvas.draw()

        left = ax_table.get_celld()[(final_row_index, 0)]
        right = ax_table.get_celld()[(final_row_index, 1)]

        self.assertTrue(right.get_visible())
        self.assertEqual(left.get_text().get_text(), 'Max')
        self.assertEqual(right.get_text().get_text(), '2.0')
        plt.close(fig)

    def test_build_histogram_density_curve_payload_accepts_numeric_string_measurements(self):
        payload = build_histogram_density_curve_payload(['1.0', '1.5', '2.0', '2.5'])

        self.assertIsNotNone(payload)
        self.assertEqual(len(payload['x']), 40)
        self.assertEqual(len(payload['y']), 40)

    def test_build_histogram_density_curve_payload_supports_kde_mode(self):
        payload = build_histogram_density_curve_payload([0.0, 0.0, 0.1, 0.2, 0.4, 3.0, 7.0], mode='kde')

        self.assertIsNotNone(payload)
        self.assertEqual(len(payload['x']), 40)

    def test_classify_normality_status_maps_all_quality_paths(self):
        self.assertEqual(classify_normality_status('normal')['palette_key'], 'normality_normal')
        self.assertEqual(classify_normality_status('not_normal')['palette_key'], 'normality_not_normal')
        self.assertEqual(classify_normality_status('unknown')['palette_key'], 'normality_unknown')

    def test_compute_normality_status_returns_unknown_for_small_or_constant_samples(self):
        self.assertEqual(compute_normality_status([1.0, 2.0])['text'], 'Shapiro p = N/A\nUnknown')
        self.assertEqual(compute_normality_status([3.0, 3.0, 3.0])['text'], 'Shapiro p = N/A\nUnknown')

    def test_compute_normality_status_returns_normal_for_gaussian_like_series(self):
        result = compute_normality_status([-1.2, -0.4, -0.1, 0.0, 0.2, 0.5, 1.1, 1.4])

        self.assertEqual(result['status'], 'normal')
        self.assertIn('Shapiro p =', result['text'])
        self.assertTrue(result['text'].endswith('\nNormal'))

    def test_compute_normality_status_returns_not_normal_for_skewed_series(self):
        result = compute_normality_status([0.0, 0.0, 0.0, 0.1, 0.2, 0.3, 4.0, 8.0])

        self.assertEqual(result['status'], 'not_normal')
        self.assertIn('Shapiro p =', result['text'])
        self.assertTrue(result['text'].endswith('\nNon-normal'))

    def test_compute_normality_status_marks_one_sided_mode_not_applicable(self):
        result = compute_normality_status([0.0, 0.02, 0.03, 0.05, 0.04, 0.01], one_sided=True, location_bound=0.0)

        self.assertEqual(result['status'], 'not_applicable')
        self.assertEqual(result['test_name'], 'One-sided tolerance model')
        self.assertIsNone(result['p_value'])
        self.assertIn('One-sided tolerance', result['text'])
        self.assertNotIn('Bound =', result['text'])
        self.assertTrue(result['text'].endswith('\nNormality not applicable'))
        self.assertEqual(classify_normality_status(result['status'])['label'], '! Normality not applicable')

    def test_render_histogram_uses_stable_fd_bins_for_non_degenerate_data(self):
        import pandas as pd

        histogram_data = [
            0.0, 0.5, 1.0, 1.5, 2.0,
            2.5, 3.0, 3.5, 4.0, 4.5,
            5.0, 5.5, 6.0, 6.5, 7.0,
            7.5, 8.0, 8.5, 9.0, 9.5,
            10.0, 10.5, 11.0, 11.5, 12.0,
        ]
        expected_fd_bins = resolve_histogram_bin_count(histogram_data)['bin_count']

        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            render_histogram(ax, pd.DataFrame({'MEAS': histogram_data}))

            self.assertEqual(len(ax.patches), expected_fd_bins)
            self.assertEqual(len(ax.patches), 3)
            total_density_area = sum((patch.get_height() * patch.get_width()) for patch in ax.patches)
            self.assertAlmostEqual(total_density_area, 1.0, places=2)
            self.assertAlmostEqual(ax.patches[0].get_linewidth(), 0.5)
            self.assertEqual(ax.patches[0].get_edgecolor(), (1.0, 1.0, 1.0, 0.72))
        finally:
            plt.close(fig)

    def test_render_histogram_uses_fallback_bins_for_constant_data(self):
        import pandas as pd

        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            render_histogram(ax, pd.DataFrame({'MEAS': [7.0] * 25}))

            self.assertEqual(len(ax.patches), 5)
            total_density_area = sum((patch.get_height() * patch.get_width()) for patch in ax.patches)
            self.assertAlmostEqual(total_density_area, 1.0, places=2)
        finally:
            plt.close(fig)

    def test_render_histogram_enforces_minimum_bin_count_of_three(self):
        import pandas as pd

        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            render_histogram(ax, pd.DataFrame({'MEAS': [1.0]}))

            self.assertEqual(len(ax.patches), 3)
            total_density_area = sum((patch.get_height() * patch.get_width()) for patch in ax.patches)
            self.assertAlmostEqual(total_density_area, 1.0, places=2)
        finally:
            plt.close(fig)

    def test_histogram_binning_qa_snapshots_for_n10_n20_and_skewed(self):
        n10_values = np.array([0.10, 0.12, 0.15, 0.20, 0.22, 0.24, 0.25, 0.30, 0.31, 0.33])
        n20_values = np.linspace(-1.0, 1.0, 20)
        skewed_values = np.array([0.0, 0.0, 0.02, 0.03, 0.05, 0.08, 0.12, 0.2, 0.4, 0.8, 1.4, 2.3, 3.8, 6.2])

        snapshots = {
            'n10': resolve_histogram_bin_count(n10_values),
            'n20': resolve_histogram_bin_count(n20_values),
            'skewed': resolve_histogram_bin_count(skewed_values),
        }

        self.assertEqual(snapshots['n10']['sample_size'], 10)
        self.assertLessEqual(snapshots['n10']['bin_count'], 8)
        self.assertEqual(snapshots['n20']['sample_size'], 20)
        self.assertLessEqual(snapshots['n20']['bin_count'], 12)
        self.assertGreaterEqual(snapshots['skewed']['bin_count'], 3)

    def test_density_curve_sampling_qa_snapshots_for_n10_n20_and_n50(self):
        n10 = resolve_density_curve_sampling(10, requested_point_count=100)
        n20 = resolve_density_curve_sampling(20, requested_point_count=100)
        n50 = resolve_density_curve_sampling(50, requested_point_count=100)

        self.assertEqual(n10, {'point_count': 40, 'kde_min_bandwidth': 0.45})
        self.assertEqual(n20, {'point_count': 60, 'kde_min_bandwidth': 0.35})
        self.assertEqual(n50, {'point_count': 100, 'kde_min_bandwidth': 0.0})

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


    def test_histogram_title_and_mean_annotation_keep_separate_bounding_boxes_with_table(self):
        import pandas as pd

        histogram_figsize = (6.2, 4)
        fig, ax = plt.subplots(figsize=histogram_figsize)
        try:
            render_histogram(ax, pd.DataFrame({'MEAS': np.linspace(9.8, 10.6, 40)}))

            font_sizes = compute_histogram_font_sizes(
                histogram_figsize,
                has_table=True,
                readability_scale=0.0,
            )
            layout = compute_histogram_table_layout(
                histogram_figsize,
                table_fontsize=font_sizes['table_fontsize'],
                has_table=True,
            )

            _ = plt.table(
                cellText=[['Statistic', 'Value'], ['Mean', '10.200']],
                colLabels=['Statistic', 'Value'],
                cellLoc='center',
                loc='right',
                bbox=[1, 0, layout['table_bbox_width'], 1],
            )

            title = render_histogram_title(ax, build_wrapped_chart_title('Histogram Layout Validation'))

            annotation_specs = build_histogram_annotation_specs(10.2, 10.6, 9.8, 1.0)
            annotation_specs, max_annotation_row = compute_histogram_annotation_rows(
                annotation_specs,
                distance_threshold=0.04,
                threshold_mode='axis_fraction',
                x_span=ax.get_xlim()[1] - ax.get_xlim()[0],
                base_text_y_axes=1.01,
                row_step=0.025,
            )
            top_margin = max(0.82, 0.82 + (max_annotation_row * 0.04))
            texts = render_histogram_annotations(
                ax,
                annotation_specs,
                annotation_fontsize=font_sizes['annotation_fontsize'],
                annotation_box={'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': '#c0c0c0', 'alpha': 0.94},
            )

            plt.subplots_adjust(right=layout['subplot_right'], top=top_margin)
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()

            title_bbox = title.get_window_extent(renderer=renderer)
            mean_text = next(text for text, spec in zip(texts, annotation_specs) if spec.get('kind') == 'mean')
            mean_bbox = mean_text.get_window_extent(renderer=renderer)

            self.assertFalse(title_bbox.overlaps(mean_bbox))
            self.assertLess(mean_bbox.y1, title_bbox.y0)
            self.assertFalse(title.get_clip_on())
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
        self.assertLessEqual(style['linewidth'], 1.4)
        self.assertLessEqual(style['alpha'], 0.5)
        self.assertLess(style['zorder'], 3)

    def test_resolve_selected_model_curve_style_maps_explicit_fit_quality_tiers(self):
        strong = resolve_selected_model_curve_style({'fit_quality': {'label': 'strong'}})
        medium = resolve_selected_model_curve_style({'fit_quality': {'label': 'medium'}})
        weak = resolve_selected_model_curve_style({'fit_quality': {'label': 'weak'}})
        unreliable = resolve_selected_model_curve_style({'fit_quality': {'label': 'unreliable'}})

        self.assertEqual(strong, {'alpha': 0.8, 'linewidth': 1.72})
        self.assertEqual(medium, {'alpha': 0.68, 'linewidth': 1.55})
        self.assertEqual(weak, {'alpha': 0.48, 'linewidth': 1.3})
        self.assertEqual(unreliable, {'alpha': 0.28, 'linewidth': 1.05})

    def test_resolve_selected_model_curve_style_defaults_unknown_quality_to_strong(self):
        fallback = resolve_selected_model_curve_style({'fit_quality': {'label': 'mystery'}})

        self.assertEqual(fallback, {'alpha': 0.8, 'linewidth': 1.72})

    def test_resolve_selected_model_curve_style_keeps_weak_unreliable_less_dominant_than_strong(self):
        def _visual_weight(style):
            return style['alpha'] * style['linewidth']

        strong = resolve_selected_model_curve_style({'fit_quality': {'label': 'strong'}})
        weak = resolve_selected_model_curve_style({'fit_quality': {'label': 'weak'}})
        unreliable = resolve_selected_model_curve_style({'fit_quality': {'label': 'unreliable'}})

        self.assertLess(weak['alpha'], strong['alpha'])
        self.assertLess(weak['linewidth'], strong['linewidth'])
        self.assertLess(unreliable['alpha'], weak['alpha'])
        self.assertLess(unreliable['linewidth'], weak['linewidth'])
        self.assertLess(_visual_weight(weak), _visual_weight(strong))
        self.assertLess(_visual_weight(unreliable), _visual_weight(weak))

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
        self.assertEqual([text.get_text() for text in rendered], ['Mean = 4.000', 'USL=8.000', 'LSL=2.000'])
        self.assertEqual(rendered[0].get_position()[0], 4.0)
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

    def test_render_histogram_annotations_resolves_priority_overlap_inside_plot_rect(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.set_xlim(0.0, 1.0)
        plt.subplots_adjust(left=0.15, right=0.85, top=0.85, bottom=0.15)

        annotation_specs = [
            {'kind': 'mean', 'x': 0.5, 'text_y_axes': 0.95, 'text': 'Mean = 0.500', 'color': '#111111', 'ha': 'center', 'priority': 300},
            {'kind': 'usl', 'x': 0.5, 'text_y_axes': 0.95, 'text': 'USL=0.500', 'color': '#222222', 'ha': 'center', 'priority': 100},
        ]

        rendered = render_histogram_annotations(
            ax,
            annotation_specs,
            annotation_fontsize=8.5,
            annotation_box={
                'boxstyle': 'round,pad=0.15',
                'fc': 'white',
                'ec': '#cccccc',
                'alpha': 0.94,
                'plot_rect': {'x': 0.0, 'y': 0.0, 'width': 1.0, 'height': 1.0},
            },
        )

        texts = [text.get_text() for text in rendered]
        self.assertIn('Mean = 0.500', texts)
        fig.canvas.draw()
        bboxes = [artist.get_window_extent(renderer=fig.canvas.get_renderer()) for artist in rendered]
        for index, left in enumerate(bboxes):
            for right in bboxes[index + 1:]:
                self.assertFalse(left.overlaps(right))
        plt.close(fig)

    def test_render_histogram_annotations_keeps_mean_usl_lsl_with_side_panel_plot_bounds(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        try:
            ax.set_xlim(0.0, 10.0)
            plt.subplots_adjust(left=0.30, right=0.70, top=0.84, bottom=0.22)

            annotation_specs = build_histogram_annotation_specs(average=5.0, usl=9.0, lsl=1.0, y_max=1.0)
            annotation_specs, _ = compute_histogram_annotation_rows(
                annotation_specs,
                distance_threshold=0.04,
                threshold_mode='axis_fraction',
                x_span=10.0,
                base_text_y_axes=1.01,
                row_step=0.025,
            )
            rendered = render_histogram_annotations(
                ax,
                annotation_specs,
                annotation_fontsize=8.2,
                annotation_box={
                    'boxstyle': 'round,pad=0.15',
                    'fc': 'white',
                    'ec': '#cccccc',
                    'alpha': 0.94,
                    'plot_rect': {'x': 0.30, 'y': 0.22, 'width': 0.40, 'height': 0.62},
                },
            )
            texts = {text.get_text() for text in rendered}
            self.assertIn('Mean = 5.000', texts)
            self.assertIn('USL=9.000', texts)
            self.assertIn('LSL=1.000', texts)
        finally:
            plt.close(fig)

    def test_render_histogram_annotations_uses_left_safe_anchor_for_lsl_near_left_boundary(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.set_xlim(0.0, 1.0)
        try:
            rendered = render_histogram_annotations(
                ax,
                [
                    {
                        'kind': 'lsl',
                        'x': 0.01,
                        'text_y_axes': 1.02,
                        'text': 'LSL=0.010',
                        'color': '#222222',
                        'ha': 'center',
                    }
                ],
                annotation_fontsize=8.5,
                annotation_box={'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': '#cccccc', 'alpha': 0.94},
            )

            self.assertEqual(len(rendered), 1)
            self.assertEqual(rendered[0].get_ha(), 'left')

            fig.canvas.draw()
            bbox = rendered[0].get_window_extent(renderer=fig.canvas.get_renderer())
            self.assertGreaterEqual(bbox.x0, 0.0)
        finally:
            plt.close(fig)

    def test_render_histogram_annotations_uses_right_safe_anchor_for_usl_near_right_boundary(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.set_xlim(0.0, 1.0)
        try:
            rendered = render_histogram_annotations(
                ax,
                [
                    {
                        'kind': 'usl',
                        'x': 0.99,
                        'text_y_axes': 1.02,
                        'text': 'USL=0.990',
                        'color': '#222222',
                        'ha': 'center',
                    }
                ],
                annotation_fontsize=8.5,
                annotation_box={'boxstyle': 'round,pad=0.15', 'fc': 'white', 'ec': '#cccccc', 'alpha': 0.94},
            )

            self.assertEqual(len(rendered), 1)
            self.assertEqual(rendered[0].get_ha(), 'right')

            fig.canvas.draw()
            bbox = rendered[0].get_window_extent(renderer=fig.canvas.get_renderer())
            self.assertLessEqual(bbox.x1, fig.bbox.x1)
        finally:
            plt.close(fig)

    def test_render_histogram_annotations_and_title_fit_with_side_panels_enabled(self):
        fig = plt.figure(figsize=(7.2, 4.0))
        try:
            rects = compute_histogram_panel_layout(
                (7.2, 4.0),
                table_fontsize=8.8,
                left_row_count=7,
                right_row_count=8,
                note_line_count=3,
                left_panel_width_hint=0.27,
                right_panel_width_hint=0.19,
            )
            plot_rect = rects['plot_rect']
            plot_ax = fig.add_axes([
                plot_rect['x'],
                plot_rect['y'],
                plot_rect['width'],
                plot_rect['height'],
            ])
            plot_ax.set_xlim(0.0, 10.0)
            plot_ax.set_ylim(0.0, 1.0)
            title_artist = render_histogram_title(plot_ax, 'Histogram panel title')
            annotation_specs = build_histogram_annotation_specs(average=5.0, usl=9.0, lsl=1.0, y_max=1.0)
            annotation_specs, _ = compute_histogram_annotation_rows(
                annotation_specs,
                distance_threshold=0.04,
                threshold_mode='axis_fraction',
                x_span=10.0,
                base_text_y_axes=1.01,
                row_step=0.025,
            )
            rendered = render_histogram_annotations(
                plot_ax,
                annotation_specs,
                annotation_fontsize=8.2,
                annotation_box={
                    'boxstyle': 'round,pad=0.15',
                    'fc': 'white',
                    'ec': '#cccccc',
                    'alpha': 0.94,
                    'plot_rect': plot_rect,
                },
            )
            fig.canvas.draw()
            fig_bbox = fig.bbox
            title_bbox = title_artist.get_window_extent(renderer=fig.canvas.get_renderer())

            texts = {text.get_text() for text in rendered}
            self.assertEqual(len(rendered), 3)
            self.assertIn('Mean = 5.000', texts)
            self.assertIn('USL=9.000', texts)
            self.assertIn('LSL=1.000', texts)
            self.assertLess(title_bbox.y0, fig_bbox.y1)
            self.assertLessEqual(title_artist.get_position()[1], 1.145)
            self.assertGreater(title_artist.get_position()[1], 1.0)
        finally:
            plt.close(fig)


    def test_render_histogram_annotations_resolves_close_limit_collisions_with_offsets_or_leaders(self):
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        try:
            ax.set_xlim(9.95, 10.05)
            ax.set_ylim(0.0, 1.0)
            annotation_specs = build_histogram_annotation_specs(average=10.0, usl=10.002, lsl=9.998, y_max=1.0)
            annotation_specs, _ = compute_histogram_annotation_rows(
                annotation_specs,
                distance_threshold=0.04,
                threshold_mode='axis_fraction',
                x_span=0.10,
                base_text_y_axes=1.01,
                row_step=0.025,
            )
            rendered = render_histogram_annotations(
                ax,
                annotation_specs,
                annotation_fontsize=8.1,
                annotation_box={
                    'boxstyle': 'round,pad=0.15',
                    'fc': 'white',
                    'ec': '#cccccc',
                    'alpha': 0.94,
                    'plot_rect': {'x': 0.14, 'y': 0.18, 'width': 0.76, 'height': 0.70},
                },
            )
            self.assertEqual(len(rendered), 3)
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            bboxes = [artist.get_window_extent(renderer=renderer) for artist in rendered]
            for index, left in enumerate(bboxes):
                for right in bboxes[index + 1:]:
                    self.assertFalse(left.overlaps(right))

        finally:
            plt.close(fig)

    def test_render_histogram_annotations_avoids_title_overlap_with_offsets(self):
        fig = plt.figure(figsize=(7.2, 4.0))
        try:
            rects = compute_histogram_plot_with_right_info_layout(
                (7.2, 4.0),
                table_fontsize=8.8,
                fit_row_count=8,
                stats_row_count=8,
                note_line_count=2,
                right_container_width_hint=0.34,
            )
            plot_rect = rects['plot_rect']
            ax = fig.add_axes([plot_rect['x'], plot_rect['y'], plot_rect['width'], plot_rect['height']])
            ax.set_xlim(0.0, 1.0)
            title_artist = render_histogram_title(ax, 'Distribution Fit')
            annotation_specs = [
                {'kind': 'mean', 'x': 0.5, 'text_y_axes': 1.14, 'text': 'Mean = 0.500', 'color': '#111111', 'ha': 'center', 'priority': 300},
                {'kind': 'usl', 'x': 0.52, 'text_y_axes': 1.14, 'text': 'USL=0.520', 'color': '#222222', 'ha': 'center', 'priority': 260},
                {'kind': 'lsl', 'x': 0.48, 'text_y_axes': 1.14, 'text': 'LSL=0.480', 'color': '#222222', 'ha': 'center', 'priority': 250},
            ]
            rendered = render_histogram_annotations(
                ax,
                annotation_specs,
                annotation_fontsize=8.2,
                annotation_box={
                    'boxstyle': 'round,pad=0.15',
                    'fc': 'white',
                    'ec': '#cccccc',
                    'alpha': 0.94,
                    'plot_rect': plot_rect,
                    'title_artist': title_artist,
                },
            )
            fig.canvas.draw()
            title_bbox = title_artist.get_window_extent(renderer=fig.canvas.get_renderer())
            for artist in rendered:
                self.assertFalse(artist.get_window_extent(renderer=fig.canvas.get_renderer()).overlaps(title_bbox))
        finally:
            plt.close(fig)

    def test_histogram_layout_reserves_additional_top_padding_for_annotation_band(self):
        self.assertGreaterEqual(HISTOGRAM_OUTER_PADDING_TOP, 0.08)

    def test_render_histogram_annotations_and_title_fit_with_right_info_column_layout(self):
        fig = plt.figure(figsize=(7.6, 4.0))
        try:
            rects = compute_histogram_plot_with_right_info_layout(
                (7.6, 4.0),
                table_fontsize=8.8,
                fit_row_count=7,
                stats_row_count=8,
                note_line_count=3,
                right_container_width_hint=0.34,
            )
            plot_rect = rects['plot_rect']
            plot_ax = fig.add_axes([
                plot_rect['x'],
                plot_rect['y'],
                plot_rect['width'],
                plot_rect['height'],
            ])
            plot_ax.set_xlim(0.0, 10.0)
            plot_ax.set_ylim(0.0, 1.0)
            title_artist = render_histogram_title(plot_ax, 'Histogram panel title')
            annotation_specs = build_histogram_annotation_specs(average=5.0, usl=9.0, lsl=1.0, y_max=1.0)
            annotation_specs, _ = compute_histogram_annotation_rows(
                annotation_specs,
                distance_threshold=0.04,
                threshold_mode='axis_fraction',
                x_span=10.0,
                base_text_y_axes=1.01,
                row_step=0.025,
            )
            rendered = render_histogram_annotations(
                plot_ax,
                annotation_specs,
                annotation_fontsize=8.2,
                annotation_box={
                    'boxstyle': 'round,pad=0.15',
                    'fc': 'white',
                    'ec': '#cccccc',
                    'alpha': 0.94,
                    'plot_rect': plot_rect,
                },
            )
            fig.canvas.draw()

            texts = {text.get_text() for text in rendered}
            self.assertEqual(len(rendered), 3)
            self.assertIn('Mean = 5.000', texts)
            self.assertIn('USL=9.000', texts)
            self.assertIn('LSL=1.000', texts)
            self.assertFalse(any('P(X < LSL)' in text for text in texts))
            self.assertFalse(any('P(X > USL)' in text for text in texts))
            self.assertLess(title_artist.get_window_extent(renderer=fig.canvas.get_renderer()).y0, fig.bbox.y1)
            self.assertFalse(title_artist.get_clip_on())
        finally:
            plt.close(fig)

    def test_histogram_layout_keeps_xlabel_and_ticks_inside_figure_bounds(self):
        fig = plt.figure(figsize=(7.2, 4.0))
        try:
            rects = compute_histogram_panel_layout(
                (7.2, 4.0),
                table_fontsize=8.8,
                left_row_count=6,
                right_row_count=6,
                note_line_count=2,
                left_panel_width_hint=0.27,
                right_panel_width_hint=0.19,
            )
            plot_rect = rects['plot_rect']
            ax = fig.add_axes([plot_rect['x'], plot_rect['y'], plot_rect['width'], plot_rect['height']])
            ax.plot([0, 1, 2], [1, 3, 2])
            ax.set_xlabel('Measurement')
            fig.canvas.draw()

            renderer = fig.canvas.get_renderer()
            fig_bbox = fig.bbox
            xlabel_bbox = ax.xaxis.label.get_window_extent(renderer=renderer)
            tick_bboxes = [tick.label1.get_window_extent(renderer=renderer) for tick in ax.xaxis.get_major_ticks() if tick.label1.get_visible()]

            self.assertGreaterEqual(xlabel_bbox.y0, fig_bbox.y0)
            self.assertTrue(all(bbox.y0 >= fig_bbox.y0 for bbox in tick_bboxes))
        finally:
            plt.close(fig)

    def test_render_histogram_note_panel_keeps_compact_text_within_panel_bounds(self):
        fig = plt.figure(figsize=(7.2, 4.0))
        try:
            rects = compute_histogram_panel_layout(
                (7.2, 4.0),
                table_fontsize=8.8,
                left_row_count=6,
                right_row_count=7,
                note_line_count=3,
                left_panel_width_hint=0.27,
                right_panel_width_hint=0.19,
            )
            note_rect = rects['note_rect']
            note_ax = fig.add_axes([note_rect['x'], note_rect['y'], note_rect['width'], note_rect['height']])
            note_ax.set_axis_off()
            meta = render_histogram_note_panel(
                ax=note_ax,
                note_items=[
                    {'label': 'Family', 'compact_label': 'Family', 'value': 'signed/bilateral', 'priority': 90},
                    {'label': 'Normality', 'compact_label': 'Normality', 'value': 'non-normal', 'priority': 60},
                    {'label': 'Warning', 'compact_label': 'Warning', 'value': 'fit weak', 'priority': 30},
                ],
                style_options={'fontsize': 7.0},
                available_height_px=note_rect['height'] * float(fig.bbox.height),
            )
            fig.canvas.draw()
            text_bbox = meta['text_artist'].get_window_extent(renderer=fig.canvas.get_renderer())
            ax_bbox = note_ax.get_window_extent(renderer=fig.canvas.get_renderer())

            self.assertGreaterEqual(text_bbox.x0, ax_bbox.x0 - 1.0)
            self.assertLessEqual(text_bbox.x1, ax_bbox.x1 + 1.0)
            self.assertGreaterEqual(text_bbox.y0, ax_bbox.y0 - 1.0)
            self.assertLessEqual(text_bbox.y1, ax_bbox.y1 + 1.0)
        finally:
            plt.close(fig)


    def test_compute_histogram_annotation_rows_stacks_close_markers_and_keeps_mean_highest(self):
        annotation_specs = build_histogram_annotation_specs(average=10.0, usl=10.01, lsl=9.99, y_max=1.0)

        resolved, max_row = compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.05,
            threshold_mode='data_units',
            base_text_y_axes=1.01,
            row_step=0.025,
        )

        by_kind = {item['kind']: item for item in resolved}
        self.assertEqual(max_row, 3)
        self.assertGreater(by_kind['mean']['text_y_axes'], by_kind['usl']['text_y_axes'])
        self.assertNotEqual(by_kind['usl']['row_index'], by_kind['lsl']['row_index'])
        self.assertNotEqual(by_kind['mean']['row_index'], by_kind['lsl']['row_index'])
        self.assertEqual(by_kind['mean']['x'], 10.0)

    def test_compute_histogram_annotation_rows_allows_shared_lower_row_when_limits_are_far(self):
        annotation_specs = build_histogram_annotation_specs(average=10.0, usl=12.0, lsl=8.0, y_max=1.0)

        resolved, max_row = compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.05,
            threshold_mode='data_units',
            base_text_y_axes=1.01,
            row_step=0.025,
        )

        by_kind = {item['kind']: item for item in resolved}
        self.assertEqual(max_row, 3)
        self.assertEqual(by_kind['mean']['row_index'], 1)
        self.assertEqual(by_kind['usl']['row_index'], 2)
        self.assertEqual(by_kind['lsl']['row_index'], 3)
        self.assertAlmostEqual(by_kind['mean']['text_y_axes'], 1.08)
    def test_compute_histogram_annotation_rows_stacks_mean_and_usl_when_close(self):
        annotation_specs = build_histogram_annotation_specs(average=10.0, usl=10.02, lsl=7.0, y_max=1.0)

        resolved, max_row = compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.05,
            threshold_mode='data_units',
            base_text_y_axes=1.01,
            row_step=0.025,
        )

        by_kind = {item['kind']: item for item in resolved}
        self.assertEqual(max_row, 3)
        self.assertEqual(by_kind['mean']['row_index'], 1)
        self.assertEqual(by_kind['usl']['row_index'], 2)
        self.assertEqual(by_kind['lsl']['row_index'], 3)
        self.assertEqual([item['kind'] for item in resolved], ['mean', 'usl', 'lsl'])
        self.assertEqual([item['x'] for item in resolved], [10.0, 10.02, 7.0])

    def test_compute_histogram_annotation_rows_stacks_mean_and_lsl_when_close(self):
        annotation_specs = build_histogram_annotation_specs(average=10.0, usl=13.0, lsl=10.03, y_max=1.0)

        resolved, max_row = compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.05,
            threshold_mode='data_units',
            base_text_y_axes=1.01,
            row_step=0.025,
        )

        by_kind = {item['kind']: item for item in resolved}
        self.assertEqual(max_row, 3)
        self.assertEqual(by_kind['mean']['row_index'], 1)
        self.assertEqual(by_kind['usl']['row_index'], 2)
        self.assertEqual(by_kind['lsl']['row_index'], 3)
        self.assertEqual([item['kind'] for item in resolved], ['mean', 'usl', 'lsl'])
        self.assertEqual([item['x'] for item in resolved], [10.0, 13.0, 10.03])

    def test_compute_histogram_annotation_rows_uses_axis_fraction_threshold_for_clustered_triplet(self):
        annotation_specs = build_histogram_annotation_specs(average=10.0, usl=10.2, lsl=9.9, y_max=1.0)

        resolved, max_row = compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.04,
            threshold_mode='axis_fraction',
            x_span=10.0,
            base_text_y_axes=1.01,
            row_step=0.025,
        )

        by_kind = {item['kind']: item for item in resolved}
        self.assertEqual(max_row, 3)
        self.assertEqual(by_kind['mean']['row_index'], 1)
        self.assertEqual(by_kind['usl']['row_index'], 2)
        self.assertEqual(by_kind['lsl']['row_index'], 3)
        self.assertEqual([item['kind'] for item in resolved], ['mean', 'usl', 'lsl'])
        self.assertEqual([item['x'] for item in resolved], [10.0, 10.2, 9.9])

    def test_compute_histogram_annotation_rows_keeps_mean_above_spec_rows_across_proximity_modes(self):
        scenarios = [
            dict(average=10.0, usl=10.01, lsl=9.99, kwargs={'threshold_mode': 'data_units', 'distance_threshold': 0.05}),
            dict(average=10.0, usl=12.0, lsl=8.0, kwargs={'threshold_mode': 'data_units', 'distance_threshold': 0.05}),
            dict(average=10.0, usl=10.2, lsl=9.9, kwargs={'threshold_mode': 'axis_fraction', 'x_span': 10.0, 'distance_threshold': 0.04}),
        ]

        for case in scenarios:
            annotation_specs = build_histogram_annotation_specs(
                average=case['average'],
                usl=case['usl'],
                lsl=case['lsl'],
                y_max=1.0,
            )
            resolved, _ = compute_histogram_annotation_rows(
                annotation_specs,
                base_text_y_axes=1.01,
                row_step=0.025,
                **case['kwargs'],
            )
            by_kind = {item['kind']: item for item in resolved}
            self.assertGreater(by_kind['mean']['text_y_axes'], by_kind['usl']['text_y_axes'])
            self.assertNotEqual(by_kind['mean']['row_index'], by_kind['lsl']['row_index'])

    def test_compute_histogram_annotation_rows_clustered_triplet_uses_non_overlapping_rows(self):
        annotation_specs = build_histogram_annotation_specs(average=5.0, usl=5.01, lsl=4.99, y_max=1.0)

        resolved, max_row = compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.05,
            threshold_mode='data_units',
            base_text_y_axes=1.01,
            row_step=0.025,
        )
        rows = [item['row_index'] for item in resolved]

        self.assertEqual(max_row, 3)
        self.assertEqual(len(set(rows)), 3)

    def test_compute_histogram_annotation_rows_well_separated_triplet_keeps_preferred_slots(self):
        annotation_specs = build_histogram_annotation_specs(average=5.0, usl=9.0, lsl=1.0, y_max=1.0)

        resolved, max_row = compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.05,
            threshold_mode='data_units',
            base_text_y_axes=1.01,
            row_step=0.025,
        )
        by_kind = {item['kind']: item for item in resolved}

        self.assertEqual(max_row, 3)
        self.assertEqual(by_kind['mean']['row_index'], 1)
        self.assertEqual(by_kind['usl']['row_index'], 2)
        self.assertEqual(by_kind['lsl']['row_index'], 3)
        self.assertEqual(by_kind['mean']['assigned_slot'], 'mean_primary')
        self.assertEqual(by_kind['usl']['assigned_slot'], 'spec_primary')
        self.assertEqual(by_kind['lsl']['assigned_slot'], 'spec_secondary')

    def test_compute_histogram_annotation_rows_is_deterministic_for_same_inputs(self):
        annotation_specs = build_histogram_annotation_specs(average=10.0, usl=10.05, lsl=9.95, y_max=1.0)

        resolved_a, max_row_a = compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.04,
            threshold_mode='axis_fraction',
            x_span=1.0,
            base_text_y_axes=1.01,
            row_step=0.025,
        )
        resolved_b, max_row_b = compute_histogram_annotation_rows(
            annotation_specs,
            distance_threshold=0.04,
            threshold_mode='axis_fraction',
            x_span=1.0,
            base_text_y_axes=1.01,
            row_step=0.025,
        )

        self.assertEqual(max_row_a, max_row_b)
        self.assertEqual(
            [(item['kind'], item['assigned_slot'], item['text_y_axes']) for item in resolved_a],
            [(item['kind'], item['assigned_slot'], item['text_y_axes']) for item in resolved_b],
        )

    def test_build_histogram_annotation_specs_aligns_annotation_x_to_marker_values(self):
        average, usl, lsl = 10.123, 11.3, 9.4
        specs = build_histogram_annotation_specs(average=average, usl=usl, lsl=lsl, y_max=1.0)
        by_kind = {item['kind']: item for item in specs}

        self.assertEqual(by_kind['mean']['x'], average)
        self.assertEqual(by_kind['usl']['x'], usl)
        self.assertEqual(by_kind['lsl']['x'], lsl)


    def test_build_summary_panel_subtitle_text_formats_samples_and_nok_percent(self):
        subtitle = build_summary_panel_subtitle_text({'sample_size': 12, 'nok_pct': 0.083333})

        self.assertEqual(subtitle, 'n=12 • NOK=8.3%')

    def test_build_histogram_table_data_formats_nok_as_percent_string(self):
        payload = build_histogram_table_data(
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

        table = payload['rows']
        self.assertEqual(table[-4], ('NOK', '2.000'))
        self.assertEqual(table[-3], ('NOK %', '8.33%'))
        self.assertEqual(table[-2], ('NOK % (obs vs est)', 'N/A'))
        self.assertEqual(table[-1], ('NOK % Δ (abs/rel)', 'N/A'))


    def test_build_histogram_table_data_uses_cpu_for_one_sided_upper_case(self):
        payload = build_histogram_table_data(
            {
                'minimum': 0.0,
                'maximum': 0.06,
                'average': 0.03,
                'median': 0.03,
                'sigma': 0.01,
                'cp': 'N/A',
                'cpk': 0.0,
                'sample_size': 8,
                'nok_count': 0,
                'nok_pct': 0.0,
                'normality_status': 'normal',
                'normality_p_value': 0.52,
                'usl': 0.06,
            }
        )

        table = payload['rows']
        labels = [label for label, _ in table]
        self.assertIn('Cpu', labels)
        self.assertNotIn('Cpk', labels)
        self.assertIn('Spec type', labels)
        self.assertIn(('Spec type', 'one-sided upper'), table)
        self.assertIn('Cp (not defined for one-sided) (info)', labels)

    def test_build_histogram_table_data_exposes_cpu_metadata_for_badges(self):
        payload = build_histogram_table_data(
            {
                'minimum': 0.0,
                'maximum': 0.06,
                'average': 0.031,
                'median': 0.031,
                'sigma': 0.0099,
                'cp': 'N/A',
                'cpk': 0.0,
                'sample_size': 8,
                'nok_count': 0,
                'nok_pct': 0.0,
                'normality_status': 'normal',
                'normality_p_value': 0.52,
                'usl': 0.06,
            }
        )

        cpk_row = next((row for row in payload['rows'] if row[0] == 'Cpu'), None)
        self.assertIsNotNone(cpk_row)

        expected_cpu = (0.06 - 0.031) / (3 * 0.0099)
        self.assertIn('Low-confidence estimate', str(cpk_row[1]))
        self.assertEqual(payload['capability_rows']['Cpk']['label'], 'Cpu')
        self.assertIn('Low-confidence estimate', str(payload['capability_rows']['Cpk']['display_value']))
        self.assertEqual(payload['capability_rows']['Cpk']['classification_value'], expected_cpu)

    def test_apply_non_normal_cpk_reference_label_for_non_normal_selected_model(self):
        payload = {
            'rows': [
                ('Cp', 1.22),
                ('Cp 95% CI', '[1.10, 1.34]'),
                ('Cpk', 1.15),
                ('Cpk 95% CI', '[1.03, 1.28]'),
                ('Cpu', 1.11),
                ('Cpl', 1.08),
                ('NOK %', '0.40%'),
            ],
            'capability_rows': {
                'Cp': {'label': 'Cp', 'display_value': 1.22, 'classification_value': 1.22},
                'Cpk': {'label': 'Cpk', 'display_value': 1.11, 'classification_value': 1.11},
                'Cpu': {'label': 'Cpu', 'display_value': 1.11, 'classification_value': 1.11},
                'Cpl': {'label': 'Cpl', 'display_value': 1.08, 'classification_value': 1.08},
            },
        }

        relabeled = _apply_non_normal_cpk_reference_label(
            payload,
            {'selected_model': {'model': 'johnsonsu'}},
        )
        labels = [label for label, _ in relabeled['rows']]

        self.assertEqual(labels.count('Cpk (normal ref)'), 1)
        self.assertIn('Cp (normal ref) 95% CI', labels)
        self.assertIn('Cpk (normal ref) 95% CI', labels)
        self.assertIn('Cpu (normal ref)', labels)
        self.assertIn('Cpl (normal ref)', labels)
        self.assertIn('Cp (normal ref)', labels)
        self.assertNotIn('Cp', labels)
        self.assertNotIn('Cpk', labels)
        self.assertNotIn('Cpu', labels)
        self.assertNotIn('Cpl', labels)
        self.assertEqual(relabeled['capability_rows']['Cp']['label'], 'Cp (normal ref)')
        self.assertEqual(relabeled['capability_rows']['Cpk']['label'], 'Cpk (normal ref)')
        self.assertEqual(relabeled['capability_rows']['Cpu']['label'], 'Cpu (normal ref)')
        self.assertEqual(relabeled['capability_rows']['Cpl']['label'], 'Cpl (normal ref)')

    def test_apply_non_normal_cpk_reference_label_keeps_ci_labels_for_normal_model(self):
        payload = {
            'rows': [('Cp', 1.22), ('Cp 95% CI', '[1.10, 1.34]'), ('Cpk', 1.15), ('Cpk 95% CI', '[1.03, 1.28]')],
            'capability_rows': {
                'Cp': {'label': 'Cp', 'display_value': 1.22, 'classification_value': 1.22},
                'Cpk': {'label': 'Cpk', 'display_value': 1.11, 'classification_value': 1.11},
            },
        }

        relabeled = _apply_non_normal_cpk_reference_label(payload, {'selected_model': {'model': 'norm'}})
        labels = [label for label, _ in relabeled['rows']]
        self.assertEqual(labels, ['Cp', 'Cp 95% CI', 'Cpk', 'Cpk 95% CI'])


    def test_build_histogram_table_render_data_three_column_duplicates_label_in_first_two_columns(self):
        table_data = [('Min', '1.0'), ('NOK %', '8.33%')]

        render_data = build_histogram_table_render_data(table_data, three_column=True)

        self.assertEqual(render_data[0], ['Min', '', '1.0'])
        self.assertEqual(render_data[1], ['NOK %', '', '8.33%'])

    def test_style_histogram_stats_table_applies_normality_badges_for_each_status(self):
        scenarios = [
            ('Shapiro p = 0.5000\nNormal', 'normal', 'normality_normal_bg'),
            ('Shapiro p = 0.0040\nNon-normal', 'not_normal', 'normality_not_normal_bg'),
            ('Shapiro p = N/A\nUnknown', 'unknown', 'normality_unknown_bg'),
            ('One-sided tolerance\nNormality not applicable', 'not_applicable', 'normality_unknown_bg'),
        ]

        for normality_text, status, palette_bg in scenarios:
            fig, ax = plt.subplots(figsize=(4, 3))
            table_data = [('Normality', normality_text)]
            render_data = build_histogram_table_render_data(table_data, three_column=True)
            ax_table = ax.table(cellText=render_data, colLabels=['Statistic', ' ', 'Value'], cellLoc='center')

            style_histogram_stats_table(
                ax_table,
                render_data,
                capability_row_badges={'Normality': classify_normality_status(status)},
            )
            adjust_histogram_stats_table_geometry(
                ax_table,
            )

            self.assertEqual(
                ax_table.get_celld()[(1, 0)].get_facecolor(),
                matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE[palette_bg]),
            )
            self.assertEqual(
                ax_table.get_celld()[(1, 1)].get_facecolor(),
                matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE[palette_bg]),
            )
            self.assertEqual(
                ax_table.get_celld()[(1, 2)].get_facecolor(),
                matplotlib.colors.to_rgba(SUMMARY_PLOT_PALETTE[palette_bg]),
            )
            self.assertTrue(ax_table.get_celld()[(1, 1)].get_visible())
            self.assertTrue(ax_table.get_celld()[(1, 2)].get_visible())
            self.assertEqual(ax_table.get_celld()[(1, 0)].get_text().get_text(), 'Normality')
            self.assertTrue(ax_table.get_celld()[(1, 2)].get_text().get_text().startswith(('✓ ', '! ', '× ')))
            self.assertTrue(ax_table.get_celld()[(1, 2)].get_text().get_text().endswith(normality_text))
            self.assertEqual(
                ax_table.get_celld()[(1, 0)].get_text().get_color(),
                SUMMARY_PLOT_PALETTE[palette_bg.replace('_bg', '_text')],
            )
            self.assertTrue(ax_table.get_celld()[(1, 0)].get_hatch() in {'', '..', '///', 'xx'})

            self.assertEqual(ax_table.get_celld()[(1, 0)].get_text().get_fontweight(), 'normal')
            self.assertEqual(ax_table.get_celld()[(1, 1)].get_text().get_fontweight(), 'normal')
            self.assertEqual(ax_table.get_celld()[(1, 2)].get_text().get_fontweight(), 'normal')
            plt.close(fig)

    def test_histogram_table_layout_three_column_keeps_data_rows_renderable(self):
        summary_stats = {
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
        table_payload = build_histogram_table_data(summary_stats)
        table_data = table_payload['rows']

        render_data = build_histogram_table_render_data(table_data, three_column=True)
        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            ax_table = ax.table(
                cellText=render_data,
                colLabels=['Statistic', ' ', 'Value'],
                cellLoc='center',
                loc='right',
                bbox=[1, 0, 0.3, 1],
            )

            style_histogram_stats_table(ax_table, render_data)
            adjust_histogram_stats_table_geometry(
                ax_table,
                statistic_col_width_ratio=0.56,
                row_height_scale=1.15,
            )
            fig.canvas.draw()

            self.assertTrue(ax_table.get_celld()[(1, 0)].get_visible())
            self.assertTrue(ax_table.get_celld()[(1, 1)].get_visible())
            self.assertTrue(ax_table.get_celld()[(1, 2)].get_visible())
        finally:
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

    def test_build_wrapped_chart_title_supports_three_line_iqr_titles(self):
        wrapped = build_wrapped_chart_title(
            '51.3 mm from plane L - D - IQR Outlier Detection with a very long extra descriptor that should avoid legend overlap',
            width=42,
            max_lines=3,
        )

        lines = wrapped.split('\n')
        self.assertGreaterEqual(len(lines), 2)
        self.assertLessEqual(len(lines), 3)

    def test_build_wrapped_chart_title_uses_shared_default_strategy(self):
        wrapped = build_wrapped_chart_title(
            'A very long shared summary title that should wrap consistently across violin iqr histogram and trend plots',
        )

        lines = wrapped.split('\n')
        self.assertGreaterEqual(len(lines), 2)
        self.assertLessEqual(len(lines), 3)

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

        self.assertEqual(ax_table.get_celld()[(1, 1)].get_text().get_text(), '✓ 1.45')
        self.assertEqual(ax_table.get_celld()[(2, 1)].get_text().get_text(), '✓ 1.4')
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

    def test_render_spec_reference_lines_vertical_use_updated_style_contract(self):
        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            lines = render_spec_reference_lines(ax, nom=10.0, lsl=9.5, usl=10.5, orientation='vertical', include_nominal=False)
            self.assertEqual(len(lines), 2)
            self.assertAlmostEqual(lines[0].get_alpha(), 0.8)
            self.assertAlmostEqual(lines[0].get_linewidth(), 1.5)
            self.assertEqual(tuple(lines[0].get_ydata()), (0, 0.92))
        finally:
            plt.close(fig)

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
            [0, 1],
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
        style = annotate_violin_group_stats(ax, ['A'], values, [0], annotation_mode='full', nom=1.0, lsl=0.5)

        sigma_collection = ax.collections[-1]
        segment = sigma_collection.get_segments()[0]
        y_start = float(segment[0][1])
        y_end = float(segment[1][1])
        mean_val = float(sum(values[0]) / len(values[0]))

        self.assertFalse(style['one_sided_sigma_mode'])
        self.assertLess(y_start, mean_val)
        self.assertGreater(y_end, mean_val)
        plt.close(fig)


    def test_annotate_violin_group_stats_explicit_one_sided_true_overrides_heuristic(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.set_xlim(-0.5, 0.5)

        values = [[1.0, 2.0, 3.0, 4.0]]
        style = annotate_violin_group_stats(
            ax,
            ['A'],
            values,
            [0],
            annotation_mode='full',
            nom=1.0,
            lsl=0.5,
            one_sided=True,
        )

        sigma_collection = ax.collections[-1]
        segment = sigma_collection.get_segments()[0]
        y_start = float(segment[0][1])
        mean_val = float(sum(values[0]) / len(values[0]))

        self.assertTrue(style['one_sided_sigma_mode'])
        self.assertTrue(style['one_sided_sigma_explicit'])
        self.assertAlmostEqual(y_start, mean_val, places=7)
        plt.close(fig)

    def test_annotate_violin_group_stats_explicit_one_sided_false_overrides_heuristic(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.set_xlim(-0.5, 0.5)

        values = [[1.0, 2.0, 3.0, 4.0]]
        style = annotate_violin_group_stats(
            ax,
            ['A'],
            values,
            [0],
            annotation_mode='full',
            nom=0.0,
            lsl=0.0,
            one_sided=False,
        )

        sigma_collection = ax.collections[-1]
        segment = sigma_collection.get_segments()[0]
        y_start = float(segment[0][1])
        mean_val = float(sum(values[0]) / len(values[0]))

        self.assertFalse(style['one_sided_sigma_mode'])
        self.assertTrue(style['one_sided_sigma_explicit'])
        self.assertLess(y_start, mean_val)
        plt.close(fig)

    def test_render_violin_fallback_heuristic_uses_one_sided_sigma_when_mode_not_provided(self):
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

    def test_annotate_violin_group_stats_one_sided_sigma_segment_starts_at_mean(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.set_xlim(-0.5, 0.5)

        values = [[1.0, 2.0, 3.0, 4.0]]
        style = annotate_violin_group_stats(ax, ['A'], values, [0], annotation_mode='full', nom=0.0, lsl=0.0)

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

    def test_render_violin_uses_one_sided_sigma_legend_label_for_explicit_mode(self):
        fig, ax = plt.subplots(figsize=(6, 4))

        render_violin(
            ax,
            [[1.0, 1.2, 0.8], [1.5, 1.7, 1.4]],
            ['A', 'B'],
            nom=1.0,
            lsl=0.5,
            one_sided=True,
            readability_scale=0.3,
        )

        legend = ax.get_legend()
        self.assertIsNotNone(legend)
        legend_labels = [text.get_text() for text in legend.get_texts()]
        self.assertIn('+3σ span (visual)', legend_labels)
        self.assertNotIn('±3σ span (visual)', legend_labels)
        plt.close(fig)

    def test_render_violin_uses_plus_minus_sigma_legend_label_for_explicit_two_sided_mode(self):
        fig, ax = plt.subplots(figsize=(6, 4))

        render_violin(
            ax,
            [[1.0, 1.2, 0.8], [1.5, 1.7, 1.4]],
            ['A', 'B'],
            nom=0.0,
            lsl=0.0,
            one_sided=False,
            readability_scale=0.3,
        )

        legend = ax.get_legend()
        self.assertIsNotNone(legend)
        legend_labels = [text.get_text() for text in legend.get_texts()]
        self.assertIn('±3σ span (visual)', legend_labels)
        self.assertNotIn('+3σ span (visual)', legend_labels)
        plt.close(fig)

    def test_annotation_collision_resolution_is_deterministic_for_dense_groups(self):
        values = [[1.0, 1.0, 1.0], [1.01, 1.01, 1.01], [1.02, 1.02, 1.02], [1.03, 1.03, 1.03]]
        labels = ['G1', 'G2', 'G3', 'G4']

        fig_one, ax_one = plt.subplots(figsize=(6, 4))
        ax_one.set_xlim(-0.5, len(labels) - 0.5)
        annotate_violin_group_stats(ax_one, labels, values, list(range(len(labels))), annotation_mode='full')
        positions_one = [(round(text.xyann[0], 2), round(text.xyann[1], 2), text.get_text()) for text in ax_one.texts]

        fig_two, ax_two = plt.subplots(figsize=(6, 4))
        ax_two.set_xlim(-0.5, len(labels) - 0.5)
        annotate_violin_group_stats(ax_two, labels, values, list(range(len(labels))), annotation_mode='full')
        positions_two = [(round(text.xyann[0], 2), round(text.xyann[1], 2), text.get_text()) for text in ax_two.texts]

        self.assertEqual(positions_one, positions_two)
        base_offsets = {(4.0, -10.0), (4.0, 2.0)}
        self.assertTrue(any((x, y) not in base_offsets for x, y, _ in positions_one))
        plt.close(fig_one)
        plt.close(fig_two)

    def test_annotate_violin_group_stats_dynamic_offsets_keep_marker_and_style_behavior(self):
        labels = ['A', 'B']
        values = [[1.0, 1.2, 1.4], [1.5, 1.7, 1.9]]
        positions = [0, 1]

        fig_static, ax_static = plt.subplots(figsize=(6, 4))
        ax_static.set_xlim(-0.5, 1.5)
        style_static = annotate_violin_group_stats(
            ax_static,
            labels,
            values,
            positions,
            annotation_mode='full',
            use_dynamic_offsets=False,
        )

        fig_dynamic, ax_dynamic = plt.subplots(figsize=(6, 4))
        ax_dynamic.set_xlim(-0.5, 1.5)
        style_dynamic = annotate_violin_group_stats(
            ax_dynamic,
            labels,
            values,
            positions,
            annotation_mode='full',
            use_dynamic_offsets=True,
        )

        self.assertEqual(style_dynamic, style_static)
        static_text_map = {text.get_text(): (round(text.xyann[0], 2), round(text.xyann[1], 2)) for text in ax_static.texts}
        dynamic_text_map = {text.get_text(): (round(text.xyann[0], 2), round(text.xyann[1], 2)) for text in ax_dynamic.texts}
        self.assertEqual(set(static_text_map), set(dynamic_text_map))

        expected_offsets = {
            'min=1.000': (4.0, -10.0),
            'μ=1.200': (4.0, 2.0),
            'max=1.400': (4.0, 2.0),
            'min=1.500': (4.0, -10.0),
            'μ=1.700': (4.0, 2.0),
            'max=1.900': (4.0, 2.0),
        }
        self.assertEqual(dynamic_text_map, expected_offsets)

        static_markers = sorted(
            (float(point[0]), float(point[1]))
            for collection in ax_static.collections
            if hasattr(collection, 'get_offsets')
            for point in collection.get_offsets()
            if np.isfinite(point[0]) and np.isfinite(point[1])
        )
        dynamic_markers = sorted(
            (float(point[0]), float(point[1]))
            for collection in ax_dynamic.collections
            if hasattr(collection, 'get_offsets')
            for point in collection.get_offsets()
            if np.isfinite(point[0]) and np.isfinite(point[1])
        )
        self.assertEqual(dynamic_markers, static_markers)

        plt.close(fig_static)
        plt.close(fig_dynamic)

    def test_annotate_violin_group_stats_uses_positions_for_sigma_and_mean_markers(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        values = [[1.0, 2.0, 3.0], [1.5, 1.7, 1.9]]
        positions = [5, 8]

        annotate_violin_group_stats(ax, ['A', 'B'], values, positions, annotation_mode='full')

        sigma_segments = []
        for collection in ax.collections:
            if hasattr(collection, 'get_segments'):
                sigma_segments.extend(collection.get_segments())
        sigma_x_positions = sorted(float(segment[0][0]) for segment in sigma_segments)
        self.assertEqual(sigma_x_positions, [5.0, 8.0])

        scatter_x_positions = sorted(
            {
                float(point[0])
                for collection in ax.collections
                if hasattr(collection, 'get_offsets')
                for point in collection.get_offsets()
            }
        )
        self.assertIn(5.0, scatter_x_positions)
        self.assertIn(8.0, scatter_x_positions)

        text_x_positions = sorted({float(text.xy[0]) for text in ax.texts if text.get_text().startswith('μ=')})
        self.assertEqual(text_x_positions, [5.0, 8.0])
        plt.close(fig)

    def test_render_violin_uses_backend_consistent_annotation_positions(self):
        values = [[1.0, 2.0, 3.0], [1.5, 1.7, 1.9]]
        labels = ['A', 'B']

        fig_seaborn, ax_seaborn = plt.subplots(figsize=(6, 4))
        seaborn_stub = types.SimpleNamespace(violinplot=lambda **kwargs: None)
        with mock.patch('modules.export_data_thread._HAS_SEABORN', True), mock.patch('modules.export_data_thread.sns', seaborn_stub, create=True):
            render_violin(ax_seaborn, values, labels)
        seaborn_mean_x = sorted({float(text.xy[0]) for text in ax_seaborn.texts if text.get_text().startswith('μ=')})
        self.assertEqual(seaborn_mean_x, [0.0, 1.0])
        self.assertEqual(ax_seaborn.get_xticks().tolist(), [0.0, 1.0])

        fig_matplotlib, ax_matplotlib = plt.subplots(figsize=(6, 4))
        with mock.patch('modules.export_data_thread._HAS_SEABORN', False):
            render_violin(ax_matplotlib, values, labels)
        matplotlib_mean_x = sorted({float(text.xy[0]) for text in ax_matplotlib.texts if text.get_text().startswith('μ=')})
        self.assertEqual(matplotlib_mean_x, [1.0, 2.0])
        self.assertEqual(ax_matplotlib.get_xticks().tolist(), [1.0, 2.0])

        plt.close(fig_seaborn)
        plt.close(fig_matplotlib)

    def test_group_analysis_plot_asset_filters_labels_with_empty_groups_after_coercion(self):
        metric_row = {
            'metric': 'M1',
            'chart_payload': {
                'groups': [
                    {'group': 'A', 'values': [1.0, 2.0]},
                    {'group': 'DropMe', 'values': ['bad', None, np.inf]},
                    {'group': 'C', 'values': [3.0]},
                ],
            },
        }

        captured_axes = []

        def _stub_violinplot(*, data, ax, **_kwargs):
            captured_axes.append(ax)

        seaborn_stub = types.SimpleNamespace(violinplot=_stub_violinplot)
        with mock.patch('modules.export_data_thread._HAS_SEABORN', True), mock.patch('modules.export_data_thread.sns', seaborn_stub, create=True), mock.patch('modules.export_data_thread.plt.close'):
            asset = ExportDataThread._render_group_analysis_plot_asset(metric_row, 'violin')

        self.assertIn('image_data', asset)
        self.assertEqual(len(captured_axes), 1)

        ax = captured_axes[0]
        labels = [tick.get_text() for tick in ax.get_xticklabels()]
        self.assertEqual(labels, ['A', 'C'])
        self.assertEqual(len(labels), 2)

    def test_group_analysis_histogram_asset_includes_multi_group_legend(self):
        metric_row = {
            'metric': 'M2',
            'chart_payload': {
                'groups': [
                    {'group': 'A', 'values': [1.0, 1.1, 1.2]},
                    {'group': 'B', 'values': [1.3, 1.4, 1.5]},
                    {'group': 'C', 'values': [1.6, 1.7, 1.8]},
                ],
            },
        }

        captured_axes = []
        original_subplots = plt.subplots

        def _capture_subplots(*args, **kwargs):
            fig, ax = original_subplots(*args, **kwargs)
            captured_axes.append(ax)
            return fig, ax

        with mock.patch('modules.export_data_thread.plt.subplots', side_effect=_capture_subplots):
            asset = ExportDataThread._render_group_analysis_plot_asset(metric_row, 'histogram')

        self.assertIn('image_data', asset)
        self.assertEqual(len(captured_axes), 1)
        legend = captured_axes[0].get_legend()
        self.assertIsNotNone(legend)
        labels = [text.get_text() for text in legend.get_texts()]
        self.assertEqual(labels, ['A', 'B', 'C'])


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


    def test_compact_histogram_note_lines_include_only_contextual_fields(self):
        lines = _build_compact_histogram_note_lines(
            {
                'inferred_support_mode': 'one_sided_zero_bound_positive',
                'fit_quality': {'label': 'weak'},
                'gof_metrics': {'reference_normality_label': 'non-normal'},
            }
        )

        self.assertEqual(lines, ['Spec handling: one-sided upper', 'Tooltip: Uses only USL for tail risk and capability decisions (Cp suppressed; Cpk shown as Cpu)', 'Warning: fit weak', 'Help: NOK obs/est gaps can indicate model mismatch, subgroup effects, or insufficient data', 'Help: model fit quality = statistical adequacy of chosen distribution', 'Help: capability status = conformance risk against specs'])
        self.assertFalse(any(line.startswith('Normality:') for line in lines))
        self.assertFalse(any('Model:' in line for line in lines))

    def test_compact_histogram_note_lines_adds_medium_confidence_line(self):
        lines = _build_compact_histogram_note_lines(
            {
                'inferred_support_mode': 'bilateral_signed',
                'fit_quality': {'label': 'medium'},
                'gof_metrics': {'reference_normality_label': 'non-normal'},
            }
        )

        self.assertEqual(lines, ['Spec handling: two-sided (both LSL and USL active)', 'Tooltip: Uses both tails; Cp and Cpk summarize spread and centering versus both limits', 'Fit reliability: medium', 'Tooltip: Fit reliability reflects distribution adequacy; lower reliability increases uncertainty in estimated NOK/PPM', 'Help: NOK obs/est gaps can indicate model mismatch, subgroup effects, or insufficient data', 'Help: model fit quality = statistical adequacy of chosen distribution', 'Help: capability status = conformance risk against specs'])


    def test_compact_histogram_note_lines_downgrades_fit_for_n10(self):
        lines = _build_compact_histogram_note_lines(
            {
                'inferred_support_mode': 'bilateral_signed',
                'fit_quality': {'label': 'good'},
                'gof_metrics': {'reference_normality_label': 'normal'},
            },
            summary_stats={'sample_size': 10},
        )

        self.assertIn('Warning: limited sample size (n=10)', lines)
        self.assertIn('Fit reliability: guarded (n<25)', lines)
        self.assertTrue(any(line.startswith('Rationale:') for line in lines))

    def test_compact_histogram_note_lines_downgrades_fit_for_n20(self):
        lines = _build_compact_histogram_note_lines(
            {
                'inferred_support_mode': 'bilateral_signed',
                'fit_quality': {'label': 'strong'},
                'gof_metrics': {'reference_normality_label': 'normal'},
            },
            summary_stats={'sample_size': 20},
        )

        self.assertIn('Warning: limited sample size (n=20)', lines)
        self.assertIn('Fit reliability: guarded (n<25)', lines)

    def test_compact_histogram_note_lines_keep_default_fit_confidence_for_n50(self):
        lines = _build_compact_histogram_note_lines(
            {
                'inferred_support_mode': 'bilateral_signed',
                'fit_quality': {'label': 'medium'},
                'gof_metrics': {'reference_normality_label': 'non-normal'},
            },
            summary_stats={'sample_size': 50},
        )

        self.assertIn('Fit reliability: medium', lines)
        self.assertFalse(any('limited sample size' in line for line in lines))

    def test_kde_footer_note_uses_bbox_background_for_readability(self):
        fig, ax = plt.subplots(figsize=(6.0, 4.0))
        try:
            artist = ax.text(
                0.02,
                0.02,
                'Dashed KDE: descriptive only',
                transform=ax.transAxes,
                ha='left',
                va='bottom',
                fontsize=6.5,
                color='#4d5968',
                bbox={
                    'boxstyle': 'round,pad=0.16',
                    'facecolor': (1.0, 1.0, 1.0, 0.74),
                    'edgecolor': '#c7ced7',
                    'linewidth': 0.45,
                },
                zorder=8,
            )
            self.assertEqual(artist.get_text(), 'Dashed KDE: descriptive only')
            self.assertIsNotNone(artist.get_bbox_patch())
            self.assertGreaterEqual(artist.get_position()[0], 0.0)
            self.assertGreaterEqual(artist.get_position()[1], 0.0)
        finally:
            plt.close(fig)


    def test_distribution_fit_table_rows_use_small_probability_notation(self):
        rows = _build_distribution_fit_table_rows(
            {
                'gof_metrics': {'ad_pvalue': 0.0004},
                'risk_estimates': {
                    'spec_type': 'upper_only',
                    'above_usl_probability': 0.0000009,
                },
            },
            usl=10.0,
        )

        rows_by_label = dict(rows)
        self.assertEqual(rows_by_label['GOF p'], '<0.001')
        self.assertEqual(rows_by_label['P(>USL)'], '<0.001%')

if __name__ == '__main__':
    unittest.main()

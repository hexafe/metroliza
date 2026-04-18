import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from modules.export_html_dashboard import (
    _build_group_analysis_plotly_spec,
    _build_plotly_chart_spec,
    _build_plotly_chart_spec_bundle,
    _render_overview_cards,
    resolve_html_dashboard_assets_dir,
    resolve_html_dashboard_path,
    write_export_html_dashboard,
)
from modules.export_summary_utils import resolve_histogram_bin_count


class TestExportHtmlDashboard(unittest.TestCase):
    def test_render_overview_cards_formats_generated_as_date_and_time_lines(self):
        html_markup = _render_overview_cards(
            {
                'generated_at': '2026-03-29T18:09:38+02:00',
                'section_count': 3,
                'chart_count': 7,
                'chart_observability_summary': {
                    'chart_backend_distribution': {'counts': {'native': 2, 'matplotlib': 5}},
                },
            }
        )

        self.assertIn('metric-value-line', html_markup)
        self.assertIn('2026-03-29', html_markup)
        self.assertIn('18:09:38', html_markup)
        self.assertNotIn('18:09:38+02:00', html_markup)
        self.assertNotIn('2026-03-29T18:09:38+02:00', html_markup)

    def test_resolve_dashboard_paths_follow_workbook_stem(self):
        html_path = resolve_html_dashboard_path('reports/out.xlsx')
        assets_path = resolve_html_dashboard_assets_dir(html_path)

        self.assertEqual(html_path, Path('reports/out_dashboard.html'))
        self.assertEqual(assets_path, Path('reports/out_dashboard_assets'))

    def test_write_export_html_dashboard_writes_html_and_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_file = Path(tmpdir) / 'report.xlsx'
            html_path = resolve_html_dashboard_path(excel_file)
            assets_dir = resolve_html_dashboard_assets_dir(html_path)

            result = write_export_html_dashboard(
                excel_file=excel_file,
                output_path=html_path,
                assets_dir=assets_dir,
                sections=[
                    {
                        'header': 'Diameter / X',
                        'subtitle': 'Reference R-100',
                        'reference': 'R-100',
                        'axis': 'X',
                        'grouping_applied': True,
                        'sample_size': 8,
                        'limits': {'nominal': 10.0, 'lsl': 9.8, 'usl': 10.2},
                        'metadata_rows': [
                            {'label': 'Part', 'value': 'Carrier Plate'},
                            {'label': 'Revision', 'value': 'B'},
                            {'label': 'Template family', 'value': 'metrology-v2'},
                            {'label': 'Operator', 'value': 'M. Nowak'},
                            {'label': 'Sample kind', 'value': 'production'},
                            {'label': 'Comment', 'value': 'night shift audit'},
                        ],
                        'summary_rows': [('Mean', '10.01'), ('Cpk', '1.42')],
                        'charts': [
                            {
                                'chart_type': 'histogram',
                                'title': 'Diameter / X',
                                'backend': 'native',
                                'image_buffer': BytesIO(b'png-bytes'),
                                'payload': {
                                    'type': 'histogram',
                                    'title': 'Diameter / X',
                                    'values': [9.9, 10.0, 10.1],
                                    'lsl': 9.8,
                                    'usl': 10.2,
                                    'bin_count': 8,
                                    'visual_metadata': {
                                        'annotation_rows': [{'label': 'Mean', 'text': 'Mean = 10.01'}],
                                        'summary_stats_table': {
                                            'rows': [
                                                ('Min', '9.90'),
                                                ('Max', '10.10'),
                                                ('Mean', '10.01'),
                                                ('Median', '10.00'),
                                                ('Std Dev', '0.07'),
                                                ('Cp', '1.31'),
                                                ('Cpk', '1.42'),
                                                ('NOK', '1'),
                                                ('NOK %', '12.50%'),
                                                ('Samples', '8'),
                                            ]
                                        },
                                        'specification_lines': [
                                            {'label': 'LSL', 'value': 9.8, 'enabled': True},
                                            {'label': 'USL', 'value': 10.2, 'enabled': True},
                                        ],
                                        'modeled_overlays': {'rows': [{'kind': 'curve'}, {'kind': 'curve', 'dash': [5, 4]}]},
                                    },
                                },
                                'note': 'Extended histogram',
                            }
                        ],
                    }
                ],
                chart_observability_summary={
                    'chart_backend_distribution': {
                        'counts': {'native': 1, 'matplotlib': 0},
                    },
                },
                backend_diagnostics_lines=['chart_renderer: status=native_available'],
                group_analysis_payload={
                    'status': 'ready',
                    'analysis_level': 'standard',
                    'effective_scope': 'single_reference',
                    'metric_rows': [
                        {
                            'metric': 'FEATURE_1',
                            'reference': 'R-100',
                            'group_count': 2,
                            'spec_status_label': 'Exact match',
                            'analysis_restriction_label': 'Pairwise yes; capability yes',
                            'metric_takeaway': 'Groups differ clearly after correction.',
                            'recommended_action': 'Investigate group B shift.',
                            'diagnostics_comment': 'Analyzed: exact match; pairwise and capability checks enabled.',
                            'metric_flags': 'LOW N',
                            'insights': ['Group B runs higher than group A.'],
                            'plot_eligibility': {
                                'violin': {'eligible': True, 'skip_reason': ''},
                                'histogram': {'eligible': True, 'skip_reason': ''},
                            },
                            'chart_payload': {
                                'groups': [
                                    {'group': 'A', 'values': [9.99, 10.01, 10.02, 10.02]},
                                    {'group': 'B', 'values': [10.08, 10.11, 10.14, 10.16]},
                                ],
                                'spec_limits': {'lsl': 9.8, 'nominal': 10.0, 'usl': 10.2},
                            },
                            'descriptive_stats': [
                                {'group': 'A', 'n': 4, 'mean': 10.01, 'std': 0.02, 'median': 10.01, 'iqr': 0.03, 'min': 9.99, 'max': 10.03, 'cp': 1.3, 'capability': 1.2, 'capability_type': 'Cpk', 'capability_ci': {'cp': None, 'cpk': {'lower': 0.21250516502733194, 'upper': 0.647494834972668}}, 'best_fit_model': 'norm', 'fit_quality': 'good', 'flags': 'none'},
                                {'group': 'B', 'n': 4, 'mean': 10.12, 'std': 0.03, 'median': 10.12, 'iqr': 0.04, 'min': 10.08, 'max': 10.16, 'cp': 1.1, 'capability': 0.95, 'capability_type': 'Cpk', 'best_fit_model': 'lognorm', 'fit_quality': 'medium', 'flags': 'LOW N'},
                            ],
                            'pairwise_rows': [
                                {'group_a': 'A', 'group_b': 'B', 'delta_mean': 0.11, 'adjusted_p_value': 0.0123, 'effect_size': 0.8, 'difference': 'YES', 'comment': 'DIFFERENCE', 'takeaway': 'These groups differ clearly after correction.', 'test_rationale': 'Welch t-test'},
                            ],
                            'distribution_difference': {
                                'comment / verdict': 'clear difference',
                                'Wasserstein distance': 0.21,
                            },
                            'distribution_pairwise_rows': [
                                {'group_a': 'A', 'group_b': 'B', 'Wasserstein distance': 0.21, 'shape difference': 'YES'},
                            ],
                        }
                    ],
                    'diagnostics': {
                        'metric_count': 1,
                        'group_count': 2,
                        'reference_count': 1,
                        'warning_summary': {'count': 1, 'messages': ['FEATURE_1: LOW N']},
                        'histogram_skip_summary': {'applies': True, 'count': 0, 'reason_counts': {}},
                    },
                },
                group_analysis_plot_assets={
                    'metrics': {
                        'FEATURE_1': {
                            'violin': {'image_data': BytesIO(b'violin-bytes'), 'description': 'Violin plot with mean, min, and max annotations.'},
                            'histogram': {'image_data': BytesIO(b'group-hist-bytes'), 'description': 'Histogram with per-group means and capability callout.'},
                        }
                    }
                },
            )

            self.assertEqual(result['html_dashboard_chart_count'], 3)
            self.assertTrue(Path(result['html_dashboard_path']).exists())
            self.assertTrue(Path(result['html_dashboard_assets_path']).exists())

            html_text = Path(result['html_dashboard_path']).read_text(encoding='utf-8')
            self.assertIn('Diameter / X', html_text)
            self.assertIn('Extended histogram', html_text)
            self.assertIn('Report metadata', html_text)
            self.assertIn('Carrier Plate', html_text)
            self.assertIn('metrology-v2', html_text)
            self.assertIn('M. Nowak', html_text)
            self.assertIn('production', html_text)
            self.assertIn('night shift audit', html_text)
            self.assertNotIn(
                '<img src="report_dashboard_assets/section_001_diameter-x_histogram_01.png" alt="Diameter / X"><div class="detail-grid">',
                html_text,
            )
            self.assertIn('chart_renderer: status=native_available', html_text)
            self.assertIn('Group Analysis', html_text)
            self.assertIn('FEATURE_1', html_text)
            self.assertIn('Interactive Plotly view', html_text)
            self.assertIn('plotly-chart', html_text)
            self.assertIn('theme-switch', html_text)
            self.assertIn('report_dashboard_assets/plotly-2.27.0.min.js', html_text)
            self.assertNotIn('cdn.plot.ly/plotly-2.27.0.min.js', html_text)
            self.assertIn('data-theme-choice="auto"', html_text)
            self.assertIn('data-theme-choice="light"', html_text)
            self.assertIn('data-theme-choice="dark"', html_text)
            self.assertIn('metroliza-dashboard-theme', html_text)
            self.assertIn('prefers-color-scheme: dark', html_text)
            self.assertIn('window.Plotly.react', html_text)
            self.assertIn('plotly-expand-trigger', html_text)
            self.assertIn('Increase size', html_text)
            self.assertIn('Enlarge interactive chart: Diameter / X', html_text)
            self.assertIn('<header class="hero" id="dashboard-start">', html_text)
            self.assertIn(
                '<a class="section-chip section-chip--back" href="#dashboard-start" role="button">'
                'Back to dashboard start</a>',
                html_text,
            )
            self.assertIn(
                '<a class="section-chip section-chip--back" href="#group-analysis" role="button">'
                'Back to Group Analysis</a>',
                html_text,
            )
            self.assertIn('<a class="section-chip" href="#group-metric-001">FEATURE_1</a>', html_text)
            self.assertIn('Pairwise comparisons', html_text)
            self.assertIn('Descriptive stats', html_text)
            self.assertNotIn('Capability CI', html_text)
            self.assertNotIn('Cpk: 95% CI 0.213 to 0.647', html_text)
            self.assertIn('<th>Cpk</th>', html_text)
            self.assertIn('chart-lightbox', html_text)
            self.assertIn('chart-lightbox-plotly', html_text)
            self.assertIn("const lightboxPlotly = document.getElementById('chart-lightbox-plotly');", html_text)
            self.assertIn('renderPlotlyContainer(lightboxPlotly', html_text)
            self.assertIn('window.Plotly.purge(lightboxPlotly)', html_text)
            self.assertIn('window.Plotly.Plots.resize(lightboxPlotly)', html_text)
            self.assertIn("document.querySelectorAll('.dragcover').forEach((overlay) => {", html_text)
            self.assertIn("lightbox.addEventListener('close', resetLightboxState);", html_text)
            self.assertIn('chart-image-trigger', html_text)
            self.assertIn('Enlarge chart: Diameter / X', html_text)
            self.assertIn("document.querySelectorAll('.chart-image-trigger').forEach((trigger) => {", html_text)
            self.assertIn('openImageLightbox(source, caption);', html_text)
            self.assertNotIn("const plotlySource = chartCard ? chartCard.querySelector('.plotly-chart') : null;", html_text)
            self.assertNotIn('if (plotlySource && window.Plotly && openPlotlyLightbox(plotlySource, caption)) {', html_text)
            self.assertNotIn('Capability type', html_text)
            self.assertNotIn('"cp": null', html_text)

            asset_files = list(Path(result['html_dashboard_assets_path']).glob('*.png'))
            self.assertEqual(len(asset_files), 3)
            self.assertIn(b'png-bytes', {path.read_bytes() for path in asset_files})
            plotly_asset = Path(result['html_dashboard_assets_path']) / 'plotly-2.27.0.min.js'
            self.assertTrue(plotly_asset.exists())
            self.assertGreater(plotly_asset.stat().st_size, 1_000_000)

    def test_write_export_html_dashboard_falls_back_to_png_only_when_plotly_bundle_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_file = Path(tmpdir) / 'report.xlsx'
            html_path = resolve_html_dashboard_path(excel_file)
            assets_dir = resolve_html_dashboard_assets_dir(html_path)

            with patch(
                'modules.export_html_dashboard._resolve_bundled_plotly_js_path',
                return_value=Path(tmpdir) / 'missing-plotly.min.js',
            ):
                write_export_html_dashboard(
                    excel_file=excel_file,
                    output_path=html_path,
                    assets_dir=assets_dir,
                    sections=[
                        {
                            'header': 'Diameter / X',
                            'charts': [
                                {
                                    'chart_type': 'histogram',
                                    'title': 'Diameter / X',
                                    'backend': 'native',
                                    'image_buffer': BytesIO(b'png-bytes'),
                                    'payload': {
                                        'type': 'histogram',
                                        'values': [9.9, 10.0, 10.1],
                                        'lsl': 9.8,
                                        'usl': 10.2,
                                    },
                                }
                            ],
                        }
                    ],
                )

            html_text = html_path.read_text(encoding='utf-8')
            self.assertNotIn('<div class="plotly-shell">', html_text)
            self.assertNotIn('class="plotly-expand-trigger"', html_text)
            self.assertNotIn('data-plotly-spec-light=', html_text)
            self.assertNotIn('data-plotly-spec-dark=', html_text)
            self.assertIn('Interactive Plotly views were unavailable in this export', html_text)
            self.assertFalse((assets_dir / 'plotly-2.27.0.min.js').exists())

    def test_plotly_chart_spec_bundle_exposes_light_and_dark_variants(self):
        bundle = _build_plotly_chart_spec_bundle(
            {
                'type': 'histogram',
                'values': [9.9, 10.0, 10.1, 10.2],
                'limits': {'lsl': 9.8, 'nominal': 10.0, 'usl': 10.2},
            },
            title='Diameter / X',
        )

        self.assertIn('light', bundle)
        self.assertIn('dark', bundle)
        self.assertEqual(bundle['light']['layout']['font']['color'], '#162330')
        self.assertEqual(bundle['dark']['layout']['font']['color'], '#edf3fb')
        self.assertNotEqual(bundle['light']['layout']['colorway'], bundle['dark']['layout']['colorway'])

    def test_group_analysis_histogram_plotly_spec_uses_shared_bins_for_overlay(self):
        all_values = [9.99, 10.01, 10.02, 10.03, 10.08, 10.11, 10.14, 10.16]
        spec = _build_group_analysis_plotly_spec(
            'FEATURE_1',
            'histogram',
            {
                'groups': [
                    {'group': 'A', 'values': [9.99, 10.01, 10.02, 10.03]},
                    {'group': 'B', 'values': [10.08, 10.11, 10.14, 10.16]},
                ],
                'spec_limits': {'lsl': 9.8, 'nominal': 10.0, 'usl': 10.2},
            },
        )

        self.assertEqual(spec['layout']['barmode'], 'overlay')
        self.assertEqual(spec['layout']['hovermode'], 'x unified')
        self.assertEqual(len(spec['data']), 2)
        self.assertEqual(spec['data'][0]['bingroup'], spec['data'][1]['bingroup'])
        self.assertEqual(spec['data'][0]['xbins'], spec['data'][1]['xbins'])
        expected_bin_count = resolve_histogram_bin_count(all_values)['bin_count']
        expected_bin_width = (max(all_values) - min(all_values)) / expected_bin_count
        self.assertAlmostEqual(spec['data'][0]['xbins']['size'], expected_bin_width)

    def test_summary_histogram_plotly_spec_uses_matplotlib_bin_range(self):
        values = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
        spec = _build_plotly_chart_spec(
            {
                'type': 'histogram',
                'values': values,
                'bin_count': 5,
                'x_view': {'min': -5.0, 'max': 15.0},
            },
            title='Summary Histogram',
        )

        bins = spec['data'][0]['xbins']
        self.assertEqual(bins['start'], -5.0)
        self.assertEqual(bins['end'], 15.0)
        self.assertEqual(bins['size'], 4.0)
        self.assertEqual(spec['layout']['xaxis']['range'], [-5.0, 15.0])

    def test_trend_plotly_spec_sorts_points_and_renders_markers_only(self):
        spec = _build_plotly_chart_spec(
            {
                'type': 'trend',
                'x_values': [3, 1, 2],
                'y_values': [30.0, 10.0, 20.0],
                'labels': ['third', 'first', 'second'],
                'horizontal_limits': [25.0],
            },
            title='Trend',
        )

        self.assertEqual(spec['layout']['hovermode'], 'x unified')
        self.assertEqual(spec['data'][0]['x'], [1.0, 2.0, 3.0])
        self.assertEqual(spec['data'][0]['y'], [10.0, 20.0, 30.0])
        self.assertEqual(spec['data'][0]['customdata'], ['first', 'second', 'third'])
        self.assertEqual(spec['data'][0]['mode'], 'markers')
        self.assertNotIn('line', spec['data'][0])


if __name__ == '__main__':
    unittest.main()

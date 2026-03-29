import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from modules.export_html_dashboard import (
    _render_overview_cards,
    resolve_html_dashboard_assets_dir,
    resolve_html_dashboard_path,
    write_export_html_dashboard,
)


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
        self.assertIn('18:09:38+02:00', html_markup)
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
            self.assertIn('detail-cards', html_text)
            self.assertIn('detail-card-label', html_text)
            self.assertIn('detail-card-value', html_text)
            self.assertIn('Mean = 10.01', html_text)
            self.assertIn('Selected model curve', html_text)
            self.assertIn('KDE reference (dashed)', html_text)
            self.assertIn('chart_renderer: status=native_available', html_text)
            self.assertIn('Group Analysis', html_text)
            self.assertIn('FEATURE_1', html_text)
            self.assertIn('Pairwise comparisons', html_text)
            self.assertIn('Descriptive stats', html_text)
            self.assertIn('Capability CI', html_text)
            self.assertIn('Cpk: 95% CI 0.213 to 0.647', html_text)
            self.assertIn('<th>Cpk</th>', html_text)
            self.assertNotIn('Capability type', html_text)
            self.assertNotIn('"cp": null', html_text)

            asset_files = list(Path(result['html_dashboard_assets_path']).glob('*.png'))
            self.assertEqual(len(asset_files), 3)
            self.assertIn(b'png-bytes', {path.read_bytes() for path in asset_files})


if __name__ == '__main__':
    unittest.main()

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from modules.export_html_dashboard import (
    resolve_html_dashboard_assets_dir,
    resolve_html_dashboard_path,
    write_export_html_dashboard,
)


class TestExportHtmlDashboard(unittest.TestCase):
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
                                        'annotation_rows': [{'text': 'Mean'}],
                                        'summary_stats_table': {'rows': [('Mean', '10.01')]},
                                        'modeled_overlays': {'rows': [{'label': 'Normal'}]},
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
            )

            self.assertEqual(result['html_dashboard_chart_count'], 1)
            self.assertTrue(Path(result['html_dashboard_path']).exists())
            self.assertTrue(Path(result['html_dashboard_assets_path']).exists())

            html_text = Path(result['html_dashboard_path']).read_text(encoding='utf-8')
            self.assertIn('Diameter / X', html_text)
            self.assertIn('Extended histogram', html_text)
            self.assertIn('chart_renderer: status=native_available', html_text)

            asset_files = list(Path(result['html_dashboard_assets_path']).glob('*.png'))
            self.assertEqual(len(asset_files), 1)
            self.assertEqual(asset_files[0].read_bytes(), b'png-bytes')


if __name__ == '__main__':
    unittest.main()

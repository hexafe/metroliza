import time
import unittest

import pandas as pd

from modules.export_sheet_writer import (
    build_measurement_header_block_plan,
    build_measurement_summary_row_layout,
    build_measurement_write_bundle,
    build_measurement_write_bundle_cached,
    build_summary_panel_write_plan,
    write_measurement_block,
    write_measurement_summary_rows,
)


class DummyWorksheet:
    def __init__(self):
        self.writes = []
        self.formulas = []
        self.columns = []
        self.conditional_formats = []

    def write(self, row, col, value, *args, **kwargs):
        self.writes.append((row, col, value))

    def write_formula(self, row, col, formula, *args, **kwargs):
        self.formulas.append((row, col, formula))

    def write_column(self, row, col, values):
        self.columns.append((row, col, list(values)))

    def conditional_format(self, *args):
        self.conditional_formats.append(args)


class TestExportSheetWriter(unittest.TestCase):
    def test_build_measurement_write_bundle_includes_limit_columns_contract(self):
        header_group = pd.DataFrame(
            {
                'DATE': ['2024-01-01', '2024-01-02', '2024-01-03'],
                'SAMPLE_NUMBER': ['1', '2', '3'],
                'MEAS': [10.1, 10.2, 10.3],
                'NOM': [10.0, 10.0, 10.0],
                '+TOL': [0.5, 0.5, 0.5],
                '-TOL': [-0.5, -0.5, -0.5],
            }
        )

        bundle = build_measurement_write_bundle('Diameter - X', header_group, 0)

        labels = [column[2] for column in bundle['data_columns']]
        self.assertEqual(labels, ['Date', 'Sample #', 'Diameter - X', 'USL', 'LSL'])

        usl_values = bundle['data_columns'][3][3]
        lsl_values = bundle['data_columns'][4][3]
        self.assertEqual(usl_values, [10.5, 10.5, 10.5])
        self.assertEqual(lsl_values, [9.5, 9.5, 9.5])
        self.assertTrue(all(value is not None for value in usl_values))
        self.assertTrue(all(value is not None for value in lsl_values))

        measurement_plan = bundle['measurement_plan']
        self.assertIn('usl_column', measurement_plan)
        self.assertIn('lsl_column', measurement_plan)

    def test_write_measurement_block_applies_three_conditional_rules(self):
        header_group = pd.DataFrame(
            {
                'DATE': ['2024-01-01', '2024-01-02'],
                'SAMPLE_NUMBER': ['1', '2'],
                'MEAS': [10.1, 10.2],
                'NOM': [10.0, 10.0],
                '+TOL': [0.5, 0.5],
                '-TOL': [-0.5, -0.5],
            }
        )
        bundle = build_measurement_write_bundle('Diameter - X', header_group, 0)
        worksheet = DummyWorksheet()
        formats = {'percent': object(), 'wrap': object(), 'red': object()}

        measurement_plan = write_measurement_block(worksheet, bundle, formats, base_col=0)

        self.assertEqual(measurement_plan['data_start_row'], 21)
        self.assertEqual(len(worksheet.conditional_formats), 3)
        self.assertTrue(any(w[2] == 'NOK %' for w in worksheet.writes if isinstance(w[2], str)))
        self.assertTrue(any((w[0], w[1], w[2]) == (0, 2, 'MIN') for w in worksheet.writes))


    def test_build_measurement_summary_row_layout_keeps_legacy_coordinates(self):
        stat_rows = [
            ('MIN', '=MIN(C22:C30)', None),
            ('NOK %', '=10%', 'percent'),
        ]

        layout = build_measurement_summary_row_layout(base_col=6, stat_rows=stat_rows)

        self.assertEqual(layout[0]['row'], 3)
        self.assertEqual(layout[0]['label_col'], 6)
        self.assertEqual(layout[0]['value_col'], 7)
        self.assertEqual(layout[1]['row'], 4)
        self.assertEqual(layout[1]['style'], 'percent')

    def test_write_measurement_summary_rows_writes_formula_and_percent_style(self):
        worksheet = DummyWorksheet()
        summary_rows = [
            {'row': 3, 'label_col': 0, 'value_col': 1, 'label': 'MIN', 'formula': '=MIN(C22:C30)', 'style': None},
            {'row': 4, 'label_col': 0, 'value_col': 1, 'label': 'NOK %', 'formula': '=10%', 'style': 'percent'},
        ]

        write_measurement_summary_rows(worksheet, summary_rows, formats={'percent': object()})

        self.assertIn((3, 0, 'MIN'), worksheet.writes)
        self.assertIn((4, 0, 'NOK %'), worksheet.writes)
        self.assertEqual(worksheet.formulas[0], (3, 1, '=MIN(C22:C30)'))
        self.assertEqual(worksheet.formulas[1], (4, 1, '=10%'))


    def test_build_summary_panel_write_plan_maps_header_and_image_slots(self):
        anchors = {
            'header': (40, 0),
            'distribution': (41, 1),
            'iqr': (41, 10),
            'histogram': (41, 19),
            'trend': (41, 29),
        }

        plan = build_summary_panel_write_plan(anchors, 'DIA - X')

        self.assertEqual(plan['header_cell'], {'row': 40, 'col': 0, 'value': 'DIA - X'})
        self.assertEqual(plan['image_slots']['distribution'], {'row': 41, 'col': 1})
        self.assertEqual(plan['image_slots']['iqr'], {'row': 41, 'col': 10})
        self.assertEqual(plan['image_slots']['histogram'], {'row': 41, 'col': 19})
        self.assertEqual(plan['image_slots']['trend'], {'row': 41, 'col': 29})


    def test_cached_write_bundle_matches_uncached_contract(self):
        header_group = pd.DataFrame(
            {
                'DATE': ['2024-01-01', '2024-01-02'],
                'SAMPLE_NUMBER': ['1', '2'],
                'MEAS': [10.1, 10.2],
                'NOM': [10.0, 10.0],
                '+TOL': [0.5, 0.5],
                '-TOL': [-0.5, -0.5],
            }
        )

        uncached = build_measurement_write_bundle('Diameter - X', header_group, 0)
        cache = {}
        cached = build_measurement_write_bundle_cached('Diameter - X', header_group, 0, cache=cache)

        self.assertEqual(cached['static_rows'], uncached['static_rows'])
        self.assertEqual(cached['header_plan']['stat_rows'], uncached['header_plan']['stat_rows'])
        self.assertEqual(cached['measurement_plan'], uncached['measurement_plan'])
        self.assertIn('usl_column', cached['measurement_plan'])
        self.assertIn('lsl_column', cached['measurement_plan'])

    def test_debug_timing_cached_header_plan_path_runs(self):
        header_group = pd.DataFrame(
            {
                'DATE': ['2024-01-01', '2024-01-02'],
                'SAMPLE_NUMBER': ['1', '2'],
                'MEAS': [10.1, 10.2],
                'NOM': [10.0, 10.0],
                '+TOL': [0.5, 0.5],
                '-TOL': [-0.5, -0.5],
            }
        )

        iterations = 1200
        uncached_start = time.perf_counter()
        for _ in range(iterations):
            build_measurement_header_block_plan(header_group, 0)
        uncached_elapsed = time.perf_counter() - uncached_start

        cache = {}
        cached_start = time.perf_counter()
        for _ in range(iterations):
            build_measurement_header_block_plan(header_group, 0, cache=cache)
        cached_elapsed = time.perf_counter() - cached_start

        self.assertGreater(uncached_elapsed, 0.0)
        self.assertGreater(cached_elapsed, 0.0)
        self.assertEqual(len(cache.get('measurement_block_templates', {})), 1)


if __name__ == '__main__':
    unittest.main()

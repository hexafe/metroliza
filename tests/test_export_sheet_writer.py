import unittest

import pandas as pd

from modules.export_sheet_writer import (
    build_measurement_summary_row_layout,
    build_measurement_write_bundle,
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


if __name__ == '__main__':
    unittest.main()

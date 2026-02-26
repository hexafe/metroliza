import unittest

import pandas as pd

from modules.export_sheet_writer import build_measurement_write_bundle, write_measurement_block


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


if __name__ == '__main__':
    unittest.main()

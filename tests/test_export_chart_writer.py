import unittest

from modules.export_chart_writer import (
    build_measurement_chart_series_specs,
    build_measurement_chart_series_specs_from_plan,
    insert_measurement_chart,
)


class DummyChart:
    def __init__(self):
        self.series = []
        self.title = None

    def add_series(self, spec):
        self.series.append(spec)

    def set_title(self, title):
        self.title = title

    def set_y_axis(self, _):
        return None

    def set_legend(self, _):
        return None

    def set_size(self, _):
        return None


class DummyWorkbook:
    def __init__(self):
        self.chart = DummyChart()

    def add_chart(self, spec):
        self.spec = spec
        return self.chart


class DummyWorksheet:
    def __init__(self):
        self.insert_calls = []

    def insert_chart(self, row, col, chart):
        self.insert_calls.append((row, col, chart))


class TestExportChartWriter(unittest.TestCase):
    def test_series_specs_include_limits(self):
        specs = build_measurement_chart_series_specs(
            header='H',
            sheet_name='Ref',
            first_data_row=21,
            last_data_row=30,
            x_column=1,
            y_column=2,
        )
        self.assertEqual(len(specs), 3)
        self.assertEqual(specs[1]['name'], 'USL')
        self.assertEqual(specs[2]['name'], 'LSL')

    def test_insert_measurement_chart_wires_series_and_anchor(self):
        workbook = DummyWorkbook()
        worksheet = DummyWorksheet()
        plan = {'data_start_row': 21, 'last_data_row': 25, 'summary_column': 1, 'y_column': 2, 'chart_insert_row': 12}

        insert_measurement_chart(
            workbook,
            worksheet,
            chart_type='scatter',
            header='H',
            sheet_name='Ref',
            measurement_plan=plan,
            chart_anchor_col=3,
        )

        self.assertEqual(workbook.spec['type'], 'scatter')
        self.assertEqual(len(workbook.chart.series), 3)
        self.assertEqual(worksheet.insert_calls[0][0:2], (12, 3))

    def test_series_specs_from_plan_matches_direct_builder(self):
        plan = {
            'data_start_row': 21,
            'last_data_row': 30,
            'summary_column': 1,
            'y_column': 2,
        }

        from_plan = build_measurement_chart_series_specs_from_plan(
            header='H',
            sheet_name='Ref',
            measurement_plan=plan,
        )
        direct = build_measurement_chart_series_specs(
            header='H',
            sheet_name='Ref',
            first_data_row=21,
            last_data_row=30,
            x_column=1,
            y_column=2,
        )

        self.assertEqual(from_plan, direct)
        self.assertEqual(from_plan[0]['categories'], '=Ref!$B22:B31')
        self.assertEqual(from_plan[0]['values'], '=Ref!$C22:C31')


if __name__ == '__main__':
    unittest.main()

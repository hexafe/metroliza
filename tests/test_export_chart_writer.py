import time
import unittest

from modules.export_chart_writer import (
    CHART_HEIGHT_CM,
    CHART_WIDTH_CM,
    DEFAULT_CHART_ANCHOR_ROW,
    build_horizontal_limit_line_specs,
    build_measurement_chart_format_policy,
    build_measurement_chart_range_specs,
    build_measurement_chart_series_specs,
    build_measurement_chart_series_specs_from_plan,
    insert_measurement_chart,
)


class DummyChart:
    def __init__(self):
        self.series = []
        self.title = None
        self.size = None
        self.legend = None

    def add_series(self, spec):
        self.series.append(spec)

    def set_title(self, title):
        self.title = title

    def set_y_axis(self, _):
        return None

    def set_legend(self, legend):
        self.legend = legend

    def set_size(self, size):
        self.size = size


class DummyWorkbook:
    def __init__(self):
        self.chart = DummyChart()

    def add_chart(self, spec):
        self.spec = spec
        return self.chart


class DummyWorksheet:
    def __init__(self):
        self.insert_calls = []
        self.formulas = []
        self.columns = []
        self.name = 'Ref'

    def write_formula(self, row, col, formula):
        self.formulas.append((row, col, formula))

    def set_column(self, first_col, last_col, width=None, cell_format=None, options=None):
        self.columns.append((first_col, last_col, width, cell_format, options))

    def insert_chart(self, row, col, chart, options=None):
        self.insert_calls.append((row, col, chart, options or {}))


class TestExportChartWriter(unittest.TestCase):
    def test_build_horizontal_limit_line_specs_is_deterministic(self):
        specs = build_horizontal_limit_line_specs(10.5, 9.8)

        self.assertEqual(
            specs,
            [
                {'y': 10.5, 'color': '#9b1c1c', 'linestyle': '--', 'linewidth': 1.0},
                {'y': 9.8, 'color': '#9b1c1c', 'linestyle': '--', 'linewidth': 1.0},
            ],
        )

        custom = build_horizontal_limit_line_specs(5.0, 4.0, color='blue', linestyle=':', linewidth=2.5)
        self.assertEqual(custom[0]['color'], 'blue')
        self.assertEqual(custom[1]['linestyle'], ':')
        self.assertEqual(custom[1]['linewidth'], 2.5)

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
        self.assertEqual(specs[1]['categories'], '=Ref!$B22:B31')
        self.assertEqual(specs[1]['line']['color'], '#c0504b')
        self.assertEqual(specs[1]['line']['width'], 2)
        self.assertEqual(specs[1]['line']['transparency'], 40)
        self.assertEqual(specs[2]['name'], 'LSL')
        self.assertEqual(specs[2]['categories'], '=Ref!$B22:B31')
        self.assertEqual(specs[2]['line']['color'], '#c0504b')
        self.assertEqual(specs[2]['line']['width'], 2)
        self.assertEqual(specs[2]['line']['transparency'], 40)
        self.assertEqual(specs[1]['line'], specs[2]['line'])


    def test_chart_size_policy_uses_updated_cm_dimensions(self):
        policy = build_measurement_chart_format_policy('H')

        self.assertEqual(CHART_WIDTH_CM, 11.09)
        self.assertEqual(CHART_HEIGHT_CM, 6.35)
        self.assertEqual(policy['size'], {'width': 419, 'height': 240})

    def test_insert_measurement_chart_wires_series_and_anchor(self):
        workbook = DummyWorkbook()
        worksheet = DummyWorksheet()
        plan = {
            'data_start_row': 21,
            'last_data_row': 25,
            'summary_column': 1,
            'y_column': 2,
            'usl_column': 3,
            'lsl_column': 4,
            'chart_insert_row': 7,
        }

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
        self.assertEqual(worksheet.insert_calls[0][0:2], (7, 3))
        self.assertEqual(worksheet.insert_calls[0][3], {'x_offset': 0, 'y_offset': 0})
        self.assertEqual(workbook.chart.series[1]['categories'], '=Ref!$B22:B26')
        self.assertEqual(workbook.chart.series[1]['values'], '=Ref!$D22:D26')
        self.assertEqual(workbook.chart.series[2]['categories'], '=Ref!$B22:B26')
        self.assertEqual(workbook.chart.series[2]['values'], '=Ref!$E22:E26')
        self.assertEqual(workbook.chart.size, {'width': 419, 'height': 240})

    def test_series_specs_from_plan_matches_direct_builder(self):
        plan = {
            'data_start_row': 21,
            'last_data_row': 30,
            'summary_column': 1,
            'y_column': 2,
            'usl_column': 3,
            'lsl_column': 4,
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
            usl_column=3,
            lsl_column=4,
        )

        self.assertEqual(from_plan, direct)
        self.assertEqual(from_plan[0]['categories'], '=Ref!$B22:B31')
        self.assertEqual(from_plan[0]['values'], '=Ref!$C22:C31')
        self.assertEqual(from_plan[1]['categories'], '=Ref!$B22:B31')
        self.assertEqual(from_plan[1]['values'], '=Ref!$D22:D31')
        self.assertEqual(from_plan[2]['categories'], '=Ref!$B22:B31')
        self.assertEqual(from_plan[2]['values'], '=Ref!$E22:E31')

    def test_cached_series_specs_match_uncached_output(self):
        args = {
            'header': 'H',
            'sheet_name': 'Ref',
            'first_data_row': 21,
            'last_data_row': 30,
            'x_column': 1,
            'y_column': 2,
        }

        uncached = build_measurement_chart_series_specs(**args)
        cache = {}
        cached_first = build_measurement_chart_series_specs(**args, cache=cache)
        cached_second = build_measurement_chart_series_specs(**args, cache=cache)

        self.assertEqual(cached_first, uncached)
        self.assertEqual(cached_second, uncached)

        range_specs = build_measurement_chart_range_specs(
            sheet_name='Ref',
            first_data_row=21,
            last_data_row=30,
            x_column=1,
            y_column=2,
            cache=cache,
        )
        self.assertEqual(range_specs['data_x'], '=Ref!$B22:B31')

    def test_range_specs_use_limit_columns_when_provided(self):
        range_specs = build_measurement_chart_range_specs(
            sheet_name='Ref',
            first_data_row=21,
            last_data_row=30,
            x_column=1,
            y_column=2,
            usl_column=3,
            lsl_column=4,
        )

        self.assertEqual(range_specs['usl_x'], '=Ref!$B22:B31')
        self.assertEqual(range_specs['usl_y'], '=Ref!$D22:D31')
        self.assertEqual(range_specs['lsl_x'], '=Ref!$B22:B31')
        self.assertEqual(range_specs['lsl_y'], '=Ref!$E22:E31')
        self.assertNotIn('limit_x', range_specs)

    def test_debug_timing_cached_range_builder_path_runs(self):
        iterations = 1500

        uncached_start = time.perf_counter()
        for _ in range(iterations):
            build_measurement_chart_range_specs(
                sheet_name='Ref',
                first_data_row=21,
                last_data_row=30,
                x_column=1,
                y_column=2,
            )
        uncached_elapsed = time.perf_counter() - uncached_start

        cache = {}
        cached_start = time.perf_counter()
        for _ in range(iterations):
            build_measurement_chart_range_specs(
                sheet_name='Ref',
                first_data_row=21,
                last_data_row=30,
                x_column=1,
                y_column=2,
                cache=cache,
            )
        cached_elapsed = time.perf_counter() - cached_start

        self.assertGreater(uncached_elapsed, 0.0)
        self.assertGreater(cached_elapsed, 0.0)
        self.assertEqual(len(cache.get('range_specs', {})), 1)

    def test_chart_format_policy_uses_default_anchor_and_hides_single_series_legend(self):
        policy = build_measurement_chart_format_policy('H')

        self.assertEqual(policy['anchor']['row'], DEFAULT_CHART_ANCHOR_ROW)
        self.assertEqual(policy['legend'], {'position': 'none'})
        self.assertEqual(policy['anchor']['x_offset'], 0)
        self.assertEqual(policy['anchor']['y_offset'], 0)

    def test_insert_measurement_chart_uses_legacy_anchor_row_and_hidden_legend_policy(self):
        workbook = DummyWorkbook()
        worksheet = DummyWorksheet()
        plan = {
            'data_start_row': 10,
            'last_data_row': 14,
            'summary_column': 1,
            'y_column': 2,
            'usl_column': 3,
            'lsl_column': 4,
            'chart_insert_row': 7,
        }

        insert_measurement_chart(
            workbook,
            worksheet,
            chart_type='scatter',
            header='Stable Export',
            sheet_name='Ref',
            measurement_plan=plan,
            chart_anchor_col=5,
        )

        self.assertEqual(worksheet.insert_calls[0][0:2], (7, 5))
        self.assertEqual(workbook.chart.legend, {'position': 'none'})
        self.assertEqual(workbook.chart.title, {'name': 'Stable Export', 'name_font': {'size': 10}})

    def test_existing_measurement_chart_export_ranges_remain_unchanged_without_custom_anchor(self):
        workbook = DummyWorkbook()
        worksheet = DummyWorksheet()
        plan = {
            'data_start_row': 21,
            'last_data_row': 25,
            'summary_column': 1,
            'y_column': 2,
            'usl_column': 3,
            'lsl_column': 4,
        }

        insert_measurement_chart(
            workbook,
            worksheet,
            chart_type='scatter',
            header='Baseline',
            sheet_name='Ref',
            measurement_plan=plan,
            chart_anchor_col=2,
        )

        self.assertEqual(worksheet.insert_calls[0][0:2], (DEFAULT_CHART_ANCHOR_ROW, 2))
        self.assertEqual(workbook.chart.legend, {'position': 'none'})
        self.assertEqual(workbook.chart.series[0]['categories'], '=Ref!$B22:B26')
        self.assertEqual(workbook.chart.series[0]['values'], '=Ref!$C22:C26')
        self.assertEqual(workbook.chart.series[1]['values'], '=Ref!$D22:D26')
        self.assertEqual(workbook.chart.series[2]['values'], '=Ref!$E22:E26')

    def test_chart_format_policy_enables_legend_for_multiple_series(self):
        policy = build_measurement_chart_format_policy('H', chart_anchor_row=15, legend_series_count=3)

        self.assertEqual(policy['anchor']['row'], 15)
        self.assertEqual(policy['legend'], {'position': 'bottom'})


if __name__ == '__main__':
    unittest.main()

import sys
import types
import unittest


# Minimal stubs for optional runtime dependencies used by ExportDataThread imports.
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
    all_measurements_within_limits,
    build_spec_limit_anchor_rows,
    build_sheet_series_range,
    build_summary_sheet_position_plan,
    build_histogram_table_data,
    build_sparse_unique_labels,
    build_trend_plot_payload,
)


class TestExportThreadLabelHelpers(unittest.TestCase):
    def test_build_sparse_unique_labels_blanks_repeated_values(self):
        labels = ['1', '1', '2', '2', '2', '3']

        result = build_sparse_unique_labels(labels)

        self.assertEqual(result, ['1', '', '2', '', '', '3'])

    def test_build_sparse_unique_labels_keeps_first_occurrence_order(self):
        labels = ['A', 'B', 'A', 'C', 'B']

        result = build_sparse_unique_labels(labels)

        self.assertEqual(result, ['A', 'B', '', 'C', ''])


class TestExportThreadToleranceHelpers(unittest.TestCase):
    def test_all_measurements_within_limits_true_when_all_values_in_range(self):
        self.assertTrue(all_measurements_within_limits([1.0, 1.1, 0.9], 0.8, 1.2))

    def test_all_measurements_within_limits_false_when_any_value_out_of_range(self):
        self.assertFalse(all_measurements_within_limits([1.0, 1.5, 0.9], 0.8, 1.2))



class TestExportThreadSummaryPayloadHelpers(unittest.TestCase):
    def test_build_spec_limit_anchor_rows_builds_expected_labels_and_values(self):
        rows = build_spec_limit_anchor_rows(usl=1.2, lsl=0.8)

        self.assertEqual(
            rows,
            [
                ('USL_MAX', 1.2),
                ('USL_MIN', 1.2),
                ('LSL_MAX', 0.8),
                ('LSL_MIN', 0.8),
            ],
        )

    def test_build_sheet_series_range_uses_absolute_excel_range(self):
        series_range = build_sheet_series_range('REF_A', 21, 30, 2)

        self.assertEqual(series_range, '=REF_A!$C22:C31')

    def test_build_histogram_table_data_rounds_numeric_values(self):
        summary_stats = {
            'minimum': 1.23456,
            'maximum': 9.87654,
            'average': 5.55555,
            'median': 5.5,
            'sigma': 0.12345,
            'cp': 1.9876,
            'cpk': 1.4321,
            'sample_size': 12,
            'nok_count': 1,
            'nok_pct': 8.3333,
        }

        table = build_histogram_table_data(summary_stats)

        self.assertEqual(table[0], ('Min', 1.235))
        self.assertEqual(table[5], ('Cp', 1.99))
        self.assertEqual(table[6], ('Cpk', 1.43))
        self.assertEqual(table[-1], ('NOK %', 8.33))

    def test_build_histogram_table_data_preserves_na_text_for_cp_fields(self):
        summary_stats = {
            'minimum': 0.0,
            'maximum': 0.0,
            'average': 0.0,
            'median': 0.0,
            'sigma': 0.0,
            'cp': 'N/A',
            'cpk': 'N/A',
            'sample_size': 1,
            'nok_count': 0,
            'nok_pct': 0.0,
        }

        table = build_histogram_table_data(summary_stats)

        self.assertEqual(table[5], ('Cp', 'N/A'))
        self.assertEqual(table[6], ('Cpk', 'N/A'))

    def test_build_trend_plot_payload_builds_dense_x_and_sparse_labels(self):
        import pandas as pd

        header_group = pd.DataFrame({
            'MEAS': [1.0, 1.1, 1.2, 1.3],
            'SAMPLE_NUMBER': ['1', '1', '2', '2'],
        })

        payload = build_trend_plot_payload(header_group)

        self.assertEqual(payload['x'], [0, 1, 2, 3])
        self.assertEqual(payload['y'], [1.0, 1.1, 1.2, 1.3])
        self.assertEqual(payload['labels'], ['1', '', '2', ''])

    def test_build_summary_sheet_position_plan_matches_existing_column_block_math(self):
        first_block = build_summary_sheet_position_plan(3)
        second_block = build_summary_sheet_position_plan(6)

        self.assertEqual(first_block['row'], 0)
        self.assertEqual(first_block['header_row'], 0)
        self.assertEqual(first_block['image_row'], 1)
        self.assertEqual(second_block['row'], 20)
        self.assertEqual(second_block['header_row'], 20)
        self.assertEqual(second_block['image_row'], 21)


class TestExportThreadProgressLabelFormatting(unittest.TestCase):
    def test_measurement_label_uses_three_rows_with_eta_placeholder_early(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest
        from modules.ExportDataThread import ExportDataThread

        request = ExportRequest(paths=AppPaths(db_file='db', excel_file='out.xlsx'), options=ExportOptions())
        thread = ExportDataThread(request)

        import modules.ExportDataThread as export_module
        previous_perf_counter = export_module.time.perf_counter
        export_module.time.perf_counter = lambda: 1.0
        try:
            label = thread._build_measurement_label(
                ref_index=1,
                total_references=2,
                completed_header_units=1,
                total_header_units=10,
                start_time=0.0,
            )
        finally:
            export_module.time.perf_counter = previous_perf_counter

        lines = label.split('\n')
        self.assertEqual(lines[0], 'Building measurement sheets...')
        self.assertIn('Ref 1/2', lines[1])
        self.assertIn('Headers remaining 9/10', lines[1])
        self.assertEqual(lines[2], 'ETA --')

    def test_measurement_label_uses_three_rows_with_eta_and_elapsed(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest
        from modules.ExportDataThread import ExportDataThread

        request = ExportRequest(paths=AppPaths(db_file='db', excel_file='out.xlsx'), options=ExportOptions())
        thread = ExportDataThread(request)

        import modules.ExportDataThread as export_module
        previous_perf_counter = export_module.time.perf_counter
        export_module.time.perf_counter = lambda: 10.0
        try:
            label = thread._build_measurement_label(
                ref_index=2,
                total_references=2,
                completed_header_units=5,
                total_header_units=10,
                start_time=0.0,
            )
        finally:
            export_module.time.perf_counter = previous_perf_counter

        lines = label.split('\n')
        self.assertEqual(lines[0], 'Building measurement sheets...')
        self.assertIn('Ref 2/2', lines[1])
        self.assertIn('Headers remaining 5/10', lines[1])
        self.assertIn('elapsed, ETA', lines[2])

if __name__ == '__main__':
    unittest.main()

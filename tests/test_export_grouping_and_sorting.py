import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd
import numpy as np


# Test-only stubs to avoid importing GUI/system libraries in headless environments.
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

from modules.ExportDataThread import ExportDataThread
from modules.contracts import AppPaths, ExportOptions, ExportRequest


class TestExportSortingAndGrouping(unittest.TestCase):

    def test_constructor_accepts_export_request_contract(self):
        request = ExportRequest(
            paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'),
            options=ExportOptions(export_type='LINE', sorting_parameter='Sample #', violin_plot_min_samplesize=1),
        )

        thread = ExportDataThread(export_request=request)

        self.assertEqual(thread.db_file, ':memory:')
        self.assertEqual(thread.selected_export_type, 'line')
        self.assertEqual(thread.selected_sorting_parameter, 'sample #')
        self.assertEqual(thread.violin_plot_min_samplesize, 2)
    def test_sort_by_sample_number_uses_numeric_order(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions(sorting_parameter='Part number')))
        header_group = pd.DataFrame(
            {
                'SAMPLE_NUMBER': ['10', '2', '1'],
                'DATE': ['2024-01-03', '2024-01-02', '2024-01-01'],
                'MEAS': [1.0, 1.1, 0.9],
            }
        )

        sorted_group = thread._sort_header_group(header_group)

        self.assertEqual(sorted_group['SAMPLE_NUMBER'].tolist(), ['1', '2', '10'])

    def test_sort_by_date_falls_back_to_sample_for_ties(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions(sorting_parameter='Date')))
        header_group = pd.DataFrame(
            {
                'SAMPLE_NUMBER': ['2', '1', '3'],
                'DATE': ['2024-01-02', '2024-01-02', '2024-01-01'],
                'MEAS': [1.0, 1.1, 0.9],
            }
        )

        sorted_group = thread._sort_header_group(header_group)

        self.assertEqual(sorted_group['SAMPLE_NUMBER'].tolist(), ['3', '1', '2'])

    def test_prepare_grouping_df_adds_group_key_for_composite_identity(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions()))
        thread.df_for_grouping = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1'],
                'FILELOC': ['/a', '/b'],
                'FILENAME': ['x.pdf', 'y.pdf'],
                'DATE': ['2024-01-01', '2024-01-01'],
                'SAMPLE_NUMBER': ['001', '001'],
                'GROUP': ['A', 'B'],
            }
        )

        grouping_df = thread._prepare_grouping_df()

        self.assertIn('GROUP_KEY', grouping_df.columns)
        self.assertEqual(len(grouping_df), 2)
        self.assertNotEqual(grouping_df['GROUP_KEY'].iloc[0], grouping_df['GROUP_KEY'].iloc[1])

    def test_resolve_group_merge_keys_prefers_group_key_then_report_id(self):
        header_with_group_key = pd.DataFrame({'GROUP_KEY': ['abc'], 'REFERENCE': ['R1']})
        grouping_with_group_key = pd.DataFrame({'GROUP_KEY': ['abc'], 'GROUP': ['G1']})
        self.assertEqual(ExportDataThread._resolve_group_merge_keys(header_with_group_key, grouping_with_group_key), ['GROUP_KEY'])

        header_with_id = pd.DataFrame({'REPORT_ID': [1], 'REFERENCE': ['R1'], 'SAMPLE_NUMBER': ['1']})
        grouping_with_id = pd.DataFrame({'REPORT_ID': [1], 'GROUP': ['G1']})
        self.assertEqual(ExportDataThread._resolve_group_merge_keys(header_with_id, grouping_with_id), ['REPORT_ID'])


    def test_resolve_group_merge_keys_skips_blank_group_key_and_uses_report_id(self):
        header_group = pd.DataFrame({'GROUP_KEY': [''], 'REPORT_ID': [10], 'REFERENCE': ['R1'], 'SAMPLE_NUMBER': ['1']})
        grouping_df = pd.DataFrame({'GROUP_KEY': [''], 'REPORT_ID': [10], 'GROUP': ['A']})

        keys = ExportDataThread._resolve_group_merge_keys(header_group, grouping_df)

        self.assertEqual(keys, ['REPORT_ID'])

    def test_resolve_group_merge_keys_skips_blank_report_id_and_uses_composite(self):
        header_group = pd.DataFrame({
            'REPORT_ID': [np.nan],
            'REFERENCE': ['R1'],
            'FILELOC': ['/a'],
            'FILENAME': ['one.pdf'],
            'DATE': ['2024-01-01'],
            'SAMPLE_NUMBER': ['1'],
        })
        grouping_df = pd.DataFrame({
            'REPORT_ID': [None],
            'REFERENCE': ['R1'],
            'FILELOC': ['/a'],
            'FILENAME': ['one.pdf'],
            'DATE': ['2024-01-01'],
            'SAMPLE_NUMBER': ['1'],
            'GROUP': ['A'],
        })

        keys = ExportDataThread._resolve_group_merge_keys(header_group, grouping_df)

        self.assertEqual(keys, ['REFERENCE', 'FILELOC', 'FILENAME', 'DATE', 'SAMPLE_NUMBER'])

    def test_build_violin_payload_drops_nan_and_empty_groups(self):
        header_group = pd.DataFrame(
            {
                'GROUP': ['A', 'A', 'B', 'C'],
                'MEAS': [1.0, float('nan'), float('nan'), 2.0],
            }
        )

        labels, values, can_render = ExportDataThread._build_violin_payload(
            header_group,
            'GROUP',
            min_samplesize=1,
        )

        self.assertEqual(labels, ['A', 'C'])
        self.assertEqual(values, [[1.0], [2.0]])
        self.assertTrue(can_render)


    def test_build_violin_payload_preserves_input_group_order(self):
        header_group = pd.DataFrame(
            {
                'GROUP': ['B', 'A', 'B', 'A'],
                'MEAS': [1.0, 2.0, 1.1, 2.1],
            }
        )

        labels, values, can_render = ExportDataThread._build_violin_payload(
            header_group,
            'GROUP',
            min_samplesize=1,
        )

        self.assertEqual(labels, ['B', 'A'])
        self.assertEqual(values, [[1.0, 1.1], [2.0, 2.1]])
        self.assertTrue(can_render)

    def test_build_violin_payload_honors_minimum_sample_size(self):
        header_group = pd.DataFrame(
            {
                'SAMPLE_NUMBER': ['1', '1', '2'],
                'MEAS': [1.0, 1.1, 0.9],
            }
        )

        labels, values, can_render = ExportDataThread._build_violin_payload(
            header_group,
            'SAMPLE_NUMBER',
            min_samplesize=2,
        )

        self.assertEqual(labels, ['1', '2'])
        self.assertEqual(values, [[1.0, 1.1], [0.9]])
        self.assertFalse(can_render)
    def test_apply_group_assignments_keeps_latest_duplicate_assignment(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions()))
        header_group = pd.DataFrame(
            {
                'REFERENCE': ['R1'],
                'FILELOC': ['/a'],
                'FILENAME': ['one.pdf'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'MEAS': [1.0],
            }
        )
        grouping_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1'],
                'FILELOC': ['/a', '/a'],
                'FILENAME': ['one.pdf', 'one.pdf'],
                'DATE': ['2024-01-01', '2024-01-01'],
                'SAMPLE_NUMBER': ['1', '1'],
                'GROUP': ['OLD_GROUP', 'NEW_GROUP'],
            }
        )
        grouping_df = thread._add_group_key(grouping_df)

        with patch('modules.ExportDataThread.logging.warning') as warning_mock:
            merged, applied = thread._apply_group_assignments(header_group, grouping_df)

        self.assertTrue(applied)
        self.assertEqual(merged['GROUP'].tolist(), ['NEW_GROUP'])
        warning_mock.assert_called_once()

    def test_apply_group_assignments_with_report_id_preserves_sample_number_column(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions()))
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'SAMPLE_NUMBER': ['7'],
                'MEAS': [1.0],
            }
        )
        grouping_df = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'SAMPLE_NUMBER': ['999'],
                'GROUP': ['A'],
            }
        )

        merged, applied = thread._apply_group_assignments(header_group, grouping_df)

        self.assertTrue(applied)
        self.assertIn('SAMPLE_NUMBER', merged.columns)
        self.assertNotIn('SAMPLE_NUMBER_x', merged.columns)
        self.assertNotIn('SAMPLE_NUMBER_y', merged.columns)
        self.assertEqual(merged['SAMPLE_NUMBER'].tolist(), ['7'])


if __name__ == '__main__':
    unittest.main()

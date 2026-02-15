import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd


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


class TestExportSortingAndGrouping(unittest.TestCase):
    def test_sort_by_sample_number_uses_numeric_order(self):
        thread = ExportDataThread(db_file=':memory:', excel_file='dummy.xlsx', selected_sorting_parameter='Part number')
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
        thread = ExportDataThread(db_file=':memory:', excel_file='dummy.xlsx', selected_sorting_parameter='Date')
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
        thread = ExportDataThread(db_file=':memory:', excel_file='dummy.xlsx')
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

    def test_apply_group_assignments_keeps_latest_duplicate_assignment(self):
        thread = ExportDataThread(db_file=':memory:', excel_file='dummy.xlsx')
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


if __name__ == '__main__':
    unittest.main()

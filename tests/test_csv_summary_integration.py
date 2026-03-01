import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path

import pandas as pd

# Minimal Qt stubs so CSVSummaryDialog can be imported in headless CI.
qtcore_stub = types.ModuleType('PyQt6.QtCore')


class _DummyQThread:
    def __init__(self, *args, **kwargs):
        pass


class _DummySignal:
    def emit(self, *args, **kwargs):
        return None


def _dummy_pyqt_signal(*args, **kwargs):
    return _DummySignal()


qtcore_stub.Qt = object()
qtcore_stub.pyqtSlot = lambda *args, **kwargs: (lambda f: f)
qtcore_stub.QThread = _DummyQThread
qtcore_stub.pyqtSignal = _dummy_pyqt_signal
qtcore_stub.QTemporaryFile = type('QTemporaryFile', (), {})
qtcore_stub.QSize = type('QSize', (), {})
sys.modules['PyQt6.QtCore'] = qtcore_stub

qtgui_stub = types.ModuleType('PyQt6.QtGui')
qtgui_stub.QMovie = type('QMovie', (), {})
sys.modules['PyQt6.QtGui'] = qtgui_stub

qtwidgets_stub = types.ModuleType('PyQt6.QtWidgets')
for name in [
    'QDialog',
    'QVBoxLayout',
    'QPushButton',
    'QFileDialog',
    'QListWidget',
    'QMessageBox',
    'QHBoxLayout',
    'QProgressBar',
    'QLabel',
    'QTableWidget',
    'QTableWidgetItem',
    'QHeaderView',
    'QCheckBox',
]:
    setattr(qtwidgets_stub, name, type(name, (), {}))
sys.modules['PyQt6.QtWidgets'] = qtwidgets_stub

from modules.CSVSummaryDialog import DataProcessingThread  # noqa: E402
from modules.csv_summary_utils import build_default_plot_toggles  # noqa: E402


class CsvSummaryIntegrationTests(unittest.TestCase):
    def test_eta_format_includes_minutes_seconds_and_hours(self):
        self.assertEqual(DataProcessingThread._format_eta(None), 'ETA --')
        self.assertEqual(DataProcessingThread._format_eta(59.4), 'ETA 0:59')
        self.assertEqual(DataProcessingThread._format_eta(61.2), 'ETA 1:01')
        self.assertEqual(DataProcessingThread._format_eta(3661.0), 'ETA 1:01:01')

    def test_eta_estimation_uses_processed_columns(self):
        original_perf_counter = DataProcessingThread._estimate_eta_seconds.__globals__['time'].perf_counter
        try:
            DataProcessingThread._estimate_eta_seconds.__globals__['time'].perf_counter = lambda: 25.0
            estimate = DataProcessingThread._estimate_eta_seconds(
                DataProcessingThread,
                start_time=5.0,
                processed_columns=2,
                total_columns=5,
            )
        finally:
            DataProcessingThread._estimate_eta_seconds.__globals__['time'].perf_counter = original_perf_counter

        self.assertEqual(estimate, 30.0)

    def test_csv_summary_export_contains_overview_and_detail_sheet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'summary.xlsx'
            df = pd.DataFrame({'PART': ['A', 'B', 'C'], 'LENGTH': [10.0, 10.1, 10.2]})

            worker = DataProcessingThread(
                selected_indexes=['PART'],
                selected_data_columns=['LENGTH'],
                input_file='input.csv',
                output_file=str(output_file),
                data_frame=df,
                csv_config={'delimiter': ',', 'decimal': '.'},
                column_spec_limits={'LENGTH': {'nom': 10.0, 'usl': 0.5, 'lsl': -0.5}},
                plot_toggles=build_default_plot_toggles(['LENGTH'], full_report=False),
            )
            worker.run()

            self.assertTrue(output_file.exists())
            with zipfile.ZipFile(output_file, 'r') as workbook_zip:
                workbook_xml = workbook_zip.read('xl/workbook.xml').decode('utf-8')

            self.assertIn('CSV_SUMMARY', workbook_xml)
            self.assertIn('LENGTH', workbook_xml)





    def test_csv_summary_boxplot_chart_uses_box_whisker_emulation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'boxplot.xlsx'
            df = pd.DataFrame({'PART': ['A', 'B', 'C', 'D', 'E'], 'LENGTH': [9.8, 10.0, 10.1, 10.2, 10.4]})

            worker = DataProcessingThread(
                selected_indexes=['PART'],
                selected_data_columns=['LENGTH'],
                input_file='input.csv',
                output_file=str(output_file),
                data_frame=df,
                plot_toggles={'LENGTH': {'histogram': False, 'boxplot': True}},
            )
            worker.run()

            self.assertTrue(output_file.exists())
            with zipfile.ZipFile(output_file, 'r') as workbook_zip:
                chart_files = sorted(name for name in workbook_zip.namelist() if name.startswith('xl/charts/chart'))
                chart_payloads = [workbook_zip.read(name).decode('utf-8') for name in chart_files]

            self.assertTrue(any('<c:barChart>' in payload for payload in chart_payloads))
            self.assertTrue(any('<c:errBars>' in payload for payload in chart_payloads))
            self.assertTrue(any('interquartile range' in payload for payload in chart_payloads))
            self.assertTrue(any('boxplot</a:t>' in payload for payload in chart_payloads))
            self.assertTrue(all('boxplot profile' not in payload for payload in chart_payloads))

    def test_csv_summary_canceled_run_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'canceled.xlsx'
            df = pd.DataFrame({'PART': ['A', 'B', 'C'], 'LENGTH': [10.0, 10.1, 10.2]})

            worker = DataProcessingThread(
                selected_indexes=['PART'],
                selected_data_columns=['LENGTH'],
                input_file='input.csv',
                output_file=str(output_file),
                data_frame=df,
            )
            worker.cancel()
            worker.run()

            self.assertFalse(output_file.exists())

    def test_csv_summary_summary_only_mode_skips_detail_sheets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'summary_only.xlsx'
            df = pd.DataFrame({'PART': ['A', 'B', 'C'], 'LENGTH': [10.0, 10.1, 10.2]})

            worker = DataProcessingThread(
                selected_indexes=['PART'],
                selected_data_columns=['LENGTH'],
                input_file='input.csv',
                output_file=str(output_file),
                data_frame=df,
                summary_only=True,
            )
            worker.run()

            self.assertTrue(output_file.exists())
            with zipfile.ZipFile(output_file, 'r') as workbook_zip:
                workbook_xml = workbook_zip.read('xl/workbook.xml').decode('utf-8')

            self.assertIn('CSV_SUMMARY', workbook_xml)
            self.assertNotIn('LENGTH', workbook_xml)

if __name__ == '__main__':
    unittest.main()

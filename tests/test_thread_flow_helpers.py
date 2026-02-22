import sys
import types
import unittest


# Stubs for Qt and logger
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


cmm_parser_stub = types.ModuleType('modules.CMMReportParser')


class _DummyCmmReportParser:
    def __init__(self, *args, **kwargs):
        pass


cmm_parser_stub.CMMReportParser = _DummyCmmReportParser
sys.modules['modules.CMMReportParser'] = cmm_parser_stub
from modules.ExportDataThread import build_export_dataframe, execute_export_query, run_export_steps
from modules.ParseReportsThread import build_report_fingerprints_from_rows, parse_new_reports


class TestParseHelpers(unittest.TestCase):
    def test_build_report_fingerprints_stops_on_cancel(self):
        rows = [
            (1, 'R1', '/a', 'one.pdf', '2024-01-01', '1'),
            (2, 'R2', '/b', 'two.pdf', '2024-01-02', '2'),
        ]
        calls = {'count': 0}

        def should_cancel():
            calls['count'] += 1
            return calls['count'] > 1

        fingerprints = build_report_fingerprints_from_rows(rows, should_cancel=should_cancel)
        self.assertEqual(len(fingerprints), 1)


    def test_build_report_fingerprints_matches_id_and_composite_behavior(self):
        rows = [
            (5, 'R1', '/a', 'one.pdf', '2024-01-01', '1'),
            (None, 'R2', '/b', 'two.pdf', '2024-01-02', '2'),
        ]

        fingerprints = build_report_fingerprints_from_rows(rows)

        self.assertIn('id:5', fingerprints)
        self.assertIn('R2|/b|two.pdf|2024-01-02|2', fingerprints)

    def test_parse_new_reports_skips_existing_and_honors_cancel(self):
        class DummyParser:
            def __init__(self, report):
                self.FILE_PATH = str(report)
                self.pdf_reference = 'R'
                self.pdf_file_path = '/tmp'
                self.pdf_file_name = str(report)
                self.pdf_date = '2024-01-01'
                self.pdf_sample_number = '1'

        persisted = []
        existing = set()
        reports = ['a.pdf', 'b.pdf', 'c.pdf']
        calls = {'count': 0}

        def should_cancel():
            calls['count'] += 1
            return calls['count'] > 2

        progress_updates = []

        result = parse_new_reports(
            reports,
            existing,
            parser_factory=DummyParser,
            persist_report=lambda parser: persisted.append(parser.FILE_PATH),
            should_cancel=should_cancel,
            on_progress=lambda parsed, total: progress_updates.append((parsed, total)),
        )

        self.assertEqual(result.total_files, 3)
        self.assertEqual(result.parsed_files, 2)
        self.assertEqual(persisted, ['a.pdf', 'b.pdf'])
        self.assertEqual(progress_updates, [(1, 3), (2, 3)])


class TestExportHelpers(unittest.TestCase):
    def test_build_export_dataframe_maps_columns(self):
        df = build_export_dataframe([(1, 'A')], ['ID', 'NAME'])
        self.assertEqual(list(df.columns), ['ID', 'NAME'])
        self.assertEqual(df.iloc[0]['NAME'], 'A')

    def test_run_export_steps_stops_when_canceled(self):
        order = []

        def step1():
            order.append('step1')

        def step2():
            order.append('step2')

        checks = {'count': 0}

        def should_cancel():
            checks['count'] += 1
            return checks['count'] > 1

        completed = run_export_steps([step1, step2], should_cancel=should_cancel)
        self.assertFalse(completed)
        self.assertEqual(order, ['step1'])

    def test_execute_export_query_propagates_reader_errors(self):
        def failing_reader(*_):
            raise RuntimeError('db unavailable')

        with self.assertRaises(RuntimeError):
            execute_export_query(':memory:', 'SELECT 1', select_reader=failing_reader)


if __name__ == '__main__':
    unittest.main()

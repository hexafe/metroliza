import os
import sys
import tempfile
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
from modules.ExportDataThread import (  # noqa: E402
    ExportDataThread,
    build_export_dataframe,
    execute_export_query,
    run_export_steps,
)
from modules.export_backends import ExcelExportBackend  # noqa: E402
from modules.ParseReportsThread import build_report_fingerprints_from_rows, parse_new_reports  # noqa: E402


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


    def test_get_list_of_reports_supports_zip_source(self):
        import zipfile

        from modules.ParseReportsThread import ParseReportsThread
        from modules.contracts import ParseRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, 'reports.zip')
            with zipfile.ZipFile(zip_path, 'w') as archive:
                archive.writestr('nested/one.pdf', b'pdf content')
                archive.writestr('nested/skip.txt', b'not a pdf')

            thread = ParseReportsThread(ParseRequest(source_directory=zip_path, db_file='test.db'))
            reports = thread.get_list_of_reports()

            self.assertEqual(len(reports), 1)
            self.assertTrue(str(reports[0]).lower().endswith('one.pdf'))

            # Explicit cleanup here because this test does not call run().
            thread._extracted_archive_dir.cleanup()
            thread._extracted_archive_dir = None


    def test_get_list_of_reports_supports_tar_source(self):
        import tarfile

        from modules.ParseReportsThread import ParseReportsThread
        from modules.contracts import ParseRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            tar_path = os.path.join(tmpdir, 'reports.tar')
            pdf_path = os.path.join(tmpdir, 'one.pdf')
            txt_path = os.path.join(tmpdir, 'skip.txt')
            with open(pdf_path, 'wb') as pdf_file:
                pdf_file.write(b'pdf content')
            with open(txt_path, 'wb') as txt_file:
                txt_file.write(b'not a pdf')

            with tarfile.open(tar_path, 'w') as archive:
                archive.add(pdf_path, arcname='nested/one.pdf')
                archive.add(txt_path, arcname='nested/skip.txt')

            thread = ParseReportsThread(ParseRequest(source_directory=tar_path, db_file='test.db'))
            reports = thread.get_list_of_reports()

            self.assertEqual(len(reports), 1)
            self.assertTrue(str(reports[0]).lower().endswith('one.pdf'))

            thread._extracted_archive_dir.cleanup()
            thread._extracted_archive_dir = None

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


class TestExportBackendSmoke(unittest.TestCase):
    def test_default_export_target_uses_excel_backend(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(),
            )
            thread = ExportDataThread(request)

            self.assertEqual(thread.export_target, 'excel_xlsx')
            self.assertIsInstance(thread.get_export_backend(), ExcelExportBackend)


    def test_google_drive_target_reuses_excel_backend_until_upload_phase(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)

            self.assertEqual(thread.export_target, 'google_sheets_drive_convert')
            self.assertEqual(thread.backend_target, 'google')
            self.assertIsInstance(thread.get_export_backend(), ExcelExportBackend)

    def test_backend_target_metadata_defaults_to_excel(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(),
            )
            thread = ExportDataThread(request)

            self.assertEqual(thread.backend_target, 'excel')

    def test_excel_backend_preserves_existing_export_flow(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        calls = []

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(),
            )
            thread = ExportDataThread(request)

            def fake_export_filtered_data(excel_writer):
                self.assertIsNotNone(excel_writer)
                calls.append('filtered')

            def fake_add_measurements(excel_writer):
                self.assertIsNotNone(excel_writer)
                calls.append('measurements')

            thread.export_filtered_data = fake_export_filtered_data
            thread.add_measurements_horizontal_sheet = fake_add_measurements

            completed = thread.get_export_backend().run(thread)

            self.assertTrue(completed)
            self.assertEqual(calls, ['filtered', 'measurements'])
            self.assertTrue(os.path.exists(out_file))

if __name__ == '__main__':
    unittest.main()
